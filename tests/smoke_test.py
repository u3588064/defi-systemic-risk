"""Smoke test: DeFi data sources + metrics on live API data."""
import sys
sys.path.insert(0, ".")

from src.sources.defillama import get_top_protocols, get_all_bridges, get_lending_rates
from src.sources.coingecko import get_stablecoin_market_data
from src.metrics.stablecoin import analyse_pegs
from src.metrics.leverage import build_leverage_heatmap
from src.metrics.bridge import build_bridge_risk_report
from src.metrics.liquidation import estimate_cascade_from_tvl

print("=== DeFi Smoke Test ===\n")

# 1. DeFiLlama protocols
protos = get_top_protocols(5)
print(f"[1] Top 5 DeFi protocols by TVL:")
for p in protos:
    name = p.get("name", "?")
    tvl = p.get("tvl", 0) / 1e9
    print(f"    {name:20s}  TVL: ${tvl:.2f}B")

# 2. Bridge risk
bridges = get_all_bridges()
print(f"\n[2] Bridges found: {len(bridges)}")
report = build_bridge_risk_report(bridges)
hhi = report.get("concentration", {}).get("hhi", "N/A")
risk = report.get("overall_bridge_risk", "N/A")
print(f"    HHI: {hhi}, Overall risk: {risk}")

# 3. Stablecoin peg stress
stable = get_stablecoin_market_data()
print(f"\n[3] Stablecoins fetched: {len(stable)}")
if stable:
    peg = analyse_pegs(stable)
    print(f"    System stress index: {peg.get('system_peg_stress_index')}%")
    print(f"    Stress level: {peg.get('system_stress_level')}")
    for c in peg.get("coins", [])[:3]:
        print(f"    {c['symbol']:6s} ${c['price_usd']:.4f}  status={c['status']}")

# 4. Protocol leverage
pools = get_lending_rates()
print(f"\n[4] Lending pools fetched: {len(pools)}")
if pools:
    lev = build_leverage_heatmap(pools)
    print(f"    System leverage: {lev.get('system_leverage_pct')}%")
    for p in lev.get("protocols", [])[:3]:
        print(f"    {p['protocol']:15s}  util={p['utilization_pct']}%  stress={p['stress_level']}")

# 5. Liquidation cascade (TVL proxy)
cascade = estimate_cascade_from_tvl(get_top_protocols(50), [0.10, 0.20, 0.40])
print(f"\n[5] Cascade (TVL proxy):")
print(f"    Lending TVL: ${cascade.get('lending_tvl_usd_bn', 0)}B")
for k, v in cascade.get("scenarios", {}).items():
    print(f"    {k}: ${v.get('estimated_liquidatable_usd_bn', 0)}B")

print("\n=== ALL DEFI TESTS PASSED ===")
