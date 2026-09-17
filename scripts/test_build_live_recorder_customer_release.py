from __future__ import annotations

import shutil
import unittest
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

from scripts.build_live_recorder_customer_release import build_customer_release
from scripts.build_skill_release import release_files


@contextmanager
def workspace_temp(root: Path):
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


class LiveRecorderCustomerReleaseTests(unittest.TestCase):
    def test_hidden_runtime_scratch_is_not_shipped(self):
        artifact_root = Path(__file__).resolve().parent.parent / '_skill_test_artifacts'
        with workspace_temp(artifact_root) as temporary:
            scratch=temporary/'scripts'/'.service-test-synthetic'
            scratch.mkdir(parents=True)
            (scratch/'should_not_ship.json').write_text('{}',encoding='utf8')
            (temporary/'SKILL.md').write_text('synthetic',encoding='utf8')
            self.assertEqual([p.relative_to(temporary).as_posix() for p in release_files(temporary)],['SKILL.md'])

    def test_customer_package_has_small_top_level_and_installable_inner_archives(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        artifact_root = repo_root / "_skill_test_artifacts"
        with workspace_temp(artifact_root) as temporary:
            result = build_customer_release(repo_root, temporary)
            archive_path = Path(str(result["archive"]))
            self.assertTrue(archive_path.is_file())
            self.assertEqual(result["version"], "0.22.10")

            expected = {
                "01_安装与快速使用.md",
                "02_Skill能力说明.md",
                "02_安装录屏助手.cmd",
                "03_卸载录屏助手.cmd",
                "BrandBAI直播录屏Skill_0.22.10.zip",
                "BrandBAI直播录屏浏览器插件_0.22.10.zip",
                "SHA256SUMS.txt",
            }
            with zipfile.ZipFile(archive_path) as outer:
                self.assertEqual(set(outer.namelist()), expected)
                self.assertIsNone(outer.testzip())
                guide = outer.read("01_安装与快速使用.md").decode("utf-8")
                self.assertIn("在浏览器中使用", guide)
                self.assertIn("下载与保存", guide)
                self.assertNotIn("127.0.0.1", guide)
                self.assertNotIn("partial_time_limit", guide)

                with workspace_temp(artifact_root) as nested_root:
                    skill_zip = nested_root / "skill.zip"
                    extension_zip = nested_root / "extension.zip"
                    skill_zip.write_bytes(outer.read("BrandBAI直播录屏Skill_0.22.10.zip"))
                    extension_zip.write_bytes(outer.read("BrandBAI直播录屏浏览器插件_0.22.10.zip"))

                    with zipfile.ZipFile(skill_zip) as skill:
                        self.assertIn("SKILL.md", skill.namelist())
                        self.assertEqual(skill.read("assets/customer/02_Skill能力说明.md"), outer.read("02_Skill能力说明.md"))
                        self.assertEqual(skill.read("assets/customer/01_安装与快速使用.md"), outer.read("01_安装与快速使用.md"))
                        self.assertIn("scripts/product_reviews.py", skill.namelist())
                        self.assertIn("scripts/product_identity.py", skill.namelist())
                        self.assertIn("scripts/export_naming.py", skill.namelist())
                        self.assertIn("scripts/interaction_export.py", skill.namelist())
                        self.assertIn("scripts/catalog_numbers.py", skill.namelist())
                        self.assertIn("scripts/browser_delivery.py", skill.namelist())
                        self.assertIn("references/export-naming-contract.md", skill.namelist())
                        self.assertFalse(any(any(p.startswith(".") for p in name.split("/")) for name in skill.namelist()))
                        self.assertIn("references/product-identity-contract.md", skill.namelist())
                        self.assertIn("references/product-review-contract.md", skill.namelist())
                        self.assertIn(
                            "assets/windows-assistant/安装 BrandBAI 直播录屏助手.cmd",
                            skill.namelist(),
                        )
                        self.assertIsNone(skill.testzip())

                    with zipfile.ZipFile(extension_zip) as extension:
                        self.assertIn(
                            "BrandBAI直播录屏浏览器插件/manifest.json",
                            extension.namelist(),
                        )
                        self.assertTrue(
                            all("__pycache__" not in name and not name.endswith(".pyc") for name in extension.namelist())
                        )
                        self.assertIsNone(extension.testzip())
                        for file in ('product-identity.js','review-panel.js','review-page.js','product-review-collector.js', 'design-tokens.css', 'browser-delivery.js', 'download-panel.js', 'ui-shell.js', 'assets/brandbai-logo.png'):
                            self.assertIn('BrandBAI直播录屏浏览器插件/'+file, extension.namelist())


if __name__ == "__main__":
    unittest.main()
