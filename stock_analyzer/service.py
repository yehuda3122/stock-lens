"""UI-independent orchestration: load inputs (cached / refreshable), compute a full bundle,
derive the 'bottom line', and build history snapshots. Used by every page and by the report."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import forensic, valuation
from .data import cache, market
from .financials import Financials, build_financials


@dataclass
class Inputs:
    fin: Financials
    quote: dict
    peer_tickers: list[str]
    peer_method: str
    peer_group: str | None
    peer_rows: list[dict]
    loaded_at: float = field(default_factory=time.time)
    data_ages: dict = field(default_factory=dict)       # human readable "updated X ago" per source


@dataclass
class Bundle:
    inputs: Inputs
    assumptions: valuation.Assumptions
    val: valuation.ValuationResult
    fr: forensic.ForensicReport

    @property
    def fin(self):
        return self.inputs.fin

    @property
    def quote(self):
        return self.inputs.quote

    @property
    def price(self):
        return self.val.price


def load_inputs(query: str, *, demo: str = "off", peers_override: list[str] | None = None,
                refresh: bool = False) -> Inputs:
    """demo: 'off' | 'clean' | 'flags'. refresh=True bypasses the disk cache for this company."""
    import os
    if demo == "off" and os.environ.get("STOCK_ANALYZER_FAKE"):   # dev/screenshots only: synthetic data for any ticker
        from .demo import make_facts, DEMO_QUOTE, DEMO_PEERS
        q = query.upper()
        seed = sum(map(ord, q))
        fin = build_financials(make_facts(revenue0=(20 + seed % 80) * 1e9, growth=0.03 + (seed % 9) / 100,
                                          manipulate=seed % 3 == 0), q, name=f"{q} Corp (synthetic)",
                               info={"sic": 3571, "sic_description": "Synthetic"})
        return Inputs(fin, {**DEMO_QUOTE, "price": 60.0 + seed % 140}, [p["ticker"] for p in DEMO_PEERS], "demo",
                      None, list(DEMO_PEERS), data_ages={"דוחות": "סינתטי"})
    if demo != "off":
        from .demo import make_facts, DEMO_QUOTE, DEMO_PEERS
        fin = build_financials(make_facts(manipulate=(demo == "flags")), "DEMO",
                               name="Demo Corp (נתוני דמה)", info={"sic": 3571, "sic_description": "Demo industry"})
        return Inputs(fin, dict(DEMO_QUOTE), [p["ticker"] for p in DEMO_PEERS], "demo", None, list(DEMO_PEERS),
                      data_ages={"דוחות": "נתוני דמה", "מחיר": "נתוני דמה"})

    from .data import sec
    from .pipeline import auto_peers
    c = sec.resolve(query)
    keys = [f"sec:facts:{c['cik']}", f"sec:sub:{c['cik']}", f"yf:quote:{c['ticker']}"]
    with cache.refresh(*(keys if refresh else [])):
        facts = sec.company_facts(c["cik"])
        try:
            info = sec.company_info(c["cik"])
        except Exception:
            info = {}
        fin = build_financials(facts, c["ticker"], name=c["name"], info=info)
        fin.cik = c["cik"]
        quote = market.quote(c["ticker"])
        if peers_override:
            tickers, method, group = [t.upper() for t in peers_override], "manual", None
        else:
            try:
                pr = auto_peers(fin, quote)
                tickers, method, group = pr.tickers, pr.method, pr.group
            except Exception:
                tickers, method, group = [], "none", None
        rows = market.peer_multiples(tickers) if tickers else []
    ages = {"דוחות (SEC)": cache.humanize_age(cache.age_seconds(keys[0])),
            "מחיר": cache.humanize_age(cache.age_seconds(keys[2]))}
    if info.get("latest_filing"):
        ages["דוח אחרון שהוגש"] = info["latest_filing"]
    return Inputs(fin, quote, tickers, method, group, rows, data_ages=ages)


def compute(inp: Inputs, *, price: float | None = None, subtract_sbc: bool = True, **overrides) -> Bundle:
    a = valuation.derive(inp.fin, inp.quote, subtract_sbc=subtract_sbc)
    if overrides:
        a = a.with_(**{k: v for k, v in overrides.items() if v is not None})
        a = a.with_(wacc=max(a.wacc, a.terminal_growth + 0.01))
    price = price or inp.quote.get("price")
    val = valuation.run(inp.fin, a, price, inp.peer_rows)
    mcap = inp.quote.get("market_cap") or (price * inp.fin.shares_outstanding if price and inp.fin.shares_outstanding else None)
    return Bundle(inp, a, val, forensic.analyze(inp.fin, mcap))


# ---------------------------------------------------------------- bottom line
VERDICT_TEXT = {
    "below": "המחיר מתחת לכל טווח השווי המוערך",
    "within": "המחיר בתוך טווח השווי המוערך",
    "above": "המחיר מעל לכל טווח השווי המוערך",
    "na": "לא ניתן לקבוע טווח שווי",
}


def bottom_line(b: Bundle, news=None) -> dict:
    """Everything the summary card needs. `news` is a NewsAnalysis or None."""
    fv, price = b.val.fair_value, b.val.price
    if price and fv.get("base"):
        verdict = "below" if price < fv["low"] else "above" if price > fv["high"] else "within"
    else:
        verdict = "na"
    counts = b.fr.counts()
    reds = [f.title for f in b.fr.flags if f.status == "red"]
    yellows = [f.title for f in b.fr.flags if f.status == "yellow"]
    hist_growth = valuation.assumptions.historical_cagr(b.fin.annual["revenue"])
    out = {
        "verdict": verdict, "verdict_text": VERDICT_TEXT[verdict], "price": price, "fair": fv,
        "mos": b.val.margin_of_safety, "implied_growth": b.val.reverse.get("implied_growth"),
        "hist_growth": hist_growth, "counts": counts, "red_flags": reds, "yellow_flags": yellows,
        "piotroski": (b.fr.piotroski or {}).get("score"), "news": None,
    }
    if news is not None:
        d = news.data
        sents = [s.get("sentiment") for s in d.get("source_analysis", [])]
        out["news"] = {
            "summary": d.get("summary", {}).get("text", ""),
            "top_concerns": [(c["severity"], c["title"]) for c in d.get("concerns", [])[:3]],
            "sentiment": {k: sents.count(k) for k in ("positive", "negative", "neutral", "mixed")},
            "conclusion": d.get("conclusion", {}).get("text", ""),
            "confidence": d.get("conclusion", {}).get("confidence"),
        }
    return out


def snapshot_fields(b: Bundle, news=None) -> dict:
    bl = bottom_line(b, news)
    payload = {"red_flags": bl["red_flags"], "yellow_flags": bl["yellow_flags"], "verdict": bl["verdict"],
               "name": b.fin.name, "piotroski": bl["piotroski"], "hist_growth": bl["hist_growth"]}
    if bl["news"]:
        payload["news"] = bl["news"]
    return dict(price=b.price, fair=b.val.fair_value, mos=b.val.margin_of_safety,
                implied_growth=bl["implied_growth"], counts=bl["counts"], payload=payload)


def compare_row(b: Bundle) -> dict:
    """Flat metrics for the comparison page."""
    df = b.fin.annual
    last = df.iloc[-1]
    bl = bottom_line(b)
    nd = (last.get("total_debt") or 0) - (last.get("cash_and_investments") or 0)
    ebitda = (last.get("operating_income") or 0) + (last.get("dna") or 0)
    return {
        "ticker": b.fin.ticker, "name": b.fin.name, "price": b.price,
        "fv_low": b.val.fair_value.get("low"), "fv_base": b.val.fair_value.get("base"),
        "fv_high": b.val.fair_value.get("high"), "mos": b.val.margin_of_safety,
        "implied_growth": bl["implied_growth"], "hist_growth": bl["hist_growth"],
        "revenue": last.get("revenue"), "op_margin": last.get("operating_margin"),
        "fcf_margin": last.get("fcf_margin"), "roe": last.get("roe"),
        "net_debt_ebitda": (nd / ebitda) if ebitda > 0 else None,
        "piotroski": bl["piotroski"], "beneish": (b.fr.beneish or {}).get("m_score"),
        "red": bl["counts"]["red"], "yellow": bl["counts"]["yellow"], "verdict": bl["verdict"],
    }
