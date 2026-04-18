"""
strategy.py
-----------
Trading strategy functions.
Each function receives a DataFrame of OHLCV + indicators (from get_stock_data.py)
and returns (triggered: bool, description: str).

Strategies
----------
1. ma_pullback                  – Trend-following pullback to MA20
2. bollinger_rsi_mean_reversion – Mean-reversion at lower Bollinger Band
3. trend_pullback_momentum      – Trend + pullback + MACD momentum
4. golden_death_cross           – MA50/MA200 crossover system
5. macd_trend_strategy          – DIF/DEA crossover in bullish territory

check_all_strategies            – Run all; return first triggered signal (or False)
"""

from __future__ import annotations
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Helper ────────────────────────────────────────────────────────────────────

def _safe_get(df: pd.DataFrame, col: str, row: int = -1):
    """Return df[col].iloc[row] or NaN if column is missing/NaN."""
    if col not in df.columns:
        return np.nan
    val = df[col].iloc[row]
    return val if pd.notna(val) else np.nan


def _has_enough_rows(df: pd.DataFrame, n: int = 210) -> bool:
    return len(df) >= n


# ── Strategy 1 ────────────────────────────────────────────────────────────────

def ma_pullback(df: pd.DataFrame) -> tuple[bool, str]:
    """
    MA Pullback Strategy
    ====================
    Setup  : price > MA50 and MA50 slope positive (last 5 bars rising)
    Entry  : price touched MA20 (low ≤ MA20) AND bullish close (close > open)
             AND MACD histogram increasing OR RSI > 40
             AND volume ≥ 1.2 × Volume_MA20
    Avoid  : MA50 is flat, price near MA200 resistance, low volume
    """
    if not _has_enough_rows(df, 210):
        return False, "Insufficient data (need 210+ bars)"

    close   = _safe_get(df, "Close")
    open_   = _safe_get(df, "Open")
    low     = _safe_get(df, "Low")
    ma20    = _safe_get(df, "MA20")
    ma50    = _safe_get(df, "MA50")
    ma200   = _safe_get(df, "MA200")
    hist    = _safe_get(df, "MACD_hist")
    hist_1  = _safe_get(df, "MACD_hist", -2)
    rsi     = _safe_get(df, "RSI14")
    volume  = _safe_get(df, "Volume")
    vol_ma  = _safe_get(df, "Volume_MA20")

    # Guard: all required values must be valid
    if any(np.isnan(v) for v in [close, open_, low, ma20, ma50, volume, vol_ma]):
        return False, "Missing indicator values"

    # ── Setup filter ──
    if close <= ma50:
        return False, f"Price ({close:.2f}) is not above MA50 ({ma50:.2f})"

    # MA50 slope: last 5 bars must be increasing
    ma50_series = df["MA50"].dropna().iloc[-6:]
    if len(ma50_series) < 5:
        return False, "Not enough MA50 data for slope check"
    ma50_slope_ok = all(ma50_series.iloc[i] < ma50_series.iloc[i + 1]
                        for i in range(len(ma50_series) - 1))
    if not ma50_slope_ok:
        # Soften to: net positive over 5 bars
        ma50_slope_ok = ma50_series.iloc[-1] > ma50_series.iloc[-5]
    if not ma50_slope_ok:
        return False, "MA50 slope is not clearly positive"

    # ── Avoid conditions ──
    # Flat MA50 (range < 0.5% over 10 bars)
    ma50_10 = df["MA50"].dropna().iloc[-11:]
    if len(ma50_10) >= 10:
        pct_range = (ma50_10.max() - ma50_10.min()) / ma50_10.mean()
        if pct_range < 0.005:
            return False, f"MA50 is flat (range {pct_range:.2%} over 10 bars)"

    # Price near MA200 resistance (within 2%)
    if not np.isnan(ma200) and abs(close - ma200) / ma200 < 0.02:
        return False, f"Price is near MA200 resistance ({ma200:.2f})"

    # Low volume
    if vol_ma > 0 and volume < vol_ma:
        return False, f"Volume ({volume:,.0f}) is below 20-day average ({vol_ma:,.0f})"

    # ── Entry conditions ──
    # 1. Pullback: low touched MA20
    touched_ma20 = low <= ma20 * 1.005   # allow 0.5% tolerance
    # 2. Bullish reversal candle
    bullish_candle = close > open_
    # 3. Price closed back above MA20
    closed_above_ma20 = close > ma20
    reversal_ok = bullish_candle or closed_above_ma20

    # 4. Momentum
    hist_increasing = (not np.isnan(hist) and not np.isnan(hist_1)) and hist > hist_1
    rsi_ok = (not np.isnan(rsi)) and rsi > 40
    momentum_ok = hist_increasing or rsi_ok

    # 5. Volume filter
    volume_ok = vol_ma > 0 and volume >= 1.2 * vol_ma

    if not touched_ma20:
        return False, f"No pullback to MA20 (low={low:.2f}, MA20={ma20:.2f})"
    if not reversal_ok:
        return False, "No bullish reversal candle"
    if not momentum_ok:
        return False, f"Momentum not confirmed (MACD hist increasing={hist_increasing}, RSI={rsi:.1f})"
    if not volume_ok:
        return False, f"Volume not sufficient ({volume:,.0f} vs 1.2×avg {1.2*vol_ma:,.0f})"

    atr14 = _safe_get(df, "ATR14")
    stop_loss = close - 1.5 * atr14 if not np.isnan(atr14) else None
    sl_str = f"{stop_loss:.2f}" if stop_loss is not None else "N/A"
    return (
        True,
        f"[MA Pullback] Price={close:.2f} pulled back to MA20={ma20:.2f}, "
        f"bullish close, momentum confirmed (RSI={rsi:.1f}), "
        f"volume {volume:,.0f} ≥ 1.2×avg. "
        f"Stop: {sl_str}  |  Trail: hold while price > MA20={ma20:.2f}, exit if close below"
    )


# ── Strategy 2 ────────────────────────────────────────────────────────────────

def bollinger_rsi_mean_reversion(df: pd.DataFrame) -> tuple[bool, str]:
    """
    Bollinger + RSI Mean Reversion (LONG)
    ======================================
    Setup  : sideways market — MA50 relatively flat
    Entry  : price touched lower Bollinger Band
             RSI < 30
             Volume decreasing (current < prev bar)
             Price then closes back inside the band
    Stop   : below lower band − 1×ATR14
    Target : BB_middle (MA20) or BB_upper
    """
    if not _has_enough_rows(df, 60):
        return False, "Insufficient data"

    close    = _safe_get(df, "Close")
    low      = _safe_get(df, "Low")
    bb_lower = _safe_get(df, "BB_lower")
    bb_upper = _safe_get(df, "BB_upper")
    bb_mid   = _safe_get(df, "BB_middle")
    rsi      = _safe_get(df, "RSI14")
    volume   = _safe_get(df, "Volume")
    volume_1 = _safe_get(df, "Volume", -2)
    atr      = _safe_get(df, "ATR14")

    if any(np.isnan(v) for v in [close, low, bb_lower, bb_upper, bb_mid, rsi]):
        return False, "Missing indicator values"

    # ── Setup: sideways MA50 ──
    ma50_10 = df["MA50"].dropna().iloc[-11:]
    if len(ma50_10) >= 10:
        pct_range = (ma50_10.max() - ma50_10.min()) / ma50_10.mean()
        if pct_range > 0.05:
            return False, f"MA50 is trending (range {pct_range:.2%}), not sideways"

    # ── Entry conditions ──
    touched_lower = low <= bb_lower * 1.002
    rsi_oversold  = rsi < 30
    vol_decreasing = (not np.isnan(volume_1) and volume_1 > 0) and volume < volume_1
    closed_inside = close > bb_lower   # closed back inside band

    if not touched_lower:
        return False, f"Price did not touch lower BB (low={low:.2f}, BB_lower={bb_lower:.2f})"
    if not rsi_oversold:
        return False, f"RSI not oversold ({rsi:.1f} ≥ 30)"
    if not vol_decreasing:
        return False, "Volume not decreasing on the pullback"
    if not closed_inside:
        return False, "Price did not close back above lower BB"

    stop = bb_lower - atr if not np.isnan(atr) else None
    stop_str = f"{stop:.2f}" if stop is not None else "N/A"
    return (
        True,
        f"[Bollinger+RSI MeanRev] Price={close:.2f} bounced from BB_lower={bb_lower:.2f}, "
        f"RSI={rsi:.1f} (oversold), volume decreasing. "
        f"Stop: {stop_str}  |  Target: BB_mid={bb_mid:.2f}, full target BB_upper={bb_upper:.2f}"
    )


# ── Strategy 3 ────────────────────────────────────────────────────────────────

def trend_pullback_momentum(df: pd.DataFrame) -> tuple[bool, str]:
    """
    Trend + Pullback + Momentum
    ===========================
    Setup   : price > MA50 (trend)
    Pullback: price pulled back to MA20 (low ≤ MA20 × 1.01)
    Trigger : MACD histogram increasing (current > previous)
    Confirm : volume spike (volume > Volume_MA20)
    """
    if not _has_enough_rows(df, 60):
        return False, "Insufficient data"

    close   = _safe_get(df, "Close")
    low     = _safe_get(df, "Low")
    ma20    = _safe_get(df, "MA20")
    ma50    = _safe_get(df, "MA50")
    hist    = _safe_get(df, "MACD_hist")
    hist_1  = _safe_get(df, "MACD_hist", -2)
    volume  = _safe_get(df, "Volume")
    vol_ma  = _safe_get(df, "Volume_MA20")

    if any(np.isnan(v) for v in [close, low, ma20, ma50, hist, volume, vol_ma]):
        return False, "Missing indicator values"

    trend_ok    = close > ma50
    pullback_ok = low <= ma20 * 1.01
    macd_ok     = (not np.isnan(hist_1)) and hist > hist_1
    volume_ok   = vol_ma > 0 and volume > vol_ma

    if not trend_ok:
        return False, f"No uptrend (price={close:.2f} ≤ MA50={ma50:.2f})"
    if not pullback_ok:
        return False, f"No pullback to MA20 (low={low:.2f}, MA20={ma20:.2f})"
    if not macd_ok:
        return False, f"MACD histogram not increasing ({hist:.4f} vs prev {hist_1:.4f})"
    if not volume_ok:
        return False, f"No volume spike ({volume:,.0f} ≤ avg {vol_ma:,.0f})"

    atr = _safe_get(df, "ATR14")
    stop = close - 1.5 * atr if not np.isnan(atr) else None
    stop_str = f"{stop:.2f}" if stop is not None else "N/A"
    return (
        True,
        f"[Trend+Pullback+Momentum] Price={close:.2f} above MA50={ma50:.2f}, "
        f"pulled back to MA20={ma20:.2f}, MACD histogram increasing ({hist:.4f}), "
        f"volume spike ({volume:,.0f} vs avg {vol_ma:,.0f}). "
        f"Stop: {stop_str}  |  Trail: hold while price > MA20={ma20:.2f}, exit if close below"
    )


# ── Strategy 4 ────────────────────────────────────────────────────────────────

def golden_death_cross(df: pd.DataFrame) -> tuple[bool, str]:
    """
    Golden / Death Cross
    ====================
    BUY  signal: MA50 crosses ABOVE MA200 (Golden Cross)
                 AND dMA50/dt > 0 (MA50 still rising)
                 AND (volume increasing OR MACD > 0)
    SELL signal: MA50 crosses BELOW MA200 (Death Cross) — returned as warning.
    """
    if not _has_enough_rows(df, 210):
        return False, "Insufficient data (need 210+ bars for MA200)"

    ma50     = _safe_get(df, "MA50")
    ma200    = _safe_get(df, "MA200")
    ma50_1   = _safe_get(df, "MA50", -2)
    ma200_1  = _safe_get(df, "MA200", -2)
    dif      = _safe_get(df, "DIF")
    volume   = _safe_get(df, "Volume")
    volume_1 = _safe_get(df, "Volume", -2)

    if any(np.isnan(v) for v in [ma50, ma200, ma50_1, ma200_1]):
        return False, "Missing MA50/MA200 values"

    # Golden cross: previous bar MA50 ≤ MA200, current bar MA50 > MA200
    golden_cross = (ma50_1 <= ma200_1) and (ma50 > ma200)
    # OR: MA50 recently crossed (within last 3 bars) — check using slope
    recent_cross = ma50 > ma200 and ma50_1 > ma200_1
    # We only fire on the actual crossover bar; use golden_cross
    if not golden_cross:
        # Death cross fires as a SELL/WARNING signal — must return True so it
        # appears in the alarm output; the description makes the direction clear.
        death_cross = (ma50_1 >= ma200_1) and (ma50 < ma200)
        if death_cross:
            return (
                True,
                f"[Death Cross ⚠ SELL SIGNAL] MA50={ma50:.2f} just crossed BELOW "
                f"MA200={ma200:.2f} — strong bearish signal. "
                f"Exit or avoid long positions. No stop target (trend exit)."
            )
        return False, f"No cross detected (MA50={ma50:.2f}, MA200={ma200:.2f})"

    # Confirm MA50 is rising
    ma50_rising = ma50 > ma50_1
    if not ma50_rising:
        return False, "Golden Cross detected but MA50 is not rising"

    # Confirm volume or MACD
    vol_up   = (not np.isnan(volume_1) and volume_1 > 0) and volume > volume_1
    macd_pos = (not np.isnan(dif)) and dif > 0
    confirm  = vol_up or macd_pos
    if not confirm:
        return False, "Golden Cross detected but neither volume nor MACD confirms"

    stop = ma200 * 0.98   # 2% below MA200 — if it falls back through, cross failed
    return (
        True,
        f"[Golden Cross BUY] MA50={ma50:.2f} just crossed ABOVE MA200={ma200:.2f}. "
        f"MA50 rising, {'volume increasing' if vol_up else 'MACD DIF > 0'}. "
        f"Stop: {stop:.2f}  |  Trail: hold while MA50 ({ma50:.2f}) > MA200 ({ma200:.2f}), exit on death cross"
    )


# ── Strategy 5 ────────────────────────────────────────────────────────────────

def macd_trend_strategy(df: pd.DataFrame) -> tuple[bool, str]:
    """
    MACD Trend Strategy
    ===================
    Setup  : price > MA50
    Entry  : DIF crosses above DEA AND both DIF > 0 and DEA > 0
    Stop   : close below MA20
    Exit   : DIF crosses below DEA
    """
    if not _has_enough_rows(df, 60):
        return False, "Insufficient data"

    close  = _safe_get(df, "Close")
    ma20   = _safe_get(df, "MA20")
    ma50   = _safe_get(df, "MA50")
    dif    = _safe_get(df, "DIF")
    dea    = _safe_get(df, "DEA")
    dif_1  = _safe_get(df, "DIF", -2)
    dea_1  = _safe_get(df, "DEA", -2)

    if any(np.isnan(v) for v in [close, ma50, dif, dea, dif_1, dea_1]):
        return False, "Missing indicator values"

    # Setup
    if close <= ma50:
        return False, f"Price ({close:.2f}) not above MA50 ({ma50:.2f})"

    # DIF crosses above DEA (bullish crossover)
    crossed_up = (dif_1 <= dea_1) and (dif > dea)
    if not crossed_up:
        return False, f"No bullish MACD crossover (DIF={dif:.4f}, DEA={dea:.4f})"

    # Both must be positive (above zero line)
    if dif <= 0 or dea <= 0:
        return False, f"MACD crossover below zero line (DIF={dif:.4f}, DEA={dea:.4f})"

    return (
        True,
        f"[MACD Trend] Price={close:.2f} above MA50={ma50:.2f}. "
        f"DIF={dif:.4f} crossed above DEA={dea:.4f}, both positive. "
        f"Stop: {ma20:.2f} (MA20)  |  Trail: hold while DIF ({dif:.4f}) > DEA ({dea:.4f}), exit on crossover"
    )


# ── Aggregate ─────────────────────────────────────────────────────────────────

STRATEGIES = [
    ("MA Pullback",                ma_pullback),
    ("Bollinger+RSI MeanReversion", bollinger_rsi_mean_reversion),
    ("Trend+Pullback+Momentum",    trend_pullback_momentum),
    ("Golden/Death Cross",         golden_death_cross),
    ("MACD Trend",                 macd_trend_strategy),
]


def check_all_strategies(df: pd.DataFrame,
                         symbol: str = "") -> tuple[bool, list[dict]]:
    """
    Run all strategies against `df`.

    Returns
    -------
    overall_triggered : bool
        True if at least one strategy fired.
    results : list[dict]
        One entry per strategy:
        {name, triggered, description}
    """
    results = []
    any_triggered = False

    for name, func in STRATEGIES:
        try:
            triggered, desc = func(df)
        except Exception as e:
            triggered, desc = False, f"Error: {e}"
            logger.warning(f"Strategy '{name}' raised an exception for {symbol}: {e}")

        results.append({"strategy": name, "triggered": triggered, "description": desc})
        if triggered:
            any_triggered = True

    return any_triggered, results


def summarize_signals(symbol: str, results: list[dict]) -> str:
    """Format strategy results into a human-readable summary string."""
    triggered = [r for r in results if r["triggered"]]
    if not triggered:
        return f"{symbol}: No signals triggered."
    lines = [f"{symbol} — {len(triggered)} signal(s) triggered:"]
    for r in triggered:
        lines.append(f"  • {r['description']}")
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from get_stock_data import get_stock_data

    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["AAPL", "NVDA", "XOM"]
    for sym in symbols:
        df = get_stock_data(sym)
        if df is None:
            print(f"{sym}: no data available")
            continue
        triggered, results = check_all_strategies(df, sym)
        print(summarize_signals(sym, results))
        print()
