"""NavegadorJev (config D): o Jev (TypeSafe) decide o passo; escala para navegador_grande quando a confiança
fica abaixo de navigate.jev_confidence_threshold (null = nunca escala).

Modelagem M1 com seleção múltipla: um Choice por passo, opções = filhos + "nenhum_destes" (voltar)
+ "ja_lido_basta" (suficiente; só quando há algo lido). Desce pela vencedora e também por até
jev_max_extra outros filhos com probabilidade >= jev_prob_minima_extra (o LLM escolhe até 3).
confianca do passo = probabilities[vencedora]; o confidence do Jev vai em info["confianca_jev"].
"""

from typesafe_sdk import Choice

from llm_client import CONFIG, ask_jev
from navegadores.base import Decisao
from navegadores.llm import NavegadorLLM

INSTRUCOES = ("Você navega no índice hierárquico da Lei Complementar 214/2025 (IBS, CBS e Imposto Seletivo). "
              "Dado `pergunta`, o nó atual `no_atual` e o que já foi lido em `ja_lido`, escolha a seção filha "
              "com maior chance de conter os dispositivos que respondem a pergunta. Escolha `ja_lido_basta` se o que "
              "já foi lido é suficiente para responder; escolha `nenhum_destes` se nenhuma seção filha parece conter a resposta.")
NENHUM, BASTA = "nenhum_destes", "ja_lido_basta"


def _descricao(no: dict) -> str:
    resumo = no.get("summary") or no.get("prefix_summary") or ""
    return f"{no['title']}. {resumo}" if resumo else no["title"]


class NavegadorJev:
    def __init__(self, config: str = "D", limiar: float | None = None):
        self.config = config
        self.question_id = None
        nav = CONFIG["navigate"]
        self.limiar = nav["jev_confidence_threshold"] if limiar is None else limiar   # 0 = nunca escala
        self.p_min, self.max_extra = nav["jev_prob_minima_extra"], nav["jev_max_extra"]
        self.reserva = NavegadorLLM("navegador_grande", config)   # escalonamento por passo

    def escolher(self, pergunta, no_atual, filhos, ja_lido) -> Decisao:
        criterios = {f["node_id"]: _descricao(f) for f in filhos}
        criterios[NENHUM] = "Nenhuma das seções acima parece conter a resposta para a pergunta."
        if ja_lido:
            criterios[BASTA] = "Os trechos em `ja_lido` já bastam para responder a pergunta; não é preciso ler mais."
        estado = {"pergunta": pergunta, "no_atual": _descricao(no_atual),
                  "ja_lido": [_descricao(n) for n in ja_lido] or "nada lido ainda"}
        r = ask_jev(estado, {"passo": Choice(instructions=INSTRUCOES, criteria=criterios)},
                    stage="navigate", config=self.config, question_id=self.question_id)
        a = r.choices["passo"]
        probs = dict(a.probabilities)
        vencedora, conf = a.choice, probs[a.choice]
        info = {"confianca_jev": round(a.confidence, 3), "escalado": False,
                "probs": {k: round(v, 3) for k, v in sorted(probs.items(), key=lambda kv: -kv[1])[:4]}}

        if self.limiar is not None and conf < self.limiar:
            self.reserva.question_id = self.question_id   # custo do passo escalado conta na pergunta
            d = self.reserva.escolher(pergunta, no_atual, filhos, ja_lido)
            d.info.update(info, escalado=True, confianca_jev_passo=round(conf, 3))
            return d
        acao, ids = decidir(probs, self.p_min, self.max_extra)
        info["multipla"] = len(ids) > 1
        return Decisao(acao, ids, conf, info)


def decidir(probs: dict[str, float], p_min: float, max_extra: int) -> tuple[str, list[str]]:
    """Vencedora -> ação; em "descer", vencedora + até max_extra outros filhos com p >= p_min, por probabilidade."""
    ordem = [k for k, _ in sorted(probs.items(), key=lambda kv: -kv[1])]
    vencedora = ordem[0]
    if vencedora == NENHUM:
        return "voltar", []
    if vencedora == BASTA:
        return "suficiente", []
    extras = [k for k in ordem[1:] if k not in (NENHUM, BASTA) and probs[k] >= p_min][:max_extra]
    return "descer", [vencedora, *extras]


if __name__ == "__main__":
    assert decidir({"a": 0.5, "b": 0.3, "c": 0.15, NENHUM: 0.05}, 0.2, 2) == ("descer", ["a", "b"])
    assert decidir({"a": 0.4, "b": 0.3, "c": 0.25, "d": 0.05}, 0.2, 2) == ("descer", ["a", "b", "c"])
    assert decidir({"a": 0.3, NENHUM: 0.5, BASTA: 0.2}, 0.2, 2) == ("voltar", [])
    assert decidir({"a": 0.3, BASTA: 0.6, NENHUM: 0.1}, 0.2, 2) == ("suficiente", [])
    assert decidir({"a": 0.5, BASTA: 0.3, "b": 0.2}, 0.2, 2) == ("descer", ["a", "b"])   # BASTA nunca entra como extra
    print("ok")
