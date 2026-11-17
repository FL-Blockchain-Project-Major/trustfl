import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_supply_chain_validator_passes():
    import scripts.validate_supply_chain as validator

    validator.main()


def test_ci_has_security_gates():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for marker in (
        "supply-chain:",
        "pip-audit",
        'npm --prefix "$directory" audit --omit=dev --audit-level=high',
        "trivy",
        "zizmor",
        "gitleaks",
    ):
        assert marker in workflow


def test_release_has_keyless_signing_and_attestation():
    workflow = (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")
    for marker in (
        "cosign sign",
        "cosign verify",
        "attest-build-provenance",
        "provenance: true",
        "sbom: true",
    ):
        assert marker in workflow


def test_python_ci_uses_lockfile():
    for relative in (".github/workflows/ci.yml", ".github/workflows/publish.yml"):
        workflow = (ROOT / relative).read_text(encoding="utf-8")
        assert "pip install -r requirements-dev.txt" in workflow
        assert 'pip install -e ".[dev]"' not in workflow


def test_workflows_use_immutable_actions_and_no_credential_persistence():
    workflow_dir = ROOT / ".github/workflows"
    action_re = re.compile(r"uses:\s*([^#\s]+)")
    for wf in workflow_dir.glob("*.y*ml"):
        content = wf.read_text(encoding="utf-8")
        for action in action_re.findall(content):
            assert re.fullmatch(r".+@[0-9a-f]{40}", action), (
                f"{wf}: action not pinned to SHA: {action}"
            )
        # Every actions/checkout must set persist-credentials: false
        checkouts = [
            m.start() for m in re.finditer(r"uses:\s*actions/checkout@[0-9a-f]{40}", content)
        ]
        for pos in checkouts:
            snippet = content[pos : pos + 300]
            assert "persist-credentials: false" in snippet, (
                f"{wf}: checkout missing persist-credentials: false"
            )


def test_sbom_generator_generates_valid_sboms(tmp_path: Path):
    from scripts.generate_sboms import generate_all_sboms

    sboms = generate_all_sboms(tmp_path, version="1.0.0")
    assert "python" in sboms
    assert "dashboard" in sboms
    assert "contracts" in sboms
    assert "zkp" in sboms
    assert "release_cdx" in sboms
    assert "release_spdx" in sboms

    # Verify CycloneDX schema basics
    cdx_data = json.loads(sboms["release_cdx"].read_text(encoding="utf-8"))
    assert cdx_data["bomFormat"] == "CycloneDX"
    assert cdx_data["specVersion"] == "1.5"
    assert len(cdx_data["components"]) > 0

    # Verify SPDX schema basics
    spdx_data = json.loads(sboms["release_spdx"].read_text(encoding="utf-8"))
    assert spdx_data["spdxVersion"] == "SPDX-2.3"
    assert len(spdx_data["packages"]) > 0


def test_dockerfiles_have_non_root_users():
    dockerfiles = list(ROOT.glob("apps/*/Dockerfile")) + list(
        ROOT.glob("infrastructure/docker/Dockerfile.*")
    )
    assert len(dockerfiles) >= 5
    for df in dockerfiles:
        content = df.read_text(encoding="utf-8")
        assert "USER " in content, f"{df} is missing non-root USER directive"


def test_secret_scanner_configuration_present():
    ignore_file = ROOT / ".gitleaksignore"
    assert ignore_file.is_file(), "Missing .gitleaksignore file"
    lines = [
        line.strip()
        for line in ignore_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) > 0, ".gitleaksignore must not be empty"


def test_release_verification_script_exists():
    script = ROOT / "scripts/verify_release.sh"
    assert script.is_file()
    content = script.read_text(encoding="utf-8")
    assert "cosign verify" in content
    assert "certificate-oidc-issuer" in content
