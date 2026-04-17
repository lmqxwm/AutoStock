# AutoStock

Automated daily stock screening system. Pulls price data for ~330 US equities, computes technical indicators, runs five trading strategies, discovers new tickers from financial news, and saves every signal to a timestamped report.

## Main developer: Aurora

---

## What it does, end-to-end

```
Financial news (Marketaux)
        ↓
  Google Gemini 2.0 Flash           ← extracts company names + tickers from headlines
        ↓
  Finnhub symbol search             ← validates each ticker is a real US stock
        ↓
  tickers.py  NEWS_DISCOVERED       ← persists new tickers across runs
        ↓
  yfinance batch download           ← OHLCV history, incremental updates (~1 HTTP call/day)
        ↓
  Technical indicators              ← MA, MACD, RSI, Bollinger Bands, ATR
        ↓
  5 trading strategy functions      ← each returns True/False + description
        ↓
  alarms/YYYY-MM-DD_HH-MM.txt      ← signal report saved every run
```

---

## File structure

```
AutoStock/
├── tickers.py          Master ticker list (~330 stocks), grouped by sector.
│                       NEWS_DISCOVERED list is auto-updated by information.py.
│
├── information.py      News → LLM → validate → update tickers.py
│                       Sources: Marketaux (news) + Gemini (extraction) + Finnhub (validation)
│
├── get_stock_data.py   Batch OHLCV download via yfinance + indicator computation.
│                       Stores per-ticker Parquet files in data/ for incremental updates.
│
├── strategy.py         Five strategy functions. Each: (df) → (bool, description).
│
├── daily_run.ipynb     Jupyter notebook — full interactive workflow.
│
├── run_daily.py        CLI runner — same logic as the notebook, no Jupyter needed.
│
├── data/               Per-ticker Parquet cache (auto-created).
├── alarms/             Timestamped signal reports (auto-created).
└── requirements.txt
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. API keys

Three services are used. All have free tiers sufficient for daily use.

| Service | Used for | Free limit | Sign up |
|---|---|---|---|
| **Finnhub** | Ticker validation | 60 req/min | [finnhub.io](https://finnhub.io) |
| **Marketaux** | Financial news articles | 100 req/day | [marketaux.com](https://www.marketaux.com) |
| **Google Gemini** | LLM extraction from news | 1 500 req/day | [aistudio.google.com](https://aistudio.google.com/app/apikey) |

Keys are already embedded in `information.py`. To override, set environment variables:

```bash
export FINNHUB_API_KEY="your_key"
export MARKETAUX_API_KEY="your_key"
export GEMINI_API_KEY="your_key"
```

---

## How to run

### Option A — Jupyter notebook (interactive)

```bash
jupyter notebook daily_run.ipynb
```

Run cells top to bottom. The `manually_added` / `manually_removed` cell lets you adjust
the ticker universe for that session without touching any file.

### Option B — Command line (recommended for daily automation)

```bash
# Normal daily run (news discovery + data update + strategies)
python run_daily.py

# Skip news discovery (faster, fewer API calls)
python run_daily.py --no-news

# Add or remove tickers for this run only
python run_daily.py --add PLTR ARM IONQ --remove LCID

# Print full indicator table for specific tickers after running
python run_daily.py --inspect NVDA AVGO AAPL

# Re-download full 2-year history for all tickers
python run_daily.py --force-download
```

### Option C — Schedule with cron (automatic daily run)

```bash
# Open crontab
crontab -e

# Run every weekday at 9 PM — after US market close and data settlement
0 21 * * 1-5 cd /path/to/AutoStock && python run_daily.py --no-news >> logs/cron.log 2>&1
```

---

## Ticker universe (`tickers.py`)

Stocks are organised into named lists by sector. Edit any list freely.

| List | Coverage |
|---|---|
| `MEGA_CAP_TECH` | AAPL, MSFT, NVDA, GOOGL, AMZN, META … |
| `SEMICONDUCTORS` | AMD, INTC, QCOM, MU, AMAT, ASML … |
| `CLOUD_INFRA` | NET, ANET, DDOG, EQIX, DLR … |
| `SAAS` | NOW, WDAY, SNOW, CRWD, PANW, OKTA … |
| `FINTECH` | V, MA, PYPL, COIN, HOOD … |
| `INTERNET` | NFLX, UBER, ABNB, BKNG, SHOP, BABA … |
| `HARDWARE_STORAGE` | STX, WDC, NTAP, DELL, HPE … |
| `ENERGY_OIL_GAS` | XOM, CVX, COP, SLB, HAL … |
| `ENERGY_CLEAN` | NEE, ENPH, FSLR, RIVN, NIO … |
| `UTILITIES` | DUK, SO, NEE, AEP … |
| `HEALTHCARE` | JNJ, LLY, ABBV, MRNA, ISRG … |
| `FINANCIALS` | JPM, GS, BRK-B, BLK … |
| `CONSUMER` | WMT, COST, NKE, SBUX, AMZN … |
| `INDUSTRIALS` | BA, LMT, CAT, UPS … |
| `NEWS_DISCOVERED` | Auto-managed by `information.py` |

`get_tickers(include_etfs=False)` returns the full deduplicated list (~330 stocks).  
`get_tickers(include_etfs=True)` also includes SPY, QQQ, GLD, TLT, etc.

---

## Technical indicators

Computed in `get_stock_data.py` on the full OHLCV history and stored in each Parquet file.

| Indicator | Columns in DataFrame |
|---|---|
| Moving averages | `MA5` `MA10` `MA20` `MA50` `MA100` `MA200` |
| MACD | `DIF` (EMA12−EMA26) · `DEA` (EMA9 of DIF) · `MACD_hist` (DIF−DEA) |
| RSI | `RSI14` |
| Bollinger Bands | `BB_upper` · `BB_middle` (=MA20) · `BB_lower` · `BB_width` |
| Volume MA | `Volume_MA20` |
| Average True Range | `ATR14` |

---

## Trading strategies (`strategy.py`)

Each function signature: `strategy(df: pd.DataFrame) → (triggered: bool, description: str)`

<!-- comments -->
### 1 · MA Pullback
Trend-following entry on a pullback to the 20-day MA.

| | Condition |
|---|---|
| Setup | price > MA50 AND MA50 slope positive (net rising last 5 bars) |
| Entry | low touches MA20 AND bullish candle AND (MACD histogram rising OR RSI > 40) AND volume ≥ 1.2× avg |
| Stop | entry − 1.5 × ATR14 |
| Exit | close below MA20, or trail stop |
| Avoid | flat MA50 · price near MA200 · low volume |

### 2 · Bollinger + RSI Mean Reversion
Counter-trend bounce in a sideways market.

| | Condition |
|---|---|
| Setup | MA50 flat — range < 5% over 10 bars |
| Entry | low touches lower BB AND RSI < 30 AND volume decreasing AND close back inside band |
| Stop | lower band − 1 × ATR14 |
| Target | BB middle (MA20) or upper band |

### 3 · Trend + Pullback + Momentum
Simplified trend-continuation entry.

| | Condition |
|---|---|
| Setup | price > MA50 |
| Entry | low ≤ MA20 × 1.01 AND MACD histogram increasing AND volume > 20-day average |

### 4 · Golden / Death Cross
MA50 / MA200 crossover system.

| Signal | Condition |
|---|---|
| Buy (triggered = True) | MA50 crosses **above** MA200 AND MA50 rising AND (volume up OR DIF > 0) |
| Bearish alert (triggered = False) | MA50 crosses **below** MA200 |

### 5 · MACD Trend
DIF / DEA crossover above the zero line.

| | Condition |
|---|---|
| Setup | price > MA50 |
| Entry | DIF crosses above DEA AND both DIF > 0 AND DEA > 0 |
| Stop | close below MA20 |
| Exit | DIF crosses below DEA |

Example: 

Entry at $100
Stop  = $92   (entry − 1.5×ATR)   ← price drops here → sell immediately, no debate
Exit  = price closes below MA20    ← trend weakening → sell even if still profitable

---

## News discovery (`information.py`)

Runs automatically at the start of each session. Pipeline:

1. **Marketaux** fetches up to 60 recent articles (last 5 days) tagged with equity entities
2. **Google Gemini 2.0 Flash** reads headlines + snippets and extracts company names + tickers — focused on corporate actions (M&A, earnings, product launches, regulatory events)
3. **Finnhub symbol search** validates each extracted name/ticker against real US stock symbols
4. Newly confirmed tickers are appended to `NEWS_DISCOVERED` in `tickers.py`
5. A summary is written to the daily alarm file

Run standalone to discover tickers without running the full strategy scan:

```bash
python information.py
```

---

## Alarm reports

Every run writes `alarms/YYYY-MM-DD_HH-MM.txt`:

```
AutoStock Daily Report
Generated  : 2026-04-17 20:10 UTC
Latest data: 2026-04-17
Universe   : 332 tickers
============================================================
SIGNALS
============================================================

[MA Pullback]
  NFLX     (data thru 2026-04-17)
  Price=97.31 pulled back to MA20=98.15, bullish close,
  RSI=48.6, volume 124M ≥ 1.2×avg. Stop=92.09.

[Golden/Death Cross]
  AVGO     (data thru 2026-04-17)
  MA50=333.00 crossed above MA200=332.07. MA50 rising. Volume up.

[MACD Trend]
  BRZE     (data thru 2026-04-17)
  DIF=0.47 crossed above DEA=0.45, both positive. Stop: MA20=21.68.

============================================================
NEWS-DISCOVERED TICKERS
============================================================
  + APPN     Appian Corporation
  + KURA     Kura Oncology
```

---

## Data storage & incremental updates

Price history lives in `data/` as one Parquet file per ticker (e.g. `data/AAPL.parquet`).

| Scenario | What happens |
|---|---|
| First run | Downloads 2 years of OHLCV in ~4 batch HTTP calls (100 tickers each) |
| Daily run | Fetches only bars since last stored date — usually **1 HTTP call** for all 330+ tickers |
| Force refresh | `python run_daily.py --force-download` or `rm data/*.parquet` |

---

## Customisation

**Add tickers permanently** — edit the relevant list in `tickers.py`:
```python
SAAS = [
    ...,
    "PLTR",   # Palantir
]
```

**Add tickers for one session only** — CLI flag or notebook cell:
```bash
python run_daily.py --add PLTR ARM IONQ
```

**Tune a strategy** — edit the relevant function in `strategy.py`. Each function is independent and self-contained. The aggregate `check_all_strategies()` calls all of them.

**Change lookback period** — edit `INITIAL_HISTORY_DAYS` in `get_stock_data.py` (default: 730 days / 2 years).
