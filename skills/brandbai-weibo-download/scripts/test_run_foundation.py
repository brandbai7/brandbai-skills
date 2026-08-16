from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from run_foundation import main


class RunFoundationTests(unittest.TestCase):
    @staticmethod
    def _project_plan() -> dict:
        return {
            "schema_version": "brandbai.weibo.project.v1",
            "project_id": "WB-PROJECT-20260810-002",
            "project_name": "合成双主体官宣项目",
            "preset": "celebrity_announcement",
            "capture_depth": "standard",
            "time_window": {"start": "2026-08-01", "end": "2026-08-10"},
            "campaigns": [{
                "campaign_id": "campaign-a",
                "actors": [
                    {"role": "celebrity", "profile_url": "https://weibo.com/u/100001"},
                    {"role": "brand", "profile_url": "https://weibo.com/u/200002"},
                ],
                "queries": ["合成明星 合成品牌"],
                "seed_posts": ["https://weibo.com/100001/AbCdE123"],
            }],
        }

    def test_dry_run_builds_post_plan_without_launching_browser(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main([
                    "all", "--post", "https://weibo.com/2712305611/RbNQaAljk?secret=1",
                    "--profile-dir", str(root / "profile"), "--out", str(root / "delivery"),
                    "--assets", "images,cover", "--include-replies", "--dry-run",
                ])
            self.assertEqual(code, 0)
            plan = json.loads(buffer.getvalue())
            self.assertEqual(plan["posts"][0]["post_id"], "RbNQaAljk")
            self.assertEqual(plan["posts"][0]["canonical_url"], "https://weibo.com/2712305611/RbNQaAljk")
            self.assertEqual(plan["privacy_mode"], "interaction_authors_pseudonymized")

    def test_rejects_profile_directory_inside_delivery(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            with redirect_stderr(io.StringIO()):
                code = main([
                    "posts", "--post", "RbNQaAljk", "--profile-dir", str(root / "delivery" / "profile"),
                    "--out", str(root / "delivery"), "--dry-run",
                ])
            self.assertEqual(code, 2)

    def test_dry_run_builds_supertopic_plan(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            buffer = io.StringIO()
            source = "https://weibo.com/p/1008081c60117765725e0da0e23007ba00d630/super_index?mod=TAB"
            with redirect_stdout(buffer):
                code = main([
                    "posts", "--supertopic", source, "--supertopic-tab", "latest", "--search-limit", "3",
                    "--profile-dir", str(root / "profile"), "--out", str(root / "delivery"), "--dry-run",
                ])
            self.assertEqual(code, 0)
            plan = json.loads(buffer.getvalue())
            self.assertEqual(plan["supertopic"]["selected_tab"], "最新")
            self.assertEqual(plan["supertopic"]["first_visible_results"], 3)

    def test_dry_run_builds_entertainment_hotlist_plan(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main([
                    "posts", "--hotlist", "文娱", "--hotlist-limit", "50",
                    "--profile-dir", str(root / "profile"), "--out", str(root / "delivery"), "--dry-run",
                ])
            self.assertEqual(code, 0)
            plan = json.loads(buffer.getvalue())
            self.assertEqual(plan["hotlist"]["category_code"], "entrank")
            self.assertEqual(plan["hotlist"]["ranked_limit"], 50)
            self.assertEqual(plan["hotlist"]["visible_pinned_and_special_rows"], "additional")

    def test_dry_run_builds_project_plan_without_launching_browser(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            plan_path = root / "project_plan.json"
            plan_path.write_text(json.dumps(self._project_plan(), ensure_ascii=False), encoding="utf-8")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main([
                    "all", "--project-plan", str(plan_path),
                    "--profile-dir", str(root / "profile"), "--out", str(root / "delivery"),
                    "--assets", "images,cover", "--resume", "--zip", "--dry-run",
                ])
            self.assertEqual(code, 0)
            result = json.loads(buffer.getvalue())
            self.assertEqual(result["operation"], "project_dry_run")
            self.assertTrue(result["execution_available"])
            self.assertEqual(result["execution_scope"], "fixed_tasks_only")
            self.assertEqual(result["task_summary"]["fixed_task_count"], 4)
            self.assertEqual(result["runtime"]["browser_policy"], "one_visible_signed_in_chrome_session_for_the_project")
            self.assertTrue(result["boundaries"]["download_only"])

    def test_project_plan_execution_runs_collection_merge_and_delivery(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            plan_path = root / "project_plan.json"
            plan_path.write_text(json.dumps(self._project_plan(), ensure_ascii=False), encoding="utf-8")
            project_result = {"state": "complete", "project_id": "WB-PROJECT-20260810-002"}
            finalization = {
                "merge": {"counts": {"posts": 1}, "project_manifest": project_result},
                "delivery": {"generated_files": ["00_项目采集总览.xlsx"]},
            }
            with patch("run_foundation.run_project_tasks", return_value=project_result) as run_tasks, patch(
                "run_foundation.finalize_project_delivery", return_value=finalization
            ) as finalize, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = main([
                    "all", "--project-plan", str(plan_path),
                    "--profile-dir", str(root / "profile"), "--out", str(root / "delivery"),
                ])
            self.assertEqual(code, 0)
            run_tasks.assert_called_once()
            finalize.assert_called_once_with((root / "delivery").resolve())


if __name__ == "__main__":
    unittest.main()
