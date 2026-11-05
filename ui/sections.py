"""Renderers for the analysis page sections (one function per tab)."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from stock_analyzer import forensic, storage, valuation
from stock_analyzer.service import Bundle
from ui.common import MODEL_HE, SEV_ICON, STATUS_ICON, money, pct


def valuation_tab(b: Bundle):
    val, a, fin, price = b.val, b.assumptions, b.fin, b.price
    if val.reverse.get("implied_growth") is not None:
        st.markdown(f"🔁 **מה המחיר מגלם (Reverse DCF):** כדי להצדיק \\${price:,.2f}, החברה צריכה צמיחת הכנסות של "
                    f"**{pct(val.reverse['implied_growth'])} בשנה** בחמש השנים הקרובות (במרווח FCF של {pct(a.fcf_margin)}), "
                    f"או מרווח FCF של **{pct(val.reverse['implied_margin'])}** בצמיחה של {pct(a.growth_initial)}. "
                    f"להשוואה — צמיחה היסטורית: {pct(valuation.assumptions.historical_cagr(fin.annual['revenue']))}.")
    tbl = val.model_table()
    if not tbl.empty:
        ff = tbl.reset_index().assign(model=lambda d: d["model"].map(MODEL_HE).fillna(d["model"]))
        bars = alt.Chart(ff).mark_bar(height=18, cornerRadius=4).encode(
            y=alt.Y("model:N", title=None, sort=None, axis=alt.Axis(labelLimit=260)),
            x=alt.X("low:Q", title="שווי למניה ($)"), x2="high:Q",
            color=alt.condition("datum.weight > 0", alt.value("#2f6fde"), alt.value("#bab0ac")),
            tooltip=["model", alt.Tooltip("low:Q", format="$.2f"), alt.Tooltip("base:Q", format="$.2f"),
                     alt.Tooltip("high:Q", format="$.2f"), alt.Tooltip("weight:Q", format=".0%")])
        ticks = alt.Chart(ff).mark_tick(color="#f58518", thickness=3, size=22).encode(y=alt.Y("model:N", sort=None), x="base:Q")
        layers = [bars, ticks]
        if price:
            layers.append(alt.Chart(pd.DataFrame({"p": [price]})).mark_rule(color="#d93025", strokeWidth=2,
                                                                             strokeDash=[6, 3]).encode(x="p:Q"))
        st.altair_chart(alt.layer(*layers).properties(height=45 * len(ff) + 40), width="stretch")
        st.caption("פס = טווח פסימי–אופטימי · קו כתום = בסיס · קו אדום מקווקו = מחיר נוכחי · באפור = לא משוקלל")
        show = tbl.rename(index=MODEL_HE)
        st.dataframe(show.style.format({"low": "${:,.2f}", "base": "${:,.2f}", "high": "${:,.2f}", "weight": "{:.0%}"}),
                     width="stretch")
    if val.multiples:
        st.markdown("**מכפילים לפי מתחרים** (חציון; טווח = רבעון 25–75)")
        m = pd.DataFrame(val.multiples["by_multiple"]).T.rename_axis("multiple")
        st.dataframe(m.style.format({"peer_multiple": "{:.1f}x", "low": "${:,.2f}", "base": "${:,.2f}", "high": "${:,.2f}"}),
                     width="stretch")
        st.dataframe(pd.DataFrame(b.inputs.peer_rows), width="stretch", hide_index=True)
    if val.epv:
        st.markdown(f"**EPV:** מרווח תפעולי מנורמל {pct(val.epv['normalized_operating_margin'])} → "
                    f"NOPAT {money(val.epv['nopat'])}. אם המחיר גבוה בהרבה מ-EPV, משלמים על צמיחה עתידית.")


def flags_tab(b: Bundle):
    fr, fin = b.fr, b.fin
    st.caption("🟢 תקין · 🟡 לבדוק · 🔴 דגל אדום · ⚪ לא רלוונטי. דגל אדום = סיבה לקרוא את הדוח לעומק, לא הוכחה להונאה.")
    for cat, items in fr.by_category().items():
        st.markdown(f"#### {forensic.CATEGORIES[cat]}")
        for f in items:
            with st.expander(f"{STATUS_ICON[f.status]}  {f.title}  —  {f.value}", expanded=(f.status == "red")):
                st.write(f.detail)
                if f.why:
                    st.caption("למה זה חשוב: " + f.why)
                if f.key == "beneish" and fr.beneish:
                    comp = pd.DataFrame({"מדד": list(fr.beneish["components"]),
                                         "ערך": list(fr.beneish["components"].values()),
                                         "משקל": [forensic.BENEISH_W[k] for k in fr.beneish["components"]],
                                         "תיאור": [forensic.BENEISH_HE[k] for k in fr.beneish["components"]]})
                    comp["תרומה לציון"] = comp["ערך"] * comp["משקל"]
                    st.dataframe(comp.style.format({"ערך": "{:.3f}", "משקל": "{:+.3f}", "תרומה לציון": "{:+.3f}"}),
                                 hide_index=True, width="stretch")
                    st.caption("ערך 1.0 = ללא שינוי מהשנה הקודמת. ציון = ‎-4.84 + סכום התרומות.")
                if f.key == "piotroski" and fr.piotroski:
                    st.dataframe(pd.DataFrame([{"מבחן": forensic.PIOTROSKI_HE[k],
                                                "תוצאה": "✅" if v else ("❌" if v is False else "—")}
                                               for k, v in fr.piotroski["tests"].items()]),
                                 hide_index=True, width="stretch")
                if f.key == "altman" and fr.altman:
                    st.dataframe(pd.DataFrame([fr.altman["components"]]).style.format("{:.3f}"),
                                 hide_index=True, width="stretch")
                if f.key == "ni_vs_cfo":
                    d = fin.annual[["net_income", "cfo"]].rename(columns={"net_income": "רווח נקי", "cfo": "תזרים מפעילות"})
                    d = d.reset_index().melt("fiscal_year", var_name="מדד", value_name="USD")
                    st.altair_chart(alt.Chart(d).mark_bar().encode(
                        x=alt.X("fiscal_year:O", title=None), xOffset="מדד:N",
                        y=alt.Y("USD:Q", axis=alt.Axis(format="~s")), color="מדד:N").properties(height=220),
                        width="stretch")
                if f.key == "ar_vs_rev":
                    dso = (fin.annual["receivables"] / fin.annual["revenue"] * 365).rename("DSO (ימים)")
                    dso.index = dso.index.astype(str)
                    st.line_chart(dso, height=180)
                if f.key == "restatements" and f.data.get("rows"):
                    rt = pd.DataFrame(f.data["rows"])[["item", "period_end", "original", "latest", "change",
                                                      "original_filed", "latest_filed"]]
                    st.dataframe(rt.style.format({"original": money, "latest": money, "change": "{:+.2%}"}),
                                 hide_index=True, width="stretch")


def news_results(b: Bundle, nc, na):
    d, arts = na.data, nc.by_id()

    def cite(srcs):
        links = [f"[{s}]({arts[s].url})" for s in srcs if s in arts]
        return (" " + " ".join(links)) if links else ""

    for w in nc.windows:
        if w.error:
            st.warning(f"{w.label}: {w.error}")
    for wmsg in na.warnings:
        st.info(wmsg)

    st.markdown("### 🧾 תקציר — מה הולך עם החברה")
    st.info(d["summary"]["text"] + cite(d["summary"]["sources"]))
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("### 📍 המצב כעת")
        for c in d["current_state"]:
            st.markdown(f"- {c['text']}{cite(c['sources'])}")
    with c2:
        st.markdown("### ❓ נקודות לחשוב עליהן")
        for c in d["questions"]:
            st.markdown(f"- {c['text']}{cite(c['sources'])}")

    st.markdown("### ⚠️ חששות")
    flag_titles = {f.key: f.title for f in b.fr.flags}
    for c in d["concerns"]:
        rel = [flag_titles[k] for k in c.get("related_red_flags", []) if k in flag_titles]
        with st.container(border=True):
            st.markdown(f"**{SEV_ICON.get(c['severity'], c['severity'])} · {c['title']}**  \n{c['text']}{cite(c['sources'])}"
                        + (f"  \n<small>🚩 קשור לבדיקות: {', '.join(rel)}</small>" if rel else ""),
                        unsafe_allow_html=True)

    st.markdown("### 📈 איך הסיפור התפתח לאורך השנה")
    for t in d["timeline"]:
        st.markdown(f"- **{t['period']} — {t['headline']}:** {t['text']}{cite(t['sources'])}")

    c1, c2 = st.columns(2, gap="large")
    with c1:
        if d["numbers_vs_narrative"]:
            st.markdown("### 🔗 מספרים מול סיפור")
            for c in d["numbers_vs_narrative"]:
                st.markdown(f"- {c['text']}{cite(c['sources'])}")
    with c2:
        if d["positives"]:
            st.markdown("### ✅ נקודות חיוביות")
            for c in d["positives"]:
                st.markdown(f"- {c['text']}{cite(c['sources'])}")

    cc = d["conclusion"]
    conf = {"high": "גבוהה", "medium": "בינונית", "low": "נמוכה"}.get(cc.get("confidence"), cc.get("confidence"))
    st.markdown("### 🧭 נקודת סיכום")
    st.success(f"{cc['text']}{cite(cc['sources'])}\n\n**מה ישנה את התמונה:** {cc['what_would_change_view']}\n\n"
               f"**רמת ביטחון בניתוח:** {conf} — {cc['confidence_reason']}")

    st.markdown("### 📚 מקורות וניתוחם")
    sa = {s["id"]: s for s in d["source_analysis"]}
    sent = {"positive": "🟢 חיובי", "negative": "🔴 שלילי", "neutral": "⚪ ניטרלי", "mixed": "🟡 מעורב"}
    imp = {"high": "גבוהה", "medium": "בינונית", "low": "נמוכה"}
    kind = {"news": "חדשות", "opinion": "דעה", "press_release": "הודעת חברה"}
    rows = []
    for art in sorted(nc.articles, key=lambda x: x.published, reverse=True):
        s = sa.get(art.id, {})
        rows.append({"id": art.id, "תאריך": art.published, "מקור": art.source, "כותרת": art.title, "קישור": art.url,
                     "סנטימנט": sent.get(s.get("sentiment"), "—"), "חשיבות": imp.get(s.get("importance"), "—"),
                     "ניתוח המודל": s.get("takeaway", ""), "אמינות": s.get("reliability_note", ""),
                     "סוג": kind.get(art.kind, art.kind), "סיקור": art.coverage,
                     "חלון": art.period, "טקסט נקרא": "✓" if (art.text or art.summary) else "כותרת בלבד"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"קישור": st.column_config.LinkColumn("קישור", display_text="פתח"),
                                "סיקור": st.column_config.NumberColumn("סיקור", help="מספר כלי תקשורת שסיקרו את אותו סיפור")})
    st.caption(f"מודל: {na.model}"
               + (f" · טוקנים: {na.usage.get('input_tokens', 0):,} קלט / {na.usage.get('output_tokens', 0):,} פלט" if na.usage else "")
               + f" · טענות שהוסרו בגלל מקור לא תקף: {na.removed_claims} · נשמר במטמון ל-24 שעות")
    st.caption("⚠️ ניתוח של מודל שפה על בסיס כותרות ותקצירים — עלול לטעות. בדוק את המקורות לפני החלטה.")


def dcf_tab(b: Bundle):
    val, a, fin, price = b.val, b.assumptions, b.fin, b.price
    if not val.dcf:
        st.info("DCF לא רלוונטי לחברה זו (ראה אזהרות).")
        return
    base = val.dcf["base"]
    cc = st.columns(4)
    cc[0].metric("שווי פירמה (EV)", money(base["enterprise_value"]))
    cc[1].metric("חוב נטו", money(a.net_debt))
    cc[2].metric("שווי הון", money(base["equity_value"]))
    cc[3].metric("חלק הערך הטרמינלי", pct(base["terminal_share"], 0))
    proj = base["projection"].copy()
    proj.insert(0, "שנה", fin.annual.index[-1] + proj.pop("year"))
    st.dataframe(proj.style.format({"growth": "{:.1%}", "revenue": lambda v: money(v), "fcf": lambda v: money(v),
                                    "discount_factor": "{:.3f}", "pv_fcf": lambda v: money(v)}),
                 width="stretch", hide_index=True)
    st.markdown("**טבלת רגישות — שווי למניה** (שורות: WACC, עמודות: צמיחה שנים 1–5)")
    s = val.sensitivity.copy()
    s.index = [f"{w:.1%}" for w in s.index]
    s.columns = [f"{g:.1%}" for g in s.columns]
    sty = s.style.format("${:,.0f}")
    if price:
        sty = sty.map(lambda v: f"background-color: {'rgba(30,142,62,.25)' if v > price else 'rgba(217,48,37,.22)'}"
                      if pd.notna(v) else "")
    st.dataframe(sty, width="stretch")
    st.caption("ירוק = שווי מעל המחיר הנוכחי, אדום = מתחת.")


def history_data_tab(b: Bundle):
    df = b.fin.annual
    cols = {"revenue": "הכנסות", "gross_margin": "מרווח גולמי", "operating_margin": "מרווח תפעולי",
            "net_income": "רווח נקי", "cfo": "תזרים מפעילות", "fcf": "FCF", "sbc": "SBC",
            "fcf_margin": "מרווח FCF", "roe": "ROE", "total_debt": "חוב", "cash_and_investments": "מזומן והשקעות",
            "diluted_shares": "מניות (מדולל)", "eps_diluted": "EPS"}
    chart_df = df[["revenue", "fcf", "net_income"]].rename(columns={"revenue": "הכנסות", "fcf": "FCF", "net_income": "רווח נקי"})
    chart_df = chart_df.reset_index().melt("fiscal_year", var_name="מדד", value_name="USD")
    st.altair_chart(alt.Chart(chart_df).mark_line(point=True).encode(
        x=alt.X("fiscal_year:O", title=None), y=alt.Y("USD:Q", axis=alt.Axis(format="~s")), color="מדד:N"),
        width="stretch")
    h = df[list(cols)].T.rename(index=cols)
    h.columns = [str(c) for c in h.columns]
    st.dataframe(h.apply(lambda r: r.map(
        (lambda v: pct(v)) if r.name in ("מרווח גולמי", "מרווח תפעולי", "מרווח FCF", "ROE")
        else (lambda v: f"{v:.2f}" if pd.notna(v) else "—") if r.name == "EPS"
        else (lambda v: f"{v/1e6:,.0f}M" if pd.notna(v) else "—") if r.name == "מניות (מדולל)"
        else (lambda v: money(v))), axis=1), width="stretch")


def checks_history_tab(email: str, ticker: str):
    hist = storage.history(email, ticker, "valuation", limit=100)
    if not hist:
        st.info("אין עדיין היסטוריה לחברה הזו.")
        return
    df = pd.DataFrame([{"תאריך": h["created_at"], "מחיר": h["price"], "שווי בסיס": h["fv_base"], "פסימי": h["fv_low"],
                        "אופטימי": h["fv_high"], "מרווח ביטחון": h["mos"], "🔴": h["red"], "🟡": h["yellow"]}
                       for h in hist])
    if len(df) > 1:
        long = df.melt("תאריך", value_vars=["מחיר", "שווי בסיס"], var_name="סדרה", value_name="$")
        st.altair_chart(alt.Chart(long).mark_line(point=True).encode(
            x=alt.X("תאריך:T", title=None), y=alt.Y("$:Q", title=None), color="סדרה:N"), width="stretch")
    st.dataframe(df.style.format({"מחיר": "${:,.2f}", "שווי בסיס": "${:,.2f}", "פסימי": "${:,.0f}", "אופטימי": "${:,.0f}",
                                  "מרווח ביטחון": "{:+.0%}"}, na_rep="—"), hide_index=True, width="stretch")
    news = storage.history(email, ticker, "news", limit=10)
    if news:
        st.markdown("**ניתוחי חדשות קודמים**")
        for h in news:
            n = h["payload"].get("news") or {}
            with st.expander(f"{h['created_at']:%d/%m/%Y %H:%M} — {', '.join(t for _, t in n.get('top_concerns', []))[:90]}"):
                st.write(n.get("conclusion", ""))
