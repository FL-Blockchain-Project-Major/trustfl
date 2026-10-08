# TrustFL Operations Dashboard

The Next.js dashboard is a read-only operations console. It polls the FastAPI
control plane every 15 seconds through the server-side `/api/dashboard/*`
proxy, keeping API credentials out of browser bundles.

It provides:

- federation health and active-round metrics
- client heartbeat status and registration details
- update verification and aggregation pipeline status
- model artifact SHA-256 hashes and storage URIs/CIDs
- blockchain transaction status and hashes
- search, status filters, pagination, refresh, loading/error/empty states
- clickable record detail drawers for operational investigation

See [`../../docs/DASHBOARD.md`](../../docs/DASHBOARD.md) for configuration,
API requirements, and current limitations. ZKP is optional/deferred in the
coordinator lifecycle and is not presented as an acceptance guarantee here.
