"""Run a long BrandBAI collector command outside short host call timeouts.

The starter returns immediately. A detached worker records stdout, stderr and
the final exit code in a job directory outside the delivery folder. Hosts such
as WorkBuddy can poll ``status`` without launching the collector twice.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ACTIVE_STATES = {"queued", "starting", "running"}


class LongJobError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass


def state_path(job_dir: Path) -> Path:
    return job_dir / "job.json"


def read_state(job_dir: Path) -> dict[str, Any]:
    path = state_path(job_dir)
    if not path.is_file():
        raise LongJobError(f"Job state not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LongJobError(f"Cannot read job state: {path}") from exc
    if not isinstance(payload, dict):
        raise LongJobError(f"Invalid job state: {path}")
    return payload


def write_state(job_dir: Path, payload: dict[str, Any]) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    path = state_path(job_dir)
    temporary = job_dir / "job.json.tmp"
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def command_tail(values: Sequence[str]) -> list[str]:
    command = list(values)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise LongJobError("A command is required after --")
    return command


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            process_query = 0x1000
            still_active = 259
            handle = ctypes.windll.kernel32.OpenProcess(process_query, False, pid)
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if not ctypes.windll.kernel32.GetExitCodeProcess(
                    handle, ctypes.byref(exit_code)
                ):
                    return False
                return exit_code.value == still_active
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def start_job(
    job_dir: Path,
    cwd: Path,
    command: Sequence[str],
    popen_factory: Any = subprocess.Popen,
) -> dict[str, Any]:
    job_dir = job_dir.expanduser().resolve()
    cwd = cwd.expanduser().resolve()
    command = command_tail(command)
    if not cwd.is_dir():
        raise LongJobError(f"Working directory not found: {cwd}")
    if state_path(job_dir).exists():
        existing = read_state(job_dir)
        state = str(existing.get("state") or "unknown")
        worker_pid = int(existing.get("worker_pid") or 0)
        if state in ACTIVE_STATES and process_exists(worker_pid):
            raise LongJobError(
                f"Job is already active in {job_dir}; poll status instead of starting twice"
            )
        raise LongJobError(
            f"Job directory already contains a prior job: {job_dir}. Use a new job directory."
        )

    job_id = uuid.uuid4().hex
    payload: dict[str, Any] = {
        "schema_version": 1,
        "job_id": job_id,
        "state": "queued",
        "created_at": utc_now(),
        "started_at": "",
        "finished_at": "",
        "worker_pid": 0,
        "child_pid": 0,
        "exit_code": None,
        "cwd": str(cwd),
        "command": list(command),
        "stdout": "stdout.log",
        "stderr": "stderr.log",
        "error_type": "",
        "error": "",
    }
    write_state(job_dir, payload)

    worker_command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "worker",
        "--job-dir",
        str(job_dir),
        "--cwd",
        str(cwd),
        "--job-id",
        job_id,
        "--",
        *command,
    ]
    spawn_options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        spawn_options["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        spawn_options["start_new_session"] = True
    worker = popen_factory(worker_command, **spawn_options)

    current = read_state(job_dir)
    if current.get("job_id") == job_id and current.get("state") == "queued":
        current["state"] = "starting"
        current["worker_pid"] = int(worker.pid)
        write_state(job_dir, current)
    return read_state(job_dir)


def run_worker(job_dir: Path, cwd: Path, job_id: str, command: Sequence[str]) -> int:
    job_dir = job_dir.expanduser().resolve()
    cwd = cwd.expanduser().resolve()
    command = command_tail(command)
    payload = read_state(job_dir)
    if payload.get("job_id") != job_id:
        raise LongJobError("Worker job ID does not match job.json")

    payload.update(
        {
            "state": "running",
            "started_at": utc_now(),
            "worker_pid": os.getpid(),
            "error_type": "",
            "error": "",
        }
    )
    write_state(job_dir, payload)
    environment = os.environ.copy()
    environment.setdefault("PYTHONUTF8", "1")
    exit_code = 1
    try:
        with (job_dir / "stdout.log").open("a", encoding="utf-8") as stdout_handle, (
            job_dir / "stderr.log"
        ).open("a", encoding="utf-8") as stderr_handle:
            child = subprocess.Popen(
                list(command),
                cwd=str(cwd),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            payload = read_state(job_dir)
            payload["child_pid"] = int(child.pid)
            write_state(job_dir, payload)
            exit_code = int(child.wait())
        payload = read_state(job_dir)
        payload["exit_code"] = exit_code
        payload["state"] = (
            "completed" if exit_code == 0 else "partial" if exit_code == 3 else "failed"
        )
    except Exception as exc:
        payload = read_state(job_dir)
        payload["state"] = "failed"
        payload["exit_code"] = None
        payload["error_type"] = type(exc).__name__
        payload["error"] = str(exc)
    finally:
        payload["finished_at"] = utc_now()
        write_state(job_dir, payload)
    return exit_code if payload.get("exit_code") is not None else 1


def tail_text(path: Path, line_count: int) -> list[str]:
    if line_count <= 0 or not path.is_file():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-line_count:]


def job_status(job_dir: Path, tail_lines: int = 20) -> dict[str, Any]:
    job_dir = job_dir.expanduser().resolve()
    payload = read_state(job_dir)
    worker_pid = int(payload.get("worker_pid") or 0)
    payload["worker_alive"] = process_exists(worker_pid)
    if payload.get("state") in ACTIVE_STATES and worker_pid and not payload["worker_alive"]:
        payload["observed_state"] = "interrupted"
        payload["status_warning"] = (
            "The recorded worker is no longer running; inspect logs and the delivery checkpoint."
        )
    else:
        payload["observed_state"] = payload.get("state")
    payload["stdout_tail"] = tail_text(job_dir / "stdout.log", tail_lines)
    payload["stderr_tail"] = tail_text(job_dir / "stderr.log", tail_lines)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run and poll a long BrandBAI collector job")
    subparsers = parser.add_subparsers(dest="action", required=True)

    start = subparsers.add_parser("start", help="Start one detached collector job")
    start.add_argument("--job-dir", required=True)
    start.add_argument("--cwd", default=str(Path.cwd()))
    start.add_argument("command", nargs=argparse.REMAINDER)

    status = subparsers.add_parser("status", help="Read job state and recent logs")
    status.add_argument("--job-dir", required=True)
    status.add_argument("--tail-lines", type=int, default=20)

    worker = subparsers.add_parser("worker", help=argparse.SUPPRESS)
    worker.add_argument("--job-dir", required=True)
    worker.add_argument("--cwd", required=True)
    worker.add_argument("--job-id", required=True)
    worker.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_output()
    args = build_parser().parse_args(argv)
    try:
        if args.action == "start":
            result = start_job(Path(args.job_dir), Path(args.cwd), args.command)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.action == "status":
            result = job_status(Path(args.job_dir), max(0, args.tail_lines))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        return run_worker(
            Path(args.job_dir), Path(args.cwd), args.job_id, args.command
        )
    except LongJobError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
