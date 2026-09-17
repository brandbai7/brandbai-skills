from __future__ import annotations

import io
import json
import threading
import unittest
from contextlib import redirect_stdout
from unittest import mock

import run_multi_recording as multi


class RuntimeStatus:
    def public_summary(self):
        return {"ready": True, "path_exposed": False}


class MultiRoomRecordingTests(unittest.TestCase):
    def test_requires_distinct_rooms_and_bounds_concurrency(self) -> None:
        one = multi.build_parser().parse_args(["https://live.douyin.com/1"])
        with self.assertRaisesRegex(multi.InputError, "at least two"):
            multi._validated_inputs(one)

        duplicate = multi.build_parser().parse_args(
            ["https://live.douyin.com/1", "https://live.douyin.com/1?from=test"]
        )
        with self.assertRaisesRegex(multi.InputError, "cannot be submitted twice"):
            multi._validated_inputs(duplicate)

        too_many = multi.build_parser().parse_args(
            [
                "https://live.douyin.com/1",
                "https://live.douyin.com/2",
                "--max-concurrent",
                "6",
            ]
        )
        with self.assertRaisesRegex(multi.InputError, "between 1 and 5"):
            multi._validated_inputs(too_many)

    def test_two_rooms_run_concurrently_without_page_enhancement(self) -> None:
        barrier = threading.Barrier(2)

        def fake_record_room(**kwargs):
            barrier.wait(timeout=2)
            return {
                "room_url": kwargs["canonical_room_url"],
                "outcome": "recorded",
                "completion_status": "complete_observed_session",
            }

        output = io.StringIO()
        with (
            mock.patch.object(multi, "ensure_streamget_runtime", return_value=RuntimeStatus()),
            mock.patch.object(multi, "_record_room", side_effect=fake_record_room),
            redirect_stdout(output),
        ):
            exit_code = multi.main(
                [
                    "https://live.douyin.com/1",
                    "https://live.douyin.com/2",
                    "--max-concurrent",
                    "2",
                ]
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["room_count"], 2)
        self.assertEqual(payload["max_concurrent"], 2)
        self.assertFalse(payload["browser_page_enhancement"])
        self.assertFalse(payload["comments_or_product_cards_collected"])
        self.assertEqual(len(payload["results"]), 2)


if __name__ == "__main__":
    unittest.main()
