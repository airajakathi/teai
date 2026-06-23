#!/usr/bin/env python3
"""Validate release metadata and tag hygiene for CI and release workflows."""

from __future__ import annotations

import os
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def main() -> int:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data.get("project", {})

    version = project.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        return fail("project.version must use semantic versioning like X.Y.Z")

    readme = project.get("readme")
    if isinstance(readme, dict):
        readme_path = ROOT / readme.get("file", "")
    else:
        readme_path = ROOT / str(readme or "")
    if not readme_path.is_file():
        return fail(f"README file not found: {readme_path}")

    license_files = project.get("license-files", [])
    required_files = {
        "LICENSE": ROOT / "LICENSE",
        "THIRD_PARTY_NOTICES.md": ROOT / "THIRD_PARTY_NOTICES.md",
        "docs/configuration-reference.md": ROOT / "docs" / "configuration-reference.md",
    }

    for label, path in required_files.items():
        if not path.is_file():
            return fail(f"required release file missing: {label}")

    for required in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        if required not in license_files:
            return fail(f"project.license-files must include {required}")

    ref_type = os.environ.get("GITHUB_REF_TYPE")
    ref_name = os.environ.get("GITHUB_REF_NAME", "")
    if ref_type == "tag" and ref_name.startswith("v"):
        expected = f"v{version}"
        if ref_name != expected:
            return fail(f"tag {ref_name!r} does not match project.version {version!r}")

    print("Release metadata checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
