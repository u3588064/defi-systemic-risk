"""
leverage.py — DeFi Protocol Leverage Heatmap

Methodology:
    Protocol leverage = Total Borrowed / Total Supplied (utilization ratio).
    High utilization → liquidity crunch risk if withdrawals accelerate.

    System leverage index = Σ (utilization_i × tvl_i) / Σ tvl_i
    (TVL-weighted average utilization across top lending protocols)

    Percentile rank vs. 90-day rolling history indicates whether current
    leverage is historically extreme.

Data sources:
    - DeFiLlama yields API (pool-level borrow/supply TVL, APR)
    - DeFiLlama protocols API (TVL per protocol)

Key metrics:
    - utilization        : borrowed / supplied
    - borrow_apy         : current floating borrow rate
    - supply_apy         : lender yield
    - interest_spread    : borrow_apy - supply_apy (widening = stress)
    - tvl_usd_bn         : protocol TVL as size weight
"""

import logging
import math

logger = logging.getLogger(__name__)

# Lending protocols to track (DeFiLlama pool project slugs)
TRACKED_LENDING = {
    "aave-v3", "aave-v2", "compound-v3", "compound-v2",
    "makerdao", "spark", "morpho-blue", "radiant-v2",
    "venus", "benqi", "euler", "fraxlend",
}


# ── Main analysis ─────────────────────────────────────────────────────────

def build_leverage_heatmap(pools: list[dict]) -> dict:
    """
    Build a protocol-level leverage heatmap from DeFiLlama yield pool data.

    Args:
        pools : List from defillama.get_lending_rates() or get_pools().

    Returns:
        Dict with per-protocol leverage metrics and system leverage index.
    """
    protocol_data: dict[str, dict] = {}

    for pool in pools:
        project = pool.get("project", "").lower()
        if project not in TRACKED_LENDING:
            continue

        symbol    = pool.get("symbol", "?")
        chain     = pool.get("chain", "?")
        tvl       = pool.get("tvlUsd", 0) or 0
        borrow_tvl = pool.get("totalBorrowUsd") or pool.get("borrowTvl") or 0
        supply_tvl = pool.get("totalSupplyUsd") or tvl
        borrow_apy = pool.get("apyBorrow") or 0
        supply_apy = pool.get("apy") or 0

        utilization = borrow_tvl / supply_tvl if supply_tvl > 0 else 0.0

        key = project
        if key not in protocol_data:
            protocol_data[key] = {
                "protocol": project,
                "pools": [],
                "total_tvl": 0,
                "total_borrow": 0,
                "total_supply": 0,
            }

        protocol_data[key]["pools"].append({
            "symbol": symbol,
            "chain": chain,
            "tvl_usd_mn": round(tvl / 1e6, 2),
            "borrow_tvl_usd_mn": round(borrow_tvl / 1e6, 2),
            "utilization": round(utilization, 4),
            "borrow_apy_pct": round(borrow_apy, 4),
            "supply_apy_pct": round(supply_apy, 4),
            "interest_spread_pct": round(borrow_apy - supply_apy, 4),
        })

        protocol_data[key]["total_tvl"]    += tvl
        protocol_data[key]["total_borrow"] += borrow_tvl
        protocol_data[key]["total_supply"] += supply_tvl

    # Aggregate per protocol
    protocols = []
    total_tvl    = 0.0
    weighted_util = 0.0

    for proj, d in protocol_data.items():
        util = d["total_borrow"] / d["total_supply"] if d["total_supply"] > 0 else 0.0
        avg_borrow_apy = (
            sum(p["borrow_apy_pct"] for p in d["pools"]) / len(d["pools"])
            if d["pools"] else 0.0
        )

        protocols.append({
            "protocol": proj,
            "tvl_usd_bn": round(d["total_tvl"] / 1e9, 3),
            "total_borrow_usd_bn": round(d["total_borrow"] / 1e9, 3),
            "utilization": round(util, 4),
            "utilization_pct": round(util * 100, 2),
            "stress_level": _util_stress(util),
            "avg_borrow_apy_pct": round(avg_borrow_apy, 3),
            "pool_count": len(d["pools"]),
        })

        total_tvl    += d["total_tvl"]
        weighted_util += d["total_tvl"] * util

    system_util = weighted_util / total_tvl if total_tvl > 0 else 0.0

    ranked = sorted(protocols, key=lambda x: x["utilization"], reverse=True)

    return {
        "system_leverage_index": round(system_util, 4),
        "system_leverage_pct": round(system_util * 100, 2),
        "system_stress_level": _util_stress(system_util),
        "total_lending_tvl_usd_bn": round(total_tvl / 1e9, 2),
        "protocols": ranked,
    }


def _util_stress(util: float) -> str:
    if util >= 0.90:   return "CRITICAL"
    if util >= 0.80:   return "HIGH"
    if util >= 0.65:   return "ELEVATED"
    if util >= 0.50:   return "MODERATE"
    return "LOW"
