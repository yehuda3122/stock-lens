import pytest

from stock_analyzer import forensic
from stock_analyzer.data import peers as P
from stock_analyzer.financials import build_financials
from stock_analyzer.demo import make_facts


def _flags(manip):
    fin = build_financials(make_facts(manipulate=manip), "T", info={"sic": 3571})
    return fin, {f.key: f for f in forensic.analyze(fin, 1.2e12).flags}


def test_clean_company_mostly_green():
    _, f = _flags(False)
    assert f["beneish"].status == "green" and f["altman"].status == "green"
    assert f["ni_vs_cfo"].status == "green" and f["ar_vs_rev"].status == "green"
    assert f["dilution"].status == "green"
    assert f["restatements"].status == "yellow"   # 1% revenue restatement in fixture


def test_manipulator_raises_red_flags():
    _, f = _flags(True)
    for k in ["ni_vs_cfo", "ar_vs_rev", "inv_vs_cogs", "restatements"]:
        assert f[k].status == "red", k
    assert f["beneish"].status in ("yellow", "red")
    assert f["piotroski"].data["tests"]["cfo_gt_ni"] is False


def test_beneish_formula_neutral_company():
    # identical years -> every index = 1, TATA from data
    fin = build_financials(make_facts(growth=0.0), "T", info={"sic": 3571})
    b = forensic.beneish(fin.annual)
    for k in ["DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "LVGI"]:
        assert b["components"][k] == pytest.approx(1.0, abs=0.02), k
    expected = -4.84 + sum(w for k, w in forensic.BENEISH_W.items() if k != "TATA") + 4.679 * b["components"]["TATA"]
    assert b["m_score"] == pytest.approx(expected, abs=0.05)


def test_financial_company_skips_scores():
    fin = build_financials(make_facts(), "B", info={"sic": 6021})
    r = forensic.analyze(fin)
    f = {x.key: x for x in r.flags}
    assert f["beneish"].status == "na" and f["altman"].status == "na"


def test_peers_yahoo_ranked_by_size_and_deduped(monkeypatch):
    tmap = {"AAA": {"cik": 1, "name": "Target"}, "BIG": {"cik": 2, "name": "Big"}, "MID": {"cik": 3, "name": "Mid"},
            "MIDB": {"cik": 3, "name": "Mid"}, "SML": {"cik": 4, "name": "Small"}, "TINY": {"cik": 5, "name": "Tiny"}}
    caps = {"BIG": 3000e9, "MID": 120e9, "MIDB": 120e9, "SML": 50e9, "TINY": 0.5e9}
    monkeypatch.setattr(P.sec, "ticker_map", lambda: tmap)
    monkeypatch.setattr(P, "yahoo_industry_candidates", lambda k: ["BIG", "AAA", "MID", "MIDB", "FOREIGN.L", "SML", "TINY"])
    monkeypatch.setattr(P.market, "quote", lambda t: {"market_cap": caps.get(t)})
    r = P.find_peers("AAA", quote={"industry_key": "x", "industry": "X", "market_cap": 100e9}, n=3)
    assert r.method == "yahoo-industry"
    assert r.tickers == ["MID", "SML", "BIG"]          # closest in log-size; self, dup class and foreign removed


def test_peers_sec_fallback(monkeypatch):
    tmap = {"AAA": {"cik": 1, "name": "Target"}, "B": {"cik": 2, "name": "B"}, "C": {"cik": 3, "name": "C"}}
    monkeypatch.setattr(P.sec, "ticker_map", lambda: tmap)
    monkeypatch.setattr(P, "sec_sic_ciks", lambda sic: [1, 2, 3, 99])
    monkeypatch.setattr(P, "sec_revenue_frame", lambda y: {2: 5e9, 3: 90e9})
    r = P.find_peers("AAA", sic=3571, quote={}, revenue=100e9, fiscal_year=2025)
    assert r.method == "sec-sic" and r.tickers == ["C", "B"]


def test_peers_none(monkeypatch):
    monkeypatch.setattr(P.sec, "ticker_map", lambda: {})
    assert P.find_peers("ZZZ", quote={}).method == "none"


def test_pipeline_end_to_end_with_auto_peers(monkeypatch):
    from stock_analyzer import pipeline
    from stock_analyzer.demo import DEMO_PEERS
    monkeypatch.setattr(pipeline.sec, "resolve", lambda q: {"ticker": "TST", "cik": 1, "name": "Test"})
    monkeypatch.setattr(pipeline.sec, "company_facts", lambda cik: make_facts(manipulate=True))
    monkeypatch.setattr(pipeline.sec, "company_info", lambda cik: {"sic": 3571, "sic_description": "Computers"})
    monkeypatch.setattr(pipeline.market, "quote", lambda t: {"price": 120.0, "beta": 1.2, "industry_key": "x"})
    monkeypatch.setattr(pipeline.market, "peer_multiples", lambda ts: [p for p in DEMO_PEERS if p["ticker"] in ts])
    seen = {}

    def fake_find(ticker, **kw):
        seen.update(kw, ticker=ticker)
        return P.PeerResult(["PEER1", "PEER2", "PEER3"], "yahoo-industry", "X")
    monkeypatch.setattr(pipeline, "find_peers", fake_find)
    out = pipeline.analyze("tst")
    assert seen["ticker"] == "TST" and seen["cik"] == 1 and seen["sic"] == 3571 and seen["revenue"] > 0
    assert out["peers"].tickers == ["PEER1", "PEER2", "PEER3"]
    assert out["valuation"].multiples is not None
    assert out["forensic"].counts()["red"] >= 3
