"""
thegraph.py — On-chain lending position data via The Graph Protocol

Protocols covered:
    - Aave V3 (Ethereum mainnet)  subgraph: aave/protocol-v3
    - Aave V2 (Ethereum mainnet)  subgraph: aave/protocol-v2
    - Compound V3                 subgraph: graphprotocol/compound-v3
    - MakerDAO                    subgraph: protofire/makerdao-cdp

The Graph free public gateway (no key required for moderate usage):
    https://gateway.thegraph.com/api/[API_KEY]/subgraphs/id/[SUBGRAPH_ID]

Hosted service (deprecated but still partially works):
    https://api.thegraph.com/subgraphs/name/[SUBGRAPH_NAME]

Strategy:
    1. Try hosted service first (no key).
    2. Fall back to decentralized gateway (requires GRAPH_API_KEY env var).
    3. If both fail, return empty data and log warning.

What we query:
    - User borrow positions: collateral token, collateral USD value,
      borrow token, borrow USD value, health factor.
    - Protocol-level: totalBorrows, totalLiquidity, liquidationThreshold.
"""

import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 30
_DELAY   = 0.5

# Hosted subgraph endpoints (no auth, deprecated mid-2024 but subsets work)
_HOSTED = "https://api.thegraph.com/subgraphs/name"

# Decentralized gateway (requires API key — free key from thegraph.com)
_GATEWAY = "https://gateway.thegraph.com/api"

# Subgraph configurations
_SUBGRAPHS = {
    "aave_v3": {
        "hosted": f"{_HOSTED}/aave/protocol-v3",
        "id": "JCNWRypm7FYwV8fx5HhzZPSFaMxgkPuw4TnWmGmfNvZ",
    },
    "aave_v2": {
        "hosted": f"{_HOSTED}/aave/protocol-v2",
        "id": "8wR23o1zkS4gpLqLNU4kG3JHYVucqGyopL5utGxP2q1N",
    },
    "compound_v3": {
        "hosted": None,  # not on hosted
        "id": "Ff3R6VUAZGiuGxLRYD5KJEsrLWLFXaLxr4SKLmJbhvL",
    },
    "makerdao": {
        "hosted": f"{_HOSTED}/protofire/maker-protocol",
        "id": None,
    },
}


def _query(subgraph_key: str, query: str, variables: dict | None = None) -> dict:
    """
    Execute a GraphQL query against a subgraph, trying hosted then gateway.
    Returns the 'data' dict, or empty dict on failure.
    """
    cfg = _SUBGRAPHS.get(subgraph_key)
    if not cfg:
        logger.warning(f"Unknown subgraph key: {subgraph_key}")
        return {}

    payload = {"query": query, "variables": variables or {}}
    endpoints = []

    # Try hosted first
    if cfg.get("hosted"):
        endpoints.append(cfg["hosted"])

    # Try decentralized gateway
    api_key = os.environ.get("GRAPH_API_KEY", "")
    if cfg.get("id"):
        gw_url = f"{_GATEWAY}/{api_key or 'public'}/subgraphs/id/{cfg['id']}"
        endpoints.append(gw_url)

    for url in endpoints:
        try:
            resp = httpx.post(url, json=payload, timeout=_TIMEOUT)
            resp.raise_for_status()
            result = resp.json()
            if "data" in result and result["data"]:
                return result["data"]
            if "errors" in result:
                logger.debug(f"GraphQL errors from {url}: {result['errors'][:1]}")
        except Exception as e:
            logger.debug(f"Graph query failed [{url}]: {e}")
        finally:
            time.sleep(_DELAY)

    logger.warning(f"All endpoints failed for subgraph '{subgraph_key}'")
    return {}


# ── Aave V3 — collateral / borrow positions ───────────────────────────────

_AAVE_V3_RESERVES_QUERY = """
{
  reserves(first: 50, orderBy: totalLiquidity, orderDirection: desc) {
    name
    symbol
    underlyingAsset
    totalLiquidity
    totalCurrentVariableDebt
    totalCurrentStableDebt
    liquidityRate
    variableBorrowRate
    baseLTVasCollateral
    reserveLiquidationThreshold
    reserveLiquidationBonus
    price { priceInEth }
  }
}
"""

_AAVE_V3_USERS_QUERY = """
query($first: Int, $skip: Int) {
  users(
    first: $first, skip: $skip,
    where: { borrowedReservesCount_gt: 0 },
    orderBy: totalCollateralETH, orderDirection: desc
  ) {
    id
    totalCollateralETH
    totalDebtETH
    availableBorrowsETH
    currentLiquidationThreshold
    healthFactor
    collateral: reserves(where: { currentATokenBalance_gt: 0 }) {
      reserve { symbol underlyingAsset price { priceInEth } }
      currentATokenBalance
    }
    borrows: reserves(where: { currentVariableDebt_gt: "0" }) {
      reserve { symbol underlyingAsset price { priceInEth } }
      currentVariableDebt
    }
  }
}
"""


def get_aave_v3_reserves() -> list[dict]:
    """Get all Aave V3 reserves with liquidity and borrow rates."""
    data = _query("aave_v3", _AAVE_V3_RESERVES_QUERY)
    return data.get("reserves", [])


def get_aave_v3_risky_users(
    max_health_factor: float = 1.5,
    batch_size: int = 1000,
    max_batches: int = 5,
) -> list[dict]:
    """
    Fetch Aave V3 users with health factor below threshold.
    These are the accounts closest to liquidation.
    
    Args:
        max_health_factor : Health factor threshold (1.0 = liquidation boundary).
        batch_size        : Users per GraphQL page.
        max_batches       : Maximum pages to fetch.
    
    Returns:
        List of user positions with collateral, debt, and health factor.
    """
    all_users = []
    for i in range(max_batches):
        data = _query("aave_v3", _AAVE_V3_USERS_QUERY,
                      {"first": batch_size, "skip": i * batch_size})
        users = data.get("users", [])
        if not users:
            break
        # Filter by health factor
        risky = [
            u for u in users
            if u.get("healthFactor") and
               _parse_ray(u["healthFactor"]) <= max_health_factor
        ]
        all_users.extend(risky)
        if len(users) < batch_size:
            break  # last page
    return all_users


# ── Compound V3 ────────────────────────────────────────────────────────────

_COMPOUND_V3_MARKETS_QUERY = """
{
  markets(first: 20, orderBy: totalSupplyUsd, orderDirection: desc) {
    id
    cometProxy
    configuration {
      baseToken { address symbol decimals }
      storeFrontPriceFactor
    }
    totalSupplyUsd
    totalBorrowUsd
    utilization
    supplyApr
    borrowApr
  }
}
"""


def get_compound_v3_markets() -> list[dict]:
    """Get Compound V3 market utilization and rate data."""
    data = _query("compound_v3", _COMPOUND_V3_MARKETS_QUERY)
    return data.get("markets", [])


# ── MakerDAO ─────────────────────────────────────────────────────────────

_MAKER_VAULTS_QUERY = """
query($first: Int, $collateralRatioMax: BigDecimal) {
  cdps(
    first: $first,
    orderBy: collateralizationRatio, orderDirection: asc,
    where: {
      collateralizationRatio_gt: "0",
      collateralizationRatio_lt: $collateralRatioMax
    }
  ) {
    id
    collateral { id }
    collateral_amount
    debt
    collateralizationRatio
    liquidationPrice
  }
}
"""


def get_maker_risky_vaults(
    max_collateral_ratio: float = 2.0,
    limit: int = 500,
) -> list[dict]:
    """Fetch MakerDAO vaults close to their liquidation ratio."""
    data = _query("makerdao", _MAKER_VAULTS_QUERY, {
        "first": limit,
        "collateralRatioMax": str(max_collateral_ratio),
    })
    return data.get("cdps", [])


# ── Helpers ────────────────────────────────────────────────────────────────

def _parse_ray(val: str | float | None, decimals: int = 27) -> float:
    """Convert Aave RAY (1e27) or WAD (1e18) string to float."""
    if val is None:
        return float("nan")
    try:
        return float(val) / (10 ** decimals)
    except (ValueError, TypeError):
        return float("nan")
