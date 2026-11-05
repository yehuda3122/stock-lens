"""Non-DCF models: Earnings Power Value, Graham number, peer multiples, residual income."""
from __future__ import annotations

import math

import numpy as np

from ..financials import Financials
from .assumptions import Assumptions


def epv(fin: Financials, a: Assumptions) -> dict | None:
    """Greenwald's Earnings Power Value: today's normalized earnings, zero growth.
    Assumes maintenance capex ≈ D&A."""
    df = fin.annual
    margins = df["operating_margin"].dropna().tail(5)
    if margins.empty:
        return None
    norm_margin = float(margins.mean())
    # GAAP operating income is already after stock-based compensation expense
    nopat = a.base_revenue * norm_margin * (1 - a.tax_rate)
    ev = nopat / a.wacc
    equity = ev - a.net_debt
    return {"normalized_operating_margin": norm_margin, "nopat": nopat,
            "enterprise_value": ev, "per_share": equity / a.shares}


def graham_number(fin: Financials, a: Assumptions) -> dict | None:
    last = fin.latest
    eps = last.get("eps_diluted")
    if eps is None or np.isnan(eps):
        ni, sh = last.get("net_income"), last.get("diluted_shares")
        eps = ni / sh if sh else None
    bvps = (last.get("equity") or np.nan) / a.shares
    if eps is None or np.isnan(eps) or eps <= 0 or np.isnan(bvps) or bvps <= 0:
        return None
    return {"eps": float(eps), "bvps": float(bvps), "per_share": math.sqrt(22.5 * eps * bvps)}


def _pct(vals, q):
    vals = [v for v in vals if v is not None and not (isinstance(v, float) and np.isnan(v)) and v > 0]
    return float(np.percentile(vals, q)) if vals else None


def multiples(fin: Financials, a: Assumptions, peers: list[dict]) -> dict | None:
    """Implied price per share using peer median (and 25th/75th percentile) multiples."""
    if not peers:
        return None
    last = fin.latest
    eps = last.get("eps_diluted")
    ebitda = (last.get("operating_income") or np.nan) + (last.get("dna") or 0)
    rev = last.get("revenue")
    bvps = (last.get("equity") or np.nan) / a.shares

    def ev_to_price(ev):
        return (ev - a.net_debt) / a.shares

    implied = {}
    for key, metric, conv in [
        ("pe", eps, lambda m, x: m * x),
        ("ev_ebitda", ebitda, lambda m, x: ev_to_price(m * x)),
        ("ev_revenue", rev, lambda m, x: ev_to_price(m * x)),
        ("pb", bvps, lambda m, x: m * x),
    ]:
        if metric is None or np.isnan(metric) or metric <= 0:
            continue
        vals = [p.get(key) for p in peers]
        q = {name: _pct(vals, pct) for name, pct in [("low", 25), ("base", 50), ("high", 75)]}
        if q["base"] is None:
            continue
        implied[key] = {"peer_multiple": q["base"], **{k: conv(v, metric) for k, v in q.items()}}
    if not implied:
        return None
    # For non-financials P/B is weak; for financials EV-based multiples are meaningless
    use = ["pe", "pb"] if fin.is_financial else ["pe", "ev_ebitda", "ev_revenue"]
    chosen = {k: v for k, v in implied.items() if k in use} or implied
    agg = {s: float(np.mean([v[s] for v in chosen.values()])) for s in ("low", "base", "high")}
    return {"by_multiple": implied, "used": list(chosen), **agg, "per_share": agg["base"]}


def residual_income(fin: Financials, a: Assumptions, years: int = 10) -> dict | None:
    """For banks/insurers: value = book value + PV of excess returns over cost of equity,
    with ROE fading linearly to the cost of equity."""
    df = fin.annual
    bv = fin.latest.get("equity")
    roe = df["roe"].dropna().tail(5)
    if bv is None or np.isnan(bv) or bv <= 0 or roe.empty:
        return None
    roe0 = float(roe.median())
    ni = df["net_income"].dropna().tail(3).sum()
    div = df["dividends_paid"].abs().dropna().tail(3).sum()
    payout = min(max(div / ni, 0), 1) if ni > 0 else 0.5

    def value(ke):
        b, pv = bv, 0.0
        for t in range(1, years + 1):
            r = roe0 + (ke - roe0) * t / years
            ri = (r - ke) * b
            pv += ri / (1 + ke) ** t
            b *= 1 + r * (1 - payout)
        return (bv + pv) / a.shares

    ke = a.cost_of_equity
    return {"roe": roe0, "payout": payout,
            "low": value(ke + 0.01), "base": value(ke), "high": value(max(ke - 0.01, 0.04)),
            "per_share": value(ke)}
