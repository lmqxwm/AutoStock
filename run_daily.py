#!/usr/bin/env python3
"""
run_daily.py
------------
Command-line runner — executes the same logic as daily_run.ipynb.

Usage
-----
    python run_daily.py                      # normal run
    python run_daily.py --no-news            # skip news discovery
    python run_daily.py --force-download     # re-download all history
    python run_daily.py --inspect NVDA AAPL  # also print indicator table for these tickers

Alarm output is written to ./alarms/YYYY-MM-DD_HH-MM.txt
"""

import argparse
import logging
import os
import sys
import warnings
from datetime import datetime, timezone
from importlib import reload
from pathlib import Path

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

ALARMS_DIR = PROJECT_DIR / "alarms"
ALARMS_DIR.mkdir(exist_ok=True)


def run(no_news: bool = False,
        force_download: bool = False,
        manually_added: list[str] | None = None,
        manually_removed: list[str] | None = None,
        inspect: list[str] | None = None):

    import pandas as pd
    import tickers as tickers_mod
    from get_stock_data import update_all_stocks, get_stock_data, last_updated, _load
    from strategy import check_all_strategies, STRATEGIES
    from information import run_news_discovery

    manually_added   = manually_added   or []
    manually_removed = manually_removed or []

    # ── Timestamps ────────────────────────────────────────────────────────────
    run_ts    = datetime.now(tz=timezone.utc)
    run_label = run_ts.strftime("%Y-%m-%d_%H-%M")
    alarm_path = ALARMS_DIR / f"{run_label}.txt"
    today = run_ts.date()

    print(f"\n{'='*60}")
    print(f"  AutoStock Daily Run — {run_ts.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}\n")

    # ── Step 1: News discovery ────────────────────────────────────────────────
    newly_added: list[str] = []
    if not no_news:
        print("[ 1/5 ] News discovery …")
        newly_added = run_news_discovery(alarm_path=None)   # alarm appended later
        if newly_added:
            print(f"        + {len(newly_added)} new ticker(s): {newly_added}")
        else:
            print("        No new tickers from news.")
    else:
        print("[ 1/5 ] News discovery skipped (--no-news).")

    # Reload tickers so NEWS_DISCOVERED is fresh
    reload(tickers_mod)
    from tickers import get_tickers
    base = get_tickers(include_etfs=False)
    all_tickers = list(dict.fromkeys(
        [t for t in base + manually_added if t not in manually_removed]
    ))
    print(f"\n[ 2/5 ] Ticker universe: {len(all_tickers)} stocks.")

    # ── Step 2: Incremental data update ──────────────────────────────────────
    print(f"\n[ 3/5 ] Updating price data …")
    needs_update = [
        t for t in all_tickers
        if (lu := last_updated(t)) is None or lu.date() < today
    ]
    print(f"        {len(needs_update)} tickers need new bars.")

    stock_data = update_all_stocks(needs_update, force_full=force_download)

    # Load already-current tickers from disk
    for t in all_tickers:
        if t not in stock_data:
            df = _load(t)
            if df is not None and not df.empty:
                stock_data[t] = df

    latest_dates = {
        sym: df.index.max().strftime("%Y-%m-%d")
        for sym, df in stock_data.items()
    }
    overall_latest = max(latest_dates.values()) if latest_dates else "N/A"
    print(f"        Data available for {len(stock_data)} tickers.")
    print(f"        Latest bar date: {overall_latest}")

    # ── Step 3: Run strategies ────────────────────────────────────────────────
    print(f"\n[ 4/5 ] Running strategies …")
    results_all: list[dict] = []
    for sym, df in stock_data.items():
        any_triggered, strat_results = check_all_strategies(df, sym)
        if any_triggered:
            for r in strat_results:
                if r["triggered"]:
                    results_all.append({
                        "Symbol"  : sym,
                        "Strategy": r["strategy"],
                        "Signal"  : r["description"],
                    })

    print(f"        Signals triggered: {len(results_all)} across {len({r['Symbol'] for r in results_all})} stocks.")

    # ── Step 4: Display results ───────────────────────────────────────────────
    print(f"\n[ 5/5 ] Results\n")
    strategy_names = [s[0] for s in STRATEGIES]
    if not results_all:
        print("  No trading signals triggered today.")
    else:
        for strat in strategy_names:
            subset = [r for r in results_all if r["Strategy"] == strat]
            if not subset:
                continue
            print(f"  ━━ {strat} ({len(subset)} signal(s)) ━━")
            for r in subset:
                data_date = latest_dates.get(r["Symbol"], "?")
                print(f"    {r['Symbol']:8s} [data thru {data_date}]")
                print(f"    {r['Signal']}\n")

    # ── Step 5: Write alarm file ──────────────────────────────────────────────
    with open(alarm_path, "w", encoding="utf-8") as f:
        f.write("AutoStock Daily Report\n")
        f.write(f"Generated  : {run_ts.strftime('%Y-%m-%d %H:%M UTC')}\n")
        f.write(f"Latest data: {overall_latest}\n")
        f.write(f"Universe   : {len(stock_data)} tickers\n")
        f.write("=" * 60 + "\n")
        f.write("SIGNALS\n")
        f.write("=" * 60 + "\n")
        if not results_all:
            f.write("  No signals triggered today.\n")
        else:
            for strat in strategy_names:
                subset = [r for r in results_all if r["Strategy"] == strat]
                if not subset:
                    continue
                f.write(f"\n[{strat}]\n")
                for r in subset:
                    data_date = latest_dates.get(r["Symbol"], "?")
                    f.write(f"  {r['Symbol']:8s} (data thru {data_date})\n")
                    f.write(f"  {r['Signal']}\n\n")

        # News section
        if newly_added:
            f.write("\n" + "=" * 60 + "\n")
            f.write("NEWS-DISCOVERED TICKERS\n")
            f.write("=" * 60 + "\n")
            for t in newly_added:
                f.write(f"  + {t}\n")

    print(f"\nAlarm saved → {alarm_path}\n")
    print(alarm_path.read_text())

    # ── Optional: inspect specific tickers ───────────────────────────────────
    if inspect:
        indicator_cols = ["Close", "MA20", "MA50", "MA200",
                          "DIF", "DEA", "MACD_hist", "RSI14",
                          "BB_upper", "BB_lower", "ATR14", "Volume"]
        for sym in inspect:
            df = stock_data.get(sym)
            if df is None:
                print(f"\n{sym}: no data available.")
                continue
            print(f"\n{'─'*60}")
            print(f"{sym} — last 5 bars")
            print(df[indicator_cols].tail(5).round(4).to_string())
            print()
            _, strat_results = check_all_strategies(df, sym)
            for r in strat_results:
                status = "✓ TRIGGERED" if r["triggered"] else "✗"
                print(f"  {status:15s}  [{r['strategy']}]")
                if r["triggered"]:
                    print(f"  {' '*17}{r['description']}")


def main():
    parser = argparse.ArgumentParser(description="AutoStock daily screening runner")
    parser.add_argument("--no-news",       action="store_true",
                        help="Skip news discovery step")
    parser.add_argument("--force-download", action="store_true",
                        help="Re-download full price history for all tickers")
    parser.add_argument("--add",           nargs="*", metavar="TICKER",
                        help="Extra tickers to include this run")
    parser.add_argument("--remove",        nargs="*", metavar="TICKER",
                        help="Tickers to exclude this run")
    parser.add_argument("--inspect",       nargs="*", metavar="TICKER",
                        help="Print full indicator table for these tickers")
    args = parser.parse_args()

    run(
        no_news        = args.no_news,
        force_download = args.force_download,
        manually_added = args.add    or [],
        manually_removed = args.remove or [],
        inspect        = args.inspect or [],
    )


if __name__ == "__main__":
    main()
