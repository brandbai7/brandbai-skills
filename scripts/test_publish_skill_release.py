import os
import shutil
import subprocess
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publish_skill_release.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def find_bash():
    bash = shutil.which("bash")
    if bash:
        return bash
    git = shutil.which("git")
    if git:
        bundled_bash = Path(git).resolve().parents[1] / "bin" / "bash.exe"
        if bundled_bash.is_file():
            return str(bundled_bash)
    return None


BASH = find_bash()


@contextmanager
def workspace_temp():
    root = ROOT / "_skill_test_artifacts"
    root.mkdir(exist_ok=True)
    path = root / f"release_{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        try:
            root.rmdir()
        except OSError:
            pass


@unittest.skipUnless(BASH, "bash is required to test the release publisher")
class PublishSkillReleaseTests(unittest.TestCase):
    def test_workflow_builds_only_the_tagged_skill(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('--skill-dir "skills/${SKILL_NAME}"', workflow)
        self.assertNotIn('for skill_dir in skills/*', workflow)

    def run_publisher(self, release_exists: bool, include_assets: bool = True):
        with workspace_temp() as temp:
            if include_assets:
                dist = temp / "dist"
                dist.mkdir()
                (dist / "brandbai-example.zip").write_bytes(b"zip")
                (dist / "brandbai-example.zip.sha256").write_text(
                    "digest  brandbai-example.zip\n",
                    encoding="ascii",
                )
            (temp / "notes.md").write_text("Release notes\n", encoding="utf-8")

            fake_gh = temp / "fake-gh.sh"
            fake_gh.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"${GH_CALL_LOG}\"\n"
                "if [[ \"$1 $2\" == \"release view\" ]]; then\n"
                "  exit \"${GH_RELEASE_VIEW_EXIT}\"\n"
                "fi\n",
                encoding="utf-8",
                newline="\n",
            )
            fake_gh.chmod(0o755)

            env = os.environ.copy()
            env.update(
                {
                    "GITHUB_REF_NAME": "brandbai-example-v1.2.3",
                    "NOTES_FILE": "notes.md",
                    "GH_CLI": "./fake-gh.sh",
                    "GH_CALL_LOG": "gh-calls.log",
                    "GH_RELEASE_VIEW_EXIT": "0" if release_exists else "1",
                }
            )
            relative_script = os.path.relpath(SCRIPT, temp).replace("\\", "/")
            result = subprocess.run(
                [BASH, relative_script],
                cwd=temp,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            call_log = temp / "gh-calls.log"
            calls = call_log.read_text(encoding="utf-8").splitlines() if call_log.exists() else []
            return result, calls

    def test_creates_release_when_tag_has_no_release(self):
        result, calls = self.run_publisher(release_exists=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[0], "release view brandbai-example-v1.2.3")
        self.assertIn("release create brandbai-example-v1.2.3", calls[1])
        self.assertIn("dist/brandbai-example.zip", calls[1])
        self.assertIn("dist/brandbai-example.zip.sha256", calls[1])
        self.assertIn("--verify-tag", calls[1])
        self.assertNotIn("release edit", "\n".join(calls))
        self.assertNotIn("release upload", "\n".join(calls))

    def test_updates_existing_release_and_replaces_assets(self):
        result, calls = self.run_publisher(release_exists=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[0], "release view brandbai-example-v1.2.3")
        self.assertIn("release edit brandbai-example-v1.2.3", calls[1])
        self.assertIn("--notes-file notes.md", calls[1])
        self.assertIn("release upload brandbai-example-v1.2.3", calls[2])
        self.assertIn("dist/brandbai-example.zip", calls[2])
        self.assertIn("dist/brandbai-example.zip.sha256", calls[2])
        self.assertIn("--clobber", calls[2])
        self.assertNotIn("release create", "\n".join(calls))

    def test_fails_before_calling_github_when_assets_are_missing(self):
        result, calls = self.run_publisher(release_exists=False, include_assets=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No release assets found in dist", result.stderr)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
