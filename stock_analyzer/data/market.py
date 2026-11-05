"""Market data (price, beta, peer multiples) via yfinance.

yfinance is unofficial and occasionally breaks; every field is optional and the
UI lets you override price/beta manually.
"""
from __future__ import annotations

from . import cache


def quote(ticker: str) -> dict:
    hit = cache.get(f"yf:quote:{ticker}", ttl_hours=0.25)
    if hit:
        return hit
    out = {"price": None, "beta": None, "market_cap": None, "currency": None,
           "trailing_pe": None, "ev_to_ebitda": None, "ev_to_revenue": None,
           "price_to_book": None, "sector": None, "industry": None,
           "industry_key": None, "sector_key": None, "name": None}
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        try:
            fi = t.fast_info
            out["price"] = float(fi["last_price"])
            out["market_cap"] = float(fi["market_cap"])
            out["currency"] = fi["currency"]
        except Exception:
            pass
        try:
            info = t.info or {}
            out["price"] = out["price"] or info.get("currentPrice") or info.get("regularMarketPrice")
            out.update({
                "beta": info.get("beta"),
                "trailing_pe": info.get("trailingPE"),
                "ev_to_ebitda": info.get("enterpriseToEbitda"),
                "ev_to_revenue": info.get("enterpriseToRevenue"),
                "price_to_book": info.get("priceToBook"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "industry_key": info.get("industryKey"),
                "sector_key": info.get("sectorKey"),
                "name": info.get("shortName") or info.get("longName"),
            })
        except Exception:
            pass
    except ImportError:
        pass
    if not out["price"]:
        out["price"] = stooq_price(ticker)          # fallback when Yahoo blocks cloud servers
    if out["price"]:
        cache.put(f"yf:quote:{ticker}", out)
    return out


def stooq_price(ticker: str) -> float | None:
    """Last close from stooq.com (free, no key). Best-effort fallback."""
    try:
        import requests
        r = requests.get("https://stooq.com/q/l/", params={"s": f"{ticker.lower()}.us", "f": "sd2t2ohlcv", "h": "", "e": "csv"},
                         timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        lines = r.text.strip().splitlines()
        if len(lines) >= 2:
            row = dict(zip(lines[0].split(","), lines[1].split(",")))
            v = float(row.get("Close", "nan"))
            return v if v == v and v > 0 else None
    except Exception:
        return None
    return None


def peer_multiples(tickers: list[str]) -> list[dict]:
    rows = []
    for tk in tickers:
        tk = tk.strip().upper()
        if not tk:
            continue
        q = quote(tk)
        rows.append({"ticker": tk, "name": q.get("name"), "market_cap": q.get("market_cap"), "pe": q["trailing_pe"], "ev_ebitda": q["ev_to_ebitda"],
                     "ev_revenue": q["ev_to_revenue"], "pb": q["price_to_book"]})
    return rows
