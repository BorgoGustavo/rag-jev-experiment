"""McNemar exato (binomial nos pares discordantes) para acerto de recuperação entre dois results/*.jsonl.

  .venv/bin/python scripts/mcnemar.py results/D.jsonl results/B.jsonl
"""
import json, sys
from math import comb


def carregar(p):
    return {json.loads(l)["id"]: json.loads(l)["acerto_recuperacao"] for l in open(p)}


def mcnemar(x: dict, y: dict) -> tuple[int, int, float]:
    """(só x acertou, só y acertou, p bicaudal exato)."""
    ids = sorted(set(x) & set(y))
    b = sum(x[i] and not y[i] for i in ids)
    c = sum(y[i] and not x[i] for i in ids)
    n = b + c
    if n == 0:
        return b, c, 1.0
    p = min(1.0, 2 * sum(comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n)
    return b, c, p


if __name__ == "__main__":
    assert mcnemar({i: v for i, v in enumerate([1]*9)}, {i: 0 for i in range(9)}) == (9, 0, 2 * 1 / 512)
    if len(sys.argv) == 3:
        b, c, p = mcnemar(carregar(sys.argv[1]), carregar(sys.argv[2]))
        print(f"{sys.argv[1]} vs {sys.argv[2]}: {b} x {c}, p = {p:.3f}")
