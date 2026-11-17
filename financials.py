"""Turn raw SEC XBRL 'company facts' into a clean annual financials table.

Each line item lists several XBRL tags because companies (and years) differ in
which tag they use. For each fiscal year we take the first tag that has a value.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

# ---- line item -> candidate us-gaap tags (in priority order) -------------------
FLOW_TAGS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet",
        "RevenuesNetOfInterestExpense",
    ],
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfServices"],
    "gross_profit": ["GrossProfit"],
    "sga": ["SellingGeneralAndAdministrativeExpense"],
    "operating_income": ["OperatingIncomeLoss"],
    "pretax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
    ],
    "income_tax": ["IncomeTaxExpenseBenefit"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestPaidNet"],
    "net_income": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
              "PaymentsForCapitalImprovements"],
    "dna": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
            "DepreciationAndAmortization", "Depreciation"],
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "dividends_paid": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
}
INSTANT_TAGS = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash"],
    "short_term_investments": ["MarketableSecuritiesCurrent", "ShortTermInvestments",
                               "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "receivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
    "inventory": ["InventoryNet"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "ppe_net": ["PropertyPlantAndEquipmentNet"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "equity": ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
    "equity_incl_nci": ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "StockholdersEquity"],
    "liabilities_and_equity": ["LiabilitiesAndStockholdersEquity"],
    "goodwill": ["Goodwill"],
    "intangibles": ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"],
    "lt_debt_total": ["LongTermDebt", "LongTermDebtAndCapitalLeaseObligations", "DebtLongtermAndShorttermCombinedAmount"],
    "lt_debt_noncurrent": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligationsNoncurrent"],
    "lt_debt_current": ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "debt_current": ["DebtCurrent"],
    "short_term_borrowings": ["ShortTermBorrowings"],
    "commercial_paper": ["CommercialPaper"],
}
SHARE_TAGS = ["WeightedAverageNumberOfDilutedSharesOutstanding"]
EPS_TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"]


@dataclass
class Financials:
    ticker: str
    name: str
    annual: pd.DataFrame                 # index = fiscal year (int), columns = line items
    shares_outstanding: float | None     # latest reported share count
    sic: int | None = None
    sic_description: str | None = None
    notes: list[str] = field(default_factory=list)
    restatements: pd.DataFrame = field(default_factory=pd.DataFrame)
    cik: int | None = None

    @property
    def latest(self) -> pd.Series:
        return self.annual.iloc[-1]

    @property
    def is_financial(self) -> bool:
        """Banks/insurers/REITs (SIC 6000-6799): FCF-based DCF is not appropriate."""
        return self.sic is not None and 6000 <= self.sic <= 6799


# ---- parsing helpers -------------------------------------------------------------
def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _entries(facts: dict, tag: str, unit: str = "USD", taxonomy: str = "us-gaap") -> list[dict]:
    try:
        return facts["facts"][taxonomy][tag]["units"][unit]
    except KeyError:
        return []


def _annual_series(facts: dict, tag: str, kind: str, unit: str = "USD") -> dict[str, float]:
    """{period_end_date: value} from 10-K filings; the most recently filed value wins
    (so restated numbers replace originals)."""
    best: dict[str, tuple[str, float]] = {}
    for e in _entries(facts, tag, unit):
        if not str(e.get("form", "")).startswith("10-K"):
            continue
        if kind == "flow":
            if "start" not in e or not (340 <= _days(e["start"], e["end"]) <= 380):
                continue
        end, filed = e["end"], e.get("filed", "")
        if end not in best or filed > best[end][0]:
            best[end] = (filed, float(e["val"]))
    return {k: v for k, (_, v) in best.items()}


def restatement_history(facts: dict, tag: str, kind: str = "flow") -> pd.DataFrame:
    """All reported versions of each annual value (used later for restatement checks)."""
    rows = []
    for e in _entries(facts, tag):
        if not str(e.get("form", "")).startswith("10-K"):
            continue
        if kind == "flow" and ("start" not in e or not (340 <= _days(e["start"], e["end"]) <= 380)):
            continue
        rows.append({"end": e["end"], "filed": e.get("filed"), "form": e.get("form"), "val": e["val"]})
    return pd.DataFrame(rows).drop_duplicates()


RESTATEMENT_ITEMS = {"revenue": ("flow", FLOW_TAGS["revenue"]), "net_income": ("flow", FLOW_TAGS["net_income"]),
                     "cfo": ("flow", FLOW_TAGS["cfo"]), "total_assets": ("instant", INSTANT_TAGS["total_assets"]),
                     "equity": ("instant", INSTANT_TAGS["equity"])}


def find_restatements(facts: dict, min_change: float = 0.005) -> pd.DataFrame:
    """Annual values that changed between the first and the latest 10-K that reported them."""
    rows = []
    for item, (kind, tags) in RESTATEMENT_ITEMS.items():
        for tag in tags:
            h = restatement_history(facts, tag, kind)
            if h.empty:
                continue
            for end, g in h.groupby("end"):
                g = g.sort_values("filed")
                orig, last = float(g["val"].iloc[0]), float(g["val"].iloc[-1])
                if orig != 0 and abs(last / orig - 1) >= min_change:
                    rows.append({"item": item, "tag": tag, "period_end": end, "original": orig, "latest": last,
                                 "change": last / orig - 1, "original_filed": g["filed"].iloc[0],
                                 "latest_filed": g["filed"].iloc[-1]})
            break  # only the primary tag that has data
    return pd.DataFrame(rows)


def _merge(facts, tags, kind, unit="USD") -> dict[str, float]:
    out: dict[str, float] = {}
    for t in tags:
        for end, v in _annual_series(facts, t, kind, unit).items():
            out.setdefault(end, v)
    return out


def fy_label(end: str) -> int:
    """52/53-week fiscal years can end in the first days of January -> belong to the prior year."""
    y, m, d = int(end[:4]), int(end[5:7]), int(end[8:10])
    return y - 1 if (m == 1 and d <= 10) else y


def _fiscal_year_ends(series_by_item: dict[str, dict]) -> list[str]:
    ends = set(series_by_item.get("revenue", {})) | set(series_by_item.get("net_income", {}))
    # Keep one end date per year (latest), sorted
    by_year: dict[int, str] = {}
    for e in ends:
        y = fy_label(e)
        if y not in by_year or e > by_year[y]:
            by_year[y] = e
    return [by_year[y] for y in sorted(by_year)]


def build_financials(facts: dict, ticker: str, name: str | None = None, info: dict | None = None,
                     max_years: int = 10) -> Financials:
    info = info or {}
    notes: list[str] = []
    series = {k: _merge(facts, tags, "flow") for k, tags in FLOW_TAGS.items()}
    series.update({k: _merge(facts, tags, "instant") for k, tags in INSTANT_TAGS.items()})
    series["diluted_shares"] = _merge(facts, SHARE_TAGS, "flow", unit="shares")
    series["eps_diluted"] = _merge(facts, EPS_TAGS, "flow", unit="USD/shares")

    ends = _fiscal_year_ends(series)[-max_years:]
    if not ends:
        raise ValueError("No annual (10-K) revenue / net income data found for this company.")

    df = pd.DataFrame({k: [s.get(e) for e in ends] for k, s in series.items()},
                      index=[fy_label(e) for e in ends], dtype="float64")
    df.index.name = "fiscal_year"
    df["period_end"] = ends

    # ---- derived items ----
    if df["revenue"].isna().all():
        notes.append("Revenue tag not found — revenue-based models are unreliable.")
    if df["gross_profit"].isna().all() and not df["cogs"].isna().all():
        df["gross_profit"] = df["revenue"] - df["cogs"]

    # Total debt (approximation; see README)
    total = df["lt_debt_total"].copy()
    alt = df["lt_debt_noncurrent"].fillna(0) + df["lt_debt_current"].fillna(df["debt_current"]).fillna(0)
    total = total.fillna(alt.where((df["lt_debt_noncurrent"].notna()) | (df["lt_debt_current"].notna())))
    total = total + df["short_term_borrowings"].fillna(0) + df["commercial_paper"].fillna(0)
    df["total_debt"] = total.fillna(0.0)
    df["cash_and_investments"] = df["cash"].fillna(0) + df["short_term_investments"].fillna(0)

    df["capex"] = df["capex"].abs()
    df["fcf"] = df["cfo"] - df["capex"].fillna(0)
    df["fcf_after_sbc"] = df["fcf"] - df["sbc"].fillna(0)
    df["tax_rate"] = (df["income_tax"] / df["pretax_income"]).where(df["pretax_income"] > 0)
    for col, num in [("gross_margin", "gross_profit"), ("operating_margin", "operating_income"),
                     ("net_margin", "net_income"), ("fcf_margin", "fcf"),
                     ("fcf_after_sbc_margin", "fcf_after_sbc")]:
        df[col] = df[num] / df["revenue"]
    df["revenue_growth"] = df["revenue"].pct_change(fill_method=None)
    df["roe"] = df["net_income"] / df["equity"]
    df["book_value_per_share"] = df["equity"] / df["diluted_shares"]

    # Latest share count (cover page of latest filing)
    shares = None
    dei = _entries(facts, "EntityCommonStockSharesOutstanding", unit="shares", taxonomy="dei")
    if dei:
        latest_end = max(e["end"] for e in dei)
        # sum share classes reported for the same date (e.g. GOOGL class A/B/C)
        shares = float(sum(e["val"] for e in dei if e["end"] == latest_end
                           and e.get("filed") == max(x.get("filed", "") for x in dei if x["end"] == latest_end)))
    if not shares and df["diluted_shares"].notna().any():
        shares = float(df["diluted_shares"].dropna().iloc[-1])
        notes.append("Using diluted weighted-average shares (cover-page share count not found).")

    return Financials(
        ticker=ticker.upper(),
        name=name or info.get("name") or facts.get("entityName", ticker),
        annual=df,
        shares_outstanding=shares,
        sic=info.get("sic"),
        sic_description=info.get("sic_description"),
        notes=notes,
        restatements=find_restatements(facts),
    )
