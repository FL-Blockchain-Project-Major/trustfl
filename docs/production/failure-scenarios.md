# Failure scenarios and validation

| Failure | Expected behavior | Operator action |
| --- | --- | --- |
| API replica loss | Load balancer removes unhealthy instance | Wait for readiness and replace |
| Coordinator loss | Lease expires; replacement acquires fencing lease | Inspect `RECOVERY_REQUIRED` rounds |
| PostgreSQL failover | API becomes unready until new primary is available | Promote standby/PITR restore |
| Redis outage | Production readiness degrades and rate limiting cannot be trusted | Restore Sentinel/managed Redis |
| Artifact loss | Hash verification fails; round is not published | Restore object by immutable hash |
| RPC timeout | Outbox retries with bounded backoff | Reconcile after provider recovery |
| Interrupted aggregation | Durable round remains recoverable | Resume only after artifact/hash checks |

Quarterly recovery exercises must create a disposable database, restore an
encrypted backup, run migrations, verify an outbox event is processed once, and
record measured RPO/RTO. CI covers lease fencing and backup script validation;
provider-specific PostgreSQL failover, PITR, and object-storage replication
remain deployment exercises.
