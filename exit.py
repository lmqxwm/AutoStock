"""
exit.py
-------
Evaluate exit conditions for held positions listed in held_stocks.txt.

For each position the script:
  1. Loads the cached parquet (computed by get_stock_data.py).
  2. Locates the entry-date bar to compute the *fixed* stop price.
  3. Inspects the latest bar for trail / target conditions.
  4. Prints a recommendation: HOLD | SELL 50% | SELL 100%.

Usage
-----
  python exit.py                   # use today's (latest) cached data
  python exit.py --date 2026-04-20 # simulate as of a specific date
  python exit.py --verbose         # show all indicator values for each position
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from datetime import date

import numpy as np
import pandas as pd

# ── project imports ────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from get_stock_data import _load   # noqa: E402


# ── constants ─────────────────────────────────────────────────────────────────

HELD_FILE  = Path(__file__).parent / "held_stocks.txt"

STRATEGIES = {
    "MA Pullback",
    "Bollinger+RSI MeanReversion",
    "Trend+Pullback+Momentum",
    "Golden/Death Cross",
    "MACD Trend",
}

# ── helpers ────────────────────────────────────────────────────────────────────

def _v(row: pd.Series, col: str) -> float:
    """Return a float value from a row; NaN if missing."""
    if col not in row.index:
        return np.nan
    val = row[col]
    return float(val) if pd.notna(val) else np.nan


def _pct(current: float, base: float) -> str:
    if base == 0:
        return "N/A"
    return f"{(current - base) / base * 100:+.2f}%"


# ── file parser ────────────────────────────────────────────────────────────────

def parse_held_file(path: Path) -> list[dict]:
    """
    Parse held_stocks.txt.

    Format:  SYMBOL | entry_price | entry_date | strategy | shares (optional)
    Lines starting with '#' or blank are skipped.
    """
    positions = []
    if not path.exists():
        print(f"[ERROR] {path} not found.")
        return positions

    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            print(f"[WARN] line {lineno}: expected at least 4 fields — skipping: {raw!r}")
            continue

        sym          = parts[0].upper()
        try:
            entry_price = float(parts[1])
        except ValueError:
            print(f"[WARN] line {lineno}: bad entry_price '{parts[1]}' — skipping {sym}")
            continue

        entry_date_str = parts[2]
        strategy       = parts[3]
        shares         = None
        if len(parts) >= 5:
            try:
                shares = float(parts[4])
            except ValueError:
                pass

        try:
            entry_date = date.fromisoformat(entry_date_str)
        except ValueError:
            print(f"[WARN] line {lineno}: bad entry_date '{entry_date_str}' — skipping {sym}")
            continue

        positions.append({
            "symbol":      sym,
            "entry_price": entry_price,
            "entry_date":  entry_date,
            "strategy":    strategy,
            "shares":      shares,
        })

    return positions


# ── strategy-specific exit logic ───────────────────────────────────────────────

def _evaluate(pos: dict, df: pd.DataFrame) -> dict:
    """
    Core evaluation.  Returns a dict with:
        stop_price, trail_ok, target_status,
        action (HOLD | SELL 50% | SELL 100%),
        reason, current_price
    """
    sym          = pos["symbol"]
    entry_price  = pos["entry_price"]
    entry_date   = pos["entry_date"]
    strategy     = pos["strategy"]

    # ── locate entry-date bar ─────────────────────────────────────────────────
    entry_ts = pd.Timestamp(entry_date, tz="UTC")
    # Find the closest bar on or after entry_date (handles weekends/holidays)
    future = df[df.index >= entry_ts]
    if future.empty:
        return _error(pos, "Entry date is beyond last cached bar — no data to evaluate.")
    entry_row = future.iloc[0]

    # ── current (latest) bar ──────────────────────────────────────────────────
    current_row   = df.iloc[-1]
    current_close = _v(current_row, "Close")
    current_low   = _v(current_row, "Low")
    current_high  = _v(current_row, "High")
    as_of_date    = df.index[-1].date()

    # ── strategy dispatch ─────────────────────────────────────────────────────
    if strategy == "MA Pullback":
        return _exit_ma_pullback(pos, entry_row, current_row,
                                 current_close, current_low, as_of_date)

    elif strategy == "Bollinger+RSI MeanReversion":
        return _exit_bollinger(pos, entry_row, current_row,
                               current_close, current_low, as_of_date)

    elif strategy == "Trend+Pullback+Momentum":
        return _exit_trend_pullback(pos, entry_row, current_row,
                                    current_close, current_low, as_of_date)

    elif strategy == "Golden/Death Cross":
        return _exit_golden_cross(pos, entry_row, current_row,
                                  current_close, current_low, as_of_date)

    elif strategy == "MACD Trend":
        return _exit_macd_trend(pos, entry_row, current_row,
                                current_close, current_low, as_of_date)

    else:
        return _exit_generic(pos, entry_row, current_row,
                             current_close, current_low, as_of_date)


def _error(pos, msg):
    return {
        "symbol":        pos["symbol"],
        "entry_price":   pos["entry_price"],
        "entry_date":    pos["entry_date"],
        "strategy":      pos["strategy"],
        "shares":        pos["shares"],
        "current_price": None,
        "as_of":         None,
        "stop_price":    None,
        "action":        "⚠ UNKNOWN",
        "reason":        msg,
    }


# ── MA Pullback ────────────────────────────────────────────────────────────────

def _exit_ma_pullback(pos, entry_row, current_row,
                      close, low, as_of) -> dict:
    """
    Stop  : entry_price − 1.5 × ATR14  (fixed at entry)
    Trail : hold while close > MA20; exit if daily close drops below MA20
    """
    atr_entry  = _v(entry_row, "ATR14")
    stop_price = (pos["entry_price"] - 1.5 * atr_entry
                  if not np.isnan(atr_entry) else np.nan)
    ma20       = _v(current_row, "MA20")

    if not np.isnan(stop_price) and low <= stop_price:
        return _result(pos, close, as_of, stop_price,
                       "SELL 100%",
                       f"Hard stop hit — low ({low:.2f}) ≤ stop ({stop_price:.2f})")

    if not np.isnan(ma20) and close < ma20:
        return _result(pos, close, as_of, stop_price,
                       "SELL 100%",
                       f"Trail broken — close ({close:.2f}) < MA20 ({ma20:.2f})")

    trail_str = f"MA20={ma20:.2f}" if not np.isnan(ma20) else "MA20=N/A"
    return _result(pos, close, as_of, stop_price,
                   "HOLD",
                   f"Close ({close:.2f}) > {trail_str} — trail intact")


# ── Bollinger + RSI Mean Reversion ────────────────────────────────────────────

def _exit_bollinger(pos, entry_row, current_row,
                    close, low, as_of) -> dict:
    """
    Stop     : BB_lower_at_entry − ATR14_at_entry  (fixed)
    Target 1 : close ≥ current BB_middle  → SELL 50%
    Target 2 : close ≥ current BB_upper   → SELL 100%
    """
    bb_lower_entry = _v(entry_row, "BB_lower")
    atr_entry      = _v(entry_row, "ATR14")
    stop_price     = (bb_lower_entry - atr_entry
                      if not np.isnan(bb_lower_entry) and not np.isnan(atr_entry)
                      else np.nan)

    bb_mid   = _v(current_row, "BB_middle")
    bb_upper = _v(current_row, "BB_upper")

    if not np.isnan(stop_price) and low <= stop_price:
        return _result(pos, close, as_of, stop_price,
                       "SELL 100%",
                       f"Hard stop hit — low ({low:.2f}) ≤ stop ({stop_price:.2f})")

    if not np.isnan(bb_upper) and close >= bb_upper:
        return _result(pos, close, as_of, stop_price,
                       "SELL 100%",
                       f"Full target hit — close ({close:.2f}) ≥ BB_upper ({bb_upper:.2f})")

    if not np.isnan(bb_mid) and close >= bb_mid:
        upper_str = f"{bb_upper:.2f}" if not np.isnan(bb_upper) else "N/A"
        return _result(pos, close, as_of, stop_price,
                       "SELL 50%",
                       f"Partial target hit — close ({close:.2f}) ≥ BB_middle ({bb_mid:.2f}). "
                       f"Hold remainder for BB_upper ({upper_str})")

    targets = []
    if not np.isnan(bb_mid):
        targets.append(f"T1={bb_mid:.2f}")
    if not np.isnan(bb_upper):
        targets.append(f"T2={bb_upper:.2f}")
    return _result(pos, close, as_of, stop_price,
                   "HOLD",
                   f"Awaiting mean-reversion targets ({', '.join(targets)}). "
                   f"Close={close:.2f}")


# ── Trend + Pullback + Momentum ───────────────────────────────────────────────

def _exit_trend_pullback(pos, entry_row, current_row,
                         close, low, as_of) -> dict:
    """
    Stop  : entry_price − 1.5 × ATR14  (fixed at entry)
    Trail : hold while close > MA20; exit if close drops below MA20
    """
    # Identical exit rules to MA Pullback
    return _exit_ma_pullback(pos, entry_row, current_row, close, low, as_of)


# ── Golden / Death Cross ──────────────────────────────────────────────────────

def _exit_golden_cross(pos, entry_row, current_row,
                       close, low, as_of) -> dict:
    """
    Stop  : MA200_at_entry × 0.98  (fixed — if price falls through MA200, cross failed)
    Trail : hold while MA50 > MA200; exit when death cross occurs (MA50 < MA200)
    """
    ma200_entry = _v(entry_row, "MA200")
    stop_price  = ma200_entry * 0.98 if not np.isnan(ma200_entry) else np.nan

    ma50_now  = _v(current_row, "MA50")
    ma200_now = _v(current_row, "MA200")

    if not np.isnan(stop_price) and low <= stop_price:
        return _result(pos, close, as_of, stop_price,
                       "SELL 100%",
                       f"Hard stop hit — low ({low:.2f}) ≤ stop ({stop_price:.2f}). "
                       f"Price fell through MA200 zone.")

    if not np.isnan(ma50_now) and not np.isnan(ma200_now) and ma50_now < ma200_now:
        return _result(pos, close, as_of, stop_price,
                       "SELL 100%",
                       f"Death cross — MA50 ({ma50_now:.2f}) < MA200 ({ma200_now:.2f}). "
                       f"Trail broken.")

    trail_str = (f"MA50 ({ma50_now:.2f}) > MA200 ({ma200_now:.2f})"
                 if not np.isnan(ma50_now) and not np.isnan(ma200_now)
                 else "MA50/MA200 N/A")
    return _result(pos, close, as_of, stop_price,
                   "HOLD",
                   f"Golden Cross trail intact — {trail_str}")


# ── MACD Trend ────────────────────────────────────────────────────────────────

def _exit_macd_trend(pos, entry_row, current_row,
                     close, low, as_of) -> dict:
    """
    Stop  : current MA20  (dynamic — exit if close drops below MA20)
    Trail : hold while DIF > DEA; exit when DIF crosses back below DEA
    """
    ma20_now = _v(current_row, "MA20")
    dif      = _v(current_row, "DIF")
    dea      = _v(current_row, "DEA")

    # Use MA20 at entry as the initial hard stop reference for display
    ma20_entry = _v(entry_row, "MA20")
    stop_price = ma20_entry if not np.isnan(ma20_entry) else np.nan

    if not np.isnan(ma20_now) and close < ma20_now:
        return _result(pos, close, as_of, stop_price,
                       "SELL 100%",
                       f"Stop hit — close ({close:.2f}) < MA20 ({ma20_now:.2f})")

    if not np.isnan(dif) and not np.isnan(dea) and dif <= dea:
        return _result(pos, close, as_of, stop_price,
                       "SELL 100%",
                       f"Trail broken — DIF ({dif:.4f}) ≤ DEA ({dea:.4f}). MACD crossover down.")

    dif_str = f"DIF ({dif:.4f}) > DEA ({dea:.4f})" if not np.isnan(dif) else "DIF/DEA N/A"
    return _result(pos, close, as_of, stop_price,
                   "HOLD",
                   f"MACD trail intact — {dif_str}. Close ({close:.2f}) > MA20 ({ma20_now:.2f})")


# ── Generic (unknown strategy) ────────────────────────────────────────────────

def _exit_generic(pos, entry_row, current_row,
                  close, low, as_of) -> dict:
    """
    Generic rules (no recognised strategy):
      Stop  : entry_price × 0.92  (8% hard stop)
      Trail : close > MA20
      Target: entry_price × 1.16  (2R at 8% risk)
    """
    entry_price = pos["entry_price"]
    stop_price  = entry_price * 0.92
    target_2r   = entry_price * 1.16
    ma20_now    = _v(current_row, "MA20")

    if low <= stop_price:
        return _result(pos, close, as_of, stop_price,
                       "SELL 100%",
                       f"Hard stop hit — low ({low:.2f}) ≤ 8% stop ({stop_price:.2f})")

    if close >= target_2r:
        return _result(pos, close, as_of, stop_price,
                       "SELL 100%",
                       f"2R target hit — close ({close:.2f}) ≥ target ({target_2r:.2f})")

    if not np.isnan(ma20_now) and close < ma20_now:
        return _result(pos, close, as_of, stop_price,
                       "SELL 100%",
                       f"Trail broken — close ({close:.2f}) < MA20 ({ma20_now:.2f})")

    return _result(pos, close, as_of, stop_price,
                   "HOLD",
                   f"Close={close:.2f}, stop={stop_price:.2f}, target={target_2r:.2f}")


# ── result builder ────────────────────────────────────────────────────────────

def _result(pos, current_price, as_of, stop_price, action, reason) -> dict:
    return {
        "symbol":        pos["symbol"],
        "entry_price":   pos["entry_price"],
        "entry_date":    pos["entry_date"],
        "strategy":      pos["strategy"],
        "shares":        pos["shares"],
        "current_price": current_price,
        "as_of":         as_of,
        "stop_price":    stop_price,
        "action":        action,
        "reason":        reason,
    }


# ── display ───────────────────────────────────────────────────────────────────

_ACTION_ICON = {
    "HOLD":       "✅ HOLD",
    "SELL 50%":   "⚠️  SELL 50%",
    "SELL 100%":  "🔴 SELL 100%",
    "⚠ UNKNOWN":  "❓ UNKNOWN",
}


def _display(result: dict, verbose: bool = False, df: pd.DataFrame | None = None):
    sym          = result["symbol"]
    entry_price  = result["entry_price"]
    entry_date   = result["entry_date"]
    strategy     = result["strategy"]
    shares       = result["shares"]
    current      = result["current_price"]
    as_of        = result["as_of"]
    stop_price   = result["stop_price"]
    action       = result["action"]
    reason       = result["reason"]

    icon = _ACTION_ICON.get(action, action)

    pnl_str = ""
    if current is not None and entry_price > 0:
        pnl_pct = (current - entry_price) / entry_price * 100
        pnl_str = f"  P&L: {pnl_pct:+.2f}%"
        if shares is not None:
            pnl_dollar = (current - entry_price) * shares
            pnl_str += f" (${pnl_dollar:+,.2f} on {shares:.0f} sh)"

    print(f"{'─'*60}")
    print(f"  {sym}  [{strategy}]")
    print(f"  Entry  : ${entry_price:.2f} on {entry_date}  →  Current: "
          f"${current:.2f}" if current else f"  Entry: ${entry_price:.2f}")
    if as_of:
        print(f"  As-of  : {as_of}")
    if stop_price and not np.isnan(stop_price):
        stop_dist = (current - stop_price) / current * 100 if current else 0
        print(f"  Stop   : ${stop_price:.2f}  ({stop_dist:.1f}% below current)")
    if pnl_str:
        print(f"{pnl_str}")
    print(f"  {icon}")
    print(f"  {reason}")

    if verbose and df is not None and not df.empty:
        row = df.iloc[-1]
        cols = ["Close", "MA20", "MA50", "MA200", "DIF", "DEA",
                "RSI14", "BB_upper", "BB_middle", "BB_lower", "ATR14"]
        parts = []
        for c in cols:
            if c in row.index and pd.notna(row[c]):
                parts.append(f"{c}={row[c]:.4f}")
        if parts:
            print(f"  Indicators: {', '.join(parts)}")


# ── main ──────────────────────────────────────────────────────────────────────

def run(as_of_date: str | None = None, verbose: bool = False):
    positions = parse_held_file(HELD_FILE)
    if not positions:
        print("No positions found in held_stocks.txt (all lines may be commented out).")
        return

    # Determine cutoff
    cutoff = None
    if as_of_date:
        cutoff = pd.Timestamp(as_of_date, tz="UTC")
        print(f"★ Simulation mode — evaluating as of {as_of_date}\n")
    else:
        print(f"★ Exit check — latest cached data\n")

    print(f"{'═'*60}")
    print(f"  AutoStock — Exit Evaluation")
    print(f"  {len(positions)} position(s) loaded from held_stocks.txt")
    print(f"{'═'*60}")

    for pos in positions:
        sym = pos["symbol"]
        df  = _load(sym)

        if df is None or df.empty:
            print(f"\n  {sym}: no cached data — run the daily screener first to download price history.")
            continue

        if cutoff is not None:
            df = df[df.index <= cutoff]
            if df.empty:
                print(f"\n  {sym}: no data available before {as_of_date}.")
                continue

        result = _evaluate(pos, df)
        _display(result, verbose=verbose, df=df)

    print(f"{'─'*60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Evaluate exit conditions for held positions in held_stocks.txt."
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Simulate as of this date (uses cached data sliced at cutoff).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print full indicator snapshot for each position.",
    )
    args = parser.parse_args()
    run(as_of_date=args.date, verbose=args.verbose)
