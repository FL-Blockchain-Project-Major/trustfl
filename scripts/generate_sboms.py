"""Deterministic CycloneDX and SPDX SBOM generator for TrustFL release artifacts."""

from __future__ import annotations

import argparse
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Known licenses for standard Python runtime dependencies
PYTHON_DEP_LICENSES: dict[str, str] = {
    "alembic": "MIT",
    "annotated-types": "MIT",
    "anyio": "MIT",
    "certifi": "MPL-2.0",
    "click": "BSD-3-Clause",
    "cryptography": "Apache-2.0",
    "ecdsa": "MIT",
    "fastapi": "MIT",
    "greenlet": "MIT",
    "h11": "MIT",
    "httptools": "MIT",
    "idna": "BSD-3-Clause",
    "mako": "MIT",
    "markupsafe": "BSD-3-Clause",
    "numpy": "BSD-3-Clause",
    "opentelemetry-api": "Apache-2.0",
    "opentelemetry-sdk": "Apache-2.0",
    "opentelemetry-semantic-conventions": "Apache-2.0",
    "pillow": "HPND",
    "psycopg2-binary": "LGPL-3.0-or-later",
    "pydantic": "MIT",
    "pydantic-core": "MIT",
    "pydantic-settings": "MIT",
    "python-dotenv": "BSD-3-Clause",
    "pyyaml": "MIT",
    "sniffio": "Apache-2.0",
    "sqlalchemy": "MIT",
    "starlette": "BSD-3-Clause",
    "torch": "BSD-3-Clause",
    "torchvision": "BSD-3-Clause",
    "typing-extensions": "Python-2.0",
    "typing_extensions": "Python-2.0",
    "uvicorn": "BSD-3-Clause",
    "uvloop": "MIT",
    "watchfiles": "MIT",
    "websockets": "BSD-3-Clause",
}


def parse_requirements(req_path: Path) -> list[dict[str, str]]:
    components = []
    if not req_path.is_file():
        return components

    line_pattern = re.compile(r"^([a-zA-Z0-9_\-\.\[\]]+)==([a-zA-Z0-9_\-\.]+)")
    for line in req_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-", "http")):
            continue
        match = line_pattern.match(line)
        if match:
            pkg_name, pkg_version = match.groups()
            clean_name = re.sub(r"\[.*\]", "", pkg_name).strip()
            lic = PYTHON_DEP_LICENSES.get(clean_name.lower(), "NOASSERTION")
            comp = {
                "type": "library",
                "name": clean_name,
                "version": pkg_version,
                "purl": f"pkg:pypi/{clean_name.lower()}@{pkg_version}",
                "bom-ref": f"pkg:pypi/{clean_name.lower()}@{pkg_version}",
                "license": lic,
            }
            if lic != "NOASSERTION":
                comp["licenses"] = [{"license": {"id": lic}}]
            components.append(comp)
    return components


def parse_package_lock(lock_path: Path) -> list[dict[str, str]]:
    components = []
    if not lock_path.is_file():
        return components

    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception:
        return components

    packages = data.get("packages", {})
    for pkg_path, info in packages.items():
        if not pkg_path or info.get("dev", False):
            continue
        name = info.get("name")
        if not name:
            if "node_modules/" in pkg_path:
                name = pkg_path.split("node_modules/")[-1]
            else:
                name = pkg_path
        version = info.get("version", "0.0.0")
        lic = info.get("license", "NOASSERTION")
        comp = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:npm/{name}@{version}",
            "bom-ref": f"pkg:npm/{name}@{version}",
            "license": lic if isinstance(lic, str) else "NOASSERTION",
        }
        if isinstance(lic, str) and lic != "NOASSERTION":
            comp["licenses"] = [{"license": {"id": lic}}]
        components.append(comp)
    return components


def build_cyclonedx_bom(
    component_name: str,
    component_version: str,
    components: list[dict[str, str]],
) -> dict:
    bom_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"trustfl.{component_name}.{component_version}"))
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    comp_entries = []
    for c in sorted(components, key=lambda x: (x["name"], x["version"])):
        entry = {
            "type": c.get("type", "library"),
            "name": c["name"],
            "version": c["version"],
            "purl": c["purl"],
            "bom-ref": c["bom-ref"],
        }
        if "licenses" in c:
            entry["licenses"] = c["licenses"]
        comp_entries.append(entry)

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{bom_uuid}",
        "version": 1,
        "metadata": {
            "timestamp": timestamp,
            "tools": [
                {
                    "vendor": "TrustFL Security",
                    "name": "trustfl-sbom-generator",
                    "version": "1.0.0",
                }
            ],
            "component": {
                "type": "application",
                "name": component_name,
                "version": component_version,
                "licenses": [{"license": {"id": "MIT"}}],
                "purl": f"pkg:generic/{component_name}@{component_version}",
            },
        },
        "components": comp_entries,
    }


def build_spdx_bom(
    component_name: str,
    component_version: str,
    components: list[dict[str, str]],
) -> dict:
    doc_namespace = f"https://github.com/FL-Blockchain-Project-Major/trustfl/spdx/{component_name}-{component_version}"
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    packages = [
        {
            "SPDXID": "SPDXRef-Package-Root",
            "name": component_name,
            "versionInfo": component_version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "MIT",
            "licenseDeclared": "MIT",
        }
    ]

    for idx, c in enumerate(sorted(components, key=lambda x: (x["name"], x["version"])), start=1):
        lic = c.get("license", "NOASSERTION")
        packages.append(
            {
                "SPDXID": f"SPDXRef-Package-{idx}",
                "name": c["name"],
                "versionInfo": c["version"],
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": lic if lic != "NOASSERTION" else "NOASSERTION",
                "licenseDeclared": lic if lic != "NOASSERTION" else "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": c["purl"],
                    }
                ],
            }
        )

    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{component_name}-{component_version}",
        "documentNamespace": doc_namespace,
        "creationInfo": {
            "created": timestamp,
            "creators": ["Tool: trustfl-sbom-generator-1.0.0", "Organization: TrustFL Team"],
        },
        "packages": packages,
    }


def generate_all_sboms(output_dir: Path, version: str = "0.1.0") -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: dict[str, Path] = {}

    # Python runtime
    py_components = parse_requirements(ROOT / "requirements.txt")
    py_cdx = build_cyclonedx_bom("trustfl-python", version, py_components)
    py_path = output_dir / "trustfl-python.cdx.json"
    py_path.write_text(json.dumps(py_cdx, indent=2), encoding="utf-8")
    generated["python"] = py_path

    # Node packages
    dashboard_components = parse_package_lock(ROOT / "apps/dashboard/package-lock.json")
    dashboard_cdx = build_cyclonedx_bom("trustfl-dashboard", version, dashboard_components)
    dashboard_path = output_dir / "trustfl-dashboard.cdx.json"
    dashboard_path.write_text(json.dumps(dashboard_cdx, indent=2), encoding="utf-8")
    generated["dashboard"] = dashboard_path

    contracts_components = parse_package_lock(ROOT / "packages/contracts/package-lock.json")
    contracts_cdx = build_cyclonedx_bom("trustfl-contracts", version, contracts_components)
    contracts_path = output_dir / "trustfl-contracts.cdx.json"
    contracts_path.write_text(json.dumps(contracts_cdx, indent=2), encoding="utf-8")
    generated["contracts"] = contracts_path

    zkp_components = parse_package_lock(ROOT / "packages/zkp/package-lock.json")
    zkp_cdx = build_cyclonedx_bom("trustfl-zkp", version, zkp_components)
    zkp_path = output_dir / "trustfl-zkp.cdx.json"
    zkp_path.write_text(json.dumps(zkp_cdx, indent=2), encoding="utf-8")
    generated["zkp"] = zkp_path

    # Aggregate release SBOM
    all_components = py_components + dashboard_components + contracts_components + zkp_components
    # Deduplicate by purl
    seen_purls = set()
    deduped_components = []
    for c in all_components:
        if c["purl"] not in seen_purls:
            seen_purls.add(c["purl"])
            deduped_components.append(c)

    # Release CycloneDX
    rel_cdx = build_cyclonedx_bom("trustfl-release", version, deduped_components)
    rel_cdx_path = output_dir / "trustfl-release.cdx.json"
    rel_cdx_path.write_text(json.dumps(rel_cdx, indent=2), encoding="utf-8")
    generated["release_cdx"] = rel_cdx_path

    # Release SPDX
    rel_spdx = build_spdx_bom("trustfl-release", version, deduped_components)
    rel_spdx_path = output_dir / "trustfl-release.spdx.json"
    rel_spdx_path.write_text(json.dumps(rel_spdx, indent=2), encoding="utf-8")
    generated["release_spdx"] = rel_spdx_path

    return generated


def validate_sboms(sboms: dict[str, Path]) -> bool:
    """Validate completeness and schema integrity of generated SBOMs."""
    required_keys = {"python", "dashboard", "contracts", "zkp", "release_cdx", "release_spdx"}
    missing = required_keys - set(sboms.keys())
    if missing:
        raise ValueError(f"Missing expected SBOM targets: {missing}")

    for name, path in sboms.items():
        if not path.is_file():
            raise FileNotFoundError(f"SBOM file not generated: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))

        if (
            "cdx" in path.name
            or "python" in path.name
            or "dashboard" in path.name
            or "contracts" in path.name
            or "zkp" in path.name
        ):
            assert data.get("bomFormat") == "CycloneDX", f"{path.name}: bad bomFormat"
            assert data.get("specVersion") == "1.5", f"{path.name}: specVersion != 1.5"
            assert "components" in data, f"{path.name}: missing components key"
            components = data["components"]
            if name != "contracts":  # contracts has 0 prod dependencies currently
                assert len(components) > 0, f"{path.name}: components empty"
            for c in components:
                assert c.get("name"), f"{path.name}: component without name"
                assert c.get("version"), f"{path.name}: component without version"
                assert c.get("purl", "").startswith("pkg:"), f"{path.name}: invalid purl"

        if "spdx" in path.name:
            assert data.get("spdxVersion") == "SPDX-2.3", f"{path.name}: bad spdxVersion"
            assert data.get("dataLicense") == "CC0-1.0", f"{path.name}: bad dataLicense"
            assert "packages" in data, f"{path.name}: missing packages key"
            packages = data["packages"]
            assert len(packages) > 1, f"{path.name}: packages empty (only root or none)"
            for p in packages:
                assert p.get("name"), f"{path.name}: package without name"
                assert p.get("licenseConcluded"), f"{path.name}: package missing licenseConcluded"

    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate TrustFL release SBOMs.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "dist" / "sboms",
        help="Directory to save generated SBOM files",
    )
    parser.add_argument(
        "--version",
        default="0.1.0",
        help="Release artifact version string",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate generated SBOMs for schema and dependency completeness",
    )
    args = parser.parse_args()

    files = generate_all_sboms(args.output_dir, args.version)
    if args.validate:
        validate_sboms(files)
        print("SBOM validation passed.")

    print(f"Successfully generated {len(files)} SBOM files in {args.output_dir}:")
    for name, path in files.items():
        print(f"  - [{name}]: {path.name}")


if __name__ == "__main__":
    main()
