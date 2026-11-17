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
           "industry_key": None, "sector_key": None, "name": None, "shares_outstanding": None,
           "quote_type": None, "financial_currency": None}
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        try:
            fi = t.fast_info
            for k_out, k_fi in (("price", "last_price"), ("market_cap", "market_cap"), ("currency", "currency")):
                try:
                    v = fi[k_fi]
                    if v is not None:
                        out[k_out] = v if k_out == "currency" else float(v)
                except Exception:
                    pass
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
                "shares_outstanding": info.get("sharesOutstanding"),   # ADR-equivalent for ADRs
                "quote_type": info.get("quoteType"),
                "financial_currency": info.get("financialCurrency"),
            })
            out["market_cap"] = out["market_cap"] or info.get("marketCap")
        except Exception:
            pass
    except ImportError:
        pass
    if not out["price"]:
        out["price"] = stooq_price(ticker)          # fallback when Yahoo blocks cloud servers
    if out["price"]:
        cache.put(f"yf:quote:{ticker}", out)
    return out


def fx_rate(currency: str) -> float | None:
    """USD per 1 unit of `currency` (e.g. TWD -> ~0.03). Yahoo first, open.er-api.com as fallback. Cached 12 h."""
    currency = currency.upper()
    if currency == "USD":
        return 1.0
    hit = cache.get(f"fx:{currency}", ttl_hours=12)
    if hit:
        return hit
    rate = None
    try:
        import yfinance as yf
        rate = float(yf.Ticker(f"{currency}USD=X").fast_info["last_price"])
    except Exception:
        rate = None
    if not rate:
        try:
            import requests
            j = requests.get(f"https://open.er-api.com/v6/latest/{currency}", timeout=10).json()
            rate = float(j["rates"]["USD"])
        except Exception:
            rate = None
    return cache.put(f"fx:{currency}", rate) if rate else None


def search(query: str, n: int = 8) -> list[dict]:
    """Yahoo Finance symbol search: [{symbol, name, type, exchange}] — finds brands ('google'), partial names, ETFs."""
    key = f"yf:search:{query.lower()}"
    hit = cache.get(key, ttl_hours=24 * 7)
    if hit is not None:
        return hit
    out = []
    try:
        import yfinance as yf
        for q in yf.Search(query, max_results=n, news_count=0).quotes or []:
            out.append({"symbol": q.get("symbol"), "name": q.get("shortname") or q.get("longname"),
                        "type": q.get("quoteType"), "exchange": q.get("exchange")})
    except Exception:
        return []
    return cache.put(key, out)


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
