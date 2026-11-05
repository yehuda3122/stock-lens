"""Stage 2 — forensic accounting checks ("red flags").

Each check returns a Flag with a traffic-light status and a Hebrew explanation of what
was found and why it matters. A red flag is a reason to dig deeper, not proof of fraud.

References
- Beneish (1999) "The Detection of Earnings Manipulation", Financial Analysts Journal.
- Altman (1968) Z-Score; Altman (2000) Z''-Score for non-manufacturers.
- Piotroski (2000) "Value Investing: The Use of Historical Financial Statement Information".
- Sloan (1996) "Do Stock Prices Fully Reflect Information in Accruals and Cash Flows".
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .financials import Financials

RED, YELLOW, GREEN, NA = "red", "yellow", "green", "na"
CATEGORIES = {
    "scores": "ציונים אקדמיים",
    "earnings": "איכות רווחים",
    "working_capital": "הון חוזר",
    "dilution": "דילול ותגמול",
    "balance": "מאזן וחוב",
    "reporting": "עקביות דיווח",
}


@dataclass
class Flag:
    key: str
    category: str
    title: str
    status: str
    value: str
    detail: str
    why: str
    data: dict = field(default_factory=dict)


@dataclass
class ForensicReport:
    flags: list[Flag]
    beneish: dict | None
    altman: dict | None
    piotroski: dict | None

    def counts(self) -> dict:
        c = {RED: 0, YELLOW: 0, GREEN: 0, NA: 0}
        for f in self.flags:
            c[f.status] += 1
        return c

    def by_category(self) -> dict[str, list[Flag]]:
        out: dict[str, list[Flag]] = {}
        for f in self.flags:
            out.setdefault(f.category, []).append(f)
        return out

    def table(self) -> pd.DataFrame:
        return pd.DataFrame([{"category": CATEGORIES[f.category], "check": f.title, "status": f.status,
                              "value": f.value, "detail": f.detail} for f in self.flags])


# ----------------------------------------------------------------- helpers
def _v(row, col):
    x = row.get(col) if hasattr(row, "get") else None
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)


def _div(a, b):
    return None if a is None or b is None or b == 0 else a / b


def _pct(x, d=1):
    return "—" if x is None else f"{x:.{d}%}"


def _lt_debt(row):
    v = _v(row, "lt_debt_noncurrent")
    if v is not None:
        return v
    td, cur = _v(row, "total_debt"), _v(row, "lt_debt_current") or 0
    return None if td is None else max(td - cur - (_v(row, "short_term_borrowings") or 0)
                                       - (_v(row, "commercial_paper") or 0), 0)


def _total_liabilities(row):
    tl = _v(row, "total_liabilities")
    if tl is None:
        ta, eq = _v(row, "total_assets"), _v(row, "equity_incl_nci") or _v(row, "equity")
        tl = None if ta is None or eq is None else ta - eq
    return tl


# ----------------------------------------------------------------- academic scores
BENEISH_W = {"DSRI": 0.920, "GMI": 0.528, "AQI": 0.404, "SGI": 0.892, "DEPI": 0.115,
             "SGAI": -0.172, "TATA": 4.679, "LVGI": -0.327}
BENEISH_HE = {"DSRI": "ימי לקוחות (גידול חריג בלקוחות מול מכירות)", "GMI": "שחיקת מרווח גולמי",
              "AQI": "איכות נכסים (נכסים 'רכים')", "SGI": "צמיחת מכירות", "DEPI": "האטה בקצב הפחת",
              "SGAI": "הוצאות מכירה והנהלה", "TATA": "אקרואלים (רווח שאינו מזומן)", "LVGI": "מינוף"}


def beneish(df: pd.DataFrame, i: int = -1) -> dict | None:
    if len(df) < 2:
        return None
    t, p = df.iloc[i], df.iloc[i - 1]
    missing = []

    def ratio(num, den, name):
        r = _div(num, den)
        if r is None or r <= 0:
            missing.append(name)
            return 1.0
        return r

    s_t, s_p = _v(t, "revenue"), _v(p, "revenue")
    if not s_t or not s_p:
        return None
    dsri = ratio(_div(_v(t, "receivables"), s_t), _div(_v(p, "receivables"), s_p), "DSRI")
    gmi = ratio(_div(_v(p, "gross_profit"), s_p), _div(_v(t, "gross_profit"), s_t), "GMI")

    def soft(row):
        ca, ppe, ta = _v(row, "current_assets"), _v(row, "ppe_net"), _v(row, "total_assets")
        return None if None in (ca, ppe, ta) or ta == 0 else 1 - (ca + ppe) / ta
    aqi = ratio(soft(t), soft(p), "AQI")
    sgi = s_t / s_p

    def deprate(row):
        d, ppe = _v(row, "dna"), _v(row, "ppe_net")
        return None if d is None or ppe is None or d + ppe == 0 else d / (d + ppe)
    depi = ratio(deprate(p), deprate(t), "DEPI")
    sgai = ratio(_div(_v(t, "sga"), s_t), _div(_v(p, "sga"), s_p), "SGAI")

    def lev(row):
        cl, ltd, ta = _v(row, "current_liabilities"), _lt_debt(row), _v(row, "total_assets")
        return None if None in (cl, ta) or ta == 0 else (cl + (ltd or 0)) / ta
    lvgi = ratio(lev(t), lev(p), "LVGI")
    ni, cfo, ta = _v(t, "net_income"), _v(t, "cfo"), _v(t, "total_assets")
    tata = (ni - cfo) / ta if None not in (ni, cfo, ta) and ta else 0.0
    if tata == 0.0 and None in (ni, cfo, ta):
        missing.append("TATA")
    comps = {"DSRI": dsri, "GMI": gmi, "AQI": aqi, "SGI": sgi, "DEPI": depi, "SGAI": sgai, "TATA": tata, "LVGI": lvgi}
    m = -4.84 + sum(BENEISH_W[k] * v for k, v in comps.items())
    return {"m_score": m, "components": comps, "missing": missing, "year": int(df.index[i])}


def altman(df: pd.DataFrame, sic: int | None, market_cap: float | None) -> dict | None:
    r = df.iloc[-1]
    ta = _v(r, "total_assets")
    ca, cl = _v(r, "current_assets"), _v(r, "current_liabilities")
    tl = _total_liabilities(r)
    if not ta or ca is None or cl is None or not tl:
        return None
    x1 = (ca - cl) / ta
    x2 = (_v(r, "retained_earnings") or 0) / ta
    x3 = (_v(r, "operating_income") or 0) / ta
    manufacturing = sic is not None and 2000 <= sic <= 3999
    if manufacturing and market_cap:
        x4, x5 = market_cap / tl, (_v(r, "revenue") or 0) / ta
        z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
        return {"z": z, "model": "Z (manufacturing)", "safe": 2.99, "distress": 1.81,
                "components": {"WC/TA": x1, "RE/TA": x2, "EBIT/TA": x3, "MVE/TL": x4, "Sales/TA": x5}}
    eq = _v(r, "equity_incl_nci") or _v(r, "equity") or 0
    x4 = eq / tl
    z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
    return {"z": z, "model": "Z'' (non-manufacturing)", "safe": 2.6, "distress": 1.1,
            "components": {"WC/TA": x1, "RE/TA": x2, "EBIT/TA": x3, "BVE/TL": x4}}


PIOTROSKI_HE = {
    "roa_pos": "תשואה על נכסים חיובית", "cfo_pos": "תזרים מפעילות חיובי", "roa_up": "שיפור בתשואה על נכסים",
    "cfo_gt_ni": "תזרים גבוה מהרווח (איכות רווח)", "lev_down": "ירידה במינוף לז\"א",
    "cr_up": "שיפור ביחס השוטף", "no_dilution": "ללא הנפקת מניות", "gm_up": "שיפור במרווח הגולמי",
    "turn_up": "שיפור במחזור הנכסים",
}


def piotroski(df: pd.DataFrame) -> dict | None:
    if len(df) < 2:
        return None
    t, p = df.iloc[-1], df.iloc[-2]
    ta_t, ta_p = _v(t, "total_assets"), _v(p, "total_assets")
    ni_t, ni_p, cfo = _v(t, "net_income"), _v(p, "net_income"), _v(t, "cfo")
    if None in (ta_t, ta_p, ni_t, ni_p, cfo):
        return None
    tests: dict[str, bool | None] = {}
    roa_t, roa_p = ni_t / ta_t, ni_p / ta_p
    tests["roa_pos"] = roa_t > 0
    tests["cfo_pos"] = cfo > 0
    tests["roa_up"] = roa_t > roa_p
    tests["cfo_gt_ni"] = cfo > ni_t
    lt, lp = _lt_debt(t), _lt_debt(p)
    tests["lev_down"] = None if lt is None or lp is None else (lt / ta_t <= lp / ta_p)
    cr_t = _div(_v(t, "current_assets"), _v(t, "current_liabilities"))
    cr_p = _div(_v(p, "current_assets"), _v(p, "current_liabilities"))
    tests["cr_up"] = None if cr_t is None or cr_p is None else cr_t > cr_p
    sh_t, sh_p = _v(t, "diluted_shares"), _v(p, "diluted_shares")
    tests["no_dilution"] = None if not sh_t or not sh_p else sh_t <= sh_p * 1.005
    gm_t, gm_p = _v(t, "gross_margin"), _v(p, "gross_margin")
    tests["gm_up"] = None if gm_t is None or gm_p is None else gm_t > gm_p
    at_t, at_p = _div(_v(t, "revenue"), ta_t), _div(_v(p, "revenue"), ta_p)
    tests["turn_up"] = None if at_t is None or at_p is None else at_t > at_p
    score = sum(1 for v in tests.values() if v)
    return {"score": score, "available": sum(1 for v in tests.values() if v is not None), "tests": tests}


# ----------------------------------------------------------------- report
def analyze(fin: Financials, market_cap: float | None = None) -> ForensicReport:
    df = fin.annual
    last = df.iloc[-1]
    flags: list[Flag] = []
    add = lambda *a, **k: flags.append(Flag(*a, **k))  # noqa: E731

    # --- Beneish ---
    b = None if fin.is_financial else beneish(df)
    if b:
        m = b["m_score"]
        st = RED if m > -1.78 else YELLOW if m > -2.22 else GREEN
        top = sorted(((k, v) for k, v in b["components"].items() if k != "TATA"), key=lambda kv: -abs(kv[1] - 1))[:2]
        drivers = ", ".join(f"{BENEISH_HE[k]} ({v:.2f})" for k, v in top)
        add("beneish", "scores", "Beneish M-Score — סיכון ל'ייפוי' רווחים", st, f"{m:.2f}",
            f"סף אזהרה: ‎-1.78. המרכיבים הבולטים: {drivers}."
            + (f" חסרים נתונים ל-{', '.join(b['missing'])} (הוצב ערך ניטרלי)." if b["missing"] else ""),
            "מודל סטטיסטי שזיהה כ-76% מהחברות שתמרנו רווחים. חברות בצמיחה מהירה מקבלות לעיתים ציון גבוה "
            "בלי שום בעיה — בדוק אילו מרכיבים דוחפים את הציון.", b)
    else:
        add("beneish", "scores", "Beneish M-Score — סיכון ל'ייפוי' רווחים", NA, "—",
            "לא חושב (חברה פיננסית או נתונים חסרים).", "")

    # --- Altman ---
    a = None if fin.is_financial else altman(df, fin.sic, market_cap)
    if a:
        z = a["z"]
        st = GREEN if z > a["safe"] else RED if z < a["distress"] else YELLOW
        zone = {GREEN: "אזור בטוח", YELLOW: "אזור אפור", RED: "אזור מצוקה"}[st]
        add("altman", "scores", "Altman Z-Score — סיכון לקשיים פיננסיים", st, f"{z:.2f}",
            f"{a['model']}: {zone} (בטוח מעל {a['safe']}, מצוקה מתחת ל-{a['distress']}).",
            "מנבא סיכון לפשיטת רגל בטווח של שנתיים. פחות רלוונטי לחברות עם הון עצמי שלילי בגלל רכישות עצמיות.", a)
    else:
        add("altman", "scores", "Altman Z-Score — סיכון לקשיים פיננסיים", NA, "—",
            "לא חושב (חברה פיננסית או מאזן לא מסווג לשוטף/לא שוטף).", "")

    # --- Piotroski ---
    pz = None if fin.is_financial else piotroski(df)
    if pz:
        s = pz["score"]
        st = GREEN if s >= 7 else RED if s <= 3 else YELLOW
        failed = [PIOTROSKI_HE[k] for k, v in pz["tests"].items() if v is False]
        add("piotroski", "scores", "Piotroski F-Score — בריאות פיננסית (0–9)", st, f"{s}/{pz['available']}",
            ("נכשל ב: " + ", ".join(failed) + ".") if failed else "עבר את כל המבחנים הזמינים.",
            "9 מבחנים בינאריים של רווחיות, מינוף ויעילות מול השנה הקודמת. 7+ = חזק, 3 ומטה = חלש.", pz)

    # --- Earnings quality: NI vs CFO ---
    tail = df.tail(3)
    ni3, cfo3 = tail["net_income"].sum(min_count=1), tail["cfo"].sum(min_count=1)
    if pd.notna(ni3) and pd.notna(cfo3) and ni3 > 0:
        r = cfo3 / ni3
        neg_years = [int(y) for y, row in tail.iterrows() if (row["net_income"] or 0) > 0 and (row["cfo"] or 0) < 0]
        st = RED if (r < 0.8 or neg_years) else YELLOW if r < 1.0 else GREEN
        add("ni_vs_cfo", "earnings", "רווח נקי מול תזרים מזומנים (3 שנים)", st, f"{r:.2f}x",
            f"על כל דולר רווח מדווח נכנסו {r:.2f} דולר מזומן מפעילות."
            + (f" בשנים {neg_years} היה רווח אבל תזרים שלילי!" if neg_years else ""),
            "רווח שלא הופך למזומן לאורך זמן הוא הסימן הקלאסי לרווח 'חשבונאי' — הכרה אגרסיבית בהכנסות או היוון הוצאות.",
            {"ratio": r})
    else:
        add("ni_vs_cfo", "earnings", "רווח נקי מול תזרים מזומנים (3 שנים)", NA, "—", "החברה הפסדית — היחס לא משמעותי.", "")

    # --- Sloan accruals ---
    if len(df) >= 2:
        avg_ta = (df["total_assets"].iloc[-1] + df["total_assets"].iloc[-2]) / 2
        ni, cfo = _v(last, "net_income"), _v(last, "cfo")
        if ni is not None and cfo is not None and avg_ta:
            acc = (ni - cfo) / avg_ta
            st = RED if acc > 0.10 else YELLOW if acc > 0.05 else GREEN
            add("sloan", "earnings", "יחס אקרואלים (Sloan)", st, _pct(acc),
                "(רווח נקי − תזרים מפעילות) / ממוצע סך נכסים.",
                "חברות עם אקרואלים גבוהים נוטות לרווחים ולתשואות נמוכים יותר בהמשך. מעל 10% = אזהרה.", {"accruals": acc})

    # --- Capex vs depreciation ---
    c3 = df.tail(3)
    capex, dna = c3["capex"].sum(min_count=1), c3["dna"].sum(min_count=1)
    if pd.notna(capex) and pd.notna(dna) and dna > 0:
        r = capex / dna
        st = YELLOW if r < 0.7 else GREEN
        add("capex_dna", "earnings", "השקעות הוניות מול פחת (3 שנים)", st, f"{r:.2f}x",
            f"Capex הוא {r:.0%} מהפחת." + (" השקעה נמוכה מהשחיקה עלולה לנפח את התזרים החופשי זמנית." if r < 0.7 else ""),
            "חברה שמשקיעה פחות מהפחת לאורך זמן 'אוכלת' את הנכסים שלה — התזרים החופשי נראה טוב יותר ממה שהוא.")

    # --- Receivables vs revenue ---
    def growth(col, n=1):
        s = df[col].dropna()
        return None if len(s) <= n or s.iloc[-1 - n] <= 0 else s.iloc[-1] / s.iloc[-1 - n] - 1
    gr, gar = growth("revenue"), growth("receivables")
    if gr is not None and gar is not None:
        gap = gar - gr
        dso = (df["receivables"] / df["revenue"] * 365).dropna()
        st = RED if gap > 0.15 else YELLOW if gap > 0.05 else GREEN
        add("ar_vs_rev", "working_capital", "צמיחת לקוחות מול צמיחת הכנסות", st, f"{_pct(gar)} מול {_pct(gr)}",
            f"ימי לקוחות (DSO): {dso.iloc[-1]:.0f} ימים" + (f" (לעומת {dso.iloc[-4:-1].mean():.0f} בממוצע 3 שנים קודמות)." if len(dso) >= 4 else "."),
            "כשהלקוחות גדלים מהר מההכנסות, ייתכן שהחברה מכירה בהכנסות לפני שגבתה (channel stuffing, תנאי אשראי מקלים).",
            {"gap": gap})

    gi = growth("inventory")
    gc = growth("cogs") if df["cogs"].notna().sum() > 1 else gr
    if gi is not None and gc is not None:
        gap = gi - gc
        st = RED if gap > 0.20 else YELLOW if gap > 0.08 else GREEN
        add("inv_vs_cogs", "working_capital", "צמיחת מלאי מול עלות המכר", st, f"{_pct(gi)} מול {_pct(gc)}",
            "מלאי שגדל מהר מהמכירות.",
            "מלאי עודף עלול להצביע על ביקוש חלש והפחתות עתידיות, או על ניפוח רווח גולמי דרך העמסת עלויות קבועות על המלאי.",
            {"gap": gap})

    # --- SBC ---
    sbc, rev, fcf = _v(last, "sbc"), _v(last, "revenue"), _v(last, "fcf")
    if sbc is not None and rev:
        s_rev = sbc / rev
        s_fcf = sbc / fcf if fcf and fcf > 0 else None
        st = RED if s_rev > 0.10 or (s_fcf or 0) > 0.5 else YELLOW if s_rev > 0.05 or (s_fcf or 0) > 0.25 else GREEN
        add("sbc", "dilution", "תגמול מבוסס מניות (SBC)", st, f"{_pct(s_rev)} מההכנסות",
            f"SBC = {_pct(s_fcf, 0)} מהתזרים החופשי." if s_fcf is not None else "התזרים החופשי שלילי.",
            "SBC לא יוצא מהקופה אבל הוא עלות אמיתית לבעלי המניות. חברות שמציגות 'תזרים חופשי' לפני SBC מנפחות אותו.")

    # --- Dilution ---
    sh = df["diluted_shares"].dropna()
    if len(sh) >= 4:
        cagr = (sh.iloc[-1] / sh.iloc[-4]) ** (1 / 3) - 1
        st = RED if cagr > 0.03 else YELLOW if cagr > 0.01 else GREEN
        add("dilution", "dilution", "שינוי במספר המניות (3 שנים, שנתי)", st, f"{cagr:+.1%}",
            "קיטון = רכישות עצמיות (טוב לבעלי המניות). גידול = דילול." ,
            "דילול מתמשך שוחק את הערך למניה גם כשהחברה עצמה גדלה.", {"cagr": cagr})

    # --- Balance sheet / debt ---
    op, intr = _v(last, "operating_income"), _v(last, "interest_expense")
    if op is not None:
        if not intr or intr <= 0:
            add("coverage", "balance", "כיסוי ריבית", GREEN, "—", "אין הוצאות ריבית מהותיות.", "")
        else:
            cov = op / intr
            st = RED if cov < 3 else YELLOW if cov < 6 else GREEN
            add("coverage", "balance", "כיסוי ריבית (רווח תפעולי / ריבית)", st, f"{cov:.1f}x",
                "מתחת ל-3 = שולי ביטחון צרים.", "יכולת לשרת את החוב גם אם הרווחים יורדים.")
    ebitda = (op or 0) + (_v(last, "dna") or 0)
    nd = (_v(last, "total_debt") or 0) - (_v(last, "cash_and_investments") or 0)
    if ebitda > 0 and not fin.is_financial:
        lev = nd / ebitda
        st = GREEN if lev < 2.5 else YELLOW if lev < 4 else RED
        add("leverage", "balance", "חוב נטו / EBITDA", st, f"{lev:.1f}x" if nd > 0 else "מזומן נטו",
            "מעל 4 = מינוף גבוה." if nd > 0 else "יש לחברה יותר מזומן מחוב.", "כמה שנות רווח תפעולי צריך כדי להחזיר את החוב.")
    ta = _v(last, "total_assets")
    gw = (_v(last, "goodwill") or 0) + (_v(last, "intangibles") or 0)
    if ta and gw:
        r = gw / ta
        st = RED if r > 0.6 else YELLOW if r > 0.4 else GREEN
        add("goodwill", "balance", "מוניטין ונכסים בלתי מוחשיים / סך נכסים", st, _pct(r),
            "חלק גבוה = הרבה רכישות בעבר.", "סיכון להפחתות (impairment) בעתיד; חלק מהנכסים לא ניתן למימוש.")

    # --- Reporting consistency ---
    rs = fin.restatements
    if rs is not None and not rs.empty:
        recent = rs[rs["period_end"] >= str(int(df.index[-1]) - 5)]
        if not recent.empty:
            worst = recent.loc[recent["change"].abs().idxmax()]
            st = RED if abs(worst["change"]) > 0.05 else YELLOW
            items = ", ".join(sorted(set(recent["item"])))
            add("restatements", "reporting", "שינויים במספרים שדווחו בעבר (הצגה מחדש)", st, f"{len(recent)} מקרים",
                f"פריטים: {items}. השינוי הגדול: {worst['item']} לתקופה {worst['period_end']} "
                f"שינוי של {worst['change']:+.1%} (דווח {worst['original_filed']}, עודכן {worst['latest_filed']}).",
                "שינוי קטן נובע לרוב מסיווג מחדש או פעילות שהופסקה. שינוי גדול / חוזר בהכנסות או ברווח — דורש קריאה בדוח.",
                {"rows": recent.to_dict("records")})
        else:
            add("restatements", "reporting", "שינויים במספרים שדווחו בעבר (הצגה מחדש)", GREEN, "0", "אין ב-5 השנים האחרונות.", "")
    else:
        add("restatements", "reporting", "שינויים במספרים שדווחו בעבר (הצגה מחדש)", GREEN, "0",
            "כל הערכים השנתיים זהים בין הדיווח המקורי לעדכני.", "")

    le = _v(last, "liabilities_and_equity")
    if ta and le:
        diff = abs(le / ta - 1)
        add("balance_check", "reporting", "מאזן מאוזן (נכסים = התחייבויות + הון)", RED if diff > 0.005 else GREEN,
            _pct(diff, 2), "פער בין סך הנכסים לסך ההתחייבויות וההון בנתוני XBRL.",
            "אמור להיות 0 תמיד. פער מצביע על טעות בתיוג הדיווח — כדאי לאמת מול הדוח המקורי.")
    if gr is not None and _v(last, "operating_margin") is not None and len(df) >= 4:
        om = df["operating_margin"].dropna().tail(4)
        jump = om.iloc[-1] - om.iloc[:-1].mean()
        if jump > 0.08:
            add("margin_jump", "earnings", "קפיצה חדה במרווח התפעולי", YELLOW, f"{jump:+.1%}",
                f"מרווח {om.iloc[-1]:.1%} לעומת ממוצע {om.iloc[:-1].mean():.1%} בשנים הקודמות.",
                "שיפור חד יכול להיות אמיתי — אבל גם תוצאה של שינוי מדיניות חשבונאית, היוון הוצאות או פריט חד-פעמי.")

    return ForensicReport(flags, b, a, pz)
