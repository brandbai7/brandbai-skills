import csv
import io
import json
import shutil
import unittest
import uuid
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from analysis_common import inspect_input, select_works
from build_analysis_dataset import main as build_main
from validate_analysis_input import main as validate_main


@contextmanager
def workspace_temp():
    root = Path.cwd() / "_analysis_test_artifacts"
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


def synthetic_work(video_id: str, published: datetime, pinned: bool = False) -> dict:
    folder = f"03_作品素材/work_{video_id}"
    return {
        "aweme_id": video_id,
        "type": "视频",
        "author": "合成测试账号",
        "title": f"合成作品 {video_id}",
        "create_time": int(published.timestamp()),
        "publish_time": published.isoformat(timespec="seconds"),
        "digg_count": int(video_id[-2:]),
        "comment_count": 1,
        "collect_count": 2,
        "share_count": 3,
        "is_pinned": pinned,
        "selection_reason": "置顶" if pinned else "最近",
        "source_url": f"https://example.invalid/video/{video_id}",
        "local_folder": folder,
        "download_status": "完成",
    }


def make_package(root: Path, include_comments: bool = True) -> Path:
    works_dir = root / "data" / "作品采集"
    comments_dir = root / "data" / "评论采集"
    media_dir = root / "03_作品素材"
    works_dir.mkdir(parents=True)
    comments_dir.mkdir(parents=True)
    media_dir.mkdir(parents=True)
    base = datetime(2026, 8, 5, tzinfo=timezone.utc)
    works = [
        synthetic_work("8000000000000000001", base - timedelta(days=100), True),
        synthetic_work("8000000000000000002", base - timedelta(days=50), True),
    ]
    works.extend(
        synthetic_work(f"8100000000000000{index:03d}", base - timedelta(days=index), False)
        for index in range(35)
    )
    for work in works:
        folder = root / str(work["local_folder"])
        folder.mkdir(parents=True)
        (folder / "video.mp4").write_bytes(b"synthetic")
    (works_dir / "works.json").write_text(
        json.dumps({"works": works}, ensure_ascii=False), encoding="utf-8"
    )
    (works_dir / "download_manifest.json").write_text(
        json.dumps({"status": "complete"}), encoding="utf-8"
    )
    if include_comments:
        headers = [
            "aweme_id", "comment_id", "text", "reply_level", "reply_count",
            "digg_count", "source_role", "id_source", "create_time",
        ]
        with (comments_dir / "comments.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for work in works:
                writer.writerow({
                    "aweme_id": work["aweme_id"],
                    "comment_id": f"c_{work['aweme_id']}",
                    "text": "合成评论，仅用于测试。",
                    "reply_level": "0",
                    "reply_count": "1",
                    "digg_count": "5",
                    "source_role": "viewer_comment",
                    "id_source": "platform",
                    "create_time": "2026-08-05T00:00:00+00:00",
                })
        (comments_dir / "run_manifest.json").write_text(
            json.dumps({"status": "complete_source_visible", "include_replies": False}),
            encoding="utf-8",
        )
    return root


class AnalysisDatasetTests(unittest.TestCase):
    def test_selects_all_pinned_plus_latest_thirty_non_pinned(self):
        with workspace_temp() as temp:
            package = make_package(temp)
            report = inspect_input(package)
            self.assertEqual(report["status"], "ready")
            self.assertEqual(report["sample_counts"]["pinned"], 2)
            self.assertEqual(report["sample_counts"]["recent_non_pinned"], 30)
            self.assertEqual(report["sample_counts"]["selected_total"], 32)
            self.assertEqual(report["selected_works"][0]["sample_role"], "pinned")
            self.assertEqual(report["selected_works"][2]["sample_role"], "recent_non_pinned")

    def test_duplicate_marked_pinned_is_not_counted_again_as_recent(self):
        base = datetime(2026, 8, 5, tzinfo=timezone.utc)
        duplicate = synthetic_work("8200000000000000001", base, False)
        duplicate_pinned = dict(duplicate, is_pinned=True, selection_reason="置顶")
        other = synthetic_work("8200000000000000002", base - timedelta(days=1), False)
        selected, warnings = select_works([duplicate, duplicate_pinned, other])
        self.assertFalse(warnings)
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0]["sample_role"], "pinned")
        self.assertEqual(selected[1]["sample_role"], "recent_non_pinned")

    def test_missing_comments_is_partial_not_invalid(self):
        with workspace_temp() as temp:
            package = make_package(temp, include_comments=False)
            report = inspect_input(package)
            self.assertEqual(report["status"], "partial")
            self.assertTrue(any("Comments CSV is missing" in item for item in report["warnings"]))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(validate_main(["--input", str(package)]), 3)

    def test_short_download_scope_is_partial_for_default_thirty_work_window(self):
        with workspace_temp() as temp:
            package = make_package(temp)
            manifest_path = package / "data" / "作品采集" / "download_manifest.json"
            manifest_path.write_text(
                json.dumps({
                    "status": "complete",
                    "requested_recent_non_pinned": 5,
                    "visible_works_observed": 36,
                    "recent_selected": 5,
                }),
                encoding="utf-8",
            )
            report = inspect_input(package)
            self.assertEqual(report["status"], "partial")
            self.assertEqual(report["analysis_window"]["status"], "partial")
            self.assertTrue(any("requested only 5" in item for item in report["warnings"]))

    def test_dry_run_does_not_create_output_and_build_writes_three_files(self):
        with workspace_temp() as root:
            package = make_package(root / "package")
            dry_out = root / "dry-output"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(build_main([
                    "--input", str(package), "--out", str(dry_out), "--dry-run",
                ]), 0)
            self.assertFalse(dry_out.exists())

            output = root / "analysis-output"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(build_main(["--input", str(package), "--out", str(output)]), 0)
            self.assertTrue((output / "data" / "analysis_manifest.json").is_file())
            self.assertTrue((output / "data" / "works_sample.json").is_file())
            self.assertTrue((output / "data" / "comment_inventory.json").is_file())
            payload = json.loads((output / "data" / "works_sample.json").read_text(encoding="utf-8"))
            self.assertEqual(len(payload["works"]), 32)

    def test_rejects_more_than_thirty_recent(self):
        with self.assertRaisesRegex(Exception, "max_recent"):
            select_works([], max_recent=31)


if __name__ == "__main__":
    unittest.main()
