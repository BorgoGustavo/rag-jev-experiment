"""Árvore PageIndex (VectifyAI, modo flash) a partir do PDF da lei.

Uso documentado do PageIndex: page_index_flash(pdf, summary=..., summary_model=..., optimize=...).
A estrutura vem dos bookmarks/layout do PDF (sem LLM); o LLM escreve os resumos e faz o "expand".
Todas as chamadas passam por litellm.completion/acompletion, embrulhadas aqui para registrar o
usage devolvido pela API em logs/calls.jsonl (stage=tree, custo único).

  python src/gerar_arvore.py --sem-llm   # só estrutura -> data/index/arvore_sem_resumos.json (grátis)
  python src/gerar_arvore.py             # resumos + expand -> data/index/arvore.json (cache: não regenera)
  python src/gerar_arvore.py --force     # regenera mesmo com cache

Anotação: cada artigo/anexo de artigos.json pertence a EXATAMENTE UMA folha, pela posição do
início da folha no texto (não pela página inteira). Relatório em data/index/arvore_relatorio.md.
"""

import argparse
import bisect
import json
import random
import re
import statistics
import time
from pathlib import Path

import litellm
import pypdfium2 as pdfium
from pageindex.flash import page_index_flash

from llm_client import CONFIG, SESSION_RECORDS, _log

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "data/raw/lcp214_compilado.pdf"
ARTS = json.loads((ROOT / "data/processed/artigos.json").read_text())
PERGUNTAS = json.loads((ROOT / "data/eval/perguntas.json").read_text())
SEM_RESUMOS = ROOT / "data/index/arvore_sem_resumos.json"
COM_RESUMOS = ROOT / "data/index/arvore.json"
RELATORIO = ROOT / "data/index/arvore_relatorio.md"
MODEL_KEY = "pageindex_index"
CAPUT_RE = re.compile(r"^(Art\.\s*(\d+)(?:º|°)?\s*(-[A-Z])?|ANEXO\s+([IVXLC]+))\b", re.M)
CABECALHO_RE = re.compile(r"(LIVRO|TÍTULO|CAPÍTULO|Seção|Subseção|ANEXO|LEI COMPLEMENTAR|Arts?\. )")   # Arts. X a Y: subtítulos sintéticos


def registrar_custo():
    """Embrulha litellm: cada chamada do PageIndex vira uma linha do calls.jsonl com o usage da API."""
    orig, aorig = litellm.completion, litellm.acompletion

    def completion(*a, **kw):
        t0 = time.perf_counter()
        r = orig(*a, **kw)
        _log(MODEL_KEY, r.usage.prompt_tokens, r.usage.completion_tokens, t0, None, None, "tree")
        return r

    async def acompletion(*a, **kw):
        t0 = time.perf_counter()
        r = await aorig(*a, **kw)
        _log(MODEL_KEY, r.usage.prompt_tokens, r.usage.completion_tokens, t0, None, None, "tree")
        return r

    litellm.completion, litellm.acompletion = completion, acompletion


# ---------- anotação nó -> artigos ----------

def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def paginas() -> list[str]:
    doc = pdfium.PdfDocument(PDF)
    return [doc[n].get_textpage().get_text_range() for n in range(len(doc))]


def posicao_dos_artigos(pags: list[str]) -> dict[str, tuple[int, int]]:
    """id -> (página 0-based, offset no texto da página sem espaços) do caput."""
    pos = {}
    for p, texto in enumerate(pags):
        for m in CAPUT_RE.finditer(texto):
            aid = f"art_{m.group(2)}{(m.group(3) or '').replace('-', '').lower()}" if m.group(2) \
                else f"anexo_{m.group(4).lower()}"
            pos.setdefault(aid, (p, len(_norm(texto[:m.start()]))))
    return pos


def inicio_do_no(no: dict, pags: list[str]) -> tuple[int, int]:
    """Onde o nó começa de fato: posição do seu título na página inicial (0 se não achar)."""
    p = no["start_index"] - 1
    titulo = _norm(re.sub(r"\s*\(intro\)$", "", no["title"]))[:30]
    i = _norm(pags[p]).find(titulo)
    return (p, max(i, 0))


def todos(nos, prof=1):
    for no in nos:
        yield no, prof
        yield from todos(no.get("nodes", []), prof + 1)


def folhas(nos):
    return [no for no, _ in todos(nos) if not no.get("nodes")]


def anotar(arvore: dict, pags: list[str]) -> dict:
    """Cada artigo vai para a última folha (em ordem do documento) que começa antes do seu caput.
    Nós internos recebem a união das folhas. Retorna o relatório de sobreposição."""
    fls = folhas(arvore["structure"])
    pos_art = posicao_dos_artigos(pags)
    # antes: por intervalo de páginas (o método antigo), só para medir
    por_pagina = {aid: [f["node_id"] for f in fls if f["start_index"] <= p + 1 <= f["end_index"]]
                  for aid, (p, _) in pos_art.items()}
    # depois: por posição
    inicios = sorted((inicio_do_no(f, pags), i) for i, f in enumerate(fls))
    chaves = [k for k, _ in inicios]
    for f in fls:
        f["artigos"] = []
    for aid, (p, off) in pos_art.items():
        i = bisect.bisect_right(chaves, (p, off)) - 1
        fls[inicios[max(i, 0)][1]]["artigos"].append(aid)
    ordem = {a["id"]: n for n, a in enumerate(ARTS)}
    for f in fls:
        f["artigos"].sort(key=ordem.get)
        f["ruido"] = not CABECALHO_RE.match(f["title"])   # alínea tomada por cabeçalho

    def subir(no):
        if no.get("nodes"):
            no["artigos"] = [a for c in no["nodes"] for a in subir(c)]
        return no["artigos"]
    for no in arvore["structure"]:
        subir(no)
    return {
        "artigos_em_mais_de_uma_folha_por_pagina": sum(len(v) > 1 for v in por_pagina.values()),
        "artigos_em_mais_de_uma_folha_por_posicao": sum(
            sum(aid in f["artigos"] for f in fls) > 1 for aid in pos_art),
        "artigos_sem_posicao_no_pdf": [a["id"] for a in ARTS if a["id"] not in pos_art],
    }


# ---------- relatório ----------

def tokens(s: str) -> int:   # tokenizer local: só estatística, nunca custo
    return litellm.token_counter(model="gpt-4o", text=s)


def relatorio(arvore: dict, sobreposicao: dict, pags: list[str]) -> str:
    por_id = {a["id"]: a for a in ARTS}
    nos = list(todos(arvore["structure"]))
    fls = folhas(arvore["structure"])
    cobertos = {a for f in fls for a in f["artigos"]}
    sem_no = [a["id"] for a in ARTS if a["id"] not in cobertos]
    ruido = [f for f in fls if f["ruido"]]
    ocultas = [f for f in fls if not f["artigos"]]
    arts_ruido = {a for f in ruido for a in f["artigos"]}
    perguntas_ruido = [q["id"] for q in PERGUNTAS if set(q["artigos_gabarito"]) & arts_ruido]
    tam = sorted(((tokens("\n\n".join(por_id[a]["text"] for a in f["artigos"])), f) for f in fls), key=lambda x: -x[0])
    ts = [t for t, _ in tam]
    custo = sum(r["cost_usd"] for r in SESSION_RECORDS if r["stage"] == "tree")
    com_resumo = [no for no, _ in nos if no.get("summary")]

    L = [f"# Árvore PageIndex (flash) da LC 214/2025\n",
         f"- PDF: {PDF.name}, {len(pags)} páginas; origem da estrutura: `{arvore.get('toc_source')}`"
         + (f"; optimize: {arvore['optimize']['merges']} merges, {arvore['optimize']['expands']} expands" if "optimize" in arvore else ""),
         f"- Nós: {len(nos)} ({len(fls)} folhas); profundidade máxima: {max(p for _, p in nos)}; maior fan-out: {max(len(no.get('nodes', [])) for no, _ in nos)}",
         f"- Nós com resumo: {len(com_resumo)}",
         f"- Custo desta geração (usage da API, stage=tree): US$ {custo:.4f} em {sum(r['stage'] == 'tree' for r in SESSION_RECORDS)} chamadas",
         "\n## Cobertura e sobreposição\n",
         f"- Artigos/anexos em artigos.json: {len(ARTS)}; sem posição no PDF: {sobreposicao['artigos_sem_posicao_no_pdf']}",
         f"- Sem folha correspondente: {len(sem_no)} {sem_no[:20]}",
         f"- Artigos em mais de uma folha, atribuição por página inteira (método antigo): {sobreposicao['artigos_em_mais_de_uma_folha_por_pagina']}",
         f"- Artigos em mais de uma folha, atribuição por posição do início do nó (atual): {sobreposicao['artigos_em_mais_de_uma_folha_por_posicao']}",
         "\n## Folhas-ruído (título que não é cabeçalho da lei)\n",
         f"- {len(ruido)} folhas-ruído, cobrindo {len(arts_ruido)} artigos",
         f"- Perguntas com artigo gabarito em folha-ruído: {len(perguntas_ruido)} {perguntas_ruido}",
         f"- Folhas com 0 artigos, ocultadas ao navegador: {len(ocultas)} de {len(fls)}",
         "\n## Tamanho das folhas (tokens, tokenizer local, só estatística)\n",
         f"- mín {min(ts)}, mediana {int(statistics.median(ts))}, média {int(statistics.mean(ts))}, máx {max(ts)}",
         f"- folhas > 2.000: {sum(t > 2000 for t in ts)}; > 4.000: {sum(t > 4000 for t in ts)}; > 8.000: {sum(t > 8000 for t in ts)}; com 0 artigos: {sum(not f['artigos'] for f in fls)}",
         "- 5 maiores:"]
    for t, f in tam[:5]:
        L.append(f"  - {t} tok | {f['title'][:60]} | p. {f['start_index']}-{f['end_index']} | {len(f['artigos'])} artigos"
                 + (f" ({f['artigos'][0]}..{f['artigos'][-1]})" if f["artigos"] else ""))
    if com_resumo:
        L.append("\n## 5 resumos sorteados\n")
        for no in random.sample(com_resumo, 5):
            L.append(f"- **{no['title'][:70]}** (p. {no['start_index']}-{no['end_index']}, {len(no['artigos'])} artigos): {no['summary']}")
    L += ["\n## Dois primeiros níveis\n", "```"]
    for no in arvore["structure"]:
        L.append(f"{no['title'][:80]}  [p. {no['start_index']}-{no['end_index']}, {len(no['artigos'])} artigos, {len(no.get('nodes', []))} filhos]")
        for c in no.get("nodes", []):
            L.append(f"    {c['title'][:76]}  [p. {c['start_index']}-{c['end_index']}, {len(c['artigos'])} artigos, {len(c.get('nodes', []))} filhos]")
    L.append("```")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sem-llm", action="store_true", help="só estrutura, sem resumos nem expand (grátis)")
    ap.add_argument("--force", action="store_true", help="regenera a árvore com resumos mesmo se já existir")
    args = ap.parse_args()
    saida = SEM_RESUMOS if args.sem_llm else COM_RESUMOS

    if saida.exists() and not args.force and not args.sem_llm:
        print(f"cache: {saida.relative_to(ROOT)} já existe (use --force para regenerar); só reanotando")
        arvore = json.loads(saida.read_text())
    else:
        registrar_custo()
        modelo = CONFIG["models"][MODEL_KEY]["id"]
        t0 = time.perf_counter()
        arvore = page_index_flash(
            PDF, summary=not args.sem_llm, summary_model=modelo,
            optimize=False if args.sem_llm else "full", optimize_model=modelo,
        )
        print(f"page_index_flash: {time.perf_counter() - t0:.0f}s, origem {arvore.get('toc_source')}")

    pags = paginas()
    sobreposicao = anotar(arvore, pags)
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps(arvore, ensure_ascii=False, indent=1))
    rel = relatorio(arvore, sobreposicao, pags)
    RELATORIO.write_text(rel)
    print(rel.split("## Dois primeiros níveis")[0])
    print(f"árvore em {saida.relative_to(ROOT)}; relatório completo em {RELATORIO.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
