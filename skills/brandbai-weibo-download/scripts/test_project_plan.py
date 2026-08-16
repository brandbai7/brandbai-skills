from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collector_core import CollectionError
from project_plan import build_project_dry_run, load_project_plan, normalize_project_plan


def sample_plan() -> dict:
    return {
        "schema_version": "brandbai.weibo.project.v1",
        "project_id": "WB-PROJECT-20260810-001",
        "project_name": "合成明星官宣项目",
        "preset": "celebrity_announcement",
        "capture_depth": "standard",
        "time_window": {"start": "2026-08-01", "end": "2026-08-10"},
        "campaigns": [
            {
                "campaign_id": "campaign-a",
                "actors": [
                    {"role": "celebrity", "profile_url": "https://weibo.com/u/100001"},
                    {"role": "brand", "profile_url": "https://weibo.com/u/200002"},
                ],
                "queries": ["合成明星 合成品牌", "合成明星 合成品牌"],
                "topics": ["#合成官宣#"],
                "supertopics": [],
                "hotlists": ["文娱"],
                "seed_posts": ["https://weibo.com/100001/AbCdE123"],
                "profile_recent_n": 8,
                "search_limit": 10,
            }
        ],
        "deep_capture": {
            "selection_rule": "seed_plus_role_posts",
            "max_deep_posts_per_campaign": 4,
            "comment_limit_per_post": 200,
            "repost_limit_per_post": 100,
            "expand_replies": True,
            "download_assets": True,
        },
    }


class ProjectPlanTests(unittest.TestCase):
    def test_normalizes_project_and_deduplicates_queries(self) -> None:
        plan = normalize_project_plan(sample_plan())
        campaign = plan["campaigns"][0]
        self.assertEqual(plan["schema_version"], "brandbai.weibo.project.v1")
        self.assertEqual(campaign["queries"], ["合成明星 合成品牌"])
        self.assertEqual(campaign["topics"], ["合成官宣"])
        self.assertEqual(campaign["seed_posts"][0]["post_id"], "AbCdE123")
        self.assertEqual(campaign["hotlists"][0]["category_code"], "entrank")

    def test_requires_celebrity_and_brand_roles(self) -> None:
        value = sample_plan()
        value["campaigns"][0]["actors"] = [
            {"role": "celebrity", "profile_url": "https://weibo.com/u/100001"}
        ]
        with self.assertRaisesRegex(CollectionError, "celebrity and brand"):
            normalize_project_plan(value)

    def test_rejects_reversed_time_window(self) -> None:
        value = sample_plan()
        value["time_window"] = {"start": "2026-08-11", "end": "2026-08-10"}
        with self.assertRaisesRegex(CollectionError, "must not be after"):
            normalize_project_plan(value)

    def test_builds_stable_source_tasks_and_deferred_deep_capture(self) -> None:
        first = build_project_dry_run(
            sample_plan(), mode="all", profile_dir=Path("profile"), out=Path("delivery"),
            assets=["images", "cover"], resume=True, package_zip=True,
        )
        second = build_project_dry_run(
            sample_plan(), mode="all", profile_dir=Path("profile"), out=Path("delivery"),
            assets=["images", "cover"], resume=True, package_zip=True,
        )
        self.assertTrue(first["execution_available"])
        self.assertEqual(first["execution_scope"], "fixed_tasks_only")
        self.assertEqual(first["task_summary"]["fixed_task_count"], 6)
        self.assertEqual(first["task_summary"]["by_source_type"], {
            "hotlist": 1, "post": 1, "profile": 2, "search": 1, "topic": 1,
        })
        self.assertTrue(first["task_summary"]["deferred_deep_capture"])
        self.assertEqual(
            [task["source_task_id"] for task in first["source_tasks"]],
            [task["source_task_id"] for task in second["source_tasks"]],
        )
        post_task = next(task for task in first["source_tasks"] if task["source_type"] == "post")
        self.assertEqual(post_task["phase"], "deep_capture")
        self.assertEqual(post_task["requested_scope"]["comment_limit"], 200)

    def test_fast_plan_keeps_seed_post_in_discovery(self) -> None:
        value = sample_plan()
        value["capture_depth"] = "fast"
        result = build_project_dry_run(
            value, mode="all", profile_dir=Path("profile"), out=Path("delivery"),
            assets=[], resume=False, package_zip=False,
        )
        post_task = next(task for task in result["source_tasks"] if task["source_type"] == "post")
        self.assertEqual(post_task["phase"], "discovery")
        self.assertEqual(post_task["requested_scope"]["mode"], "posts")
        self.assertFalse(post_task["requested_scope"]["download_assets"])
        self.assertFalse(result["task_summary"]["deferred_deep_capture"])

    def test_rejects_more_seed_posts_than_deep_capture_cap(self) -> None:
        value = sample_plan()
        value["deep_capture"]["max_deep_posts_per_campaign"] = 1
        value["campaigns"][0]["seed_posts"].append("https://weibo.com/200002/FgHiJ456")
        with self.assertRaisesRegex(CollectionError, "smaller than explicit seed_posts"):
            normalize_project_plan(value)

    def test_load_project_plan_rejects_non_object_root(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            source = Path(temp) / "plan.json"
            source.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
            with self.assertRaisesRegex(CollectionError, "root must be"):
                load_project_plan(source)


if __name__ == "__main__":
    unittest.main()
