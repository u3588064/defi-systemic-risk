"""
bridge.py — Cross-chain Bridge Risk & Anomaly Detection

Cross-chain bridges are among the highest-risk components in DeFi:
    - They custodize large amounts of locked assets.
    - A bridge exploit immediately drains TVL (rapid single-day drops).
    - Network concentration (most TVL in 2-3 bridges) amplifies systemic risk.

Metrics:
    1. Bridge TVL concentration (Herfindahl-Hirschman Index, HHI)
       HHI = Σ (share_i)²  ×  10000
       High HHI → single-bridge dominance → systemic fragility.

    2. Single-day TVL drop detection
       A drop > threshold% (default 20%) in one bridge in one day
       flags a potential exploit or bank-run.

    3. Net daily flow (inflow - outflow via bridge)
       Large consistent outflows → capital flight from a chain.

Data source: DeFiLlama Bridges API (free).
"""

import logging
import math
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ── HHI Concentration ─────────────────────────────────────────────────────

def calc_bridge_concentration(bridges: list[dict]) -> dict:
    """
    Compute HHI concentration index for bridge TVL.

    Args:
        bridges : List from defillama.get_all_bridges().

    Returns:
        Dict with HHI, top bridges, and concentration level.
    """
    tvls = [(b.get("displayName", b.get("name", "?")),
             float(b.get("currentTotalVolume", 0) or 0))
            for b in bridges]
    tvls = [(name, tvl) for name, tvl in tvls if tvl > 0]

    total = sum(t for _, t in tvls)
    if total == 0:
        return {"error": "No bridge TVL data"}

    shares = [(name, tvl / total) for name, tvl in tvls]
    hhi = sum(s ** 2 for _, s in shares) * 10000

    top_bridges = sorted(
        [{"name": n, "tvl_usd_bn": round(v / 1e9, 3), "share_pct": round(s * 100, 2)}
         for (n, v), (_, s) in zip(sorted(tvls, key=lambda x: x[1], reverse=True),
                                    sorted(shares, key=lambda x: x[1], reverse=True))],
        key=lambda x: x["share_pct"], reverse=True
    )[:10]

    return {
        "hhi": round(hhi, 1),
        "concentration_level": _hhi_level(hhi),
        "total_bridge_tvl_usd_bn": round(total / 1e9, 2),
        "bridge_count": len(tvls),
        "top_bridges": top_bridges,
    }


# ── Anomaly detection ─────────────────────────────────────────────────────

def detect_bridge_anomalies(
    bridges: list[dict],
    drop_threshold_pct: float = 20.0,
) -> list[dict]:
    """
    Flag bridges with unusually large single-day TVL moves.

    Args:
        bridges            : Bridge list from defillama.get_all_bridges().
        drop_threshold_pct : % TVL drop in one day that triggers a flag.

    Returns:
        List of anomalous bridge dicts sorted by severity.
    """
    anomalies = []

    for bridge in bridges:
        name    = bridge.get("displayName", bridge.get("name", "?"))
        current = float(bridge.get("currentTotalVolume", 0) or 0)
        # DeFiLlama provides lastDailyVolume (24h net volume on the bridge)
        daily_vol = float(bridge.get("lastDailyVolume", 0) or 0)

        if current <= 0:
            continue

        # A large net outflow relative to total locked is a red flag
        outflow_ratio = abs(daily_vol) / current if current > 0 else 0

        if outflow_ratio * 100 >= drop_threshold_pct:
            anomalies.append({
                "bridge": name,
                "tvl_usd_bn": round(current / 1e9, 3),
                "daily_volume_usd_bn": round(daily_vol / 1e9, 3),
                "outflow_pct": round(outflow_ratio * 100, 2),
                "severity": "CRITICAL" if outflow_ratio > 0.40 else "WARNING",
            })

    return sorted(anomalies, key=lambda x: x["outflow_pct"], reverse=True)


# ── Complete bridge risk report ───────────────────────────────────────────

def build_bridge_risk_report(bridges: list[dict], drop_threshold_pct: float = 20.0) -> dict:
    """Combined bridge risk report: concentration + anomaly detection."""
    if not bridges:
        return {"error": "No bridge data available from DeFiLlama."}

    concentration = calc_bridge_concentration(bridges)
    anomalies     = detect_bridge_anomalies(bridges, drop_threshold_pct)

    overall_risk = "HIGH" if (
        anomalies or concentration.get("hhi", 0) > 3000
    ) else ("MODERATE" if concentration.get("hhi", 0) > 1500 else "LOW")

    return {
        "overall_bridge_risk": overall_risk,
        "concentration": concentration,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    }


def _hhi_level(hhi: float) -> str:
    if hhi >= 2500:  return "HIGHLY_CONCENTRATED"
    if hhi >= 1500:  return "MODERATELY_CONCENTRATED"
    return "COMPETITIVE"
