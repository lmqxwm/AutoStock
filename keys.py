"""
keys.py  —  API key loader.  Never committed to git.
Reads from keys.txt (same directory), then falls back to environment variables.

keys.txt format (one per line):
    FINNHUB_API_KEY=your_key_here
    GEMINI_API_KEY=your_key_here
    MARKETAUX_API_KEY=your_key_here
    GROQ_API_KEY=your_key_here
"""
import os
from pathlib import Path

_FILE = Path(__file__).parent / "keys.txt"


def _load() -> dict[str, str]:
    if not _FILE.exists():
        return {}
    out: dict[str, str] = {}
    for line in _FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


_store = _load()


def get(name: str, default: str = "") -> str:
    """Return key: env var takes priority over keys.txt."""
    return os.environ.get(name) or _store.get(name, default)


FINNHUB_API_KEY = get("FINNHUB_API_KEY")
GEMINI_API_KEY  = get("GEMINI_API_KEY")
MARKETAUX_KEY   = get("MARKETAUX_API_KEY")
GROQ_API_KEY    = get("GROQ_API_KEY")
