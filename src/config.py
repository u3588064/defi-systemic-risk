"""
config.py — DeFi Systemic Risk: Central configuration (env-var overridable)
"""

import os
from dataclasses import dataclass


def _float(env, default): return float(os.environ.get(env, default))
def _int(env, default):   return int(os.environ.get(env, default))
def _str(env, default):   return os.environ.get(env, default)


@dataclass
class Config:
    # ── Liquidation cascade ───────────────────────────────────────────────
    cascade_price_drops: list = None   # set in __post_init__
    """Price drop scenarios for cascade simulation (% as decimals)."""

    # ── Stablecoin peg ────────────────────────────────────────────────────
    peg_warn_threshold: float = _float("PEG_WARN_THRESHOLD", 0.005)
    """Absolute deviation from $1.00 that triggers a warning."""

    peg_critical_threshold: float = _float("PEG_CRITICAL_THRESHOLD", 0.02)
    """Absolute deviation from $1.00 triggering a critical alert."""

    # ── Leverage ──────────────────────────────────────────────────────────
    leverage_warn_pct: float = _float("LEVERAGE_WARN_PCT", 75)
    """Historical percentile above which leverage is flagged."""

    # ── Bridge anomaly ────────────────────────────────────────────────────
    bridge_drop_pct: float = _float("BRIDGE_DROP_PCT", 20)
    """Single-day % TVL drop flagged as anomalous."""

    # ── Data / caching ────────────────────────────────────────────────────
    data_dir: str = _str("DATA_DIR", "data")
    raw_dir: str  = _str("RAW_DIR",  "data/raw")

    # ── Graph API ─────────────────────────────────────────────────────────
    graph_api_key: str = _str("GRAPH_API_KEY", "")
    """Optional The Graph API key (free gateway key or Studio key)."""

    # ── Glassnode ─────────────────────────────────────────────────────────
    glassnode_api_key: str = _str("GLASSNODE_API_KEY", "")
    """Optional Glassnode API key (free-tier works with empty key for some endpoints)."""

    # ── CoinGecko ─────────────────────────────────────────────────────────
    coingecko_api_key: str = _str("COINGECKO_API_KEY", "")
    """Optional CoinGecko Pro API key (free demo key also works)."""

    # ── MCP Server ────────────────────────────────────────────────────────
    mcp_host: str = _str("MCP_HOST", "0.0.0.0")
    mcp_port: int = _int("MCP_PORT", 8001)

    # ── GitHub (remote data URL) ──────────────────────────────────────────
    github_repo: str   = _str("GITHUB_REPO", "")
    github_branch: str = _str("GITHUB_BRANCH", "main")

    def __post_init__(self):
        raw = _str("CASCADE_DROPS", "0.10,0.20,0.30,0.40,0.50")
        self.cascade_price_drops = [float(x) for x in raw.split(",")]

    def raw_base_url(self) -> str | None:
        if not self.github_repo:
            return None
        return f"https://raw.githubusercontent.com/{self.github_repo}/{self.github_branch}"


cfg = Config()
