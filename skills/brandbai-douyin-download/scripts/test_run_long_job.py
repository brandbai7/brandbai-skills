import shutil
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from run_long_job import LongJobError, job_status, run_worker, start_job, write_state


@contextmanager
def workspace_temp():
    root = Path.cwd() / "_long_job_test_artifacts"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"case_{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        try:
            root.rmdir()
        except OSError:
            pass


def seed_job(job_dir: Path, job_id: str) -> None:
    write_state(
        job_dir,
        {
            "schema_version": 1,
            "job_id": job_id,
            "state": "queued",
            "created_at": "2026-01-01T00:00:00+00:00",
            "started_at": "",
            "finished_at": "",
            "worker_pid": 0,
            "child_pid": 0,
            "exit_code": None,
            "cwd": str(Path.cwd()),
            "command": [],
            "stdout": "stdout.log",
            "stderr": "stderr.log",
            "error_type": "",
            "error": "",
        },
    )


class RunLongJobTests(unittest.TestCase):
    def test_worker_records_stdout_and_success(self):
        with workspace_temp() as temp:
            job_id = uuid.uuid4().hex
            seed_job(temp, job_id)
            exit_code = run_worker(
                temp,
                Path.cwd(),
                job_id,
                [sys.executable, "-c", "print('collector finished')"],
            )
            self.assertEqual(exit_code, 0)
            status = job_status(temp, 5)
            self.assertEqual(status["state"], "completed")
            self.assertEqual(status["exit_code"], 0)
            self.assertIn("collector finished", status["stdout_tail"])
            self.assertEqual(status["stderr_tail"], [])

    def test_worker_maps_exit_three_to_partial(self):
        with workspace_temp() as temp:
            job_id = uuid.uuid4().hex
            seed_job(temp, job_id)
            exit_code = run_worker(
                temp,
                Path.cwd(),
                job_id,
                [sys.executable, "-c", "raise SystemExit(3)"],
            )
            self.assertEqual(exit_code, 3)
            status = job_status(temp, 0)
            self.assertEqual(status["state"], "partial")
            self.assertEqual(status["exit_code"], 3)

    def test_start_returns_immediately_and_blocks_duplicate_active_job(self):
        with workspace_temp() as temp:
            fake_worker = SimpleNamespace(pid=43210)
            first = start_job(
                temp,
                Path.cwd(),
                [sys.executable, "-c", "print('queued')"],
                popen_factory=lambda *_args, **_kwargs: fake_worker,
            )
            self.assertEqual(first["state"], "starting")
            self.assertEqual(first["worker_pid"], 43210)
            with patch("run_long_job.process_exists", return_value=True):
                with self.assertRaisesRegex(LongJobError, "already active"):
                    start_job(
                        temp,
                        Path.cwd(),
                        [sys.executable, "-c", "print('duplicate')"],
                        popen_factory=lambda *_args, **_kwargs: fake_worker,
                    )


if __name__ == "__main__":
    unittest.main()
