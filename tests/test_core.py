import math

import numpy as np
import pytest

from stock_analyzer.financials import build_financials
from stock_analyzer.valuation import derive, run
from stock_analyzer.valuation import dcf as D
from stock_analyzer.valuation.assumptions import Assumptions
from tests.fixtures import make_facts, YEARS


@pytest.fixture
def fin():
    return build_financials(make_facts(), "TEST", info={"sic": 3571})


def test_parsing_annual_only_and_tag_merge(fin):
    df = fin.annual
    assert list(df.index) == YEARS                     # one row per year, 10 years
    assert df["revenue"].notna().all()                  # old + new revenue tags merged
    assert df.loc[2016, "revenue"] == pytest.approx(100e9)   # not the quarterly value
    assert df.loc[2025, "revenue"] == pytest.approx(100e9 * 1.08 ** 9)


def test_restated_value_wins(fin):
    # 2024 revenue was re-reported 1% lower in the 2025 10-K -> latest filing wins
    assert fin.annual.loc[2024, "revenue"] == pytest.approx(100e9 * 1.08 ** 8 * 0.99)


def test_derived_items(fin):
    last = fin.latest
    assert last["total_debt"] == pytest.approx(105e9)          # 90 + 10 + 5 CP
    assert last["cash_and_investments"] == pytest.approx(50e9)
    assert last["fcf_margin"] == pytest.approx(0.22)
    assert last["tax_rate"] == pytest.approx(0.18)
    assert fin.shares_outstanding == pytest.approx(10e9 * 0.98 ** 9 * 0.995)


def test_dcf_matches_manual_calculation():
    a = Assumptions(base_revenue=100, growth_initial=0.10, fcf_margin=0.2, wacc=0.09, terminal_growth=0.02,
                    net_debt=10, shares=1, tax_rate=0.2, cost_of_equity=0.1, years=10)
    rev, pv = 100, 0
    path = [0.10] * 5 + [0.10 + (0.02 - 0.10) * i / 5 for i in range(1, 6)]
    for t, g in enumerate(path, 1):
        rev *= 1 + g
        pv += rev * 0.2 / 1.09 ** t
    tv = rev * 0.2 * 1.02 / (0.09 - 0.02) / 1.09 ** 10
    assert D.dcf(a)["per_share"] == pytest.approx(pv + tv - 10)


def test_reverse_dcf_roundtrip():
    a = Assumptions(base_revenue=100, growth_initial=0.07, fcf_margin=0.2, wacc=0.09, terminal_growth=0.025,
                    net_debt=0, shares=1, tax_rate=0.2, cost_of_equity=0.1)
    price = D.dcf(a)["per_share"]
    r = D.reverse_dcf(a.with_(growth_initial=0.0), price)
    assert r["implied_growth"] == pytest.approx(0.07, abs=1e-4)
    r2 = D.reverse_dcf(a.with_(fcf_margin=0.05), price)
    assert r2["implied_margin"] == pytest.approx(0.2, abs=1e-4)


def test_scenarios_ordered_and_sensitivity_monotonic(fin):
    a = derive(fin, {"beta": 1.1, "price": 150, "market_cap": 150 * fin.shares_outstanding})
    s = {k: D.dcf(v)["per_share"] for k, v in D.scenarios(a).items()}
    assert s["bear"] < s["base"] < s["bull"]
    grid = D.sensitivity(a)
    assert (grid.diff(axis=0).dropna() < 0).all().all()  # higher WACC -> lower value
    assert (grid.diff(axis=1).dropna(axis=1) > 0).all().all()  # higher growth -> higher value


def test_full_run_with_peers(fin):
    q = {"beta": 1.1, "price": 150.0, "market_cap": 150 * fin.shares_outstanding}
    a = derive(fin, q)
    assert 0.02 < a.growth_initial < 0.12
    peers = [{"ticker": t, "pe": pe, "ev_ebitda": ev, "ev_revenue": evr, "pb": 5}
             for t, pe, ev, evr in [("A", 20, 14, 4), ("B", 25, 17, 5), ("C", 30, 20, 6), ("D", None, 15, 4.5)]]
    r = run(fin, a, q["price"], peers)
    assert set(r.weights) == {"DCF", "Peer multiples", "EPV (no growth)"}
    assert sum(r.weights.values()) == pytest.approx(1)
    assert r.fair_value["low"] < r.fair_value["base"] < r.fair_value["high"]
    assert r.margin_of_safety == pytest.approx(r.fair_value["base"] / 150 - 1)
    assert r.graham and r.graham["per_share"] > 0
    t = r.model_table()
    assert "DCF" in t.index and not t[["low", "base", "high"]].isna().any().any()


def test_financial_company_uses_residual_income():
    fin = build_financials(make_facts(), "BANK", info={"sic": 6021})
    a = derive(fin, {"beta": 1.0, "price": 50})
    r = run(fin, a, 50, [{"ticker": "X", "pe": 12, "pb": 1.3}])
    assert not r.dcf and r.residual_income
    assert set(r.weights) == {"Residual income", "Peer multiples"}
    assert any("Financial company" in w for w in r.warnings)


def test_negative_fcf_company_flags_warning():
    fin = build_financials(make_facts(fcf_margin=-0.05), "BURN", info={"sic": 7372})
    a = derive(fin, {"beta": 1.5, "price": 10})
    assert a.fcf_margin < 0
    r = run(fin, a, 10, [])
    assert any("negative" in w for w in r.warnings)
    assert r.reverse.get("implied_growth") is None
