"""Checagem offline do loop de busca (sem modelo): navegadores roteirizados sobre a árvore real.

  .venv/bin/python test_busca.py
"""

import sys

sys.path.insert(0, "src")
from config_arvore import MAX_STEPS, RAIZ, buscar  # noqa: E402
from navegadores.base import Decisao  # noqa: E402


class SempreOPrimeiro:
    """Desce sempre pelo primeiro filho: deve chegar a uma folha e lê-la."""
    def escolher(self, pergunta, no, filhos, ja_lido):
        return Decisao("descer", [filhos[0]["node_id"]], 0.9)


class DoisDepoisSuficiente:
    """Desce por dois filhos; depois de ler a primeira folha, diz que basta."""
    def escolher(self, pergunta, no, filhos, ja_lido):
        if ja_lido:
            return Decisao("suficiente", [], 1.0)
        return Decisao("descer", [f["node_id"] for f in filhos[:2]], 0.6)


class SempreVolta:
    def escolher(self, pergunta, no, filhos, ja_lido):
        return Decisao("voltar", [], 0.1)


def test_desce_ate_folha():
    lidos, caminho, _ = buscar(SempreOPrimeiro(), "x")
    assert len(lidos) == 1 and not lidos[0].get("nodes"), caminho
    assert caminho[-1]["acao"] == "ler" and len(caminho) <= MAX_STEPS


def test_suficiente_encerra():
    lidos, caminho, _ = buscar(DoisDepoisSuficiente(), "x")
    assert len(lidos) == 1 and caminho[-1]["acao"] == "suficiente", caminho


def test_voltar_na_raiz_nao_le_nada():
    lidos, caminho, _ = buscar(SempreVolta(), "x")
    assert lidos == [] and len(caminho) == 1 and caminho[0]["no"] == RAIZ["title"]


if __name__ == "__main__":
    for nome, fn in list(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
