# Disaster recovery

## Targets

The initial internal targets are RPO <= 15 minutes for PostgreSQL metadata
(with WAL/PITR enabled) and RTO <= 60 minutes for a regional service outage.
These are targets, not demonstrated guarantees; provider failover and artifact
restore measurements must be recorded during quarterly exercises.

## Recovery procedure

1. Declare the incident and freeze client submissions at the ingress.
2. Promote the PostgreSQL standby or restore the latest verified backup plus
   WAL to a clean environment.
3. Restore replicated artifact/model and ZKP verification-key references.
4. Run migrations and verify database integrity/checksums.
5. Start one coordinator only; its lease acquisition fences stale instances.
6. Reconcile `RECOVERY_REQUIRED` rounds and `blockchain_outbox` records using
   their stable idempotency keys. Never manually replay a submitted event with
   a new key.
7. Verify mandatory ZKP/signature configuration and `/health/ready`.
8. Re-enable ingress and monitor round, outbox, and error-rate metrics.

For node loss, replace the node and let the lease expire or explicitly release
it. For storage loss, restore the artifact by hash and keep the round in
`RECOVERY_REQUIRED` when the hash cannot be verified. For blockchain RPC loss,
leave events in the outbox and use a healthy provider; do not mark them
confirmed locally.
