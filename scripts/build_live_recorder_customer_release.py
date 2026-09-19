#!/usr/bin/env python3
"""Build a small customer-facing live-recorder handoff package."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
import zipfile
from pathlib import Path, PurePosixPath

try:
    from scripts.build_skill_release import FIXED_ZIP_TIME, build_release, skill_version
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from build_skill_release import FIXED_ZIP_TIME, build_release, skill_version


class CustomerReleaseError(RuntimeError):
    pass


def _write_zip(archive_path: Path, files: list[tuple[str, bytes]]) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for name, payload in sorted(files, key=lambda item: item[0].lower()):
            info = zipfile.ZipInfo(str(PurePosixPath(name)), date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _customer_installer(version: str, skill_archive_name: str) -> bytes:
    text = f"""@echo off
setlocal
chcp 65001 >nul
set "SKILL_ZIP=%~dp0{skill_archive_name}"
set "STAGE=%LOCALAPPDATA%\\BrandBAI\\LiveRecorderInstaller\\{version}"

if not exist "%SKILL_ZIP%" (
  echo 安装包不完整，请重新解压完整客户包后再试。
  pause
  exit /b 1
)

if not exist "%STAGE%" mkdir "%STAGE%"
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%SKILL_ZIP%' -DestinationPath '%STAGE%' -Force"
if errorlevel 1 (
  echo 安装文件未能准备，请重新解压客户包后再试。
  pause
  exit /b 1
)

call "%STAGE%\\assets\\windows-assistant\\安装 BrandBAI 直播采集助手.cmd"
"""
    return text.replace("\n", "\r\n").encode("utf-8-sig")


def _customer_uninstaller() -> bytes:
    text = """@echo off
setlocal
chcp 65001 >nul
set "ASSISTANT_SCRIPT=%LOCALAPPDATA%\\BrandBAI\\LiveRecorder\\app\\scripts\\recorder_assistant.py"

if not exist "%ASSISTANT_SCRIPT%" (
  echo 当前电脑没有找到已安装的 BrandBAI 直播采集助手。
  pause
  exit /b 0
)

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -B "%ASSISTANT_SCRIPT%" uninstall-windows
) else (
  python -B "%ASSISTANT_SCRIPT%" uninstall-windows
)

if errorlevel 1 (
  echo.
  echo 启动入口未能移除，请稍后重试。
  pause
  exit /b 1
)

echo.
echo 已有文件不会被删除。
pause
"""
    return text.replace("\n", "\r\n").encode("utf-8-sig")


def build_customer_release(repo_root: Path, dist_dir: Path) -> dict[str, object]:
    repo_root = repo_root.expanduser().resolve()
    dist_dir = dist_dir.expanduser().resolve()
    skill_dir = repo_root / "skills" / "brandbai-live-recorder"
    extension_dir = skill_dir / "assets" / "chrome-extension"
    guide_path = skill_dir / "assets" / "customer" / "01_安装与快速使用.md"
    capabilities_path = skill_dir / "assets" / "customer" / "02_Skill能力说明.md"
    manifest_path = extension_dir / "manifest.json"
    if not skill_dir.is_dir() or not extension_dir.is_dir() or not guide_path.is_file() or not capabilities_path.is_file():
        raise CustomerReleaseError("Live recorder customer release inputs are incomplete")

    version = skill_version(skill_dir / "SKILL.md")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != version:
        raise CustomerReleaseError("Skill and Chrome extension versions do not match")

    skill_customer_name = f"BrandBAI直播采集助手Skill_{version}.zip"
    extension_customer_name = f"BrandBAI直播采集助手浏览器插件_{version}.zip"
    outer_name = f"BrandBAI直播采集助手_客户版_{version}.zip"

    dist_dir.mkdir(parents=True, exist_ok=True)
    temporary_dir = dist_dir / f".brandbai-live-recorder-{uuid.uuid4().hex}"
    temporary_dir.mkdir()
    try:
        skill_result = build_release(
            skill_dir,
            temporary_dir,
            f"brandbai-live-recorder-v{version}",
        )
        skill_archive = Path(str(skill_result["archive"]))

        extension_archive = temporary_dir / extension_customer_name
        extension_files: list[tuple[str, bytes]] = []
        for path in sorted(extension_dir.rglob("*"), key=lambda item: item.as_posix().lower()):
            if not path.is_file():
                continue
            relative = path.relative_to(extension_dir).as_posix()
            if "__pycache__" in path.parts or path.suffix.lower() in {".pyc", ".pyo"}:
                continue
            extension_files.append((f"BrandBAI直播采集助手浏览器插件/{relative}", path.read_bytes()))
        _write_zip(extension_archive, extension_files)

        skill_payload = skill_archive.read_bytes()
        extension_payload = extension_archive.read_bytes()
        checksums = (
            f"{hashlib.sha256(skill_payload).hexdigest()}  {skill_customer_name}\n"
            f"{hashlib.sha256(extension_payload).hexdigest()}  {extension_customer_name}\n"
        ).encode("utf-8")

        outer_archive = dist_dir / outer_name
        _write_zip(
            outer_archive,
            [
                ("01_安装与快速使用.md", guide_path.read_bytes()),
                ("02_Skill能力说明.md", capabilities_path.read_bytes()),
                ("02_安装采集助手.cmd", _customer_installer(version, skill_customer_name)),
                ("03_卸载采集助手.cmd", _customer_uninstaller()),
                (skill_customer_name, skill_payload),
                (extension_customer_name, extension_payload),
                ("SHA256SUMS.txt", checksums),
            ],
        )
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)

    with zipfile.ZipFile(outer_archive) as archive:
        names = archive.namelist()
        bad = archive.testzip()
    if bad:
        raise CustomerReleaseError(f"Customer archive CRC verification failed: {bad}")

    checksum_path = outer_archive.with_suffix(outer_archive.suffix + ".sha256")
    digest = _sha256(outer_archive)
    checksum_path.write_text(f"{digest}  {outer_archive.name}\n", encoding="utf-8")
    return {
        "version": version,
        "archive": str(outer_archive),
        "checksum": str(checksum_path),
        "sha256": digest,
        "top_level_items": names,
        "skill_sha256": hashlib.sha256(skill_payload).hexdigest(),
        "extension_sha256": hashlib.sha256(extension_payload).hexdigest(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build BrandBAI live recorder customer package")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--dist", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_customer_release(Path(args.repo_root), Path(args.dist))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
