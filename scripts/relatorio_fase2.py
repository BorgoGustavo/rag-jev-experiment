"""Fase 2: tabela consolidada (A, B, C, variantes de D), detalhe das variantes de D, McNemar e gráfico.

  .venv/bin/python scripts/relatorio_fase2.py            # imprime tudo e grava results/custo_vs_acerto.png
"""
import json, statistics as st, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from mcnemar import mcnemar  # noqa: E402

TIPOS = {"direta": "direta", "referencia_cruzada": "cruzada", "vocabulario_diferente": "vocab."}
# variantes de D: arquivo com respostas (custo real); as rodadas só de recuperação ficam em D_limiar*.jsonl
ARQUIVOS = {"A": "A.jsonl", "B": "B.jsonl", "C": "C.jsonl",
            "D Jev puro": "D_limiar0_resp.jsonl", "D limiar 0,70": "D_limiar0.7_resp.jsonl", "D limiar 0,80": "D.jsonl"}
ROTULO = {"D Jev puro": "D Jev puro", "D limiar 0,70": "D 0,70", "D limiar 0,80": "D 0,80"}
AV = json.loads((ROOT / "data/eval/avaliacao_respostas.json").read_text())
AV_CHAVE = {"A": "A", "B": "B", "C": "C", "D Jev puro": "D_puro", "D limiar 0,70": "D_070", "D limiar 0,80": "D"}


def ler(nome):
    p = ROOT / "results" / nome
    return [json.loads(l) for l in p.open()] if p.exists() else []


def custo_por_pergunta(rs):
    """Custo real (API) por pergunta; rodadas --sem-resposta somam a estimativa do gerador (marcada com *)."""
    est = any(r.get("tokens_contexto_estimado") for r in rs)
    tot = sum(r["custo_usd"] + (r.get("custo_gerador_estimado_usd") or 0) for r in rs)
    return tot / len(rs), est


def acc(rs):
    return sum(r["acerto_recuperacao"] for r in rs), len(rs)


def respostas(nome):
    notas = AV.get(AV_CHAVE.get(nome), {})
    n = Counter(v[0] for v in notas.values())
    return f"{n['correta']} (+{n['parcial']}p)" if notas else "-"


def tabela(dados):
    print(f"{'config':<14} {'recup.':>7} {'direta':>7} {'cruz.':>7} {'vocab.':>7} {'resposta':>10} {'US$/q':>8} {'lat. med':>9} {'passos':>7} {'ctx tok':>8} {'escal.':>7}")
    for nome, rs in dados.items():
        a, n = acc(rs)
        por_tipo = " ".join(f"{acc([r for r in rs if r['tipo'] == t])[0]:>4}/{acc([r for r in rs if r['tipo'] == t])[1]:<2}" for t in TIPOS)
        custo, est = custo_por_pergunta(rs)
        esc = sum(r.get("escalados", 0) for r in rs)
        passos = sum(r.get("passos", 0) for r in rs)
        print(f"{nome:<14} {a:>4}/{n:<2} {por_tipo} {respostas(nome):>10} {custo:>7.4f}{'*' if est else ' '} {st.median(r['latencia_s'] for r in rs):>8.1f}s "
              f"{(passos / n if passos else 0):>7.1f} {st.mean(r['tokens_contexto_gerador'] for r in rs):>8.0f} "
              f"{(f'{esc / passos:.0%}' if passos and 'D' in nome else '-'):>7}")
    if any(custo_por_pergunta(rs)[1] for rs in dados.values()):
        print("* custo do gerador estimado localmente (rodada só de recuperação); demais: usage da API")


def detalhe_d(nome, rs):
    n = len(rs)
    passos_nav = [p for r in rs for p in r["caminho"] if p["acao"] in ("descer", "voltar", "suficiente", "erro")]
    esc = [p for p in passos_nav if p.get("escalado")]
    prov = Counter()
    for r in rs:
        for k, v in r["custo_navegacao_por_provedor"].items():
            prov[k] += v
    ctx = [r["tokens_contexto_gerador"] for r in rs]
    print(f"\n== {nome} ({n} perguntas)")
    print(f"  recuperação {acc(rs)[0]}/{n}: " + ", ".join(f"{TIPOS[t]} {acc([r for r in rs if r['tipo'] == t])[0]}/{acc([r for r in rs if r['tipo'] == t])[1]}" for t in TIPOS)
          + f" | cobertura média {st.mean(r['cobertura'] for r in rs):.2f}")
    print(f"  escalonamento: {len(esc)}/{len(passos_nav)} passos de decisão ({len(esc) / len(passos_nav):.0%}), "
          f"{sum(1 for r in rs if r['escalados'])}/{n} perguntas com algum passo escalado")
    print(f"  custo de navegação por provedor: " + ", ".join(f"{k} US$ {v:.4f}" for k, v in prov.items())
          + f" (total US$ {sum(prov.values()):.4f}, {sum(prov.values()) / n:.5f}/q)")
    print(f"  latência mediana da busca {st.median(r['latencia_busca_s'] for r in rs):.1f}s | passos médios {st.mean(r['passos'] for r in rs):.1f} "
          f"| folhas lidas médias {st.mean(len(r['nos_lidos']) for r in rs):.1f} | erros {sum(r['erros'] for r in rs)}")
    print(f"  contexto ao gerador: média {st.mean(ctx):.0f} tokens, mediana {st.median(ctx):.0f}"
          + (" (estimativa local)" if rs[0].get("tokens_contexto_estimado") else " (usage da API)"))
    print(f"  término das buscas: " + ", ".join(f"{k} {v}" for k, v in Counter(r["termino"] for r in rs).most_common()))
    conf = sorted(p.get("confianca_jev_passo", p["confianca"]) for p in passos_nav if "confianca_jev" in p)   # escalado: p do Jev, não do LLM
    if conf:
        q = lambda f: conf[int(f * (len(conf) - 1))]
        print(f"  confiança do Jev (p vencedora), {len(conf)} passos: min {conf[0]:.2f}, p25 {q(.25):.2f}, mediana {q(.5):.2f}, p75 {q(.75):.2f}, max {conf[-1]:.2f}"
              f" | seleção múltipla {sum(p.get('multipla', False) for p in passos_nav)}x | nenhum_destes/ja_lido_basta: "
              f"{sum(p['acao'] == 'voltar' and not p.get('escalado') for p in passos_nav)}/{sum(p['acao'] == 'suficiente' and not p.get('escalado') for p in passos_nav)}")


def grafico(dados):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6, 5.5), dpi=200)
    desloc = {"A": (0, 12), "B": (0, 12), "C": (0, -22), "D Jev puro": (0, -22), "D limiar 0,70": (-6, -22), "D limiar 0,80": (0, 12)}
    for nome, rs in dados.items():
        custo, est = custo_por_pergunta(rs)
        y = 100 * acc(rs)[0] / acc(rs)[1]
        ax.scatter(custo, y, s=150, zorder=3, marker="o" if not est else "s", edgecolor="black", linewidth=0.8)
        ax.annotate(ROTULO.get(nome, nome), (custo, y), textcoords="offset points", xytext=desloc.get(nome, (0, 12)),
                    ha="center", fontsize=12, fontweight="bold")
    ax.set_xscale("log")
    ax.set_xlabel("custo por pergunta (US$, escala log)", fontsize=13)
    ax.set_ylabel("acerto de recuperação (%)", fontsize=13)
    ax.set_ylim(50, 100)
    ax.tick_params(labelsize=12)
    ax.grid(True, which="both", alpha=0.3)
    ax.set_title("LC 214/2025, 40 perguntas, custo real por pergunta (API)", fontsize=11)
    fig.tight_layout()
    out = ROOT / "results/custo_vs_acerto.png"
    fig.savefig(out)
    print(f"\ngráfico em {out.relative_to(ROOT)}")


def main():
    dados = {k: v for k, v in ((k, ler(v)) for k, v in ARQUIVOS.items()) if v}
    tabela(dados)
    for nome, rs in dados.items():
        if nome.startswith("D"):
            detalhe_d(nome, rs)
    print("\nMcNemar (recuperação, pares discordantes, binomial exato):")
    pares = [("B", "A"), ("B", "C")] + [(d, o) for d in ("D Jev puro", "D limiar 0,70", "D limiar 0,80") for o in ("A", "C")] + [("D limiar 0,80", "B")]
    for a, b in pares:
        if a in dados and b in dados:
            x, y, p = mcnemar({r["id"]: r["acerto_recuperacao"] for r in dados[a]}, {r["id"]: r["acerto_recuperacao"] for r in dados[b]})
            print(f"  {a} vs {b}: só {a} {x} x só {b} {y}, p = {p:.3f}")
    grafico(dados)


if __name__ == "__main__":
    main()
