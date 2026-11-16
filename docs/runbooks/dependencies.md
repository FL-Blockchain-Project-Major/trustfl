# Dependency readiness

`/health/live` only confirms that the process is running. `/health/ready`
returns `degraded` when database, Redis, production ZKP artifacts, or configured
storage cannot safely serve traffic. Resolve the failing dependency and confirm
the readiness metric returns to `1`; do not restart repeatedly during an outage.
