"""Build the search indexes from the crawled data.

    python backend/ingest.py                  # with generated search questions (questions.py)
    python backend/ingest.py --no-questions   # no API calls

Reads  data/processed/pages.json + data/raw/*.pdf
Writes data/processed/chunks.jsonl  (all chunks, used for BM25 keyword search)
       chroma_db/                   (vector index, used for semantic search)
Safe to re-run: the Chroma collection is rebuilt from scratch each time.
"""
import re, sys, json, hashlib
from pathlib import Path

import pymupdf
import chromadb
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "data/processed/pages.json"
CHUNKS = ROOT / "data/processed/chunks.jsonl"
CHROMA_DIR = ROOT / "chroma_db"
COLLECTION = "rgipt"

EMBED_MODEL = "BAAI/bge-small-en-v1.5"   # small, fast on CPU, good English retrieval
# bge models expect this prefix on *queries* (not on documents) -- used in retrieval.py
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

CHUNK_CHARS = 1200       # ~300 tokens; bge-small truncates at 512 tokens
OVERLAP_CHARS = 200      # carried over so a fact split across chunks isn't lost
MIN_CHARS_PER_PAGE = 50  # below this, a PDF is treated as scanned (image-only)

TITLE_PREFIX = re.compile(r"^Official Website of Rajiv Gandhi Institute.*?/\s*", re.I)


def clean(text):
    text = text.replace("�", " ").replace("\xa0", " ")
    lines = (" ".join(l.split()) for l in text.split("\n"))
    return "\n".join(l for l in lines if l)


def chunk_text(text):
    """Split on line boundaries into ~CHUNK_CHARS pieces, with a small overlap."""
    chunks, cur = [], ""
    for line in text.split("\n"):
        while len(line) > CHUNK_CHARS:           # a single giant line (e.g. a table dump)
            chunks.append(line[:CHUNK_CHARS])
            line = line[CHUNK_CHARS - OVERLAP_CHARS:]
        if cur and len(cur) + len(line) + 1 > CHUNK_CHARS:
            chunks.append(cur)
            cur = cur[-OVERLAP_CHARS:].split("\n", 1)[-1]   # overlap, starting at a line break
        cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def html_sections(doc):
    title = TITLE_PREFIX.sub("", doc.get("title", "")).strip() or doc["label"]
    return title, [(None, clean(doc["text"]))], False


def pdf_sections(doc):
    """Returns (title, [(page_no, text)], scanned)."""
    title = doc["label"] or Path(doc["url"]).stem
    try:
        with pymupdf.open(ROOT / doc["file"]) as pdf:
            pages = [(i + 1, clean(p.get_text())) for i, p in enumerate(pdf)]
    except Exception as e:
        print("  unreadable PDF:", doc["url"], e)
        pages = []
    total = sum(len(t) for _, t in pages)
    if total < MIN_CHARS_PER_PAGE * max(1, len(pages)):
        # Scanned PDF: no usable text. Index its label so the bot can at least point to it.
        # TODO: OCR these later.
        stub = f"{title}\n(Scanned PDF document - text not extracted. Parent page: {doc['parent']})"
        return title, [(None, stub)], True
    return title, [(n, t) for n, t in pages if t], False


def build_chunks(docs):
    chunks, seen = [], set()
    stats = {"html": 0, "pdf_text": 0, "pdf_scanned": 0, "duplicates": 0}
    for doc in docs:
        if doc["type"] == "html":
            title, sections, scanned = html_sections(doc)
            stats["html"] += 1
        else:
            title, sections, scanned = pdf_sections(doc)
            stats["pdf_scanned" if scanned else "pdf_text"] += 1

        for page, text in sections:
            for piece in chunk_text(text):
                h = hashlib.md5(piece.encode()).hexdigest()
                if h in seen:            # same text reachable from several URLs
                    stats["duplicates"] += 1
                    continue
                seen.add(h)
                chunks.append({
                    "id": f"{doc['id']}-{len(chunks)}",
                    # Title is prepended so each chunk carries its own context when embedded
                    "text": f"{title}\n{piece}" if not piece.startswith(title) else piece,
                    "url": doc["url"],
                    "title": title,
                    "type": doc["type"],
                    "page": page or 0,          # Chroma metadata can't be None
                    "scanned": scanned,
                })
    return chunks, stats


def index_text(chunk):
    """What search matches against: the chunk text plus any generated questions.
    (The answering model only ever sees chunk["text"].)"""
    qs = chunk.get("questions")
    return chunk["text"] + ("\nQuestions answered: " + " ".join(qs) if qs else "")


def main():
    docs = json.load(open(PAGES, encoding="utf-8"))
    chunks, stats = build_chunks(docs)
    print(f"{len(docs)} docs -> {len(chunks)} chunks  {stats}")
    if "--no-questions" not in sys.argv:
        from questions import add_questions   # imported here: questions.py imports this module
        add_questions(chunks)

    with open(CHUNKS, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print("wrote", CHUNKS.relative_to(ROOT))

    print(f"embedding with {EMBED_MODEL} (first run downloads the model)...")
    model = SentenceTransformer(EMBED_MODEL)
    vectors = model.encode([index_text(c) for c in chunks], batch_size=32,
                           normalize_embeddings=True, show_progress_bar=True)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    if COLLECTION in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION)
    col = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    B = 1000
    for i in range(0, len(chunks), B):
        batch = chunks[i:i + B]
        col.add(ids=[c["id"] for c in batch],
                documents=[c["text"] for c in batch],
                embeddings=vectors[i:i + B].tolist(),
                metadatas=[{k: c[k] for k in ("url", "title", "type", "page", "scanned")}
                           for c in batch])
    print(f"stored {col.count()} vectors in {CHROMA_DIR.relative_to(ROOT)}/{COLLECTION}")


if __name__ == "__main__":
    main()
