# ETF Radar Architecture

## Current Stage

ETF Radar is currently a high-quality modular monolith: one deployable Docker service, with code boundaries aligned to future microservices.

This keeps operating cost low while avoiding a rewrite when Kafka, ClickHouse, PostgreSQL, Redis, or Kubernetes are introduced.

## Module Boundaries

```text
app/api          HTTP routes, authentication, request/response boundary
app/core         settings, runtime orchestration, market calendar/status
app/domain       Pydantic domain models and API contracts
app/adapters     external systems: market data source, SQLite store
app/services     business capabilities: scoring, AI, alerts, backtest
```

Compatibility shims remain at `app/models.py`, `app/store.py`, etc. New code should import from the structured packages above.

## Runtime Flow Today

```text
Eastmoney source
  -> adapters.eastmoney
  -> core.runtime poll loop
  -> adapters.store SQLite snapshots/history
  -> services.scoring signal plans
  -> services.alerts optional webhook events
  -> services.ai DeepSeek cached explanation
  -> api.routes FastAPI responses
```

## Future Microservice Split Points

The current packages map directly to these future services:

```text
collector-service      app/adapters/eastmoney + source normalization
signal-worker          app/services/scoring + risk rules
alert-worker           app/services/alerts
backtest-worker        app/services/backtest
api-service            app/api + read models
ai-explainer-service   app/services/ai
```

## Kafka / Redpanda Role

Kafka or Redpanda should be introduced when polling more instruments, consuming professional market feeds, or running multiple workers.

It should carry immutable events:

```text
market.raw.tick
market.normalized.snapshot
feature.updated
signal.generated
risk.triggered
alert.requested
```

Kafka provides decoupling, buffering, replay, and horizontal worker scaling. It is the event bus, not the trading logic engine.

## ClickHouse Role

ClickHouse should be introduced for analytical history:

```text
etf_snapshots
etf_minute_bars
factor_values
signal_history
fund_flow_snapshots
backtest_observations
```

It is for fast historical analysis, signal validation, and backtest statistics. It should not replace PostgreSQL for user/config/position state.

## Storage Direction

Current:

```text
SQLite for all persisted MVP state
```

Next durable split:

```text
PostgreSQL: positions, config, users, API tokens, job state
Redis: cache, locks, latest small hot state, rate limits
ClickHouse: market/factor/signal analytical history
Object storage: raw vendor files or large archived payloads
```

## Scaling Rule

Do not scale by duplicating the current poll loop blindly. Horizontal scaling should happen after introducing a lease/lock or Kafka partitioning.

Safe scaling path:

1. Keep one collector while API can scale read-only.
2. Move signal generation to event-driven workers.
3. Partition by ETF code or sector topic.
4. Store analytical history in ClickHouse.
5. Move stateful config to PostgreSQL and short-lived locks/cache to Redis.

## Quality Principles

- API layer must not know vendor-specific field names.
- Business services must not directly perform HTTP calls unless they are adapters.
- Storage access stays behind adapter interfaces.
- AI explains signals; it does not create trading truth.
- Backtests must always disclose assumptions and limitations.
- Every trading signal should be traceable to source data and rule evidence.

## Kafka / ClickHouse Deployment Added

Current Docker deployment now includes:

```text
etf-radar API container, read-oriented and no longer owning the poll loop
etf-collector worker, owns Eastmoney polling, source status, history refresh, Kafka snapshot/status publishing
etf-radar-signal-worker worker, consumes Kafka market snapshots and emits rule-based trade signals
redpanda Kafka-compatible broker, internal Docker network only
clickhouse analytical database, internal Docker network only
```

The public surface remains FastAPI on port `8088`. Redpanda and ClickHouse are intentionally not exposed to the public internet.

Collector and signal worker write three event/data streams:

```text
Kafka topic etf_radar.market.normalized.snapshot
Kafka topic etf_radar.signal.generated
Kafka topic etf_radar.source.status

ClickHouse table etf_snapshots
ClickHouse table signal_history
ClickHouse table source_status
```

SQLite remains the operational store for the MVP. ClickHouse is now the analytical store. Kafka/Redpanda is now the event bus. If either integration is temporarily unavailable, the API continues serving from SQLite and reports the integration error via `/api/v1/integrations`.

The system is now a modular service deployment: API, collector, and signal worker are separate processes that reuse the same domain services and adapters. The signal worker has no fixed `container_name`, so it can be scaled with Docker Compose when topic partitions and downstream write semantics are acceptable. The collector should remain singleton until a lease/lock is introduced.

## PostgreSQL / Redis Deployment Added

Current Docker deployment also includes:

```text
postgres operational database, internal Docker network only
redis hot-state cache, internal Docker network only
```

PostgreSQL is initialized with the first operational schema:

```text
schema_meta      schema version tracking
positions        future ETF position and execution-state source of truth
system_locks     future singleton job leases and safe horizontal scaling locks
job_runs         future collector/backtest/alert job audit trail
```

Redis is currently wired for health checks and is reserved for short-lived hot state:

```text
latest API response cache
source freshness cache
rate limits
idempotency keys
distributed locks with TTL
```

Important boundary: SQLite still remains the MVP operational store for snapshots, current positions, and generated signal records until a deliberate migration is implemented and verified. PostgreSQL/Redis are now deployed and observable through `/api/v1/integrations`, but they are not yet the canonical trading state path.

The new risk and validation APIs are:

```text
GET /api/v1/data-quality
GET /api/v1/risk
GET /api/v1/backtest-summary
```

These endpoints make source freshness, low-buy risk, take-profit state, and replay assumptions visible before a trading decision is made.

## Free Quote Fallback

Spot quotes now use a market-data facade:

```text
Eastmoney primary spot source
  -> Tencent free quote fallback when primary spot source fails
```

Tencent is only a free fallback source. It can provide price, volume, amount, source time, IOPV, and premium/discount for the tracked ETF list, but it is not treated as a professional paid feed. When fallback data is used, snapshots carry `source="tencent"`, data quality is slightly discounted, and `/api/v1/data-quality` exposes the source field.

Current ETF selection boundary: the tracked ETF list is still configured by `MAIN_ETF_CODES` and `BACKUP_ETF_CODES`. Scores are dynamic, but full-market ETF discovery is not yet automatic.

## ETF Direction Discovery

The system now has a separate full-market ETF discovery API:

```text
GET /api/v1/discovery
```

Discovery uses the free Eastmoney ETF universe list, filters out low-liquidity and cash/bond-like products, classifies ETFs into direction buckets, then returns exactly two main candidates plus one backup candidate. It is intentionally separate from the configured trading watchlist: discovery can suggest candidates, but it does not automatically rewrite `MAIN_ETF_CODES` or `BACKUP_ETF_CODES`.

Current discovery evidence includes same-day strength, liquidity, volume ratio, turnover, estimated big-order flow, ETF premium/discount, and intraday amplitude risk. High same-day strength is treated as direction confirmation and may still receive an entry bias of `direction_hot_wait_pullback`.


## Web Frontend

The deployment now includes a dedicated frontend container:

```text
etf-radar-web, React + TypeScript + Ant Design static app served by Nginx
```

The web container is intentionally thin. It does not contain the API token, trading rules, or market-data adapters. Browser requests go to Nginx on port `8090`, and Nginx proxies `/api/*` and `/health` to the internal FastAPI service at `etf-radar:8088`.

Frontend refresh policy:

```text
latest signals / risk / data quality / integrations: 30 seconds
direction discovery: 60 seconds plus manual force refresh
```

This keeps the API service as the source of truth while giving the user a compact operations console for direction discovery, low-buy zones, take-profit levels, exit levels, source quality, and infrastructure status.

## Web Authentication

The web UI no longer asks for the backend `API_TOKEN`. It uses a dedicated login endpoint:

```text
POST /api/v1/auth/login -> signed web session token
GET  /api/v1/auth/session -> current session metadata
POST /api/v1/auth/logout -> client-side session cleanup acknowledgement
```

The original static API token remains valid for scripts and operational API calls. Browser users authenticate with `WEB_USERNAME` and `WEB_PASSWORD_HASH`; the server signs short-lived session tokens with `WEB_SESSION_SECRET`.

Bootstrap credentials are local runtime secrets stored outside source control and should be deleted after first login. The service itself reads only the password hash and session secret from `.env`.
