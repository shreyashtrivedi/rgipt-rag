"""Answer a question with Gemini, using only the chunks found by retrieval.py.

    python backend/llm.py "what is the hostel fee?"
"""
import os, re, sys

from dotenv import load_dotenv
from google import genai
from google.genai import types

from ingest import ROOT

load_dotenv(ROOT / ".env")
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
# Tried in order when the model above has a server error (5xx) or is rate-limited (429)
FALLBACK_MODELS = ["gemini-3.5-flash", "gemini-2.5-flash"]

SYSTEM_PROMPT = """You are the help assistant for RGIPT (Rajiv Gandhi Institute of Petroleum
Technology, Jais, Amethi). You answer questions from students, applicants and visitors.

Rules:
- Answer ONLY from the numbered context passages. Never use outside knowledge about RGIPT,
  and never guess fees, dates, cutoffs, names or numbers.
- Cite the passages you used with their numbers in square brackets, e.g. [1] or [2][4].
- If the passages don't contain the answer, say so plainly in one sentence and, if a passage
  looks related (e.g. a scanned PDF or a page that links to documents), point the user to it.
- Information may be outdated; if a passage is clearly for a specific year, mention the year.
- Be concise: a short paragraph or a few bullet points. No preamble."""

_client = None


def client():
    global _client
    if _client is None:
        # Reads GEMINI_API_KEY from the environment. The SDK's default retries (5 attempts,
        # up to 60s apart) are too slow for a chatbot; retry briefly, then fall back to another model.
        _client = genai.Client(http_options=types.HttpOptions(
            timeout=60_000,
            retry_options=types.HttpRetryOptions(attempts=2, initial_delay=1, max_delay=4)))
    return _client


def format_context(chunks):
    blocks = []
    for i, c in enumerate(chunks, 1):
        src = c["url"] + (f" (page {c['page']})" if c["page"] else "")
        blocks.append(f"[{i}] {c['title']}\nSource: {src}\n{c['text']}")
    return "\n\n---\n\n".join(blocks)


def answer(question, chunks):
    """Returns {"answer": str, "sources": [{"n", "title", "url", "page"}]} --
    sources are only the passages the model actually cited."""
    prompt = f"Context passages:\n\n{format_context(chunks)}\n\nQuestion: {question}"
    config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=0.2)
    models = [MODEL] + [m for m in FALLBACK_MODELS if m != MODEL]
    for i, model in enumerate(models):
        try:
            resp = client().models.generate_content(model=model, contents=prompt, config=config)
            break
        except genai.errors.APIError as e:
            if not (e.code == 429 or e.code >= 500) or i == len(models) - 1:
                raise
            print(f"  {model} unavailable ({e.code}), trying {models[i + 1]}", file=sys.stderr)
    text = (resp.text or "").strip()
    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", text) if 0 < int(n) <= len(chunks)})
    sources = [{"n": n, "title": chunks[n - 1]["title"], "url": chunks[n - 1]["url"],
                "page": chunks[n - 1]["page"]} for n in cited]
    return {"answer": text, "sources": sources}


if __name__ == "__main__":
    from retrieval import Retriever

    questions = sys.argv[1:] or [
        "Who is the director of RGIPT?",
        "How do I get admission to M.Tech?",
        "What is the hostel fee?",
        "Where is the campus located?",
    ]
    r = Retriever()
    for q in questions:
        result = answer(q, r.search(q, k=6))
        print(f"\nQ: {q}\n{result['answer']}")
        for s in result["sources"]:
            print(f"  [{s['n']}] {s['title'][:50]} - {s['url']}" + (f" p.{s['page']}" if s["page"] else ""))
