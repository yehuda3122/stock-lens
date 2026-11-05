"""Shared UI helpers: styling, formatting, current user, cached loaders, LLM settings."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import streamlit as st

from stock_analyzer import config, service, storage

MODEL_HE = {"DCF": "DCF (היוון תזרימים)", "EPV (no growth)": "EPV (ללא צמיחה)",
            "Peer multiples": "מכפילים מול מתחרים", "Residual income": "רווח שיורי (Residual Income)",
            "Graham number (reference)": "מספר גראהם (ייחוס)"}
STATUS_ICON = {"red": "🔴", "yellow": "🟡", "green": "🟢", "na": "⚪"}
SEV_ICON = {"high": "🔴 גבוה", "medium": "🟠 בינוני", "low": "🟡 נמוך"}
METHOD_HE = {"yahoo-industry": "לפי ענף (Yahoo Finance)", "sec-sic": "לפי קוד ענף SIC ב-SEC",
             "manual": "הוזנו ידנית", "demo": "נתוני דמה", "none": "לא נמצאו"}
PROVIDER_NAMES = {"gemini": "Google Gemini", "anthropic": "Anthropic Claude"}

CSS = """
<style>
:root { --ok:#1e8e3e; --ok-bg:rgba(30,142,62,.12); --bad:#d93025; --bad-bg:rgba(217,48,37,.12);
        --warn:#b06000; --warn-bg:rgba(242,153,0,.15); --line:rgba(128,128,128,.25); --muted:rgba(128,128,128,.95);
        --accent:#2f6fde; }
.main .block-container, section[data-testid="stSidebar"] {direction: rtl; text-align: right;}
.block-container {padding-top: 3.2rem; max-width: 1250px;}
[data-testid="stMarkdownContainer"] li {direction: rtl; text-align: right;}
[data-testid="stMetricValue"], [data-testid="stDataFrame"], .vega-embed, code {direction: ltr;}
[data-testid="stMarkdownContainer"] ul {direction: rtl; padding-right: 1.4rem; padding-left: 0;}
h1, h2, h3 {letter-spacing: -.01em;}
.bl-card {border:1px solid var(--line); border-radius:16px; padding:18px 20px; margin:6px 0 14px;
          background: linear-gradient(180deg, rgba(47,111,222,.06), rgba(47,111,222,0));}
.bl-head {display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:12px;}
.pill {display:inline-block; padding:5px 12px; border-radius:999px; font-weight:600; font-size:.95rem;}
.pill.below {background:var(--ok-bg); color:var(--ok);} .pill.above {background:var(--bad-bg); color:var(--bad);}
.pill.within, .pill.na {background:var(--warn-bg); color:var(--warn);}
.kpis {display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px;}
.kpi {border:1px solid var(--line); border-radius:12px; padding:9px 12px;}
.kpi .l {font-size:.8rem; color:var(--muted);} .kpi .v {font-size:1.35rem; font-weight:650; direction:ltr; text-align:right;}
.kpi .s {font-size:.78rem; color:var(--muted);}
.pos {color:var(--ok);} .neg {color:var(--bad);}
.range {position:relative; height:34px; margin:16px 6px 4px;}
.range .track {position:absolute; top:14px; left:0; right:0; height:6px; border-radius:3px; background:var(--line);}
.range .band {position:absolute; top:10px; height:14px; border-radius:7px; background:rgba(47,111,222,.35);}
.range .base {position:absolute; top:6px; width:3px; height:22px; background:var(--accent); border-radius:2px;}
.range .price {position:absolute; top:0; width:0; height:34px; border-left:2px dashed var(--bad);}
.range .lbl {position:absolute; top:-18px; transform:translateX(-50%); font-size:.75rem; white-space:nowrap; direction:ltr;}
.chips {margin-top:10px; display:flex; flex-wrap:wrap; gap:6px;}
.chip {font-size:.8rem; padding:3px 9px; border-radius:999px; border:1px solid var(--line);}
.chip.red {background:var(--bad-bg); border-color:transparent;} .chip.yellow {background:var(--warn-bg); border-color:transparent;}
.small-muted {font-size:.8rem; color:var(--muted);}
.login-box {max-width:520px; margin:8vh auto; text-align:center; border:1px solid var(--line); border-radius:18px; padding:32px;}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def money(x, d=1):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    a = abs(x)
    for div, suf in [(1e12, "T"), (1e9, "B"), (1e6, "M")]:
        if a >= div:
            return f"${x/div:,.{d}f}{suf}"
    return f"${x:,.2f}"


def pct(x, d=1, sign=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:+.{d}%}" if sign else f"{x:.{d}%}"


# ---------------------------------------------------------------- user
@dataclass
class User:
    email: str
    name: str
    is_admin: bool
    local: bool = False


def current_user() -> User:
    return st.session_state["user"]


# ---------------------------------------------------------------- LLM settings
def llm_settings() -> tuple[str, str, str | None, str]:
    """(provider, model, key or None, key_source). Key order: entered this session → saved for user →
    the owner's server key (admins / local mode only)."""
    from stock_analyzer.news.analyst import PROVIDERS, DEFAULT_PROVIDER
    provider = st.session_state.get("llm_provider", DEFAULT_PROVIDER)
    models, env = PROVIDERS[provider]
    model = st.session_state.get(f"llm_model_{provider}", models[0])
    u = current_user()
    key = st.session_state.get(f"llm_key_{provider}")
    if key:
        return provider, model, key, "session"
    if provider == "gemini" and not u.local:
        saved = storage.load_user_key(u.email)
        if saved:
            return provider, model, saved, "saved"
    if u.is_admin or u.local:
        k = config.get_setting(env)
        if k:
            return provider, model, k, "server"
    return provider, model, None, "none"


# ---------------------------------------------------------------- cached loaders
@st.cache_data(ttl=3600, show_spinner=False, max_entries=64)
def cached_inputs(query: str, demo: str, peers: tuple[str, ...], nonce: int) -> service.Inputs:
    return service.load_inputs(query, demo=demo, peers_override=list(peers) or None, refresh=nonce > 0)


def refresh_nonce(query: str) -> int:
    return st.session_state.get(f"nonce:{query.upper()}", 0)


def bump_refresh(query: str):
    st.session_state[f"nonce:{query.upper()}"] = refresh_nonce(query) + 1


def range_bar_html(low, base, high, price) -> str:
    """Horizontal range: band = low–high, blue tick = base, red dashed = price."""
    if not (low and high and price):
        return ""
    lo, hi = min(low, price) * 0.92, max(high, price) * 1.08
    pos = lambda v: 100 * (v - lo) / (hi - lo)  # noqa: E731
    return (f'<div class="range"><div class="track"></div>'
            f'<div class="band" style="left:{pos(low):.1f}%;width:{pos(high)-pos(low):.1f}%"></div>'
            f'<div class="base" style="left:{pos(base):.1f}%"></div>'
            f'<div class="price" style="left:{pos(price):.1f}%"></div>'
            f'<div class="lbl" style="left:{pos(low):.1f}%">${low:,.0f}</div>'
            f'<div class="lbl" style="left:{pos(high):.1f}%">${high:,.0f}</div>'
            f'<div class="lbl" style="left:{pos(price):.1f}%;top:36px;color:var(--bad)">מחיר ${price:,.0f}</div></div>')


def bottom_line_card(bl: dict, *, compact: bool = False) -> str:
    fv = bl["fair"]
    mos = bl["mos"]
    mos_cls = "pos" if (mos or 0) > 0 else "neg"
    ig, hg = bl["implied_growth"], bl["hist_growth"]
    gap_note = ""
    if ig is not None and hg is not None:
        gap_note = "דורש האצה" if ig > hg + 0.02 else ("נמוך מההיסטוריה" if ig < hg - 0.02 else "דומה להיסטוריה")
    c = bl["counts"]
    kpis = [
        ("שווי הוגן — בסיס", f"${fv['base']:,.2f}" if fv.get("base") else "—", ""),
        ("מרווח ביטחון", f'<span class="{mos_cls}">{pct(mos, 0, True)}</span>', "שווי בסיס מול מחיר"),
        ("צמיחה שהמחיר מגלם", pct(ig), f"היסטורית {pct(hg)} · {gap_note}" if gap_note else ""),
        ("בדיקת דוחות", f"🔴{c['red']} 🟡{c['yellow']} 🟢{c['green']}",
         f"Piotroski {bl['piotroski']}/9" if bl["piotroski"] is not None else ""),
    ]
    n = bl.get("news")
    if n:
        s = n["sentiment"]
        conf = {"high": "גבוהה", "medium": "בינונית", "low": "נמוכה"}.get(n["confidence"], "—")
        kpis.append(("סנטימנט חדשות", f"🟢{s['positive']} 🔴{s['negative']} 🟡{s['mixed']}", f"ביטחון בניתוח: {conf}"))
    k_html = "".join(f'<div class="kpi"><div class="l">{l}</div><div class="v">{v}</div><div class="s">{sub}</div></div>'
                     for l, v, sub in kpis)
    chips = "".join(f'<span class="chip red">🔴 {t}</span>' for t in bl["red_flags"])
    if not compact:
        chips += "".join(f'<span class="chip yellow">🟡 {t}</span>' for t in bl["yellow_flags"][:4])
    if n:
        chips += "".join(f'<span class="chip">{SEV_ICON.get(sv, sv)} · {t}</span>' for sv, t in n["top_concerns"])
    rng = range_bar_html(fv.get("low"), fv.get("base"), fv.get("high"), bl["price"]) if not compact else ""
    range_txt = '<span dir="ltr">${:,.0f} – ${:,.0f}</span>'.format(fv["low"], fv["high"]) if fv.get("low") else "—"
    price_txt = '<span dir="ltr">${:,.2f}</span>'.format(bl["price"]) if bl["price"] else "—"
    chips_html = '<div class="chips">' + chips + "</div>" if chips else ""
    return ('<div class="bl-card"><div class="bl-head">'
            + '<span class="pill ' + bl["verdict"] + '">' + bl["verdict_text"] + "</span>"
            + '<span class="small-muted">טווח: ' + range_txt + " · מחיר: " + price_txt + "</span></div>"
            + '<div class="kpis">' + k_html + "</div>" + rng + chips_html + "</div>")
