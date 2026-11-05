"""Watchlist: saved tickers with their latest check, one-click open, and bulk refresh."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from stock_analyzer import service, storage
from ui.common import bump_refresh, cached_inputs, current_user, pct, refresh_nonce

user = current_user()
st.markdown("## ⭐ רשימת מעקב")

c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
new_t = c1.text_input("הוסף מניה", placeholder="סימול, למשל MSFT", key="wl_add")
if c2.button("➕ הוסף", width="stretch") and new_t.strip():
    if storage.add_to_watchlist(user.email, new_t.strip().upper()):
        st.toast(f"{new_t.upper()} נוסף לרשימה")
    st.rerun()

wl = storage.get_watchlist(user.email)
if not wl:
    st.info("הרשימה ריקה. הוסף מניות כאן, או לחץ ☆ למעקב בדף הניתוח.")
    st.stop()

if st.button("🔄 עדכן הערכות שווי לכל הרשימה", help="מושך מחיר ודוחות לכל מניה ושומר בדיקה חדשה (בלי ניתוח חדשות)"):
    bar = st.progress(0.0)
    for i, w in enumerate(wl, 1):
        t = w["ticker"]
        bar.progress(i / len(wl), text=f"מעדכן {t}…")
        try:
            bump_refresh(t)
            inp = cached_inputs(t, "off", (), refresh_nonce(t))
            b = service.compute(inp)
            storage.save_snapshot(user.email, t, "valuation", **service.snapshot_fields(b))
        except Exception as e:
            st.warning(f"{t}: {e}")
    bar.empty()
    st.rerun()

rows = []
for w in wl:
    last = storage.latest_snapshot(user.email, w["ticker"])
    news = storage.latest_snapshot(user.email, w["ticker"], kind="news")
    p = (last or {}).get("payload", {})
    verdict = {"below": "🟢 מתחת לטווח", "within": "🟡 בתוך הטווח", "above": "🔴 מעל הטווח", "na": "—"}.get(p.get("verdict"), "—")
    concerns = ", ".join(t for _, t in ((news or {}).get("payload", {}).get("news", {}) or {}).get("top_concerns", [])[:2])
    rows.append({
        "סימול": w["ticker"], "חברה": p.get("name", ""),
        "מחיר": (last or {}).get("price"), "שווי בסיס": (last or {}).get("fv_base"),
        "מרווח ביטחון": (last or {}).get("mos"), "מצב": verdict,
        "🔴": (last or {}).get("red"), "🟡": (last or {}).get("yellow"),
        "חששות עיקריים (חדשות)": concerns or "—",
        "נבדק": last["created_at"].strftime("%d/%m/%Y %H:%M") if last else "לא נבדק",
    })
df = pd.DataFrame(rows)
st.dataframe(df.style.format({"מחיר": "${:,.2f}", "שווי בסיס": "${:,.2f}", "מרווח ביטחון": "{:+.0%}"}, na_rep="—"),
             hide_index=True, width="stretch")

st.markdown("#### פעולות")
for w in wl:
    t = w["ticker"]
    a, b_, c = st.columns([3, 1, 1], vertical_alignment="center")
    hist = storage.history(user.email, t, "valuation", limit=2)
    trend = ""
    if len(hist) == 2 and hist[0]["mos"] is not None and hist[1]["mos"] is not None:
        d = hist[0]["mos"] - hist[1]["mos"]
        trend = f" · מרווח הביטחון {'עלה' if d > 0 else 'ירד'} ב-{abs(d)*100:.0f} נק' מאז הבדיקה הקודמת" if abs(d) >= 0.01 else ""
    a.markdown(f"**{t}**{trend}")
    if b_.button("פתח ניתוח", key=f"open_{t}", width="stretch"):
        st.session_state.update(query=t, demo="off", ran=True, peers_txt="")
        st.switch_page("ui/page_analysis.py")
    if c.button("הסר", key=f"rm_{t}", width="stretch"):
        storage.remove_from_watchlist(user.email, t)
        st.rerun()
st.caption(f"{len(wl)} מניות · בדיקות נשמרות אוטומטית בכל ניתוח (פעם בשעה לכל היותר).")
