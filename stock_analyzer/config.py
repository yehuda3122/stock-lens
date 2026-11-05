"""Global settings. Override via environment variables or the local `keys.env` file."""
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
KEYS_FILE = PROJECT_DIR / "keys.env"


def load_keys_file(path: Path = KEYS_FILE) -> dict:
    """Read KEY=VALUE lines from keys.env into the environment (real env vars take precedence).
    Keeps API keys out of the code and lets every entry point (app, CLI) pick them up."""
    loaded = {}
    if not path.exists():
        return loaded
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and not os.environ.get(k):
            os.environ[k] = v
            loaded[k] = v
    return loaded


load_keys_file()


def get_setting(name: str, default=None):
    """Environment variable first, then Streamlit secrets (cloud deployment), then default."""
    v = os.environ.get(name)
    if v:
        return v
    try:
        import streamlit as st
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return default


def get_list_setting(name: str) -> list[str]:
    """Comma-separated string or TOML list -> lowercase list."""
    v = get_setting(name, [])
    if isinstance(v, str):
        v = v.split(",")
    return [str(x).strip().lower() for x in v if str(x).strip()]

# SEC requires a descriptive User-Agent with contact e-mail:
# https://www.sec.gov/os/accessing-edgar-data
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "PersonalStockResearch your-email@example.com")

CACHE_DIR = Path(os.environ.get("STOCK_CACHE_DIR", Path.home() / ".stock_analyzer_cache"))
CACHE_TTL_HOURS = float(os.environ.get("STOCK_CACHE_TTL_HOURS", "24"))

# Market defaults (editable in the UI)
DEFAULT_RISK_FREE = 0.043       # ~10Y US Treasury
DEFAULT_EQUITY_RISK_PREMIUM = 0.05
DEFAULT_TERMINAL_GROWTH = 0.025
DEFAULT_TAX_RATE = 0.21
