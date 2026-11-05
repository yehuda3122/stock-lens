"""Small JSON disk cache with per-call TTLs, age reporting and forced refresh.

TTLs used across the app (smart cache):
  price / quote ........ 15 min
  news ................. 6 h
  SEC company facts .... until the company files a new 10-K/10-Q (checked every 6 h)
  LLM analysis ......... 24 h
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import threading
import time

from ..config import CACHE_DIR, CACHE_TTL_HOURS

_local = threading.local()


def _bypass() -> set[str]:
    if not hasattr(_local, "bypass"):
        _local.bypass = set()
    return _local.bypass


@contextlib.contextmanager
def refresh(*key_substrings: str):
    """Inside this block, cache entries whose key contains any of the substrings are ignored (and rewritten).
    `refresh("")` bypasses everything."""
    b = _bypass()
    added = [s for s in key_substrings if s not in b]
    b.update(added)
    try:
        yield
    finally:
        for s in added:
            b.discard(s)


def _path(key: str):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / (hashlib.sha1(key.encode()).hexdigest() + ".json")


def _bypassed(key: str) -> bool:
    return any(s in key for s in _bypass())


def age_seconds(key: str) -> float | None:
    p = _path(key)
    return (time.time() - p.stat().st_mtime) if p.exists() else None


def written_at(key: str) -> float | None:
    p = _path(key)
    return p.stat().st_mtime if p.exists() else None


def get(key: str, ttl_hours: float = CACHE_TTL_HOURS):
    if _bypassed(key):
        return None
    p = _path(key)
    if p.exists() and (time.time() - p.stat().st_mtime) < ttl_hours * 3600:
        try:
            return json.loads(p.read_text())
        except Exception:
            return None
    return None


def put(key: str, value):
    try:
        _path(key).write_text(json.dumps(value))
    except Exception:
        pass
    return value


def humanize_age(seconds: float | None) -> str:
    """Hebrew 'X ago' string."""
    if seconds is None:
        return "עכשיו"
    m = int(seconds // 60)
    if m < 1:
        return "לפני פחות מדקה"
    if m < 60:
        return f"לפני {m} דק'"
    h = m // 60
    if h < 24:
        return f"לפני {h} שע'"
    return f"לפני {h // 24} ימים"
