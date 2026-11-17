"""Tiny JSON disk cache so we don't hammer SEC / Yahoo."""
import hashlib
import json
import time

from ..config import CACHE_DIR, CACHE_TTL_HOURS


def _path(key: str):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / (hashlib.sha1(key.encode()).hexdigest() + ".json")


def get(key: str, ttl_hours: float = CACHE_TTL_HOURS):
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
