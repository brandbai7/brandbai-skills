#!/usr/bin/env python3
"""Validate the public BrandBAI Agent Skills repository."""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "skills"
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REQUIRED_ROOT_FILES = {
    "AGENTS.md",
    "COMMERCIAL_LICENSING.md",
    "CONTRIBUTING.md",
    "IP_AND_DATA_POLICY.md",
    "LICENSE",
    "README.md",
    "RELEASE_NOTES.md",
    "THIRD_PARTY_NOTICES.md",
    "TRADEMARKS.md",
}
EXPECTED_LICENSE = "PolyForm-Noncommercial-1.0.0"
FORBIDDEN_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\Users\\", re.IGNORECASE),
    re.compile(r"[A-Za-z]:\\得宝", re.IGNORECASE),
    re.compile(r"[A-Za-z]:\\BrandBAI增长学院", re.IGNORECASE),
)
FORBIDDEN_DIR_NAMES = {
    "__pycache__",
    "outputs",
    "media",
    "_browser_skill_test_artifacts",
    "_foundation_test_artifacts",
    "_skill_test_artifacts",
}


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    match = re.match(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.DOTALL)
    if not match:
        raise ValueError("missing YAML frontmatter")
    value = yaml.safe_load(match.group(1))
    if not isinstance(value, dict):
        raise ValueError("frontmatter must be a mapping")
    return value


def validate_xlsx_asset(path: Path) -> list[str]:
    failures: list[str] = []
    relative = path.relative_to(ROOT)
    try:
        skill_relative = path.relative_to(SKILLS_ROOT)
    except ValueError:
        return [f"Forbidden generated file: {relative}"]
    if len(skill_relative.parts) < 3 or skill_relative.parts[1] != "assets":
        return [f"XLSX is only allowed as a Skill asset: {relative}"]
    if "template" not in path.stem.lower() and "模板" not in path.stem:
        failures.append(f"XLSX asset must be explicitly named as a template: {relative}")
    if path.stat().st_size > 1_000_000:
        failures.append(f"XLSX template is unexpectedly large: {relative}")
        return failures
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            required = {"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml"}
            if not required <= names:
                failures.append(f"XLSX template is not a complete workbook: {relative}")
                return failures
            forbidden_members = [
                name for name in names
                if name == "xl/vbaProject.bin"
                or name == "xl/connections.xml"
                or name.startswith("xl/externalLinks/")
                or name.startswith("xl/embeddings/")
            ]
            if forbidden_members:
                failures.append(f"XLSX template contains active or external content: {relative}")
            xml_text = "".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in names if name.endswith(".xml")
            )
            for pattern in FORBIDDEN_PATH_PATTERNS:
                if pattern.search(xml_text):
                    failures.append(f"Local absolute path found in XLSX template: {relative}")
                    break
    except (OSError, zipfile.BadZipFile):
        failures.append(f"XLSX template cannot be opened: {relative}")
    return failures


def main() -> int:
    failures: list[str] = []
    for filename in sorted(REQUIRED_ROOT_FILES):
        if not (ROOT / filename).is_file():
            failures.append(f"Required root file is missing: {filename}")

    skill_dirs = sorted(path for path in SKILLS_ROOT.iterdir() if path.is_dir())
    if not skill_dirs:
        failures.append("No public skills found")

    for skill_dir in skill_dirs:
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            failures.append(f"{skill_dir.relative_to(ROOT)}: SKILL.md is missing")
            continue
        try:
            meta = frontmatter(skill_md)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            failures.append(f"{skill_md.relative_to(ROOT)}: {exc}")
            continue
        name = str(meta.get("name") or "")
        description = str(meta.get("description") or "").strip()
        license_id = str(meta.get("license") or "").strip()
        if name != skill_dir.name:
            failures.append(f"{skill_md.relative_to(ROOT)}: name must equal folder name")
        if not NAME_RE.fullmatch(name) or len(name) > 64:
            failures.append(f"{skill_md.relative_to(ROOT)}: invalid skill name")
        if not description or len(description) > 1024:
            failures.append(f"{skill_md.relative_to(ROOT)}: description must be 1-1024 characters")
        if license_id != EXPECTED_LICENSE:
            failures.append(
                f"{skill_md.relative_to(ROOT)}: license must be {EXPECTED_LICENSE}"
            )
        metadata = meta.get("metadata")
        if not isinstance(metadata, dict) or not str(metadata.get("version") or "").strip():
            failures.append(f"{skill_md.relative_to(ROOT)}: metadata.version is required")
        embedded_license = skill_dir / "references" / "license.md"
        if not embedded_license.is_file():
            failures.append(
                f"{skill_dir.relative_to(ROOT)}: references/license.md is required for standalone installs"
            )
        elif embedded_license.read_text(encoding="utf-8-sig").strip() != (
            ROOT / "LICENSE"
        ).read_text(encoding="utf-8-sig").strip():
            failures.append(
                f"{embedded_license.relative_to(ROOT)}: must match the root LICENSE exactly"
            )

    for path in ROOT.rglob("*"):
        if path.is_dir() and path.name in FORBIDDEN_DIR_NAMES:
            failures.append(f"Forbidden generated directory: {path.relative_to(ROOT)}")
            continue
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.suffix.lower() == ".xlsx":
            failures.extend(validate_xlsx_asset(path))
            continue
        if path.suffix.lower() in {".pyc", ".sqlite3", ".jsonl"}:
            failures.append(f"Forbidden generated file: {path.relative_to(ROOT)}")
            continue
        if path.stat().st_size > 2_000_000:
            failures.append(f"Unexpected large file: {path.relative_to(ROOT)}")
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        for pattern in FORBIDDEN_PATH_PATTERNS:
            if pattern.search(text):
                failures.append(f"Local absolute path found in {path.relative_to(ROOT)}")
                break

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        return 1
    print(f"Validated {len(skill_dirs)} BrandBAI skill(s): public tree is clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
