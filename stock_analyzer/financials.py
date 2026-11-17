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

# ---- IFRS (foreign private issuers filing 20-F, e.g. TSM, NVO) ------------------------
IFRS_FLOW_TAGS = {
    "revenue": ["Revenue", "RevenueFromContractsWithCustomers"],
    "cogs": ["CostOfSales"],
    "gross_profit": ["GrossProfit"],
    "sga": ["SellingGeneralAndAdministrativeExpense", "AdministrativeExpense"],
    "operating_income": ["ProfitLossFromOperatingActivities"],
    "pretax_income": ["ProfitLossBeforeTax"],
    "income_tax": ["IncomeTaxExpenseContinuingOperations"],
    "interest_expense": ["InterestExpense", "FinanceCosts", "InterestExpenseOnBorrowings"],
    "net_income": ["ProfitLossAttributableToOwnersOfParent", "ProfitLoss"],
    "cfo": ["CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
              "PurchaseOfPropertyPlantAndEquipment"],
    "dna": ["DepreciationAndAmortisationExpense", "AdjustmentsForDepreciationAndAmortisationExpense",
            "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss",
            "DepreciationExpense"],
    "sbc": ["AdjustmentsForSharebasedPayments", "ExpenseFromSharebasedPaymentTransactionsWithEmployees"],
    "dividends_paid": ["DividendsPaidClassifiedAsFinancingActivities", "DividendsPaid"],
    "buybacks": ["PaymentsToAcquireOrRedeemEntitysShares"],
}
IFRS_INSTANT_TAGS = {
    "cash": ["CashAndCashEquivalents"],
    "short_term_investments": ["CurrentInvestments", "OtherCurrentFinancialAssets"],
    "receivables": ["TradeAndOtherCurrentReceivables", "CurrentTradeReceivables"],
    "inventory": ["Inventories"],
    "current_assets": ["CurrentAssets"],
    "current_liabilities": ["CurrentLiabilities"],
    "ppe_net": ["PropertyPlantAndEquipment"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "equity": ["EquityAttributableToOwnersOfParent", "Equity"],
    "retained_earnings": ["RetainedEarnings"],
    "equity_incl_nci": ["Equity"],
    "liabilities_and_equity": ["EquityAndLiabilities"],
    "goodwill": ["Goodwill"],
    "intangibles": ["IntangibleAssetsOtherThanGoodwill"],
    "lt_debt_total": ["Borrowings"],
    "lt_debt_noncurrent": ["LongtermBorrowings", "NoncurrentPortionOfNoncurrentLoansReceived"],
    "lt_debt_current": ["CurrentPortionOfLongtermBorrowings"],
    "debt_current": ["CurrentLoansReceivedAndCurrentPortionOfNoncurrentLoansReceived"],
    "short_term_borrowings": ["ShorttermBorrowings"],
    "commercial_paper": [],
    "bonds_noncurrent": ["NoncurrentPortionOfNoncurrentBondsIssued"],
    "bonds_current": ["CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued"],
}
IFRS_SHARE_TAGS = ["AdjustedWeightedAverageShares", "WeightedAverageShares"]
IFRS_EPS_TAGS = ["DilutedEarningsLossPerShare", "BasicAndDilutedEarningsLossPerShare", "BasicEarningsLossPerShare"]

ANNUAL_FORMS = ("10-K", "20-F", "40-F")


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
    currency: str = "USD"              # reporting currency of the filings (values in `annual` are converted to USD)
    fx_rate: float = 1.0               # USD per 1 unit of `currency` used for the conversion
    foreign_filer: bool = False        # files 20-F / 40-F (shares are usually ADRs in the US)

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


def _is_annual_form(form) -> bool:
    return str(form or "").startswith(ANNUAL_FORMS)


def detect_profile(facts: dict) -> tuple[str, str]:
    """(taxonomy, reporting currency). US filers: ('us-gaap','USD'); e.g. TSM: ('ifrs-full','TWD'), ASML: ('us-gaap','EUR')."""
    f = facts.get("facts", {})
    best = None
    for tax, flow in (("us-gaap", FLOW_TAGS), ("ifrs-full", IFRS_FLOW_TAGS)):
        if tax not in f:
            continue
        counts: dict[str, int] = {}
        for tag in flow["revenue"] + flow["net_income"]:
            for unit, entries in f[tax].get(tag, {}).get("units", {}).items():
                n = sum(1 for e in entries if _is_annual_form(e.get("form")))
                if n and "/" not in unit and unit not in ("shares", "pure"):
                    counts[unit] = counts.get(unit, 0) + n
        if counts:
            cur = max(counts, key=counts.get)
            if best is None or counts[cur] > best[2]:
                best = (tax, cur, counts[cur])
    return (best[0], best[1]) if best else ("us-gaap", "USD")


def _annual_series(facts: dict, tag: str, kind: str, unit: str = "USD", tax: str = "us-gaap") -> dict[str, float]:
    """{period_end_date: value} from annual filings (10-K / 20-F / 40-F); the most recently filed value wins
    (so restated numbers replace originals)."""
    best: dict[str, tuple[str, float]] = {}
    for e in _entries(facts, tag, unit, tax):
        if not _is_annual_form(e.get("form")):
            continue
        if kind == "flow":
            if "start" not in e or not (340 <= _days(e["start"], e["end"]) <= 380):
                continue
        end, filed = e["end"], e.get("filed", "")
        if end not in best or filed > best[end][0]:
            best[end] = (filed, float(e["val"]))
    return {k: v for k, (_, v) in best.items()}


def restatement_history(facts: dict, tag: str, kind: str = "flow", unit: str = "USD", tax: str = "us-gaap") -> pd.DataFrame:
    """All reported versions of each annual value (used later for restatement checks)."""
    rows = []
    for e in _entries(facts, tag, unit, tax):
        if not _is_annual_form(e.get("form")):
            continue
        if kind == "flow" and ("start" not in e or not (340 <= _days(e["start"], e["end"]) <= 380)):
            continue
        rows.append({"end": e["end"], "filed": e.get("filed"), "form": e.get("form"), "val": e["val"]})
    return pd.DataFrame(rows).drop_duplicates()


RESTATEMENT_ITEMS = {"revenue": ("flow", FLOW_TAGS["revenue"]), "net_income": ("flow", FLOW_TAGS["net_income"]),
                     "cfo": ("flow", FLOW_TAGS["cfo"]), "total_assets": ("instant", INSTANT_TAGS["total_assets"]),
                     "equity": ("instant", INSTANT_TAGS["equity"])}


def find_restatements(facts: dict, min_change: float = 0.005, *, tax: str = "us-gaap", unit: str = "USD",
                      fx: float = 1.0) -> pd.DataFrame:
    """Annual values that changed between the first and the latest annual report that reported them."""
    rows = []
    flow, inst = (FLOW_TAGS, INSTANT_TAGS) if tax == "us-gaap" else (IFRS_FLOW_TAGS, IFRS_INSTANT_TAGS)
    items = {"revenue": ("flow", flow["revenue"]), "net_income": ("flow", flow["net_income"]),
             "cfo": ("flow", flow["cfo"]), "total_assets": ("instant", inst["total_assets"]),
             "equity": ("instant", inst["equity"])}
    for item, (kind, tags) in items.items():
        for tag in tags:
            h = restatement_history(facts, tag, kind, unit, tax)
            if h.empty:
                continue
            for end, g in h.groupby("end"):
                g = g.sort_values("filed")
                orig, last = float(g["val"].iloc[0]), float(g["val"].iloc[-1])
                if orig != 0 and abs(last / orig - 1) >= min_change:
                    rows.append({"item": item, "tag": tag, "period_end": end, "original": orig * fx, "latest": last * fx,
                                 "change": last / orig - 1, "original_filed": g["filed"].iloc[0],
                                 "latest_filed": g["filed"].iloc[-1]})
            break  # only the primary tag that has data
    return pd.DataFrame(rows)


def _merge(facts, tags, kind, unit="USD", tax="us-gaap") -> dict[str, float]:
    out: dict[str, float] = {}
    for t in tags:
        for end, v in _annual_series(facts, t, kind, unit, tax).items():
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
                     max_years: int = 10, fx=None) -> Financials:
    """fx: optional callable(currency) -> USD per unit; used when the company reports in another currency."""
    info = info or {}
    notes: list[str] = []
    tax, cur = detect_profile(facts)
    flow, inst = (FLOW_TAGS, INSTANT_TAGS) if tax == "us-gaap" else (IFRS_FLOW_TAGS, IFRS_INSTANT_TAGS)
    share_tags, eps_tags = (SHARE_TAGS, EPS_TAGS) if tax == "us-gaap" else (IFRS_SHARE_TAGS, IFRS_EPS_TAGS)
    series = {k: _merge(facts, tags, "flow", cur, tax) for k, tags in flow.items()}
    series.update({k: _merge(facts, tags, "instant", cur, tax) for k, tags in inst.items()})
    series["diluted_shares"] = _merge(facts, share_tags, "flow", "shares", tax)
    series["eps_diluted"] = _merge(facts, eps_tags, "flow", f"{cur}/shares", tax)

    ends = _fiscal_year_ends(series)[-max_years:]
    if not ends:
        raise ValueError("לא נמצאו דוחות שנתיים (10-K / 20-F) עם הכנסות ורווח לחברה הזו ב-SEC.")

    forms = {e.get("form") for tag in flow["revenue"] for u in facts.get("facts", {}).get(tax, {}).get(tag, {})
             .get("units", {}).values() for e in u}
    foreign = any(str(f).startswith(("20-F", "40-F")) for f in forms)
    rate = 1.0
    if cur != "USD":
        if fx is None:
            from .data.market import fx_rate as fx
        rate = fx(cur)
        if not rate:
            raise ValueError(f"הדוחות של החברה במטבע {cur} ולא הצלחתי למשוך שער המרה לדולר.")
        for k in series:
            if k != "diluted_shares":
                series[k] = {e: v * rate for e, v in series[k].items()}
        notes.append(f"הדוחות מדווחים ב-{cur}; כל הסכומים הומרו לדולר לפי שער נוכחי ({rate:.4g} $ ל-1 {cur}). "
                     "שינויי שער לאורך השנים משפיעים על שיעורי הצמיחה בדולרים.")

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
    if "bonds_noncurrent" in df and df["lt_debt_total"].isna().all():      # IFRS: bonds reported separately
        total = total.fillna(0) + df["bonds_noncurrent"].fillna(0) + df["bonds_current"].fillna(0)
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
        restatements=find_restatements(facts, tax=tax, unit=cur, fx=rate),
        currency=cur,
        fx_rate=rate,
        foreign_filer=foreign,
    )


def apply_market_shares(fin: Financials, quote: dict) -> Financials:
    """Express per-share values per *traded* share.
    * Foreign filers trade as ADRs (1 TSM ADR = 5 ordinary shares).
    * Multi-class companies (BRK-A/BRK-B) report a share count that doesn't match the traded class.
    The market-implied count (market cap / price) is the consistent one; if the reported count differs by
    more than 15 %, rescale share counts / EPS to it."""
    price, mcap = quote.get("price"), quote.get("market_cap")
    market_shares = (mcap / price) if mcap and price else (quote.get("shares_outstanding") if fin.foreign_filer else None)
    reported = fin.shares_outstanding or (fin.annual["diluted_shares"].dropna().iloc[-1]
                                          if fin.annual["diluted_shares"].notna().any() else None)
    if not market_shares or not reported:
        if fin.foreign_filer:
            fin.notes.append("חברה זרה: לא הצלחתי לאמת את יחס ה-ADR — ערכים למניה עלולים להיות מוטים.")
        return fin
    ratio = float(reported) / float(market_shares)
    if abs(ratio - 1) <= 0.15:
        return fin
    df = fin.annual
    last_diluted = df["diluted_shares"].dropna().iloc[-1] if df["diluted_shares"].notna().any() else reported
    k = float(market_shares) / float(last_diluted)          # anchor the share history to today's traded count
    df["diluted_shares"] = (df["diluted_shares"] if df["diluted_shares"].notna().any() else reported) * k
    df["eps_diluted"] = df["net_income"] / df["diluted_shares"]
    df["book_value_per_share"] = df["equity"] / df["diluted_shares"]
    fin.shares_outstanding = float(market_shares)
    if fin.foreign_filer:
        fin.notes.append(f"חברה זרה הנסחרת כ-ADR: כל ADR שווה בערך {ratio:.2f} מניות רגילות — הערכים למניה מחושבים ל-ADR.")
    else:
        fin.notes.append(f"מספר המניות בדוח ({reported:,.0f}) לא תואם למניה הנסחרת (כנראה כמה סוגי מניות); "
                         f"הערכים למניה חושבו לפי שווי השוק / מחיר ({market_shares:,.0f} מניות שוות-ערך).")
    return fin
