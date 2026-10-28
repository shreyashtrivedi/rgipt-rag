import re, json, time, hashlib, requests
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode, quote
from bs4 import BeautifulSoup

BASE = "https://rgipt.ac.in"
HEADERS = {"User-Agent": "RGIPT-RAG-student-project (contact: trivedishreyash621@gmail.com)"}
DELAY = 1.5
MAX_DOCS = 600      # set to 20 for a quick test
MAX_DEPTH = 1       # 0 = seeds only, 1 = seeds + pages/PDFs they link to

RAW = Path("data/raw"); RAW.mkdir(parents=True, exist_ok=True)
PROC = Path("data/processed"); PROC.mkdir(parents=True, exist_ok=True)

EXTRA_SEEDS = [
    "/en/page/admission-zone",
    "/en/news?Newslistslug=en-latest-news",
    "/en/news?Newslistslug=en-training-and-placement",
    "/en/page/seminar-talk-all",
    "/en/page/study-in-india",
    "/en/page/home-alumni",
    "/en/page/conferences-symposia-workshops",
]

# Pages that are noise for a student Q&A bot (adjust as you like)
SKIP = re.compile(
    r"tender|quotation|auction|recruit|temporary-research|project-assistants|"
    r"gallery|photo|video|faculty/Faculty|rgipterp|portal\.rgipt|gst|"
    r"minutes-of-meetings|immovable-property|/en/page/results$|"
    r"screen-reader|/sitemap|home-hi", re.I)

BAD_EXT = (".jpg", ".jpeg", ".png", ".gif", ".css", ".js", ".docx", ".doc",
           ".xlsx", ".xls", ".zip", ".mp4", ".ico", ".svg")

# The site serves these instead of a 404; indexing them only adds noise
NO_CONTENT = re.compile(r"^(Global Page Error|Content not available)", re.I)
LABEL_SUFFIX = re.compile(r"\s*(\[ ?News ?\]|\[?view\]?)\s*$", re.I)   # "... View", "... [ News ]"
TITLE_PREFIX = re.compile(r"^Official Website of Rajiv Gandhi Institute.*?/\s*", re.I)


def normalize(url):
    p = urlparse(url)
    # drop tracking/breadcrumb params that create duplicate URLs
    q = [(k, v) for k, v in parse_qsl(p.query) if k not in ("cd", "brd")]
    path = quote(p.path, safe="/%()-_.,~")   # fix spaces in PDF URLs
    return urlunparse((p.scheme, p.netloc, path, "", urlencode(q), ""))


def wanted(url):
    p = urlparse(url)
    if p.netloc != "rgipt.ac.in" or SKIP.search(url):
        return False
    path = p.path.lower()
    if path.endswith(BAD_EXT):
        return False
    return path.endswith(".pdf") or p.path.startswith(
        ("/en/page/", "/en/news", "/en/archivednews", "/article/en/"))


def text_of(tag):
    return " ".join(tag.get_text(" ", strip=True).split())


def link_label(a, section):
    """Table-row text if the link is in a table, else the link text.
    A row with links to several files ("Registration Forms | For UG | For PG") gets the other
    links' text removed, and a vague label ("Undergraduate") is prefixed with the page's section
    ("Academics / Ordinances: Undergraduate")."""
    row = a.find_parent("tr")
    if row is None:
        label = text_of(a)
    else:
        label = text_of(row)
        for other in row.find_all("a", href=True):
            if other["href"] != a["href"] and text_of(other):
                label = label.replace(text_of(other), " ", 1)
    label = LABEL_SUFFIX.sub("", " ".join(label.split()))
    if len(label.split()) <= 2 and section:
        label = f"{section}: {label}" if label else section
    return label[:200]


def links_in(html, base_url):
    """Yield (url, label). The site uses <base href="https://rgipt.ac.in">, so relative links
    resolve from the site root."""
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.string or "") if soup.title else ""
    # "Official Website of ... / Academics / Ordinances" -> "Academics / Ordinances"
    section = " / ".join(TITLE_PREFIX.sub("", title).split(" / ")[-2:]).strip() \
        if TITLE_PREFIX.match(title) else ""
    for a in soup.find_all("a", href=True):
        h = a["href"].strip()
        if h.lower().startswith(("javascript", "mailto", "tel:", "#")):
            continue
        yield normalize(urljoin(BASE + "/", h)), link_label(a, section)


def fetch(url):
    key = hashlib.md5(url.encode()).hexdigest()[:10]
    for ext in ("html", "pdf"):              # reuse cache, don't re-download
        f = RAW / f"{key}.{ext}"
        if f.exists():
            return key, ext, f.read_bytes(), False
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    ext = "pdf" if ("pdf" in ctype or url.lower().endswith(".pdf")) else "html"
    if ext == "pdf" and not r.content.startswith(b"%PDF"):
        raise ValueError("not a real PDF (got HTML/other)")
    (RAW / f"{key}.{ext}").write_bytes(r.content)
    return key, ext, r.content, True


# 1. Seeds: sitemap links + manual extras
sitemap = requests.get(BASE + "/article/en/sitemap", headers=HEADERS, timeout=30).text
seed_map = {}
for u, lab in links_in(sitemap, BASE):
    if wanted(u):
        seed_map.setdefault(u, lab)
for s in EXTRA_SEEDS:
    seed_map.setdefault(normalize(BASE + s), "")
queue = [(u, 0, lab, "sitemap") for u, lab in seed_map.items()]
seen = set()
print(f"{len(queue)} seed URLs")

# 2. Crawl
docs, errors = [], []
while queue and len(docs) < MAX_DOCS:
    url, depth, label, parent = queue.pop(0)
    if url in seen:
        continue
    seen.add(url)
    try:
        key, ext, content, fresh = fetch(url)
    except Exception as e:
        errors.append((url, str(e)))
        print("ERR", url, e)
        continue

    if ext == "pdf":
        docs.append({"id": key, "url": url, "type": "pdf", "label": label,
                     "parent": parent, "file": f"data/raw/{key}.pdf"})
    else:
        html = content.decode("utf-8", errors="ignore")
        soup = BeautifulSoup(html, "lxml")
        for t in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            t.decompose()
        # Campus home pages (e.g. /en/page/bengaluru) have several #main-content blocks
        parts = [m.get_text("\n", strip=True) for m in soup.find_all(id="main-content")]
        text = "\n".join(dict.fromkeys(p for p in parts if p)) if parts else \
            (soup.body or soup).get_text("\n", strip=True)
        if not text or NO_CONTENT.match(text):   # error page, or images/map only
            errors.append((url, "no text content"))
            continue
        docs.append({"id": key, "url": url, "type": "html", "label": label, "parent": parent,
                     "title": (soup.title.string or "").strip() if soup.title else "",
                     "text": text})
        if depth < MAX_DEPTH:
            for l, lab in links_in(html, url):
                if wanted(l) and l not in seen:
                    queue.append((l, depth + 1, lab, url))

    print(f"[{len(docs)}] {url}")
    if fresh:
        time.sleep(DELAY)

# 3. Save + summary
json.dump(docs, open(PROC / "pages.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump(errors, open(PROC / "crawl_errors.json", "w"), indent=1)
html_n = sum(d["type"] == "html" for d in docs)
print(f"\nDone: {len(docs)} docs ({html_n} HTML, {len(docs) - html_n} PDF), {len(errors)} errors")
bad = [d["url"] for d in docs if "/en/page/en/" in d["url"] or "?brd=" in d["url"]]
print(f"Suspicious URLs (should be 0): {len(bad)}")
empty = [d["url"] for d in docs if d["type"] == "html" and len(d["text"]) < 300]
print(f"{len(empty)} HTML pages with <300 chars of text:")
for u in empty[:20]:
    print("  ", u)