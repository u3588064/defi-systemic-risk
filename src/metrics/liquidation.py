"""
liquidation.py — DeFi Liquidation Cascade Simulator

Methodology:
    For each price-drop scenario (e.g. ETH -20%, BTC -30%):
    1. Fetch all on-chain lending positions from Aave V3 via The Graph.
    2. Re-price each position's collateral at the hypothetical lower price.
    3. If re-priced health factor < 1.0 → position becomes liquidatable.
    4. Sum all liquidatable collateral USD value → cascade estimate.

    This approximates NYU Stern's approach to measuring
    "Second-Round Systemic Amplification" in DeFi.

Key outputs:
    - cascade_at_drop: {10%: $X bn, 20%: $Y bn, ...}
    - liquidatable_positions: count and total value at each threshold
    - most_vulnerable_asset: which collateral type dominates the risk

Limitations:
    - Uses Aave V3 on-chain data only (The Graph).
    - Assumes collateral is denominated in the stressed asset.
    - Does not account for partial liquidations or protocol pause mechanisms.
"""

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


# ── Main cascade simulator ────────────────────────────────────────────────

def simulate_cascade(
    positions: list[dict],
    asset_prices_usd: dict[str, float],
    drop_pcts: list[float],
    eth_price_usd: float = 2000.0,
) -> dict:
    """
    Simulate liquidation cascade for multiple price-drop scenarios.

    Args:
        positions       : List of user positions from thegraph.get_aave_v3_risky_users().
        asset_prices_usd: Current prices in USD {symbol: price}.
        drop_pcts       : List of fractional price drops to simulate (e.g. [0.10, 0.20]).
        eth_price_usd   : Current ETH price in USD (used to convert ETH values).

    Returns:
        Dict with cascade estimates per drop scenario.
    """
    if not positions:
        return {"error": "No position data available from The Graph."}

    results = {}
    for drop in drop_pcts:
        dropped_prices = {k: v * (1 - drop) for k, v in asset_prices_usd.items()}
        cascade = _calc_cascade(positions, dropped_prices, eth_price_usd * (1 - drop))
        results[f"drop_{int(drop*100)}pct"] = cascade

    return {
        "total_positions_analyzed": len(positions),
        "scenarios": results,
        "methodology": "Aave V3 positions re-priced at hypothetical collateral drops.",
    }


def _calc_cascade(
    positions: list[dict],
    stressed_prices: dict[str, float],
    stressed_eth_usd: float,
) -> dict:
    """Compute liquidatable value under a single price-stress scenario."""
    liquidatable_count = 0
    liquidatable_usd   = 0.0
    total_collateral   = 0.0
    liquidatable_by_asset: dict[str, float] = {}

    for pos in positions:
        # Aave stores collateral values in ETH (18 decimals)
        collateral_eth = _safe_float(pos.get("totalCollateralETH")) / 1e18
        debt_eth       = _safe_float(pos.get("totalDebtETH")) / 1e18
        liq_threshold  = _safe_float(pos.get("currentLiquidationThreshold")) / 1e4

        if collateral_eth <= 0 or debt_eth <= 0 or liq_threshold <= 0:
            continue

        collateral_usd = collateral_eth * stressed_eth_usd
        debt_usd       = debt_eth * stressed_eth_usd
        total_collateral += collateral_usd

        # Health Factor = (collateral * liquidation threshold) / debt
        stressed_hf = (collateral_usd * liq_threshold) / debt_usd if debt_usd > 0 else float("inf")

        if stressed_hf < 1.0:
            liquidatable_count += 1
            liquidatable_usd   += collateral_usd

            # Track which collateral tokens dominate
            for col in pos.get("collateral", []):
                symbol = col.get("reserve", {}).get("symbol", "UNKNOWN")
                bal_raw = _safe_float(col.get("currentATokenBalance"))
                # Rough USD estimate (bal_raw in token units, 18 decimals assumed)
                token_price = stressed_prices.get(symbol, stressed_eth_usd if symbol == "WETH" else 1.0)
                usd_val = (bal_raw / 1e18) * token_price
                liquidatable_by_asset[symbol] = liquidatable_by_asset.get(symbol, 0) + usd_val

    top_assets = sorted(liquidatable_by_asset.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "liquidatable_positions": liquidatable_count,
        "liquidatable_usd_bn": round(liquidatable_usd / 1e9, 4),
        "total_collateral_usd_bn": round(total_collateral / 1e9, 4),
        "cascade_pct_of_tvl": round(liquidatable_usd / total_collateral * 100, 2) if total_collateral > 0 else None,
        "top_liquidatable_assets": [{"symbol": s, "usd_bn": round(v / 1e9, 4)} for s, v in top_assets],
    }


# ── Static cascade from DeFiLlama (no Graph needed) ─────────────────────

def estimate_cascade_from_tvl(
    protocol_tvls: list[dict],
    drop_pcts: list[float],
    avg_ltv: float = 0.70,
) -> dict:
    """
    Coarser estimate when The Graph data is unavailable.
    Assumes a fraction of lending TVL becomes liquidatable at each drop.

    cascade_at_drop_X ≈ lending_TVL × (drop% / 100) / avg_LTV
    
    This is a back-of-envelope approach.
    """
    lending_tvl = sum(
        p.get("tvl", 0) for p in protocol_tvls
        if p.get("category", "").lower() in ("lending", "cdp")
    )

    return {
        "method": "TVL-proxy (no Graph data)",
        "lending_tvl_usd_bn": round(lending_tvl / 1e9, 2),
        "avg_ltv_assumption": avg_ltv,
        "scenarios": {
            f"drop_{int(d*100)}pct": {
                "estimated_liquidatable_usd_bn": round(
                    lending_tvl * d / avg_ltv / 1e9, 2
                )
            }
            for d in drop_pcts
        },
    }


def _safe_float(val: Any) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0
