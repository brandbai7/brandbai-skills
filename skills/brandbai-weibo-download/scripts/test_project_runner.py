from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from json import loads
from pathlib import Path
from unittest.mock import patch

from collector_core import CollectionError
from project_runner import execute_browser_source_task, run_project_tasks


def project_plan(*, selection_rule: str = "seed_only") -> dict:
    return {
        "schema_version": "brandbai.weibo.project.v1",
        "project_id": "WB-PROJECT-20260810-QUEUE",
        "project_name": "合成项目队列测试",
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
            "profile_recent_n": 3,
            "search_limit": 5,
        }],
        "deep_capture": {
            "selection_rule": selection_rule,
            "max_deep_posts_per_campaign": 3,
            "comment_limit_per_post": 20,
            "repost_limit_per_post": 10,
            "expand_replies": True,
            "download_assets": False,
        },
    }


class FakeSessionFactory:
    def __init__(self) -> None:
        self.opens = 0
        self.context = object()
        self.page = object()

    @contextmanager
    def __call__(self, **_: object):
        self.opens += 1
        yield self.context, self.page


class ProjectRunnerTests(unittest.TestCase):
    @staticmethod
    def _browser_task_kwargs(task_out: Path) -> dict:
        return {
            "task_out": task_out,
            "context": object(),
            "page": object(),
            "assets": ["images", "cover"],
            "max_profile_scroll_actions": 10,
            "max_search_scroll_actions": 10,
            "max_scroll_actions": 20,
            "login_wait": 0,
            "retain_author_display": False,
            "max_asset_mb": 10,
            "resume": False,
        }

    def test_all_tasks_share_one_session_and_complete(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            session = FakeSessionFactory()
            observations: list[tuple[object, object, str]] = []

            def executor(task: dict, **kwargs: object) -> dict:
                observations.append((kwargs["context"], kwargs["page"], task["source_task_id"]))
                return {"state": "complete_visible_test"}

            result = run_project_tasks(
                project_plan(), profile_dir=root / "profile", out=root / "delivery",
                mode="all", assets=[], resume=False,
                task_executor=executor, session_factory=session,
            )
            self.assertEqual(session.opens, 1)
            self.assertEqual(len(observations), 4)
            self.assertTrue(all(item[0] is session.context and item[1] is session.page for item in observations))
            self.assertEqual(result["state"], "complete")
            self.assertEqual(result["source_task_counts"], {"complete": 4})
            self.assertFalse(result["usable_for_handoff"])

    def test_resume_skips_complete_tasks_and_retries_partial(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            first_calls: list[str] = []

            def first_executor(task: dict, **_: object) -> dict:
                first_calls.append(task["source_task_id"])
                state = "partial_selector_drift" if len(first_calls) == 2 else "complete_visible_test"
                return {"state": state}

            run_project_tasks(
                project_plan(), profile_dir=root / "profile", out=root / "delivery",
                mode="all", assets=[], resume=False,
                task_executor=first_executor, session_factory=FakeSessionFactory(),
            )
            retry_calls: list[str] = []

            def retry_executor(task: dict, **_: object) -> dict:
                retry_calls.append(task["source_task_id"])
                return {"state": "complete_visible_test"}

            result = run_project_tasks(
                project_plan(), profile_dir=root / "profile", out=root / "delivery",
                mode="all", assets=[], resume=True,
                task_executor=retry_executor, session_factory=FakeSessionFactory(),
            )
            self.assertEqual(len(retry_calls), 1)
            self.assertEqual(result["state"], "complete")
            self.assertEqual(result["source_task_counts"], {"complete": 4})

    def test_login_block_stops_later_tasks_and_can_resume(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            calls: list[str] = []

            def blocked_executor(task: dict, **_: object) -> dict:
                calls.append(task["source_task_id"])
                raise CollectionError("Weibo requires manual login or verification in the visible Chrome window")

            result = run_project_tasks(
                project_plan(), profile_dir=root / "profile", out=root / "delivery",
                mode="all", assets=[], resume=False,
                task_executor=blocked_executor, session_factory=FakeSessionFactory(),
            )
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["state"], "blocked")
            self.assertEqual(result["source_task_counts"], {"blocked": 1, "queued": 3})
            self.assertTrue(result["resume_available"])

    def test_deferred_deep_targets_keep_project_partial(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            result = run_project_tasks(
                project_plan(selection_rule="seed_plus_role_posts"),
                profile_dir=root / "profile", out=root / "delivery",
                mode="all", assets=[], resume=False,
                task_executor=lambda task, **kwargs: {"state": "complete_visible_test"},
                session_factory=FakeSessionFactory(),
            )
            self.assertEqual(result["state"], "partial")
            self.assertTrue(result["fixed_tasks_complete"])
            self.assertTrue(result["deferred_deep_capture"])
            self.assertTrue(result["resume_available"])

    def test_existing_state_requires_resume(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            run_project_tasks(
                project_plan(), profile_dir=root / "profile", out=root / "delivery",
                mode="all", assets=[], resume=False,
                task_executor=lambda task, **kwargs: {"state": "complete_visible_test"},
                session_factory=FakeSessionFactory(),
            )
            with self.assertRaisesRegex(CollectionError, "use --resume"):
                run_project_tasks(
                    project_plan(), profile_dir=root / "profile", out=root / "delivery",
                    mode="all", assets=[], resume=False,
                    task_executor=lambda task, **kwargs: {"state": "complete_visible_test"},
                    session_factory=FakeSessionFactory(),
                )

    def test_completed_resume_does_not_open_browser(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            run_project_tasks(
                project_plan(), profile_dir=root / "profile", out=root / "delivery",
                mode="all", assets=[], resume=False,
                task_executor=lambda task, **kwargs: {"state": "complete_visible_test"},
                session_factory=FakeSessionFactory(),
            )
            session = FakeSessionFactory()
            result = run_project_tasks(
                project_plan(), profile_dir=root / "profile", out=root / "delivery",
                mode="all", assets=[], resume=True,
                task_executor=lambda task, **kwargs: {"state": "complete_visible_test"},
                session_factory=session,
            )
            self.assertEqual(session.opens, 0)
            self.assertEqual(result["state"], "complete")

    def test_resume_rejects_changed_frozen_plan(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            run_project_tasks(
                project_plan(), profile_dir=root / "profile", out=root / "delivery",
                mode="all", assets=[], resume=False,
                task_executor=lambda task, **kwargs: {"state": "complete_visible_test"},
                session_factory=FakeSessionFactory(),
            )
            changed = project_plan()
            changed["campaigns"][0]["search_limit"] = 9
            with self.assertRaisesRegex(CollectionError, "plan changed"):
                run_project_tasks(
                    changed, profile_dir=root / "profile", out=root / "delivery",
                    mode="all", assets=[], resume=True,
                    task_executor=lambda task, **kwargs: {"state": "complete_visible_test"},
                    session_factory=FakeSessionFactory(),
                )

    def test_profile_task_saves_list_snapshot_without_opening_post_details(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            task = {
                "source_task_id": "derived:weibo-project-task:aaaaaaaaaaaaaaaaaaaaaaaa",
                "campaign_id": "campaign-a",
                "source_type": "profile",
                "target_key": "100001",
                "canonical_url": "https://weibo.com/u/100001",
                "requested_scope": {"recent_non_pinned": 3},
            }
            selection = {
                "state": "complete_visible_pinned_plus_recent_n",
                "profile_id": "100001",
                "account": {"uid": "100001", "display_name": "合成账号"},
                "selected": [{
                    "post_id": "AbCdE123", "author_uid": "100001", "rank": 1,
                    "is_pinned": True, "selection_reason": "pinned",
                }],
            }
            with patch("project_runner._discover_profile_posts", return_value=selection), patch(
                "project_runner._collect_one_post"
            ) as collect_post:
                result = execute_browser_source_task(task, **self._browser_task_kwargs(root / "task"))
            self.assertEqual(result["state"], "complete_visible_pinned_plus_recent_n")
            self.assertEqual(result["saved_visible_post_refs"], 1)
            self.assertTrue((root / "task" / "data" / "profile_selection.json").is_file())
            self.assertTrue((root / "task" / "data" / "accounts.jsonl").is_file())
            collect_post.assert_not_called()

    def test_post_task_preserves_component_partial_state(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            task = {
                "source_task_id": "derived:weibo-project-task:bbbbbbbbbbbbbbbbbbbbbbbb",
                "campaign_id": "campaign-a",
                "source_type": "post",
                "target_key": "AbCdE123",
                "canonical_url": "https://weibo.com/100001/AbCdE123",
                "selection_reason": "explicit_seed_post",
                "requested_scope": {
                    "mode": "all", "comment_limit": 20, "repost_limit": 10,
                    "include_replies": True, "download_assets": False,
                },
            }
            with patch("project_runner._collect_one_post", return_value=(
                {"post_id": "AbCdE123", "completion_state": "complete_visible_post"},
                {"state": "partial_reply_not_expanded"},
                {"state": "complete_visible_reposts_exhausted"},
            )):
                result = execute_browser_source_task(task, **self._browser_task_kwargs(root / "task"))
            self.assertEqual(result["state"], "partial")
            self.assertEqual(result["comment_state"], "partial_reply_not_expanded")
            manifest = loads((root / "task" / "data" / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["state"], "partial")

    def test_post_task_marks_fulfilled_limits_complete_without_claiming_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            task = {
                "source_task_id": "derived:weibo-project-task:cccccccccccccccccccccccc",
                "campaign_id": "campaign-a",
                "source_type": "post",
                "target_key": "AbCdE123",
                "canonical_url": "https://weibo.com/100001/AbCdE123",
                "selection_reason": "explicit_seed_post",
                "requested_scope": {
                    "mode": "all", "comment_limit": 20, "repost_limit": 10,
                    "include_replies": True, "download_assets": False,
                },
            }
            with patch("project_runner._collect_one_post", return_value=(
                {"post_id": "AbCdE123", "completion_state": "complete_visible_post"},
                {"state": "partial_limit_sample", "saved_comments": 20},
                {"state": "partial_limit_sample", "saved_reposts": 10},
            )):
                result = execute_browser_source_task(task, **self._browser_task_kwargs(root / "task"))
            self.assertEqual(result["state"], "complete_requested_scope")
            self.assertEqual(result["comment_state"], "partial_limit_sample")
            self.assertEqual(result["repost_state"], "partial_limit_sample")
            manifest = loads((root / "task" / "data" / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["state"], "complete_requested_scope")

    def test_public_task_error_redacts_runtime_paths(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)

            def executor(task: dict, **kwargs: object) -> dict:
                raise RuntimeError(f"failed under {kwargs['task_out']}")

            run_project_tasks(
                project_plan(), profile_dir=root / "profile", out=root / "delivery",
                mode="all", assets=[], resume=False,
                task_executor=executor, session_factory=FakeSessionFactory(),
            )
            rows = [
                loads(line) for line in (root / "delivery" / "data" / "source_tasks.jsonl")
                .read_text(encoding="utf-8").splitlines() if line.strip()
            ]
            self.assertIn("<local-path>", rows[0]["error_message"])
            self.assertNotIn(str(root), rows[0]["error_message"])


if __name__ == "__main__":
    unittest.main()
