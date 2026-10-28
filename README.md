# RGIPT Assistant

A question-answering chatbot for the [RGIPT](https://rgipt.ac.in) website, built with
retrieval-augmented generation (RAG): it searches the crawled website content and has
Gemini answer only from what it found, with source links.

```
crawl.py → backend/ocr.py → backend/ingest.py → backend/retrieval.py → backend/llm.py → backend/main.py
(scrape)    (scanned PDFs)   (chunk + embed)      (hybrid search)        (Gemini answer)   (API + chat UI)
```

## Setup

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env          # then put your Gemini API key in .env
```

## Run

```
.venv\Scripts\python crawl.py               # 1. download pages + PDFs into data/
.venv\Scripts\python backend\ocr.py         # 2. transcribe scanned PDFs with Gemini (resumable)
.venv\Scripts\python backend\ingest.py      # 3. build chunks.jsonl + chroma_db/
.venv\Scripts\uvicorn main:app --app-dir backend --reload   # 4. start the server
```

Open http://127.0.0.1:8000.

Each step can also be tested on its own:

```
.venv\Scripts\python backend\retrieval.py "who is the director?"   # show retrieved chunks
.venv\Scripts\python backend\llm.py "who is the director?"         # full answer in the terminal
```

## Configuration (`.env`)

| Variable | Default | |
|---|---|---|
| `GEMINI_API_KEY` | — | required |
| `GEMINI_MODEL` | `gemini-3.5-flash` | falls back to `gemini-3.5-flash-lite`, then `gemini-3.1-flash-lite` if busy or rate-limited |

The Gemini free tier has small per-minute and per-day request limits (e.g. only 20/day for
`gemini-3.8-flash`), so a full `eval.py --answers` run uses a noticeable share of the daily quota.

## Evaluation

```
.venv\Scripts\python eval\eval.py             # retrieval only: hit@k and MRR, no API calls
.venv\Scripts\python eval\eval.py --answers   # also checks the generated answers
```

## Known limitations

- About 285 of the 371 crawled PDFs are scanned images. `ocr.py` transcribes them with Gemini
  (one API call per PDF, most useful first); any not yet transcribed are indexed by title only.
- Answers are only as current as the last crawl.
