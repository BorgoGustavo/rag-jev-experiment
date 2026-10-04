"""NavegadorLLM: um modelo de linguagem decide o passo. B usa navegador_grande, C usa navegador_pequeno."""

import json
import re

from llm_client import CONFIG, SESSION_RECORDS, call_llm
from navegadores.base import Decisao

SYSTEM = """Você navega no índice hierárquico da Lei Complementar 214/2025 (IBS, CBS e Imposto Seletivo) para localizar os dispositivos que respondem a uma pergunta.

A cada passo você vê o nó atual, seus filhos (id, título, resumo) e o que já foi lido. Decida:
- "descer": explorar os filhos mais prováveis (1 a 3 ids, do mais provável ao menos);
- "suficiente": o que já foi lido basta para responder a pergunta;
- "voltar": nenhum filho deste nó parece conter a resposta.

Responda SOMENTE com o JSON abaixo, sem explicação antes ou depois:
{"acao": "descer" | "suficiente" | "voltar", "nos_escolhidos": ["id", ...], "confianca": 0.0 a 1.0}"""

USER = """Pergunta: {pergunta}

Nó atual: {atual}

Filhos:
{filhos}

Já lido:
{lido}"""


def _linha(no: dict) -> str:
    resumo = no.get("summary") or no.get("prefix_summary") or ""   # md_to_tree: internos só têm prefix_summary
    return f"- id={no['node_id']} | {no['title']}" + (f" | {resumo}" if resumo else "")


class NavegadorLLM:
    def __init__(self, model_key: str, config: str):
        self.model_key, self.config = model_key, config
        self.question_id = None   # o loop de busca define antes de cada pergunta

    def escolher(self, pergunta, no_atual, filhos, ja_lido) -> Decisao:
        prompt = USER.format(
            pergunta=pergunta, atual=_linha(no_atual)[2:],
            filhos="\n".join(_linha(f) for f in filhos) or "(nenhum)",
            lido="\n".join(_linha(n) for n in ja_lido) or "(nada)",
        )
        texto = call_llm(self.model_key, SYSTEM, prompt, CONFIG["navigate"]["max_tokens"],
                         stage="navigate", config=self.config, question_id=self.question_id)
        if SESSION_RECORDS[-1]["stop_reason"] == "max_tokens":
            return Decisao("erro", [], 0.0, {"erro": "truncado"})
        try:
            d = json.loads(re.search(r"\{.*\}", texto, re.S).group())
        except (AttributeError, json.JSONDecodeError):
            return Decisao("erro", [], 0.0, {"erro": "parse"})
        validos = {f["node_id"] for f in filhos}
        acao, ids = d.get("acao", "voltar"), [i for i in d.get("nos_escolhidos", []) if i in validos]
        if acao == "descer" and not ids:        # só ids que não são filhos: erro explícito, não "voltar" calado
            return Decisao("erro", [], 0.0, {"erro": "ids_invalidos", "ids": d.get("nos_escolhidos", [])})
        return Decisao(acao, ids, float(d.get("confianca", 0.0)))
