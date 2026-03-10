# defi-systemic-risk

> Daily DeFi systemic-risk signals **for agents and humans**.  
> Generates a compact JSON snapshot every day and exposes it via **MCP (FastAPI + SSE)** for tool-using agents.

---

## 1) What this repo does (TL;DR)

This project runs a daily pipeline that:
1) Pulls public DeFi market / on-chain / protocol data (CoinGecko, DeFiLlama, The Graph, Glassnode).
2) Computes a small set of **systemic-risk indicators** (stablecoin depeg stress, lending leverage, bridge anomalies, liquidation cascade proxy, on-chain stress).
3) Writes a canonical JSON snapshot to:
- `data/latest.json` (most recent)
- `data/history/YYYY-MM-DD.json` (daily history)
4) Serves the snapshot as **MCP tools** so an agent can query it (SSE transport).

---

## 2) Repository layout (agent-oriented)

```

.
├─ data/
│  ├─ latest.json                # canonical latest snapshot (agent-friendly JSON)
│  └─ history/
│     └─ YYYY-MM-DD.json         # daily snapshots
├─ src/
│  ├─ pipeline.py                # daily pipeline orchestrator (builds the JSON payload)
│  ├─ config.py                  # env-var overridable config
│  ├─ publish.py                 # writes JSON to data/
│  ├─ metrics/                   # all computed risk metrics (pure functions)
│  │  ├─ stablecoin.py           # peg stress index + per-coin flags
│  │  ├─ leverage.py             # protocol leverage / utilization heatmap
│  │  ├─ bridge.py               # bridge concentration + anomaly detection
│  │  └─ liquidation.py          # liquidation cascade simulation (Graph) + fallback proxy
│  └─ sources/                   # API clients for upstream data
│     ├─ coingecko.py
│     ├─ defillama.py
│     ├─ thegraph.py
│     └─ glassnode.py
├─ mcp/
│  └─ server.py                  # MCP server (FastAPI + SSE) exposing tools
├─ tests/
│  └─ smoke_test.py              # live API smoke test
├─ .github/workflows/main.yml    # daily scheduled run + auto-commit data/**
├─ requirements.txt
└─ Procfile                      # deploy-friendly uvicorn entry

````

---

## 3) Quickstart

### 3.1 Local install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
````

### 3.2 Run the daily pipeline (writes JSON)

```bash
python src/pipeline.py
# outputs:
#   data/latest.json
#   data/history/YYYY-MM-DD.json
```

### 3.3 Run the MCP server

```bash
uvicorn mcp.server:app --host 0.0.0.0 --port 8001
# endpoints:
#   GET /health
#   GET /docs
#   GET /sse        (MCP SSE endpoint)
#   POST /messages  (MCP message endpoint)
```

### 3.4 Smoke test (optional)

```bash
python tests/smoke_test.py
```

---

## 4) Configuration (env vars)

> All settings are optional. Defaults are safe and work on free tiers (but may return nulls / fallbacks).

### 4.1 Core thresholds

* `PEG_WARN_THRESHOLD` (default `0.005`)
  Absolute deviation from $1.00 triggering WARNING.
* `PEG_CRITICAL_THRESHOLD` (default `0.02`)
  Absolute deviation from $1.00 triggering CRITICAL.
* `CASCADE_DROPS` (default `0.10,0.20,0.30,0.40,0.50`)
  Price-drop scenarios (fractional) for cascade simulation.
* `BRIDGE_DROP_PCT` (default `20`)
  % daily outflow ratio threshold for bridge anomaly flags.

### 4.2 Data / server wiring

* `DATA_DIR` (default `data`)
* `RAW_DIR` (default `data/raw`)
* `MCP_HOST` (default `0.0.0.0`)
* `MCP_PORT` (default `8001`)

### 4.3 Optional API keys

* `GRAPH_API_KEY` (The Graph gateway key; improves on-chain liquidation simulation)
* `GLASSNODE_API_KEY` (enables more reliable Glassnode calls; free tier may still work partially)
* `COINGECKO_API_KEY` (CoinGecko Pro key; improves rate limits)

### 4.4 Remote-data mode (useful for agents)

If you deploy the MCP server without a local `data/latest.json`, you can fetch from GitHub raw:

* `GITHUB_REPO` (e.g. `u3588064/defi-systemic-risk`)
* `GITHUB_BRANCH` (default `main`)

---

## 5) Data contract (the JSON schema your agent should rely on)

### 5.1 Top-level shape

`data/latest.json` and `data/history/YYYY-MM-DD.json` share the same top-level keys:

```json
{
  "date": "YYYY-MM-DD",
  "generated_at": "ISO-8601 UTC timestamp",
  "methodology_version": "1.0",
  "stablecoin_stress": { ... },
  "protocol_leverage": { ... },
  "bridge_risk": { ... },
  "liquidation_cascade": { ... },
  "onchain_stress": { ... },
  "defi_global": { ... },
  "top_chains_tvl": [ ... ]
}
```

**Units & conventions**

* `*_usd_bn`: USD **billions** (rounded)
* `*_usd_mn`: USD **millions** (rounded)
* `*_pct`: percent values in **0–100** (already multiplied by 100)
* `utilization`: ratio **0–1**
* Some upstream APIs return large numbers as strings; treat them as decimal strings if present.

---

## 6) Metric blocks (what each section means)

### 6.1 `stablecoin_stress` (peg stability)

**Goal:** detect system-wide stablecoin peg fragility.

**Core formula (system index):**
StablecoinStress = Σ (market_cap_i × |price_i − 1|) / Σ market_cap_i
The stored field `system_peg_stress_index` is the above **converted to percent**.

**Fields**

```json
"stablecoin_stress": {
  "total_stablecoin_mcap_usd_bn": 0.0,
  "system_peg_stress_index": 0.0,
  "system_stress_level": "NORMAL|MILD|ELEVATED|CRITICAL",
  "critical_count": 0,
  "warning_count": 0,
  "coins": [
    {
      "id": "coingecko-id",
      "symbol": "USDT",
      "name": "Tether",
      "price_usd": 1.0,
      "peg_deviation": 0.0,
      "peg_deviation_pct": 0.0,
      "status": "STABLE|WARNING|CRITICAL",
      "market_cap_usd_bn": 0.0,
      "volume_24h_usd_bn": 0.0,
      "price_change_24h_pct": 0.0
    }
  ]
}
```

**Agent usage pattern**

* Alert if any coin `status=CRITICAL`
* If `system_peg_stress_index` rises quickly day-over-day → “systemic stablecoin stress rising”
* Use `min_mcap_bn` filtering via MCP tool to reduce noise

---

### 6.2 `protocol_leverage` (lending utilization heatmap)

**Goal:** spot liquidity crunch risk in lending protocols via utilization.

**Definition:**

* `utilization = totalBorrowed / totalSupplied`
* `system_leverage_index` is TVL-weighted average utilization (stored as ratio and percent)

**Fields**

```json
"protocol_leverage": {
  "system_leverage_index": 0.0,
  "system_leverage_pct": 0.0,
  "system_stress_level": "LOW|MODERATE|ELEVATED|HIGH|CRITICAL",
  "total_lending_tvl_usd_bn": 0.0,
  "protocols": [
    {
      "protocol": "aave-v3",
      "tvl_usd_bn": 0.0,
      "total_borrow_usd_bn": 0.0,
      "utilization": 0.0,
      "utilization_pct": 0.0,
      "stress_level": "LOW|MODERATE|ELEVATED|HIGH|CRITICAL",
      "avg_borrow_apy_pct": 0.0,
      "pool_count": 0
    }
  ]
}
```

**Agent usage pattern**

* Track top-N utilization, alert if any protocol is `HIGH/CRITICAL`
* Rising utilization + widening borrow APY can be interpreted as tightening liquidity

---

### 6.3 `bridge_risk` (cross-chain bridge fragility)

**Goal:** detect bridge risk via (a) concentration (HHI) and (b) large daily outflow anomalies.

**Fields**

```json
"bridge_risk": {
  "overall_bridge_risk": "LOW|MODERATE|HIGH",
  "concentration": {
    "hhi": 0.0,
    "concentration_level": "COMPETITIVE|MODERATELY_CONCENTRATED|HIGHLY_CONCENTRATED",
    "total_bridge_tvl_usd_bn": 0.0,
    "bridge_count": 0,
    "top_bridges": [
      { "name": "BridgeName", "tvl_usd_bn": 0.0, "share_pct": 0.0 }
    ]
  },
  "anomaly_count": 0,
  "anomalies": [
    {
      "bridge": "BridgeName",
      "tvl_usd_bn": 0.0,
      "daily_volume_usd_bn": 0.0,
      "outflow_pct": 0.0,
      "severity": "WARNING|CRITICAL"
    }
  ]
}
```

**Agent usage pattern**

* `anomaly_count>0` → possible exploit / bank-run / capital flight signal
* `hhi` high → “bridge layer concentration risk elevated”

---

### 6.4 `liquidation_cascade` (liquidation stress)

**Goal:** estimate how much collateral becomes liquidatable under price drops.

This section has **two possible shapes**:

#### (A) Graph-based simulation (preferred)

Triggered when Aave V3 risky users can be fetched from The Graph.

```json
"liquidation_cascade": {
  "total_positions_analyzed": 1234,
  "scenarios": {
    "drop_10pct": {
      "liquidatable_positions": 0,
      "liquidatable_usd_bn": 0.0,
      "total_collateral_usd_bn": 0.0,
      "cascade_pct_of_tvl": 0.0,
      "top_liquidatable_assets": [
        { "symbol": "WETH", "usd_bn": 0.0 }
      ]
    }
  },
  "methodology": "Aave V3 positions re-priced at hypothetical collateral drops."
}
```

#### (B) TVL-proxy fallback (when Graph fails / no key)

```json
"liquidation_cascade": {
  "method": "TVL-proxy (no Graph data)",
  "lending_tvl_usd_bn": 0.0,
  "avg_ltv_assumption": 0.7,
  "scenarios": {
    "drop_10pct": { "estimated_liquidatable_usd_bn": 0.0 }
  }
}
```

**Agent usage pattern**

* Watch “liquidatable_usd_bn” or “estimated_liquidatable_usd_bn” vs historical baseline
* Combine with leverage + stablecoin stress to produce a “composite systemic alert”

---

### 6.5 `onchain_stress` (BTC/ETH systemic “fear/greed” proxies)

**Goal:** compact on-chain stress snapshot.

```json
"onchain_stress": {
  "btc": { "exchange_balance": null, "mvrv_z_score": null, "sopr": null, "tx_count": null, "price_usd": null },
  "eth": { "exchange_balance": null, "mvrv_z_score": null, "sopr": null, "tx_count": null, "price_usd": null }
}
```

Notes:

* Values can be `null` if Glassnode calls fail or are rate-limited.
* Interpret:

  * rising exchange balance = sell pressure
  * SOPR < 1 sustained = capitulation
  * MVRV Z-score extreme high = overheating

---

### 6.6 `defi_global` and `top_chains_tvl` (macro context)

**Goal:** give context for the risk indicators.

`defi_global` is CoinGecko DeFi macro stats (may include large numeric strings).
`top_chains_tvl` is top chains by TVL (USD billions).

---

## 7) MCP interface (tools for agents)

The MCP server exposes the following tools:

* `get_chain_overview() -> dict`
  Returns: `date`, `defi_global`, `top_chains_tvl`, stablecoin summary, `onchain_stress`.

* `get_stablecoin_stress(date: str | None = None, min_mcap_bn: float = 0.1) -> dict`
  Returns stablecoin stress block; optional historical date.

* `get_liquidation_cascade(asset: str = "ETH", drop_pct: float | None = None) -> dict`
  Returns full cascade block or a single scenario (e.g. 20%).

* `get_protocol_leverage(top_n: int = 10, stress_level: str | None = None) -> dict`
  Returns leverage block filtered for top-N and/or stress level.

* `get_bridge_risk(date: str | None = None) -> dict`
  Returns bridge risk block; optional historical date.

* `get_methodology() -> dict`
  Returns methodology summary + thresholds.

---

## 8) Application scenarios (how to use this in the real world)

### 8.1 Real-time monitoring & alerting (agent)

* Watch `stablecoin_stress.coins[*].status` for CRITICAL depegs
* Watch `bridge_risk.anomalies` for potential exploit / capital flight
* Watch `liquidation_cascade` for “cascade magnitude” spikes
* Summarize daily, send alerts to Slack/Email/incident channel

### 8.2 Research / backtesting dataset

* Use `data/history/*.json` as a daily time series of systemic-risk features
* Build your own composite index or train a forecasting model

### 8.3 Dashboard / API backend

* Serve `data/latest.json` as a “public snapshot”
* Use MCP tools as the agent-facing API layer

### 8.4 Incident response playbooks

* When a depeg happens: correlate with bridge anomalies + leverage tightness
* When a bridge anomaly triggers: check stablecoins + liquidation cascade estimates

---

## 9) Known limitations (important for agent reasoning)

* Public APIs are rate-limited; nulls / fallbacks are expected in free mode.
* Liquidation cascade:

  * Graph-based simulation covers Aave V3 (and is only as good as Graph data availability).
  * TVL-proxy fallback is a coarse approximation.
* Some parameters (e.g. ETH price extraction) may be simplified placeholders; treat outputs as signals, not oracle truth.
* Protocol leverage depends on DeFiLlama yield fields; missing borrow fields can reduce fidelity.

---

## 10) Automation

This repo is configured to run daily (GitHub Actions cron) and auto-commit fresh snapshots to `data/**`.

---

## License

MIT


[1]: https://raw.githubusercontent.com/u3588064/defi-systemic-risk/main/data/latest.json "raw.githubusercontent.com"
