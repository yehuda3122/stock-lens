"""Self-contained HTML report (RTL, print-friendly — 'Save as PDF' from the browser gives a clean PDF)."""
from __future__ import annotations

import html
from datetime import datetime

from .service import Bundle, bottom_line
from .forensic import CATEGORIES

MODEL_HE = {"DCF": "DCF (היוון תזרימים)", "EPV (no growth)": "EPV (ללא צמיחה)", "Peer multiples": "מכפילים מול מתחרים",
            "Residual income": "רווח שיורי", "Graham number (reference)": "מספר גראהם (ייחוס)"}
STATUS = {"red": ("🔴", "דגל אדום"), "yellow": ("🟡", "לבדוק"), "green": ("🟢", "תקין"), "na": ("⚪", "לא רלוונטי")}
SEV = {"high": "גבוה", "medium": "בינוני", "low": "נמוך"}
SENT = {"positive": "חיובי", "negative": "שלילי", "neutral": "ניטרלי", "mixed": "מעורב"}

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1f2328;--muted:#5f6b7a;--line:#e3e7ec;--accent:#2f6fde;
--green:#1e8e3e;--green-bg:#e6f4ea;--red:#c5221f;--red-bg:#fce8e6;--amber:#b06000;--amber-bg:#fef7e0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 "Segoe UI",Arial,sans-serif;direction:rtl}
.wrap{max-width:980px;margin:0 auto;padding:28px 18px}
h1{margin:0;font-size:28px}h2{font-size:20px;margin:28px 0 10px;border-bottom:2px solid var(--line);padding-bottom:6px}
.sub{color:var(--muted);margin:4px 0 18px}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:12px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}.kpi .l{color:var(--muted);font-size:13px}
.kpi .v{font-size:22px;font-weight:600;direction:ltr;text-align:right}
.verdict{border-radius:10px;padding:12px 14px;font-weight:600}.v-below{background:var(--green-bg);color:var(--green)}
.v-above{background:var(--red-bg);color:var(--red)}.v-within,.v-na{background:var(--amber-bg);color:var(--amber)}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}
th{background:#f0f2f5;font-weight:600}.num{direction:ltr;text-align:left;white-space:nowrap}
ul{margin:6px 0;padding-right:20px}a{color:var(--accent);text-decoration:none}.cite a{font-size:12px;margin-inline-start:3px}
.sev-high{color:var(--red);font-weight:600}.sev-medium{color:var(--amber);font-weight:600}.sev-low{color:var(--muted);font-weight:600}
.muted{color:var(--muted);font-size:13px}.disc{margin-top:30px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:10px}
@media print{body{background:#fff}.card,.kpi{break-inside:avoid}.wrap{padding:0}}
"""


def _e(x) -> str:
    return html.escape(str(x)) if x is not None else ""


def _money(x, d=2):
    return "—" if x is None else f"${x:,.{d}f}"


def _pct(x, d=1, sign=False):
    return "—" if x is None else (f"{x:+.{d}%}" if sign else f"{x:.{d}%}")


def _cite(srcs, arts):
    links = [f'<a href="{_e(arts[s].url)}" target="_blank">[{_e(s)}]</a>' for s in srcs if s in arts]
    return f'<span class="cite">{"".join(links)}</span>' if links else ""


def render_html(b: Bundle, news_collection=None, news_analysis=None, *, history_diff: list[str] | None = None) -> str:
    fin, val = b.fin, b.val
    bl = bottom_line(b, news_analysis)
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    p = []
    p.append(f"<h1>{_e(fin.name)} ({_e(fin.ticker)})</h1>")
    p.append(f'<div class="sub">{_e(fin.sic_description or "")} · דוח נוצר {now} · שנה פיסקלית אחרונה {fin.annual.index[-1]}</div>')

    # ---- bottom line
    p.append("<h2>שורה תחתונה</h2>")
    p.append(f'<div class="verdict v-{bl["verdict"]}">{_e(bl["verdict_text"])}</div>')
    fv = bl["fair"]
    p.append('<div class="grid" style="margin-top:10px">')
    for label, value in [("מחיר נוכחי", _money(bl["price"])), ("שווי הוגן — בסיס", _money(fv.get("base"))),
                         ("טווח שווי", f'{_money(fv.get("low"), 0)} – {_money(fv.get("high"), 0)}' if fv.get("low") else "—"),
                         ("מרווח ביטחון", _pct(bl["mos"], 0, True)),
                         ("צמיחה שהמחיר מגלם", _pct(bl["implied_growth"])), ("צמיחה היסטורית (5ש')", _pct(bl["hist_growth"])),
                         ("דגלים", f'🔴 {bl["counts"]["red"]} · 🟡 {bl["counts"]["yellow"]} · 🟢 {bl["counts"]["green"]}'),
                         ("Piotroski", f'{bl["piotroski"]}/9' if bl["piotroski"] is not None else "—")]:
        p.append(f'<div class="kpi"><div class="l">{label}</div><div class="v">{value}</div></div>')
    p.append("</div>")
    if bl["red_flags"]:
        p.append(f'<div class="card"><b>דגלים אדומים:</b> {_e("; ".join(bl["red_flags"]))}</div>')
    if bl["news"]:
        n = bl["news"]
        tops = "".join(f'<li><span class="sev-{s}">{SEV.get(s, s)}</span> · {_e(t)}</li>' for s, t in n["top_concerns"])
        p.append(f'<div class="card"><b>מסקנת ניתוח החדשות:</b> {_e(n["conclusion"])}<ul>{tops}</ul></div>')
    if history_diff:
        p.append('<div class="card"><b>מה השתנה</b><ul>' + "".join(f"<li>{_e(x)}</li>" for x in history_diff) + "</ul></div>")

    # ---- valuation
    p.append("<h2>הערכת שווי</h2>")
    t = val.model_table()
    rows = "".join(f'<tr><td>{_e(MODEL_HE.get(m, m))}</td><td class="num">{_money(r.low)}</td><td class="num">{_money(r.base)}</td>'
                   f'<td class="num">{_money(r.high)}</td><td class="num">{r.weight:.0%}</td></tr>' for m, r in t.iterrows())
    p.append(f'<table><tr><th>מודל</th><th>פסימי</th><th>בסיס</th><th>אופטימי</th><th>משקל</th></tr>{rows}</table>')
    a = b.assumptions
    p.append(f'<p class="muted">הנחות: צמיחה שנים 1–5 {_pct(a.growth_initial)}, מרווח FCF {_pct(a.fcf_margin)}, '
             f'WACC {_pct(a.wacc)}, צמיחה טרמינלית {_pct(a.terminal_growth)}. מתחרים להשוואה: '
             f'{_e(", ".join(b.inputs.peer_tickers) or "—")}.</p>')
    if val.warnings:
        p.append("<ul>" + "".join(f'<li class="muted">{_e(w)}</li>' for w in val.warnings) + "</ul>")

    # ---- flags
    p.append("<h2>בדיקת הדוחות — דגלים</h2><table><tr><th>קטגוריה</th><th>בדיקה</th><th>מצב</th><th>ערך</th><th>פירוט</th></tr>")
    for f in b.fr.flags:
        ic, he = STATUS[f.status]
        p.append(f"<tr><td>{_e(CATEGORIES[f.category])}</td><td>{_e(f.title)}</td><td>{ic} {he}</td>"
                 f'<td class="num">{_e(f.value)}</td><td>{_e(f.detail)}</td></tr>')
    p.append("</table>")

    # ---- news
    if news_analysis is not None and news_collection is not None:
        d, arts = news_analysis.data, news_collection.by_id()
        p.append("<h2>ניתוח חדשות</h2>")
        p.append(f'<div class="card">{_e(d["summary"]["text"])}{_cite(d["summary"]["sources"], arts)}</div>')

        def lst(title, items, sev=False):
            if not items:
                return
            p.append(f"<h3>{title}</h3><ul>")
            for c in items:
                head = f'<span class="sev-{c["severity"]}">{SEV.get(c["severity"])}</span> · <b>{_e(c["title"])}</b> — ' if sev else ""
                p.append(f"<li>{head}{_e(c['text'])}{_cite(c['sources'], arts)}</li>")
            p.append("</ul>")
        lst("המצב כעת", d["current_state"])
        lst("חששות", d["concerns"], sev=True)
        if d["timeline"]:
            p.append("<h3>התפתחות לאורך השנה</h3><ul>" + "".join(
                f"<li><b>{_e(t['period'])} — {_e(t['headline'])}:</b> {_e(t['text'])}{_cite(t['sources'], arts)}</li>"
                for t in d["timeline"]) + "</ul>")
        lst("מספרים מול סיפור", d["numbers_vs_narrative"])
        lst("נקודות חיוביות", d["positives"])
        lst("נקודות לחשוב עליהן", d["questions"])
        cc = d["conclusion"]
        p.append(f'<div class="card"><b>נקודת סיכום:</b> {_e(cc["text"])}{_cite(cc["sources"], arts)}<br>'
                 f'<b>מה ישנה את התמונה:</b> {_e(cc["what_would_change_view"])}<br>'
                 f'<b>רמת ביטחון:</b> {SEV.get(cc.get("confidence"), cc.get("confidence"))} — {_e(cc.get("confidence_reason", ""))}</div>')
        sa = {s["id"]: s for s in d["source_analysis"]}
        p.append("<h3>מקורות</h3><table><tr><th>#</th><th>תאריך</th><th>מקור</th><th>כותרת</th><th>סנטימנט</th><th>ניתוח</th></tr>")
        for art in sorted(arts.values(), key=lambda x: x.published, reverse=True):
            s = sa.get(art.id, {})
            p.append(f'<tr><td>{art.id}</td><td class="num">{art.published}</td><td>{_e(art.source)}</td>'
                     f'<td><a href="{_e(art.url)}" target="_blank">{_e(art.title)}</a></td>'
                     f'<td>{SENT.get(s.get("sentiment"), "—")}</td><td>{_e(s.get("takeaway", ""))}</td></tr>')
        p.append("</table>")
        p.append(f'<p class="muted">מודל: {_e(news_analysis.model)}</p>')

    p.append('<div class="disc">כלי מחקר בלבד — לא ייעוץ השקעות. הערכות השווי תלויות בהנחות; ניתוח החדשות נעשה על ידי '
             'מודל שפה ועלול לטעות. נתונים: SEC EDGAR, Yahoo Finance, Google News.</div>')
    return (f'<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(fin.ticker)} — דוח מניה</title>'
            f"<style>{CSS}</style></head><body><div class='wrap'>{''.join(p)}</div></body></html>")
