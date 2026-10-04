"""Interface comum dos navegadores da árvore (LLM grande, LLM pequeno, Jev).

A cada passo o navegador recebe a pergunta, o nó atual, seus filhos e o que já foi lido,
e devolve uma Decisao:
  - "descer":     explorar os filhos em nos_escolhidos (ids de nó, 1 ou mais)
  - "suficiente": o que está em ja_lido basta para responder; a busca para
  - "voltar":     nenhum filho parece conter a resposta; a busca segue pelo próximo nó pendente
  - "erro":       o navegador não produziu decisão legível (saída truncada, JSON inválido);
                  a busca descarta o nó como em "voltar", mas o passo fica registrado e contado
confianca é um número de 0 a 1 sobre a decisão (o escalonamento em D usa isso).
info: campos extras do navegador para o registro do passo (ex.: erro, confianca_jev, escalado).
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Decisao:
    acao: str                                  # "descer" | "suficiente" | "voltar" | "erro"
    nos_escolhidos: list[str] = field(default_factory=list)
    confianca: float = 1.0
    info: dict = field(default_factory=dict)


class Navegador(Protocol):
    def escolher(self, pergunta: str, no_atual: dict, filhos: list[dict], ja_lido: list[dict]) -> Decisao: ...
