"""Compare 2–4 stocks side by side."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from stock_analyzer import service, storage
from ui.common import bottom_line_card, cached_inputs, current_user, money, pct, refresh_nonce

user = current_user()
st.markdown("## ⚖️ השוואת מניות")
wl = [w["ticker"] for w in storage.get_watchlist(user.email)]
c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
raw = c1.text_input("מניות להשוואה (2–4, מופרדות בפסיק)", value=st.session_state.get("cmp", ", ".join(wl[:3])),
                    placeholder="AAPL, MSFT, GOOGL")
go = c2.button("השווה", type="primary", width="stretch")
if go:
    st.session_state["cmp"] = raw
tickers = [t.strip().upper() for t in st.session_state.get("cmp", "").split(",") if t.strip()][:4]
if len(tickers) < 2:
    st.info("הכנס לפחות שתי מניות ולחץ השווה." + (" אפשר להתחיל מרשימת המעקב." if wl else ""))
    st.stop()

bundles, errors = {}, {}
prog = st.progress(0.0)
for i, t in enumerate(tickers, 1):
    prog.progress(i / len(tickers), text=f"טוען {t}…")
    try:
        bundles[t] = service.compute(cached_inputs(t, "off", (), refresh_nonce(t)))
    except Exception as e:
        errors[t] = str(e)
prog.empty()
for t, e in errors.items():
    st.warning(f"{t}: {e}")
if len(bundles) < 2:
    st.stop()

# ---- cards
cols = st.columns(len(bundles))
for c, (t, b) in zip(cols, bundles.items()):
    with c:
        st.markdown(f"#### {t}")
        st.caption(b.fin.name)
        st.markdown(bottom_line_card(service.bottom_line(b), compact=True), unsafe_allow_html=True)

# ---- price vs range, normalized to price
rows = [service.compare_row(b) for b in bundles.values()]
rng = pd.DataFrame([{"ticker": r["ticker"], "low": r["fv_low"] / r["price"], "base": r["fv_base"] / r["price"],
                     "high": r["fv_high"] / r["price"]} for r in rows if r["price"] and r["fv_base"]])
if not rng.empty:
    st.markdown("#### טווח שווי ביחס למחיר")
    bars = alt.Chart(rng).mark_bar(height=20, cornerRadius=4, color="#2f6fde", opacity=.55).encode(
        y=alt.Y("ticker:N", title=None), x=alt.X("low:Q", title="שווי / מחיר (1.0 = המחיר הנוכחי)", axis=alt.Axis(format=".0%")),
        x2="high:Q", tooltip=[alt.Tooltip("low:Q", format=".0%"), alt.Tooltip("base:Q", format=".0%"),
                              alt.Tooltip("high:Q", format=".0%")])
    ticks = alt.Chart(rng).mark_tick(color="#f58518", thickness=3, size=24).encode(y="ticker:N", x="base:Q")
    rule = alt.Chart(pd.DataFrame({"x": [1.0]})).mark_rule(color="#d93025", strokeDash=[6, 3], strokeWidth=2).encode(x="x:Q")
    st.altair_chart(alt.layer(bars, ticks, rule).properties(height=60 * len(rng) + 40), width="stretch")
    st.caption("מימין לקו האדום = שווי גבוה מהמחיר. קו כתום = הערכת בסיס.")

# ---- metrics table
labels = [("price", "מחיר", money), ("fv_base", "שווי בסיס", money), ("mos", "מרווח ביטחון", lambda v: pct(v, 0, True)),
          ("implied_growth", "צמיחה שהמחיר מגלם", pct), ("hist_growth", "צמיחה היסטורית (5ש')", pct),
          ("revenue", "הכנסות", money), ("op_margin", "מרווח תפעולי", pct), ("fcf_margin", "מרווח FCF", pct),
          ("roe", "ROE", pct), ("net_debt_ebitda", "חוב נטו / EBITDA", lambda v: "—" if v is None else f"{v:.1f}x"),
          ("piotroski", "Piotroski (0–9)", lambda v: "—" if v is None else str(v)),
          ("beneish", "Beneish M", lambda v: "—" if v is None else f"{v:.2f}"),
          ("red", "🔴 דגלים אדומים", str), ("yellow", "🟡 לבדוק", str)]
better_high = {"mos", "hist_growth", "op_margin", "fcf_margin", "roe", "piotroski"}
better_low = {"implied_growth", "net_debt_ebitda", "beneish", "red", "yellow"}
table = {}
for r in rows:
    col = {}
    for k, name, f in labels:
        v = r.get(k)
        col[name] = f(v) if v is not None else "—"
    table[r["ticker"]] = col
df = pd.DataFrame(table)


def highlight(row):
    key = next(k for k, n, _ in labels if n == row.name)
    vals = {r["ticker"]: r.get(key) for r in rows}
    nums = {t: v for t, v in vals.items() if isinstance(v, (int, float)) and v == v}
    if len(nums) < 2 or key not in better_high | better_low:
        return [""] * len(row)
    best = (max if key in better_high else min)(nums, key=nums.get)
    return ["background-color: rgba(30,142,62,.18); font-weight:600" if t == best else "" for t in row.index]


st.markdown("#### מדדים זה לצד זה")
st.dataframe(df.style.apply(highlight, axis=1), width="stretch")
st.caption("מודגש בירוק = הטוב ביותר בשורה (לפי כיוון המדד). השוואה כמותית בלבד — כל חברה בענף ובשלב חיים שונה.")
