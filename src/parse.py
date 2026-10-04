"""HTML compilado do Planalto -> data/processed/artigos.json (lista, um item por artigo)

Item: {"id": "art_12" | "art_12a", "numero": "12" | "12-A", "path": [títulos dos ancestrais],
       "text": "...", "pagina": null}   (HTML não tem página de origem)
Anexos viram itens também (id "anexo_i", numero "I"), com path ["ANEXO I ..."].
Este arquivo é o gabarito: perguntas e métrica de recuperação apontam para estes ids.

Regras do HTML do Planalto:
- texto revogado/superado vem em <strike> ou span com text-decoration:line-through: descartado;
- anotações "(Redação dada pela ...)", "(Incluído pela ...)", "(Vide ...)" são links <a href>
  cujo texto começa com "(": descartadas, exceto "(Revogado)";
- cada <p> é um bloco (caput, inciso, parágrafo ou cabeçalho); as quebras de linha
  dentro do <p> são só formatação.
"""

import html
import json
import random
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data/raw/lcp214_compilado.html"
OUT = ROOT / "data/processed/artigos.json"

BLOCK_TAGS = {"p", "div", "br", "tr", "h1", "h2", "h3", "h4", "li", "table"}
HEADING_RE = re.compile(r"^(LIVRO|TÍTULO|CAPÍTULO|Seção|Subseção)\s+([IVXLC]+(?:-[A-Z])?|ÚNIC[OA])\b", re.I)
ARTICLE_RE = re.compile(r"^Art\.\s*(\d+)\s*(?:º|°|o)?\s*(-[A-Z])?\s*\.?\s*")
ANNEX_RE = re.compile(r"^ANEXO\s+([IVXLC]+)\b")
END_OF_ARTICLES = "Brasília, 16 de janeiro de 2025"
LEVELS = ["livro", "título", "capítulo", "seção", "subseção"]


class Blocks(HTMLParser):
    """Extrai blocos de texto, pulando tachados e anotações."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.buf = []
        self.stack = []        # (tag, struck) por elemento aberto
        self.struck = 0        # profundidade dentro de texto tachado
        self.in_annotation = None  # buffer do texto de um <a href> em andamento

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        text = re.sub(r"\s*Produção de efeitos$", "", text)   # anotação do Planalto fora de link
        self.buf = []
        if text:
            self.blocks.append(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        struck = tag == "strike" or "line-through" in (attrs.get("style") or "")
        if tag in BLOCK_TAGS:
            self._flush()
        if tag == "a" and attrs.get("href") and not self.struck:
            self.in_annotation = []
        self.stack.append((tag, struck))
        self.struck += struck

    def handle_endtag(self, tag):
        if tag == "a" and self.in_annotation is not None:
            text = "".join(self.in_annotation).strip()
            self.in_annotation = None
            # links de anotação: "(Redação dada...)", "(Vide...)", "Produção de efeitos"
            if (not text.startswith("(") and text != "Produção de efeitos") or text.startswith("(Revogad"):
                self.buf.append(text)
        # fecha até o elemento correspondente (FrontPage deixa tags sem fechar)
        while self.stack:
            t, struck = self.stack.pop()
            self.struck -= struck
            if t == tag:
                break
        if tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        # cabeçalho "Art. N." de artigo totalmente revogado vem tachado; sem ele o
        # "(Revogado pela ...)" seguinte cairia no artigo anterior
        if self.struck and not re.match(r"\s*Art\.\s*\d", data):
            return
        if self.in_annotation is not None:
            self.in_annotation.append(data)
        else:
            self.buf.append(data)


def extract_blocks(html_text: str) -> list[str]:
    p = Blocks()
    p.feed(html_text)
    p._flush()
    return p.blocks


def parse(blocks: list[str]) -> list[dict]:
    """Percorre os blocos em ordem mantendo a hierarquia corrente."""
    arts = []
    path = {}            # nível -> título
    current = None       # artigo em construção
    pending_heading = None
    started = False

    def close():
        if current:
            arts.append(current)

    for b in blocks:
        if not started:
            started = b.startswith("LIVRO I")
            if not started:
                continue
        if b.startswith(END_OF_ARTICLES):
            close(); current = None
            break
        if pending_heading:
            level, label = pending_heading
            path[level] = f"{label} {b}"
            for lower in LEVELS[LEVELS.index(level) + 1:]:
                path.pop(lower, None)
            pending_heading = None
            continue
        if m := HEADING_RE.match(b):
            level = m.group(1).lower()
            rest = b[m.end():].strip(" -")
            if rest:   # título na mesma linha
                path[level] = f"{m.group(0)} {rest}"
                for lower in LEVELS[LEVELS.index(level) + 1:]:
                    path.pop(lower, None)
            else:
                pending_heading = (level, m.group(0))
            continue
        if m := ARTICLE_RE.match(b):
            close()
            num = m.group(1) + (m.group(2) or "")
            current = {"id": f"art_{num.replace('-', '').lower()}", "numero": num,
                       "path": [path[l] for l in LEVELS if l in path], "text": b, "pagina": None}
            continue
        if current:
            current["text"] += "\n" + b

    # artigo com redação antiga tachada e nova em seguida gera duas entradas: fica a maior
    by_id = {}
    for a in arts:
        if a["id"] not in by_id or len(a["text"]) > len(by_id[a["id"]]["text"]):
            by_id[a["id"]] = a
    arts = list(by_id.values())

    # anexos: tudo depois do fim dos artigos, até os anexos da LC 227 (tabelas do Simples)
    i = next(i for i, b in enumerate(blocks) if b.startswith(END_OF_ARTICLES))
    current, seen = None, set()
    for b in blocks[i:]:
        if m := ANNEX_RE.match(b):
            if m.group(1) in seen:   # numeração reiniciou: começaram os anexos da LC 227
                current = None
                break
            seen.add(m.group(1))
            if current and "\n" in current["text"]:   # anexo sem corpo é só cabeçalho da LC 227
                arts.append(current)
            current = {"id": f"anexo_{m.group(1).lower()}", "numero": m.group(1),
                       "path": [b], "text": b, "pagina": None}
        elif current:
            current["text"] += "\n" + b
    if current:
        arts.append(current)
    return arts


def main():
    arts = parse(extract_blocks(RAW.read_text(encoding="utf-8")))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(arts, ensure_ascii=False, indent=1))

    # relatório de sanidade
    artigos = [a for a in arts if a["id"].startswith("art_")]
    anexos = [a for a in arts if a["id"].startswith("anexo_")]
    ids = [a["id"] for a in arts]
    base_nums = [int(re.match(r"\d+", a["numero"]).group()) for a in artigos]
    print(f"{len(artigos)} artigos + {len(anexos)} anexos, {sum(len(a['text']) for a in arts):,} chars -> {OUT.relative_to(ROOT)}")
    print(f"primeiro: Art. {artigos[0]['numero']}   último: Art. {artigos[-1]['numero']}")
    print("faltando na sequência 1..%d:" % max(base_nums), [n for n in range(1, max(base_nums) + 1) if n not in base_nums] or "nenhum")
    print("ids duplicados:", sorted({i for i in ids if ids.count(i) > 1}) or "nenhum")
    print("fora de ordem:", [f"Art. {a['numero']}" for a, b in zip(artigos, artigos[1:]) if int(re.match(r"\d+", b["numero"]).group()) < int(re.match(r"\d+", a["numero"]).group())] or "nenhum")
    for a in random.sample(artigos, 3):
        print(f"\n{'=' * 80}\n{a['id']}  |  {' > '.join(a['path'])}\n{'-' * 80}\n{a['text']}")


if __name__ == "__main__":
    main()
