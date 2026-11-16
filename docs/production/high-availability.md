# High availability

## Architecture

```text
clients -> load balancer -> API replicas -> PostgreSQL HA + Redis HA
                                      \-> replicated artifact storage
coordinator replicas -- DB fencing lease -> one active FL executor
                                      \-> blockchain RPC failover endpoints
```

The API is stateless and may be replicated. The coordinator is stateful at the
execution boundary: every instance must use the same PostgreSQL database and
must acquire the per-federation `coordinator_leases` fencing lease. Only the
lease holder may execute rounds, aggregation, or outbox work; lease loss
fences the instance and aborts its in-memory execution. The database lease is
not a replacement for PostgreSQL HA.

PostgreSQL requires a managed HA service or primary/standby deployment with
streaming replication, synchronous durability appropriate to the RPO, and
automated failover. Redis must use Sentinel/Cluster or a managed equivalent;
the application uses Redis only for distributed rate limiting and can be
restarted after Redis recovery. Artifact storage must be replicated object
storage or a replicated IPFS pinning service; local volumes are development
only. Blockchain RPC requires at least two provider endpoints behind a
health-checked failover policy.

Rolling deployments must wait for `/health/ready`, drain the old instance, and
never run a second coordinator without the database lease. The lease TTL is
30 seconds and is renewed by the coordinator monitor.
