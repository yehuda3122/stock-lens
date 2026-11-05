"""Google sign-in + access control.

* No `[auth]` section in Streamlit secrets  -> local single-user mode (no login).
* With `[auth]` (Google OIDC): users must sign in; only ADMIN_EMAILS, ALLOWED_EMAILS (secrets) and emails the
  admin added in the app (stored in the DB) get in. Patterns like "*@company.com" are supported.
"""
from __future__ import annotations

import streamlit as st

from stock_analyzer import config, storage
from ui.common import User


def auth_configured() -> bool:
    try:
        a = st.secrets.get("auth", {})
        return bool(a.get("client_id") or any(isinstance(v, dict) and v.get("client_id") for v in a.values()))
    except Exception:
        return False


def _user_logged_in() -> bool:
    try:
        return bool(st.user.is_logged_in)
    except Exception:
        return False


def require_user() -> User:
    if "user" in st.session_state and st.session_state["user"].local == (not auth_configured()):
        return st.session_state["user"]

    if not auth_configured():
        u = User(email="local@localhost", name="משתמש מקומי", is_admin=True, local=True)
        st.session_state["user"] = u
        return u

    if not _user_logged_in():
        st.markdown('<div class="login-box"><h2>📊 ניתוח מניות</h2>'
                    '<p>הערכת שווי מדוחות כספיים, בדיקת דגלים אדומים וניתוח חדשות ביקורתי.</p>'
                    '<p class="small-muted">הכניסה למשתמשים מורשים בלבד.</p></div>', unsafe_allow_html=True)
        c = st.columns([1, 1, 1])[1]
        if c.button("התחברות עם Google", type="primary", width="stretch"):
            st.login()
        st.stop()

    email = (st.user.get("email") or "").lower()
    name = st.user.get("name") or email
    admins = config.get_list_setting("ADMIN_EMAILS")
    is_admin = email in admins
    if not (is_admin or storage.is_allowed(email, config.get_list_setting("ALLOWED_EMAILS"))):
        st.markdown(f'<div class="login-box"><h3>אין לך הרשאת גישה</h3><p>התחברת כ-<b>{email}</b>.</p>'
                    '<p class="small-muted">בקש ממנהל המערכת להוסיף את כתובת המייל שלך.</p></div>', unsafe_allow_html=True)
        c = st.columns([1, 1, 1])[1]
        if c.button("התנתקות", width="stretch"):
            st.logout()
        st.stop()

    try:
        storage.touch_user(email, name)
    except Exception:
        pass
    u = User(email=email, name=name, is_admin=is_admin)
    st.session_state["user"] = u
    return u
