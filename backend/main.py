"""Web API + chat page.

    .venv\\Scripts\\uvicorn main:app --app-dir backend --reload
    then open http://127.0.0.1:8000
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from google.genai import errors as genai_errors
from pydantic import BaseModel, Field

from ingest import ROOT
from llm import answer
from retrieval import Retriever

TOP_K = 6
retriever = None


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
    chunks = retriever.search(question, k=TOP_K)
    try:
        result = answer(question, chunks)
    except genai_errors.APIError as e:
        print("Gemini error:", e)
        raise HTTPException(503, "The AI service is busy right now. Please try again in a minute.")
    return {"answer": result["answer"], "sources": merge_sources(result["sources"])}


@app.get("/api/health")
def health():
    return {"ok": True, "chunks": len(retriever.chunks)}


@app.get("/")
def index():
    return FileResponse(ROOT / "frontend/index.html")
