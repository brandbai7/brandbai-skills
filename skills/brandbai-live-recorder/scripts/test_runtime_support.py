from __future__ import annotations

import io
import shutil
import sys
import unittest
import uuid
from contextlib import contextmanager
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import bootstrap_runtime
import runtime_support as runtime


@contextmanager
def scratch_dir():
    path = Path(__file__).resolve().parent / f".runtime-test-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class RuntimeSupportTests(unittest.TestCase):
    def test_workspace_candidate_is_discoverable_without_an_absolute_contract(self) -> None:
        with scratch_dir() as root:
            cwd = root / "project" / "nested"
            cwd.mkdir(parents=True)
            expected = root / "project" / ".runtime" / "brandbai-live-recorder" / "site-packages"
            candidates = runtime.runtime_candidates(cwd=cwd, home=root / "home", environ={})
            self.assertIn(("workspace_runtime", expected), candidates)

    def test_existing_runtime_is_activated_before_install(self) -> None:
        with scratch_dir() as root:
            site = root / ".runtime" / "brandbai-live-recorder" / "site-packages"
            site.mkdir(parents=True)
            ready = runtime.RuntimeStatus(
                ready=True,
                version="4.0.10",
                source="workspace_runtime",
                site_packages=site,
            )
            with patch("runtime_support._import_status", side_effect=[runtime.RuntimeStatus(False), ready]):
                status = runtime.activate_existing_streamget_runtime(cwd=root, home=root, environ={})
            self.assertTrue(status.ready)
            self.assertEqual(status.source, "workspace_runtime")
            self.assertIn(str(site), sys.path)
            sys.path.remove(str(site))

    def test_install_failure_is_redacted_and_stable(self) -> None:
        completed = Mock(returncode=1, stdout="private proxy value", stderr="secret token")
        with scratch_dir() as root:
            with patch("runtime_support.activate_existing_streamget_runtime", return_value=runtime.RuntimeStatus(False)):
                with patch("runtime_support.default_runtime_site_packages", return_value=root / "site-packages"):
                    with patch("runtime_support.subprocess.run", return_value=completed):
                        with self.assertRaises(runtime.RuntimeSetupError) as caught:
                            runtime.ensure_streamget_runtime(auto_install=True)
            rendered = str(caught.exception)
            self.assertNotIn("private proxy", rendered)
            self.assertNotIn("secret token", rendered)

    def test_first_use_install_returns_only_public_runtime_status(self) -> None:
        completed = Mock(returncode=0, stdout="installed", stderr="")
        with scratch_dir() as root:
            target = root / "site-packages"
            prepared = runtime.RuntimeStatus(
                True,
                "4.0.10",
                "user_private_runtime",
                site_packages=target,
            )
            with patch("runtime_support.activate_existing_streamget_runtime", return_value=runtime.RuntimeStatus(False)):
                with patch("runtime_support.default_runtime_site_packages", return_value=target):
                    with patch("runtime_support.subprocess.run", return_value=completed) as installer:
                        with patch("runtime_support._import_status", return_value=prepared):
                            status = runtime.ensure_streamget_runtime(auto_install=True)
            self.assertTrue(status.ready)
            self.assertTrue(status.prepared_this_run)
            self.assertEqual(status.version, "4.0.10")
            command = installer.call_args.args[0]
            expected_flags = getattr(runtime.subprocess, "CREATE_NO_WINDOW", 0) if runtime.os.name == "nt" else 0
            self.assertEqual(installer.call_args.kwargs["creationflags"], expected_flags)
            self.assertIn(runtime.STREAMGET_REQUIREMENT, command)
            self.assertNotIn(str(target), str(status.public_summary()))

    def test_bootstrap_check_never_prints_runtime_path(self) -> None:
        status = runtime.RuntimeStatus(
            ready=True,
            version="4.0.10",
            source="user_private_runtime",
            site_packages=Path("private/location"),
        )
        buffer = io.StringIO()
        with patch("bootstrap_runtime.activate_existing_streamget_runtime", return_value=status):
            with redirect_stdout(buffer):
                exit_code = bootstrap_runtime.main(["check"])
        self.assertEqual(exit_code, 0)
        self.assertNotIn("private/location", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
