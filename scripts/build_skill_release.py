#!/usr/bin/env python3
"""Build a deterministic, standalone BrandBAI Skill release archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable


ARCHIVE_NAME = "brandbai-douyin-download.zip"
CHECKSUM_NAME = f"{ARCHIVE_NAME}.sha256"
FORBIDDEN_PARTS = {
    ".git",
    "__pycache__",
    "data",
    "dist",
    "media",
    "outputs",
}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".sqlite3", ".xlsx", ".jsonl", ".log"}
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class ReleaseBuildError(RuntimeError):
    pass


def skill_version(skill_md: Path) -> str:
    text = skill_md.read_text(encoding="utf-8-sig")
    frontmatter = re.match(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.DOTALL)
    if not frontmatter:
        raise ReleaseBuildError("SKILL.md is missing YAML frontmatter")
    match = re.search(r'^\s{2}version:\s*["\']?([^"\'\s]+)', frontmatter.group(1), re.MULTILINE)
    if not match:
        raise ReleaseBuildError("SKILL.md metadata.version is missing")
    return match.group(1)


def release_files(skill_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(skill_dir.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file():
            continue
        relative = path.relative_to(skill_dir)
        if any(part in FORBIDDEN_PARTS for part in relative.parts):
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            continue
        files.append(path)
    return files


def validate_skill(skill_dir: Path, tag: str) -> str:
    required = [
        skill_dir / "SKILL.md",
        skill_dir / "references" / "license.md",
        skill_dir / "requirements-browser.txt",
        skill_dir / "scripts" / "run_foundation.py",
        skill_dir / "scripts" / "build_foundation_workbooks.py",
    ]
    missing = [str(path.relative_to(skill_dir)) for path in required if not path.is_file()]
    if missing:
        raise ReleaseBuildError(f"Standalone Skill is missing required files: {', '.join(missing)}")
    version = skill_version(skill_dir / "SKILL.md")
    if tag and tag != f"v{version}":
        raise ReleaseBuildError(f"Tag {tag!r} does not match SKILL.md version v{version}")
    return version


def write_archive(skill_dir: Path, archive_path: Path, files: Iterable[Path]) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for source in files:
            relative = PurePosixPath(source.relative_to(skill_dir).as_posix())
            info = zipfile.ZipInfo(str(relative), date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def inspect_archive(archive_path: Path) -> list[str]:
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if "SKILL.md" not in names:
            raise ReleaseBuildError("Archive root must contain SKILL.md")
        if "references/license.md" not in names:
            raise ReleaseBuildError("Archive must contain references/license.md")
        if any(name.startswith("brandbai-douyin-download/") for name in names):
            raise ReleaseBuildError("Archive must not add an enclosing skill directory")
        bad = archive.testzip()
        if bad:
            raise ReleaseBuildError(f"Archive CRC verification failed: {bad}")
    return names


def build_release(skill_dir: Path, dist_dir: Path, tag: str = "") -> dict[str, object]:
    skill_dir = skill_dir.expanduser().resolve()
    dist_dir = dist_dir.expanduser().resolve()
    if not skill_dir.is_dir():
        raise ReleaseBuildError(f"Skill directory not found: {skill_dir}")
    version = validate_skill(skill_dir, tag)
    files = release_files(skill_dir)
    archive_path = dist_dir / ARCHIVE_NAME
    checksum_path = dist_dir / CHECKSUM_NAME
    write_archive(skill_dir, archive_path, files)
    names = inspect_archive(archive_path)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{digest}  {ARCHIVE_NAME}\n", encoding="ascii")
    return {
        "skill": skill_dir.name,
        "version": version,
        "tag": tag or f"v{version}",
        "archive": str(archive_path),
        "checksum": str(checksum_path),
        "sha256": digest,
        "files": len(names),
        "root_skill_md": names[0] == "SKILL.md" or "SKILL.md" in names,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a standalone BrandBAI Skill ZIP")
    parser.add_argument("--skill-dir", required=True)
    parser.add_argument("--dist", required=True)
    parser.add_argument("--tag", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_release(Path(args.skill_dir), Path(args.dist), args.tag)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
