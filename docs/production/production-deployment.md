# TrustFL Production Deployment Guide

> **Status:** Deployment infrastructure ready. External dependencies (managed PostgreSQL,
> Redis, blockchain RPC endpoint, IPFS pinning service, container registry) must be
> provisioned separately before go-live. No horizontal scalability or HA is claimed without
> demonstrated multi-instance tests in your target environment.

---

## Table of Contents

1. [External Dependency Requirements](#1-external-dependency-requirements)
2. [Secrets Management](#2-secrets-management)
3. [Container Image Preparation](#3-container-image-preparation)
4. [Kubernetes Deployment](#4-kubernetes-deployment)
5. [Database Migrations](#5-database-migrations)
6. [Production Validation Checklist](#6-production-validation-checklist)
7. [Rolling Upgrades and Rollback](#7-rolling-upgrades-and-rollback)
8. [Key Rotation and Revocation](#8-key-rotation-and-revocation)
9. [Incident Response](#9-incident-response)
10. [Known Limitations](#10-known-limitations)

---

## 1. External Dependency Requirements

TrustFL requires these external services to be provisioned **before** deployment:

| Service | Minimum requirement | Notes |
|:--------|:--------------------|:------|
| **PostgreSQL** | 15+ with connection pooling (PgBouncer recommended) | HA with streaming replication for production. WAL/PITR for RPO ≤ 15 min |
| **Redis** | 7+ (Sentinel or Cluster for HA) | Used for distributed rate limiting only. Can be restarted without data loss |
| **Blockchain RPC** | Any EVM-compatible endpoint | Two providers recommended for failover. Infura, Alchemy, or self-hosted |
| **IPFS / Artifact Storage** | Pinning service (Pinata, Web3.Storage) or replicated IPFS cluster | Local IPFS is development-only |
| **Container Registry** | GHCR, ECR, or GCR | Images published by the CI pipeline |
| **Secrets Manager** | GCP Secret Manager, AWS Secrets Manager, or HashiCorp Vault | Private keys and bearer tokens must never be in env vars or ConfigMaps |
| **TLS Certificates** | cert-manager + Let's Encrypt or managed cert service | Required for HTTPS ingress |
| **DNS** | A/CNAME records for `api.` and `dashboard.` subdomains | |

---

## 2. Secrets Management

### Required secrets

All secrets must be injected at runtime through your secrets manager — never committed
to source control or baked into container images.

| Secret name | Description | Rotation frequency |
|:------------|:------------|:-------------------|
| `API_READ_KEY` | Bearer token for read-scoped API access | 90 days |
| `API_WRITE_KEY` | Bearer token for write-scoped API access | 90 days |
| `API_ADMIN_KEY` | Bearer token for administrative API access | 30 days |
| `COORDINATOR_PRIVATE_KEY` | Ed25519/ECDSA private key for update signing | On compromise only; planned annually |
| `COORDINATOR_ENROLLMENT_TOKEN` | Shared token for client enrollment | 30 days |
| `COORDINATOR_ENROLLMENT_ALLOWLIST` | JSON map of `{client_id: base64_public_key}` | On client provisioning |
| `DASHBOARD_ACCESS_KEY` | Bearer token for dashboard proxy access | 90 days |
| `DATABASE_URL` | PostgreSQL connection string with credentials | On password rotation |
| `REDIS_URL` | Redis connection string with password | 90 days |

### Key injection for Kubernetes

Use External Secrets Operator (ESO) or Secrets Store CSI Driver to sync secrets
from your cloud provider:

```yaml
# Example: GCP Secret Manager via ESO
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: trustfl-api-keys
  namespace: trustfl
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: gcp-secret-manager
    kind: ClusterSecretStore
  target:
    name: trustfl-api-keys
  data:
    - secretKey: read-key
      remoteRef:
        key: trustfl-api-read-key
    - secretKey: write-key
      remoteRef:
        key: trustfl-api-write-key
    - secretKey: admin-key
      remoteRef:
        key: trustfl-api-admin-key
```

### Key rotation procedure

1. Generate new credentials in your secrets manager.
2. Update the secret version — ESO/CSI driver will sync to the cluster.
3. Trigger a rolling restart: `kubectl rollout restart deployment/trustfl-api -n trustfl`
4. For coordinator private key rotation: coordinate with client allowlist update (see §8).
5. Verify all health probes pass after restart.
6. Revoke the old secret version after confirming stability (minimum 1 hour window).

> [!CAUTION]
> Never rotate the `COORDINATOR_PRIVATE_KEY` without simultaneously updating the
> allowlist and communicating the new key to enrolled clients. An in-flight round
> will fail if the signing key changes mid-round.

---

## 3. Container Image Preparation

### Verify image signatures before deployment

All release images are signed with Cosign. Verify before pulling:

```bash
export TRUSTFL_VERSION=0.1.0
export IMAGE_REGISTRY=ghcr.io/fl-blockchain-project-major/trustfl

for service in api coordinator client dashboard; do
  cosign verify \
    --certificate-identity-regexp="https://github.com/FL-Blockchain-Project-Major/trustfl" \
    --certificate-oidc-issuer="https://token.actions.githubusercontent.com" \
    "${IMAGE_REGISTRY}/${service}:${TRUSTFL_VERSION}"
done
```

### Pin images by digest (required for production)

Never deploy with a mutable tag like `latest`. Get the digest and pin it:

```bash
# Get digest for a pinned tag
export DIGEST=$(crane digest "${IMAGE_REGISTRY}/api:${TRUSTFL_VERSION}")
echo "api image: ${IMAGE_REGISTRY}/api@${DIGEST}"
```

Update your Kustomize overlay or Helm values to use `@sha256:<digest>`.

---

## 4. Kubernetes Deployment

### Prerequisites

- `kubectl` configured for your cluster
- `kustomize` v5+ or `kubectl kustomize`
- Secrets provisioned (§2)
- Namespace does not already exist (Kustomize creates it)

### Deploy with Kustomize

```bash
# Review what will be applied
kubectl kustomize deploy/k8s/overlays/production | less

# Apply (dry-run first)
kubectl kustomize deploy/k8s/overlays/production | kubectl apply --dry-run=server -f -

# Apply for real
kubectl kustomize deploy/k8s/overlays/production | kubectl apply -f -
```

### Deploy with Helm

```bash
# Install (first time)
helm install trustfl deploy/helm/trustfl \
  --namespace trustfl --create-namespace \
  --set global.imageTag="${TRUSTFL_VERSION}" \
  --set api.secrets.readKey="${API_READ_KEY}" \
  --set api.secrets.writeKey="${API_WRITE_KEY}" \
  --set api.secrets.adminKey="${API_ADMIN_KEY}" \
  --set api.secrets.databaseUrl="${DATABASE_URL}" \
  --set api.secrets.redisUrl="${REDIS_URL}" \
  --set coordinator.secrets.privateKey="${COORDINATOR_PRIVATE_KEY}" \
  --set coordinator.secrets.enrollmentToken="${COORDINATOR_ENROLLMENT_TOKEN}" \
  --set coordinator.secrets.databaseUrl="${DATABASE_URL}" \
  --set config.blockchainRpcUrl="${BLOCKCHAIN_RPC_URL}" \
  --set config.corsAllowedOrigins="${CORS_ALLOWED_ORIGINS}"
```

### Verify deployment health

```bash
# Wait for rollout
kubectl rollout status deployment/trustfl-api -n trustfl
kubectl rollout status deployment/trustfl-coordinator -n trustfl

# Check all pods are Running
kubectl get pods -n trustfl

# Verify API readiness
kubectl exec -n trustfl deploy/trustfl-api -- \
  python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready')"
```

---

## 5. Database Migrations

Alembic manages schema migrations. Always run migrations **before** deploying a new
coordinator or API version.

```bash
# Run as a one-off Job in Kubernetes (recommended)
kubectl run trustfl-migrate \
  --image=ghcr.io/fl-blockchain-project-major/trustfl/api:${TRUSTFL_VERSION} \
  --restart=Never \
  --env="DATABASE_URL=${DATABASE_URL}" \
  --command -- alembic -c apps/api/alembic.ini upgrade head

# Wait for completion
kubectl wait pod/trustfl-migrate --for=condition=Succeeded --timeout=120s
kubectl logs pod/trustfl-migrate
kubectl delete pod/trustfl-migrate
```

### Rollback migrations

```bash
# Roll back one migration step
kubectl run trustfl-migrate-down \
  --image=ghcr.io/fl-blockchain-project-major/trustfl/api:${TRUSTFL_VERSION} \
  --restart=Never \
  --env="DATABASE_URL=${DATABASE_URL}" \
  --command -- alembic -c apps/api/alembic.ini downgrade -1
```

> [!WARNING]
> Migration rollback may be destructive for schema changes that drop columns or tables.
> Always take a PostgreSQL backup (see `docs/production/backup-and-restore.md`) before
> running `downgrade`.

---

## 6. Production Validation Checklist

After deployment, verify every item before declaring production-ready:

### Security gates

- [ ] `ENVIRONMENT=production` is set in all application containers
- [ ] `COORDINATOR_REQUIRE_ZKP=true` — verified via `/health/ready`
- [ ] `COORDINATOR_INSECURE_DEV_AUTH=false`
- [ ] `API_LEGACY_AUTH_COMPAT=false`
- [ ] `CLIENT_ENROLLMENT_AUTO_APPROVE=false`
- [ ] All API keys are ≥ 32 characters, randomly generated, stored only in secrets manager
- [ ] Coordinator private key is from a KMS/HSM or secrets manager, not hardcoded
- [ ] No Hardhat devchain in the production stack

### Functional validation

```bash
# Confirm unauthenticated access is rejected
curl -i http://api.trustfl.example.com/federations/
# Expected: HTTP 401

# Confirm authenticated read works
curl -H "Authorization: Bearer ${API_READ_KEY}" https://api.trustfl.example.com/health/ready
# Expected: HTTP 200 {"status": "ready"}

# Confirm admin-only endpoint rejects read key
curl -i -X DELETE \
  -H "Authorization: Bearer ${API_READ_KEY}" \
  https://api.trustfl.example.com/clients/some-client
# Expected: HTTP 403

# Confirm invalid ZKP proof is rejected (not bypassed)
# Submit a client update with an invalid proof and verify status is REJECTED
```

### FL lifecycle validation

```bash
# After running a full federation round:
curl -H "Authorization: Bearer ${API_READ_KEY}" \
  https://api.trustfl.example.com/rounds/federation/fed-default | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print([r['status'] for r in d['data']])"
# Expected: contains 'FINALIZED' entries

# Verify blockchain confirmation
curl -H "Authorization: Bearer ${API_READ_KEY}" \
  "https://api.trustfl.example.com/blockchain/transactions?limit=10" | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print([(t['function_name'],t['status']) for t in d['data']])"
# Expected: ('finalizeRound', 'CONFIRMED') entries
```

---

## 7. Rolling Upgrades and Rollback

### API rolling upgrade (zero-downtime)

```bash
# Update the image tag
kubectl set image deployment/trustfl-api api=ghcr.io/fl-blockchain-project-major/trustfl/api:NEW_VERSION -n trustfl

# Monitor rollout (waits for readinessProbe)
kubectl rollout status deployment/trustfl-api -n trustfl --timeout=5m

# Rollback if needed
kubectl rollout undo deployment/trustfl-api -n trustfl
```

### Coordinator upgrade (requires brief downtime)

The coordinator uses `Recreate` strategy. The old pod terminates before the new one starts,
ensuring the DB fencing lease is released.

```bash
# Upgrade coordinator (the Recreate strategy handles lease release)
kubectl set image deployment/trustfl-coordinator coordinator=\
ghcr.io/fl-blockchain-project-major/trustfl/coordinator:NEW_VERSION -n trustfl

# Monitor (expect brief downtime while the old pod stops and new one starts)
kubectl rollout status deployment/trustfl-coordinator -n trustfl --timeout=5m
```

> [!IMPORTANT]
> Never run two coordinator instances simultaneously. The database fencing lease prevents
> dual execution, but it is better to avoid the situation entirely.

---

## 8. Key Rotation and Revocation

### API bearer token rotation

1. Create new tokens in your secrets manager.
2. Update the secret — ESO/CSI will sync automatically.
3. Trigger API rollout: `kubectl rollout restart deployment/trustfl-api -n trustfl`
4. Revoke old tokens in the secrets manager after confirming the rollout succeeded.

### Coordinator signing key rotation

> [!CAUTION]
> Rotating the coordinator signing key invalidates all in-flight round signatures.
> Complete or abort the current round before rotating.

1. Wait for the current round to reach `FINALIZED` or manually abort with `FAILED`.
2. Generate a new Ed25519 key pair (do not use the same key material).
3. Build the new `allowlist.json` mapping all enrolled client IDs to their existing public keys,
   with the new coordinator public key registered separately.
4. Update the `COORDINATOR_PRIVATE_KEY` secret.
5. Update `COORDINATOR_ENROLLMENT_ALLOWLIST` to reference any client keys that must re-enroll.
6. Restart the coordinator (Recreate strategy).
7. Verify new coordinator successfully acquires the DB lease and starts a round.

### Emergency credential replacement

If a credential is suspected compromised:
1. Immediately rotate the affected secret in your secrets manager.
2. Force restart all services using that secret.
3. Review audit logs for unauthorized access in the period since the last known-good rotation.
4. File an incident report per your organization's security policy.
5. After securing the system, perform a post-incident review.

---

## 9. Incident Response

See `docs/production/disaster-recovery.md` for the full DR procedure.

Quick reference for common incidents:

| Incident | Immediate action |
|:---------|:-----------------|
| Coordinator lease stuck | Delete the `coordinator_leases` row for `fed-default` after verifying no coordinator is running |
| API returning 500 for all requests | Check DB connectivity; restart API; check logs |
| ZKP rejection spike | Check ZKP artifacts are mounted; verify `verify-cli.js` is accessible |
| Blockchain outbox not draining | Check RPC endpoint connectivity; check outbox retry logs |
| Data integrity concern | Freeze ingress, take DB backup, engage DR procedure |

---

## 10. Known Limitations

The following limitations are documented and not yet resolved:

| Limitation | Impact | Mitigation |
|:-----------|:-------|:-----------|
| **Coordinator is single-instance** | Coordinator downtime = FL pause | Recreate deployment keeps downtime minimal; DB lease prevents split-brain |
| **ZKP verification is ~1.4s/call** | Limits client update throughput at high client counts | Acceptable for the current scale; batch verification or native implementation required for 100+ concurrent clients |
| **IPFS is not production-pinned** | Local IPFS volume is not HA | Use Pinata or Web3.Storage for pinned, replicated artifact storage |
| **No horizontal scalability demonstrated** | Cannot claim HA without evidence | Multi-instance API has been configured; coordinator cannot scale horizontally by design |
| **Blockchain confirmation latency** | 15s–60s per round depending on network | Built-in retry/outbox pattern handles this; not suitable for sub-minute round cycles |
| **Dashboard has no rate limiting** | DoS risk on the proxy endpoint | Add `nginx.ingress.kubernetes.io/limit-rps` annotation in production |
| **No automated secret expiry alerts** | Stale credentials go undetected | Configure secrets manager to alert 14 days before expiry |
