"""SEC EDGAR access: ticker -> CIK, company facts (XBRL), company metadata.

Free, official API. Docs: https://www.sec.gov/edgar/sec-api-documentation
"""
import requests

from ..config import SEC_USER_AGENT
from . import cache

_HEADERS = {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}


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


def company_facts(cik: int) -> dict:
    return _get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", f"sec:facts:{cik}")


def company_info(cik: int) -> dict:
    """Name, SIC industry code, fiscal year end, exchange."""
    sub = _get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", f"sec:sub:{cik}")
    return {
        "name": sub.get("name"),
        "sic": int(sub["sic"]) if str(sub.get("sic", "")).isdigit() else None,
        "sic_description": sub.get("sicDescription"),
        "fiscal_year_end": sub.get("fiscalYearEnd"),
        "exchanges": sub.get("exchanges", []),
    }
