# Serves the chatbot (backend/main.py + frontend/). The search index is built outside the
# image (crawl.py -> ocr.py -> ingest.py) and copied in, so build it before `docker build`.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.hf

WORKDIR /app

# CPU-only PyTorch first: the default wheel bundles ~2 GB of CUDA libraries we don't use
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt

# Download the embedding model at build time so the container starts offline and fast
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"
ENV HF_HUB_OFFLINE=1

COPY backend backend
COPY frontend frontend
COPY data/processed/chunks.jsonl data/processed/chunks.jsonl
COPY chroma_db chroma_db

# Run as a normal user; it needs write access to chroma_db (Chroma keeps a lock file there)
RUN useradd --create-home app && chown -R app /app
USER app

# GEMINI_API_KEY is passed at run time (docker run --env-file .env), never baked in.
# Hosting platforms set $PORT; 8000 locally.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}"]
