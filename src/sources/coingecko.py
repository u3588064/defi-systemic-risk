"""
coingecko.py — CoinGecko API client

Free API base: https://api.coingecko.com/api/v3
Demo API key (optional): set COINGECKO_API_KEY env var for higher rate limits.

No key needed for:
    - /simple/price (current prices)
    - /coins/markets (market overview)
    - /coins/{id}/market_chart (historical OHLCV)
    - /global/decentralized_finance_defi (DeFi macro)

Key CoinGecko IDs for stablecoins and major assets:
    tether, usd-coin, dai, frax, true-usd, pax-usd,
    bitcoin, ethereum, wrapped-bitcoin
"""

import time
import logging
import os

import httpx

logger = logging.getLogger(__name__)

_FREE_BASE = "https://api.coingecko.com/api/v3"
_PRO_BASE  = "https://pro-api.coingecko.com/api/v3"
_DELAY     = 1.2   # ~50 req/min on free tier; pro allows more
_TIMEOUT   = 20


def _base_url() -> str:
    return _PRO_BASE if os.environ.get("COINGECKO_API_KEY") else _FREE_BASE


def _headers() -> dict:
    key = os.environ.get("COINGECKO_API_KEY", "")
    if key:
        return {"x-cg-pro-api-key": key}
    return {}


def _get(path: str, params: dict | None = None) -> dict | list | None:
    url = f"{_base_url()}{path}"
    try:
        resp = httpx.get(url, params=params, headers=_headers(), timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            logger.warning("CoinGecko rate limit hit — sleeping 60s")
            time.sleep(60)
        else:
            logger.warning(f"CoinGecko error [{path}]: {e}")
        return None
    except Exception as e:
        logger.warning(f"CoinGecko request failed [{path}]: {e}")
        return None
    finally:
        time.sleep(_DELAY)


# ── Key asset IDs ─────────────────────────────────────────────────────────

STABLECOIN_IDS = [
    "tether",       # USDT
    "usd-coin",     # USDC
    "dai",          # DAI
    "frax",         # FRAX
    "true-usd",     # TUSD
    "paxos-standard",  # USDP
    "first-digital-usd",  # FDUSD
    "ethena-usde",  # USDe
    "usdd",         # USDD
]

MAJOR_ASSET_IDS = ["bitcoin", "ethereum", "wrapped-bitcoin"]


# ── Prices ────────────────────────────────────────────────────────────────

def get_prices(coin_ids: list[str], vs_currency: str = "usd") -> dict:
    """Get current prices for a list of coin IDs."""
    data = _get("/simple/price", params={
        "ids": ",".join(coin_ids),
        "vs_currencies": vs_currency,
        "include_24hr_change": "true",
        "include_market_cap": "true",
    })
    return data or {}


def get_stablecoin_prices() -> dict:
    """Get current prices + 24h change for all tracked stablecoins."""
    return get_prices(STABLECOIN_IDS)


# ── Market overview ───────────────────────────────────────────────────────

def get_markets(ids: list[str] | None = None, top_n: int = 100) -> list[dict]:
    """
    Get market data (cap, volume, price change) for coins.
    If ids provided, fetches those specifically. Otherwise top_n by market cap.
    """
    params = {
        "vs_currency": "usd",
        "per_page": min(top_n, 250),
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "24h,7d,30d",
    }
    if ids:
        params["ids"] = ",".join(ids)
    data = _get("/coins/markets", params=params)
    return data if isinstance(data, list) else []


def get_stablecoin_market_data() -> list[dict]:
    """Market data for all tracked stablecoins."""
    return get_markets(ids=STABLECOIN_IDS)


# ── Historical price ──────────────────────────────────────────────────────

def get_price_history(coin_id: str, days: int = 90, interval: str = "daily") -> dict:
    """
    Get historical price, market cap, and volume.
    Free tier: up to 365 days with daily interval.
    Returns: {prices: [[ts, price], ...], market_caps: [...], total_volumes: [...]}
    """
    data = _get(f"/coins/{coin_id}/market_chart", params={
        "vs_currency": "usd",
        "days": days,
        "interval": interval,
    })
    return data or {}


# ── DeFi global stats ─────────────────────────────────────────────────────

def get_defi_global() -> dict:
    """Overall DeFi market stats: total TVL, volume, dominance."""
    data = _get("/global/decentralized_finance_defi")
    return data.get("data", {}) if isinstance(data, dict) else {}


def get_global_market() -> dict:
    """Overall crypto market stats: total market cap, fear & greed, dominance."""
    data = _get("/global")
    return data.get("data", {}) if isinstance(data, dict) else {}


# ── Convenience: peg deviation ────────────────────────────────────────────

def calc_peg_deviation(price: float, peg: float = 1.0) -> float:
    """Return signed deviation from peg as a fraction."""
    return (price - peg) / peg
