from __future__ import annotations

import contextlib
import shutil
import uuid
from pathlib import Path
from typing import Iterator


@contextlib.contextmanager
def workspace_temp() -> Iterator[str]:
    """Create a writable test directory without Python 3.14's Windows temp ACL."""

    root = Path(__file__).resolve().parent / ".test-tmp"
    root.mkdir(exist_ok=True)
    path = root / f"case-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)
        try:
            root.rmdir()
        except OSError:
            pass
