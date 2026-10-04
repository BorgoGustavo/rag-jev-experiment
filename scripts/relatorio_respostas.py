"""Acerto de resposta (avaliação do agente em data/eval/avaliacao_respostas.json) por configuração e tipo, e amostra para conferência manual."""
import json, random
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
AV = json.loads((ROOT / "data/eval/avaliacao_respostas.json").read_text())
QS = {q["id"]: q for q in json.loads((ROOT / "data/eval/perguntas.json").read_text())}
ARQ = {"D_puro": "D_limiar0_resp", "D_070": "D_limiar0.7_resp"}   # chave da avaliação -> arquivo de resultados
RES = {cfg: {json.loads(l)["id"]: json.loads(l) for l in (ROOT / f"results/{ARQ.get(cfg, cfg)}.jsonl").open()} for cfg in AV if cfg != "_nota"}
TIPOS = ("direta", "referencia_cruzada", "vocabulario_diferente")
print(f"{'config':<6} {'correta':>8} {'parcial':>8} {'incorr.':>8} | " + " | ".join(f"{t[:11]:>11}" for t in TIPOS) + " | abstenções")
for cfg, notas in AV.items():
    if cfg == "_nota": continue
    c = lambda sel, n: sum(1 for q, (nota, _) in notas.items() if nota == n and sel(q))
    tot = lambda sel: sum(1 for q in notas if sel(q))
    linha = f"{cfg:<6} {c(lambda q: True,'correta'):>8} {c(lambda q: True,'parcial'):>8} {c(lambda q: True,'incorreta'):>8} | "
    linha += " | ".join(f"{c(lambda q,t=t: QS[q]['tipo']==t,'correta')}/{tot(lambda q,t=t: QS[q]['tipo']==t)} (+{c(lambda q,t=t: QS[q]['tipo']==t,'parcial')}p)".rjust(11) for t in TIPOS)
    linha += f" | {sum(1 for q in notas if RES[cfg][q]['resposta'].startswith('Não encontrei base'))}"
    print(linha)
random.seed(42)
pares = [(cfg, q) for cfg in ("A", "B", "C", "D") for q in random.sample(sorted(AV[cfg]), 3)]   # 3 por config
L = ["# Amostra para conferência manual (12 avaliações sorteadas, 3 de A, B, C e D 0,80; seed 42)\n"]
for cfg, q in pares:
    nota, just = AV[cfg][q]; Q = QS[q]; r = RES[cfg][q]
    L += [f"\n---\n\n## {cfg} · {q} · {Q['tipo']} · avaliação: **{nota}**\n", f"**Pergunta:** {Q['pergunta']}\n",
          f"**Resposta esperada:** {Q['resposta_esperada']}\n", "**Trechos de evidência:**\n"] + [f"- `{a}`: \"{t}\"" for a, t in zip(Q["artigos_gabarito"], Q["trechos_evidencia"])]
    L += [f"\n**Recuperação:** {'ok' if r['acerto_recuperacao'] else 'falhou'} (recuperados: {', '.join(r['recuperados'][:12])}{'...' if len(r['recuperados'])>12 else ''})\n",
          f"**Resposta gerada:**\n\n> " + r["resposta"].replace("\n", "\n> "), f"\n**Justificativa da avaliação:** {just}"]
(ROOT / "data/eval/amostra_manual.md").write_text("\n".join(L) + "\n")
print("\namostra em data/eval/amostra_manual.md")
