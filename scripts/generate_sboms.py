"""Deterministic CycloneDX and SPDX SBOM generator for TrustFL release artifacts."""

from __future__ import annotations

import argparse
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
            components.append(
                {
                    "type": "library",
                    "name": clean_name,
                    "version": pkg_version,
                    "purl": f"pkg:pypi/{clean_name.lower()}@{pkg_version}",
                    "bom-ref": f"pkg:pypi/{clean_name.lower()}@{pkg_version}",
                }
            )
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
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:npm/{name}@{version}",
                "bom-ref": f"pkg:npm/{name}@{version}",
            }
        )
    return components


def build_cyclonedx_bom(
    component_name: str,
    component_version: str,
    components: list[dict[str, str]],
) -> dict:
    bom_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"trustfl.{component_name}.{component_version}"))
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

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
        "components": sorted(components, key=lambda c: (c["name"], c["version"])),
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
        packages.append(
            {
                "SPDXID": f"SPDXRef-Package-{idx}",
                "name": c["name"],
                "versionInfo": c["version"],
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
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
    args = parser.parse_args()

    files = generate_all_sboms(args.output_dir, args.version)
    print(f"Successfully generated {len(files)} SBOM files in {args.output_dir}:")
    for name, path in files.items():
        print(f"  - [{name}]: {path.name}")


if __name__ == "__main__":
    main()
