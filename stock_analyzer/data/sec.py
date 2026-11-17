"""SEC EDGAR access: ticker -> CIK, company facts (XBRL), company metadata.

Free, official API. Docs: https://www.sec.gov/edgar/sec-api-documentation
"""
import time

import requests

from .. import config
from . import cache

_HEADERS = {"User-Agent": config.get_setting("SEC_USER_AGENT", config.SEC_USER_AGENT),
            "Accept-Encoding": "gzip, deflate"}


class SecError(RuntimeError):
    pass


def _get_json(url: str, cache_key: str, ttl_hours: float = 24):
    hit = cache.get(cache_key, ttl_hours)
    if hit is not None:
        return hit
    r = requests.get(url, headers=_HEADERS, timeout=30)
    if r.status_code == 404:
        raise SecError(f"Not found at SEC: {url}")
    r.raise_for_status()
    return cache.put(cache_key, r.json())


def ticker_map() -> dict:
    """{'AAPL': {'cik': 320193, 'name': 'Apple Inc.'}, ...}  (refreshed daily so new listings appear)"""
    raw = _get_json("https://www.sec.gov/files/company_tickers.json", "sec:tickers:v2", ttl_hours=24)
    return {v["ticker"].upper(): {"cik": int(v["cik_str"]), "name": v["title"]} for v in raw.values()}


# Common Hebrew names -> ticker (Yahoo search doesn't understand Hebrew)
ALIASES_HE = {
    "אפל": "AAPL", "מיקרוסופט": "MSFT", "גוגל": "GOOGL", "אלפבית": "GOOGL", "אמזון": "AMZN", "מטא": "META",
    "פייסבוק": "META", "טסלה": "TSLA", "אנבידיה": "NVDA", "נבידיה": "NVDA", "אינטל": "INTC", "נטפליקס": "NFLX",
    "טבע": "TEVA", "קוקה קולה": "KO", "קוקה-קולה": "KO", "פפסי": "PEP", "מקדונלדס": "MCD", "סטארבקס": "SBUX",
    "וולמארט": "WMT", "קוסטקו": "COST", "דיסני": "DIS", "נייקי": "NKE", "בואינג": "BA", "פייזר": "PFE",
    "ג'ונסון אנד ג'ונסון": "JNJ", "ויזה": "V", "מאסטרקארד": "MA", "פייפאל": "PYPL", "ברקשייר": "BRK-B",
    "ג'יי פי מורגן": "JPM", "גולדמן זאקס": "GS", "אורקל": "ORCL", "סיילספורס": "CRM", "אדובי": "ADBE",
    "איי אם די": "AMD", "קוואלקום": "QCOM", "ברודקום": "AVGO", "פלנטיר": "PLTR", "אובר": "UBER",
    "איירביאנבי": "ABNB", "ספוטיפיי": "SPOT", "שופיפיי": "SHOP", "טיוואן סמיקונדקטור": "TSM", "טי אס אמ סי": "TSM",
    "נובו נורדיסק": "NVO", "עליבאבא": "BABA", "אליבאבא": "BABA", "ASML": "ASML", "וויקס": "WIX", "מובילאיי": "MBLY",
    "צ'קפוינט": "CHKP", "צ'ק פוינט": "CHKP", "מאנדיי": "MNDY", "סייברארק": "CYBR", "נייס": "NICE", "אלביט": "ESLT",
    "אלביט מערכות": "ESLT", "טאואר": "TSEM", "פייבר": "FVRR", "לימונייד": "LMND", "ויסטרה": "VST", "אקסון": "XOM",
    "שברון": "CVX", "קטרפילר": "CAT", "אבווי": "ABBV", "אלי לילי": "LLY", "מרק": "MRK",
}


class LookupProblem(SecError):
    """Lookup failed with a message meant for the user (Hebrew)."""


def _as_ticker(q: str) -> str:
    return q.upper().replace(".", "-").replace("/", "-").replace(" ", "")


def _name_match(q: str, tm: dict) -> tuple[str, dict] | None:
    q = q.strip().lower()
    if len(q) < 2:
        return None
    starts = [(t, v) for t, v in tm.items() if v["name"].lower().startswith(q)]
    contains = [(t, v) for t, v in tm.items() if f" {q}" in f" {v['name'].lower()}"]
    for group in (starts, contains):
        if group:
            group.sort(key=lambda tv: (len(tv[1]["name"]), "-" in tv[0], len(tv[0])))
            return group[0]
    return None


def resolve(query: str) -> dict:
    """Ticker ('MSFT', '$msft', 'BRK.B'), company name ('coca cola'), brand ('google') or Hebrew name ('אפל')."""
    q = query.strip().lstrip("$").strip()
    if not q:
        raise LookupProblem("לא הוזן סימול או שם חברה.")
    tm = ticker_map()
    t = _as_ticker(ALIASES_HE.get(q, q))
    if t in tm:
        return {"ticker": t, **tm[t]}
    m = _name_match(q, tm)
    if m and len(q) >= 4:
        return {"ticker": m[0], **m[1]}

    # Yahoo symbol search: brands, partial names, ETFs, non-US listings
    from . import market
    hits = market.search(q)
    for h in hits:
        sym = _as_ticker(h.get("symbol") or "")
        if h.get("type") == "EQUITY" and sym in tm:
            return {"ticker": sym, **tm[sym]}
    for h in hits:                      # foreign listing (e.g. TSMC.BA) -> find the same company among SEC filers
        if h.get("type") == "EQUITY" and h.get("name"):
            words = " ".join(h["name"].split()[:2])
            mm = _name_match(words, tm)
            if mm:
                return {"ticker": mm[0], **mm[1]}
    if m:
        return {"ticker": m[0], **m[1]}
    if hits and hits[0].get("type") in ("ETF", "MUTUALFUND"):
        raise LookupProblem(f"{hits[0]['symbol']} היא קרן סל / קרן נאמנות ({hits[0].get('name') or ''}). "
                            "הכלי מנתח חברות בודדות לפי הדוחות הכספיים שלהן, ולקרנות אין דוחות כאלה.")
    if hits and hits[0].get("type") == "EQUITY":
        raise LookupProblem(f"נמצאה המניה {hits[0]['symbol']} ({hits[0].get('name') or ''}), אבל היא לא מדווחת ל-SEC "
                            "(נסחרת רק מחוץ לארה\"ב). הכלי עובד עם חברות שמגישות דוחות ל-SEC.")
    raise LookupProblem(f"לא מצאתי חברה בשם או בסימול '{query}'. נסה סימול באנגלית (למשל AAPL).")


def submissions(cik: int) -> dict:
    return _get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", f"sec:sub:{cik}", ttl_hours=6)


def latest_periodic_filing(sub: dict) -> str | None:
    """Date (YYYY-MM-DD) of the most recent 10-K / 10-Q / 20-F in the submissions feed."""
    rec = (sub.get("filings") or {}).get("recent") or {}
    dates = [d for f, d in zip(rec.get("form", []), rec.get("filingDate", []))
             if f in ("10-K", "10-Q", "10-K/A", "10-Q/A", "20-F")]
    return max(dates) if dates else None


def company_facts(cik: int) -> dict:
    """XBRL facts. Cached until the company files a new periodic report (checked via submissions, 6 h TTL),
    with a hard ceiling of 30 days."""
    key = f"sec:facts:{cik}"
    hit = cache.get(key, ttl_hours=24 * 30)
    if hit is not None:
        try:
            latest = latest_periodic_filing(submissions(cik))
            written = cache.written_at(key)
            if latest and written and latest > time.strftime("%Y-%m-%d", time.gmtime(written - 86400)):
                hit = None          # a newer filing exists -> refetch
        except Exception:
            pass
    if hit is not None:
        return hit
    r = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", headers=_HEADERS, timeout=60)
    if r.status_code == 404:
        raise LookupProblem("ל-SEC אין נתונים כספיים מובנים לחברה הזו. זה קורה לקרנות סל וקרנות נאמנות, "
                            "לחברות שהונפקו לאחרונה ועוד לא הגישו דוח שנתי, ולחלק מהחברות הזרות.")
    r.raise_for_status()
    return cache.put(key, r.json())


def company_info(cik: int) -> dict:
    """Name, SIC industry code, fiscal year end, exchange."""
    sub = submissions(cik)
    return {
        "name": sub.get("name"),
        "sic": int(sub["sic"]) if str(sub.get("sic", "")).isdigit() else None,
        "sic_description": sub.get("sicDescription"),
        "fiscal_year_end": sub.get("fiscalYearEnd"),
        "exchanges": sub.get("exchanges", []),
        "latest_filing": latest_periodic_filing(sub),
    }
