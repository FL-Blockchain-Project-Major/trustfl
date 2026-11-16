# Production observability

TrustFL exposes Prometheus-compatible metrics at `/metrics`, W3C
`traceparent` propagation, request IDs, and structured production logs. The
metrics registry is dependency-free and in-process; scraping or exporting it is
optional and cannot prevent the API from starting.

## Signals

The API emits bounded-route request counters, error counters, latency
quantiles, readiness, and rate-limit events. The coordinator emits client
registration, update processing, ZKP verification, and round aggregation
counters/durations. Client IDs, credentials, proofs, model contents, and
request IDs are never metric labels.

`/health/live` is a liveness probe. `/health/ready` checks database, Redis,
production ZKP artifacts, and configured artifact storage without exposing
dependency details. Prometheus configuration, alert rules, and a Grafana
overview are under `observability/`.

## SLO starting points

These are internal targets, not demonstrated guarantees:

| SLI | Window | Target | Error budget |
| --- | --- | --- | --- |
| API non-5xx availability | 30 days | 99.5% | 0.5% |
| API request latency | 30 days | 99% under 2s | 1% |
| Readiness | 30 days | 99.5% | 0.5% |
| Completed rounds | per federation/month | 99% of eligible rounds | 1% |

Round, ZKP, and blockchain objectives require deployment-specific baselines
before numeric targets are adopted.
