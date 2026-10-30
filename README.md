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

Or with Docker (after steps 1–3, since the image ships the built index, not the raw data):

```
docker compose up --build       # then open http://localhost:8000
```

The API key is read from `.env` when the container starts; it is never copied into the image.

## Sharing a public demo link

Free option, no account needed. The bot stays on this computer, so the link only works while
the computer, Docker and this command are running, and the address changes each time:

```
cloudflared tunnel --url http://localhost:8000
```

Hugging Face Docker Spaces now need a paid plan, so `deploy_hf.py` only works on a PRO account.

## Adding the chat to a website

One line before `</body>` adds an "Ask RGIPT" button that opens the chat in a popup:

```html
<script src="https://YOUR-BOT-ADDRESS/widget.js" defer></script>
```

`/demo` shows it on a sample page.

## Limits and usage

- Repeat questions are answered from an in-memory cache and use no Gemini quota.
- New questions are limited per visitor to 8 a minute and 100 a day (`LIMITS` in `backend/main.py`).
- `/api/health` shows usage totals. Only counts are kept, never questions or visitor details.

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
  Gemini occasionally returns nothing for a PDF; those are not saved, so re-running `ocr.py`
  retries them.
- Answers are only as current as the last crawl.
