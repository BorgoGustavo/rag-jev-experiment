"""Resumo dos results/*.jsonl por configuração: recuperação (geral, por tipo, com/sem ruído), custo, latência, passos, contexto."""
import json, statistics, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for arq in sorted((ROOT / "results").glob("*.jsonl")):
    rs = [json.loads(l) for l in arq.open()]
    if not rs:
        continue
    acc = lambda xs: f"{sum(r['acerto_recuperacao'] for r in xs)}/{len(xs)}" if xs else "-"
    tipos = {t: acc([r for r in rs if r["tipo"] == t]) for t in ("direta", "referencia_cruzada", "vocabulario_diferente")}
    ruido = [r for r in rs if r["gabarito_em_folha_ruido"]]
    sem = [r for r in rs if not r["gabarito_em_folha_ruido"]]
    custo = sum(r["custo_usd"] for r in rs)
    print(f"\n== {arq.stem} ({len(rs)} perguntas)")
    print(f"  recuperação: {acc(rs)} | direta {tipos['direta']}, cruzada {tipos['referencia_cruzada']}, vocabulário {tipos['vocabulario_diferente']}"
          f" | com ruído {acc(ruido)}, sem ruído {acc(sem)} | cobertura média {statistics.mean(r['cobertura'] for r in rs):.2f}")
    print(f"  custo: US$ {custo:.3f} total, US$ {custo/len(rs):.4f}/pergunta | latência mediana {statistics.median(r['latencia_s'] for r in rs):.1f}s"
          f" | passos médios {statistics.mean(r.get('passos', 0) for r in rs):.1f} | contexto do gerador médio {statistics.mean(r['tokens_contexto_gerador'] for r in rs):.0f} tokens")
