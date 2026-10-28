"""Answer a question with Gemini, using only the chunks found by retrieval.py.

    python backend/llm.py "what is the hostel fee?"
"""
import os, re, sys

from dotenv import load_dotenv
from google import genai
from google.genai import types

from ingest import ROOT

load_dotenv(ROOT / ".env")
# gemini-3.8-flash is newer but its free tier allows only 20 requests/day.
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
# Tried in order when the model above has a server error (5xx) or is rate-limited (429).
# Each model has its own free-tier quota.
FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]

SYSTEM_PROMPT = """You are the help assistant for RGIPT (Rajiv Gandhi Institute of Petroleum
Technology, Jais, Amethi). You answer questions from students, applicants and visitors.

Rules:
- Answer ONLY from the numbered context passages. Never use outside knowledge about RGIPT,
  and never guess fees, dates, cutoffs, names or numbers.
- Cite the passages you used with their numbers in square brackets, e.g. [1] or [2][4].
- If the passages don't contain the answer, say so plainly in one sentence and, if a passage
  looks related (e.g. a scanned PDF or a page that links to documents), point the user to it.
- Each passage says whether it is a current website page or a PDF document (with its date when
  known). PDFs can be years old. When passages disagree (e.g. different people named for the
  same post), trust the website page over a PDF, and a newer document over an older one.
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


DATE_PATTERNS = [
    # upload timestamp: .../siteContent/202509101015457632... or .../C_202607131456537785.pdf
    (re.compile(r"(?<!\d)(20[0-3]\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{6,}"), "ymd"),
    # date in the file name: ..._19-03-2021.pdf or ..._10092025.pdf
    (re.compile(r"(0[1-9]|[12]\d|3[01])-?(0[1-9]|1[0-2])-?(20[0-3]\d)\.pdf$", re.I), "dmy"),
]


def pdf_date(url):
    """Publication date of a PDF guessed from its URL ("YYYY-MM-DD"), or None.
    Year-only names like EV_2025.pdf are skipped: there the year is a student batch."""
    for pattern, order in DATE_PATTERNS:
        m = pattern.search(url)
        if m:
            y, mo, d = m.groups() if order == "ymd" else m.groups()[::-1]
            return f"{y}-{mo}-{d}"
    return None


def source_kind(chunk):
    if chunk["type"] == "html":
        return "website page (current)"
    date = pdf_date(chunk["url"])
    return f"PDF document dated {date}" if date else "PDF document (date unknown)"


def format_context(chunks):
    blocks = []
    for i, c in enumerate(chunks, 1):
        src = c["url"] + (f" (page {c['page']})" if c["page"] else "")
        blocks.append(f"[{i}] {c['title']}\nSource: {src}\nType: {source_kind(c)}\n{c['text']}")
    return "\n\n---\n\n".join(blocks)


def generate(prompt, system, model=MODEL, temperature=0.2, json_output=False):
    """One Gemini call, falling back to FALLBACK_MODELS when `model` is busy or rate-limited."""
    config = types.GenerateContentConfig(
        system_instruction=system, temperature=temperature,
        response_mime_type="application/json" if json_output else None)
    models = [model] + [m for m in FALLBACK_MODELS if m != model]
    for i, m in enumerate(models):
        try:
            resp = client().models.generate_content(model=m, contents=prompt, config=config)
            return (resp.text or "").strip()
        except genai.errors.APIError as e:
            if not (e.code == 429 or e.code >= 500) or i == len(models) - 1:
                raise
            print(f"  {m} unavailable ({e.code}), trying {models[i + 1]}", file=sys.stderr)


def answer(question, chunks):
    """Returns {"answer": str, "sources": [{"n", "title", "url", "page"}]} --
    sources are only the passages the model actually cited."""
    prompt = f"Context passages:\n\n{format_context(chunks)}\n\nQuestion: {question}"
    text = generate(prompt, SYSTEM_PROMPT)
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
