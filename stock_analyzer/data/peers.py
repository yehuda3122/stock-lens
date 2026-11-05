"""Automatic peer (competitor) discovery.

Strategy
1. Yahoo Finance industry classification: the company's `industryKey` -> top companies
   in that industry.
2. Fallback: SEC SIC code -> all SEC filers with the same SIC; sized with the SEC
   "frames" API (one call returns revenue for every filer).

Candidates are kept only if they are SEC filers (US-listed; also removes duplicate share
classes like GOOG/GOOGL via CIK), then ranked by size similarity to the target and the
closest `n` are returned.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import requests

from . import cache, market, sec


@dataclass
class PeerResult:
    tickers: list[str]
    method: str                      # "yahoo-industry" | "sec-sic" | "none"
    group: str | None = None         # industry / SIC description used
    details: list[dict] = field(default_factory=list)
    note: str | None = None


def _dedupe_by_cik(tickers: list[str], self_cik: int | None, tmap: dict) -> list[str]:
    seen, out = {self_cik}, []
    for t in tickers:
        t = t.upper().replace(".", "-")
        info = tmap.get(t)
        if not info or info["cik"] in seen:
            continue
        seen.add(info["cik"])
        out.append(t)
    return out


def _rank_by_size(cands: list[tuple[str, float | None]], target_size: float | None, n: int) -> list[str]:
    """Closest in log-size first; candidates without size go last (in original order)."""
    if not target_size or target_size <= 0:
        return [t for t, _ in cands][:n]
    sized = [(abs(math.log(s / target_size)), t) for t, s in cands if s and s > 0]
    unsized = [t for t, s in cands if not s or s <= 0]
    return ([t for _, t in sorted(sized)] + unsized)[:n]


# ---------- Yahoo industry ----------
def yahoo_industry_candidates(industry_key: str) -> list[str]:
    hit = cache.get(f"yf:industry:{industry_key}", ttl_hours=24 * 7)
    if hit is not None:
        return hit
    try:
        import yfinance as yf
        df = yf.Industry(industry_key).top_companies
        syms = list(df.index) if df is not None else []
    except Exception:
        syms = []
    return cache.put(f"yf:industry:{industry_key}", syms) if syms else syms


# ---------- SEC SIC ----------
def sec_sic_ciks(sic: int, pages: int = 4) -> list[int]:
    hit = cache.get(f"sec:sic:{sic}", ttl_hours=24 * 7)
    if hit is not None:
        return hit
    ciks: list[int] = []
    for p in range(pages):
        url = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
               f"&SIC={sic:04d}&type=10-K&owner=include&count=100&start={p*100}&output=atom")
        try:
            r = requests.get(url, headers=sec._HEADERS, timeout=30)
            r.raise_for_status()
        except Exception:
            break
        found = [int(c) for c in re.findall(r"<cik>(\d+)</cik>", r.text)] or \
                [int(c) for c in re.findall(r"CIK=(\d{6,10})", r.text)]
        new = [c for c in found if c not in ciks]
        if not new:
            break
        ciks.extend(new)
    return cache.put(f"sec:sic:{sic}", ciks) if ciks else ciks


def sec_revenue_frame(year: int) -> dict[int, float]:
    """{cik: annual revenue} for every SEC filer for calendar year `year`."""
    hit = cache.get(f"sec:frame:rev:{year}", ttl_hours=24 * 7)
    if hit is not None:
        return {int(k): v for k, v in hit.items()}
    out: dict[int, float] = {}
    for tag in ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"]:
        try:
            j = sec._get_json(f"https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/CY{year}.json",
                              f"sec:frame:{tag}:{year}", ttl_hours=24 * 7)
            for d in j.get("data", []):
                out[int(d["cik"])] = max(out.get(int(d["cik"]), 0), float(d["val"]))
        except Exception:
            continue
    cache.put(f"sec:frame:rev:{year}", out)
    return out


# ---------- main entry ----------
def find_peers(ticker: str, *, cik: int | None = None, sic: int | None = None, sic_description: str | None = None,
               quote: dict | None = None, revenue: float | None = None, fiscal_year: int | None = None,
               n: int = 5, max_candidates: int = 15) -> PeerResult:
    ticker = ticker.upper()
    quote = quote if quote is not None else market.quote(ticker)
    try:
        tmap = sec.ticker_map()
    except Exception:
        tmap = {}
    cik = cik or (tmap.get(ticker) or {}).get("cik")

    # 1) Yahoo industry
    ikey = quote.get("industry_key")
    if ikey:
        cands = _dedupe_by_cik(yahoo_industry_candidates(ikey), cik, tmap)[:max_candidates]
        if cands:
            sized = [(t, market.quote(t).get("market_cap")) for t in cands]
            chosen = _rank_by_size(sized, quote.get("market_cap"), n)
            if chosen:
                det = [{"ticker": t, "name": tmap.get(t, {}).get("name"), "market_cap": dict(sized).get(t)} for t in chosen]
                return PeerResult(chosen, "yahoo-industry", quote.get("industry") or ikey, det)

    # 2) SEC SIC fallback
    if sic:
        ciks = sec_sic_ciks(sic)
        rev_by_cik = sec_revenue_frame((fiscal_year or 2024) - 1) if ciks else {}
        cik_to_t = {}
        for t, v in tmap.items():
            cik_to_t.setdefault(v["cik"], t)       # first (primary) ticker per CIK
        cands = [(cik_to_t[c], rev_by_cik.get(c)) for c in ciks if c in cik_to_t and c != cik]
        chosen = _rank_by_size(cands, revenue, n)
        if chosen:
            det = [{"ticker": t, "name": tmap[t]["name"], "revenue": dict(cands).get(t)} for t in chosen]
            return PeerResult(chosen, "sec-sic", f"SIC {sic} {sic_description or ''}".strip(), det)

    return PeerResult([], "none", note="No peers found automatically — enter tickers manually.")
