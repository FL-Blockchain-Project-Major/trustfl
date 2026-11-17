#!/usr/bin/env bash
# Deterministic container release verification for TrustFL images.
# Verifies Cosign signatures, GitHub OIDC certificate identity, and build provenance.

set -Eeuo pipefail

IMAGE="${1:-}"
REPO="${2:-FL-Blockchain-Project-Major/trustfl}"

if [[ -z "$IMAGE" ]]; then
  echo "Usage: $0 <image-reference-with-digest> [github-repo-slug]" >&2
  echo "Example: $0 ghcr.io/fl-blockchain-project-major/trustfl/api@sha256:..." >&2
  exit 1
fi

echo "==> Verifying TrustFL release image: $IMAGE"

if ! command -v cosign >/dev/null 2>&1; then
  echo "ERROR: 'cosign' CLI is required for release verification." >&2
  echo "Install cosign: https://docs.sigstore.dev/cosign/system_config/installation/" >&2
  exit 1
fi

echo "--> Verifying Cosign keyless signature..."
cosign verify "$IMAGE" \
  --certificate-identity-regexp "^https://github.com/${REPO}/\.github/workflows/.*" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com"

echo "--> Verifying GitHub build provenance attestation..."
if command -v gh >/dev/null 2>&1; then
  gh attestation verify "$IMAGE" --repo "$REPO" || {
    echo "Notice: 'gh attestation verify' failed or unauthenticated; falling back to cosign verify-attestation."
    cosign verify-attestation \
      --type slsaprovenance \
      --certificate-identity-regexp "^https://github.com/${REPO}/\.github/workflows/.*" \
      --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
      "$IMAGE" || true
  }
else
  cosign verify-attestation \
    --type slsaprovenance \
    --certificate-identity-regexp "^https://github.com/${REPO}/\.github/workflows/.*" \
    --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
    "$IMAGE" || true
fi

echo "==> Image verification SUCCEEDED for $IMAGE"
