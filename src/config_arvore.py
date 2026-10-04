"""Configurações B, C (e D, quando o Jev for plugado): busca na árvore PageIndex + resposta.

Busca em profundidade guiada pelo navegador, com limite navigate.max_steps:
  pilha = [raiz]; a cada passo tira um nó; se é folha, lê (texto = artigos que ele cobre);
  senão pergunta ao navegador: "descer" empilha os filhos escolhidos, "suficiente" encerra,
  "voltar" descarta o nó. A resposta final usa o MESMO gerador e o MESMO prompt da config A.

  python src/config_arvore.py --config B --estimate
  python src/config_arvore.py --config B --limit 3
  python src/config_arvore.py --config C
"""

import argparse
import json
import time
from pathlib import Path

from llm_client import CONFIG, SESSION_RECORDS, call_llm, cost_usd
from navegadores.jev import NavegadorJev
from navegadores.llm import NavegadorLLM
from perguntas import PERGUNTAS, amostra, gabarito_em_folha_ruido
from prompts import ANSWER_SYSTEM, ANSWER_USER, formatar_contexto

ROOT = Path(__file__).resolve().parent.parent
ARTS = {a["id"]: a for a in json.loads((ROOT / "data/processed/artigos.json").read_text())}
ARVORES = {"pageindex": ROOT / "data/index/arvore.json",              # resumos do PageIndex (gpt-5.6-luna, por página)
           "md": ROOT / "data/index/arvore_pageindex_md.json",       # PageIndex modo markdown: resumos por nó
           "agente": ROOT / "data/index/arvore_resumo_por_no.json"}   # resumos escritos pelo agente (variante explorada, fora das rodadas)
ARVORE = RAIZ = None


def carregar_arvore(nome: str):
    global ARVORE, RAIZ
    ARVORE = json.loads(ARVORES[nome].read_text())
    RAIZ = {"node_id": "raiz", "title": "Lei Complementar 214/2025", "nodes": ARVORE["structure"],
            "artigos": [a for n in ARVORE["structure"] for a in n["artigos"]]}
    return RAIZ


carregar_arvore("pageindex")
NAVEGADORES = {"B": lambda: NavegadorLLM("navegador_grande", "B"),
               "C": lambda: NavegadorLLM("navegador_pequeno", "C"),
               "D": lambda: NavegadorJev("D")}
MAX_STEPS = CONFIG["navigate"]["max_steps"]


def texto_do_no(no: dict) -> str:
    return "\n\n".join(ARTS[i]["text"] for i in no["artigos"])


def buscar(navegador, pergunta: str) -> tuple[list[dict], list[dict], str]:
    """Retorna (nós lidos, caminho, término). caminho: um registro por passo.
    término: suficiente | suficiente_escalado | max_steps | esgotado (pilha vazia)."""
    pilha, lidos, caminho = [RAIZ], [], []
    while pilha and len(caminho) < MAX_STEPS:
        no = pilha.pop()
        filhos = [f for f in no.get("nodes", []) if f["artigos"]]   # folhas com 0 artigos ficam invisíveis
        if not no["artigos"]:                            # nó vazio (só folhas ocultas): nada a ler
            caminho.append({"no": no["title"], "acao": "vazio"})
            continue
        if not filhos:                                   # folha: lê
            lidos.append(no)
            caminho.append({"no": no["title"], "acao": "ler"})
            continue
        d = navegador.escolher(pergunta, no, filhos, lidos)
        caminho.append({"no": no["title"], "acao": d.acao, "escolhidos": d.nos_escolhidos,
                        "confianca": round(d.confianca, 2), **d.info})
        if d.acao == "suficiente":
            break
        if d.acao == "descer":
            por_id = {f["node_id"]: f for f in filhos}
            pilha.extend(por_id[i] for i in reversed(d.nos_escolhidos))   # o 1º escolhido sai primeiro
    if caminho and caminho[-1]["acao"] == "suficiente":
        termino = "suficiente_escalado" if caminho[-1].get("escalado") else "suficiente"
    else:
        termino = "max_steps" if pilha else "esgotado"
    return lidos, caminho, termino


def _prompt_resposta(trechos: list[dict], pergunta: str) -> str:
    return ANSWER_USER.format(contexto=formatar_contexto(trechos) or "(nenhum trecho encontrado)", pergunta=pergunta)


def gerar_resposta(trechos: list[dict], q: dict, config: str) -> tuple[str, int]:
    """Chama o gerador (mesmo modelo e prompt de A). Retorna (resposta, tokens de entrada pelo usage da API)."""
    resposta = call_llm("gerador_resposta", ANSWER_SYSTEM, _prompt_resposta(trechos, q["pergunta"]),
                        CONFIG["answer"]["max_tokens"], stage="answer", config=config, question_id=q["id"])
    return resposta, SESSION_RECORDS[-1]["input_tokens"]


def estimar_contexto(trechos: list[dict], q: dict) -> int:
    """Só estatística (regra: custo real vem da API). Tokenizer local aproximado sobre o prompt que iria ao gerador."""
    import litellm
    return litellm.token_counter(model="gpt-4o", text=ANSWER_SYSTEM + _prompt_resposta(trechos, q["pergunta"]))


def responder(navegador, q: dict, config: str, arvore: str = "pageindex", com_resposta: bool = True) -> dict:
    t0 = time.perf_counter()
    navegador.question_id = q["id"]
    lidos, caminho, termino = buscar(navegador, q["pergunta"])
    trechos = [{"text": texto_do_no(n), "artigos": n["artigos"]} for n in lidos if n["artigos"]]
    recuperados = list(dict.fromkeys(i for t in trechos for i in t["artigos"]))
    latencia_busca = round(time.perf_counter() - t0, 2)
    if com_resposta:
        resposta, tokens_contexto = gerar_resposta(trechos, q, config)
    else:
        resposta, tokens_contexto = None, estimar_contexto(trechos, q)
    gabarito = set(q["artigos_gabarito"])
    achados = gabarito & set(recuperados)
    meus = [r for r in SESSION_RECORDS if r["question_id"] == q["id"]]
    nav_por_provedor = {}
    for r in meus:
        if r["stage"] == "navigate":
            prov = CONFIG["models"][r["model_key"]]["provider"]
            nav_por_provedor[prov] = round(nav_por_provedor.get(prov, 0) + r["cost_usd"], 6)
    return {
        "id": q["id"], "tipo": q["tipo"], "dificuldade": q["dificuldade"], "arvore": arvore,
        "gabarito": q["artigos_gabarito"], "gabarito_em_folha_ruido": gabarito_em_folha_ruido(q),
        "recuperados": recuperados,
        "acerto_recuperacao": achados == gabarito,
        "cobertura": len(achados) / len(gabarito),
        "resposta": resposta,
        "tokens_contexto_gerador": tokens_contexto,            # usage da API; sem resposta: estimativa local
        "tokens_contexto_estimado": not com_resposta,
        "custo_gerador_estimado_usd": None if com_resposta else round(cost_usd("gerador_resposta", tokens_contexto, 200), 6),
        "custo_usd": sum(r["cost_usd"] for r in meus),
        "custo_navegacao_por_provedor": nav_por_provedor,
        "latencia_s": round(time.perf_counter() - t0, 2),
        "latencia_busca_s": latencia_busca,
        "caminho": caminho, "passos": len(caminho), "termino": termino,
        "erros": sum(p["acao"] == "erro" for p in caminho),          # saída truncada ou JSON ilegível (nunca vira "voltar" calado)
        "escalados": sum(p.get("escalado", False) for p in caminho),  # D: passos decididos pelo navegador_grande
        "nos_lidos": [n["node_id"] for n in lidos],
    }


def _nos_por_id(nos: list[dict], out: dict) -> dict:
    for n in nos:
        out[n["node_id"]] = n
        _nos_por_id(n.get("nodes", []), out)
    return out


def responder_arquivo(entrada: Path, config: str, saida: Path | None = None) -> Path:
    """Gera as respostas para uma rodada feita com --sem-resposta (navegação já gravada). Saída: results/<config>.jsonl ou --saida."""
    por_id = _nos_por_id(ARVORE["structure"], {})
    saida = saida or ROOT / f"results/{config}.jsonl"
    feitas = {json.loads(l)["id"] for l in saida.open()} if saida.exists() else set()
    qs = {q["id"]: q for q in PERGUNTAS}
    with saida.open("a") as f:
        for linha in entrada.open():
            r = json.loads(linha)
            if r["id"] in feitas:
                continue
            trechos = [{"text": texto_do_no(por_id[i]), "artigos": por_id[i]["artigos"]} for i in r["nos_lidos"]]
            t0 = time.perf_counter()
            r["resposta"], r["tokens_contexto_gerador"] = gerar_resposta(trechos, qs[r["id"]], config)
            r["tokens_contexto_estimado"], r["custo_gerador_estimado_usd"] = False, None
            r["custo_usd"] += SESSION_RECORDS[-1]["cost_usd"]
            r["latencia_s"] = round(r["latencia_busca_s"] + time.perf_counter() - t0, 2)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{r['id']} resposta: {r['resposta'][:100]!r}")
    return saida


def estimar(config: str):
    model_key = {"B": "navegador_grande", "C": "navegador_pequeno"}[config]
    passos, tok_in, tok_out = 7, 1500, 60                 # profundidade típica 6 + 1 folha; filhos com resumo
    nav = passos * cost_usd(model_key, tok_in, tok_out)
    resp = cost_usd("gerador_resposta", 6000, 200)          # folhas cobrem vários artigos: contexto maior que em A
    print(f"{config}: ~{passos} passos x {CONFIG['models'][model_key]['id']} = US$ {nav:.4f} + resposta US$ {resp:.4f} "
          f"= ~US$ {nav + resp:.4f}/pergunta -> 40 perguntas ~US$ {40 * (nav + resp):.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", choices=list(NAVEGADORES), required=True)
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--arvore", choices=list(ARVORES), default="pageindex")
    ap.add_argument("--ids", nargs="+", help="só estas perguntas; grava em results/<config>_fumaca.jsonl")
    ap.add_argument("--limiar", type=float, help="D: limiar de escalonamento (0 = Jev puro); sufixo _limiarX no arquivo")
    ap.add_argument("--sem-resposta", action="store_true", help="só navegação; contexto do gerador estimado localmente")
    ap.add_argument("--responder-arquivo", type=Path, help="gera respostas de uma rodada --sem-resposta -> results/<config>.jsonl")
    ap.add_argument("--saida", type=Path, help="arquivo de saída do --responder-arquivo")
    args = ap.parse_args()
    if args.estimate:
        return estimar(args.config)

    carregar_arvore(args.arvore)
    if args.responder_arquivo:
        return print("respostas em", responder_arquivo(args.responder_arquivo, args.config, args.saida))
    navegador = NavegadorJev("D", args.limiar) if args.config == "D" and args.limiar is not None else NAVEGADORES[args.config]()
    perguntas = [q for q in PERGUNTAS if q["id"] in args.ids] if args.ids else amostra(args.limit)
    sufixo = ("" if args.arvore == "pageindex" else f"_{args.arvore}") + (f"_limiar{args.limiar:g}" if args.limiar is not None else "") + ("_fumaca" if args.ids else "")
    out = ROOT / f"results/{args.config}{sufixo}.jsonl"
    out.parent.mkdir(exist_ok=True)
    feitas = {json.loads(l)["id"] for l in out.open()} if out.exists() else set()
    resultados = []
    with out.open("a") as f:   # retoma de onde parou: pula ids já gravados
        for q in perguntas:
            if q["id"] in feitas:
                continue
            r = responder(navegador, q, args.config, args.arvore, com_resposta=not args.sem_resposta)
            resultados.append(r)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()   # grava de fato a cada pergunta (retomada após falha)
            print(f"\n{r['id']} acerto={r['acerto_recuperacao']} cobertura={r['cobertura']:.2f} "
                  f"passos={r['passos']} erros={r['erros']} escalados={r['escalados']} US$ {r['custo_usd']:.4f} {r['latencia_s']}s")
            for p in r["caminho"]:
                extra = f"  -> {p['escolhidos']} ({p['confianca']})" if p["acao"] == "descer" else (f"  {p.get('erro', '')}" if p["acao"] == "erro" else "")
                print(f"   {p['acao']:<11} {p['no'][:70]}{extra}")
            print(f"   término: {r['termino']}; resposta: {(r['resposta'] or '(sem resposta)')[:120]!r}")

    n = len(resultados)
    if not n:
        return print("nada a fazer: todas as perguntas já estavam gravadas")
    custo = sum(r["custo_usd"] for r in resultados)
    lat = sum(r["latencia_s"] for r in resultados)
    print(f"\n{n} perguntas: US$ {custo:.4f}, {lat:.0f}s, acerto de recuperação "
          f"{sum(r['acerto_recuperacao'] for r in resultados)}/{n}, passos médios {sum(r['passos'] for r in resultados) / n:.1f}, "
          f"erros {sum(r['erros'] for r in resultados)}, escalados {sum(r['escalados'] for r in resultados)}")
    por_provedor = {}
    for rec in SESSION_RECORDS:
        prov = CONFIG["models"][rec["model_key"]]["provider"]
        por_provedor[prov] = por_provedor.get(prov, 0) + rec["cost_usd"]
    print("custo por provedor: " + ", ".join(f"{p} US$ {c:.4f}" for p, c in por_provedor.items()))
    if n < len(PERGUNTAS):
        print(f"estimativa para 40: US$ {custo / n * 40:.2f}, ~{lat / n * 40 / 60:.1f} min")


if __name__ == "__main__":
    main()
