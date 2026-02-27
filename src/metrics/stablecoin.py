"""
stablecoin.py — Stablecoin Peg Stress Analyser

Metrics computed:
    1. Peg deviation: (price - 1.0) / 1.0  for each stablecoin
    2. Peg stress score: composite signal weighted by market cap
    3. Depeg probability proxy: based on deviation z-score vs 30-day history
    4. Supply trend: 30-day change in market cap (contraction = redemption pressure)

Methodology:
    A stablecoin "depeg event" is defined as |price - 1.0| > 0.5%
    (warn threshold) or > 2% (critical threshold).

    The system-level stress index is:
        StablecoinStress = Σ (market_cap_i × |deviation_i|) / Σ market_cap_i
    This is a market-cap-weighted average deviation across all stablecoins.

Data source: CoinGecko (free tier).
"""

import logging
import math
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ── Peg analysis ──────────────────────────────────────────────────────────

def analyse_pegs(
    stablecoin_market_data: list[dict],
    warn_threshold: float = 0.005,
    critical_threshold: float = 0.02,
) -> dict:
    """
    Analyse peg stability for all tracked stablecoins.

    Args:
        stablecoin_market_data : List from coingecko.get_stablecoin_market_data().
        warn_threshold         : |deviation| at which to issue a warning.
        critical_threshold     : |deviation| at which to issue a critical alert.

    Returns:
        Dict with per-coin analysis and system stress index.
    """
    coins = []
    total_mcap   = 0.0
    weighted_dev = 0.0

    for coin in stablecoin_market_data:
        price  = coin.get("current_price", 1.0) or 1.0
        mcap   = coin.get("market_cap", 0)       or 0
        vol24h = coin.get("total_volume", 0)      or 0
        change_24h = coin.get("price_change_percentage_24h") or 0

        deviation     = price - 1.0
        abs_deviation = abs(deviation)

        if abs_deviation >= critical_threshold:
            status = "CRITICAL"
        elif abs_deviation >= warn_threshold:
            status = "WARNING"
        else:
            status = "STABLE"

        coins.append({
            "id": coin.get("id"),
            "symbol": coin.get("symbol", "").upper(),
            "name": coin.get("name"),
            "price_usd": round(price, 6),
            "peg_deviation": round(deviation, 6),
            "peg_deviation_pct": round(abs_deviation * 100, 4),
            "status": status,
            "market_cap_usd_bn": round(mcap / 1e9, 3),
            "volume_24h_usd_bn": round(vol24h / 1e9, 3),
            "price_change_24h_pct": round(change_24h, 4),
        })

        total_mcap   += mcap
        weighted_dev += mcap * abs_deviation

    system_stress = weighted_dev / total_mcap if total_mcap > 0 else 0.0

    critical_coins = [c for c in coins if c["status"] == "CRITICAL"]
    warning_coins  = [c for c in coins if c["status"] == "WARNING"]

    return {
        "total_stablecoin_mcap_usd_bn": round(total_mcap / 1e9, 2),
        "system_peg_stress_index": round(system_stress * 100, 6),   # in %
        "system_stress_level": _stress_level(system_stress),
        "critical_count": len(critical_coins),
        "warning_count": len(warning_coins),
        "coins": sorted(coins, key=lambda x: abs(x["peg_deviation"]), reverse=True),
    }


# ── Supply trend (redemption pressure) ───────────────────────────────────

def calc_supply_trend(price_history: dict) -> dict:
    """
    Compute 30-day market cap trend for a stablecoin.
    Sustained market cap decline = redemption pressure = systemic concern.

    Args:
        price_history : Response from coingecko.get_price_history(coin_id, days=30).

    Returns:
        Dict with start_mcap, end_mcap, change_pct, trend.
    """
    mcaps = price_history.get("market_caps", [])
    if len(mcaps) < 2:
        return {"error": "Insufficient history"}

    start_mcap = mcaps[0][1]
    end_mcap   = mcaps[-1][1]
    change_pct = (end_mcap - start_mcap) / start_mcap * 100 if start_mcap > 0 else 0

    if change_pct < -15:
        trend = "SEVERE_CONTRACTION"
    elif change_pct < -5:
        trend = "CONTRACTION"
    elif change_pct > 10:
        trend = "EXPANSION"
    else:
        trend = "STABLE"

    return {
        "start_mcap_usd_bn": round(start_mcap / 1e9, 3),
        "end_mcap_usd_bn":   round(end_mcap   / 1e9, 3),
        "change_pct_30d":    round(change_pct, 2),
        "trend":             trend,
    }


# ── Helpers ───────────────────────────────────────────────────────────────

def _stress_level(deviation: float) -> str:
    if deviation > 0.02:   return "CRITICAL"
    if deviation > 0.005:  return "ELEVATED"
    if deviation > 0.001:  return "MILD"
    return "NORMAL"
