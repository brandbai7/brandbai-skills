"""Discover and prepare the private StreamGet runtime used by the recorder."""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


STREAMGET_REQUIREMENT = "streamget==4.0.10"
RUNTIME_ENVIRONMENT_VARIABLE = "BRANDBAI_LIVE_RUNTIME_ROOT"


class RuntimeSetupError(RuntimeError):
    """Raised when the private resolver runtime cannot be prepared safely."""

    reason_code = "runtime_dependency_unavailable"


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    ready: bool
    version: str | None = None
    source: str = "missing"
    prepared_this_run: bool = False
    site_packages: Path | None = None

    def public_summary(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "version": self.version,
            "source": self.source,
            "prepared_this_run": self.prepared_this_run,
            "path_exposed": False,
        }


def default_runtime_site_packages(*, home: Path | None = None) -> Path:
    base = home or Path.home()
    if os.name == "nt":
        return base / "AppData" / "Local" / "BrandBAI" / "live-recorder" / "site-packages"
    return base / ".local" / "share" / "BrandBAI" / "live-recorder" / "site-packages"


def _normalize_candidate(path: Path) -> Path:
    expanded = path.expanduser()
    nested = expanded / "site-packages"
    return nested if nested.is_dir() else expanded


def runtime_candidates(
    *,
    cwd: Path | None = None,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[tuple[str, Path]]:
    values = os.environ if environ is None else environ
    candidates: list[tuple[str, Path]] = []
    configured = values.get(RUNTIME_ENVIRONMENT_VARIABLE, "").strip()
    if configured:
        candidates.append(("environment_override", _normalize_candidate(Path(configured))))

    working = (cwd or Path.cwd()).resolve()
    for parent in (working, *working.parents):
        candidates.append(
            (
                "workspace_runtime",
                parent / ".runtime" / "brandbai-live-recorder" / "site-packages",
            )
        )
    candidates.append(("user_private_runtime", default_runtime_site_packages(home=home)))

    unique: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for source, candidate in candidates:
        marker = os.path.normcase(os.path.abspath(str(candidate)))
        if marker not in seen:
            seen.add(marker)
            unique.append((source, candidate))
    return unique


def _purge_failed_streamget_import() -> None:
    for name in tuple(sys.modules):
        if name == "streamget" or name.startswith("streamget."):
            sys.modules.pop(name, None)


def _import_status(*, source: str, site_packages: Path | None = None) -> RuntimeStatus:
    try:
        importlib.invalidate_caches()
        module = importlib.import_module("streamget")
        resolver = getattr(module, "DouyinLiveStream")
        if not callable(resolver):
            raise ImportError("DouyinLiveStream is not callable")
        version = importlib.metadata.version("streamget")
        return RuntimeStatus(
            ready=True,
            version=str(version),
            source=source,
            site_packages=site_packages,
        )
    except (AttributeError, ImportError, importlib.metadata.PackageNotFoundError, OSError):
        _purge_failed_streamget_import()
        return RuntimeStatus(ready=False)


def activate_existing_streamget_runtime(
    *,
    cwd: Path | None = None,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> RuntimeStatus:
    current = _import_status(source="current_python_environment")
    if current.ready:
        return current

    for source, candidate in runtime_candidates(cwd=cwd, home=home, environ=environ):
        try:
            if not candidate.is_dir():
                continue
        except OSError:
            continue
        value = str(candidate)
        already_present = value in sys.path
        if not already_present:
            sys.path.insert(0, value)
        status = _import_status(source=source, site_packages=candidate)
        if status.ready:
            return status
        if not already_present:
            try:
                sys.path.remove(value)
            except ValueError:
                pass
    return RuntimeStatus(ready=False)


def ensure_streamget_runtime(
    *,
    auto_install: bool,
    cwd: Path | None = None,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    timeout_seconds: int = 600,
) -> RuntimeStatus:
    existing = activate_existing_streamget_runtime(cwd=cwd, home=home, environ=environ)
    if existing.ready:
        return existing
    if not auto_install:
        raise RuntimeSetupError(
            "StreamGet runtime is unavailable; first-use setup is required before a real probe or recording"
        )

    target = default_runtime_site_packages(home=home)
    try:
        target.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                "--upgrade",
                "--target",
                str(target),
                STREAMGET_REQUIREMENT,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeSetupError(
            f"StreamGet first-use setup could not finish: {type(exc).__name__}"
        ) from exc
    if completed.returncode != 0:
        raise RuntimeSetupError(
            "StreamGet first-use setup failed; check the approved network and package source, then retry"
        )

    _purge_failed_streamget_import()
    value = str(target)
    if value not in sys.path:
        sys.path.insert(0, value)
    prepared = _import_status(source="user_private_runtime", site_packages=target)
    if not prepared.ready:
        raise RuntimeSetupError(
            "StreamGet was downloaded but its Douyin resolver could not be loaded"
        )
    return RuntimeStatus(
        ready=True,
        version=prepared.version,
        source=prepared.source,
        prepared_this_run=True,
        site_packages=prepared.site_packages,
    )
