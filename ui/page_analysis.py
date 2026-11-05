"""Main page: analyze one stock."""
from __future__ import annotations

import streamlit as st

from stock_analyzer import config, report, service, storage
from stock_analyzer.data import cache
from ui import sections
from ui.common import (METHOD_HE, PROVIDER_NAMES, bottom_line_card, bump_refresh, cached_inputs, current_user,
                       llm_settings, refresh_nonce)

DEMO_OPTIONS = {"off": "נתונים אמיתיים", "clean": "דמו: חברה תקינה", "flags": "דמו: חברה עם דגלים"}

user = current_user()

# ---------------------------------------------------------------- search bar
with st.container():
    c1, c2, c3 = st.columns([5, 1.2, 1.2], vertical_alignment="bottom")
    query = c1.text_input("סימול או שם חברה", value=st.session_state.get("query", ""), placeholder="למשל AAPL, MSFT, Nvidia",
                          help="מניות הנסחרות בארה\"ב (מדווחות ל-SEC)")
    go = c2.button("🔎 נתח", type="primary", width="stretch")
    with c3.popover("אפשרויות", width="stretch"):
        peers_txt = st.text_input("מתחרות להשוואה", value=st.session_state.get("peers_txt", ""), placeholder="ריק = אוטומטי",
                                  help="השאר ריק והמערכת תמצא מתחרות מאותו ענף בגודל דומה.")
        demo = st.radio("מקור נתונים", list(DEMO_OPTIONS), format_func=DEMO_OPTIONS.get,
                        index=list(DEMO_OPTIONS).index(st.session_state.get("demo", "off")))
    if go:
        st.session_state.update(query=query.strip(), peers_txt=peers_txt, demo=demo, ran=True)
        for k in [k for k in st.session_state if str(k).startswith("a_")]:
            del st.session_state[k]
        st.rerun()

query, demo = st.session_state.get("query", ""), st.session_state.get("demo", "off")
if not st.session_state.get("ran") or (not query and demo == "off"):
    st.markdown("## 📊 ניתוח מניה")
    st.write("הכנס סימול ולחץ **נתח**. תקבל טווח שווי מכמה מודלים, בדיקת דגלים אדומים בדוחות, "
             "וניתוח ביקורתי של החדשות מהשנה האחרונה — עם מקורות.")
    wl = storage.get_watchlist(user.email)
    if wl:
        st.caption("מרשימת המעקב שלך:")
        cols = st.columns(min(len(wl), 8))
        for c, w in zip(cols, wl[:8]):
            if c.button(w["ticker"], width="stretch", key=f"quick_{w['ticker']}"):
                st.session_state.update(query=w["ticker"], demo="off", ran=True)
                st.rerun()
    st.info("כלי מחקר בלבד — לא ייעוץ השקעות.")
    st.stop()

peers = tuple(p.strip().upper() for p in st.session_state.get("peers_txt", "").split(",") if p.strip())
qkey = query.upper() if demo == "off" else f"DEMO-{demo}"
try:
    with st.spinner("טוען דוחות, מחיר ומתחרות…"):
        inp = cached_inputs(query if demo == "off" else "DEMO", demo, peers, refresh_nonce(qkey))
except Exception as e:
    st.error(f"לא הצלחתי לטעון את החברה: {e}")
    st.stop()
fin, quote = inp.fin, inp.quote
import os
if demo == "off" and not os.environ.get("STOCK_ANALYZER_FAKE"):   # price has a shorter life (15 min disk cache) than statements & peers (1 h in memory)
    from stock_analyzer.data import market
    try:
        fresh = market.quote(fin.ticker)
        if fresh.get("price"):
            quote = {**quote, "price": fresh["price"], "market_cap": fresh.get("market_cap") or quote.get("market_cap")}
            inp.quote = quote
            inp.data_ages["מחיר"] = cache.humanize_age(cache.age_seconds(f"yf:quote:{fin.ticker}"))
    except Exception:
        pass

# ---------------------------------------------------------------- assumptions (sidebar)
defaults = service.compute(inp)
with st.sidebar:
    st.subheader("⚙️ הנחות")
    st.caption("ברירות המחדל מחושבות מההיסטוריה. שנה ובדוק עד כמה התוצאה זזה.")
    price = st.number_input("מחיר מניה ($)", value=float(quote.get("price") or 0.0), min_value=0.0, step=1.0, key="a_price")
    da = defaults.assumptions
    growth = st.slider("צמיחת הכנסות שנים 1–5", -0.10, 0.40, float(round(da.growth_initial, 3)), 0.005, format="%.3f", key="a_growth")
    sbc = st.checkbox("להחסיר SBC מהתזרים", value=True, key="a_sbc", help="שמרני יותר — SBC הוא עלות אמיתית (דילול).")
    d2 = service.compute(inp, subtract_sbc=sbc).assumptions
    margin = st.slider("מרווח תזרים חופשי", -0.30, 0.60, float(round(d2.fcf_margin, 3)), 0.005, format="%.3f", key=f"a_margin_{sbc}")
    wacc = st.slider("שיעור היוון (WACC)", 0.05, 0.16, float(round(da.wacc, 3)), 0.0025, format="%.4f", key="a_wacc")
    tg = st.slider("צמיחה טרמינלית", 0.0, 0.04, float(da.terminal_growth), 0.0025, format="%.4f", key="a_tg")
    if st.button("↺ איפוס הנחות", width="stretch"):
        for k in [k for k in st.session_state if str(k).startswith("a_")]:
            del st.session_state[k]
        st.rerun()

b = service.compute(inp, price=price or None, subtract_sbc=sbc, growth_initial=growth, fcf_margin=margin,
                    wacc=wacc, terminal_growth=tg)

# ---------------------------------------------------------------- history snapshot (once per fresh load)
snap_key = f"snap:{qkey}:{inp.loaded_at}"
diff_lines = st.session_state.get(f"diff:{snap_key}")
if snap_key not in st.session_state and demo == "off":
    try:
        last = storage.latest_snapshot(user.email, fin.ticker)
        recent = last is not None and storage.age_hours(last) < 1 and refresh_nonce(qkey) == 0
        if not recent:   # at most one snapshot per hour unless the user hit refresh
            storage.save_snapshot(user.email, fin.ticker, "valuation", **service.snapshot_fields(defaults))
        hist = storage.history(user.email, fin.ticker, "valuation", limit=30)
        new = hist[0]
        prev = next((h for h in hist[1:] if storage.age_hours(h) - storage.age_hours(new) >= 1), None)
        diff_lines = storage.diff_snapshots(new, prev)
    except Exception as e:  # storage problems must never break the analysis
        diff_lines = None
        st.toast(f"שמירת ההיסטוריה נכשלה: {e}")
    st.session_state[snap_key] = True
    st.session_state[f"diff:{snap_key}"] = diff_lines

# ---------------------------------------------------------------- header + toolbar
news_state_key = f"news:{qkey}"
news = st.session_state.get(news_state_key)          # (collection, analysis) or None

h1, h2 = st.columns([3, 2], vertical_alignment="center")
with h1:
    st.markdown(f"## {fin.name} <span class='small-muted'>({fin.ticker})</span>", unsafe_allow_html=True)
    st.caption(" · ".join(x for x in [fin.sic_description, quote.get("industry"),
                                       f"שנה פיסקלית אחרונה: {fin.annual.index[-1]}"] if x))
with h2:
    t1, t2, t3 = st.columns(3)
    if demo == "off":
        watched = storage.in_watchlist(user.email, fin.ticker)
        if t1.button("★ במעקב" if watched else "☆ למעקב", width="stretch", help="הוסף/הסר מרשימת המעקב"):
            (storage.remove_from_watchlist if watched else storage.add_to_watchlist)(user.email, fin.ticker)
            st.rerun()
        if t2.button("🔄 רענון", width="stretch", help="משוך מחדש דוחות, מחיר ומתחרות (עוקף את המטמון)"):
            bump_refresh(qkey)
            st.rerun()
    prev_diff = None if not diff_lines else diff_lines
    t3.download_button("⬇️ דוח", data=report.render_html(b, *(news or (None, None)), history_diff=prev_diff),
                       file_name=f"{fin.ticker}_report.html", mime="text/html", width="stretch",
                       help="דוח HTML מלא. לפתוח בדפדפן → הדפסה → שמירה כ-PDF")
st.caption("עודכן: " + " · ".join(f"{k} {v}" for k, v in inp.data_ages.items())
           + f" · מתחרות ({METHOD_HE.get(inp.peer_method, inp.peer_method)}"
           + (f" — {inp.peer_group}" if inp.peer_group else "") + "): " + (", ".join(inp.peer_tickers) or "אין"))

# ---------------------------------------------------------------- bottom line
bl = service.bottom_line(b, news[1] if news else None)
st.markdown(bottom_line_card(bl), unsafe_allow_html=True)
if diff_lines and len(diff_lines) > 1:
    with st.container(border=True):
        st.markdown("**🕓 " + diff_lines[0] + "**\n" + "\n".join(f"- {x}" for x in diff_lines[1:]))
elif diff_lines:
    st.caption("🕓 " + diff_lines[0])
if b.val.warnings:
    with st.expander(f"⚠️ הערות למודלים ({len(b.val.warnings)})"):
        for w in b.val.warnings:
            st.write("• " + w)

# ---------------------------------------------------------------- tabs
tabs = st.tabs(["📊 הערכת שווי", "🚩 דגלים אדומים", "📰 חדשות וניתוח", "🧮 DCF ורגישות", "📈 נתונים היסטוריים",
                "🕓 היסטוריית בדיקות", "⚙️ הנחות מלאות"])
with tabs[0]:
    sections.valuation_tab(b)
with tabs[1]:
    sections.flags_tab(b)
with tabs[2]:
    from stock_analyzer.news import analyst as news_analyst
    provider, model, key, key_src = llm_settings()
    st.caption("סקירת כתבות מהחודש האחרון + הכתבות הדומיננטיות בכל רבעון לאורך השנה, וניתוח ביקורתי של מודל שפה "
               "שמצליב אותן עם הדוחות, הדגלים והשווי. כל טענה מקושרת למקור.")
    can_run = demo != "off" or bool(key)
    cc1, cc2 = st.columns([1, 3], vertical_alignment="center")
    run_news = cc1.button("🔍 אסוף כתבות ונתח", type="primary", disabled=not can_run, width="stretch")
    if demo == "off":
        if key:
            src = {"session": "המפתח שהזנת", "saved": "המפתח השמור שלך", "server": "מפתח המערכת"}[key_src]
            cc2.caption(f"{PROVIDER_NAMES[provider]} · {model} · {src}")
        else:
            cc2.warning("כדי להריץ ניתוח חדשות צריך מפתח API (חינמי). עבור לדף **🔑 הגדרות ומפתח** — יש שם הסבר צעד-אחר-צעד.")
            st.page_link("ui/page_settings.py", label="🔑 להגדרת מפתח", icon=None)
    if run_news:
        try:
            if demo != "off":
                from stock_analyzer.news.demo import demo_collection, demo_analysis
                st.session_state[news_state_key] = (demo_collection(), demo_analysis())
            else:
                from stock_analyzer.news.collect import collect_news
                with st.spinner("אוסף כתבות מהשנה האחרונה…"):
                    nc = collect_news(fin.ticker, fin.name, finnhub_key=st.session_state.get("finnhub_key")
                                      or config.get_setting("FINNHUB_API_KEY"))
                ctx = news_analyst.financial_context(fin, b.val, b.fr, quote)
                with st.spinner(f"המודל קורא {len(nc.articles)} כתבות ומנתח… (1–5 דקות; בשכבה החינמית לפעמים יש תור)"):
                    na = news_analyst.analyze_news(nc, ctx, api_key=key, model=model, provider=provider)
                st.session_state[news_state_key] = (nc, na)
                try:
                    storage.save_snapshot(user.email, fin.ticker, "news", **service.snapshot_fields(b, na))
                except Exception:
                    pass
            st.rerun()
        except Exception as e:
            msg = str(e)
            if "402" in msg or "prepayment" in msg.lower() or "credit balance" in msg.lower():
                st.error("למפתח אין יתרת קרדיט. השתמש במפתח מפרויקט בשכבה החינמית (ראה דף ההגדרות), "
                         "או הוסף קרדיט ב-AI Studio → Billing.")
            elif "API_KEY_INVALID" in msg or "401" in msg or "authentication" in msg.lower():
                st.error("המפתח לא תקין. בדוק אותו בדף ההגדרות.")
            elif "busy" in msg or "503" in msg:
                st.error("כל המודלים עמוסים כרגע (שכבה חינמית). נסה שוב בעוד כמה דקות.")
            elif "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                st.error("חרגת ממכסת הבקשות של המפתח. נסה שוב מאוחר יותר.")
            else:
                st.error(f"הניתוח נכשל: {e}")
    if news:
        sections.news_results(b, *news)
with tabs[3]:
    sections.dcf_tab(b)
with tabs[4]:
    sections.history_data_tab(b)
with tabs[5]:
    if demo == "off":
        sections.checks_history_tab(user.email, fin.ticker)
    else:
        st.info("היסטוריה נשמרת רק לנתונים אמיתיים.")
with tabs[6]:
    st.json(b.assumptions.to_dict())
    st.caption("נתונים: SEC EDGAR (XBRL) · מחיר ובטא: Yahoo Finance (גיבוי: Stooq). "
               "חוב = חוב לז\"א + חלויות שוטפות + ניירות ערך מסחריים (ללא חכירות).")
