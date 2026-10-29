"""Web API + chat page.

    .venv\\Scripts\\uvicorn main:app --app-dir backend --reload
    then open http://127.0.0.1:8000
"""
import re, threading
from collections import OrderedDict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from google.genai import errors as genai_errors
from pydantic import BaseModel, Field

from ingest import ROOT
from llm import answer
from retrieval import Retriever

TOP_K = 6
CACHE_SIZE = 1000   # answers kept in memory; a restart (e.g. a redeploy with a new index) clears them
retriever = None


class AnswerCache:
    """Saves Gemini quota: the same question (ignoring case, spacing and trailing punctuation)
    gets the stored answer. Exact match only -- "fee 2025-26" and "fee 2026-27" must not
    share an answer, which a similarity-based cache could get wrong."""

    def __init__(self, size):
        self.size, self.items, self.lock = size, OrderedDict(), threading.Lock()

    @staticmethod
    def key(question):
        return re.sub(r"[\s?.!]+$", "", " ".join(question.lower().split()))

    def get(self, question):
        with self.lock:
            k = self.key(question)
            if k in self.items:
                self.items.move_to_end(k)   # least recently used is evicted first
                return self.items[k]

    def put(self, question, result):
        with self.lock:
            self.items[self.key(question)] = result
            if len(self.items) > self.size:
                self.items.popitem(last=False)


cache = AnswerCache(CACHE_SIZE)


@asynccontextmanager
async def lifespan(app):
    global retriever
    retriever = Retriever()   # loads the embedding model + indexes once, at startup
    yield


app = FastAPI(title="RGIPT Assistant", lifespan=lifespan)


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=500)


def merge_sources(sources):
    """Several cited chunks can come from the same page; show each page once,
    keeping all the citation numbers that point to it."""
    merged = {}
    for s in sources:
        key = (s["url"], s["page"])
        if key in merged:
            merged[key]["ns"].append(s["n"])
        else:
            merged[key] = {"ns": [s["n"]], "title": s["title"], "url": s["url"], "page": s["page"]}
    return list(merged.values())


# Plain `def` (not async): retrieval and the Gemini call are blocking, so FastAPI
# runs this in a worker thread and the server stays responsive.
@app.post("/api/ask")
def ask(q: Question):
    question = q.question.strip()
    if cached := cache.get(question):
        return cached
    chunks = retriever.search(question, k=TOP_K)
    try:
        result = answer(question, chunks)
    except genai_errors.APIError as e:   # errors are not cached, so a retry can succeed
        print("Gemini error:", e)
        raise HTTPException(503, "The AI service is busy right now. Please try again in a minute.")
    response = {"answer": result["answer"], "sources": merge_sources(result["sources"])}
    cache.put(question, response)
    return response


@app.get("/api/health")
def health():
    return {"ok": True, "chunks": len(retriever.chunks), "cached_answers": len(cache.items)}


@app.get("/")
def index():
    return FileResponse(ROOT / "frontend/index.html")


@app.get("/widget.js")
def widget():
    return FileResponse(ROOT / "frontend/widget.js", media_type="text/javascript")


@app.get("/demo")
def demo():
    """A stand-in host page showing the widget the way the college site would include it."""
    return FileResponse(ROOT / "frontend/demo.html")
