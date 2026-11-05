"""Discounted cash flow, scenarios, sensitivity grid and reverse DCF."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .assumptions import Assumptions


def growth_path(a: Assumptions) -> list[float]:
    """Years 1-5 at growth_initial, then linear fade to terminal growth by the last year."""
    n_hold = a.years // 2
    path = [a.growth_initial] * n_hold
    n_fade = a.years - n_hold
    for i in range(1, n_fade + 1):
        path.append(a.growth_initial + (a.terminal_growth - a.growth_initial) * i / n_fade)
    return path


def dcf(a: Assumptions) -> dict:
    if a.wacc <= a.terminal_growth:
        raise ValueError("WACC must exceed terminal growth")
    rev = a.base_revenue
    rows, pv_sum = [], 0.0
    for t, g in enumerate(growth_path(a), start=1):
        rev *= 1 + g
        fcf = rev * a.fcf_margin
        df_ = 1 / (1 + a.wacc) ** t
        pv_sum += fcf * df_
        rows.append({"year": t, "growth": g, "revenue": rev, "fcf": fcf, "discount_factor": df_, "pv_fcf": fcf * df_})
    tv = rows[-1]["fcf"] * (1 + a.terminal_growth) / (a.wacc - a.terminal_growth)
    pv_tv = tv * rows[-1]["discount_factor"]
    ev = pv_sum + pv_tv
    equity = ev - a.net_debt
    return {
        "enterprise_value": ev,
        "equity_value": equity,
        "per_share": equity / a.shares,
        "pv_explicit": pv_sum,
        "pv_terminal": pv_tv,
        "terminal_share": pv_tv / ev if ev > 0 else np.nan,
        "projection": pd.DataFrame(rows),
    }


def scenarios(a: Assumptions) -> dict[str, Assumptions]:
    m = a.fcf_margin
    return {
        "bear": a.with_(growth_initial=a.growth_initial * 0.5 - 0.01, fcf_margin=m - abs(m) * 0.15,
                        wacc=a.wacc + 0.01, terminal_growth=max(a.terminal_growth - 0.005, 0.0)),
        "base": a,
        "bull": a.with_(growth_initial=a.growth_initial * 1.3 + 0.01, fcf_margin=m + abs(m) * 0.10,
                        wacc=max(a.wacc - 0.01, a.terminal_growth + 0.02)),
    }


def sensitivity(a: Assumptions, wacc_steps=(-0.02, -0.01, 0, 0.01, 0.02),
                growth_steps=(-0.04, -0.02, 0, 0.02, 0.04)) -> pd.DataFrame:
    """Value per share: rows = WACC, columns = initial growth."""
    data = {}
    for gs in growth_steps:
        g = a.growth_initial + gs
        col = {}
        for ws in wacc_steps:
            w = a.wacc + ws
            col[w] = dcf(a.with_(wacc=w, growth_initial=g))["per_share"] if w > a.terminal_growth + 0.005 else np.nan
        data[g] = col
    df = pd.DataFrame(data)
    df.index.name = "WACC \\ growth"
    return df


def _solve(f, lo, hi, target, iters=100):
    flo, fhi = f(lo) - target, f(hi) - target
    if np.sign(flo) == np.sign(fhi):
        return None
    for _ in range(iters):
        mid = (lo + hi) / 2
        fm = f(mid) - target
        if abs(fm) < 1e-6 * max(1, abs(target)):
            return mid
        if np.sign(fm) == np.sign(flo):
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2


def reverse_dcf(a: Assumptions, price: float) -> dict:
    """What does the current price imply? Solve for growth (holding margin) and margin (holding growth)."""
    out = {"implied_growth": None, "implied_margin": None}
    if not price or price <= 0:
        return out
    if a.fcf_margin > 0:
        out["implied_growth"] = _solve(lambda g: dcf(a.with_(growth_initial=g))["per_share"], -0.5, 1.5, price)
    out["implied_margin"] = _solve(lambda m: dcf(a.with_(fcf_margin=m))["per_share"], -0.5, 1.5, price)
    return out
