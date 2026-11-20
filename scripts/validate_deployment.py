#!/usr/bin/env python3
"""
TrustFL Production Deployment Configuration Validator
=====================================================
Validates that Kubernetes manifests, Helm charts, and deployment configurations
strictly adhere to production security gates:
  1. Image Immutability: Rejects mutable 'latest' or bare tags; requires sha256 digests.
  2. Secret Injection: Enforces secretKeyRef / existingSecret; rejects plaintext secrets in values/ConfigMaps.
  3. Security Context & Least Privilege: Enforces runAsNonRoot, dropped capabilities, read-only root filesystems.
  4. Network Isolation: Validates default-deny NetworkPolicies and TLS Ingress with secure headers.
  5. High-Availability & Fencing: Enforces coordinator single-replica + Recreate strategy.
  6. Production Invariants: Rejects insecure dev auth, legacy auth compat, and disabled ZKP.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY_DIR = ROOT / "deploy"
K8S_BASE = DEPLOY_DIR / "k8s" / "base"
K8S_PROD = DEPLOY_DIR / "k8s" / "overlays" / "production"
HELM_DIR = DEPLOY_DIR / "helm" / "trustfl"

DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
MUTABLE_TAGS = {"latest", "dev", "master", "main", "staging", "head"}


def validate_image_immutability(errors: list[str]) -> None:
    """Ensure production deployment paths reject mutable tags and require immutable digests."""
    # 1. Helm values: global.imageDigest must not be 'latest', must not default to mutable tag
    values_text = (HELM_DIR / "values.yaml").read_text(encoding="utf-8")
    for mutable in MUTABLE_TAGS:
        if re.search(rf'image(?:Tag|Digest):\s*["\']?{mutable}["\']?', values_text, re.IGNORECASE):
            errors.append(f"Helm values.yaml defaults to mutable image tag '{mutable}'")

    # 2. Helm templates must enforce sha256 digest validation
    helpers_text = (HELM_DIR / "templates" / "_helpers.tpl").read_text(encoding="utf-8")
    if "sha256:" not in helpers_text or "Mutable image tag" not in helpers_text:
        errors.append("Helm _helpers.tpl does not enforce sha256 digest validation")

    # 3. K8s production overlay: images must use digest, not newTag
    kustomize_text = (K8S_PROD / "kustomization.yaml").read_text(encoding="utf-8")
    if "newTag:" in kustomize_text:
        errors.append("Production kustomization.yaml uses mutable 'newTag:' instead of 'digest:'")
    if "digest:" not in kustomize_text:
        errors.append("Production kustomization.yaml does not specify 'digest:' for images")

    # 4. K8s base deployment: must not hardcode :latest
    for dep_file in ("api-deployment.yaml", "coordinator-deployment.yaml"):
        dep_text = (K8S_BASE / dep_file).read_text(encoding="utf-8")
        if re.search(r"image:\s*ghcr\.io/fl-blockchain-project-major/trustfl/\w+:latest", dep_text):
            errors.append(f"K8s base manifest {dep_file} hardcodes ':latest' image tag")


def validate_secrets_management(errors: list[str]) -> None:
    """Ensure production credentials are never passed via Helm values, ConfigMaps, or CLI args."""
    # 1. Helm values must not contain plaintext credentials
    values_text = (HELM_DIR / "values.yaml").read_text(encoding="utf-8")
    forbidden_value_keys = ["readKey:", "writeKey:", "adminKey:", "privateKey:", "enrollmentToken:"]
    for fvk in forbidden_value_keys:
        if fvk in values_text:
            errors.append(f"Helm values.yaml exposes sensitive secret key '{fvk}'")

    # 2. ConfigMap must not contain credentials
    for cm_file in (K8S_BASE / "configmap.yaml", HELM_DIR / "templates" / "configmap.yaml"):
        if cm_file.exists():
            cm_text = cm_file.read_text(encoding="utf-8")
            for pattern in [
                "password",
                "private-key",
                "token",
                "secret",
                "read-key",
                "write-key",
                "admin-key",
            ]:
                if re.search(rf"\b{pattern}\b", cm_text, re.IGNORECASE):
                    errors.append(
                        f"ConfigMap {cm_file.name} contains potential credential keyword '{pattern}'"
                    )

    # 3. Helm templates must use existingSecret references
    for tmpl in HELM_DIR.glob("templates/deployment-*.yaml"):
        text = tmpl.read_text(encoding="utf-8")
        if "secretKeyRef" not in text:
            errors.append(f"Helm template {tmpl.name} does not inject secrets via secretKeyRef")
        if "existingSecret" not in text:
            errors.append(f"Helm template {tmpl.name} does not reference existingSecret")


def validate_security_hardening(errors: list[str]) -> None:
    """Validate least-privilege securityContext, network policies, TLS, and probes."""
    # 1. Base deployments must enforce runAsNonRoot, readOnlyRootFilesystem, dropped caps
    for dep_file in ("api-deployment.yaml", "coordinator-deployment.yaml"):
        path = K8S_BASE / dep_file
        text = path.read_text(encoding="utf-8")
        if "runAsNonRoot: true" not in text:
            errors.append(f"{dep_file}: missing 'runAsNonRoot: true'")
        if 'drop: ["ALL"]' not in text and "drop:\n                - ALL" not in text:
            errors.append(f"{dep_file}: missing dropped capabilities ['ALL']")
        if "readOnlyRootFilesystem: true" not in text:
            errors.append(f"{dep_file}: missing 'readOnlyRootFilesystem: true'")
        if "resources:" not in text or "limits:" not in text or "requests:" not in text:
            errors.append(f"{dep_file}: missing explicit CPU/memory resource requests and limits")
        if "readinessProbe:" not in text or "livenessProbe:" not in text:
            errors.append(f"{dep_file}: missing readiness/liveness probes")

    # 2. Coordinator must use Recreate strategy and replicaCount=1
    coord_text = (K8S_BASE / "coordinator-deployment.yaml").read_text(encoding="utf-8")
    if "type: Recreate" not in coord_text:
        errors.append(
            "coordinator-deployment.yaml: must use 'type: Recreate' strategy to prevent dual execution"
        )
    if "replicas: 1" not in coord_text:
        errors.append("coordinator-deployment.yaml: must enforce 'replicas: 1'")

    # 3. Network policy must have default-deny
    netpol_text = (K8S_BASE / "network-policies.yaml").read_text(encoding="utf-8")
    if "podSelector: {}" not in netpol_text:
        errors.append("network-policies.yaml: missing default-deny policy (podSelector: {})")

    # 4. Ingress must configure TLS and HSTS/CSP
    ingress_text = (K8S_BASE / "ingress.yaml").read_text(encoding="utf-8")
    if "tls:" not in ingress_text:
        errors.append("ingress.yaml: missing TLS configuration")
    if "Strict-Transport-Security" not in ingress_text:
        errors.append("ingress.yaml: missing HSTS configuration")


def validate_production_invariants(errors: list[str]) -> None:
    """Verify that development authentication, local dev chains, or disabled ZKP are never active."""
    for yaml_path in DEPLOY_DIR.rglob("*.yaml"):
        text = yaml_path.read_text(encoding="utf-8")
        if re.search(
            r"COORDINATOR_INSECURE_DEV_AUTH.*?value:\s*['\"]?true['\"]?", text, re.IGNORECASE
        ):
            errors.append(f"{yaml_path.name}: COORDINATOR_INSECURE_DEV_AUTH is set to true")
        if re.search(r"API_LEGACY_AUTH_COMPAT.*?value:\s*['\"]?true['\"]?", text, re.IGNORECASE):
            errors.append(f"{yaml_path.name}: API_LEGACY_AUTH_COMPAT is set to true")
        if re.search(r"COORDINATOR_REQUIRE_ZKP.*?value:\s*['\"]?false['\"]?", text, re.IGNORECASE):
            errors.append(f"{yaml_path.name}: COORDINATOR_REQUIRE_ZKP is set to false")


def validate_digest(digest: str) -> bool:
    """Validate that a string conforms to sha256:<64 hex chars>."""
    return bool(DIGEST_RE.match(digest))


def main() -> None:
    parser = argparse.ArgumentParser(description="TrustFL Production Deployment Validator")
    parser.add_argument(
        "--assert-digest", type=str, help="Validate an image digest string against sha256 format"
    )
    args = parser.parse_args()

    if args.assert_digest:
        if not validate_digest(args.assert_digest):
            sys.exit(
                f"[FAIL] Image digest {args.assert_digest!r} is invalid. Expected format: sha256:<64 hex chars>"
            )
        print(f"[OK] Image digest {args.assert_digest!r} is a valid immutable sha256 digest.")
        return

    print("--> Validating TrustFL production deployment configuration...")
    errors: list[str] = []
    validate_image_immutability(errors)
    validate_secrets_management(errors)
    validate_security_hardening(errors)
    validate_production_invariants(errors)

    if errors:
        print(f"\n[!] Deployment validation FAILED with {len(errors)} error(s):")
        for err in errors:
            print(f"    - {err}")
        sys.exit(1)

    print("[+] All production deployment security checks PASSED.")


if __name__ == "__main__":
    main()
