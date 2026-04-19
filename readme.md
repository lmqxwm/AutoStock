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

Four services are used. All have free tiers sufficient for daily use.

| Service | Used for | Free limit | Sign up |
|---|---|---|---|
| **Finnhub** | Ticker validation | 60 req/min | [finnhub.io](https://finnhub.io) |
| **Marketaux** | Financial news articles | 100 req/day | [marketaux.com](https://www.marketaux.com) |
| **Google Gemini** | LLM extraction from news | 1 500 req/day | [aistudio.google.com](https://aistudio.google.com/app/apikey) — key starts with `AIzaSy` |
| **Groq** | LLM fallback if Gemini unavailable | ~14 400 req/day free | [console.groq.com](https://console.groq.com) |

Copy `keys_template.txt` to `keys.txt` and fill in your keys. `keys.txt` is gitignored and never committed.

```bash
cp keys_template.txt keys.txt
# then edit keys.txt with your actual keys
```

Alternatively, set environment variables (takes priority over `keys.txt`):

```bash
export FINNHUB_API_KEY="your_key"
export MARKETAUX_API_KEY="your_key"
export GEMINI_API_KEY="your_key"   # must start with AIzaSy
export GROQ_API_KEY="your_key"
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

### Understanding Stop, Trail, and Target

Every signal in the alarm report includes one or two of these exit instructions:

| Term | What it means | Typical position relative to price |
|---|---|---|
| **Stop** | Hard cut-loss level. If price touches this, sell immediately — no debate. Protects you when the trade goes against you right away. | **Below** entry price |
| **Trail** | A dynamic hold condition. Stay in the trade *as long as* price remains above this level. As price rises, MA20 rises with it, so the trail level rises too — locking in more profit over time. Exit when price closes below the trail. | **Below** current price — intentionally, because you're riding a trend upward |
| **Target** | A fixed profit-taking price. Used in mean-reversion strategies where you expect price to snap back to a specific level (e.g. Bollinger mid-band). | **Above** current price |

**Practical example using Walmart (WMT):**
```
WMT entry at $95.00 (signal triggered)
ATR14       = $2.00

Stop        = $92.00  (entry − 1.5×ATR)  ← sell here if wrong from day one
Trail level = $91.50  (today's MA20)     ← if WMT runs to $110 and MA20 reaches $106,
                                            you only exit when price drops back to $106
                                            — capturing most of the $15 gain
```
Stop and trail work together: the Stop covers the immediate downside risk; the Trail locks in gains once the trade moves in your favour.

---

### 1 · MA Pullback
Trend-following entry on a pullback to the 20-day MA.

| | Condition |
|---|---|
| Setup | price > MA50 AND MA50 slope positive (net rising last 5 bars) |
| Entry | low touches MA20 AND bullish candle AND (MACD histogram rising OR RSI > 40) AND volume ≥ 1.2× avg |
| Stop | entry − 1.5 × ATR14 |
| Trail | hold while price > MA20; exit if daily close drops below MA20 |
| Avoid | flat MA50 · price near MA200 · low volume |

### 2 · Bollinger + RSI Mean Reversion
Counter-trend bounce in a sideways market.

| | Condition |
|---|---|
| Setup | MA50 flat — range < 5% over 10 bars |
| Entry | low touches lower BB AND RSI < 30 AND volume decreasing AND close back inside band |
| Stop | lower BB − 1 × ATR14 |
| Target | BB middle (MA20) for partial exit; BB upper for full exit |

### 3 · Trend + Pullback + Momentum
Simplified trend-continuation entry.

| | Condition |
|---|---|
| Setup | price > MA50 |
| Entry | low ≤ MA20 × 1.01 AND MACD histogram increasing AND volume > 20-day average |
| Stop | entry − 1.5 × ATR14 |
| Trail | hold while price > MA20; exit if daily close drops below MA20 |

### 4 · Golden / Death Cross
MA50 / MA200 crossover system.

| Signal | Condition |
|---|---|
| **BUY** (triggered = True) | MA50 crosses **above** MA200 AND MA50 rising AND (volume up OR DIF > 0) |
| **SELL WARNING** (triggered = True) | MA50 crosses **below** MA200 — exit or avoid longs |

| | Condition |
|---|---|
| Stop (Golden Cross) | 2% below MA200 at entry |
| Trail | hold while MA50 > MA200; exit when death cross occurs |

### 5 · MACD Trend
DIF / DEA crossover above the zero line.

| | Condition |
|---|---|
| Setup | price > MA50 |
| Entry | DIF crosses above DEA AND both DIF > 0 AND DEA > 0 |
| Stop | close below MA20 |
| Trail | hold while DIF > DEA; exit when DIF crosses back below DEA |

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
Generated  : 2026-04-17 20:10 ET
Latest data: 2026-04-17 16:00 ET
Universe   : 332 tickers
============================================================
SIGNALS
============================================================

[MA Pullback]
  WMT      (data thru 2026-04-17 16:00 ET)
  [MA Pullback] Price=95.40 pulled back to MA20=91.50, bullish close,
  RSI=48.6, volume 42M ≥ 1.2×avg.
  Stop: 92.10  |  Trail: hold while price > MA20=91.50, exit if close below
  News: Walmart beats Q1 estimates on strong grocery and e-commerce growth

[Golden/Death Cross]
  AVGO     (data thru 2026-04-17 16:00 ET)
  [Golden Cross BUY] MA50=333.00 crossed above MA200=332.07. MA50 rising. Volume up.
  Stop: 325.43  |  Trail: hold while MA50 (333.00) > MA200 (332.07), exit on death cross

[MACD Trend]
  BRZE     (data thru 2026-04-17 16:00 ET)
  [MACD Trend] Price=21.90 above MA50=20.40. DIF=0.47 crossed above DEA=0.45, both positive.
  Stop: 21.68 (MA20)  |  Trail: hold while DIF (0.47) > DEA (0.45), exit on crossover

============================================================
NEWS-DISCOVERED TICKERS
============================================================
  + RDDT
    Title  : Reddit Partners with OpenAI to Provide Real-Time Data Access
    Summary: Reddit secured a data licensing deal with OpenAI, boosting revenue
             diversification and validating its AI content strategy.
    Link   : https://www.marketaux.com/article/...
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
CONSUMER = [
    ...,
    "WMT",   # Walmart
]
```

**Add tickers for one session only** — CLI flag or notebook cell:
```bash
python run_daily.py --add WMT TGT COST
```

**Tune a strategy** — edit the relevant function in `strategy.py`. Each function is independent and self-contained. The aggregate `check_all_strategies()` calls all of them.

**Change lookback period** — edit `INITIAL_HISTORY_DAYS` in `get_stock_data.py` (default: 730 days / 2 years).
