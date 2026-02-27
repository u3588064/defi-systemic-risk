"""
glassnode.py — Glassnode on-chain metrics client

Free tier (no or empty API key) provides access to a limited metric set.
Endpoints used (all available on free tier):

    /v1/metrics/transactions/count           — Daily tx count
    /v1/metrics/supply/current               — Circulating supply
    /v1/metrics/market/price_usd_close       — Daily close price
    /v1/metrics/distribution/balance_exchanges — Exchange balance (BTC/ETH)
    /v1/metrics/market/mvrv_z_score          — MVRV Z-Score (free)
    /v1/metrics/indicators/sopr              — SOPR - Spent Output Profit Ratio

Strategy:
    - Build a small set of on-chain indicators that act as systemic
      "fear / greed / stress" signals for BTC and ETH.
    - Full key: set GLASSNODE_API_KEY env var to unlock premium metrics.
    - Free key: no key or empty string works for the basic set above.

Docs: https://docs.glassnode.com/api/metrics
"""

import logging
import os
import time
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

_BASE    = "https://api.glassnode.com"
_TIMEOUT = 20
_DELAY   = 1.0   # Glassnode rate limits are strict on free tier


def _get(path: str, params: dict | None = None) -> list | None:
    """Execute a Glassnode REST call, return list of {t, v} dicts."""
    key = os.environ.get("GLASSNODE_API_KEY", "")
    base_params = {"a": "BTC", "i": "24h", "f": "JSON"}
    if key:
        base_params["api_key"] = key
    if params:
        base_params.update(params)

    try:
        resp = httpx.get(f"{_BASE}{path}", params=base_params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            logger.warning(f"Glassnode auth error — metric may require paid plan: {path}")
        elif e.response.status_code == 429:
            logger.warning("Glassnode rate limit hit — sleeping 60s")
            time.sleep(60)
        else:
            logger.warning(f"Glassnode HTTP error [{path}]: {e}")
        return None
    except Exception as e:
        logger.warning(f"Glassnode request failed [{path}]: {e}")
        return None
    finally:
        time.sleep(_DELAY)


def _latest(path: str, asset: str = "BTC") -> float | None:
    """Return the most recent single value for a metric."""
    data = _get(path, {"a": asset, "i": "24h"})
    if data and isinstance(data, list) and len(data) > 0:
        return data[-1].get("v")
    return None


# ── Exchange balance (BTC / ETH held on exchanges) ────────────────────────

def get_exchange_balance(asset: str = "BTC") -> float | None:
    """
    Total amount of BTC or ETH held in exchange wallets.
    Rising balance = sell pressure / stress. Falling = accumulation.
    Free tier metric.
    """
    return _latest("/v1/metrics/distribution/balance_exchanges", asset)


def get_exchange_balance_history(asset: str = "BTC", days: int = 90) -> list[dict]:
    """Historical exchange balance series."""
    since = int((datetime.now(timezone.utc).timestamp()) - days * 86400)
    data = _get("/v1/metrics/distribution/balance_exchanges",
                {"a": asset, "i": "24h", "s": since})
    return data or []


# ── MVRV Z-Score ─────────────────────────────────────────────────────────

def get_mvrv_z_score(asset: str = "BTC") -> float | None:
    """
    MVRV Z-Score = (Market Cap - Realized Cap) / std(Market Cap).
    High values: overheated market. Negative: capitulation.
    Free tier metric.
    """
    return _latest("/v1/metrics/market/mvrv_z_score", asset)


# ── SOPR ─────────────────────────────────────────────────────────────────

def get_sopr(asset: str = "BTC") -> float | None:
    """
    SOPR (Spent Output Profit Ratio): >1 = coins sold at profit, <1 = at loss.
    Sustained <1 = capitulation signal.
    Free tier metric.
    """
    return _latest("/v1/metrics/indicators/sopr", asset)


# ── Transaction count ─────────────────────────────────────────────────────

def get_tx_count(asset: str = "BTC") -> float | None:
    """Number of on-chain transactions (activity proxy). Free tier."""
    return _latest("/v1/metrics/transactions/count", asset)


# ── Close price ───────────────────────────────────────────────────────────

def get_price_close(asset: str = "BTC") -> float | None:
    """Daily close price from Glassnode. Free tier."""
    return _latest("/v1/metrics/market/price_usd_close", asset)


# ── Convenience: stress snapshot ─────────────────────────────────────────

def get_onchain_stress_snapshot() -> dict:
    """
    Return a compact snapshot of all key on-chain stress indicators
    for BTC and ETH. Suitable for caching to data/latest.json.
    """
    return {
        "btc": {
            "exchange_balance": get_exchange_balance("BTC"),
            "mvrv_z_score": get_mvrv_z_score("BTC"),
            "sopr": get_sopr("BTC"),
            "tx_count": get_tx_count("BTC"),
            "price_usd": get_price_close("BTC"),
        },
        "eth": {
            "exchange_balance": get_exchange_balance("ETH"),
            "mvrv_z_score": get_mvrv_z_score("ETH"),
            "sopr": get_sopr("ETH"),
            "tx_count": get_tx_count("ETH"),
            "price_usd": get_price_close("ETH"),
        },
    }
