import time

import pytest

from stock_analyzer import storage, config
from stock_analyzer.data import cache


@pytest.fixture
def eng(tmp_path):
    return storage.engine(f"sqlite:///{tmp_path/'t.db'}")


def test_watchlist_crud(eng):
    assert storage.add_to_watchlist("a@x.com", "aapl", eng=eng)
    assert not storage.add_to_watchlist("a@x.com", "AAPL", eng=eng)       # no duplicates
    storage.add_to_watchlist("a@x.com", "MSFT", eng=eng)
    storage.add_to_watchlist("b@x.com", "NVDA", eng=eng)
    assert [w["ticker"] for w in storage.get_watchlist("a@x.com", eng=eng)] == ["AAPL", "MSFT"]
    storage.remove_from_watchlist("a@x.com", "aapl", eng=eng)
    assert [w["ticker"] for w in storage.get_watchlist("a@x.com", eng=eng)] == ["MSFT"]
    assert [w["ticker"] for w in storage.get_watchlist("b@x.com", eng=eng)] == ["NVDA"]   # isolated per user


def test_snapshots_and_diff(eng):
    s1 = storage.save_snapshot("a@x.com", "AAPL", "valuation", price=100, fair={"low": 80, "base": 110, "high": 140},
                               mos=0.10, counts={"red": 0}, payload={"red_flags": ["A"]}, eng=eng)
    time.sleep(0.01)
    s2 = storage.save_snapshot("a@x.com", "AAPL", "valuation", price=120, fair={"low": 80, "base": 100, "high": 130},
                               mos=-0.17, counts={"red": 1}, payload={"red_flags": ["B"]}, eng=eng)
    h = storage.history("a@x.com", "AAPL", eng=eng)
    assert [x["id"] for x in h] == [s2, s1] and h[0]["payload"]["red_flags"] == ["B"]
    prev = storage.latest_snapshot("a@x.com", "AAPL", before_id=s2, eng=eng)
    d = storage.diff_snapshots(h[0], prev)
    text = " ".join(d)
    assert "עלה ב-20.0%" in text and "ירד ב-9.1%" in text and "דגל אדום חדש: B" in text and "שנעלם: A" in text
    assert storage.history("other@x.com", eng=eng) == []


def test_allowlist(eng):
    assert storage.add_allowed("Friend@Gmail.com", "admin", eng=eng)
    storage.add_allowed("*@company.com", eng=eng)
    assert storage.is_allowed("friend@gmail.com", eng=eng)
    assert storage.is_allowed("bob@company.com", eng=eng)
    assert not storage.is_allowed("bob@evil.com", eng=eng)
    assert not storage.is_allowed("x@notcompany.com.evil", eng=eng)
    assert storage.is_allowed("boss@x.com", ["boss@x.com"], eng=eng)
    storage.remove_allowed("friend@gmail.com", eng=eng)
    assert not storage.is_allowed("friend@gmail.com", eng=eng)


def test_encrypted_user_key(eng, monkeypatch):
    monkeypatch.delenv("APP_SECRET", raising=False)
    assert not storage.can_store_keys() and not storage.save_user_key("a@x.com", "k", eng=eng)
    monkeypatch.setenv("APP_SECRET", "s3cret")
    assert storage.save_user_key("a@x.com", "MY-KEY", eng=eng)
    assert storage.load_user_key("a@x.com", eng=eng) == "MY-KEY"
    with eng.begin() as c:
        raw = c.execute(storage.select(storage.users.c.gemini_key_enc)).scalar()
    assert "MY-KEY" not in raw                              # stored encrypted
    monkeypatch.setenv("APP_SECRET", "other")
    assert storage.load_user_key("a@x.com", eng=eng) is None   # wrong secret -> unreadable
    monkeypatch.setenv("APP_SECRET", "s3cret")
    storage.save_user_key("a@x.com", None, eng=eng)
    assert storage.load_user_key("a@x.com", eng=eng) is None


def test_cache_refresh_and_age(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache.put("yf:quote:AAPL", {"p": 1})
    assert cache.get("yf:quote:AAPL", 1) == {"p": 1}
    assert cache.age_seconds("yf:quote:AAPL") < 5
    with cache.refresh("yf:quote:AAPL"):
        assert cache.get("yf:quote:AAPL", 1) is None
    assert cache.get("yf:quote:AAPL", 1) == {"p": 1}
    assert cache.humanize_age(30) == "לפני פחות מדקה" and cache.humanize_age(7200) == "לפני 2 שע'"


def test_sec_facts_refetch_on_new_filing(tmp_path, monkeypatch):
    from stock_analyzer.data import sec
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache.put("sec:facts:1", {"old": True})
    calls = []

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"new": True}
    monkeypatch.setattr(sec.requests, "get", lambda *a, **k: calls.append(a) or R())
    monkeypatch.setattr(sec, "submissions", lambda cik: {"filings": {"recent": {"form": ["8-K", "10-Q"],
                                                                                "filingDate": ["2001-01-01", "2000-01-01"]}}})
    assert sec.company_facts(1) == {"old": True} and not calls            # no newer 10-Q -> cached
    monkeypatch.setattr(sec, "submissions", lambda cik: {"filings": {"recent": {"form": ["10-Q"],
                                                                                "filingDate": ["2999-01-01"]}}})
    assert sec.company_facts(1) == {"new": True} and len(calls) == 1      # newer filing -> refetch


def test_get_setting_env_and_list(monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAILS", "A@x.com, *@y.com ,")
    assert config.get_list_setting("ALLOWED_EMAILS") == ["a@x.com", "*@y.com"]
    assert config.get_setting("NOPE_NOT_SET", "d") == "d"
