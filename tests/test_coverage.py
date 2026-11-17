"""Ticker lookup, foreign (20-F / IFRS / non-USD) filers, share-class & ADR reconciliation."""
import pytest

from stock_analyzer.data import sec
from stock_analyzer.financials import apply_market_shares, build_financials, detect_profile

TMAP = {"MSFT": {"cik": 1, "name": "MICROSOFT CORP"}, "BRK-B": {"cik": 2, "name": "BERKSHIRE HATHAWAY INC"},
        "AAPL": {"cik": 3, "name": "Apple Inc."}, "GOOGL": {"cik": 4, "name": "Alphabet Inc."},
        "TSM": {"cik": 5, "name": "TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD"}, "KO": {"cik": 6, "name": "COCA COLA CO"}}


@pytest.fixture
def lookup(monkeypatch):
    from stock_analyzer.data import market
    monkeypatch.setattr(sec, "ticker_map", lambda: TMAP)
    hits = {"google": [{"symbol": "GOOGL", "type": "EQUITY", "name": "Alphabet Inc."}],
            "XLU": [{"symbol": "XLU", "type": "ETF", "name": "Utilities Select"}],
            "tsmc": [{"symbol": "TSMC34.SA", "type": "EQUITY", "name": "TAIWAN SEMICONDUCTOR MANUFACTUR"}],
            "elbit tlv": [{"symbol": "ESLT.TA", "type": "EQUITY", "name": "ELBIT SYSTEMS"}]}
    monkeypatch.setattr(market, "search", lambda q, n=8: hits.get(q, []))


@pytest.mark.parametrize("q,expected", [("MSFT", "MSFT"), ("$msft", "MSFT"), (" aapl ", "AAPL"), ("BRK.B", "BRK-B"),
                                        ("brk/b", "BRK-B"), ("coca cola", "KO"), ("אפל", "AAPL"), ("גוגל", "GOOGL"),
                                        ("google", "GOOGL"), ("tsmc", "TSM"), ("microsoft", "MSFT")])
def test_resolve(lookup, q, expected):
    assert sec.resolve(q)["ticker"] == expected


def test_resolve_etf_and_foreign_only_messages(lookup):
    with pytest.raises(sec.LookupProblem, match="קרן סל"):
        sec.resolve("XLU")
    with pytest.raises(sec.LookupProblem, match="SEC"):
        sec.resolve("elbit tlv")
    with pytest.raises(sec.LookupProblem, match="לא מצאתי"):
        sec.resolve("zzzzqqq")


def _ifrs_facts():
    def flow(vals, unit="TWD"):
        return {"units": {unit: [{"start": f"{y}-01-01", "end": f"{y}-12-31", "val": v, "form": "20-F",
                                  "filed": f"{y+1}-04-15"} for y, v in vals.items()]}}

    def inst(vals, unit="TWD"):
        return {"units": {unit: [{"end": f"{y}-12-31", "val": v, "form": "20-F", "filed": f"{y+1}-04-15"}
                                 for y, v in vals.items()]}}
    years = range(2019, 2025)
    rev = {y: 1000e9 * 1.2 ** i for i, y in enumerate(years)}
    return {"facts": {
        "ifrs-full": {
            "Revenue": flow(rev), "ProfitLoss": flow({y: r * .4 for y, r in rev.items()}),
            "ProfitLossFromOperatingActivities": flow({y: r * .45 for y, r in rev.items()}),
            "CashFlowsFromUsedInOperatingActivities": flow({y: r * .6 for y, r in rev.items()}),
            "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": flow({y: r * .3 for y, r in rev.items()}),
            "Assets": inst({y: r * 2 for y, r in rev.items()}), "Equity": inst({y: r * 1.4 for y, r in rev.items()}),
            "CashAndCashEquivalents": inst({y: 500e9 for y in years}),
            "LongtermBorrowings": inst({y: 100e9 for y in years}),
            "NoncurrentPortionOfNoncurrentBondsIssued": inst({y: 900e9 for y in years}),
            "AdjustedWeightedAverageShares": flow({y: 25.9e9 for y in years}, "shares"),
            "DilutedEarningsLossPerShare": flow({y: r * .4 / 25.9e9 for y, r in rev.items()}, "TWD/shares"),
        },
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
            {"end": "2025-03-31", "val": 25.9e9, "form": "20-F", "filed": "2025-04-15"}]}}}}}


def test_ifrs_foreign_filer_converted_to_usd():
    facts = _ifrs_facts()
    assert detect_profile(facts) == ("ifrs-full", "TWD")
    fin = build_financials(facts, "TSM", info={"sic": 3674}, fx=lambda c: 0.03)
    last = fin.latest
    assert fin.currency == "TWD" and fin.foreign_filer and fin.fx_rate == 0.03
    assert last["revenue"] == pytest.approx(1000e9 * 1.2 ** 5 * 0.03)
    assert last["total_debt"] == pytest.approx((100e9 + 900e9) * 0.03)      # bank loans + bonds
    assert last["fcf_margin"] == pytest.approx(0.3)
    assert any("TWD" in n for n in fin.notes)

    # ADR: 1 ADR = 5 ordinary shares -> per-share values per ADR
    apply_market_shares(fin, {"price": 300.0, "market_cap": 300.0 * 5.18e9})
    assert fin.shares_outstanding == pytest.approx(5.18e9)
    assert fin.latest["eps_diluted"] == pytest.approx(fin.latest["net_income"] / 5.18e9)
    assert any("ADR" in n for n in fin.notes)


def test_share_class_mismatch_and_normal_case():
    from stock_analyzer.demo import make_facts
    fin = build_financials(make_facts(), "X", info={"sic": 3571})
    before = fin.shares_outstanding
    apply_market_shares(fin, {"price": 100.0, "market_cap": 100.0 * before * 1.05})   # within 15% -> untouched
    assert fin.shares_outstanding == before
    apply_market_shares(fin, {"price": 100.0, "market_cap": 100.0 * before * 1500})   # BRK-style mismatch
    assert fin.shares_outstanding == pytest.approx(before * 1500)
    assert any("סוגי מניות" in n for n in fin.notes)


def test_negative_fair_value_is_not_shown():
    from stock_analyzer.demo import make_facts
    from stock_analyzer import valuation
    fin = build_financials(make_facts(fcf_margin=-0.4, op_margin=-0.3), "BURN", info={"sic": 7372})
    a = valuation.derive(fin, {"beta": 1.5, "price": 10})
    r = valuation.run(fin, a, 10, [])
    assert r.fair_value["base"] is None and r.margin_of_safety is None
    assert any("שלילי" in w for w in r.warnings)
