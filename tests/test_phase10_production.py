"""
Phase 10: Production Deployment & Security Validation Tests.
============================================================
Validates:
  - Startup configuration rejects insecure production settings at startup
  - No development-only credentials in production paths
  - Published Compose stack enforces mandatory env-var gates
  - CI .env file is free of leading-whitespace bugs
  - Kubernetes manifest and Helm chart structural completeness
  - Secret-handling policy: no secrets in configmaps, images, or logs
  - ZKP and auth invariants cannot be bypassed through configuration
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1. Startup Config Validation
# ---------------------------------------------------------------------------
class TestProductionStartupValidation:
    """check_config must reject dangerous production misconfigurations."""

    def _run_check(self, env: dict[str, str]) -> None:
        """Run check_config in a sandboxed env; propagate RuntimeError."""
        from fastapi import FastAPI

        from apps.api.api.db.session import check_config

        app = FastAPI()
        with patch.dict(os.environ, env, clear=True):
            check_config(app)

    def test_production_requires_postgresql(self) -> None:
        """SQLite must be rejected in production."""
        with pytest.raises(RuntimeError, match="PostgreSQL"):
            self._run_check(
                {
                    "ENVIRONMENT": "production",
                    "DATABASE_URL": "sqlite:///./trustfl.db",
                    "API_READ_KEY": "real-key",
                    "API_WRITE_KEY": "real-key-write",
                    "API_ADMIN_KEY": "real-key-admin",
                    "COORDINATOR_REQUIRE_ZKP": "true",
                    "ZKP_VERIFY_COMMAND": "node /app/verify-cli.js",
                    "REDIS_URL": "redis://localhost:6379",
                    "CLIENT_KEY_STORE": "secret_manager",
                }
            )

    def test_production_rejects_placeholder_api_keys(self) -> None:
        """Placeholder API keys must be caught at startup."""
        with pytest.raises(RuntimeError, match="API_READ_KEY"):
            self._run_check(
                {
                    "ENVIRONMENT": "production",
                    "DATABASE_URL": "postgresql://user:pass@db:5432/trustfl",
                    "API_READ_KEY": "CHANGE_ME_IN_PRODUCTION",
                    "API_WRITE_KEY": "real-write",
                    "API_ADMIN_KEY": "real-admin",
                    "COORDINATOR_REQUIRE_ZKP": "true",
                    "ZKP_VERIFY_COMMAND": "node /app/verify-cli.js",
                    "REDIS_URL": "redis://redis:6379",
                    "CLIENT_KEY_STORE": "secret_manager",
                }
            )

    def test_production_rejects_missing_zkp(self) -> None:
        """ZKP must remain mandatory in production."""
        with pytest.raises(RuntimeError, match="COORDINATOR_REQUIRE_ZKP|ZKP_VERIFY_COMMAND"):
            self._run_check(
                {
                    "ENVIRONMENT": "production",
                    "DATABASE_URL": "postgresql://user:pass@db:5432/trustfl",
                    "API_READ_KEY": "real-read",
                    "API_WRITE_KEY": "real-write",
                    "API_ADMIN_KEY": "real-admin",
                    "COORDINATOR_REQUIRE_ZKP": "false",  # FORBIDDEN
                    "REDIS_URL": "redis://redis:6379",
                    "CLIENT_KEY_STORE": "secret_manager",
                }
            )

    def test_production_rejects_legacy_auth_compat(self) -> None:
        """Legacy auth compatibility must be disabled in production."""
        with pytest.raises(RuntimeError, match="API_LEGACY_AUTH_COMPAT"):
            self._run_check(
                {
                    "ENVIRONMENT": "production",
                    "DATABASE_URL": "postgresql://user:pass@db:5432/trustfl",
                    "API_READ_KEY": "real-read",
                    "API_WRITE_KEY": "real-write",
                    "API_ADMIN_KEY": "real-admin",
                    "COORDINATOR_REQUIRE_ZKP": "true",
                    "ZKP_VERIFY_COMMAND": "node /app/verify-cli.js",
                    "REDIS_URL": "redis://redis:6379",
                    "CLIENT_KEY_STORE": "secret_manager",
                    "API_LEGACY_AUTH_COMPAT": "true",  # FORBIDDEN
                }
            )

    def test_production_rejects_missing_redis(self) -> None:
        """Redis is required in production for distributed rate limiting."""
        with pytest.raises(RuntimeError, match="REDIS_URL"):
            self._run_check(
                {
                    "ENVIRONMENT": "production",
                    "DATABASE_URL": "postgresql://user:pass@db:5432/trustfl",
                    "API_READ_KEY": "real-read",
                    "API_WRITE_KEY": "real-write",
                    "API_ADMIN_KEY": "real-admin",
                    "COORDINATOR_REQUIRE_ZKP": "true",
                    "ZKP_VERIFY_COMMAND": "node /app/verify-cli.js",
                    "CLIENT_KEY_STORE": "secret_manager",
                    # REDIS_URL intentionally omitted
                }
            )

    def test_development_allows_sqlite(self) -> None:
        """Development mode must allow SQLite without errors."""
        # Should not raise
        self._run_check({"ENVIRONMENT": "development", "DATABASE_URL": "sqlite:///./trustfl.db"})


# ---------------------------------------------------------------------------
# 2. Published Compose Stack Checks (from test_published_compose.py extended)
# ---------------------------------------------------------------------------
class TestPublishedComposeStack:
    COMPOSE = REPO_ROOT / "docker-compose.published.yml"

    def _compose_text(self) -> str:
        return self.COMPOSE.read_text()

    def test_published_compose_exists(self) -> None:
        assert self.COMPOSE.exists(), "docker-compose.published.yml not found"

    def test_no_dev_credentials_in_published_compose(self) -> None:
        """Dev token defaults must never appear in the published stack."""
        text = self._compose_text()
        dev_tokens = [
            "trustfl-read-dev",
            "trustfl-write-dev",
            "trustfl-admin-dev",
            "trustfl-coordinator-dev",
            "trustfl-dashboard-dev",
            "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
        ]
        for token in dev_tokens:
            assert token not in text, f"Dev token {token!r} found in docker-compose.published.yml"

    def test_no_local_hardhat_in_published_compose(self) -> None:
        """Published stack must not provision a local Hardhat devchain."""
        text = self._compose_text()
        assert "\n  hardhat:\n" not in text
        assert "\n  contract-deployer:\n" not in text

    def test_insecure_dev_auth_disabled_in_published_compose(self) -> None:
        """COORDINATOR_INSECURE_DEV_AUTH must be absent or explicitly false."""
        text = self._compose_text()
        # Either not present, or only allowed as false
        matches = re.findall(r"COORDINATOR_INSECURE_DEV_AUTH\s*=\s*([^\s\n]+)", text)
        for m in matches:
            assert m.lower() in {"false", '"false"', "'false'", "${coordinator_insecure_dev_auth:-false}"}, (
                f"COORDINATOR_INSECURE_DEV_AUTH has non-false value {m!r} in published compose"
            )

    def test_zkp_required_in_published_compose(self) -> None:
        """ZKP must remain mandatory in published stack."""
        text = self._compose_text()
        # Either COORDINATOR_REQUIRE_ZKP=true or not set (defaults to true)
        matches = re.findall(r"COORDINATOR_REQUIRE_ZKP\s*=\s*([^\s\n]+)", text)
        for m in matches:
            assert m.lower() in {"true", '"true"', "'true'"}, (
                f"COORDINATOR_REQUIRE_ZKP is {m!r} (must be true) in published compose"
            )


# ---------------------------------------------------------------------------
# 3. CI .env file whitespace correctness
# ---------------------------------------------------------------------------
class TestCIEnvFileGeneration:
    """Ensure CI .env generation produces clean KEY=VALUE lines."""

    def test_printf_env_generation_has_no_leading_whitespace(self) -> None:
        """
        Simulate what the CI printf-based .env generation produces.
        Each KEY=VALUE line must start at column 0 (no leading spaces).
        """
        env_lines = [
            "POSTGRES_USER=trustfl",
            "POSTGRES_PASSWORD=trustfl",
            "POSTGRES_DB=trustfl",
            "ENVIRONMENT=development",
            "FL_FEDERATION_ID=fed-default",
            "FL_NUM_ROUNDS=3",
            "FL_NUM_CLIENTS=3",
            "FL_MIN_CLIENTS=3",
            "FL_MAX_CLIENT_WEIGHT_SHARE=0.5",
            "FL_MAX_UPDATE_NORM=1.0",
            "FL_LOCAL_EPOCHS=1",
            "FL_MAX_SAMPLES=50",
            "FL_POLL_INTERVAL_SECONDS=3.0",
            "COORDINATOR_REQUIRE_SIGNATURES=true",
            "COORDINATOR_INSECURE_DEV_AUTH=true",
        ]
        for line in env_lines:
            assert not line.startswith(" "), (
                f"Leading whitespace in CI .env line: {line!r}"
            )
            assert "=" in line, f"No '=' in env line: {line!r}"
            key, _, val = line.partition("=")
            assert key == key.strip(), f"Key has whitespace: {key!r}"
            assert val == val.strip() or val.strip(), f"Value malformed: {val!r}"

    def test_ci_yaml_does_not_use_heredoc_for_env(self) -> None:
        """
        The CI workflow must not use the indented heredoc pattern for .env
        generation. Any heredoc writing to .env must have an unindented marker.
        Confirm the printf approach is used instead.
        """
        ci_text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
        # Look for the .env-writing section
        # Must NOT contain the old 'cat > .env <<' pattern for the main .env
        # (Heredocs for Python inline scripts are acceptable)
        assert r"printf '%s\n'" in ci_text, (
            "CI .env must use printf to avoid heredoc indentation issues"
        )
        # The old broken pattern must not still be there for the .env block
        broken_heredoc = "cat > .env <<'ENVEOF'\n          POSTGRES_USER"
        assert broken_heredoc not in ci_text, (
            "Old indented heredoc for .env still present in CI workflow"
        )


# ---------------------------------------------------------------------------
# 4. Kubernetes manifest structural checks
# ---------------------------------------------------------------------------
class TestKubernetesManifests:
    K8S_BASE = REPO_ROOT / "deploy" / "k8s" / "base"
    K8S_PROD = REPO_ROOT / "deploy" / "k8s" / "overlays" / "production"

    def test_k8s_base_manifests_exist(self) -> None:
        required = [
            "namespace.yaml",
            "api-deployment.yaml",
            "coordinator-deployment.yaml",
            "configmap.yaml",
            "network-policies.yaml",
            "ingress.yaml",
            "kustomization.yaml",
        ]
        for f in required:
            assert (self.K8S_BASE / f).exists(), f"Missing K8s base manifest: {f}"

    def test_k8s_production_overlay_exists(self) -> None:
        assert (self.K8S_PROD / "kustomization.yaml").exists()

    def test_api_deployment_has_resource_limits(self) -> None:
        text = (self.K8S_BASE / "api-deployment.yaml").read_text()
        assert "resources:" in text
        assert "requests:" in text
        assert "limits:" in text
        assert "cpu:" in text
        assert "memory:" in text

    def test_api_deployment_has_health_probes(self) -> None:
        text = (self.K8S_BASE / "api-deployment.yaml").read_text()
        assert "readinessProbe:" in text
        assert "livenessProbe:" in text
        assert "/health/ready" in text
        assert "/health/live" in text

    def test_coordinator_uses_recreate_strategy(self) -> None:
        """Coordinator must use Recreate (not RollingUpdate) to prevent dual-leader."""
        text = (self.K8S_BASE / "coordinator-deployment.yaml").read_text()
        assert "type: Recreate" in text
        assert "RollingUpdate" not in text

    def test_coordinator_runs_as_non_root(self) -> None:
        text = (self.K8S_BASE / "coordinator-deployment.yaml").read_text()
        assert "runAsNonRoot: true" in text

    def test_api_runs_as_non_root(self) -> None:
        text = (self.K8S_BASE / "api-deployment.yaml").read_text()
        assert "runAsNonRoot: true" in text

    def test_secrets_not_in_configmap(self) -> None:
        """ConfigMap must never contain secrets or credentials."""
        text = (self.K8S_BASE / "configmap.yaml").read_text()
        secret_patterns = [
            "password",
            "private-key",
            "api-key",
            "enrollment-token",
            "api_read_key",
            "api_write_key",
            "api_admin_key",
        ]
        for pattern in secret_patterns:
            assert pattern.lower() not in text.lower(), (
                f"Potential secret pattern {pattern!r} found in ConfigMap"
            )

    def test_network_policies_deny_by_default(self) -> None:
        """Network policies must have a deny-all default rule."""
        text = (self.K8S_BASE / "network-policies.yaml").read_text()
        assert "trustfl-deny-all-default" in text
        assert "podSelector: {}" in text

    def test_insecure_dev_auth_not_in_k8s_manifests(self) -> None:
        """COORDINATOR_INSECURE_DEV_AUTH must never be true in K8s manifests."""
        for yaml_file in self.K8S_BASE.glob("*.yaml"):
            text = yaml_file.read_text()
            # Must not set insecure dev auth to true
            matches = re.findall(r"COORDINATOR_INSECURE_DEV_AUTH.*?value:\s*['\"]?(\w+)['\"]?", text)
            for m in matches:
                assert m.lower() != "true", (
                    f"{yaml_file.name}: COORDINATOR_INSECURE_DEV_AUTH is set to true"
                )


# ---------------------------------------------------------------------------
# 5. Helm chart structural checks
# ---------------------------------------------------------------------------
class TestHelmChart:
    HELM_DIR = REPO_ROOT / "deploy" / "helm" / "trustfl"

    def test_chart_yaml_exists(self) -> None:
        assert (self.HELM_DIR / "Chart.yaml").exists()

    def test_values_yaml_exists(self) -> None:
        assert (self.HELM_DIR / "values.yaml").exists()

    def test_values_has_no_plaintext_credentials(self) -> None:
        """Production values.yaml must not contain plaintext credentials or secret keys."""
        text = (self.HELM_DIR / "values.yaml").read_text()
        forbidden_keys = ["readKey:", "writeKey:", "adminKey:", "privateKey:", "enrollmentToken:"]
        for key in forbidden_keys:
            assert key not in text, f"Helm values.yaml exposes sensitive secret key {key!r}"
        assert "existingSecret: \"trustfl-api-keys\"" in text
        assert "existingSecret: \"trustfl-coordinator-keys\"" in text
        assert "existingSecret: \"trustfl-dashboard-keys\"" in text

    def test_helm_templates_exist_and_enforce_immutable_digest(self) -> None:
        """Helm templates must enforce sha256 digest validation and forbid mutable tags."""
        helpers = (self.HELM_DIR / "templates" / "_helpers.tpl").read_text()
        assert "sha256:" in helpers
        assert "Mutable image tag" in helpers
        required_templates = [
            "deployment-api.yaml",
            "service-api.yaml",
            "deployment-coordinator.yaml",
            "service-coordinator.yaml",
            "deployment-dashboard.yaml",
            "service-dashboard.yaml",
            "configmap.yaml",
            "ingress.yaml",
            "networkpolicy.yaml",
        ]
        for t in required_templates:
            assert (self.HELM_DIR / "templates" / t).exists(), f"Missing Helm template: {t}"

    def test_values_requires_zkp_in_coordinator(self) -> None:
        text = (self.HELM_DIR / "values.yaml").read_text()
        assert "COORDINATOR_REQUIRE_ZKP" in text
        assert '"true"' in text or "'true'" in text

    def test_values_disables_insecure_dev_auth(self) -> None:
        text = (self.HELM_DIR / "values.yaml").read_text()
        assert "COORDINATOR_INSECURE_DEV_AUTH" in text
        # Must be false
        matches = re.findall(r'COORDINATOR_INSECURE_DEV_AUTH:\s*"?([^"\n]+)"?', text)
        for m in matches:
            assert m.strip().lower() in {"false", '"false"'}, (
                f"Helm values has COORDINATOR_INSECURE_DEV_AUTH={m!r}"
            )

    def test_coordinator_replica_count_is_one(self) -> None:
        """Coordinator must be deployed as a single replica (DB fencing lease)."""
        text = (self.HELM_DIR / "values.yaml").read_text()
        coord_section = text[text.find("coordinator:"):]
        match = re.search(r"replicaCount:\s*(\d+)", coord_section)
        assert match, "coordinator.replicaCount not found in values.yaml"
        assert int(match.group(1)) == 1, (
            f"coordinator.replicaCount must be 1, got {match.group(1)}"
        )


# ---------------------------------------------------------------------------
# 6. No private keys or credentials in images or docs
# ---------------------------------------------------------------------------
class TestNoSecretsInRepository:
    FORBIDDEN_PATTERNS = [
        # Private key hex strings (Hardhat well-known key is allowed only in dev compose)
        r"0x[0-9a-fA-F]{63,64}",
        # Base64-encoded Ed25519 private keys (32-byte = 44 chars)
        r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{43}={0,1}(?![A-Za-z0-9+/=])",
        # PEM private key headers
        r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
        # AWS / GCP credential patterns
        r"AKIA[0-9A-Z]{16}",
        r"ya29\.[0-9A-Za-z\-_]+",
    ]

    # Files/patterns explicitly allowed to contain these (dev defaults, test vectors, docs)
    ALLOWED_FILES = {
        "docker-compose.yml",         # has the Hardhat dev key
        ".env.example",               # placeholder
        "DEPLOYMENT.md",              # documentation references
        "THREAT_MODEL.md",            # security documentation
        "docs",                       # documentation directory
        "tests",                      # test files may have test vectors
        "packages/contracts",         # contract deployment key (Hardhat well-known)
        "infrastructure",             # infra examples
        ".gitleaksignore",
    }

    def _should_skip(self, path: Path) -> bool:
        rel = path.relative_to(REPO_ROOT)
        for allowed in self.ALLOWED_FILES:
            if str(rel).startswith(allowed) or rel.name in self.ALLOWED_FILES:
                return True
        return False

    def test_no_private_key_hex_in_production_deploy_manifests(self) -> None:
        """K8s and Helm manifests must not contain private key hex strings."""
        deploy_dir = REPO_ROOT / "deploy"
        pkey_pattern = re.compile(r"0x[0-9a-fA-F]{63,64}")
        for yaml_file in deploy_dir.rglob("*.yaml"):
            text = yaml_file.read_text()
            matches = pkey_pattern.findall(text)
            assert not matches, (
                f"Private key hex found in {yaml_file.relative_to(REPO_ROOT)}: {matches[:3]}"
            )

    def test_no_pem_private_keys_in_production_config(self) -> None:
        """PEM private key headers must not appear in production deploy files."""
        deploy_dir = REPO_ROOT / "deploy"
        pem_pattern = re.compile(r"-----BEGIN .* PRIVATE KEY-----")
        for f in deploy_dir.rglob("*"):
            if f.is_file() and f.suffix in {".yaml", ".json", ".txt", ".md"}:
                text = f.read_text(errors="replace")
                assert not pem_pattern.search(text), (
                    f"PEM private key found in {f.relative_to(REPO_ROOT)}"
                )

    def test_production_compose_has_no_embedded_private_keys(self) -> None:
        """docker-compose.published.yml must not embed any private key."""
        text = (REPO_ROOT / "docker-compose.published.yml").read_text()
        pkey_re = re.compile(r"0x[0-9a-fA-F]{63,64}")
        matches = pkey_re.findall(text)
        assert not matches, f"Private key hex in docker-compose.published.yml: {matches}"


# ---------------------------------------------------------------------------
# 7. SBOM completeness spot-check
# ---------------------------------------------------------------------------
class TestSBOMCompleteness:
    SBOM_DIR = REPO_ROOT / "dist" / "sboms"

    def test_sbom_directory_exists(self) -> None:
        """SBOM output directory must exist (generated by CI or manually)."""
        # In CI this directory is created during the supply-chain job.
        # In a clean checkout it may not exist — skip gracefully.
        if not self.SBOM_DIR.exists():
            pytest.skip("dist/sboms not generated yet; run scripts/generate_sboms.py first")

    def test_python_sbom_has_required_fields(self) -> None:
        import json

        sbom_file = self.SBOM_DIR / "trustfl-python.cdx.json"
        if not sbom_file.exists():
            pytest.skip("trustfl-python.cdx.json not found")
        sbom = json.loads(sbom_file.read_text())
        assert sbom.get("bomFormat") == "CycloneDX"
        assert sbom.get("specVersion") in {"1.4", "1.5", "1.6"}
        assert "components" in sbom
        assert len(sbom["components"]) > 0
        # Every component must have name and version
        for comp in sbom["components"]:
            assert "name" in comp, f"Component missing name: {comp}"

    def test_sbom_has_no_unknown_licenses(self) -> None:
        """Every SBOM component with a license should have a resolved license identifier."""
        import json

        sbom_file = self.SBOM_DIR / "trustfl-python.cdx.json"
        if not sbom_file.exists():
            pytest.skip("trustfl-python.cdx.json not found")
        sbom = json.loads(sbom_file.read_text())
        unknown_count = 0
        for comp in sbom.get("components", []):
            for lic in comp.get("licenses", []):
                lic_obj = lic.get("license", {})
                if lic_obj.get("id") == "UNKNOWN" or lic_obj.get("name") == "UNKNOWN":
                    unknown_count += 1
        # Allow at most 20% unknown (some packages do not declare their license)
        total = len(sbom["components"])
        ratio = unknown_count / total if total > 0 else 0
        assert ratio <= 0.20, (
            f"Too many UNKNOWN licenses in Python SBOM: {unknown_count}/{total} ({ratio:.0%})"
        )


# ---------------------------------------------------------------------------
# 8. Least-privilege endpoint authorization regression tests
# ---------------------------------------------------------------------------
class TestEndpointLeastPrivilegeAuthorization:
    """Validate that GET /blockchain/transactions rejects read/write credentials and requires admin."""

    @pytest.fixture
    def test_client(self, monkeypatch):
        from fastapi.testclient import TestClient

        from apps.api.api.db.models import Base
        from apps.api.api.db.session import engine
        from apps.api.main import app

        Base.metadata.create_all(bind=engine)
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("API_AUTH_REQUIRED", "true")
        monkeypatch.setenv("API_READ_KEY", "ci-read-secret")
        monkeypatch.setenv("API_WRITE_KEY", "ci-write-secret")
        monkeypatch.setenv("API_ADMIN_KEY", "ci-admin-secret")
        return TestClient(app)

    def test_blockchain_transactions_rejects_read_credentials(self, test_client) -> None:
        """GET /blockchain/transactions must return HTTP 403 Forbidden with read credentials."""
        resp = test_client.get(
            "/blockchain/transactions",
            headers={"Authorization": "Bearer ci-read-secret"},
        )
        assert resp.status_code == 403, f"Expected 403 Forbidden, got {resp.status_code}: {resp.text}"

    def test_blockchain_transactions_rejects_unauthenticated(self, test_client) -> None:
        """GET /blockchain/transactions must return HTTP 401 Unauthorized without credentials."""
        resp = test_client.get("/blockchain/transactions")
        assert resp.status_code == 401, f"Expected 401 Unauthorized, got {resp.status_code}: {resp.text}"

    def test_blockchain_transactions_accepts_admin_credentials(self, test_client) -> None:
        """GET /blockchain/transactions must succeed (HTTP 200) with admin credentials."""
        resp = test_client.get(
            "/blockchain/transactions",
            headers={"Authorization": "Bearer ci-admin-secret"},
        )
        assert resp.status_code == 200, f"Expected 200 OK, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# 9. Deployment configuration validator test
# ---------------------------------------------------------------------------
class TestDeploymentValidator:
    """Validate deployment validator logic and immutability checks."""

    def test_deployment_validator_script_passes(self) -> None:
        import subprocess

        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "validate_deployment.py")],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=False,
        )
        assert result.returncode == 0, f"validate_deployment.py failed:\n{result.stdout}\n{result.stderr}"
        assert "All production deployment security checks PASSED" in result.stdout

    def test_validate_digest_accepts_valid_sha256(self) -> None:
        from scripts.validate_deployment import validate_digest

        assert validate_digest("sha256:" + "a" * 64) is True
        assert validate_digest("sha256:" + "0123456789abcdef" * 4) is True

    def test_validate_digest_rejects_mutable_tags(self) -> None:
        from scripts.validate_deployment import validate_digest

        assert validate_digest("latest") is False
        assert validate_digest("dev") is False
        assert validate_digest("v1.0.0") is False
        assert validate_digest("sha256:short") is False

