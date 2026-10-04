"""Prompt de geração da resposta final. O MESMO em todas as configurações (A, B, C, D):
só o contexto recuperado muda."""

ANSWER_SYSTEM = """Você responde perguntas sobre a Lei Complementar 214/2025 (IBS, CBS e Imposto Seletivo).

Regras:
1. Use EXCLUSIVAMENTE os trechos fornecidos. Não use conhecimento próprio sobre a lei.
2. Cite o(s) artigo(s) que sustentam cada afirmação, no formato "art. 12" (e parágrafo/inciso quando relevante).
3. Se os trechos não permitirem responder, responda exatamente: "Não encontrei base nos trechos fornecidos."
4. Resposta curta e objetiva, em português, sem preâmbulo."""

ANSWER_USER = """Trechos da lei:

{contexto}

Pergunta: {pergunta}"""


def formatar_contexto(trechos: list[dict]) -> str:
    """trechos: [{"text": ..., "artigos": ["art_12", ...]}, ...]"""
    return "\n\n".join(
        f"[Trecho {i} | artigos: {', '.join(t['artigos'])}]\n{t['text']}"
        for i, t in enumerate(trechos, 1)
    )
