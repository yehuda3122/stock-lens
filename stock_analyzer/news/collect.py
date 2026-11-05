"""Collect and rank news over time windows.

Windows (relative to `today`):
  * last month                       -> up to `recent_n` stories (the most detail)
  * 4 quarterly windows over the year -> up to `quarter_n` *dominant* stories each

"Dominant" = a story many outlets covered (title clustering), from a strong source,
early in Google's relevance order, and actually about the company. Auto-generated
filler ("XYZ Fund buys 1,200 shares of ...") and price-prediction spam are dropped.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from .sources import Article, clean_company_name, google_news, finnhub_news, fetch_excerpt

TIER1 = {"reuters", "bloomberg", "wsj", "wall street journal", "financial times", "ft.com", "associated press",
         "ap news", "the new york times", "cnbc", "barron's", "the economist", "the information", "axios"}
TIER2 = {"marketwatch", "yahoo finance", "investor's business daily", "business insider", "forbes", "fortune",
         "the guardian", "bbc", "techcrunch", "the verge", "investing.com", "seeking alpha", "morningstar",
         "fierce", "politico", "cnn", "fox business", "s&p global", "ars technica", "wired", "nikkei asia"}
PRESS = {"pr newswire", "business wire", "globenewswire", "accesswire", "newsfile", "prnewswire"}
OPINION_HINTS = re.compile(r"\b(should you buy|is it time to|buy now|my top|best stocks?|\d+ reasons|"
                           r"millionaire|could make you|prediction|forecast for 20\d\d|if you (had )?(invested|bought)|"
                           r"today in .{0,30} history|where will .{0,40} be in)\b", re.I)
SPAM = re.compile(r"(shares (sold|bought|acquired) by|position in|stake in|holdings (lifted|trimmed|raised|cut)|"
                  r"acquires new|sells \d[\d,]* shares|buys \d[\d,]* shares|has \$[\d.]+ (million|billion) "
                  r"(stock )?position|stock price prediction|price target (raised|lowered|cut) .* at|"
                  r"short interest (up|down)|stock price, news, quote|stock quote|options? (volume|activity) spike|trading (up|down) [\d.]+%)", re.I)


def _norm_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", title.lower())
    stop = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "as", "at", "is", "its", "with", "by", "after",
            "from", "stock", "shares", "says", "inc", "corp"}
    return {w for w in words if w not in stop and len(w) > 2}


def _source_weight(a: Article) -> float:
    s = (a.source or "").lower()
    d = (a.source_domain or "").lower()
    if any(t in s or t in d for t in TIER1):
        return 1.0
    if any(t in s or t in d for t in TIER2):
        return 0.6
    return 0.3


GENERIC_FIRST = {"american", "general", "united", "first", "national", "international", "global", "bank", "the",
                 "new", "western", "southern", "northern", "eastern", "royal", "advanced", "applied", "digital"}


def name_variants(company: str) -> list[str]:
    """'Meta Platforms' -> ['Meta Platforms', 'Meta']; 'General Motors' -> ['General Motors']."""
    out = [company]
    first = company.split()[0]
    if len(company.split()) > 1 and len(first) >= 4 and first.lower() not in GENERIC_FIRST:
        out.append(first)
    return out


def classify(a: Article, company: str) -> str:
    s, d = (a.source or "").lower(), (a.source_domain or "").lower()
    first = re.sub(r"[^a-z]", "", company.lower().split()[0]) if company else ""
    own_site = bool(first) and (d.split(".")[0] == first or s == company.lower() or s == first)
    if any(p in s for p in PRESS) or own_site:
        return "press_release"   # newswire or the company's own site
    if OPINION_HINTS.search(a.title) or "motley fool" in s or "fool.com" in d:
        return "opinion"
    return "news"


def is_relevant(a: Article, company: str, ticker: str) -> bool:
    blob = f"{a.title} {a.summary}".lower()
    return any(re.search(rf"\b{re.escape(v.lower())}\b", blob) for v in name_variants(company)) or re.search(rf"\b{re.escape(ticker.lower())}\b", blob) is not None


def rank(articles: list[Article], company: str, ticker: str, n: int) -> list[Article]:
    """Cluster near-duplicate headlines, score each cluster, return the best article of the top-n clusters."""
    arts = [a for a in articles if a.title and not SPAM.search(a.title) and is_relevant(a, company, ticker)]
    clusters: list[dict] = []
    for pos, a in enumerate(arts):
        a.kind = classify(a, company)
        tok = _norm_tokens(a.title)
        for c in clusters:
            inter = len(tok & c["tok"])
            if tok and inter / max(1, min(len(tok), len(c["tok"]))) >= 0.6:
                c["members"].append((pos, a))
                break
        else:
            clusters.append({"tok": tok, "members": [(pos, a)]})

    scored = []
    for c in clusters:
        members = c["members"]
        outlets = {m.source for _, m in members}
        best_pos, best = max(members, key=lambda pm: (_source_weight(pm[1]) + (0.2 if pm[1].summary else 0), -pm[0]))
        first_pos = min(p for p, _ in members)
        kind_pen = {"news": 0, "opinion": -0.6, "press_release": -0.3}[best.kind]
        score = (1.5 * math.log1p(len(outlets) - 1) + 1.2 * _source_weight(best)
                 + 1.0 / (1 + first_pos / 10)                       # Google relevance order
                 + (0.4 if any(v.lower() in best.title.lower() for v in name_variants(company)) else 0) + kind_pen)
        best.score, best.coverage = round(score, 3), len(outlets)
        best.also_in = sorted(o for o in outlets if o != best.source)[:6]
        scored.append(best)
    scored.sort(key=lambda a: -a.score)
    return scored[:n]


@dataclass
class Window:
    label: str
    start: date
    end: date
    kind: str                          # "recent" | "quarter"
    articles: list[Article] = field(default_factory=list)
    raw_count: int = 0
    error: str | None = None


@dataclass
class NewsCollection:
    company: str
    ticker: str
    windows: list[Window]

    @property
    def articles(self) -> list[Article]:
        return [a for w in self.windows for a in w.articles]

    def by_id(self) -> dict[str, Article]:
        return {a.id: a for a in self.articles}


def make_windows(today: date, quarters: int = 4) -> list[Window]:
    recent_start = today - timedelta(days=30)
    wins = [Window("החודש האחרון", recent_start, today, "recent")]
    end = recent_start
    for q in range(1, quarters + 1):
        start = end - timedelta(days=91)
        wins.append(Window(f"לפני {q * 3 - 2}–{q * 3 + 1} חודשים ({start:%m/%Y}–{end:%m/%Y})", start, end, "quarter"))
        end = start
    return wins


def collect_news(ticker: str, company_name: str, *, today: date | None = None, finnhub_key: str | None = None,
                 recent_n: int = 15, quarter_n: int = 5, fetch_text: bool = True, text_top_k: int = 15,
                 google=google_news, finnhub=finnhub_news, excerpt=fetch_excerpt) -> NewsCollection:
    today = today or date.today()
    company = clean_company_name(company_name)
    names = " OR ".join(f'"{v}"' for v in name_variants(company))
    query = f'({names}) (stock OR shares OR earnings OR analyst OR revenue OR CEO)'
    windows = make_windows(today)
    for w in windows:
        raw: list[Article] = []
        try:
            raw += google(query, w.start, w.end)
            if len(raw) < 30:   # older windows: Google returns little for the narrow query -> broaden
                raw += google(f"({names})", w.start, w.end)
        except Exception as e:  # network / rate limit — keep going with other sources
            w.error = f"Google News: {e}"
        if finnhub_key:
            try:
                raw += finnhub(ticker, w.start, w.end, finnhub_key)
            except Exception as e:
                w.error = (w.error + "; " if w.error else "") + f"Finnhub: {e}"
        w.raw_count = len(raw)
        w.articles = rank(raw, company, ticker, recent_n if w.kind == "recent" else quarter_n)
        for a in w.articles:
            a.period = w.label

    # ids in chronological order (oldest first reads naturally as a timeline)
    all_arts = sorted((a for w in windows for a in w.articles), key=lambda a: a.published)
    for i, a in enumerate(all_arts, 1):
        a.id = f"S{i}"

    if fetch_text:
        top = sorted(windows[0].articles, key=lambda a: -a.score)[:text_top_k]
        top += [w.articles[0] for w in windows[1:] if w.articles]       # the #1 story of each quarter
        for a in top:
            if not a.text:
                a.text = excerpt(a.url)
    return NewsCollection(company, ticker, windows)
