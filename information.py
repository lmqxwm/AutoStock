"""
information.py
--------------
Pipeline
--------
1. Fetch recent financial news from Marketaux API (last 3-7 days)
2. Send article headlines + snippets to Google Gemini 2.0 Flash
   → LLM extracts company names + US stock tickers
3. Validate each ticker via Finnhub symbol search
4. Add newly discovered tickers to news_discovered.txt (gitignored)
5. Append a summary section to the daily alarm report

APIs used (all free-tier)
--------------------------
Marketaux  – financial news, entity-tagged articles
             https://www.marketaux.com  (100 req/day free)
Gemini     – Google AI LLM for text extraction
             https://aistudio.google.com/app/apikey  (1 500 req/day free)
Finnhub    – symbol search for ticker validation
             (uses existing key, no extra quota needed)
"""

from __future__ import annotations
import os, re, json, time, logging, textwrap, requests
from pathlib import Path
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# ── API keys (loaded from keys.txt via keys.py) ───────────────────────────────
from keys import FINNHUB_API_KEY, GEMINI_API_KEY, MARKETAUX_KEY, GROQ_API_KEY

# ── Config ────────────────────────────────────────────────────────────────────
MARKETAUX_BASE   = "https://api.marketaux.com/v1"
FINNHUB_BASE     = "https://finnhub.io/api/v1"
PROJECT_DIR           = Path(__file__).parent
NEWS_DISCOVERED_FILE  = PROJECT_DIR / "news_discovered.txt"   # gitignored
ALARMS_DIR            = PROJECT_DIR / "alarms"

NEWS_DAYS        = 5      # look back this many days
MAX_ARTICLES     = 60     # cap to stay within Marketaux free limit
ARTICLES_PER_PAGE = 50    # Marketaux max per request
LLM_BATCH_SIZE   = 25     # articles per Gemini call
FINNHUB_DELAY    = 0.6    # seconds between Finnhub search calls


# ── Marketaux news fetcher ────────────────────────────────────────────────────

def fetch_recent_news(days: int = NEWS_DAYS,
                      max_articles: int = MAX_ARTICLES) -> list[dict]:
    """
    Pull recent financial news from Marketaux.
    Filters to English articles that mention at least one equity entity.
    Returns list of {date, title, snippet, entities_raw}.
    """
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")
    articles: list[dict] = []
    seen: set[str] = set()

    pages_needed = -(-max_articles // ARTICLES_PER_PAGE)   # ceil division
    for page in range(1, pages_needed + 1):
        try:
            r = requests.get(
                f"{MARKETAUX_BASE}/news/all",
                params={
                    "filter_entities"   : "true",
                    "must_have_entities": "true",
                    "entity_types"      : "equity",
                    "language"          : "en",
                    "published_after"   : cutoff,
                    "limit"             : ARTICLES_PER_PAGE,
                    "page"              : page,
                    "api_token"         : MARKETAUX_KEY,
                },
                timeout=15,
            )
            r.raise_for_status()
            data = r.json().get("data", [])
            if not data:
                break
        except requests.RequestException as e:
            logger.warning(f"Marketaux page {page} error: {e}")
            break

        for item in data:
            uid = item.get("uuid", item.get("url", ""))
            if uid in seen:
                continue
            seen.add(uid)

            # Collect clean US-ticker entities Marketaux already tagged
            raw_entities: list[str] = []
            us_pat = re.compile(r'^[A-Z]{1,5}$')
            for ent in item.get("entities", []):
                sym = ent.get("symbol", "")
                if us_pat.match(sym):
                    raw_entities.append(sym)

            articles.append({
                "date"        : item.get("published_at", "")[:10],
                "title"       : item.get("title", ""),
                "snippet"     : (item.get("description") or item.get("snippet") or "")[:300],
                "entities_raw": raw_entities,
                "url"         : item.get("url", ""),
            })

        if len(articles) >= max_articles:
            break

    articles = articles[:max_articles]
    logger.info(f"Marketaux: fetched {len(articles)} articles (last {days} days).")
    return articles


# ── Gemini LLM extractor ──────────────────────────────────────────────────────

_SYSTEM_PROMPT = textwrap.dedent("""
You are a financial data extractor.
Given financial news headlines and snippets, find all US-listed companies that are
the SUBJECT of a significant corporate event: mergers/acquisitions, earnings results,
product launches, regulatory actions, partnerships, restructuring, IPO, leadership change.

Skip companies only mentioned as market context or price commentary.

Return ONLY a compact JSON array — no markdown, no extra text.
Format: [{"company": "Full Name", "ticker": "US_TICKER_OR_EMPTY"}]
If ticker is unknown, leave it as "". Only include US-listed equities.
""").strip()


def _articles_to_prompt(articles: list[dict]) -> str:
    lines = []
    for i, a in enumerate(articles, 1):
        line = f"{i}. [{a['date']}] {a['title']}"
        if a["snippet"]:
            line += f"\n   {a['snippet'][:200]}"
        lines.append(line)
    return "\n".join(lines)


def _call_gemini(articles: list[dict]) -> list[dict]:
    """
    Call Gemini via the new google-genai SDK.
    Tries gemini-2.0-flash first, falls back to gemini-1.5-flash on quota errors.
    """
    try:
        from google import genai
    except ImportError:
        logger.error("Run: pip3 install google-genai")
        return []

    client = genai.Client(api_key=GEMINI_API_KEY)
    results: list[dict] = []

    # Fallback chain: fastest → lightest (to survive quota limits)
    models_to_try = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-flash-lite-latest"]

    for i in range(0, len(articles), LLM_BATCH_SIZE):
        batch  = articles[i : i + LLM_BATCH_SIZE]
        prompt = _SYSTEM_PROMPT + "\n\nNews:\n" + _articles_to_prompt(batch)
        success = False
        for model_id in models_to_try:
            try:
                resp = client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                )
                text = resp.text.strip()
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    results.extend(parsed)
                success = True
                break
            except Exception as e:
                err_str = str(e)
                if "quota" in err_str.lower() or "429" in err_str:
                    logger.warning(f"Gemini quota hit on {model_id}, trying next model …")
                    continue
                logger.warning(f"Gemini batch {i//LLM_BATCH_SIZE+1} ({model_id}) error: {e}")
                break
        if not success:
            logger.warning(f"All Gemini models exhausted for batch {i//LLM_BATCH_SIZE+1}.")

    return results


def _regex_fallback(articles: list[dict]) -> list[dict]:
    """Extract $TICKER or (TICKER) patterns when no LLM is available."""
    skip = {"US","CEO","CFO","AI","IPO","GDP","FED","ECB","SEC","FDA","FTC",
            "DOJ","UK","EU","UN","WHO","ETF","NYSE","NASDAQ","AM","PM","EST",
            "GMT","Q1","Q2","Q3","Q4","EPS","PE","YTD","ATH","ATL","YOY"}
    found: set[str] = set()
    pats  = [re.compile(r'\(([A-Z]{1,5})\)'), re.compile(r'\$([A-Z]{1,5})\b')]
    for a in articles:
        for pat in pats:
            for m in pat.finditer(a["title"] + " " + a["snippet"]):
                t = m.group(1)
                if t not in skip:
                    found.add(t)
    return [{"company": "", "ticker": t} for t in found]


def _call_groq(articles: list[dict]) -> list[dict]:
    """
    Call Groq API (free tier) as a fallback when Gemini is unavailable.
    Uses llama-3.3-70b-versatile — fast, free, and handles structured output well.
    """
    try:
        from groq import Groq
    except ImportError:
        logger.error("Run: pip install groq")
        return []

    client = Groq(api_key=GROQ_API_KEY)
    results: list[dict] = []
    models_to_try = ["llama-3.3-70b-versatile", "llama3-70b-8192", "mixtral-8x7b-32768"]

    for i in range(0, len(articles), LLM_BATCH_SIZE):
        batch  = articles[i : i + LLM_BATCH_SIZE]
        prompt = _articles_to_prompt(batch)
        success = False
        for model_id in models_to_try:
            try:
                resp = client.chat.completions.create(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user",   "content": "News:\n" + prompt},
                    ],
                    temperature=0,
                )
                text = resp.choices[0].message.content.strip()
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    results.extend(parsed)
                success = True
                logger.info(f"Groq batch {i//LLM_BATCH_SIZE+1} OK ({model_id}).")
                break
            except Exception as e:
                err_str = str(e)
                if "rate_limit" in err_str.lower() or "429" in err_str:
                    logger.warning(f"Groq quota hit on {model_id}, trying next …")
                    continue
                logger.warning(f"Groq batch {i//LLM_BATCH_SIZE+1} ({model_id}) error: {e}")
                break
        if not success:
            logger.warning(f"All Groq models exhausted for batch {i//LLM_BATCH_SIZE+1}.")

    return results


# ── Finnhub news fetcher ──────────────────────────────────────────────────────

def fetch_finnhub_news(symbols: list[str], days: int = 7) -> dict[str, dict]:
    """
    Fetch the most recent news headline for each symbol via Finnhub /company-news.
    Used to fill in news for alarm-triggered tickers not covered by Marketaux articles.
    Returns {symbol: {title, snippet, url}}.
    """
    from_date = (datetime.now(tz=timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    to_date   = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    result: dict[str, dict] = {}

    for sym in symbols:
        time.sleep(FINNHUB_DELAY)
        try:
            r = requests.get(
                f"{FINNHUB_BASE}/company-news",
                params={"symbol": sym, "from": from_date, "to": to_date,
                        "token": FINNHUB_API_KEY},
                timeout=10,
            )
            r.raise_for_status()
            articles = r.json()
            if articles:
                art = articles[0]   # most recent first
                result[sym] = {
                    "title"  : art.get("headline", "").strip(),
                    "snippet": art.get("summary",  "")[:300].strip(),
                    "url"    : art.get("url",       "").strip(),
                }
        except Exception as e:
            logger.debug(f"Finnhub news for {sym}: {e}")

    logger.info(f"Finnhub news: fetched headlines for {len(result)}/{len(symbols)} tickers.")
    return result


# ── Finnhub ticker validator ──────────────────────────────────────────────────

def _finnhub_search(query: str) -> str | None:
    time.sleep(FINNHUB_DELAY)
    try:
        r = requests.get(f"{FINNHUB_BASE}/search",
                         params={"q": query, "token": FINNHUB_API_KEY},
                         timeout=10)
        r.raise_for_status()
        for res in r.json().get("result", []):
            if res.get("type") == "Common Stock" and "." not in res.get("symbol", ""):
                return res["symbol"]
    except requests.RequestException:
        pass
    return None


def validate_candidates(raw: list[dict],
                        existing: set[str]) -> list[dict]:
    """
    Validate each {company, ticker} pair via Finnhub symbol search.
    Merges direct-from-Marketaux tickers (already pre-labeled) and
    LLM-extracted candidates.
    Returns validated list of {company, ticker} not already in universe.
    """
    out: list[dict] = []
    seen: set[str] = set()
    us_pat = re.compile(r'^[A-Z]{1,5}$')

    for item in raw:
        company = (item.get("company") or "").strip()
        ticker  = (item.get("ticker")  or "").strip().upper()

        if ticker and ticker in existing | seen:
            continue

        # Validate ticker via Finnhub search
        if ticker and us_pat.match(ticker):
            confirmed = _finnhub_search(ticker)
            if confirmed and confirmed not in existing and confirmed not in seen:
                out.append({"company": company or ticker, "ticker": confirmed})
                seen.add(confirmed)
                continue

        # No ticker — try company name
        if company and len(company) > 3:
            confirmed = _finnhub_search(company)
            if confirmed and confirmed not in existing and confirmed not in seen:
                out.append({"company": company, "ticker": confirmed})
                seen.add(confirmed)

    return out


# ── news_discovered.txt reader / writer ───────────────────────────────────────

def _read_news_discovered() -> list[str]:
    """Return tickers from news_discovered.txt; empty list if file absent."""
    if not NEWS_DISCOVERED_FILE.exists():
        return []
    lines = [ln.strip() for ln in NEWS_DISCOVERED_FILE.read_text().splitlines()]
    return [ln for ln in lines if ln and not ln.startswith("#")]


def _write_news_discovered(tickers: list[str]) -> None:
    """Overwrite news_discovered.txt with one ticker per line."""
    NEWS_DISCOVERED_FILE.write_text("\n".join(tickers) + ("\n" if tickers else ""))


def update_tickers_py(validated: list[dict]) -> list[str]:
    existing = _read_news_discovered()
    exist_set = set(existing)
    added: list[str] = []
    for item in validated:
        t = item["ticker"]
        if t not in exist_set:
            existing.append(t)
            exist_set.add(t)
            added.append(t)
    if added:
        _write_news_discovered(existing)
        logger.info(f"Added {len(added)} ticker(s) to NEWS_DISCOVERED: {added}")
    else:
        logger.info("No new tickers to add.")
    return added


# ── Alarm report writer ───────────────────────────────────────────────────────

def append_news_to_alarm(alarm_path: Path, added_items: list[dict]) -> None:
    ALARMS_DIR.mkdir(parents=True, exist_ok=True)
    with open(alarm_path, "a", encoding="utf-8") as f:
        f.write("\n" + "=" * 60 + "\n")
        f.write("NEWS-DISCOVERED TICKERS\n")
        f.write("=" * 60 + "\n")
        if not added_items:
            f.write("  No new tickers discovered from recent news.\n")
        else:
            for item in added_items:
                f.write(f"  + {item['ticker']:8s}  {item['company']}\n")
        f.write("\n")


# ── Main entry point ──────────────────────────────────────────────────────────

def build_ticker_headlines(articles: list[dict]) -> dict[str, dict]:
    """
    Build a mapping of ticker → {title, snippet, url} from fetched articles.
    Uses Marketaux entity tags so no extra API call is needed.
    Only keeps the first (most recent) article per ticker.
    """
    ticker_to_info: dict[str, dict] = {}
    for art in articles:
        title = art.get("title", "").strip()
        if not title:
            continue
        for sym in art.get("entities_raw", []):
            if sym not in ticker_to_info:
                ticker_to_info[sym] = {
                    "title"  : title,
                    "snippet": art.get("snippet", "").strip(),
                    "url"    : art.get("url", "").strip(),
                }
    return ticker_to_info


def _summarize_news(items: list[dict]) -> dict[str, str]:
    """
    Given [{ticker, title, snippet}, ...], ask the LLM to write one sentence
    per ticker explaining why the news matters to the stock.
    Tries Gemini first, falls back to Groq.
    Returns {ticker: summary_sentence}.
    """
    if not items:
        return {}

    system = (
        "You are a financial analyst. For each stock news item below, write ONE concise "
        "sentence explaining the business or price impact on that specific company. "
        "Return ONLY compact JSON — no markdown, no extra text.\n"
        'Format: [{"ticker": "XXX", "summary": "one sentence here"}]'
    )
    lines = []
    for it in items:
        lines.append(f"TICKER: {it['ticker']}")
        lines.append(f"Title: {it['title']}")
        if it.get("snippet"):
            lines.append(f"Snippet: {it['snippet'][:250]}")
        lines.append("")
    user_content = "News items:\n" + "\n".join(lines)

    def _parse(text: str) -> dict[str, str]:
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```$", "", text)
        parsed = json.loads(text)
        return {d["ticker"]: d["summary"]
                for d in parsed
                if isinstance(d, dict) and "ticker" in d and "summary" in d}

    # Try Gemini
    if GEMINI_API_KEY and GEMINI_API_KEY.startswith("AIzaSy"):
        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=system + "\n\n" + user_content,
            )
            return _parse(resp.text)
        except Exception as e:
            logger.warning(f"Gemini summary error: {e}")

    # Try Groq
    if GROQ_API_KEY:
        try:
            from groq import Groq
            client = Groq(api_key=GROQ_API_KEY)
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user_content},
                ],
                temperature=0,
            )
            return _parse(resp.choices[0].message.content)
        except Exception as e:
            logger.warning(f"Groq summary error: {e}")

    return {}


def run_news_discovery(alarm_path: Path | None = None,
                       days: int = NEWS_DAYS) -> tuple[list[str], dict[str, str]]:
    """
    Full pipeline.
    Returns (newly_added_tickers, ticker_to_headline).
    ticker_to_headline maps every ticker mentioned in recent news → its latest headline.
    """
    from tickers import get_tickers
    existing_all = set(get_tickers(include_etfs=True))

    # 1. Fetch news
    articles = fetch_recent_news(days=days)
    if not articles:
        logger.warning("No recent news articles returned from Marketaux.")
        return [], {}

    # 2. Collect Marketaux pre-labeled entity tickers (free, no LLM needed)
    entity_candidates: list[dict] = []
    for art in articles:
        for sym in art.get("entities_raw", []):
            entity_candidates.append({"company": "", "ticker": sym})

    # 3. LLM extraction from article text
    # Warn once if Gemini key looks wrong (OAuth token instead of API key)
    if GEMINI_API_KEY and not GEMINI_API_KEY.startswith("AIzaSy"):
        logger.warning(
            "GEMINI_API_KEY looks wrong — real Gemini API keys start with 'AIzaSy'. "
            "Get one at: https://aistudio.google.com/app/apikey"
        )

    llm_candidates: list[dict] = []
    llm_source = "none"

    if GEMINI_API_KEY and GEMINI_API_KEY.startswith("AIzaSy"):
        cands = _call_gemini(articles)
        if cands:
            llm_candidates = cands
            llm_source = "Gemini"

    if not llm_candidates and GROQ_API_KEY:
        logger.info("Trying Groq for LLM extraction …")
        cands = _call_groq(articles)
        if cands:
            llm_candidates = cands
            llm_source = "Groq"

    if not llm_candidates:
        logger.info("No LLM available — using regex fallback.")
        llm_candidates = _regex_fallback(articles)
        llm_source = "regex"

    logger.info(f"LLM extraction ({llm_source}): {len(llm_candidates)} candidates.")

    # 4. Merge & deduplicate candidates
    all_candidates = entity_candidates + llm_candidates
    logger.info(f"Total raw candidates: {len(all_candidates)} "
                f"({len(entity_candidates)} from entities, "
                f"{len(llm_candidates)} from LLM).")

    # 5. Validate via Finnhub
    validated = validate_candidates(all_candidates, existing_all)
    logger.info(f"Validated: {len(validated)} new tickers.")

    # 6. Update tickers.py
    added_syms = update_tickers_py(validated)
    added_items = [v for v in validated if v["ticker"] in added_syms]

    # 7. Build full ticker → {title, snippet, url} map from Marketaux entity tags
    ticker_info = build_ticker_headlines(articles)

    # 8. Top-up: newly discovered tickers that weren't entity-tagged by Marketaux
    #    (found via LLM or regex) have no entry in ticker_info — fetch from Finnhub
    if added_syms:
        missing = [t for t in added_syms if not ticker_info.get(t, {}).get("title")]
        if missing:
            logger.info(f"Fetching Finnhub news for {len(missing)} ticker(s) with no Marketaux headline …")
            finnhub_news = fetch_finnhub_news(missing)
            ticker_info.update(finnhub_news)

    # 9. LLM one-sentence summaries for all newly discovered tickers
    if added_syms:
        summary_inputs = [
            {"ticker": t,
             "title"  : ticker_info.get(t, {}).get("title", ""),
             "snippet": ticker_info.get(t, {}).get("snippet", "")}
            for t in added_syms
            if ticker_info.get(t, {}).get("title")
        ]
        summaries = _summarize_news(summary_inputs)
        for t, s in summaries.items():
            if t in ticker_info:
                ticker_info[t]["summary"] = s
        logger.info(f"LLM summaries generated for {len(summaries)} new ticker(s).")

    # 9. Write to alarm report
    if alarm_path:
        append_news_to_alarm(alarm_path, added_items)

    return added_syms, ticker_info


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    added, _ = run_news_discovery()
    print(f"\n{'='*40}")
    print(f"Newly added to NEWS_DISCOVERED ({len(added)}):")
    for t in added:
        print(f"  {t}")
