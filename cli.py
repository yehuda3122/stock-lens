"""Quick terminal report.
Usage:  python cli.py AAPL                 (peers found automatically)
        python cli.py AAPL --peers MSFT,GOOGL,META
"""
import argparse

import pandas as pd

from stock_analyzer.pipeline import analyze

ICON = {"red": "[RED]   ", "yellow": "[YELLOW]", "green": "[OK]    ", "na": "[n/a]   "}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ticker")
    p.add_argument("--peers", default=None, help="comma separated; omit for automatic discovery")
    p.add_argument("--price", type=float, default=None)
    p.add_argument("--news", action="store_true", help="stage 3: collect news + LLM analysis (needs GEMINI_API_KEY or ANTHROPIC_API_KEY)")
    p.add_argument("--provider", default=None, choices=["gemini", "anthropic"],
                   help="LLM provider (default: gemini; key from GEMINI_API_KEY / ANTHROPIC_API_KEY)")
    p.add_argument("--model", default=None)
    args = p.parse_args()

    peers = None if args.peers is None else [x for x in args.peers.split(",") if x]
    out = analyze(args.ticker, peers=peers, price=args.price)
    fin, r, fr, pi = out["financials"], out["valuation"], out["forensic"], out["peers"]
    pd.set_option("display.float_format", "{:,.2f}".format)
    print(f"\n{fin.name} ({fin.ticker})  |  price: {r.price}")
    if pi:
        print(f"Peers ({pi.method}, {pi.group}): {', '.join(pi.tickers) or '-'}")
    print(r.model_table())
    fv = r.fair_value
    if fv["base"]:
        print(f"\nFair value  low {fv['low']:,.2f}  base {fv['base']:,.2f}  high {fv['high']:,.2f}")
    if r.margin_of_safety is not None:
        print(f"Margin of safety: {r.margin_of_safety:.1%}")
    if r.reverse.get("implied_growth") is not None:
        print(f"Reverse DCF: price implies {r.reverse['implied_growth']:.1%} revenue growth (yrs 1-5)")
    for w in r.warnings:
        print("! " + w)
    print(f"\nRed-flag checks: {fr.counts()}")
    for f in fr.flags:
        print(f"{ICON[f.status]} {f.key:14} {f.value}")

    if args.news:
        import os
        from stock_analyzer.news.collect import collect_news
        from stock_analyzer.news import analyst
        nc = collect_news(fin.ticker, fin.name, finnhub_key=os.environ.get("FINNHUB_API_KEY"))
        print(f"\nCollected {len(nc.articles)} articles; analyzing...")
        na = analyst.analyze_news(nc, analyst.financial_context(fin, r, fr, out["quote"]),
                                  model=args.model, provider=args.provider)
        d, arts = na.data, nc.by_id()
        cite = lambda srcs: " " + " ".join(f"[{s}]" for s in srcs) if srcs else ""  # noqa: E731
        print("\n== Summary ==\n" + d["summary"]["text"] + cite(d["summary"]["sources"]))
        for title, key in [("Current state", "current_state"), ("Positives", "positives"),
                           ("Numbers vs narrative", "numbers_vs_narrative"), ("Questions", "questions")]:
            print(f"\n== {title} ==")
            for c in d[key]:
                print(" - " + c["text"] + cite(c["sources"]))
        print("\n== Concerns ==")
        for c in d["concerns"]:
            print(f" - [{c['severity']}] {c['title']}: {c['text']}{cite(c['sources'])}")
        print("\n== Conclusion ==\n" + d["conclusion"]["text"])
        print("What would change the view: " + d["conclusion"]["what_would_change_view"])
        print("\n== Sources ==")
        for a in sorted(arts.values(), key=lambda a: a.published):
            print(f" [{a.id}] {a.published} {a.source}: {a.title}\n       {a.url}")


if __name__ == "__main__":
    main()
