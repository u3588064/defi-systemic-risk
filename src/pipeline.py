"""
pipeline.py — DeFi Systemic Risk daily pipeline

Usage:
    python src/pipeline.py              # run for today
    python src/pipeline.py --date 2024-01-15
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("defi-pipeline")

from src.config import cfg
from src.sources.defillama import (
    get_lending_protocols, get_all_bridges, get_all_stablecoins,
    get_lending_rates, get_global_tvl_history, get_chain_tvls,
)
from src.sources.coingecko import (
    get_stablecoin_market_data, get_defi_global, get_global_market
)
from src.sources.thegraph import get_aave_v3_reserves, get_aave_v3_risky_users
from src.sources.glassnode import get_onchain_stress_snapshot
from src.metrics.liquidation import simulate_cascade, estimate_cascade_from_tvl
from src.metrics.stablecoin import analyse_pegs
from src.metrics.leverage import build_leverage_heatmap
from src.metrics.bridge import build_bridge_risk_report
from src.publish import publish_latest, publish_snapshot


def run_pipeline():
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    logger.info(f"=== DeFi Systemic Risk Pipeline  date={today} ===")

    payload = {
        "date": today,
        "generated_at": now.isoformat(),
        "methodology_version": "1.0",
    }

    # ── 1. Stablecoin peg stress ───────────────────────────────────────
    logger.info("Fetching stablecoin market data…")
    stable_market = get_stablecoin_market_data()
    peg_analysis = {}
    if stable_market:
        peg_analysis = analyse_pegs(
            stable_market,
            warn_threshold=cfg.peg_warn_threshold,
            critical_threshold=cfg.peg_critical_threshold,
        )
        logger.info(f"  Peg stress index: {peg_analysis.get('system_peg_stress_index')} | "
                    f"Critical: {peg_analysis.get('critical_count')}")
    payload["stablecoin_stress"] = peg_analysis

    # ── 2. Protocol leverage heatmap ──────────────────────────────────
    logger.info("Fetching DeFi yield pool data…")
    pools = get_lending_rates()
    leverage_data = {}
    if pools:
        leverage_data = build_leverage_heatmap(pools)
        logger.info(f"  System leverage index: {leverage_data.get('system_leverage_pct')}%")
    payload["protocol_leverage"] = leverage_data

    # ── 3. Bridge risk ────────────────────────────────────────────────
    logger.info("Fetching bridge data…")
    bridges = get_all_bridges()
    bridge_risk = {}
    if bridges:
        bridge_risk = build_bridge_risk_report(bridges, cfg.bridge_drop_pct)
        logger.info(f"  Bridge risk: {bridge_risk.get('overall_bridge_risk')} | "
                    f"Anomalies: {bridge_risk.get('anomaly_count')}")
    payload["bridge_risk"] = bridge_risk

    # ── 4. Liquidation cascade ────────────────────────────────────────
    logger.info("Fetching Aave V3 positions…")
    cascade_data = {}
    try:
        aave_positions = get_aave_v3_risky_users(max_health_factor=1.5)
        if aave_positions:
            # Get ETH price from stablecoin data / coingecko global
            eth_price = _extract_eth_price(stable_market)
            asset_prices = {"WETH": eth_price, "WBTC": eth_price * 15,
                            "USDC": 1.0, "USDT": 1.0, "DAI": 1.0}  # rough defaults
            cascade_data = simulate_cascade(
                aave_positions,
                asset_prices,
                drop_pcts=cfg.cascade_price_drops,
                eth_price_usd=eth_price,
            )
        else:
            # Fallback: TVL-proxy method
            lending_protos = get_lending_protocols(top_n=30)
            cascade_data = estimate_cascade_from_tvl(
                lending_protos, cfg.cascade_price_drops
            )
    except Exception as e:
        logger.warning(f"Cascade simulation failed: {e}")
        cascade_data = {"error": str(e)}
    payload["liquidation_cascade"] = cascade_data

    # ── 5. On-chain stress (Glassnode) ────────────────────────────────
    logger.info("Fetching on-chain indicators…")
    try:
        onchain = get_onchain_stress_snapshot()
    except Exception as e:
        logger.warning(f"Glassnode fetch failed: {e}")
        onchain = {}
    payload["onchain_stress"] = onchain

    # ── 6. DeFi macro stats (CoinGecko) ──────────────────────────────
    logger.info("Fetching DeFi global stats…")
    try:
        defi_global = get_defi_global()
    except Exception as e:
        logger.warning(f"CoinGecko DeFi global failed: {e}")
        defi_global = {}
    payload["defi_global"] = defi_global

    # ── 7. Global chain TVL summary (DeFiLlama) ───────────────────────
    logger.info("Fetching chain TVL breakdown…")
    try:
        chain_tvls = get_chain_tvls()
        if isinstance(chain_tvls, list):
            top_chains = sorted(chain_tvls, key=lambda x: x.get("tvl", 0), reverse=True)[:10]
            payload["top_chains_tvl"] = [
                {"chain": c.get("name"), "tvl_usd_bn": round(c.get("tvl", 0) / 1e9, 2)}
                for c in top_chains
            ]
    except Exception as e:
        logger.warning(f"Chain TVL fetch failed: {e}")

    # ── Publish ───────────────────────────────────────────────────────
    publish_latest(today, payload)
    publish_snapshot(today, payload)
    logger.info(f"=== Pipeline complete — {today} ===")


def _extract_eth_price(stable_market: list[dict]) -> float:
    """Try to extract ETH price from CoinGecko market data, default 2000."""
    return 2000.0  # Will be overridden by live fetches in next iteration


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    args = parser.parse_args()
    run_pipeline()


if __name__ == "__main__":
    main()
