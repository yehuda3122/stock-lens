"""One call from ticker to full report."""
from __future__ import annotations

from .data import sec, market
from .data.peers import PeerResult, find_peers
from .financials import Financials, build_financials
from . import valuation, forensic


def load_company(query: str) -> tuple[Financials, dict]:
    c = sec.resolve(query)
    facts = sec.company_facts(c["cik"])
    try:
        info = sec.company_info(c["cik"])
    except Exception:
        info = {}
    fin = build_financials(facts, c["ticker"], name=c["name"], info=info)
    fin.cik = c["cik"]
    return fin, market.quote(c["ticker"])


def auto_peers(fin: Financials, quote: dict, n: int = 5) -> PeerResult:
    return find_peers(fin.ticker, cik=fin.cik, sic=fin.sic, sic_description=fin.sic_description,
                      quote=quote, revenue=float(fin.latest.get("revenue") or 0) or None,
                      fiscal_year=int(fin.annual.index[-1]), n=n)


def analyze(query: str, peers: list[str] | None = None, price: float | None = None, **assumption_kw):
    """peers=None -> discover automatically; peers=[] -> no peers."""
    fin, q = load_company(query)
    price = price or q.get("price")
    a = valuation.derive(fin, q)
    if assumption_kw:
        a = a.with_(**assumption_kw)
    peer_info = None
    if peers is None:
        peer_info = auto_peers(fin, q)
        peers = peer_info.tickers
    peer_rows = market.peer_multiples(peers) if peers else []
    val = valuation.run(fin, a, price, peer_rows)
    mcap = q.get("market_cap") or (price * fin.shares_outstanding if price and fin.shares_outstanding else None)
    flags = forensic.analyze(fin, mcap)
    return {"financials": fin, "quote": q, "valuation": val, "forensic": flags, "peers": peer_info, "peer_rows": peer_rows}
