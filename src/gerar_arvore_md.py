"""Árvore PageIndex em modo Markdown (md_to_tree): resumos escritos pelo pipeline a partir do
texto do PRÓPRIO nó (não da página). Exceção autorizada à regra de economia de API (~US$ 0,08).

  python src/gerar_arvore_md.py           # gera data/index/arvore_pageindex_md.json (cache)
  python src/gerar_arvore_md.py --force

Markdown: um nível de cabeçalho por nível da lei (# Livro/Anexo, ## Título, ### Capítulo,
#### Seção, ##### Subseção), gerado dos mesmos blocos limpos do PDF (scripts/gerar_pdf.py).
Uso documentado: md_to_tree(md_path, if_add_node_summary='yes', summary_token_threshold=200,
model=...). Folhas com menos de 200 tokens recebem o próprio texto como resumo (comportamento
do PageIndex); nós internos recebem "prefix_summary" (texto antes do primeiro filho).
Artigos atribuídos pelo caput presente no texto do nó: cada artigo em exatamente um nó.
"""

import argparse
import asyncio
import html
import json
import random
import re
import statistics
import sys
import time
from pathlib import Path

from pageindex.page_index_md import md_to_tree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from gerar_arvore import ARTS, CAPUT_RE, MODEL_KEY, registrar_custo, tokens, todos, folhas  # noqa: E402
from gerar_pdf import blocos_para_html  # noqa: E402
from llm_client import CONFIG, SESSION_RECORDS  # noqa: E402
from parse import RAW, extract_blocks  # noqa: E402

MD = ROOT / "data/raw/lcp214_compilado.md"
OUT = ROOT / "data/index/arvore_pageindex_md.json"
RELATORIO = ROOT / "data/index/arvore_md_relatorio.md"
PDF_TREE = ROOT / "data/index/arvore.json"


def gerar_markdown() -> str:
    linhas = ["# LEI COMPLEMENTAR Nº 214, DE 16 DE JANEIRO DE 2025 (compilada)", ""]
    for bloco in blocos_para_html(extract_blocks(RAW.read_text(encoding="utf-8"))):
        m = re.match(r"<h(\d)>(.*)</h\d>$", bloco)
        if m:
            linhas += ["", "#" * int(m.group(1)) + " " + html.unescape(m.group(2)), ""]
        else:
            linhas += [html.unescape(bloco[3:-4]), ""]
    return "\n".join(linhas)


CAPUT_MD_RE = re.compile(r"^(?:#+\s*)?(Art\.\s*(\d+)(?:º|°)?\s*(-[A-Z])?|ANEXO\s+([IVXLC]+))\b", re.M)


def anotar(arvore: dict, md_lines: list[str]):
    """Texto próprio de cada nó = linhas entre o seu cabeçalho e o próximo cabeçalho (como o
    md_to_tree faz). Artigo -> nó cujo texto próprio contém o caput; cada artigo em um só nó.
    Nó interno com artigos no texto próprio ganha um filho "(intro)", como no modo flash.
    Nós internos recebem a união dos filhos."""
    ordem = {a["id"]: n for n, a in enumerate(ARTS)}
    nos = [no for no, _ in todos(arvore["structure"])]
    nos_ordem = sorted(nos, key=lambda n: n["line_num"])
    vistos = set()
    for i, no in enumerate(nos_ordem):
        fim = nos_ordem[i + 1]["line_num"] - 1 if i + 1 < len(nos_ordem) else len(md_lines)
        texto = "\n".join(md_lines[no["line_num"] - 1:fim])
        ids = []
        for m in CAPUT_MD_RE.finditer(texto):
            aid = f"art_{m.group(2)}{(m.group(3) or '').replace('-', '').lower()}" if m.group(2) \
                else f"anexo_{m.group(4).lower()}"
            if aid in ordem and aid not in vistos:
                ids.append(aid)
                vistos.add(aid)
        no["artigos"] = sorted(ids, key=ordem.get)
        no["ruido"] = False
        no.pop("text", None)
        if no.get("nodes") and ids:   # caput antes do primeiro filho: vira folha "(intro)"
            no["nodes"].insert(0, {"title": f"{no['title']} (intro)", "node_id": no["node_id"] + "i",
                                   "line_num": no["line_num"], "summary": no.get("prefix_summary", ""),
                                   "artigos": list(no["artigos"]), "ruido": False})

    def subir(no):
        if no.get("nodes"):
            no["artigos"] = [a for c in no["nodes"] for a in subir(c)]
            no["artigos"].sort(key=ordem.get)
        return no["artigos"]
    for no in arvore["structure"]:
        subir(no)


def relatorio(arvore: dict) -> str:
    por_id = {a["id"]: a for a in ARTS}
    nos = list(todos(arvore["structure"]))
    fls = folhas(arvore["structure"])
    cobertos = {a for f in fls for a in f["artigos"]}
    internos_com_art = [no for no, _ in nos if no.get("nodes") and
                        set(no["artigos"]) - {a for c in no["nodes"] for a in c["artigos"]}]
    sem_no = [a["id"] for a in ARTS if a["id"] not in cobertos]
    tam = sorted(((tokens("\n\n".join(por_id[a]["text"] for a in f["artigos"])), f) for f in fls), key=lambda x: -x[0])
    ts = [t for t, _ in tam]
    custo = sum(r["cost_usd"] for r in SESSION_RECORDS if r["stage"] == "tree")
    res = [no["summary"] for no, _ in nos if no.get("summary")]
    pref = [no["prefix_summary"] for no, _ in nos if no.get("prefix_summary")]
    pdf = json.loads(PDF_TREE.read_text())
    res_pdf = [no["summary"] for no, _ in todos(pdf["structure"]) if no.get("summary")]
    w = lambda xs: sorted(len(s.split()) for s in xs)
    L = ["# Árvore PageIndex (markdown) da LC 214/2025\n",
         f"- Nós: {len(nos)} ({len(fls)} folhas); profundidade máxima: {max(p for _, p in nos)}; maior fan-out: {max(len(no.get('nodes', [])) for no, _ in nos)}",
         f"- Folhas com resumo: {sum(bool(f.get('summary')) for f in fls)}; nós internos com prefix_summary não vazio: {len(pref)} de {len(nos) - len(fls)}",
         f"- Custo desta geração (usage da API, stage=tree): US$ {custo:.4f} em {sum(r['stage'] == 'tree' for r in SESSION_RECORDS)} chamadas",
         "\n## Cobertura\n",
         f"- Artigos/anexos cobertos por folhas: {len(cobertos)} de {len(ARTS)}; sem folha: {len(sem_no)} {sem_no[:20]}",
         f"- Nós internos com artigos no próprio texto (caput antes do primeiro filho): {len(internos_com_art)} {[n['title'][:40] for n in internos_com_art][:8]}",
         f"- Folhas com 0 artigos, ocultadas ao navegador: {sum(not f['artigos'] for f in fls)} de {len(fls)}",
         "\n## Tamanho das folhas (tokens, tokenizer local, só estatística)\n",
         f"- mín {min(ts)}, mediana {int(statistics.median(ts))}, média {int(statistics.mean(ts))}, máx {max(ts)}",
         f"- folhas > 2.000: {sum(t > 2000 for t in ts)}; > 4.000: {sum(t > 4000 for t in ts)}; > 8.000: {sum(t > 8000 for t in ts)}",
         "- 5 maiores:"]
    for t, f in tam[:5]:
        L.append(f"  - {t} tok | {f['title'][:60]} | {len(f['artigos'])} artigos" + (f" ({f['artigos'][0]}..{f['artigos'][-1]})" if f["artigos"] else ""))
    L += ["\n## Tamanho dos resumos (palavras)\n",
          f"- Markdown, folhas (summary): mediana {w(res)[len(res)//2]}, máx {w(res)[-1]}, {len(res)} resumos",
          f"- Markdown, internos (prefix_summary): mediana {w(pref)[len(pref)//2] if pref else 0}, máx {w(pref)[-1] if pref else 0}",
          f"- PDF (flash), todos os nós: mediana {w(res_pdf)[len(res_pdf)//2]}, máx {w(res_pdf)[-1]}, {len(res_pdf)} resumos",
          "\n## 5 resumos sorteados\n"]
    random.seed(7)
    for no, _ in random.sample([x for x in nos if x[0].get("summary")], 5):
        L.append(f"- **{no['title'][:70]}** ({len(no['artigos'])} artigos): {no['summary']}")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    MD.write_text(gerar_markdown())
    print(f"markdown: {MD.relative_to(ROOT)}, {MD.stat().st_size // 1024} KB, {sum(l.startswith('#') for l in MD.read_text().splitlines())} cabeçalhos")

    if OUT.exists() and not args.force:
        print(f"cache: {OUT.relative_to(ROOT)} já existe (use --force)")
        arvore = json.loads(OUT.read_text())
    else:
        registrar_custo()
        t0 = time.perf_counter()
        arvore = asyncio.run(md_to_tree(
            md_path=str(MD), if_add_node_summary="yes", summary_token_threshold=200,
            if_add_node_text="yes", if_add_node_id="yes", model=CONFIG["models"][MODEL_KEY]["id"],
        ))
        print(f"md_to_tree: {time.perf_counter() - t0:.0f}s")
    arvore["structure"] = [no for no in arvore["structure"]]
    # reanotação sempre (determinística, sem API); remove intros de uma anotação anterior
    def limpar(nos):
        for no in nos:
            no["nodes"] = [c for c in no.get("nodes", []) if not c["node_id"].endswith("i")]
            limpar(no["nodes"])
            if not no["nodes"]:
                no.pop("nodes")
    limpar(arvore["structure"])
    anotar(arvore, MD.read_text().splitlines())
    OUT.write_text(json.dumps(arvore, ensure_ascii=False, indent=1))
    rel = relatorio(arvore)
    RELATORIO.write_text(rel)
    print(rel)


if __name__ == "__main__":
    main()
