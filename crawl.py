# crawl.py
import time, json, hashlib, requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

BASE = "https://rgipt.ac.in"
SEEDS = [
    "/en/page/admission-zone", "/en/page/programmes", "/en/page/ordinances",
    "/en/page/course-structure", "/en/page/academic-calendar-1",
    "/en/page/semester-fee-structures", "/en/page/academic-scholarship-financial-assistant",
    "/en/page/freshers-faq", "/en/page/hostels-", "/en/page/amenities",
    "/en/page/rgipt-placement-status", "/en/page/overview-tp-eib",
    "/en/page/academic-notification", "/en/page/student-downloads",
    "/en/page/institute-policies", "/en/page/grievance-cell",
]
HEADERS = {"User-Agent": "RGIPT-RAG-student-project (contact: your@email)"}
seen, queue, out = set(), [urljoin(BASE, s) for s in SEEDS], []

while queue and len(seen) < 400:
    url = queue.pop(0)
    if url in seen or urlparse(url).netloc != "rgipt.ac.in":
        continue
    seen.add(url)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
    except requests.RequestException:
        continue
    ctype = r.headers.get("content-type", "")
    doc_id = hashlib.md5(url.encode()).hexdigest()[:10]
    if "pdf" in ctype:
        open(f"data/raw/{doc_id}.pdf", "wb").write(r.content)
        out.append({"id": doc_id, "url": url, "type": "pdf"})
    elif "html" in ctype:
        soup = BeautifulSoup(r.text, "html.parser")
        for t in soup(["script", "style", "nav", "footer"]):
            t.decompose()
        text = soup.get_text("\n", strip=True)
        out.append({"id": doc_id, "url": url, "type": "html",
                    "title": soup.title.string if soup.title else "", "text": text})
        for a in soup.find_all("a", href=True):
            link = urljoin(url, a["href"]).split("#")[0]
            if "/en/page/" in link or link.lower().endswith(".pdf"):
                queue.append(link)
    time.sleep(1.5)  # be gentle

json.dump(out, open("data/processed/pages.json", "w"), ensure_ascii=False, indent=1)
print(f"Crawled {len(out)} documents")