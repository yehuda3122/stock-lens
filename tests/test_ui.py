"""Smoke tests for every page (offline: synthetic data via STOCK_ANALYZER_FAKE)."""
import os

import pytest
from streamlit.testing.v1 import AppTest

ROOT = os.path.dirname(os.path.dirname(__file__))


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCK_ANALYZER_FAKE", "1")
    monkeypatch.setenv("STOCK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_CACHE_DIR", str(tmp_path / "cache"))
    from stock_analyzer import config, storage
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    storage._engines.clear()
    monkeypatch.chdir(ROOT)


def app():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=120)
    at.run()
    return at


def ok(at):
    assert not at.exception, [e.value for e in at.exception]


def test_landing():
    at = app()
    ok(at)
    assert any(b.label == "🔎 נתח" for b in at.button)


def test_analysis_flow_watchlist_and_news_demo():
    at = app()
    at.text_input[0].set_value("AAPL")
    next(b for b in at.button if b.label == "🔎 נתח").click()
    at.run()
    ok(at)
    assert any("bl-card" in m.value for m in at.markdown)
    next(b for b in at.button if b.label == "☆ למעקב").click()
    at.run()
    ok(at)
    assert any(b.label == "★ במעקב" for b in at.button)
    # settings slider change keeps working
    at.slider(key="a_wacc").set_value(0.11).run()
    ok(at)


def test_demo_news_section():
    at = app()
    at.session_state["query"] = "DEMO"
    at.session_state["demo"] = "flags"
    at.session_state["ran"] = True
    at.run()
    next(b for b in at.button if b.label == "🔍 אסוף כתבות ונתח").click()
    at.run()
    ok(at)
    assert any("נקודת סיכום" in m.value for m in at.markdown)


def test_watchlist_compare_settings_about_pages():
    from stock_analyzer import storage
    storage.add_to_watchlist("local@localhost", "MSFT")
    storage.add_to_watchlist("local@localhost", "NVDA")
    at = app()
    at.switch_page("ui/page_watchlist.py").run()
    ok(at)
    assert any(b.label == "פתח ניתוח" for b in at.button)
    next(b for b in at.button if "עדכן הערכות" in b.label).click()
    at.run()
    ok(at)
    assert len(storage.history("local@localhost", "MSFT")) >= 1

    at.switch_page("ui/page_compare.py").run()
    ok(at)
    at.text_input[0].set_value("MSFT, NVDA")
    next(b for b in at.button if b.label == "השווה").click()
    at.run()
    ok(at)
    assert at.dataframe

    at.switch_page("ui/page_settings.py").run()
    ok(at)
    assert any("ניהול" in m.value for m in at.markdown)
    at.text_input(key="allow_add").set_value("friend@gmail.com")
    next(b for b in at.button if b.label == "הוסף").click()
    at.run()
    ok(at)
    assert "friend@gmail.com" in storage.get_allowed()

    at.switch_page("ui/page_about.py").run()
    ok(at)


def test_login_gate_when_auth_configured():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=60)
    at.secrets["auth"] = {"client_id": "x.apps.googleusercontent.com", "client_secret": "s",
                          "redirect_uri": "http://localhost:8501/oauth2callback", "cookie_secret": "c",
                          "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration"}
    at.run()
    ok(at)
    assert any(b.label == "התחברות עם Google" for b in at.button)
    assert not any(b.label == "🔎 נתח" for b in at.button)      # nothing else is reachable before login
