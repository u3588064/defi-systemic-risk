"""
server.py — DeFi Systemic Risk MCP Server (FastAPI + SSE transport)

Exposes DeFi systemic risk metrics via the Model Context Protocol.
Transport: HTTP/SSE. Default: http://0.0.0.0:8001

Run:
    python mcp/server.py
    uvicorn mcp.server:app --host 0.0.0.0 --port 8001
"""

import json
import logging
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import cfg

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("defi-mcp")

mcp = FastMCP(
    name="defi-systemic-risk",
    description=(
        "Real-time DeFi systemic risk metrics: stablecoin peg stress, "
        "liquidation cascades, protocol leverage, and cross-chain bridge anomalies."
    ),
)

DATA_DIR = Path(cfg.data_dir)


def _load_latest() -> dict:
    local = DATA_DIR / "latest.json"
    if local.exists():
        return json.loads(local.read_text(encoding="utf-8"))
    base = cfg.raw_base_url()
    if base:
        try:
            return httpx.get(f"{base}/data/latest.json", timeout=10).json()
        except Exception as e:
            logger.warning(f"Remote fetch failed: {e}")
    return {}


def _load_snapshot(date: str) -> dict:
    local = DATA_DIR / "history" / f"{date}.json"
    if local.exists():
        return json.loads(local.read_text(encoding="utf-8"))
    base = cfg.raw_base_url()
    if base:
        try:
            return httpx.get(f"{base}/data/history/{date}.json", timeout=10).json()
        except Exception:
            pass
    return {}


# ── MCP Tools ─────────────────────────────────────────────────────────────

@mcp.tool()
def get_chain_overview() -> dict:
    """
    Get a high-level DeFi ecosystem snapshot:
    total TVL, stablecoin market cap, key protocol counts,
    and top chains by TVL.
    """
    data = _load_latest()
    if not data:
        return {"error": "No data available. Run the pipeline first."}

    return {
        "date": data.get("date"),
        "defi_global": data.get("defi_global", {}),
        "top_chains_tvl": data.get("top_chains_tvl", []),
        "stablecoin_summary": {
            k: v for k, v in data.get("stablecoin_stress", {}).items()
            if k in ("total_stablecoin_mcap_usd_bn", "system_peg_stress_index",
                     "system_stress_level", "critical_count", "warning_count")
        },
        "onchain_stress": data.get("onchain_stress", {}),
    }


@mcp.tool()
def get_stablecoin_stress(
    date: str | None = None,
    min_mcap_bn: float = 0.1,
) -> dict:
    """
    Get stablecoin peg stress analysis.

    Args:
        date        : YYYY-MM-DD for historical snapshot. Default: latest.
        min_mcap_bn : Only return stablecoins with market cap above this (USD bn).

    Returns:
        System stress index, per-coin peg deviation, and critical alerts.
    """
    data = _load_snapshot(date) if date else _load_latest()
    if not data:
        return {"error": f"No data for {date or 'latest'}."}

    stress = data.get("stablecoin_stress", {})
    if min_mcap_bn > 0:
        stress["coins"] = [
            c for c in stress.get("coins", [])
            if c.get("market_cap_usd_bn", 0) >= min_mcap_bn
        ]
    return stress


@mcp.tool()
def get_liquidation_cascade(
    asset: str = "ETH",
    drop_pct: float | None = None,
) -> dict:
    """
    Get liquidation cascade estimates at various price-drop scenarios.

    Args:
        asset    : Asset to stress-test ('ETH' or 'BTC'). Informational filter.
        drop_pct : If provided, return only this specific drop scenario
                   (e.g. 20.0 for 20% drop). Otherwise return all scenarios.

    Returns:
        Cascade estimates showing how much collateral becomes liquidatable
        at each hypothetical price drop.
    """
    data = _load_latest()
    cascade = data.get("liquidation_cascade", {})
    if not cascade:
        return {"error": "No liquidation data available."}

    if drop_pct is not None:
        key = f"drop_{int(drop_pct)}pct"
        scenarios = cascade.get("scenarios", {})
        scenario = scenarios.get(key)
        if not scenario:
            available = list(scenarios.keys())
            return {"error": f"Scenario '{key}' not found. Available: {available}"}
        return {
            "date": data.get("date"),
            "asset": asset,
            "drop_pct": drop_pct,
            **scenario,
            "methodology": cascade.get("methodology"),
        }

    return {
        "date": data.get("date"),
        "asset": asset,
        **cascade,
    }


@mcp.tool()
def get_protocol_leverage(
    top_n: int = 10,
    stress_level: str | None = None,
) -> dict:
    """
    Get DeFi lending protocol leverage heatmap.

    Args:
        top_n        : Return top N most leveraged protocols. Default 10.
        stress_level : Filter by stress level: LOW | MODERATE | ELEVATED | HIGH | CRITICAL.

    Returns:
        System leverage index and per-protocol utilization ranking.
    """
    data = _load_latest()
    leverage = data.get("protocol_leverage", {})
    if not leverage:
        return {"error": "No leverage data available."}

    protocols = leverage.get("protocols", [])
    if stress_level:
        protocols = [p for p in protocols
                     if p.get("stress_level") == stress_level.upper()]
    leverage["protocols"] = protocols[:top_n]
    return leverage


@mcp.tool()
def get_bridge_risk(date: str | None = None) -> dict:
    """
    Get cross-chain bridge risk report.

    Args:
        date : YYYY-MM-DD for historical snapshot. Default: latest.

    Returns:
        Bridge concentration (HHI), anomalies, and overall risk level.
    """
    data = _load_snapshot(date) if date else _load_latest()
    return data.get("bridge_risk", {"error": "No bridge data available."})


@mcp.tool()
def get_methodology() -> dict:
    """Return full methodology documentation for all DeFi risk metrics."""
    return {
        "title": "DeFi Systemic Risk Metrics — Methodology",
        "version": "1.0",
        "metrics": {
            "Stablecoin Peg Stress Index": {
                "formula": "Σ (market_cap_i × |price_i - 1.0|) / Σ market_cap_i",
                "description": "Market-cap-weighted average peg deviation across all tracked stablecoins.",
                "thresholds": {"warning": "0.5%", "critical": "2.0%"},
                "source": "CoinGecko free API",
            },
            "Liquidation Cascade": {
                "formula": "Σ collateral_USD_i × 1(stressed_HF_i < 1.0)",
                "description": "Sum of collateral value that becomes liquidatable when re-priced at hypothetical drop.",
                "primary_source": "Aave V3 via The Graph (on-chain positions)",
                "fallback_source": "DeFiLlama TVL proxy method",
                "scenarios": cfg.cascade_price_drops,
            },
            "Protocol Leverage Heatmap": {
                "formula": "utilization = totalBorrowed / totalSupplied",
                "system_index": "TVL-weighted average utilization",
                "source": "DeFiLlama Yields API (free)",
                "stress_thresholds": {"HIGH": "80%", "CRITICAL": "90%"},
            },
            "Bridge Concentration (HHI)": {
                "formula": "HHI = Σ (TVL_i / totalTVL)² × 10000",
                "description": "Herfindahl-Hirschman Index. Higher = more concentrated = more fragile.",
                "thresholds": {"competitive": "<1500", "concentrated": ">2500"},
                "source": "DeFiLlama Bridges API (free)",
            },
            "On-Chain Stress Indicators": {
                "mvrv_z_score": "Overheating signal. >7 = extreme bull; <0 = capitulation.",
                "sopr": "Profit ratio. Sustained <1 = seller capitulation.",
                "exchange_balance": "Rising = sell pressure. Falling = accumulation.",
                "source": "Glassnode free tier (BTC & ETH)",
            },
        },
        "data_update_frequency": "Daily via GitHub Actions (UTC 02:00)",
        "parameters": {
            "peg_warn_threshold": cfg.peg_warn_threshold,
            "peg_critical_threshold": cfg.peg_critical_threshold,
            "bridge_drop_threshold_pct": cfg.bridge_drop_pct,
            "cascade_scenarios": cfg.cascade_price_drops,
        },
    }


# ── FastAPI app ────────────────────────────────────────────────────────────

app = FastAPI(title="DeFi Systemic Risk MCP", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

sse = SseServerTransport("/messages")


@app.get("/sse")
async def sse_endpoint(request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await mcp._mcp_server.run(
            streams[0], streams[1], mcp._mcp_server.create_initialization_options()
        )


@app.post("/messages")
async def messages_endpoint(request):
    await sse.handle_post_message(request.scope, request.receive, request._send)


@app.get("/health")
async def health():
    return {"status": "ok", "server": "defi-systemic-risk-mcp", "version": "1.0.0"}


@app.get("/")
async def root():
    return {"name": "DeFi Systemic Risk MCP Server", "mcp_endpoint": "/sse",
            "docs": "/docs", "health": "/health"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("mcp.server:app", host=cfg.mcp_host, port=cfg.mcp_port, reload=False)
