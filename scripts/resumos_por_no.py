"""Variante de árvore com resumos escritos pelo agente (sem API) a partir do texto de cada nó.

  python3 scripts/resumos_por_no.py dump <lote> <saida.txt>   # material de leitura: folhas de um lote
  python3 scripts/resumos_por_no.py internos <saida.txt>       # nós internos com os resumos dos filhos
  python3 scripts/resumos_por_no.py merge <resumos.json>       # grava {node_id: resumo} na variante
  python3 scripts/resumos_por_no.py status                     # quantos nós já têm resumo

Lotes: livro1a (Títulos I-IV), livro1b (V-VIII), livro2, livro3, anexos.
Saída: data/index/arvore_resumo_por_no.json (cópia de arvore.json com os resumos trocados).
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTS = {a["id"]: a for a in json.loads((ROOT / "data/processed/artigos.json").read_text())}
BASE = ROOT / "data/index/arvore.json"
OUT = ROOT / "data/index/arvore_resumo_por_no.json"
LOTES = {
    "livro1a": lambda n: n["title"].startswith("LIVRO I ") or re.match(r"TÍTULO (I|II|III|IV) ", n["title"]),
    "livro1b": lambda n: re.match(r"TÍTULO (V|VI|VII|VIII) ", n["title"]),
    "livro2": lambda n: re.match(r"LIVRO II\b", n["title"]),
    "livro3": lambda n: re.match(r"LIVRO III\b", n["title"]),
    "anexos": lambda n: n["title"].startswith("ANEXO") or n["title"].startswith("LEI COMPLEMENTAR"),
}


def carregar():
    if not OUT.exists():
        arvore = json.loads(BASE.read_text())
        for no, _ in todos(arvore["structure"]):
            no["summary"] = ""
        OUT.write_text(json.dumps(arvore, ensure_ascii=False, indent=1))
    return json.loads(OUT.read_text())


def todos(nos, prof=1, pai=None):
    for no in nos:
        yield no, prof
        yield from todos(no.get("nodes", []), prof + 1, no)


def folhas_do_lote(arvore, lote):
    """Folhas sob os nós de nível 1 (ou 2, no Livro I) do lote, em ordem do documento."""
    sel = []
    for n1 in arvore["structure"]:
        topos = n1.get("nodes", []) if n1["title"].startswith("LIVRO I ") else [n1]
        for t in topos:
            if LOTES[lote](t):
                sel += [no for no, _ in todos([t]) if not no.get("nodes")]
    return sel


def dump(lote, saida):
    arvore = carregar()
    linhas = []
    for f in folhas_do_lote(arvore, lote):
        if not f["artigos"]:
            continue
        linhas.append(f"\n## {f['node_id']} | {f['title']} | p.{f['start_index']}-{f['end_index']} | {len(f['artigos'])} artigos")
        for aid in f["artigos"]:
            t = ARTS[aid]["text"]
            linhas.append(f"[{aid}] " + re.sub(r"\s+", " ", t[:380]) + (" ..." if len(t) > 380 else ""))
    Path(saida).write_text("\n".join(linhas))
    print(f"{lote}: {sum(l.lstrip().startswith('## ') for l in linhas)} folhas, {len(''.join(linhas)):,} chars -> {saida}")


def internos(saida):
    arvore = carregar()
    linhas = []
    for no, prof in todos(arvore["structure"]):
        if no.get("nodes"):
            linhas.append(f"\n## {no['node_id']} | {no['title']} | nível {prof} | {len(no['artigos'])} artigos")
            for c in no["nodes"]:
                linhas.append(f"  - [{c['node_id']}] {c['title'][:70]}: {c.get('summary', '')[:300]}")
    Path(saida).write_text("\n".join(linhas))
    print(f"{sum(l.lstrip().startswith('## ') for l in linhas)} nós internos -> {saida}")


def merge(arquivo):
    arvore = carregar()
    novos = json.loads(Path(arquivo).read_text())
    por_id = {no["node_id"]: no for no, _ in todos(arvore["structure"])}
    faltando = [i for i in novos if i not in por_id]
    for i, s in novos.items():
        if i in por_id:
            por_id[i]["summary"] = s.strip()
    OUT.write_text(json.dumps(arvore, ensure_ascii=False, indent=1))
    print(f"{len(novos) - len(faltando)} resumos gravados" + (f"; ids desconhecidos: {faltando}" if faltando else ""))
    status()


def status():
    arvore = carregar()
    nos = [no for no, _ in todos(arvore["structure"])]
    com = [n for n in nos if n["summary"]]
    folhas = [n for n in nos if not n.get("nodes") and n["artigos"]]
    print(f"{len(com)}/{len(nos)} nós com resumo; folhas com artigos: {sum(bool(f['summary']) for f in folhas)}/{len(folhas)}; "
          f"internos: {sum(bool(n['summary']) for n in nos if n.get('nodes'))}/{sum(bool(n.get('nodes')) for n in nos)}")
    if com:
        p = sorted(len(n["summary"].split()) for n in com)
        print(f"palavras por resumo: mín {p[0]}, mediana {p[len(p)//2]}, máx {p[-1]}")


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    {"dump": dump, "internos": internos, "merge": merge, "status": status}[cmd](*args)
