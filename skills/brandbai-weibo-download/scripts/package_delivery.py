"""Create a deterministic, ZIP64-capable BrandBAI delivery archive."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Any


ALREADY_COMPRESSED = {".mp4", ".mov", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".xlsx", ".zip"}


class PackageError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_directory(source_value: str | Path, zip_value: str | Path | None = None) -> dict[str, Any]:
    source = Path(source_value).expanduser().resolve()
    if not source.is_dir():
        raise PackageError(f"Delivery directory not found: {source}")
    target = Path(zip_value).expanduser().resolve() if zip_value else source.with_suffix(".zip")
    if target == source or source in target.parents:
        raise PackageError("ZIP output must be outside the delivery directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)
    files = sorted(path for path in source.rglob("*") if path.is_file() and not path.name.endswith(".part"))
    if not files:
        raise PackageError("Delivery directory contains no files")
    try:
        with zipfile.ZipFile(partial, "w", allowZip64=True) as archive:
            for path in files:
                compression = zipfile.ZIP_STORED if path.suffix.lower() in ALREADY_COMPRESSED else zipfile.ZIP_DEFLATED
                archive.write(path, arcname=(Path(source.name) / path.relative_to(source)).as_posix(), compress_type=compression)
        partial.replace(target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return {"zip": str(target), "files": len(files), "bytes": target.stat().st_size, "sha256": sha256_file(target)}
