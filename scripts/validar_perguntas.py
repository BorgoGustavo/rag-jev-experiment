"""Valida data/eval/perguntas.json contra data/processed/artigos.json e gera data/eval/revisao.md.

Checa: 40 perguntas, ids únicos, distribuição 15/12/13 por tipo, campos obrigatórios,
ids de artigo existentes, um trecho de evidência por artigo gabarito e cada trecho
presente LITERALMENTE no artigo correspondente. Sai com código 1 se algo falhar.
"""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTS = {a["id"]: a for a in json.loads((ROOT / "data/processed/artigos.json").read_text())}
PERGUNTAS = json.loads((ROOT / "data/eval/perguntas.json").read_text())
REVISAO = ROOT / "data/eval/revisao.md"

ESPERADO = {"direta": 15, "referencia_cruzada": 12, "vocabulario_diferente": 13}
CAMPOS = {"id", "tipo", "pergunta", "artigos_gabarito", "trechos_evidencia", "resposta_esperada", "dificuldade"}


def validar() -> list[str]:
    erros = []
    if len(PERGUNTAS) != 40:
        erros.append(f"total: {len(PERGUNTAS)} perguntas, esperado 40")
    ids = [q["id"] for q in PERGUNTAS]
    if len(set(ids)) != len(ids):
        erros.append(f"ids repetidos: {[i for i, n in Counter(ids).items() if n > 1]}")
    tipos = Counter(q["tipo"] for q in PERGUNTAS)
    if tipos != Counter(ESPERADO):
        erros.append(f"distribuição por tipo: {dict(tipos)}, esperado {ESPERADO}")
    for q in PERGUNTAS:
        if faltam := CAMPOS - q.keys():
            erros.append(f"{q.get('id')}: campos faltando {sorted(faltam)}")
            continue
        if q["dificuldade"] not in {"facil", "media", "dificil"}:
            erros.append(f"{q['id']}: dificuldade inválida {q['dificuldade']!r}")
        if len(q["trechos_evidencia"]) != len(q["artigos_gabarito"]):
            erros.append(f"{q['id']}: {len(q['trechos_evidencia'])} trechos para {len(q['artigos_gabarito'])} artigos")
        for art_id, trecho in zip(q["artigos_gabarito"], q["trechos_evidencia"]):
            if art_id not in ARTS:
                erros.append(f"{q['id']}: artigo inexistente {art_id}")
            elif trecho not in ARTS[art_id]["text"]:
                erros.append(f"{q['id']}: trecho não encontrado literalmente em {art_id}: {trecho[:70]!r}")
    return erros


def gerar_revisao():
    linhas = ["# Revisão do conjunto de avaliação\n",
              f"{len(PERGUNTAS)} perguntas. Para cada uma: gabarito, trechos de evidência e texto integral dos artigos.\n"]
    for q in PERGUNTAS:
        linhas += [f"\n---\n\n## {q['id']} · {q['tipo']} · {q['dificuldade']}\n",
                   f"**Pergunta:** {q['pergunta']}\n",
                   f"**Resposta esperada:** {q['resposta_esperada']}\n",
                   f"**Artigos gabarito:** {', '.join(q['artigos_gabarito'])}\n",
                   "**Trechos de evidência:**\n"]
        linhas += [f"- `{a}`: \"{t}\"" for a, t in zip(q["artigos_gabarito"], q["trechos_evidencia"])]
        for art_id in q["artigos_gabarito"]:
            a = ARTS[art_id]
            linhas += [f"\n<details><summary><b>{art_id}</b> · {' > '.join(a['path'])}</summary>\n", "```",
                       a["text"], "```", "</details>"]
    REVISAO.write_text("\n".join(linhas) + "\n")


if __name__ == "__main__":
    erros = validar()
    for e in erros:
        print("ERRO:", e)
    if erros:
        sys.exit(1)
    gerar_revisao()
    print(f"ok: {len(PERGUNTAS)} perguntas válidas; revisão em {REVISAO.relative_to(ROOT)}")
