"""Global settings. Override via environment variables."""
import os
from pathlib import Path

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
