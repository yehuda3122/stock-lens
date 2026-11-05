"""Run every model and combine them into a single fair-value range."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..financials import Financials
from .assumptions import Assumptions
from . import dcf as dcf_mod
from .other_models import epv, graham_number, multiples, residual_income


@dataclass
class ValuationResult:
    price: float | None
    assumptions: Assumptions
    dcf: dict                     # scenario -> dcf dict
    reverse: dict
    sensitivity: pd.DataFrame | None
    epv: dict | None
    graham: dict | None
    multiples: dict | None
    residual_income: dict | None
    weights: dict
    fair_value: dict              # low / base / high
    margin_of_safety: float | None
    warnings: list[str] = field(default_factory=list)

    def model_table(self) -> pd.DataFrame:
        rows = []
        if self.dcf:
            rows.append(("DCF", self.dcf["bear"]["per_share"], self.dcf["base"]["per_share"], self.dcf["bull"]["per_share"]))
        if self.epv:
            rows.append(("EPV (no growth)", self.epv["per_share"], self.epv["per_share"], self.epv["per_share"]))
        if self.multiples:
            rows.append(("Peer multiples", self.multiples["low"], self.multiples["base"], self.multiples["high"]))
        if self.residual_income:
            ri = self.residual_income
            rows.append(("Residual income", ri["low"], ri["base"], ri["high"]))
        if self.graham:
            g = self.graham["per_share"]
            rows.append(("Graham number (reference)", g, g, g))
        df = pd.DataFrame(rows, columns=["model", "low", "base", "high"]).set_index("model")
        df["weight"] = [self.weights.get(k, 0.0) for k in df.index]
        return df


def _weights(fin: Financials, a: Assumptions, available: set[str]) -> dict:
    if fin.is_financial:
        w = {"Residual income": 0.6, "Peer multiples": 0.4}
    elif a.fcf_margin <= 0:
        w = {"Peer multiples": 0.7, "DCF": 0.3}
    else:
        w = {"DCF": 0.5, "Peer multiples": 0.3, "EPV (no growth)": 0.2}
    w = {k: v for k, v in w.items() if k in available}
    s = sum(w.values())
    return {k: v / s for k, v in w.items()} if s else {}


def run(fin: Financials, a: Assumptions, price: float | None, peers: list[dict] | None = None) -> ValuationResult:
    warnings = list(fin.notes) + list(a.notes)
    if fin.is_financial:
        warnings.append(f"Financial company (SIC {fin.sic}): cash-flow DCF is excluded; "
                        "valuation relies on residual income and P/E, P/B.")

    dcf_res, rev, sens = {}, {}, None
    if not fin.is_financial and a.shares and not np.isnan(a.shares):
        dcf_res = {k: dcf_mod.dcf(s) for k, s in dcf_mod.scenarios(a).items()}
        rev = dcf_mod.reverse_dcf(a, price) if price else {}
        sens = dcf_mod.sensitivity(a)
        if dcf_res["base"]["terminal_share"] > 0.75:
            warnings.append(f"{dcf_res['base']['terminal_share']:.0%} of DCF value comes from the terminal value — "
                            "result is highly assumption-sensitive.")

    e = None if fin.is_financial else epv(fin, a)
    g = graham_number(fin, a)
    m = multiples(fin, a, peers or [])
    ri = residual_income(fin, a) if fin.is_financial else None

    available = {name for name, obj in [("DCF", dcf_res), ("EPV (no growth)", e),
                                        ("Peer multiples", m), ("Residual income", ri)] if obj}
    w = _weights(fin, a, available)

    def pick(name, scen):
        if name == "DCF":
            return dcf_res[{"low": "bear", "base": "base", "high": "bull"}[scen]]["per_share"]
        if name == "EPV (no growth)":
            return e["per_share"]
        if name == "Peer multiples":
            return m[scen]
        if name == "Residual income":
            return ri[scen]

    fair = {s: (sum(w[k] * pick(k, s) for k in w) if w else None) for s in ("low", "base", "high")}
    mos = (fair["base"] / price - 1) if (price and fair["base"]) else None
    if not peers:
        warnings.append("No peers entered — add 3-6 comparable companies to include multiples.")

    return ValuationResult(price, a, dcf_res, rev, sens, e, g, m, ri, w, fair, mos, warnings)
