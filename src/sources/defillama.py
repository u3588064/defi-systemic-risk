"""
defillama.py — DeFiLlama REST API client (completely free, no key required)

Endpoints used:
    https://api.llama.fi/protocols        — All DeFi protocols with TVL
    https://api.llama.fi/protocol/{slug}  — Single protocol detail + historical TVL
    https://bridges.llama.fi/bridges      — All cross-chain bridges with TVL
    https://bridges.llama.fi/bridge/{id}  — Bridge detail
    https://stablecoins.llama.fi/stablecoins — All stablecoins with pegged info
    https://stablecoins.llama.fi/stablecoin/{id} — Stablecoin chain breakdown

DeFiLlama docs: https://defillama.com/docs/api
Rate limits: generous, ~300 req/min. We add a small delay to be polite.
"""

import time
import logging
from functools import lru_cache

import httpx

logger = logging.getLogger(__name__)

_BASE     = "https://api.llama.fi"
_BRIDGES  = "https://bridges.llama.fi"
_STABLE   = "https://stablecoins.llama.fi"

_TIMEOUT  = 30
_DELAY    = 0.3   # seconds between requests


def _get(url: str, params: dict | None = None) -> dict | list | None:
    try:
        resp = httpx.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"DeFiLlama request failed [{url}]: {e}")
        return None
    finally:
        time.sleep(_DELAY)


# ── Protocols ──────────────────────────────────────────────────────────────

def get_all_protocols() -> list[dict]:
    """Return full list of tracked DeFi protocols with current TVL."""
    data = _get(f"{_BASE}/protocols")
    return data if isinstance(data, list) else []


def get_protocol(slug: str) -> dict | None:
    """Return detailed protocol info including TVL history."""
    return _get(f"{_BASE}/protocol/{slug}")


def get_top_protocols(n: int = 50, category: str | None = None) -> list[dict]:
    """Return top N protocols by TVL, optionally filtered by category."""
    all_p = get_all_protocols()
    if category:
        all_p = [p for p in all_p if p.get("category", "").lower() == category.lower()]
    sorted_p = sorted(all_p, key=lambda x: x.get("tvl") or 0, reverse=True)
    return sorted_p[:n]


def get_lending_protocols(top_n: int = 20) -> list[dict]:
    """Top lending protocols (Aave, Compound, MakerDAO, etc.)."""
    return get_top_protocols(n=top_n, category="Lending")


# ── Global TVL ────────────────────────────────────────────────────────────

def get_global_tvl_history() -> list[dict]:
    """Historical daily total DeFi TVL across all chains."""
    data = _get(f"{_BASE}/v2/historicalChainTvl")
    return data if isinstance(data, list) else []


def get_chain_tvls() -> dict | None:
    """Current TVL broken down by chain."""
    return _get(f"{_BASE}/v2/chains")


# ── Bridges ───────────────────────────────────────────────────────────────

def get_all_bridges() -> list[dict]:
    """Return all tracked cross-chain bridges with TVL."""
    data = _get(f"{_BRIDGES}/bridges", params={"includeChains": "true"})
    if isinstance(data, dict):
        return data.get("bridges", [])
    return []


def get_bridge_volume_history(bridge_id: int, period: str = "daily") -> dict | None:
    """Historical bridge volume and net flows."""
    return _get(f"{_BRIDGES}/bridgevolume/{bridge_id}", params={"period": period})


# ── Stablecoins ───────────────────────────────────────────────────────────

def get_all_stablecoins() -> list[dict]:
    """All stablecoins with current peg status and market cap."""
    data = _get(f"{_STABLE}/stablecoins", params={"includePrices": "true"})
    if isinstance(data, dict):
        return data.get("peggedAssets", [])
    return []


def get_stablecoin_history(stablecoin_id: int) -> dict | None:
    """Historical chain-level market cap and peg price for one stablecoin."""
    return _get(f"{_STABLE}/stablecoin/{stablecoin_id}")


def get_stablecoin_prices() -> list[dict]:
    """Current prices of all tracked stablecoins."""
    data = _get(f"{_STABLE}/stablecoinprices")
    return data if isinstance(data, list) else []


# ── Yield / Lending rates ─────────────────────────────────────────────────

def get_pools() -> list[dict]:
    """All yield pools with APY and TVL (covers Aave, Compound, etc.)."""
    data = _get("https://yields.llama.fi/pools")
    if isinstance(data, dict):
        return data.get("data", [])
    return []


def get_lending_rates(protocols: list[str] | None = None) -> list[dict]:
    """Filter yield pools to major lending protocols."""
    _default = {"aave-v3", "aave-v2", "compound-v3", "compound-v2",
                "makerdao", "spark", "morpho-blue", "radiant-v2"}
    targets = set(p.lower() for p in protocols) if protocols else _default
    pools = get_pools()
    return [p for p in pools if p.get("project", "").lower() in targets]
