"""Generate likely user questions for chunks, to help search find them.

Short pages like Contact Us are lists of addresses and phone numbers that share no words with
how people actually ask ("how do I contact the placement cell?"). Gemini writes a few questions
each chunk answers; ingest.py indexes them together with the chunk text. They are used for
search only -- the answering model never sees them.

Results are cached by chunk text in data/processed/questions.json, so re-running ingest.py
only calls the API for new or changed chunks.
"""
import json, time, hashlib
from collections import Counter

from google.genai.errors import APIError

from ingest import ROOT
from llm import generate

CACHE = ROOT / "data/processed/questions.json"
MODEL = "gemini-3.5-flash-lite"   # an easy task; keeps the answering model's quota free
BATCH = 20                        # chunks per API call
MAX_CHUNKS_PER_PAGE = 8           # longer pages are big lists (all publications, all faculty...)

SYSTEM_PROMPT = """You help build a search index for the RGIPT college website.
For each numbered passage, write 3 to 5 short questions that a student, applicant or visitor
might type into a chatbot and that the passage answers. Use natural, everyday wording, and
avoid copying the passage's own phrasing (e.g. "how do I contact the placement cell?" for a
list of phone numbers). Only ask about facts that are actually in the passage.
Return JSON: {"1": ["question", ...], "2": [...], ...}"""


def cache_key(chunk):
    return hashlib.md5(chunk["text"].encode()).hexdigest()


def add_questions(chunks):
    """Sets chunk["questions"] on HTML chunks from short pages, calling Gemini only for
    chunks that aren't cached yet."""
    cache = json.load(open(CACHE, encoding="utf-8")) if CACHE.exists() else {}
    per_page = Counter(c["url"] for c in chunks if c["type"] == "html")
    eligible = [c for c in chunks if c["type"] == "html" and per_page[c["url"]] <= MAX_CHUNKS_PER_PAGE]
    todo = [c for c in eligible if cache_key(c) not in cache]

    if todo:
        print(f"generating questions for {len(todo)} chunks "
              f"({-(-len(todo) // BATCH)} API calls, cached for next time)...")
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        prompt = "\n\n---\n\n".join(f"[{n}] {c['text']}" for n, c in enumerate(batch, 1))
        try:
            out = json.loads(generate(prompt, SYSTEM_PROMPT, model=MODEL, temperature=0.4,
                                      json_output=True))
        except APIError as e:
            print(f"  stopping: API error {e.code}. Re-run ingest.py later to fill in the rest.")
            break
        except json.JSONDecodeError:
            print("  bad JSON for one batch, skipping it (it will be retried next run)")
            continue
        for n, c in enumerate(batch, 1):
            qs = out.get(str(n))
            if isinstance(qs, list):
                cache[cache_key(c)] = [str(q) for q in qs][:5]
        # save after every batch so an interrupted run doesn't lose progress
        json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  {min(i + BATCH, len(todo))}/{len(todo)}")
        time.sleep(4)   # stay under the free tier's per-minute limit

    for c in eligible:
        if cache_key(c) in cache:
            c["questions"] = cache[cache_key(c)]
    print(f"{sum('questions' in c for c in chunks)} chunks have generated questions")
