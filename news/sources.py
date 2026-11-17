"""News providers.

- Google News RSS: free, no key, supports date windows (after:/before:). Results come in
  Google's relevance order, which we use as a "dominance" signal. Links are Google redirect
  links; they open fine in a browser and can be decoded to the publisher URL.
- Finnhub company-news (optional, free API key): ~1 year of US company news with a short
  summary and the publisher URL.
"""
from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from ..data import cache

UA = {"User-Agent": "Mozilla/5.0 (personal stock research tool)"}


@dataclass
class Article:
    title: str
    source: str
    url: str
    published: str                 # ISO date
    summary: str = ""
    provider: str = ""
    source_domain: str = ""
    text: str = ""                 # optional excerpt of the article body
    period: str = ""               # window label it belongs to
    score: float = 0.0
    coverage: int = 1              # how many outlets ran the same story
    also_in: list[str] = field(default_factory=list)
    kind: str = "news"             # news | press_release | opinion
    id: str = ""                   # "S1", "S2"... assigned at the end

    def to_dict(self):
        return asdict(self)


_SUFFIX = re.compile(r",?\s+(inc\.?|incorporated|corp\.?|corporation|co\.?|company|holdings?|group|plc|ltd\.?|"
                     r"limited|l\.?p\.?|n\.?v\.?|s\.?a\.?|ag|se|/de/?|/[a-z]{2}/?)$", re.I)


def clean_company_name(name: str) -> str:
    """'APPLE INC.' -> 'Apple'; 'Alphabet Inc.' -> 'Alphabet'; 'Coca-Cola Co' -> 'Coca-Cola'."""
    n = name.strip()
    for _ in range(3):
        n2 = _SUFFIX.sub("", n).strip(" ,.")
        if n2 == n:
            break
        n = n2
    if n.isupper():
        n = " ".join(w.capitalize() if len(w) > 3 else w for w in n.split())
        n = n[:1].upper() + n[1:]
    return n


def _strip_source_suffix(title: str, source: str) -> str:
    sfx = f" - {source}"
    return title[: -len(sfx)] if source and title.endswith(sfx) else title


def parse_google_rss(xml_text: str) -> list[Article]:
    root = ET.fromstring(xml_text)
    out = []
    for it in root.findall(".//item"):
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        domain = urllib.parse.urlparse(src_el.get("url", "")).netloc.replace("www.", "") if src_el is not None else ""
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate")).date().isoformat()
        except Exception:
            pub = ""
        out.append(Article(title=_strip_source_suffix(it.findtext("title") or "", source), source=source,
                           url=it.findtext("link") or "", published=pub, provider="google_news",
                           source_domain=domain))
    return out


def google_news(query: str, start: date, end: date, *, timeout: int = 20) -> list[Article]:
    q = f"{query} after:{start.isoformat()} before:{end.isoformat()}"
    key = f"gnews:{q}"
    hit = cache.get(key, ttl_hours=6)
    if hit is not None:
        return [Article(**a) for a in hit]
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    arts = parse_google_rss(r.text)
    cache.put(key, [a.to_dict() for a in arts])
    return arts


def finnhub_news(ticker: str, start: date, end: date, api_key: str, *, timeout: int = 20) -> list[Article]:
    key = f"finnhub:{ticker}:{start}:{end}"
    hit = cache.get(key, ttl_hours=6)
    if hit is not None:
        return [Article(**a) for a in hit]
    r = requests.get("https://finnhub.io/api/v1/company-news",
                     params={"symbol": ticker, "from": start.isoformat(), "to": end.isoformat(), "token": api_key},
                     timeout=timeout)
    r.raise_for_status()
    arts = []
    for d in r.json() or []:
        try:
            pub = datetime.fromtimestamp(int(d["datetime"]), tz=timezone.utc).date().isoformat()
        except Exception:
            pub = ""
        arts.append(Article(title=d.get("headline", ""), source=d.get("source", ""), url=d.get("url", ""),
                            published=pub, summary=(d.get("summary") or "")[:800], provider="finnhub",
                            source_domain=urllib.parse.urlparse(d.get("url", "")).netloc.replace("www.", "")))
    cache.put(key, [a.to_dict() for a in arts])
    return arts


# ---------------- optional full-text excerpts ----------------
def resolve_url(url: str) -> str:
    """Google News redirect link -> publisher URL (needs the optional `googlenewsdecoder` package)."""
    if "news.google.com" not in url:
        return url
    hit = cache.get(f"gnurl:{url}", ttl_hours=24 * 30)
    if hit:
        return hit
    try:
        from googlenewsdecoder import gnewsdecoder
        res = gnewsdecoder(url, interval=0)
        if res.get("status") or res.get("success"):
            return cache.put(f"gnurl:{url}", res["decoded_url"])
    except Exception:
        pass
    return url


def fetch_excerpt(url: str, max_chars: int = 1500, timeout: int = 12) -> str:
    """Best-effort article text (many publishers block bots / paywall — then returns '').
    Only a short excerpt is kept and it is only sent to the model, never displayed."""
    hit = cache.get(f"text:{url}", ttl_hours=24 * 7)
    if hit is not None:
        return hit
    text = ""
    try:
        import trafilatura
        r = requests.get(resolve_url(url), headers=UA, timeout=timeout)
        if r.ok:
            text = (trafilatura.extract(r.text, include_comments=False, include_tables=False) or "")
            text = re.sub(r"\s+", " ", text).strip()[:max_chars]
    except Exception:
        text = ""
    return cache.put(f"text:{url}", text)
