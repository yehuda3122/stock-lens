"""Synthetic SEC 'companyfacts' payload shaped exactly like the real API."""


def _flow(vals: dict[int, float], extra_quarters=True, restated: dict | None = None):
    out = []
    for y, v in vals.items():
        out.append({"start": f"{y-1}-10-01", "end": f"{y}-09-30", "val": v, "fy": y, "fp": "FY",
                    "form": "10-K", "filed": f"{y}-11-01"})
        # same number repeated as a comparative in the next year's 10-K
        out.append({"start": f"{y-1}-10-01", "end": f"{y}-09-30", "val": (restated or {}).get(y, v),
                    "fy": y + 1, "fp": "FY", "form": "10-K", "filed": f"{y+1}-11-01"})
        if extra_quarters:  # quarterly entries must be ignored
            out.append({"start": f"{y}-07-01", "end": f"{y}-09-30", "val": v / 4, "fy": y, "fp": "Q4",
                        "form": "10-K", "filed": f"{y}-11-01"})
            out.append({"start": f"{y}-01-01", "end": f"{y}-03-31", "val": v / 4, "fy": y, "fp": "Q2",
                        "form": "10-Q", "filed": f"{y}-05-01"})
    return out


def _inst(vals: dict[int, float]):
    return [{"end": f"{y}-09-30", "val": v, "fy": y, "fp": "FY", "form": "10-K", "filed": f"{y}-11-01"}
            for y, v in vals.items()]


YEARS = list(range(2016, 2026))


def make_facts(revenue0=100e9, growth=0.08, op_margin=0.25, fcf_margin=0.22, manipulate=False):
    """manipulate=True builds a company with classic warning signs in the last 2 years:
    receivables & inventory ballooning, profit not turning into cash, dilution, big restatement."""
    rev = {y: revenue0 * (1 + growth) ** i for i, y in enumerate(YEARS)}
    op = {y: r * op_margin for y, r in rev.items()}
    pretax = {y: o * 0.98 for y, o in op.items()}
    tax = {y: p * 0.18 for y, p in pretax.items()}
    ni = {y: pretax[y] - tax[y] for y in YEARS}
    capex = {y: r * 0.04 for y, r in rev.items()}
    cfo = {y: rev[y] * fcf_margin + capex[y] for y in YEARS}
    shares = {y: 10e9 * (0.98 ** i) for i, y in enumerate(YEARS)}
    ar = {y: r * 0.10 for y, r in rev.items()}
    inv = {y: r * 0.45 * 0.12 for y, r in rev.items()}
    restated_rev = {YEARS[-2]: rev[YEARS[-2]] * 0.99}
    if manipulate:
        for k, y in enumerate(YEARS[-2:], 1):
            ar[y] *= 1.0 + 0.5 * k
            inv[y] *= 1.0 + 0.4 * k
            cfo[y] = ni[y] * 0.4
            shares[y] *= 1.0 + 0.06 * k
        restated_rev = {YEARS[-2]: rev[YEARS[-2]] * 0.90}
    usgaap = {
        # older years under SalesRevenueNet, newer under ASC 606 tag -> tests tag merging
        "SalesRevenueNet": {"units": {"USD": _flow({y: rev[y] for y in YEARS[:3]})}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": _flow({y: rev[y] for y in YEARS[3:]},
                                                                restated=restated_rev)}},
        "CostOfRevenue": {"units": {"USD": _flow({y: r * 0.55 for y, r in rev.items()})}},
        "OperatingIncomeLoss": {"units": {"USD": _flow(op)}},
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
            {"units": {"USD": _flow(pretax)}},
        "IncomeTaxExpenseBenefit": {"units": {"USD": _flow(tax)}},
        "InterestExpense": {"units": {"USD": _flow({y: 3e9 for y in YEARS})}},
        "NetIncomeLoss": {"units": {"USD": _flow(ni)}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": _flow(cfo)}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": _flow(capex)}},
        "DepreciationDepletionAndAmortization": {"units": {"USD": _flow({y: r * 0.03 for y, r in rev.items()})}},
        "ShareBasedCompensation": {"units": {"USD": _flow({y: r * 0.02 for y, r in rev.items()})}},
        "PaymentsOfDividends": {"units": {"USD": _flow({y: n * 0.25 for y, n in ni.items()})}},
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": _flow(shares)}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": _flow({y: ni[y] / shares[y] for y in YEARS})}},
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": _inst({y: 30e9 for y in YEARS})}},
        "MarketableSecuritiesCurrent": {"units": {"USD": _inst({y: 20e9 for y in YEARS})}},
        "LongTermDebtNoncurrent": {"units": {"USD": _inst({y: 90e9 for y in YEARS})}},
        "LongTermDebtCurrent": {"units": {"USD": _inst({y: 10e9 for y in YEARS})}},
        "CommercialPaper": {"units": {"USD": _inst({y: 5e9 for y in YEARS})}},
        "StockholdersEquity": {"units": {"USD": _inst({y: 60e9 + 5e9 * i for i, y in enumerate(YEARS)})}},
        "Assets": {"units": {"USD": _inst({y: 350e9 for y in YEARS})}},
        "LiabilitiesAndStockholdersEquity": {"units": {"USD": _inst({y: 350e9 for y in YEARS})}},
        "Liabilities": {"units": {"USD": _inst({y: 350e9 - (60e9 + 5e9 * i) for i, y in enumerate(YEARS)})}},
        "AccountsReceivableNetCurrent": {"units": {"USD": _inst(ar)}},
        "InventoryNet": {"units": {"USD": _inst(inv)}},
        "AssetsCurrent": {"units": {"USD": _inst({y: 50e9 + ar[y] + inv[y] for y in YEARS})}},
        "LiabilitiesCurrent": {"units": {"USD": _inst({y: 0.6 * (50e9 + ar[y] + inv[y]) for y in YEARS})}},
        "PropertyPlantAndEquipmentNet": {"units": {"USD": _inst({y: r * 0.3 for y, r in rev.items()})}},
        "SellingGeneralAndAdministrativeExpense": {"units": {"USD": _flow({y: r * 0.10 for y, r in rev.items()})}},
        "RetainedEarningsAccumulatedDeficit": {"units": {"USD": _inst({y: 20e9 + 3e9 * i for i, y in enumerate(YEARS)})}},
        "Goodwill": {"units": {"USD": _inst({y: 40e9 for y in YEARS})}},
    }
    dei = {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2025-10-15", "val": shares[2025] * 0.995, "form": "10-K", "filed": "2025-11-01"}]}}}
    return {"cik": 1, "entityName": "TESTCO INC", "facts": {"us-gaap": usgaap, "dei": dei}}


DEMO_QUOTE = {"price": 150.0, "beta": 1.1, "market_cap": None, "currency": "USD",
              "sector": "Technology (demo)", "industry": "Synthetic data"}
DEMO_PEERS = [
    {"ticker": "PEER1", "pe": 20, "ev_ebitda": 14, "ev_revenue": 4, "pb": 6},
    {"ticker": "PEER2", "pe": 25, "ev_ebitda": 17, "ev_revenue": 5, "pb": 8},
    {"ticker": "PEER3", "pe": 30, "ev_ebitda": 20, "ev_revenue": 6, "pb": 10},
]
