from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_supply_chain_validator_passes():
    import scripts.validate_supply_chain as validator

    validator.main()


def test_ci_has_security_gates():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    for marker in ("supply-chain:", "pip-audit", "npm audit", "trivy", "zizmor"):
        assert marker in workflow


def test_release_has_keyless_signing_and_attestation():
    workflow = (ROOT / ".github/workflows/publish.yml").read_text()
    for marker in ("cosign sign", "cosign verify", "attest-build-provenance", "provenance: true", "sbom: true"):
        assert marker in workflow


def test_python_ci_uses_lockfile():
    for relative in (".github/workflows/ci.yml", ".github/workflows/publish.yml"):
        workflow = (ROOT / relative).read_text()
        assert "pip install -r requirements-dev.txt" in workflow
        assert "pip install -e \".[dev]\"" not in workflow
