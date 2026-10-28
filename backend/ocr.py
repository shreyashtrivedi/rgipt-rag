"""Transcribe scanned PDFs (no text layer) with Gemini, so ingest.py can index them.

    python backend/ocr.py            # all scanned PDFs, most useful first
    python backend/ocr.py --limit 20

Writes data/processed/ocr/<doc id>.md, one per PDF, with "=== Page N ===" markers and tables
as Markdown. Already-transcribed PDFs are skipped, so the script can be stopped and re-run at
any time -- e.g. when the free tier's daily quota runs out, just run it again tomorrow.
Afterwards, re-run ingest.py to index the new text.
"""
import re, sys, json, time, argparse

from google.genai import types
from google.genai.errors import APIError

from ingest import PAGES, ROOT, OCR_DIR, pdf_text_pages, is_scanned
from llm import generate

MODEL = "gemini-3.5-flash-lite"
MAX_BYTES = 18_000_000   # Gemini's inline request limit is 20 MB

# PDFs whose label/URL matches this are transcribed first: they answer the most common questions
PRIORITY = re.compile(r"fee|admission|calendar|scholarship|hostel|placement|notice|circular|"
                      r"brochure|ordinance|rules|policy|curriculum|syllabus|exam|result", re.I)

SYSTEM_PROMPT = """You transcribe scanned documents from the RGIPT college website.
- Transcribe all the text faithfully. Never summarise, correct or invent anything.
- Start each page with a line "=== Page N ===" (N = page number, starting at 1).
- Render tables as Markdown tables, keeping every row and column header.
- If the same text appears in both Hindi and English, transcribe only the English.
  Hindi-only text should be transcribed as it is.
- Plain text only, no LaTeX or math notation: write "8th August", not superscripts.
- Skip signatures, stamps and logos. Output only the transcription."""

# Safety net for LaTeX the model still produces, e.g. "$08^{\text{th}}$" -> "08th"
LATEX_SUPERSCRIPT = re.compile(r"\$?(\d*)\s*\^\{\\text\{(\w+)\}\}\s*\$?")


def tidy(text):
    return LATEX_SUPERSCRIPT.sub(r"\1\2", text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="transcribe at most this many PDFs in this run")
    args = ap.parse_args()
    OCR_DIR.mkdir(parents=True, exist_ok=True)

    docs = [d for d in json.load(open(PAGES, encoding="utf-8")) if d["type"] == "pdf"]
    todo = [d for d in docs
            if not (OCR_DIR / f"{d['id']}.md").exists() and is_scanned(pdf_text_pages(d))]
    todo.sort(key=lambda d: not PRIORITY.search(d["label"] + " " + d["url"]))  # priority first
    done = len(list(OCR_DIR.glob("*.md")))
    print(f"{len(todo)} scanned PDFs to transcribe ({done} already done)")
    if args.limit:
        todo = todo[:args.limit]

    for i, d in enumerate(todo, 1):
        data = (ROOT / d["file"]).read_bytes()
        if len(data) > MAX_BYTES:
            print(f"  skipping (too large, {len(data) // 1_000_000} MB): {d['label'][:60]}")
            continue
        prompt = [types.Part.from_bytes(data=data, mime_type="application/pdf"),
                  "Transcribe this document."]
        try:
            text = generate(prompt, SYSTEM_PROMPT, model=MODEL, temperature=0)
        except APIError as e:
            print(f"Stopped: API error {e.code} ({len(todo) - i + 1} left). "
                  f"Re-run later to continue -- finished PDFs are kept.")
            break
        text = tidy(text or "")
        if not text.strip():   # model returned nothing (blocked/overloaded): leave it for a re-run
            print(f"  [{i}/{len(todo)}] empty response, will retry next run: {d['label'][:60]}")
            continue
        (OCR_DIR / f"{d['id']}.md").write_text(text, encoding="utf-8")
        print(f"  [{i}/{len(todo)}] {len(text):6} chars  {d['label'][:70]}", flush=True)
        time.sleep(4)   # stay under the free tier's per-minute limit

    print("\nNow run: python backend/ingest.py")


if __name__ == "__main__":
    main()
