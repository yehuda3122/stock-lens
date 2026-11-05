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
    """{'AAPL': {'cik': 320193, 'name': 'Apple Inc.'}, ...}"""
    raw = _get_json("https://www.sec.gov/files/company_tickers.json", "sec:tickers", ttl_hours=24 * 7)
    return {v["ticker"].upper(): {"cik": int(v["cik_str"]), "name": v["title"]} for v in raw.values()}


def resolve(query: str) -> dict:
    """Accepts a ticker ('MSFT') or part of a company name ('microsoft')."""
    q = query.strip().upper()
    tm = ticker_map()
    if q in tm:
        return {"ticker": q, **tm[q]}
    q_low = query.strip().lower()
    matches = [(t, v) for t, v in tm.items() if q_low in v["name"].lower()]
    if not matches:
        raise SecError(f"No US-listed company found for '{query}'")
    matches.sort(key=lambda tv: len(tv[1]["name"]))  # shortest name = closest match
    t, v = matches[0]
    return {"ticker": t, **v}


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
        raise SecError("No XBRL financial data at SEC for this company (foreign filer or too new).")
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
