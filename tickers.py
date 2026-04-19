"""
tickers.py
----------
Master list of stocks to screen.
Edit any section freely — add/remove tickers as you like.
`get_tickers()` returns the full deduplicated list.
"""

# ── Mega-cap Tech ─────────────────────────────────────────────────────────────
MEGA_CAP_TECH = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA",
    "AVGO", "ORCL", "ADBE", "CRM", "IBM", "SAP", "INTU",
]

# ── Semiconductors ────────────────────────────────────────────────────────────
SEMICONDUCTORS = [
    "AMD", "INTC", "QCOM", "TXN", "MU", "AMAT", "LRCX", "KLAC",
    "MRVL", "MPWR", "NXPI", "MCHP", "ON", "SWKS", "QRVO", "ADI",
    "ASML", "TSM", "UMC", "SLAB", "SMCI", "WOLF", "MTSI", "SITM",
    "ALGM", "ACLS", "ONTO", "FORM", "KLIC", "ICHR", "UCTT",
]

# ── Cloud Infrastructure & Hyperscalers ───────────────────────────────────────
CLOUD_INFRA = [
    "NET", "ANET", "FFIV", "FSLY", "AKAM", "DDOG",
    "DT", "ESTC", "VNET", "GDS",
    "VRT", "EQIX", "DLR", "AMT", "CCI", "SBAC",  # data center REITs
    # Removed: JNPR (acquired by HPE 2024), NEWR (went private 2024),
    #          SUMO (went private 2023), SPLK (acquired by Cisco 2024)
]

# ── SaaS / Enterprise Software ────────────────────────────────────────────────
SAAS = [
    "NOW", "WDAY", "SNOW", "CRWD", "ZS", "PANW", "OKTA", "MDB",
    "TEAM", "VEEV", "ZM", "DOCU", "BILL", "HUBS", "TWLO",
    "GTLB", "CFLT", "S", "BOX", "PCTY", "PAYC",
    "APPF", "BRZE", "NCNO",
    "RNG", "FIVN", "NICE", "TTWO", "EA",
    "U", "RBLX", "DAVA",
    # Removed: ATLASSIAN (use TEAM), ATVI (acquired by MSFT 2023),
    #          SMAR (went private 2024), COUP (went private 2023),
    #          ALTR (invalid), SAMSF (OTC/invalid)
]

# ── Fintech / Payments ────────────────────────────────────────────────────────
FINTECH = [
    "V", "MA", "PYPL", "XYZ", "FIS", "FISV", "GPN", "AXP",
    "ADYEY", "AFRM", "UPST", "SOFI", "COIN", "HOOD",
    "LPLA",
    # Removed: SQ → renamed to XYZ (Block Inc 2024), SNSXX (not a stock)
]

# ── Internet / Consumer Tech ──────────────────────────────────────────────────
INTERNET = [
    "NFLX", "SPOT", "SNAP", "PINS", "UBER", "LYFT", "ABNB",
    "DASH", "MTCH", "IAC", "YELP", "EXPE", "BKNG",
    "ETSY", "EBAY", "SHOP", "MELI", "SE", "GRAB",
    "BIDU", "JD", "PDD", "BABA", "TCOM",
    # Removed: TRIP (very low volume)
]

# ── Hardware / Storage / Devices ──────────────────────────────────────────────
HARDWARE_STORAGE = [
    "STX", "WDC", "NTAP", "PSTG", "NTNX", "DELL", "HPQ", "HPE",
    "CSCO", "ANET", "ZBRA", "PLAB", "NDSN",
    "ARLO", "SONO",
    # Removed: JNPR (acquired by HPE 2024), HEAR (very small cap)
]

# ── Communications / Telecom ──────────────────────────────────────────────────
TELECOM = [
    "T", "VZ", "TMUS", "CMCSA", "CHTR",
    "LUMN", "ATEX",
    # Removed: DISH (merged/delisted 2024), CTL (renamed to LUMN, duplicate)
]

# ── Energy — Oil, Gas, Refining ───────────────────────────────────────────────
ENERGY_OIL_GAS = [
    "XOM", "CVX", "COP", "EOG", "DVN", "FANG", "MPC",
    "VLO", "PSX", "OXY", "SLB", "HAL", "BKR",
    "APA", "CTRA", "MTDR", "SM",
    "CNQ", "SU", "CVE", "IMO",
    "TRP", "ENB", "KMI", "WMB", "OKE", "EPD", "ET",  # midstream
    # Removed: PXD (acquired by XOM 2024), HES (acquired by CVX 2024),
    #          MRO (acquired by COP 2024), PDCE (acquired by CVX 2023),
    #          ROCC (small-cap, delisted)
]

# ── Energy — Renewables & Clean Tech ─────────────────────────────────────────
ENERGY_CLEAN = [
    "NEE", "ENPH", "FSLR", "RUN", "SEDG", "BE", "PLUG", "BLNK",
    "CHPT", "EVGO", "RIVN", "LCID", "NIO", "XPEV", "LI",
    "ARRY", "SHLS", "MAXN", "CSIQ", "JKS",
    "STEM", "FLUX", "OPAL", "GEVO", "AMRC",
    # Removed: NOVA (Sunnova - went bankrupt 2024)
]

# ── Utilities ─────────────────────────────────────────────────────────────────
UTILITIES = [
    "DUK", "SO", "D", "AEP", "EXC", "SRE", "PEG", "ED",
    "ES", "XEL", "WEC", "DTE", "PPL", "AES", "NRG",
]

# ── Healthcare & Biotech ──────────────────────────────────────────────────────
HEALTHCARE = [
    "JNJ", "PFE", "MRK", "ABBV", "LLY", "BMY", "AMGN", "GILD",
    "BIIB", "REGN", "VRTX", "MRNA", "BNTX",  # SGEN acquired by Pfizer 2023
    "ISRG", "MDT", "ABT", "SYK", "ZBH", "BSX", "EW",
    "TMO", "DHR", "A", "ILMN", "EXAS", "NTRA",
    "CVS", "UNH", "HUM", "CI", "CNC", "MOH",
]

# ── Financials ────────────────────────────────────────────────────────────────
FINANCIALS = [
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BK", "STT",
    "BRK-B", "AIG", "MET", "PRU", "AFL", "ALL", "TRV",  # BRK-B is yfinance format
    "SCHW", "IBKR", "RJF",
    "BLK", "IVZ", "TROW", "BEN", "AMG",
    "ICE", "CME", "CBOE", "NDAQ",
]

# ── Consumer & Retail ─────────────────────────────────────────────────────────
CONSUMER = [
    "AMZN", "WMT", "COST", "TGT", "HD", "LOW", "NKE", "SBUX",
    "MCD", "CMG", "DPZ", "YUM", "QSR",
    "PG", "KO", "PEP", "CL", "EL", "ULTA",
    "LULU", "GAP", "AEO", "ANF",  # Gap Inc trades as GAP since 2024
]

# ── Industrials / Defense ─────────────────────────────────────────────────────
INDUSTRIALS = [
    "BA", "LMT", "RTX", "NOC", "GE", "HON", "MMM", "CAT",
    "DE", "EMR", "ROK", "PH", "ITW", "GD",
    "UPS", "FDX", "XPO", "CHRW",
]

# ── Real Estate (non-data-center) ─────────────────────────────────────────────
REAL_ESTATE = [
    "SPG", "O", "VICI", "WPC", "PSA", "AVB", "EQR", "MAA",
    "PLD", "STAG", "REXR",
]

# ── ETFs (useful as benchmark / context) ─────────────────────────────────────
ETFS = [
    "SPY", "QQQ", "IWM", "DIA",         # broad market
    "XLK", "SMH", "SOXX",               # tech / semis
    "XLE", "XOP", "ICLN",               # energy / clean
    "XLF", "XLV", "XLI", "XLU",        # other sectors
    "GLD", "SLV", "USO",                # commodities
    "TLT", "HYG",                       # bonds
]


# ── News-discovered tickers (auto-updated by information.py) ─────────────────
# Do not edit manually — this list is managed programmatically.
NEWS_DISCOVERED: list[str] = [
    "SRHBF",
    "NSANF",
    "ICHIF",
    "KMRPF",
    "GRWG",
    "HYFM",
    "SMG",
]

# ── Master list ───────────────────────────────────────────────────────────────

def get_tickers(include_etfs: bool = True) -> list[str]:
    """
    Return the full deduplicated ticker list.

    Parameters
    ----------
    include_etfs : bool
        Set False to exclude ETFs (strategy signals don't apply well to them).
    """
    all_lists = [
        MEGA_CAP_TECH, SEMICONDUCTORS, CLOUD_INFRA, SAAS, FINTECH,
        INTERNET, HARDWARE_STORAGE, TELECOM,
        ENERGY_OIL_GAS, ENERGY_CLEAN, UTILITIES,
        HEALTHCARE, FINANCIALS, CONSUMER, INDUSTRIALS, REAL_ESTATE,
        NEWS_DISCOVERED,
    ]
    if include_etfs:
        all_lists.append(ETFS)

    seen: set[str] = set()
    result: list[str] = []
    for lst in all_lists:
        for t in lst:
            if t not in seen:
                seen.add(t)
                result.append(t)
    return result


if __name__ == "__main__":
    tickers = get_tickers(include_etfs=False)
    print(f"Total tickers (no ETFs): {len(tickers)}")
    tickers_all = get_tickers(include_etfs=True)
    print(f"Total tickers (with ETFs): {len(tickers_all)}")
