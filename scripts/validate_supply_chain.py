"""Deterministic repository checks used by CI supply-chain gates."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
ACTION_RE = re.compile(r"uses:\s*([^#\s]+)")
SECRET_FILE_RE = re.compile(
    r"(^|/)(\.env(\..*)?|.*\.(pem|key|p12|pfx|crt|cer|secret|secrets))$",
    re.IGNORECASE,
)


def tracked_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True, text=False
        )
        return [item for item in result.stdout.decode().split("\0") if item]
    except (FileNotFoundError, subprocess.CalledProcessError):
        return [
            str(p.relative_to(ROOT))
            for p in ROOT.rglob("*")
            if p.is_file() and ".git" not in p.parts
        ]


def check_no_sensitive_files(files: list[str]) -> None:
    forbidden = [
        path
        for path in files
        if (
            SECRET_FILE_RE.search(path)
            and Path(path).name.lower() not in {".env.example", ".env.template"}
        )
        or Path(path).name.lower() in {"id_rsa", "id_ed25519", "credentials.json"}
    ]
    if forbidden:
        raise SystemExit(f"tracked sensitive files: {', '.join(forbidden)}")


def check_workflows() -> None:
    for workflow in WORKFLOWS.glob("*.y*ml"):
        content = workflow.read_text(encoding="utf-8")
        for action in ACTION_RE.findall(content):
            if "@" not in action or not re.fullmatch(r".+@[0-9a-f]{40}", action):
                raise SystemExit(f"{workflow}: action is not pinned to a commit: {action}")
        if "permissions:" not in content:
            raise SystemExit(f"{workflow}: missing explicit permissions")


def check_lockfiles() -> None:
    required = [
        "requirements.txt",
        "requirements-dev.txt",
        "apps/dashboard/package-lock.json",
        "packages/contracts/package-lock.json",
        "packages/zkp/package-lock.json",
    ]
    for relative in required:
        path = ROOT / relative
        if not path.is_file():
            raise SystemExit(f"missing lockfile: {relative}")
    for relative in required[-3:]:
        data = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        if data.get("lockfileVersion") != 3:
            raise SystemExit(f"{relative}: expected npm lockfileVersion 3")


def check_manifests() -> None:
    for relative in ("apps/dashboard/package.json", "packages/contracts/package.json", "packages/zkp/package.json"):
        data = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        if not data.get("license"):
            raise SystemExit(f"{relative}: missing license declaration")
    if "license = \"MIT\"" not in (ROOT / "pyproject.toml").read_text(encoding="utf-8"):
        raise SystemExit("pyproject.toml: missing MIT license declaration")


def main() -> None:
    files = tracked_files()
    check_no_sensitive_files(files)
    check_workflows()
    check_lockfiles()
    check_manifests()
    print("Supply-chain repository checks passed.")


if __name__ == "__main__":
    main()
