"""Measure retrieval and answer quality on the questions in golden.jsonl.

    python eval/eval.py              # retrieval only (fast, no API calls)
    python eval/eval.py --answers    # also generate answers with Gemini and check them

golden.jsonl, one question per line:
  q       the question
  urls    pages that contain the answer (a retrieved chunk "hits" if its URL ends with one)
  must    regexes (case-insensitive) that must ALL appear in a correct answer; use | for alternatives
  refuse  true if the answer is NOT in the data and the bot should say it doesn't know
"""
import re, sys, json, time, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from retrieval import Retriever

GOLDEN = Path(__file__).resolve().parent / "golden.jsonl"
REFUSAL = re.compile(
    r"(do(es)?n['’]?t|do(es)? not) (contain|have|include|mention|provide|specify)|"
    r"not (available|mentioned|found|provided|specified|included)|no (information|details|mention)|"
    r"unable to|can(not|['’]t) (find|answer)|could(n['’]t| not) find", re.I)


def first_hit(chunks, urls):
    """1-based rank of the first chunk from an expected page, or None."""
    for rank, c in enumerate(chunks, 1):
        if any(c["url"].endswith(u) for u in urls):
            return rank
    return None


def check_answer(item, text):
    if item.get("refuse"):
        return bool(REFUSAL.search(text)), "should refuse"
    missing = [p for p in item["must"] if not re.search(p, text, re.I)]
    return not missing, ("missing " + ", ".join(missing)) if missing else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", action="store_true", help="also generate and check answers (uses the Gemini API)")
    ap.add_argument("-k", type=int, default=6, help="chunks retrieved per question (default 6, same as the app)")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between Gemini calls, to stay under rate limits")
    args = ap.parse_args()

    items = [json.loads(l) for l in open(GOLDEN, encoding="utf-8") if l.strip()]
    retriever = Retriever()
    if args.answers:
        from llm import answer

    hits = rr = answered = correct = 0
    retrieval_items = [it for it in items if it["urls"]]
    failures = []
    for i, item in enumerate(items, 1):
        chunks = retriever.search(item["q"], k=args.k)
        line = f"{i:2}. {item['q'][:60]:60}"
        if item["urls"]:
            rank = first_hit(chunks, item["urls"])
            hits += rank is not None
            rr += 1 / rank if rank else 0
            line += f"  retrieval: {'#' + str(rank) if rank else 'MISS':4}"
            if not rank:
                failures.append((item["q"], "retrieval miss", [c["url"] for c in chunks[:3]]))
        else:
            line += " " * 17
        if args.answers:
            if answered:
                time.sleep(args.delay)
            text = answer(item["q"], chunks)["answer"]
            ok, why = check_answer(item, text)
            answered += 1
            correct += ok
            line += f"  answer: {'ok' if ok else 'FAIL'}"
            if not ok:
                failures.append((item["q"], why, text[:300]))
        print(line, flush=True)

    n = len(retrieval_items)
    print(f"\nRetrieval hit@{args.k}: {hits}/{n} = {hits / n:.0%}   MRR: {rr / n:.3f}")
    if args.answers:
        print(f"Answer accuracy: {correct}/{answered} = {correct / answered:.0%}")
    if failures:
        print("\nFailures:")
        for q, why, detail in failures:
            print(f"- {q}\n    {why}\n    {detail}")


if __name__ == "__main__":
    main()
