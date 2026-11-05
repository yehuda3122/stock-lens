from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from stock_analyzer.news import analyst
from stock_analyzer.news.collect import collect_news, rank, make_windows, SPAM
from stock_analyzer.news.sources import Article, parse_google_rss, clean_company_name
from stock_analyzer.news.demo import demo_collection, demo_analysis

SAMPLE = (Path(__file__).parent / "data" / "google_news_sample.xml").read_text()


def test_parse_real_google_rss_sample():
    arts = parse_google_rss(SAMPLE)
    assert len(arts) > 50
    a = arts[0]
    assert a.title and a.source and a.url.startswith("https://news.google.com/") and len(a.published) == 10
    assert not a.title.endswith(f" - {a.source}")


def test_clean_company_name():
    assert clean_company_name("APPLE INC.") == "Apple"
    assert clean_company_name("Alphabet Inc.") == "Alphabet"
    assert clean_company_name("Meta Platforms, Inc.") == "Meta Platforms"
    assert clean_company_name("Microsoft Corp") == "Microsoft"


def test_spam_filter():
    for t in ["Vanguard Group Inc. Acquires New Position in Apple Inc.", "XYZ Advisors LLC Sells 1,200 Shares of Apple",
              "Apple Inc. (AAPL) stock price, news, quote and history"]:
        assert SPAM.search(t), t
    assert not SPAM.search("Apple forecasts margin drop as memory costs bite")


def test_rank_real_sample_prefers_major_outlets_and_dedupes():
    top = rank(parse_google_rss(SAMPLE), "Apple", "AAPL", 10)
    assert len(top) == 10
    assert sum(1 for a in top if a.source in ("Reuters", "Financial Times", "Bloomberg.com", "AP News", "CNBC",
                                              "The New York Times", "Axios", "WSJ", "Barron's")) >= 5
    titles = [a.title for a in top]
    assert len(set(titles)) == len(titles)
    assert top == sorted(top, key=lambda a: -a.score)


def test_windows_cover_a_year():
    w = make_windows(date(2026, 11, 5))
    assert len(w) == 5 and w[0].kind == "recent"
    assert (w[0].end - w[-1].start).days >= 360
    for a, b in zip(w, w[1:]):
        assert b.end == a.start


def test_collect_assigns_ids_and_excerpts():
    calls = []

    def fake_google(q, s, e):
        calls.append((q, s, e))
        return [Article(f"Acme wins contract {s}", "Reuters", f"https://x/{s}", s.isoformat(), source_domain="reuters.com"),
                Article(f"Acme Corp shares sold by Some Fund {s}", "MarketBeat", "u", s.isoformat())]
    nc = collect_news("ACME", "ACME CORP", today=date(2026, 11, 5), google=fake_google,
                      excerpt=lambda u: "body text", finnhub=None)
    assert len(nc.articles) == 5                       # 1 per window, spam dropped
    assert [a.id for a in sorted(nc.articles, key=lambda a: a.published)] == ["S1", "S2", "S3", "S4", "S5"]
    assert all(a.text == "body text" for a in nc.articles)
    assert '"Acme"' in calls[0][0]


def test_collect_survives_provider_failure():
    def boom(*a):
        raise RuntimeError("rate limited")
    nc = collect_news("ACME", "Acme", today=date(2026, 11, 5), google=boom, excerpt=lambda u: "")
    assert nc.articles == [] and all(w.error for w in nc.windows)
    with pytest.raises(ValueError):
        analyst.analyze_news(nc, "ctx", client=object(), use_cache=False)


class FakeClient:
    def __init__(self, payload):
        self.payload, self.kwargs = payload, None
        self.messages = self

    def create(self, **kw):
        self.kwargs = kw
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=self.payload)],
                               stop_reason="tool_use", usage=SimpleNamespace(input_tokens=1000, output_tokens=500))


def test_analyst_validates_citations_and_builds_prompt():
    nc = demo_collection()
    payload = {
        "summary": {"text": "x", "sources": ["S1", "S99"]},
        "current_state": [{"text": "ok", "sources": ["[S8]"]}, {"text": "fabricated", "sources": ["S77"]}],
        "timeline": [], "positives": [{"text": "no source", "sources": []}],
        "concerns": [{"title": "b", "text": "", "severity": "low", "sources": ["S2"]},
                     {"title": "a", "text": "", "severity": "high", "sources": ["S5"]}],
        "numbers_vs_narrative": [{"text": "context only", "sources": []}],
        "questions": [], "conclusion": {"text": "c", "what_would_change_view": "w", "confidence": "low",
                                        "confidence_reason": "r", "sources": []},
        "source_analysis": [{"id": "S1", "takeaway": "t", "sentiment": "neutral", "importance": "low",
                             "reliability_note": "n"}, {"id": "S50", "takeaway": "t", "sentiment": "neutral",
                                                         "importance": "low", "reliability_note": "n"}],
    }
    fc = FakeClient(payload)
    res = analyst.analyze_news(nc, "CONTEXT-BLOCK", client=fc, provider="anthropic", model="m", use_cache=False)
    d = res.data
    assert d["summary"]["sources"] == ["S1"]
    assert [c["text"] for c in d["current_state"]] == ["ok"]          # fabricated id removed
    assert d["positives"] == []                                       # un-sourced claim removed
    assert [c["title"] for c in d["concerns"]] == ["a", "b"]          # sorted by severity
    assert len(d["numbers_vs_narrative"]) == 1                        # context-only allowed
    assert [s["id"] for s in d["source_analysis"]] == ["S1"]
    assert res.removed_claims == 2 and res.usage["output_tokens"] == 500
    # prompt checks
    assert fc.kwargs["tool_choice"] == {"type": "tool", "name": "submit_analysis"}
    msg = fc.kwargs["messages"][0]["content"]
    assert "CONTEXT-BLOCK" in msg and "[S8]" in msg and "untrusted" in fc.kwargs["system"]


def test_financial_context_includes_flags_and_reverse_dcf():
    from stock_analyzer.demo import make_facts
    from stock_analyzer.financials import build_financials
    from stock_analyzer import valuation, forensic
    fin = build_financials(make_facts(manipulate=True), "DEMO", info={"sic": 3571})
    a = valuation.derive(fin, {"beta": 1.1, "price": 150})
    val = valuation.run(fin, a, 150, [])
    ctx = analyst.financial_context(fin, val, forensic.analyze(fin, 1e12))
    assert "Reverse DCF" in ctx and "ni_vs_cfo: red" in ctx and "FY2025" in ctx


def test_demo_analysis_is_fully_sourced():
    res = demo_analysis()
    assert res.removed_claims == 0
    assert len(res.data["concerns"]) >= 3 and res.data["concerns"][0]["severity"] == "high"


class FakeGemini:
    def __init__(self, text, finish="STOP"):
        self.text, self.finish, self.kwargs = text, finish, None
        self.models = self

    def generate_content(self, **kw):
        self.kwargs = kw
        return SimpleNamespace(text=self.text, candidates=[SimpleNamespace(finish_reason=self.finish)],
                               usage_metadata=SimpleNamespace(prompt_token_count=3000, candidates_token_count=1500),
                               prompt_feedback=None)


def test_gemini_provider_structured_output():
    import json
    nc = demo_collection()
    payload = demo_analysis().data | {"positives": [{"text": "fake", "sources": ["S404"]}]}
    fg = FakeGemini(json.dumps(payload, ensure_ascii=False), finish="MAX_TOKENS")
    res = analyst.analyze_news(nc, "CTX", client=fg, provider="gemini", model="gemini-3.8-flash", use_cache=False)
    cfg = fg.kwargs["config"]
    assert fg.kwargs["model"] == "gemini-3.8-flash"
    assert cfg.response_mime_type == "application/json" and cfg.response_json_schema == analyst.SCHEMA
    assert "untrusted" in cfg.system_instruction and "CTX" in fg.kwargs["contents"]
    assert res.removed_claims == 1 and res.data["positives"] == []
    assert res.usage == {"input_tokens": 3000, "output_tokens": 1500}
    assert res.warnings and res.model == "gemini: gemini-3.8-flash"


def test_gemini_bad_json_raises(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="complete analysis"):
        analyst.analyze_news(demo_collection(), "CTX", client=FakeGemini("not json"), provider="gemini",
                             model="x", use_cache=False)


def test_default_provider_is_gemini():
    assert analyst.DEFAULT_PROVIDER == "gemini" and analyst.DEFAULT_MODEL.startswith("gemini")


def test_keys_file_loader(tmp_path, monkeypatch):
    from stock_analyzer import config
    f = tmp_path / "keys.env"
    f.write_text("# comment\nTEST_KEY_A=abc\nTEST_KEY_B = 'quoted'\nEMPTY=\nTEST_KEY_C=fromfile\n")
    monkeypatch.delenv("TEST_KEY_A", raising=False)
    monkeypatch.delenv("TEST_KEY_B", raising=False)
    monkeypatch.setenv("TEST_KEY_C", "fromenv")
    loaded = config.load_keys_file(f)
    import os
    assert os.environ["TEST_KEY_A"] == "abc" and os.environ["TEST_KEY_B"] == "quoted"
    assert os.environ["TEST_KEY_C"] == "fromenv"          # real env var wins
    assert set(loaded) == {"TEST_KEY_A", "TEST_KEY_B"}
    monkeypatch.delenv("TEST_KEY_A"); monkeypatch.delenv("TEST_KEY_B")


class FlakyGemini(FakeGemini):
    """First model always 503, second works."""
    def __init__(self, text):
        super().__init__(text)
        self.calls = []

    def generate_content(self, **kw):
        self.calls.append(kw["model"])
        if kw["model"] == "gemini-3.8-flash":
            raise RuntimeError("503 UNAVAILABLE. high demand")
        return super().generate_content(**kw)


def test_gemini_retries_then_falls_back(monkeypatch):
    import json
    monkeypatch.setattr("time.sleep", lambda s: None)
    fg = FlakyGemini(json.dumps(demo_analysis().data, ensure_ascii=False))
    res = analyst.analyze_news(demo_collection(), "CTX", client=fg, provider="gemini", model="gemini-3.8-flash",
                               use_cache=False)
    assert fg.calls == ["gemini-3.8-flash"] * 4 + ["gemini-3.6-flash"]   # 1 try + 3 retries, then fallback
    assert res.model == "gemini: gemini-3.6-flash" and any("עמוס" in w for w in res.warnings)


def test_gemini_billing_error_not_retried(monkeypatch):
    class Billing(FakeGemini):
        n = 0
        def generate_content(self, **kw):
            Billing.n += 1
            raise RuntimeError("402 RESOURCE_EXHAUSTED prepayment credits are depleted")
    with pytest.raises(RuntimeError, match="402"):
        analyst.analyze_news(demo_collection(), "CTX", client=Billing(""), provider="gemini", use_cache=False)
    assert Billing.n == 1



def test_gemini_truncated_json_retries_compact(monkeypatch):
    import json
    good = json.dumps(demo_analysis().data, ensure_ascii=False)

    class Trunc(FakeGemini):
        def __init__(self):
            super().__init__(good)
            self.contents = []
        def generate_content(self, **kw):
            self.contents.append(kw["contents"])
            r = super().generate_content(**kw)
            if len(self.contents) == 1:          # first answer cut off mid-string
                r.text = good[:500]
                r.candidates[0].finish_reason = "MAX_TOKENS"
            return r
    fg = Trunc()
    res = analyst.analyze_news(demo_collection(), "CTX", client=fg, provider="gemini", model="gemini-3.8-flash",
                               use_cache=False)
    assert len(fg.contents) == 2 and "too long" in fg.contents[1] and "too long" not in fg.contents[0]
    assert res.data["concerns"] and res.model == "gemini: gemini-3.8-flash"
    cfg = fg.kwargs["config"]
    assert cfg.max_output_tokens >= 32768 and cfg.thinking_config is not None
