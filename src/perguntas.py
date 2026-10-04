"""Conjunto de avaliação e amostragem para rodadas parciais."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PERGUNTAS = json.loads((ROOT / "data/eval/perguntas.json").read_text())


def _artigos_em_folha_ruido() -> set[str]:
    """Artigos cuja folha na árvore PageIndex é uma alínea tomada por cabeçalho (marcada em gerar_arvore.py)."""
    arq = next((f for f in (ROOT / "data/index/arvore.json", ROOT / "data/index/arvore_sem_resumos.json") if f.exists()), None)
    if arq is None:
        return set()
    def folhas(nos):
        for n in nos:
            yield from folhas(n["nodes"]) if n.get("nodes") else [n]
    return {a for f in folhas(json.loads(arq.read_text())["structure"]) if f.get("ruido") for a in f["artigos"]}


ARTIGOS_RUIDO = _artigos_em_folha_ruido()


def gabarito_em_folha_ruido(q: dict) -> bool:
    return bool(set(q["artigos_gabarito"]) & ARTIGOS_RUIDO)


def amostra(limit: int | None) -> list[dict]:
    """--limit N: N perguntas alternando os tipos (3 -> uma direta, uma cruzada, uma de vocabulário)."""
    if not limit:
        return PERGUNTAS
    por_tipo = {}
    for q in PERGUNTAS:
        por_tipo.setdefault(q["tipo"], []).append(q)
    out, filas = [], list(por_tipo.values())
    while len(out) < limit and any(filas):
        for fila in filas:
            if fila and len(out) < limit:
                out.append(fila.pop(0))
    return out
