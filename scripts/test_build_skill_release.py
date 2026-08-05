import shutil
import unittest
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

from scripts.build_skill_release import ARCHIVE_NAME, CHECKSUM_NAME, ReleaseBuildError, build_release


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "brandbai-douyin-download"


@contextmanager
def workspace_temp():
    root = ROOT / "_skill_test_artifacts"
    root.mkdir(exist_ok=True)
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


class BuildSkillReleaseTests(unittest.TestCase):
    def test_builds_skill_at_archive_root(self):
        with workspace_temp() as temp:
            result = build_release(SKILL_DIR, temp, "v0.2.4")
            archive_path = temp / ARCHIVE_NAME
            checksum_path = temp / CHECKSUM_NAME
            self.assertTrue(archive_path.is_file())
            self.assertTrue(checksum_path.is_file())
            self.assertEqual(result["version"], "0.2.4")
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertIn("SKILL.md", names)
                self.assertIn("references/license.md", names)
                self.assertIn("scripts/run_foundation.py", names)
                self.assertNotIn("scripts/build_foundation_workbooks.mjs", names)
                self.assertFalse(any(name.startswith("brandbai-douyin-download/") for name in names))

    def test_rejects_tag_version_mismatch(self):
        with workspace_temp() as temp:
            with self.assertRaises(ReleaseBuildError):
                build_release(SKILL_DIR, temp, "v9.9.9")


if __name__ == "__main__":
    unittest.main()
