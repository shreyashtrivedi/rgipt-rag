"""Hybrid search over the chunks built by ingest.py.

    python backend/retrieval.py "who is the director?"

Two retrievers, merged with Reciprocal Rank Fusion (RRF):
  - vector search (Chroma + bge embeddings): finds chunks with the same *meaning*
  - BM25 keyword search: finds chunks with the same *words* (names, "JEE", "M.Tech", ...)
Then a cross-encoder reranker re-scores the top fused candidates: it reads the question and
each chunk together, which is far more accurate than comparing embeddings, but too slow to
run on every chunk.
"""
import re, sys, json

import chromadb
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer

from ingest import CHUNKS, CHROMA_DIR, COLLECTION, EMBED_MODEL, QUERY_PREFIX

CANDIDATES = 20   # how many results each retriever contributes before fusion
RRF_K = 60        # standard RRF constant; higher = flatter weighting across ranks
# Off by default. Measured with eval.py (33 questions, CPU):
#   none                                    hit@6 94%  MRR 0.807  0.03 s/query
#   cross-encoder/ms-marco-MiniLM-L-6-v2    hit@6 94%  MRR 0.828  0.6 s/query  (pool 15)
#   BAAI/bge-reranker-base                  hit@6 94%  MRR 0.851  3.0 s/query  (pool 15)
# Reranking only reorders the top 6 slightly, and the LLM reads all 6 anyway, so it isn't
# worth the latency yet. Revisit if the eval set grows and hit@6 drops.
RERANK_MODEL = None
RERANK_POOL = 15  # how many fused candidates the reranker re-scores

STOPWORDS = set("""a an the is are was were be been of in on at to for from by with and or
not what which who whom how when where why do does did can could i me my we our you your
it its this that these those there here about as into rgipt please tell""".split())


def tokenize(text):
    return [t for t in re.findall(r"\w+", text.lower()) if t not in STOPWORDS]


class Retriever:
    def __init__(self, reranker=RERANK_MODEL, pool=RERANK_POOL):
        """reranker: a cross-encoder model name, or None to use hybrid search alone.
        pool: how many fused candidates the reranker re-scores (fewer = faster)."""
        self.pool = pool
        self.chunks = [json.loads(l) for l in open(CHUNKS, encoding="utf-8")]
        self.by_id = {c["id"]: c for c in self.chunks}
        self.bm25 = BM25Okapi([tokenize(c["text"]) for c in self.chunks])
        self.model = SentenceTransformer(EMBED_MODEL)
        self.col = chromadb.PersistentClient(path=str(CHROMA_DIR)).get_collection(COLLECTION)
        self.reranker = CrossEncoder(reranker, max_length=512) if reranker else None

    def vector_search(self, query, n=CANDIDATES):
        emb = self.model.encode([QUERY_PREFIX + query], normalize_embeddings=True)
        res = self.col.query(query_embeddings=emb.tolist(), n_results=n)
        return res["ids"][0]

    def keyword_search(self, query, n=CANDIDATES):
        scores = self.bm25.get_scores(tokenize(query))
        top = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)[:n]
        return [self.chunks[i]["id"] for i in top if scores[i] > 0]

    def search(self, query, k=5):
        """Returns the top-k chunks (dicts from chunks.jsonl) with an added 'score'."""
        fused = {}
        for ranked in (self.vector_search(query), self.keyword_search(query)):
            for rank, cid in enumerate(ranked):
                fused[cid] = fused.get(cid, 0) + 1 / (RRF_K + rank + 1)
        if not self.reranker:
            best = sorted(fused, key=fused.get, reverse=True)[:k]
            return [{**self.by_id[cid], "score": round(fused[cid], 4)} for cid in best]

        pool = sorted(fused, key=fused.get, reverse=True)[:self.pool]
        scores = self.reranker.predict([(query, self.by_id[cid]["text"]) for cid in pool])
        ranked = sorted(zip(pool, scores), key=lambda p: p[1], reverse=True)[:k]
        return [{**self.by_id[cid], "score": round(float(s), 4)} for cid, s in ranked]


if __name__ == "__main__":
    questions = sys.argv[1:] or [
        "Who is the director of RGIPT?",
        "What B.Tech programs are offered?",
        "How do I get admission to M.Tech?",
        "hostel fee",
        "placement statistics",
        "Where is the campus located?",
    ]
    r = Retriever()
    for q in questions:
        print(f"\nQ: {q}")
        for c in r.search(q):
            snippet = c["text"][len(c["title"]):].strip().replace("\n", " ")[:100]
            print(f"  {c['score']:.4f} [{c['title'][:45]}] {snippet}")
            print(f"         {c['url']}" + (f"  (p.{c['page']})" if c["page"] else ""))
