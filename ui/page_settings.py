"""Settings: LLM provider & API key (with a step-by-step guide), and admin tools."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from stock_analyzer import config, storage
from stock_analyzer.news.analyst import PROVIDERS
from ui.common import PROVIDER_NAMES, current_user, llm_settings

user = current_user()
st.markdown("## 🔑 הגדרות ומפתח API")
st.write("ניתוח החדשות משתמש במודל שפה. כל משתמש משתמש במפתח משלו — **מפתח Gemini הוא חינמי** ולוקח דקה להוציא.")


def test_key(provider: str, model: str, key: str) -> tuple[bool, str]:
    try:
        if provider == "gemini":
            from google import genai
            r = genai.Client(api_key=key, http_options={"timeout": 30_000}).models.generate_content(
                model="gemini-3.5-flash-lite", contents="Reply with OK")
            return True, (r.text or "").strip()[:20]
        import anthropic
        r = anthropic.Anthropic(api_key=key).messages.create(model="claude-haiku-5-5", max_tokens=5,
                                                              messages=[{"role": "user", "content": "Reply OK"}])
        return True, r.content[0].text
    except Exception as e:
        m = str(e)
        if "API_KEY_INVALID" in m or "401" in m:
            return False, "המפתח לא תקין."
        if "402" in m or "prepayment" in m.lower():
            return False, "המפתח תקין אבל הפרויקט שלו דורש תשלום מראש ואין בו יתרה. צור מפתח בפרויקט ללא חיוב (שכבה חינמית)."
        if "503" in m or "UNAVAILABLE" in m:
            return True, "המפתח תקין (המודל עמוס כרגע, זה זמני)."
        return False, m[:200]


tab_key, tab_guide = st.tabs(["מפתח ומודל", "📘 איך משיגים מפתח Gemini חינמי"])

with tab_guide:
    st.markdown("""
1. היכנס ל-**[Google AI Studio → API Keys](https://aistudio.google.com/apikey)** עם חשבון Google שלך.
2. אם זו הפעם הראשונה — אשר את תנאי השימוש.
3. לחץ על **Create API key** (למעלה משמאל).
   - אם מתבקש לבחור פרויקט: בחר **Default Gemini Project** או צור פרויקט חדש.
   - **אל תפעיל חיוב (Billing)** בפרויקט — כך המפתח נשאר בשכבה החינמית ולא נדרש כרטיס אשראי.
4. בחלון שנפתח לחץ על **Copy** כדי להעתיק את המפתח (מחרוזת ארוכה שמתחילה ב-`AIza` או `AQ.`).
5. חזור לכאן, הדבק את המפתח בלשונית **מפתח ומודל**, ולחץ **בדוק ושמור**.

**טוב לדעת:**
- בשכבה החינמית יש מכסה יומית מוגבלת — מספיקה לכמה ניתוחים ביום.
- בשעות עומס המודל לפעמים "עמוס"; המערכת מנסה שוב ועוברת אוטומטית למודל קל יותר.
- בשכבה החינמית Google רשאית להשתמש בתוכן הבקשות לשיפור המוצרים שלה (כאן מדובר בכתבות ציבוריות).
- אל תשתף את המפתח עם אחרים. אפשר למחוק אותו בכל רגע באותו דף ב-AI Studio.
""")

with tab_key:
    provider = st.radio("ספק", list(PROVIDERS), format_func=PROVIDER_NAMES.get, horizontal=True,
                        index=list(PROVIDERS).index(st.session_state.get("llm_provider", "gemini")))
    st.session_state["llm_provider"] = provider
    models = PROVIDERS[provider][0]
    cur = st.session_state.get(f"llm_model_{provider}", models[0])
    st.session_state[f"llm_model_{provider}"] = st.selectbox(
        "מודל", models, index=models.index(cur) if cur in models else 0,
        help=("3.8 Flash = מומלץ · 3.6 Flash = גיבוי יציב · 4 Argon = הכי מעמיק (לא בשכבה החינמית) · Flash-Lite = הכי מהיר"
              if provider == "gemini" else "Sonnet = איזון · Opus = הכי מעמיק · Haiku = זול"))

    _, _, active_key, src = llm_settings()
    src_he = {"session": "מפתח שהוזן בסשן הזה", "saved": "המפתח השמור שלך", "server": "מפתח המערכת (מנהל)",
              "none": "אין מפתח"}[src]
    st.markdown(f"**מצב נוכחי:** {'✅' if active_key else '❌'} {src_he}"
                + (f" (…{active_key[-4:]})" if active_key else ""))

    link = "https://aistudio.google.com/apikey" if provider == "gemini" else "https://platform.claude.com/settings/keys"
    new_key = st.text_input(f"מפתח {PROVIDER_NAMES[provider]}", type="password", placeholder="הדבק כאן את המפתח",
                            help=f"להוצאת מפתח: {link}")
    remember = False
    if provider == "gemini" and not user.local:
        if storage.can_store_keys():
            remember = st.checkbox("זכור את המפתח בחשבון שלי (נשמר מוצפן)", value=True)
        else:
            st.caption("המפתח נשמר רק לסשן הנוכחי (המערכת לא מוגדרת לשמירת מפתחות).")
    c1, c2 = st.columns([1, 1])
    if c1.button("בדוק ושמור", type="primary", disabled=not new_key, width="stretch"):
        with st.spinner("בודק את המפתח…"):
            ok, msg = test_key(provider, st.session_state[f"llm_model_{provider}"], new_key.strip())
        if ok:
            st.session_state[f"llm_key_{provider}"] = new_key.strip()
            if remember:
                storage.save_user_key(user.email, new_key.strip())
            st.success("המפתח עובד ונשמר ✔" + (" (מוצפן בחשבון שלך)" if remember else " (לסשן הנוכחי)"))
        else:
            st.error(msg)
    if c2.button("מחק את המפתח שלי", width="stretch"):
        st.session_state.pop(f"llm_key_{provider}", None)
        if provider == "gemini" and not user.local:
            storage.save_user_key(user.email, None)
        st.rerun()

    st.divider()
    fh = st.text_input("Finnhub API key (אופציונלי)", type="password", value=st.session_state.get("finnhub_key", ""),
                       help="מוסיף כתבות עם תקצירים לשנה האחרונה. מפתח חינמי ב-finnhub.io")
    st.session_state["finnhub_key"] = fh

# ---------------------------------------------------------------- admin
if user.is_admin:
    st.divider()
    st.markdown("## 🛡️ ניהול (מנהל בלבד)")
    if user.local:
        st.info("מצב מקומי — אין התחברות. ניהול משתמשים פעיל רק כשהמערכת רצה בענן עם התחברות Google.")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("#### מי מורשה להיכנס")
        st.caption("כתובת מייל מלאה, או `*@domain.com` לכל הדומיין. מנהלים (ADMIN_EMAILS) תמיד מורשים.")
        a1, a2 = st.columns([3, 1], vertical_alignment="bottom")
        new_email = a1.text_input("הוסף מייל", key="allow_add", placeholder="friend@gmail.com")
        if a2.button("הוסף", width="stretch") and new_email:
            if storage.add_allowed(new_email, user.email):
                st.toast(f"{new_email} נוסף")
            st.rerun()
        fixed = config.get_list_setting("ALLOWED_EMAILS")
        for p in fixed:
            st.markdown(f"- `{p}` <span class='small-muted'>(מוגדר ב-secrets)</span>", unsafe_allow_html=True)
        for p in storage.get_allowed():
            r1, r2 = st.columns([4, 1], vertical_alignment="center")
            r1.markdown(f"- `{p}`")
            if r2.button("הסר", key=f"rmallow_{p}"):
                storage.remove_allowed(p)
                st.rerun()
    with c2:
        st.markdown("#### משתמשים שנכנסו")
        us = storage.list_users()
        if us:
            st.dataframe(pd.DataFrame([{"מייל": u["email"], "שם": u["name"], "כניסה אחרונה": u["last_seen"],
                                        "מפתח שמור": "✓" if u["has_key"] else ""} for u in us]),
                         hide_index=True, width="stretch")
        else:
            st.caption("עדיין אין.")
        st.markdown("#### מצב המערכת")
        from ui.auth import auth_configured
        st.markdown(
            f"- התחברות Google: {'✅ פעילה' if auth_configured() else '— כבויה (מצב מקומי)'}\n"
            f"- מסד נתונים: `{storage.backend_name()}`" + (" ⚠️ בענן SQLite נמחק באתחול — הגדר DATABASE_URL" if
                                                          storage.backend_name() == "sqlite" and not user.local else "") + "\n"
            f"- שמירת מפתחות מוצפנת: {'✅' if storage.can_store_keys() else '❌ (חסר APP_SECRET)'}\n"
            f"- מפתח Gemini של המערכת: {'✅' if config.get_setting('GEMINI_API_KEY') else '❌'}")
