"""Porta única de saída para modelos. Tudo que custa dinheiro passa por aqui.

Cada chamada grava uma linha em logs/calls.jsonl:
  config (A-D ou null), question_id, stage (index | tree | navigate | answer | test),
  model_key, model_id, input_tokens, output_tokens, cost_usd, latency_s.
Custos únicos (index, tree) têm question_id null; o evaluate.py separa por isso.
"""

import json
import time
from functools import cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text())
LOG_PATH = ROOT / "logs" / "calls.jsonl"
SESSION_RECORDS: list[dict] = []   # mesmas linhas do log, desta execução; para somar custo por pergunta


def cost_usd(model_key: str, input_tokens: int, output_tokens: int) -> float:
    m = CONFIG["models"][model_key]
    return (input_tokens * m["input_per_m"] + output_tokens * m["output_per_m"]) / 1_000_000


def _log(model_key, input_tokens, output_tokens, started, config, question_id, stage, stop_reason=None) -> dict:
    record = {
        "ts": time.time(),
        "config": config,
        "question_id": question_id,
        "stage": stage,
        "model_key": model_key,
        "model_id": CONFIG["models"][model_key]["id"],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd(model_key, input_tokens, output_tokens),
        "latency_s": round(time.perf_counter() - started, 3),
    }
    if stop_reason is not None:
        record["stop_reason"] = stop_reason   # quem chama detecta truncamento ("max_tokens")
    LOG_PATH.parent.mkdir(exist_ok=True)
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    SESSION_RECORDS.append(record)
    return record


# Clientes criados sob demanda: importar este módulo não exige todas as chaves.
@cache
def _anthropic():
    import anthropic
    return anthropic.Anthropic()


@cache
def _openai():
    from openai import OpenAI
    return OpenAI()


@cache
def _typesafe():
    from typesafe_sdk import TypeSafeClient
    return TypeSafeClient(model=CONFIG["models"]["jev"]["id"])


def call_llm(model_key: str, system: str, user: str, max_tokens: int, *,
             stage: str, config: str | None = None, question_id: str | None = None) -> str:
    """Uma mensagem de usuário, uma resposta em texto. Sem histórico, sem tools."""
    m = CONFIG["models"][model_key]
    kwargs = {}
    if "effort" in m:   # Haiku 4.5 rejeita effort; Opus/Sonnet 5.x aceitam
        kwargs["output_config"] = {"effort": m["effort"]}
    started = time.perf_counter()
    r = _anthropic().messages.create(
        model=m["id"], max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}], **kwargs,
    )
    _log(model_key, r.usage.input_tokens, r.usage.output_tokens, started, config, question_id, stage, r.stop_reason)
    if r.stop_reason == "refusal":
        raise RuntimeError(f"refusal em {m['id']}: {r.stop_details}")
    return "".join(b.text for b in r.content if b.type == "text")


def embed(texts: list[str], *, stage: str, config: str | None = None,
          question_id: str | None = None) -> list[list[float]]:
    m = CONFIG["models"]["embedding"]
    started = time.perf_counter()
    r = _openai().embeddings.create(model=m["id"], input=texts)
    _log("embedding", r.usage.prompt_tokens, 0, started, config, question_id, stage)
    return [d.embedding for d in r.data]


def ask_jev(state, questions: dict, *, stage: str, config: str | None = None,
            question_id: str | None = None):
    """Retorna o SystemOneResponse do SDK (r.choices[k].choice/.confidence, r.nouls[k].noul)."""
    started = time.perf_counter()
    r = _typesafe().system_one(state, questions)
    _log("jev", r.usage.input_tokens or 0, r.usage.output_tokens or 0, started, config, question_id, stage)
    return r


if __name__ == "__main__":
    # Checagem sem rede: só a aritmética de custo.
    assert abs(cost_usd("navegador_grande", 1_000_000, 1_000_000) - 24.0) < 1e-9
    assert abs(cost_usd("jev", 1_000_000, 500) - 0.042) < 1e-9
    assert cost_usd("embedding", 0, 0) == 0
    print("ok")
