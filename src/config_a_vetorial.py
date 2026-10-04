"""Configuração A: RAG vetorial.

Texto completo (artigos em ordem) -> chunks (RecursiveCharacterTextSplitter, cada chunk sabe
quais artigos cobre) -> embeddings -> Chroma persistido em data/index/chroma (uma vez só,
stage=index) -> top-k por pergunta -> resposta com gerador_resposta e o prompt de prompts.py.

  python src/config_a_vetorial.py --estimate   # sem chamar modelo
  python src/config_a_vetorial.py --limit 3    # indexa se preciso, roda 3, extrapola para 40
  python src/config_a_vetorial.py              # todas -> results/A.jsonl
"""

import argparse
import json
import time
from pathlib import Path

import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter

from llm_client import CONFIG, SESSION_RECORDS, call_llm, cost_usd, embed
from perguntas import PERGUNTAS, amostra, gabarito_em_folha_ruido
from prompts import ANSWER_SYSTEM, ANSWER_USER, formatar_contexto

ROOT = Path(__file__).resolve().parent.parent
ARTS = json.loads((ROOT / "data/processed/artigos.json").read_text())
INDEX_DIR = ROOT / "data/index/chroma"
RESULTS = ROOT / "results/A.jsonl"
CFG = CONFIG["vector"]


def gerar_chunks() -> list[dict]:
    """Concatena os artigos; cada chunk guarda os ids dos artigos cujo texto ele toca."""
    partes, spans, pos = [], [], 0
    for a in ARTS:
        spans.append((pos, pos + len(a["text"]), a["id"]))
        partes.append(a["text"])
        pos += len(a["text"]) + 2            # separador "\n\n"
    texto = "\n\n".join(partes)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CFG["chunk_size"], chunk_overlap=CFG["chunk_overlap"], add_start_index=True)
    chunks = []
    for d in splitter.create_documents([texto]):
        ini = d.metadata["start_index"]
        fim = ini + len(d.page_content)
        chunks.append({"text": d.page_content, "artigos": [i for s, e, i in spans if s < fim and e > ini]})
    return chunks


def indexar(chunks: list[dict]):
    """Cria (ou reaproveita) a coleção. Custo único, stage=index, sem question_id."""
    client = chromadb.PersistentClient(path=str(INDEX_DIR))
    nome = CFG["collection"]
    coll = client.get_or_create_collection(nome, metadata={"hnsw:space": "cosine"})
    if coll.count() == len(chunks):
        print(f"índice existente: {coll.count()} chunks em {INDEX_DIR.relative_to(ROOT)}")
        return coll
    if coll.count():
        client.delete_collection(nome)
        coll = client.create_collection(nome, metadata={"hnsw:space": "cosine"})
    for i in range(0, len(chunks), 100):
        lote = chunks[i:i + 100]
        coll.add(
            ids=[str(i + j) for j in range(len(lote))],
            embeddings=embed([c["text"] for c in lote], stage="index", config="A"),
            documents=[c["text"] for c in lote],
            metadatas=[{"artigos": ",".join(c["artigos"])} for c in lote],
        )
    custo = sum(r["cost_usd"] for r in SESSION_RECORDS if r["stage"] == "index")
    print(f"indexados {len(chunks)} chunks; custo único US$ {custo:.4f}")
    return coll


def responder(coll, q: dict) -> dict:
    """Uma pergunta, passo a passo: embedding da pergunta -> top-k -> contexto -> resposta."""
    t0 = time.perf_counter()
    vetor = embed([q["pergunta"]], stage="retrieve", config="A", question_id=q["id"])[0]
    res = coll.query(query_embeddings=[vetor], n_results=CFG["top_k"], include=["documents", "metadatas"])
    trechos = [{"text": d, "artigos": m["artigos"].split(",")}
               for d, m in zip(res["documents"][0], res["metadatas"][0])]
    recuperados = list(dict.fromkeys(i for t in trechos for i in t["artigos"]))   # únicos, em ordem
    resposta = call_llm(
        "gerador_resposta", ANSWER_SYSTEM,
        ANSWER_USER.format(contexto=formatar_contexto(trechos), pergunta=q["pergunta"]),
        CONFIG["answer"]["max_tokens"], stage="answer", config="A", question_id=q["id"],
    )
    tokens_contexto = SESSION_RECORDS[-1]["input_tokens"]   # usage da API na chamada do gerador
    gabarito = set(q["artigos_gabarito"])
    achados = gabarito & set(recuperados)
    return {
        "id": q["id"], "tipo": q["tipo"], "dificuldade": q["dificuldade"],
        "gabarito": q["artigos_gabarito"], "gabarito_em_folha_ruido": gabarito_em_folha_ruido(q),
        "recuperados": recuperados,
        "acerto_recuperacao": achados == gabarito,
        "cobertura": len(achados) / len(gabarito),
        "resposta": resposta,
        "tokens_contexto_gerador": tokens_contexto,
        "custo_usd": sum(r["cost_usd"] for r in SESSION_RECORDS if r["question_id"] == q["id"]),
        "latencia_s": round(time.perf_counter() - t0, 2),
    }


def estimar(chunks: list[dict]):
    chars = sum(len(c["text"]) for c in chunks)
    idx = cost_usd("embedding", chars // 3, 0)
    sistema = len(ANSWER_SYSTEM) + 100
    por_pergunta = (cost_usd("embedding", 40, 0)
                    + cost_usd("gerador_resposta", (CFG["top_k"] * CFG["chunk_size"] + sistema) // 3, 200))
    print(f"{len(chunks)} chunks, {chars:,} chars -> índice ~US$ {idx:.4f} (custo único)")
    print(f"por pergunta ~US$ {por_pergunta:.4f} -> 40 perguntas ~US$ {40 * por_pergunta:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    chunks = gerar_chunks()
    if args.estimate:
        return estimar(chunks)

    coll = indexar(chunks)
    perguntas = amostra(args.limit)
    RESULTS.parent.mkdir(exist_ok=True)
    feitas = {json.loads(l)["id"] for l in RESULTS.open()} if RESULTS.exists() else set()
    resultados = []
    with RESULTS.open("a") as f:   # retoma de onde parou: pula ids já gravados
        for q in perguntas:
            if q["id"] in feitas:
                continue
            r = responder(coll, q)
            resultados.append(r)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()   # grava de fato a cada pergunta (retomada após falha)
            print(f"{r['id']} acerto={r['acerto_recuperacao']} cobertura={r['cobertura']:.2f} "
                  f"US$ {r['custo_usd']:.4f} {r['latencia_s']}s | {r['resposta'][:90]!r}")

    n = len(resultados)
    if not n:
        return print("nada a fazer: todas as perguntas já estavam gravadas")
    custo = sum(r["custo_usd"] for r in resultados)
    lat = sum(r["latencia_s"] for r in resultados)
    print(f"\n{n} perguntas: US$ {custo:.4f}, {lat:.0f}s, acerto de recuperação "
          f"{sum(r['acerto_recuperacao'] for r in resultados)}/{n}")
    if n < len(PERGUNTAS):
        print(f"estimativa para 40: US$ {custo / n * 40:.2f}, ~{lat / n * 40 / 60:.1f} min")


if __name__ == "__main__":
    main()
