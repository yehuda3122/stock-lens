"""Persistence: users (optional saved API key), watchlist, analysis history (snapshots).

* Locally: SQLite file in ~/.stock_analyzer/data.db (no setup).
* In the cloud: set DATABASE_URL (e.g. a free Neon / Supabase Postgres) so data survives restarts.

API keys saved by users are encrypted with Fernet using APP_SECRET; without APP_SECRET keys are never stored.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (Column, DateTime, Float, Integer, MetaData, String, Table, Text, create_engine, delete,
                        insert, select, update)

from . import config

metadata = MetaData()

users = Table(
    "users", metadata,
    Column("email", String(320), primary_key=True),
    Column("name", String(200)),
    Column("gemini_key_enc", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("last_seen", DateTime(timezone=True)),
)
watchlist = Table(
    "watchlist", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String(320), index=True, nullable=False),
    Column("ticker", String(16), nullable=False),
    Column("note", Text, default=""),
    Column("added_at", DateTime(timezone=True)),
)
allowed = Table(
    "allowed_emails", metadata,
    Column("pattern", String(320), primary_key=True),     # "user@gmail.com" or "*@company.com"
    Column("added_by", String(320)),
    Column("added_at", DateTime(timezone=True)),
)
snapshots = Table(
    "snapshots", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String(320), index=True, nullable=False),
    Column("ticker", String(16), index=True, nullable=False),
    Column("created_at", DateTime(timezone=True), index=True),
    Column("kind", String(16)),               # "valuation" | "news"
    Column("price", Float), Column("fv_low", Float), Column("fv_base", Float), Column("fv_high", Float),
    Column("mos", Float), Column("implied_growth", Float),
    Column("red", Integer), Column("yellow", Integer), Column("green", Integer),
    Column("payload", Text),                  # JSON: flags, concerns, summary...
)


def _now():
    return datetime.now(timezone.utc)


def _default_url() -> str:
    p = Path(os.environ.get("STOCK_DATA_DIR", Path.home() / ".stock_analyzer"))
    p.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{p / 'data.db'}"


_engines: dict[str, object] = {}


def engine(url: str | None = None):
    url = url or config.get_setting("DATABASE_URL") or _default_url()
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    if url not in _engines:
        eng = create_engine(url, pool_pre_ping=True, future=True)
        metadata.create_all(eng)
        _engines[url] = eng
    return _engines[url]


def backend_name(url: str | None = None) -> str:
    return engine(url).dialect.name


# ---------------- encryption of user API keys ----------------
def _fernet():
    secret = config.get_setting("APP_SECRET")
    if not secret:
        return None
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(str(secret).encode()).digest()))


def can_store_keys() -> bool:
    return _fernet() is not None


# ---------------- users ----------------
def touch_user(email: str, name: str | None = None, *, eng=None):
    eng = eng or engine()
    with eng.begin() as c:
        row = c.execute(select(users.c.email).where(users.c.email == email)).first()
        if row:
            c.execute(update(users).where(users.c.email == email).values(last_seen=_now(), name=name or users.c.name))
        else:
            c.execute(insert(users).values(email=email, name=name, created_at=_now(), last_seen=_now()))


def save_user_key(email: str, key: str | None, *, eng=None) -> bool:
    f = _fernet()
    if f is None:
        return False
    eng = eng or engine()
    touch_user(email, eng=eng)
    enc = f.encrypt(key.encode()).decode() if key else None
    with eng.begin() as c:
        c.execute(update(users).where(users.c.email == email).values(gemini_key_enc=enc))
    return True


def load_user_key(email: str, *, eng=None) -> str | None:
    f = _fernet()
    if f is None:
        return None
    eng = eng or engine()
    with eng.begin() as c:
        row = c.execute(select(users.c.gemini_key_enc).where(users.c.email == email)).first()
    if not row or not row[0]:
        return None
    try:
        return f.decrypt(row[0].encode()).decode()
    except Exception:
        return None


def list_users(*, eng=None) -> list[dict]:
    eng = eng or engine()
    with eng.begin() as c:
        rows = c.execute(select(users.c.email, users.c.name, users.c.last_seen,
                                users.c.gemini_key_enc.isnot(None).label("has_key"))).mappings().all()
    return [dict(r) for r in rows]


# ---------------- access control ----------------
def email_matches(email: str, pattern: str) -> bool:
    email, pattern = email.lower().strip(), pattern.lower().strip()
    if pattern.startswith("*@"):
        return email.endswith(pattern[1:])
    return email == pattern


def get_allowed(*, eng=None) -> list[str]:
    eng = eng or engine()
    with eng.begin() as c:
        return [r[0] for r in c.execute(select(allowed.c.pattern).order_by(allowed.c.pattern))]


def add_allowed(pattern: str, by: str = "", *, eng=None) -> bool:
    pattern = pattern.lower().strip()
    if not pattern or "@" not in pattern:
        return False
    eng = eng or engine()
    if pattern in get_allowed(eng=eng):
        return False
    with eng.begin() as c:
        c.execute(insert(allowed).values(pattern=pattern, added_by=by, added_at=_now()))
    return True


def remove_allowed(pattern: str, *, eng=None):
    eng = eng or engine()
    with eng.begin() as c:
        c.execute(delete(allowed).where(allowed.c.pattern == pattern.lower().strip()))


def is_allowed(email: str, extra_patterns: list[str] | None = None, *, eng=None) -> bool:
    pats = list(extra_patterns or []) + get_allowed(eng=eng)
    return any(email_matches(email, p) for p in pats)


# ---------------- watchlist ----------------
def get_watchlist(email: str, *, eng=None) -> list[dict]:
    eng = eng or engine()
    with eng.begin() as c:
        rows = c.execute(select(watchlist).where(watchlist.c.email == email).order_by(watchlist.c.added_at)).mappings().all()
    return [dict(r) for r in rows]


def in_watchlist(email: str, ticker: str, *, eng=None) -> bool:
    return any(w["ticker"] == ticker.upper() for w in get_watchlist(email, eng=eng))


def add_to_watchlist(email: str, ticker: str, note: str = "", *, eng=None) -> bool:
    eng = eng or engine()
    ticker = ticker.upper().strip()
    if not ticker or in_watchlist(email, ticker, eng=eng):
        return False
    with eng.begin() as c:
        c.execute(insert(watchlist).values(email=email, ticker=ticker, note=note, added_at=_now()))
    return True


def remove_from_watchlist(email: str, ticker: str, *, eng=None):
    eng = eng or engine()
    with eng.begin() as c:
        c.execute(delete(watchlist).where((watchlist.c.email == email) & (watchlist.c.ticker == ticker.upper())))


# ---------------- history ----------------
def save_snapshot(email: str, ticker: str, kind: str, *, price=None, fair=None, mos=None, implied_growth=None,
                  counts=None, payload: dict | None = None, eng=None) -> int:
    eng = eng or engine()
    fair, counts = fair or {}, counts or {}
    with eng.begin() as c:
        res = c.execute(insert(snapshots).values(
            email=email, ticker=ticker.upper(), created_at=_now(), kind=kind, price=price,
            fv_low=fair.get("low"), fv_base=fair.get("base"), fv_high=fair.get("high"), mos=mos,
            implied_growth=implied_growth, red=counts.get("red"), yellow=counts.get("yellow"),
            green=counts.get("green"), payload=json.dumps(payload or {}, ensure_ascii=False, default=str)))
        return int(res.inserted_primary_key[0])


def history(email: str, ticker: str | None = None, kind: str | None = None, limit: int = 50, *, eng=None) -> list[dict]:
    eng = eng or engine()
    q = select(snapshots).where(snapshots.c.email == email)
    if ticker:
        q = q.where(snapshots.c.ticker == ticker.upper())
    if kind:
        q = q.where(snapshots.c.kind == kind)
    q = q.order_by(snapshots.c.created_at.desc(), snapshots.c.id.desc()).limit(limit)
    with eng.begin() as c:
        rows = c.execute(q).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d["payload"] or "{}")
        out.append(d)
    return out


def latest_snapshot(email: str, ticker: str, kind: str = "valuation", *, before_id: int | None = None, eng=None):
    for s in history(email, ticker, kind, limit=20, eng=eng):
        if before_id is None or s["id"] < before_id:
            return s
    return None


def age_hours(snap: dict) -> float:
    t = snap["created_at"]
    if t.tzinfo is None:              # SQLite returns naive datetimes (stored as UTC)
        t = t.replace(tzinfo=timezone.utc)
    return (_now() - t).total_seconds() / 3600


def diff_snapshots(new: dict, old: dict | None) -> list[str]:
    """Human-readable Hebrew list of what changed between two valuation snapshots."""
    if not old:
        return []
    out = []

    def pct(a, b):
        return (a / b - 1) if a is not None and b not in (None, 0) else None
    when = old["created_at"].strftime("%d/%m/%Y") if hasattr(old["created_at"], "strftime") else str(old["created_at"])[:10]
    p = pct(new.get("price"), old.get("price"))
    if p is not None and abs(p) >= 0.005:
        out.append(f"המחיר {'עלה' if p > 0 else 'ירד'} ב-{abs(p):.1%} (מ-${old['price']:,.2f} ל-${new['price']:,.2f})")
    f = pct(new.get("fv_base"), old.get("fv_base"))
    if f is not None and abs(f) >= 0.01:
        out.append(f"השווי ההוגן (בסיס) {'עלה' if f > 0 else 'ירד'} ב-{abs(f):.1%} (מ-${old['fv_base']:,.0f} ל-${new['fv_base']:,.0f})")
    if new.get("mos") is not None and old.get("mos") is not None and abs(new["mos"] - old["mos"]) >= 0.02:
        out.append(f"מרווח הביטחון השתנה מ-{old['mos']:+.0%} ל-{new['mos']:+.0%}")
    oflags = set((old.get("payload") or {}).get("red_flags", []))
    nflags = set((new.get("payload") or {}).get("red_flags", []))
    for t in sorted(nflags - oflags):
        out.append(f"🔴 דגל אדום חדש: {t}")
    for t in sorted(oflags - nflags):
        out.append(f"🟢 דגל אדום שנעלם: {t}")
    return [f"מאז הבדיקה ב-{when}:"] + out if out else [f"אין שינוי מהותי מאז הבדיקה ב-{when}."]
