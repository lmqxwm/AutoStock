"""
get_stock_data.py
-----------------
Downloads OHLCV history via yfinance BATCH calls (one HTTP request per
batch of up to BATCH_SIZE tickers) and computes all technical indicators.
Per-ticker data is stored as Parquet files in ./data/ for incremental updates.

Indicators
----------
MA5, MA10, MA20, MA50, MA100, MA200
DIF (EMA12−EMA26), DEA (EMA9 of DIF), MACD_hist (DIF−DEA)
RSI14
BB_upper, BB_middle (=MA20), BB_lower, BB_width
Volume_MA20
ATR14
"""

import logging
import warnings
from pathlib import Path
from datetime import datetime, timedelta, date, timezone
from collections import defaultdict

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

INITIAL_HISTORY_DAYS = 730   # ~2 years on first download
MIN_BARS = 210               # need at least this many rows for MA200
BATCH_SIZE = 100             # tickers per yf.download() call


# ── Technical indicators ──────────────────────────────────────────────────────

def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _add_mas(df: pd.DataFrame) -> pd.DataFrame:
    for p in (5, 10, 20, 50, 100, 200):
        df[f"MA{p}"] = df["Close"].rolling(p).mean()
    return df


def _add_macd(df: pd.DataFrame) -> pd.DataFrame:
    df["DIF"] = _ema(df["Close"], 12) - _ema(df["Close"], 26)
    df["DEA"] = _ema(df["DIF"], 9)
    df["MACD_hist"] = df["DIF"] - df["DEA"]
    return df


def _add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    df["RSI14"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    return df


def _add_bollinger(df: pd.DataFrame, period: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = df["Close"].rolling(period).mean()
    std = df["Close"].rolling(period).std()
    df["BB_middle"] = mid
    df["BB_upper"]  = mid + k * std
    df["BB_lower"]  = mid - k * std
    df["BB_width"]  = df["BB_upper"] - df["BB_lower"]
    return df


def _add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    hl  = df["High"] - df["Low"]
    hc  = (df["High"] - df["Close"].shift()).abs()
    lc  = (df["Low"]  - df["Close"].shift()).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df["ATR14"] = tr.ewm(com=period - 1, adjust=False).mean()
    return df


def _add_volume_ma(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df["Volume_MA20"] = df["Volume"].rolling(period).mean()
    return df


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for fn in (_add_mas, _add_macd, _add_rsi, _add_bollinger,
               _add_atr, _add_volume_ma):
        df = fn(df)
    return df


# ── Storage helpers ───────────────────────────────────────────────────────────

def _path(symbol: str) -> Path:
    return DATA_DIR / f"{symbol.upper().replace('.', '_')}.parquet"


def _load(symbol: str) -> pd.DataFrame | None:
    p = _path(symbol)
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
        df.index = pd.to_datetime(df.index, utc=True)
        return df
    except Exception as e:
        logger.warning(f"Cache read failed for {symbol}: {e}")
        return None


def _save(symbol: str, df: pd.DataFrame) -> None:
    df.to_parquet(_path(symbol))


def last_updated(symbol: str) -> datetime | None:
    df = _load(symbol)
    if df is not None and not df.empty:
        return df.index.max().to_pydatetime()
    return None


# ── Batch download ────────────────────────────────────────────────────────────

OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def _yf_batch(symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    """
    Download multiple tickers in one yf.download() call.
    Returns {symbol: OHLCV DataFrame}.  Silently drops tickers with no data.

    Handles both old yfinance (flat columns for single ticker) and new yfinance
    (always MultiIndex: top level = field name, second level = ticker).
    """
    if not symbols:
        return {}

    raw = yf.download(
        tickers=symbols,
        start=start,
        end=end,
        auto_adjust=True,
        group_by="ticker",
        threads=True,
        progress=False,
    )

    results: dict[str, pd.DataFrame] = {}
    if raw is None or raw.empty:
        return results

    # ── Normalise to MultiIndex (field, ticker) ───────────────────────────────
    # Newer yfinance always returns MultiIndex; older returns flat for 1 ticker.
    if not isinstance(raw.columns, pd.MultiIndex):
        # Flat columns → single ticker, wrap into MultiIndex
        sym = symbols[0]
        available = [c for c in OHLCV if c in raw.columns]
        if not available:
            return results
        df = raw[available].copy()
        df.dropna(how="all", inplace=True)
        if not df.empty:
            df.index = pd.to_datetime(df.index, utc=True)
            df.index.name = "Date"
            results[sym] = df
        return results

    # MultiIndex: iterate per ticker
    top_level = raw.columns.get_level_values(0).unique().tolist()
    for sym in symbols:
        try:
            # yfinance ≥ 0.2.50 puts ticker at level 1; older puts it at level 0
            if sym in top_level:
                df = raw[sym].copy()        # (field) columns
            else:
                # Try transposing level order: columns are (field, ticker)
                df = raw.xs(sym, axis=1, level=1).copy()
            missing = [c for c in OHLCV if c not in df.columns]
            if missing:
                continue
            df = df[OHLCV].copy()
            df.dropna(how="all", inplace=True)
            if df.empty:
                continue
            df.index = pd.to_datetime(df.index, utc=True)
            df.index.name = "Date"
            results[sym] = df
        except (KeyError, TypeError):
            pass

    return results


def _batches(lst: list, size: int):
    """Yield successive sublists of length `size`."""
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


# ── Update logic ──────────────────────────────────────────────────────────────

def update_all_stocks(symbols: list[str],
                      force_full: bool = False) -> dict[str, pd.DataFrame]:
    """
    Incrementally update data for all symbols.

    Strategy
    --------
    1. Group symbols by the date they need new data from.
    2. Send one batch download per unique start-date group (at most a handful).
    3. Merge new bars with existing data, recompute indicators, save.

    This results in very few HTTP requests regardless of how many tickers
    you track (typically 1-3 calls when running daily).

    Returns
    -------
    dict {symbol: full DataFrame with indicators}
    """
    today = datetime.now(tz=timezone.utc).date()
    end_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    default_start = (today - timedelta(days=INITIAL_HISTORY_DAYS)).strftime("%Y-%m-%d")

    # ── Determine start date per symbol ──────────────────────────────────────
    # Group by start-date so we can batch together tickers that need the same range.
    start_date_groups: dict[str, list[str]] = defaultdict(list)

    skipped = []
    for sym in symbols:
        if not force_full:
            lu = last_updated(sym)
            if lu is not None and lu.date() >= today:
                skipped.append(sym)
                continue
            if lu is not None:
                start = (lu.date() + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                start = default_start
        else:
            start = default_start
        start_date_groups[start].append(sym)

    if skipped:
        logger.info(f"  {len(skipped)} tickers already up-to-date, skipping.")

    results: dict[str, pd.DataFrame] = {}

    # Load already-current tickers from disk
    for sym in skipped:
        df = _load(sym)
        if df is not None and not df.empty:
            results[sym] = df

    # ── Download, merge, recompute ────────────────────────────────────────────
    total_groups = len(start_date_groups)
    for g_idx, (start_str, group_syms) in enumerate(start_date_groups.items(), 1):
        logger.info(
            f"  Download group {g_idx}/{total_groups}: "
            f"{len(group_syms)} tickers from {start_str} …"
        )

        # Split into batches of BATCH_SIZE (avoid yfinance URL-length limits)
        for batch in _batches(group_syms, BATCH_SIZE):
            new_data = _yf_batch(batch, start=start_str, end=end_str)

            for sym in batch:
                new_bars = new_data.get(sym)
                existing = _load(sym) if not force_full else None

                if new_bars is None or new_bars.empty:
                    # Ticker returned no data (delisted / invalid) — use existing if any
                    if existing is not None and not existing.empty:
                        results[sym] = existing
                    # Do NOT log here; yfinance already printed the error
                    continue

                if existing is not None and not existing.empty:
                    base = existing[OHLCV]
                    combined = pd.concat(
                        [base, new_bars[~new_bars.index.isin(base.index)]]
                    ).sort_index()
                else:
                    combined = new_bars.sort_index()

                combined = _compute_indicators(combined)
                _save(sym, combined)
                results[sym] = combined

    logger.info(
        f"Update complete — {len(results)} tickers loaded "
        f"({len(start_date_groups)} download group(s), "
        f"~{sum(len(g) for g in start_date_groups.values())} new tickers fetched)."
    )
    return results


def get_stock_data(symbol: str) -> pd.DataFrame | None:
    """
    Return stored DataFrame for `symbol`.
    Downloads via batch if not yet cached (single-symbol batch = 1 call).
    Returns None if the ticker is unavailable (delisted etc.).
    """
    df = _load(symbol)
    if df is not None and not df.empty:
        return df
    # Not cached — try one download (result may be empty for delisted tickers)
    result = update_all_stocks([symbol])
    df = result.get(symbol)
    return df if (df is not None and not df.empty) else None


def get_latest_row(symbol: str) -> pd.Series | None:
    df = get_stock_data(symbol)
    return df.iloc[-1] if (df is not None and not df.empty) else None


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    syms = sys.argv[1:] if len(sys.argv) > 1 else ["AAPL", "NVDA", "XOM"]
    data = update_all_stocks(syms)
    cols = ["Close", "MA20", "MA50", "DIF", "DEA", "MACD_hist",
            "RSI14", "BB_upper", "BB_lower", "ATR14", "Volume"]
    for sym, df in data.items():
        print(f"\n{sym}  ({len(df)} rows)")
        print(df[cols].tail(3).round(4).to_string())
