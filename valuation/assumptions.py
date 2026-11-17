"""Derive default valuation assumptions from history. Every value is editable in the UI —
the defaults are a starting point, not a verdict."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict, replace

import numpy as np

from .. import config
from ..financials import Financials


def _clamp(x, lo, hi):
    return float(min(max(x, lo), hi))


def _median_last(s, n):
    v = s.dropna().tail(n)
    return float(v.median()) if len(v) else None


@dataclass
class Assumptions:
    base_revenue: float
    growth_initial: float          # yearly revenue growth for years 1-5 (then fades to terminal)
    fcf_margin: float              # unlevered FCF / revenue
    wacc: float
    terminal_growth: float
    net_debt: float                # debt - cash & short-term investments
    shares: float
    tax_rate: float
    cost_of_equity: float
    years: int = 10
    subtract_sbc: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    def with_(self, **kw) -> "Assumptions":
        return replace(self, **kw)


def historical_cagr(revenue, years=5):
    r = revenue.dropna()
    if len(r) < 2:
        return None
    n = min(years, len(r) - 1)
    start, end = r.iloc[-1 - n], r.iloc[-1]
    if start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / n) - 1


def derive(fin: Financials, market: dict | None = None, *, subtract_sbc: bool = True,
           risk_free: float = config.DEFAULT_RISK_FREE,
           erp: float = config.DEFAULT_EQUITY_RISK_PREMIUM,
           terminal_growth: float = config.DEFAULT_TERMINAL_GROWTH) -> Assumptions:
    market = market or {}
    df = fin.annual
    last = df.iloc[-1]
    notes: list[str] = []

    # --- growth ---
    cagr = historical_cagr(df["revenue"])
    if cagr is None:
        cagr = 0.03
        notes.append("Not enough revenue history — default growth 3%.")
    growth = _clamp(cagr, -0.05, 0.25)
    if growth != cagr:
        notes.append(f"Historical revenue CAGR {cagr:.1%} clamped to {growth:.1%} for the base case.")

    # --- tax ---
    tr = _median_last(df["tax_rate"], 3)
    tax = _clamp(tr, 0.05, 0.35) if tr is not None else config.DEFAULT_TAX_RATE

    # --- unlevered FCF margin (CFO already deducts interest under US GAAP -> add back after tax) ---
    fcf_col = "fcf_after_sbc" if subtract_sbc else "fcf"
    fcff = df[fcf_col] + df["interest_expense"].fillna(0) * (1 - tax)
    margin = _median_last(fcff / df["revenue"], 5)
    if margin is None:
        margin = 0.0
        notes.append("FCF history missing — DCF not meaningful.")
    elif margin <= 0:
        notes.append("Median free-cash-flow margin is negative — DCF is not meaningful for this company yet.")

    # --- WACC ---
    beta = market.get("beta")
    if not beta:
        beta = 1.0
        notes.append("Beta unavailable — using 1.0.")
    beta = _clamp(beta, 0.6, 2.0)
    ke = risk_free + beta * erp
    debt = float(last.get("total_debt") or 0)
    interest = last.get("interest_expense")
    kd = _clamp(interest / debt, 0.03, 0.10) if debt > 0 and interest and not np.isnan(interest) else risk_free + 0.015
    mcap = market.get("market_cap")
    if not mcap and market.get("price") and fin.shares_outstanding:
        mcap = market["price"] * fin.shares_outstanding
    equity_w = mcap if mcap else max(float(last.get("equity") or 0), 1.0)
    wd = debt / (debt + equity_w) if (debt + equity_w) > 0 else 0
    wacc = (1 - wd) * ke + wd * kd * (1 - tax)
    wacc = max(wacc, terminal_growth + 0.03)

    net_debt = debt - float(last.get("cash_and_investments") or 0)
    shares = fin.shares_outstanding or float(last.get("diluted_shares") or np.nan)

    return Assumptions(
        base_revenue=float(last["revenue"]), growth_initial=growth, fcf_margin=float(margin),
        wacc=float(wacc), terminal_growth=terminal_growth, net_debt=net_debt, shares=float(shares),
        tax_rate=tax, cost_of_equity=ke, subtract_sbc=subtract_sbc, notes=notes,
    )
