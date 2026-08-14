import shutil
import unittest
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

from scripts.build_skill_release import ARCHIVE_NAME, CHECKSUM_NAME, ReleaseBuildError, build_release


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "brandbai-douyin-download"
ANALYSIS_SKILL_DIR = ROOT / "skills" / "brandbai-douyin-account-analysis"
TMALL_SKILL_DIR = ROOT / "skills" / "brandbai-tmall-download"
XIAOHONGSHU_SKILL_DIR = ROOT / "skills" / "brandbai-xiaohongshu-download"
TIKTOK_SKILL_DIR = ROOT / "skills" / "brandbai-tiktok-download"
PRODUCT_VALUE_SKILL_DIR = ROOT / "skills" / "brandbai-product-value"
VALUE_EXPRESSION_SKILL_DIR = ROOT / "skills" / "brandbai-value-expression"


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
            result = build_release(SKILL_DIR, temp, "v0.4.0")
            archive_path = temp / ARCHIVE_NAME
            checksum_path = temp / CHECKSUM_NAME
            self.assertTrue(archive_path.is_file())
            self.assertTrue(checksum_path.is_file())
            self.assertEqual(result["version"], "0.4.0")
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertIn("SKILL.md", names)
                self.assertIn("references/license.md", names)
                self.assertIn("scripts/run_foundation.py", names)
                self.assertIn("scripts/run_long_job.py", names)
                self.assertIn("scripts/selection_contract.py", names)
                self.assertIn("scripts/package_delivery.py", names)
                self.assertIn("references/selection-contract.md", names)
                self.assertNotIn("scripts/build_foundation_workbooks.mjs", names)
                self.assertFalse(any(name.startswith("brandbai-douyin-download/") for name in names))

    def test_builds_analysis_skill_with_d1_template(self):
        with workspace_temp() as temp:
            result = build_release(
                ANALYSIS_SKILL_DIR,
                temp,
                "brandbai-douyin-account-analysis-v0.2.0",
            )
            archive_path = temp / "brandbai-douyin-account-analysis.zip"
            checksum_path = temp / "brandbai-douyin-account-analysis.zip.sha256"
            self.assertTrue(archive_path.is_file())
            self.assertTrue(checksum_path.is_file())
            self.assertEqual(result["version"], "0.2.0")
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertIn("SKILL.md", names)
                self.assertIn("assets/02_D1评论语义证据包模板.xlsx", names)
                self.assertIn("scripts/build_d1_workbook.py", names)
                self.assertIn("scripts/validate_analysis_delivery.py", names)
                self.assertFalse(any(name.startswith("brandbai-douyin-account-analysis/") for name in names))

    def test_builds_tmall_skill_at_archive_root(self):
        with workspace_temp() as temp:
            result = build_release(TMALL_SKILL_DIR, temp, "brandbai-tmall-download-v0.3.2")
            archive_path = temp / "brandbai-tmall-download.zip"
            checksum_path = temp / "brandbai-tmall-download.zip.sha256"
            self.assertTrue(archive_path.is_file())
            self.assertTrue(checksum_path.is_file())
            self.assertEqual(result["version"], "0.3.2")
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertIn("SKILL.md", names)
                self.assertIn("scripts/browser_collect_tmall.py", names)
                self.assertIn("scripts/build_delivery.py", names)
                self.assertIn("references/collection-contract.md", names)
                self.assertFalse(any(name.startswith("brandbai-tmall-download/") for name in names))

    def test_builds_xiaohongshu_skill_at_archive_root(self):
        with workspace_temp() as temp:
            result = build_release(
                XIAOHONGSHU_SKILL_DIR,
                temp,
                "brandbai-xiaohongshu-download-v0.4.0",
            )
            archive_path = temp / "brandbai-xiaohongshu-download.zip"
            checksum_path = temp / "brandbai-xiaohongshu-download.zip.sha256"
            self.assertTrue(archive_path.is_file())
            self.assertTrue(checksum_path.is_file())
            self.assertEqual(result["version"], "0.4.0")
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertIn("SKILL.md", names)
                self.assertIn("scripts/browser_collect_xiaohongshu.py", names)
                self.assertIn("scripts/build_delivery.py", names)
                self.assertIn("scripts/package_delivery.py", names)
                self.assertIn("references/collection-contract.md", names)
                self.assertIn("references/release-notes.md", names)
                self.assertFalse(any(name.startswith("brandbai-xiaohongshu-download/") for name in names))

    def test_builds_tiktok_skill_at_archive_root(self):
        with workspace_temp() as temp:
            result = build_release(
                TIKTOK_SKILL_DIR,
                temp,
                "brandbai-tiktok-download-v0.2.1",
            )
            archive_path = temp / "brandbai-tiktok-download.zip"
            checksum_path = temp / "brandbai-tiktok-download.zip.sha256"
            self.assertTrue(archive_path.is_file())
            self.assertTrue(checksum_path.is_file())
            self.assertEqual(result["version"], "0.2.1")
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertIn("SKILL.md", names)
                self.assertIn("agents/openai.yaml", names)
                self.assertIn("scripts/browser_collect_tiktok.py", names)
                self.assertIn("scripts/build_delivery.py", names)
                self.assertIn("scripts/package_delivery.py", names)
                self.assertIn("references/business-scenarios.md", names)
                self.assertIn("references/translation-policy.md", names)
                self.assertFalse(any(name.startswith("brandbai-tiktok-download/") for name in names))

    def test_builds_product_value_skill_with_contracts_and_validator(self):
        with workspace_temp() as temp:
            result = build_release(
                PRODUCT_VALUE_SKILL_DIR,
                temp,
                "brandbai-product-value-v0.1.23",
            )
            archive_path = temp / "brandbai-product-value.zip"
            checksum_path = temp / "brandbai-product-value.zip.sha256"
            self.assertTrue(archive_path.is_file())
            self.assertTrue(checksum_path.is_file())
            self.assertEqual(result["version"], "0.1.23")
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertIn("SKILL.md", names)
                self.assertIn("agents/openai.yaml", names)
                self.assertIn("references/input-output-contract.md", names)
                self.assertIn("references/release-notes.md", names)
                self.assertIn("assets/01_商品价值底座模板.md", names)
                self.assertIn("scripts/init_product_value_delivery.py", names)
                self.assertIn("scripts/index_product_sources.py", names)
                self.assertIn("scripts/build_source_audit_cards.py", names)
                self.assertIn("scripts/build_product_value_report.py", names)
                self.assertIn("scripts/validate_product_value_delivery.py", names)
                self.assertFalse(any(name.startswith("brandbai-product-value/") for name in names))

    def test_builds_value_expression_skill_with_method_and_validator(self):
        with workspace_temp() as temp:
            result = build_release(
                VALUE_EXPRESSION_SKILL_DIR,
                temp,
                "brandbai-value-expression-v0.1.3",
            )
            archive_path = temp / "brandbai-value-expression.zip"
            checksum_path = temp / "brandbai-value-expression.zip.sha256"
            self.assertTrue(archive_path.is_file())
            self.assertTrue(checksum_path.is_file())
            self.assertEqual(result["version"], "0.1.3")
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertIn("SKILL.md", names)
                self.assertIn("agents/openai.yaml", names)
                self.assertIn("references/expression-method.md", names)
                self.assertIn("references/release-notes.md", names)
                self.assertIn("assets/01_卖点可视化呈现模板.md", names)
                self.assertIn("scripts/init_value_expression_delivery.py", names)
                self.assertIn("scripts/build_value_expression_report.py", names)
                self.assertIn("scripts/validate_value_expression_delivery.py", names)
                self.assertFalse(any(name.startswith("brandbai-value-expression/") for name in names))

    def test_rejects_tag_version_mismatch(self):
        with workspace_temp() as temp:
            with self.assertRaises(ReleaseBuildError):
                build_release(SKILL_DIR, temp, "v9.9.9")


if __name__ == "__main__":
    unittest.main()
