from __future__ import annotations

import unittest

from live_resilience_test import _navigate, classify_page_health, soak_result_state


class LiveResilienceTests(unittest.TestCase):
    def test_navigation_retries_transient_abort(self) -> None:
        class FakePage:
            def __init__(self) -> None:
                self.calls = 0
                self.waits = []

            def goto(self, _target: str, **_kwargs) -> None:
                self.calls += 1
                if self.calls < 3:
                    raise RuntimeError("synthetic navigation abort")

            def wait_for_timeout(self, milliseconds: int) -> None:
                self.waits.append(milliseconds)

        page = FakePage()
        _navigate(page, "https://weibo.com/100001/AbCdE123")
        self.assertEqual(page.calls, 3)
        self.assertEqual(page.waits, [2_000, 2_000, 3_000])

    def test_page_health_preserves_login_and_visibility_boundaries(self) -> None:
        self.assertEqual(
            classify_page_health(blocker="login", article_visible=True, current_url="https://weibo.com/x"),
            "partial_login_required",
        )
        self.assertEqual(
            classify_page_health(blocker="", article_visible=False, current_url="https://weibo.com/x"),
            "partial_article_unavailable",
        )
        self.assertEqual(
            classify_page_health(blocker="", article_visible=True, current_url="https://weibo.com/x"),
            "complete_visible_page_healthy",
        )

    def test_soak_requires_duration_and_all_healthy_checkpoints(self) -> None:
        healthy = [{"state": "complete_visible_page_healthy"}]
        self.assertEqual(
            soak_result_state(healthy, elapsed_seconds=120.0, requested_seconds=120),
            "complete_soak_duration_healthy",
        )
        self.assertEqual(
            soak_result_state(healthy, elapsed_seconds=119.0, requested_seconds=120),
            "partial_duration_not_reached",
        )
        self.assertEqual(
            soak_result_state([{"state": "partial_login_required"}], elapsed_seconds=120.0,
                              requested_seconds=120),
            "partial_soak_health_anomaly",
        )


if __name__ == "__main__":
    unittest.main()
