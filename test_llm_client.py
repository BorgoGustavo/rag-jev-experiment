"""Chamada mínima a cada provedor e o registro que ela gera no log.

  .venv/bin/python test_llm_client.py            # os três provedores (custa frações de centavo)
  .venv/bin/python test_llm_client.py anthropic   # só um deles

Também roda com pytest, se quiser.
"""

import json
import sys

sys.path.insert(0, "src")
from llm_client import LOG_PATH, ask_jev, call_llm, embed  # noqa: E402

CHECKS = {
    "anthropic": lambda: call_llm("navegador_pequeno", "Responda com uma palavra.", "Qual a capital do Brasil?",
                                  max_tokens=16, stage="test"),
    "openai": lambda: len(embed(["teste"], stage="test")[0]),
    "typesafe": lambda: ask_jev({"texto": "Brasília é a capital do Brasil."},
                                {"capital": __import__("typesafe_sdk").Noul(instructions="O texto fala de uma capital?")},
                                stage="test").nouls["capital"].noul,
}


def run(name: str):
    result = CHECKS[name]()
    record = json.loads(LOG_PATH.read_text().splitlines()[-1])
    assert record["stage"] == "test" and record["input_tokens"] > 0 and record["latency_s"] > 0, record
    print(f"[{name}] resultado: {result!r}\n          log: {json.dumps(record, ensure_ascii=False)}")


def test_anthropic(): run("anthropic")
def test_openai(): run("openai")
def test_typesafe(): run("typesafe")


if __name__ == "__main__":
    for name in sys.argv[1:] or CHECKS:
        run(name)
