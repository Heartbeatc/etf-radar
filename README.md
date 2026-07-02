# ETF Radar

ETF low-buy, hold, stop-profit, exit, and direction-discovery assistant with API and web frontend.

Tracked ETFs:

- 513120: main, 港股创新药ETF广发
- 159516: main, 半导体设备ETF国泰
- 515880: backup, 通信ETF国泰

Endpoints:

- GET /health
- GET /api/v1/latest
- GET /api/v1/plan
- GET /api/v1/detail/{code}
- GET /api/v1/detail/{code}?entry_price=1.116
- GET /api/v1/positions
- GET /api/v1/discovery
- GET /api/v1/risk
- GET /api/v1/data-quality
- GET /api/v1/integrations
- PUT /api/v1/positions/{code}
- DELETE /api/v1/positions/{code}

Position example:

curl -X PUT http://127.0.0.1:8088/api/v1/positions/513120 \
  -H 'Content-Type: application/json' \
  -d '{"entry_price":1.116,"shares":10000,"note":"manual buy"}'

This service is a research and discipline tool. It does not place orders.

Web frontend:

- The web UI is served by the `web` service. Expose it only through your own firewall, reverse proxy, and access-control policy.
- The browser uses username/password login. It stores only a short-lived signed web session token in localStorage; the backend API token stays server-side.
- The frontend polls latest signals, risk, data quality, and integration health every 30 seconds; direction discovery refreshes every 60 seconds and also supports manual force refresh.
- Bootstrap credentials are runtime-only secrets. Keep them out of source control and delete one-time credential files after first login.

Docker:

```bash
docker compose up -d --build web
```
