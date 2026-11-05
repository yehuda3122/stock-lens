"""Stock Analyzer — Streamlit entry point.  Run:  streamlit run app.py"""
import streamlit as st

st.set_page_config(page_title="ניתוח מניות", page_icon="📊", layout="wide", initial_sidebar_state="expanded")

from ui import auth, common  # noqa: E402  (after set_page_config)

common.inject_css()
user = auth.require_user()

pages = [
    st.Page("ui/page_analysis.py", title="ניתוח מניה", icon="🔎", default=True),
    st.Page("ui/page_watchlist.py", title="רשימת מעקב", icon="⭐"),
    st.Page("ui/page_compare.py", title="השוואת מניות", icon="⚖️"),
    st.Page("ui/page_settings.py", title="הגדרות ומפתח", icon="🔑"),
    st.Page("ui/page_about.py", title="אודות", icon="ℹ️"),
]
nav = st.navigation(pages)

with st.sidebar:
    if not user.local:
        st.markdown(f"**{user.name}**  \n<span class='small-muted'>{user.email}{' · מנהל' if user.is_admin else ''}</span>",
                    unsafe_allow_html=True)
        if st.button("התנתקות", width="stretch"):
            st.logout()
    st.divider()

nav.run()

st.divider()
st.caption("⚠️ כלי מחקר בלבד, לא ייעוץ השקעות.")
