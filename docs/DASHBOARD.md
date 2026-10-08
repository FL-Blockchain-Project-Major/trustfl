# TrustFL Operations Dashboard

The dashboard is a read-only Next.js operations console backed by the FastAPI
control plane. It displays persisted metadata; it does not call the coordinator
directly and it never receives blockchain or API private keys.

## Running it

```bash
cd apps/dashboard
npm ci
npm run dev
```

Open <http://localhost:3000>. In Compose, the dashboard is started with
`docker compose up --build`.

The browser calls `/api/dashboard/*` on the Next.js server. That server-side
proxy adds `API_READ_KEY` (or the explicitly supported development
`API_SECRET_KEY`) and forwards only GET requests to `INTERNAL_API_URL` or
`NEXT_PUBLIC_API_URL`. Do not prefix an API credential with `NEXT_PUBLIC_`.

## Console features

- Federation selector and control-plane health
- Active round, online clients, verified updates, artifact count, and
  blockchain confirmation metrics
- Overview of the update and aggregation pipeline
- Rounds, clients, updates, artifacts, and blockchain transaction tabs
- Status filtering and text search
- Eight-row pagination for each operational table
- Clickable rows with a record detail drawer
- Loading, empty, API-error, retry, and unavailable-federation states
- Automatic refresh every 15 seconds and a manual refresh action

Artifacts show their SHA-256 hash and storage URI/CID when the API has recorded
one. ZKP status is not presented as proof of coordinator acceptance because ZKP
verification is optional/deferred in the current runtime.

## API requirements

The dashboard requires the following read endpoints:

- `GET /federations/`
- `GET /clients/federation/{federation_id}`
- `GET /rounds/federation/{federation_id}`
- `GET /updates/federation/{federation_id}`
- `GET /artifacts/federation/{federation_id}`
- `GET /blockchain/transactions`

The last endpoint is the read API for the blockchain transaction table. It is
paginated with `skip` and `limit` query parameters.

## Operational limitations

The dashboard is an observability surface, not an administrative control
plane. It cannot start rounds, approve updates, change client status, or
manage secrets. Live status is polling-based rather than WebSocket-based, so a
value can be up to 15 seconds old. Pagination is client-side over the bounded
dashboard result set; high-volume deployments should add server-side filtered
list endpoints before removing the 100-record dashboard cap.
