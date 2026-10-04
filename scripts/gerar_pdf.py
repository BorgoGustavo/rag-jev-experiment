"""HTML compilado do Planalto -> PDF limpo para o PageIndex (data/raw/lcp214_compilado.pdf).

Reaproveita o extrator de blocos do parse.py (sem tachado nem anotações), marca Livro/Título/
Capítulo/Seção/Subseção/Anexo como <h1>..<h5> e imprime com o Chrome headless gerando o
outline (bookmarks) do PDF, como um PDF oficial bem formatado teria. O texto é o mesmo do
artigos.json, então o mapeamento nó -> artigos fica exato.
"""

import html
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from parse import ANNEX_RE, END_OF_ARTICLES, HEADING_RE, RAW, extract_blocks  # noqa: E402

HTML_OUT = ROOT / "data/raw/lcp214_compilado_limpo.html"
ARTS = {a["id"]: a for a in json.loads((ROOT / "data/processed/artigos.json").read_text())}
# Intervenção (README): blocos sem subdivisão interna com mais de 4.000 tokens ganham subtítulos
# sintéticos "Arts. X a Y" por grupos de artigos de até ~2.500 tokens; artigo sozinho > 4.000 vira
# folha própria. (primeiro artigo, último artigo, nível do subtítulo = um abaixo do cabeçalho pai)
DIVIDIR = [("art_21", "art_26", 5), ("art_439", "art_457", 4), ("art_491", "art_544", 3)]
MAX_TOKENS_GRUPO = 2500
PDF_OUT = ROOT / "data/raw/lcp214_compilado.pdf"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
LEVEL = {"livro": 1, "título": 2, "capítulo": 3, "seção": 4, "subseção": 5}
CSS = """body{font-family:'Times New Roman',serif;font-size:11pt;line-height:1.35;margin:0}
h1{font-size:18pt;text-align:center;margin:28pt 0 10pt} h2{font-size:15pt;text-align:center;margin:22pt 0 8pt}
h3{font-size:13pt;text-align:center;margin:18pt 0 6pt} h4{font-size:12pt;font-weight:bold;margin:14pt 0 4pt}
h5{font-size:11.5pt;font-weight:bold;font-style:italic;margin:12pt 0 4pt}
p{text-align:justify;margin:0 0 6pt;text-indent:24pt} @page{size:A4;margin:2cm}"""


def tokens(s: str) -> int:
    import litellm
    return litellm.token_counter(model="gpt-4o", text=s)


def subtitulos() -> dict[str, tuple[int, str]]:
    """id do primeiro artigo de cada grupo -> (nível, título do subtítulo sintético)."""
    ids = list(ARTS)
    out = {}
    for ini, fim, nivel in DIVIDIR:
        faixa = ids[ids.index(ini):ids.index(fim) + 1]
        grupo, soma = [], 0
        def fechar():
            if grupo:
                a, b = ARTS[grupo[0]]["numero"], ARTS[grupo[-1]]["numero"]
                out[grupo[0]] = (nivel, f"Art. {a}" if a == b else f"Arts. {a} a {b}")
        for aid in faixa:
            t = tokens(ARTS[aid]["text"])
            if t > 4000:                       # exceção: artigo sozinho vira folha própria
                fechar(); grupo, soma = [], 0
                out[aid] = (nivel, f"Art. {ARTS[aid]['numero']}")
                continue
            if grupo and soma + t > MAX_TOKENS_GRUPO:
                fechar(); grupo, soma = [], 0
            grupo.append(aid); soma += t
        fechar()
    return out


ART_RE = re.compile(r"^Art\.\s*(\d+)\s*(?:º|°)?\s*(-[A-Z])?")


def blocos_para_html(blocks: list[str]) -> list[str]:
    subs = subtitulos()
    out, started, pending, anexos, aberto = [], False, None, set(), {}
    for b in blocks:
        if not started:
            started = b.startswith("LIVRO I")
            if not started:
                continue
        if b.startswith(END_OF_ARTICLES):
            out.append(f"<p>{html.escape(b)}</p>")
            continue
        if m := ANNEX_RE.match(b):
            if m.group(1) in anexos:          # numeração reiniciou: anexos da LC 227, fim
                break
            anexos.add(m.group(1))
            out.append(f"<h1>{html.escape(b)}</h1>")
            continue
        if pending:
            lvl, label = pending
            pending = None
            b = f"{label} {b}"
            m = HEADING_RE.match(b)
        elif m := HEADING_RE.match(b):
            lvl = LEVEL[m.group(1).lower()]
            if not b[m.end():].strip(" -"):   # título vem no bloco seguinte
                pending = (lvl, m.group(0))
                continue
        if not m:
            ma = ART_RE.match(b)
            aid = ma and f"art_{ma.group(1)}{(ma.group(2) or '').replace('-', '').lower()}"
            if aid in subs:
                lvl, titulo = subs[aid]
                out.append(f"<h{lvl}>{html.escape(titulo)}</h{lvl}>")
        if m:
            chave = m.group(0).upper()
            if aberto.get(lvl) == chave:      # mesmo agrupamento renomeado pela LC 227: não repete
                continue
            aberto[lvl] = chave
            for deeper in range(lvl + 1, 6):
                aberto.pop(deeper, None)
            out.append(f"<h{lvl}>{html.escape(b)}</h{lvl}>")
            continue
        out.append(f"<p>{html.escape(b)}</p>")
    # anexos sem corpo (cabeçalhos da LC 227 que sobraram no fim)
    while out and out[-1].startswith("<h1>ANEXO"):
        out.pop()
    return out


def main():
    subs = subtitulos()
    print("subtítulos sintéticos:", ", ".join(t for _, t in subs.values()))
    corpo = blocos_para_html(extract_blocks(RAW.read_text(encoding="utf-8")))
    doc = (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
           f"<title>Lei Complementar nº 214, de 16 de janeiro de 2025 (compilada)</title><style>{CSS}</style></head><body>"
           "<h1>LEI COMPLEMENTAR Nº 214, DE 16 DE JANEIRO DE 2025</h1>"
           "<p>Institui o Imposto sobre Bens e Serviços (IBS), a Contribuição Social sobre Bens e Serviços (CBS) "
           "e o Imposto Seletivo (IS); cria o Comitê Gestor do IBS e altera a legislação tributária. Texto compilado.</p>"
           + "\n".join(corpo) + "</body></html>")
    HTML_OUT.write_text(doc)
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--generate-pdf-document-outline", f"--print-to-pdf={PDF_OUT}", f"file://{HTML_OUT}"],
                   check=True, capture_output=True)
    print(f"{len(corpo)} blocos ({sum(c.startswith('<h') for c in corpo)} cabeçalhos) -> {PDF_OUT.relative_to(ROOT)} "
          f"({PDF_OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
