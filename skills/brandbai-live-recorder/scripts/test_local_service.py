from __future__ import annotations

import json
import shutil
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest import mock

from local_service import (
    ExtensionSessionManager,
    RecordingSettings,
    ServiceConflictError,
    ServiceOriginError,
    ServiceInputError,
    TaskManager,
    TaskStore,
    create_http_server,
    is_allowed_origin,
    is_extension_origin,
    load_or_create_token,
    validate_create_request,
    validate_visible_event_batch,
)
from recorder_core import RecordingResult, normalize_douyin_room_url
from runtime_support import RuntimeSetupError


EXTENSION_ID = "abcdefghijklmnopabcdefghijklmnop"
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}"
SECOND_EXTENSION_ID = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
SECOND_EXTENSION_ORIGIN = f"chrome-extension://{SECOND_EXTENSION_ID}"


@contextmanager
def scratch_dir():
    path = Path(__file__).resolve().parent / f".service-test-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def payload(**overrides):
    value = {
        "room_url": "https://live.douyin.com/123456",
        "mode": "immediate",
        "quality": "SD",
        "max_runtime_seconds": 1800,
        "split_enabled": True,
        "segment_duration_seconds": 300,
        "retain_original": True,
        "authorized_public_content": True,
    }
    value.update(overrides)
    return value


def visible_batch(observed_ms, **event_overrides):
    event = {
        "sequence": 1,
        "event_type": "comment_visible",
        "observed_at_epoch_ms": observed_ms,
        "room_url": "https://live.douyin.com/123456",
        "payload": {
            "masked_user": "示***",
            "text": "还能补测试库存吗",
            "observation_kind": "new_visible",
        },
    }
    event.update(event_overrides)
    return {"collector_session_id": "collector-test-01", "events": [event]}


class ServiceContractTests(unittest.TestCase):
    def test_only_extension_or_originless_requests_are_allowed(self) -> None:
        self.assertTrue(is_allowed_origin(None))
        self.assertTrue(is_allowed_origin(EXTENSION_ORIGIN))
        self.assertFalse(is_allowed_origin("https://example.com"))
        self.assertFalse(is_allowed_origin("chrome-extension://id/path"))
        self.assertTrue(is_extension_origin(EXTENSION_ORIGIN))
        self.assertFalse(is_extension_origin(None))

    def test_request_contract_rejects_monitor_and_short_regular_segments(self) -> None:
        with self.assertRaises(ServiceInputError):
            validate_create_request(payload(mode="monitor"))
        with self.assertRaises(ServiceInputError):
            validate_create_request(payload(segment_duration_seconds=30))
        accepted = validate_create_request(
            payload(segment_duration_seconds=30, test_mode=True)
        )
        self.assertEqual(accepted["segment_duration_seconds"], 30)
        self.assertTrue(accepted["test_mode"])

    def test_total_recording_and_segmentation_are_separate(self) -> None:
        single = validate_create_request(
            payload(max_runtime_seconds=1800, split_enabled=False)
        )
        self.assertEqual(single["max_runtime_seconds"], 1800)
        self.assertFalse(single["split_enabled"])
        split = validate_create_request(
            payload(max_runtime_seconds=1800, split_enabled=True, segment_duration_seconds=600)
        )
        self.assertEqual(split["segment_duration_seconds"], 600)
        with self.assertRaisesRegex(ServiceInputError, "must not exceed"):
            validate_create_request(
                payload(max_runtime_seconds=300, split_enabled=True, segment_duration_seconds=600)
            )
        with self.assertRaisesRegex(ServiceInputError, "must enable segmentation"):
            validate_create_request(
                payload(max_runtime_seconds=21601, split_enabled=False)
            )

    def test_collector_options_are_explicit_booleans_on_the_task(self) -> None:
        accepted = validate_create_request(
            payload(
                collect_comments=True,
                collect_product_cards=False,
                collect_room_metrics=True,
            )
        )
        self.assertTrue(accepted["collect_comments"])
        self.assertFalse(accepted["collect_product_cards"])
        self.assertTrue(accepted["collect_room_metrics"])
        defaults = validate_create_request(payload())
        self.assertFalse(defaults["collect_comments"])
        self.assertFalse(defaults["collect_product_cards"])
        self.assertFalse(defaults["collect_room_metrics"])
        with self.assertRaisesRegex(ServiceInputError, "must be a boolean"):
            validate_create_request(payload(collect_comments="yes"))

    def test_token_is_stable_and_not_stored_in_database(self) -> None:
        with scratch_dir() as root:
            token1, created1 = load_or_create_token(root / "private-state")
            token2, created2 = load_or_create_token(root / "private-state")
            self.assertTrue(created1)
            self.assertFalse(created2)
            self.assertEqual(token1, token2)
            database = root / "private-state" / "service_state.sqlite3"
            TaskStore(database)
            self.assertNotIn(token1.encode("utf-8"), database.read_bytes())

    def test_public_task_separates_current_run_events_from_room_history(self) -> None:
        started = threading.Event()

        def fake_recorder(config, *, stop_event):
            config.output_root.mkdir(parents=True, exist_ok=True)
            started.set()
            stop_event.wait(timeout=3)
            return RecordingResult(
                task_id="ignored",
                session_id="synthetic-session",
                outcome="recorded",
                completion_status="partial_service_stop",
                valid_mp4_count=1,
                segment_count=1,
                actual_media_duration_seconds=3.0,
                output_root=str(config.output_root),
                test_only=config.test_mode,
            )

        with scratch_dir() as root:
            store = TaskStore(root / "state" / "service.sqlite3")
            manager = TaskManager(
                store=store,
                output_root=root / "deliveries",
                recorder=fake_recorder,
                min_free_space_gb=0,
            )
            task, _reused = manager.create(payload())
            self.assertTrue(started.wait(timeout=2))
            current = manager.get(task["task_id"])
            started_ms = datetime.fromisoformat(current["started_at"]).timestamp() * 1000

            historical_batch = visible_batch(started_ms - 5000)
            historical_batch["collector_session_id"] = "collector-history"
            _session, historical = validate_visible_event_batch(historical_batch, current)
            current_batch = visible_batch(started_ms + 5000)
            current_batch["collector_session_id"] = "collector-current"
            _session, current_events = validate_visible_event_batch(current_batch, current)
            store.add_visible_events(task["task_id"], historical + current_events)

            refreshed = manager.get(task["task_id"])
            self.assertEqual(refreshed["visible_event_count"], 1)
            self.assertEqual(refreshed["visible_event_count_total"], 2)
            self.assertEqual(refreshed['visible_event_counts'],{'comment_visible':1})
            manager.stop(task["task_id"])
            self.assertTrue(manager.wait_for_idle(timeout=3))
            output=Path(manager.get(task['task_id'])['output_dir'])
            report=json.loads((output/'05_直播互动/完整性.json').read_text(encoding='utf-8'))
            self.assertEqual(report['event_count'],1)
            self.assertTrue(manager.get(task['task_id'])['interaction_export_available'])
            late=visible_batch(started_ms+6000,sequence=2)
            late['collector_session_id']='collector-current'
            manager.ingest_visible_events(task['task_id'],late)
            self.assertEqual(json.loads((output/'05_直播互动/完整性.json').read_text(encoding='utf-8'))['event_count'],2)
            self.assertEqual(len((output/'data/visible_page_events.jsonl').read_text(encoding='utf-8').splitlines()),2)
            self.assertTrue(manager.get(task['task_id'])['interaction_export_available'])


class VisibleEventContractTests(unittest.TestCase):
    def task(self):
        return {
            "task_id": "dy-0123456789abcdef",
            "room_url": "https://live.douyin.com/123456",
            "started_at": "2026-08-27T10:00:00+08:00",
            "ended_at": None,
        }

    def test_comment_event_has_first_observation_time_not_model_timing(self) -> None:
        _session, events = validate_visible_event_batch(
            visible_batch(1787796005000), self.task()
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["recording_offset_seconds"], 5.0)
        self.assertEqual(
            events[0]["time_alignment_status"],
            "wall_clock_approximate_uncalibrated",
        )
        self.assertEqual(events[0]["completeness"], "page_visible_first_observation_only")

    def test_rejects_cross_room_urls_and_unsupported_private_fields(self) -> None:
        with self.assertRaisesRegex(ServiceConflictError, "does not match"):
            validate_visible_event_batch(
                visible_batch(1787796005000, room_url="https://live.douyin.com/999999"),
                self.task(),
            )
        bad = visible_batch(1787796005000)
        bad["events"][0]["payload"]["user_id"] = "private-id"
        with self.assertRaisesRegex(ServiceInputError, "unsupported comment fields"):
            validate_visible_event_batch(bad, self.task())

    def test_rejects_urls_control_text_and_duplicate_sequence_in_one_batch(self) -> None:
        bad_url = visible_batch(1787796005000)
        bad_url["events"][0]["payload"]["text"] = "https://example.com/private"
        with self.assertRaisesRegex(ServiceInputError, "must not contain a URL"):
            validate_visible_event_batch(bad_url, self.task())
        duplicated = visible_batch(1787796005000)
        duplicated["events"].append(dict(duplicated["events"][0]))
        with self.assertRaisesRegex(ServiceInputError, "duplicated inside the batch"):
            validate_visible_event_batch(duplicated, self.task())

    def test_controller_product_card_states_keep_observed_visibility_boundary(self) -> None:
        shown = visible_batch(
            1787796005000,
            event_type="product_state",
            payload={
                "visible": True,
                "product_title": "测试礼盒",
                "display_price": "¥399",
                "change_kind": "visible_product_changed",
            },
        )
        _session, events = validate_visible_event_batch(shown, self.task())
        self.assertTrue(events[0]["payload"]["visible"])
        self.assertEqual(events[0]["payload"]["change_kind"], "visible_product_changed")
        hidden = visible_batch(
            1787796006000,
            event_type="product_state",
            payload={
                "visible": False,
                "product_title": None,
                "display_price": None,
                "change_kind": "temporarily_not_visible",
            },
        )
        _session, events = validate_visible_event_batch(hidden, self.task())
        self.assertFalse(events[0]["payload"]["visible"])
        self.assertIsNone(events[0]["payload"]["product_title"])

    def test_collector_status_records_the_explicit_enabled_scope(self) -> None:
        started = visible_batch(
            1787796005000,
            event_type="collector_status",
            payload={
                "status": "started",
                "reason": None,
                "collect_comments": True,
                "collect_product_cards": False,
                "collect_room_metrics": True,
            },
        )
        _session, events = validate_visible_event_batch(started, self.task())
        self.assertTrue(events[0]["payload"]["collect_comments"])
        self.assertFalse(events[0]["payload"]["collect_product_cards"])
        self.assertTrue(events[0]["payload"]["collect_room_metrics"])

        missing_scope = visible_batch(
            1787796006000,
            event_type="collector_status",
            payload={"status": "started", "reason": None},
        )
        with self.assertRaisesRegex(ServiceInputError, "must be a boolean"):
            validate_visible_event_batch(missing_scope, self.task())

        empty_active_scope = visible_batch(
            1787796007000,
            event_type="collector_status",
            payload={
                "status": "options_changed",
                "reason": None,
                "collect_comments": False,
                "collect_product_cards": False,
                "collect_room_metrics": False,
            },
        )
        with self.assertRaisesRegex(ServiceInputError, "at least one enabled collector"):
            validate_visible_event_batch(empty_active_scope, self.task())

        playback_paused = visible_batch(
            1787796008000,
            event_type="collector_status",
            payload={
                "status": "playback_paused",
                "reason": "platform_energy_saver",
                "collect_comments": True,
                "collect_product_cards": True,
                "collect_room_metrics": True,
            },
        )
        _session, events = validate_visible_event_batch(playback_paused, self.task())
        self.assertEqual(events[0]["payload"]["status"], "playback_paused")
        self.assertEqual(events[0]["payload"]["reason"], "platform_energy_saver")

        playback_resumed = visible_batch(
            1787796009000,
            event_type="collector_status",
            payload={
                "status": "playback_resumed",
                "reason": "platform_energy_saver_cleared",
                "collect_comments": True,
                "collect_product_cards": True,
                "collect_room_metrics": True,
            },
        )
        _session, events = validate_visible_event_batch(playback_resumed, self.task())
        self.assertEqual(events[0]["payload"]["status"], "playback_resumed")

        playback_resume_requested = visible_batch(
            1787796009500,
            event_type="collector_status",
            payload={
                "status": "playback_resume_requested",
                "reason": "platform_energy_saver_attempt_1",
                "collect_comments": True,
                "collect_product_cards": True,
                "collect_room_metrics": True,
            },
        )
        _session, events = validate_visible_event_batch(playback_resume_requested, self.task())
        self.assertEqual(events[0]["payload"]["status"], "playback_resume_requested")

        playback_resume_failed = visible_batch(
            1787796009600,
            event_type="collector_status",
            payload={
                "status": "playback_resume_failed",
                "reason": "platform_energy_saver_continue_no_effect",
                "collect_comments": True,
                "collect_product_cards": True,
                "collect_room_metrics": True,
            },
        )
        _session, events = validate_visible_event_batch(playback_resume_failed, self.task())
        self.assertEqual(events[0]["payload"]["status"], "playback_resume_failed")


class ExtensionSessionTests(unittest.TestCase):
    def test_session_is_origin_bound_expires_and_raw_token_is_not_retained(self) -> None:
        now = [100.0]
        sessions = ExtensionSessionManager(ttl_seconds=10, clock=lambda: now[0])
        origin = EXTENSION_ORIGIN
        token, ttl = sessions.issue(origin, EXTENSION_ID)
        self.assertEqual(ttl, 10)
        self.assertTrue(sessions.validate(token, origin, EXTENSION_ID))
        self.assertTrue(sessions.validate(token, None, EXTENSION_ID))
        self.assertFalse(sessions.validate(token, SECOND_EXTENSION_ORIGIN, SECOND_EXTENSION_ID))
        self.assertFalse(sessions.validate(token, None, SECOND_EXTENSION_ID))
        self.assertNotIn(token, repr(sessions.__dict__))
        now[0] = 111.0
        self.assertFalse(sessions.validate(token, origin, EXTENSION_ID))

    def test_first_extension_origin_binds_service_lifetime(self) -> None:
        sessions = ExtensionSessionManager()
        sessions.issue(EXTENSION_ORIGIN, EXTENSION_ID)
        with self.assertRaises(ServiceOriginError):
            sessions.issue(SECOND_EXTENSION_ORIGIN, SECOND_EXTENSION_ID)
        with self.assertRaises(ServiceOriginError):
            sessions.issue("https://example.com", EXTENSION_ID)


class TaskManagerTests(unittest.TestCase):
    def test_storage_choice_applies_only_to_new_sessions_and_extension_is_single_active(self) -> None:
        started = {"123456": threading.Event(), "789012": threading.Event()}

        def fake_recorder(config, *, stop_event):
            _canonical, room_id = normalize_douyin_room_url(config.room_url)
            config.output_root.mkdir(parents=True, exist_ok=True)
            started[room_id].set()
            stop_event.wait(timeout=3)
            return RecordingResult(
                task_id="ignored",
                session_id=f"session-{room_id}",
                outcome="recorded",
                completion_status="partial_service_stop",
                valid_mp4_count=1,
                segment_count=1,
                actual_media_duration_seconds=3.0,
                output_root=str(config.output_root),
                test_only=False,
            )

        with scratch_dir() as root:
            first_root = root / "recordings-a"
            second_root = root / "recordings-b"
            settings = RecordingSettings(
                root / "state" / "recording_settings.json",
                default_output_root=first_root,
                disallowed_roots=(root / "state",),
                directory_selector=lambda _initial: second_root,
            )
            self.assertFalse(settings.public()["configured"])
            settings.confirm_default()
            manager = TaskManager(
                store=TaskStore(root / "state" / "service.sqlite3"),
                output_root=first_root,
                recording_settings=settings,
                recorder=fake_recorder,
                min_free_space_gb=0,
            )
            first, _reused = manager.create(payload())
            self.assertTrue(started["123456"].wait(timeout=2))
            with self.assertRaises(ServiceConflictError):
                manager.create(
                    payload(room_url="https://live.douyin.com/789012"),
                    single_active_task=True,
                )

            chosen, canceled = settings.choose()
            self.assertFalse(canceled)
            self.assertEqual(Path(chosen["output_root"]), second_root.resolve())
            second, _reused = manager.create(
                payload(room_url="https://live.douyin.com/789012")
            )
            self.assertTrue(started["789012"].wait(timeout=2))
            first_current = manager.get(first["task_id"])
            second_current = manager.get(second["task_id"])
            self.assertTrue(Path(first_current["output_dir"]).is_relative_to(first_root.resolve()))
            self.assertTrue(Path(second_current["output_dir"]).is_relative_to(second_root.resolve()))
            manager.stop(first["task_id"])
            manager.stop(second["task_id"])
            self.assertTrue(manager.wait_for_idle(timeout=3))

    def test_runtime_is_prepared_after_task_creation_and_before_real_recording(self) -> None:
        order = []

        def prepare_runtime():
            order.append("runtime")

        def fake_recorder(config, *, stop_event):
            order.append("recorder")
            config.output_root.mkdir(parents=True, exist_ok=True)
            return RecordingResult(
                task_id="ignored",
                session_id="synthetic-session",
                outcome="recorded",
                completion_status="partial_time_limit",
                valid_mp4_count=1,
                segment_count=1,
                actual_media_duration_seconds=60.0,
                output_root=str(config.output_root),
                test_only=False,
            )

        with scratch_dir() as root:
            manager = TaskManager(
                store=TaskStore(root / "state" / "service.sqlite3"),
                output_root=root / "deliveries",
                recorder=fake_recorder,
                runtime_preparer=prepare_runtime,
                min_free_space_gb=0,
            )
            task, reused = manager.create(payload())
            self.assertFalse(reused)
            self.assertTrue(manager.wait_for_idle(timeout=3))
            current = manager.get(task["task_id"])
            self.assertEqual(current["completion_status"], "partial_time_limit")
        self.assertEqual(order, ["runtime", "recorder"])

    def test_runtime_setup_failure_is_preserved_as_task_failure(self) -> None:
        def prepare_runtime():
            raise RuntimeSetupError("runtime setup unavailable")

        recorder = mock.Mock()
        with scratch_dir() as root:
            manager = TaskManager(
                store=TaskStore(root / "state" / "service.sqlite3"),
                output_root=root / "deliveries",
                recorder=recorder,
                runtime_preparer=prepare_runtime,
                min_free_space_gb=0,
            )
            task, _reused = manager.create(payload())
            self.assertTrue(manager.wait_for_idle(timeout=3))
            current = manager.get(task["task_id"])
            self.assertEqual(current["state"], "failed")
            self.assertEqual(current["completion_status"], "failed_service_worker")
            self.assertIn("runtime_dependency_unavailable", current["last_error"])
        recorder.assert_not_called()

    def test_duplicate_active_task_reuses_id_and_stop_is_idempotent(self) -> None:
        started = threading.Event()
        stop_kinds = []

        def fake_recorder(config, *, stop_event):
            config.output_root.mkdir(parents=True, exist_ok=True)
            self.assertEqual(config.max_runtime_seconds, 1800)
            self.assertTrue(config.split_enabled)
            started.set()
            stop_event.wait(timeout=3)
            stop_kinds.append(getattr(stop_event, 'recording_stop_kind', None))
            return RecordingResult(
                task_id="ignored",
                session_id="synthetic-session",
                outcome="recorded",
                completion_status="partial_service_stop",
                valid_mp4_count=1,
                segment_count=1,
                actual_media_duration_seconds=3.0,
                output_root=str(config.output_root),
                test_only=config.test_mode,
            )

        with scratch_dir() as root:
            manager = TaskManager(
                store=TaskStore(root / "state" / "service.sqlite3"),
                output_root=root / "deliveries",
                recorder=fake_recorder,
                min_free_space_gb=0,
            )
            first, reused1 = manager.create(payload())
            self.assertTrue(started.wait(timeout=2))
            second, reused2 = manager.create(payload())
            self.assertFalse(reused1)
            self.assertTrue(reused2)
            self.assertEqual(first["task_id"], second["task_id"])
            stopping, already_stopped1 = manager.stop(first["task_id"])
            self.assertFalse(already_stopped1)
            self.assertIn(stopping["state"], {"stopping", "partial"})

            deadline = time.monotonic() + 3
            current = manager.get(first["task_id"])
            while time.monotonic() < deadline:
                current = manager.get(first["task_id"])
                if current["state"] == "partial":
                    break
                time.sleep(0.02)
            self.assertEqual(current["completion_status"], "partial_service_stop")
            self.assertEqual(stop_kinds, ['manual'])
            self.assertEqual(
                Path(current["output_dir"]).parent,
                (root / "deliveries" / "直播录制").resolve(),
            )
            self.assertIn('_R123456_直播录制_',Path(current['output_dir']).name)
            final, already_stopped2 = manager.stop(first["task_id"])
            self.assertTrue(already_stopped2)
            self.assertEqual(final["state"], "partial")

    def test_visible_event_ingest_is_idempotent_and_exports_public_jsonl(self) -> None:
        started = threading.Event()

        def fake_recorder(config, *, stop_event):
            config.output_root.mkdir(parents=True, exist_ok=True)
            started.set()
            stop_event.wait(timeout=3)
            return RecordingResult(
                task_id="ignored",
                session_id="synthetic-session",
                outcome="recorded",
                completion_status="partial_service_stop",
                valid_mp4_count=1,
                segment_count=1,
                actual_media_duration_seconds=3.0,
                output_root=str(config.output_root),
                test_only=config.test_mode,
            )

        with scratch_dir() as root:
            manager = TaskManager(
                store=TaskStore(root / "state" / "service.sqlite3"),
                output_root=root / "deliveries",
                recorder=fake_recorder,
                min_free_space_gb=0,
            )
            task, _reused = manager.create(payload())
            self.assertTrue(started.wait(timeout=2))
            current = manager.get(task["task_id"])
            observed_ms = datetime.fromisoformat(current["started_at"]).timestamp() * 1000 + 5000
            batch = visible_batch(observed_ms)
            first = manager.ingest_visible_events(task["task_id"], batch)
            second = manager.ingest_visible_events(task["task_id"], batch)
            self.assertEqual(first["accepted"], 1)
            self.assertEqual(second["accepted"], 0)
            self.assertEqual(second["duplicates"], 1)
            self.assertEqual(manager.get(task["task_id"])["visible_event_count"], 1)
            self.assertEqual(manager.get(task["task_id"])["visible_event_count_total"], 1)
            event_path = Path(manager.get(task["task_id"])["output_dir"]) / "data" / "visible_page_events.jsonl"
            rows = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["payload"]["masked_user"], "示***")
            self.assertNotIn("user_id", event_path.read_text(encoding="utf-8"))
            manager.stop(task["task_id"])
            self.assertTrue(manager.wait_for_idle(timeout=3))


class HttpApiTests(unittest.TestCase):
    def test_service_and_assistant_match_core_version(self):
        from local_service import SERVICE_VERSION
        from recorder_core import TOOL_VERSION
        from recorder_assistant import ASSISTANT_VERSION
        self.assertEqual(SERVICE_VERSION, TOOL_VERSION)
        self.assertEqual(ASSISTANT_VERSION, TOOL_VERSION)

    def test_storage_settings_require_authenticated_user_action(self) -> None:
        def fake_recorder(config, *, stop_event):
            return RecordingResult(
                task_id="ignored",
                session_id=None,
                outcome="not_live",
                completion_status=None,
                valid_mp4_count=0,
                segment_count=0,
                actual_media_duration_seconds=0,
                output_root=str(config.output_root),
                test_only=False,
            )

        with scratch_dir() as root:
            settings = RecordingSettings(
                root / "state" / "recording_settings.json",
                default_output_root=root / "recordings",
                disallowed_roots=(root / "state",),
            )
            manager = TaskManager(
                store=TaskStore(root / "state" / "service.sqlite3"),
                output_root=root / "recordings",
                recording_settings=settings,
                recorder=fake_recorder,
                min_free_space_gb=0,
            )
            token = "unit-test-token-with-at-least-32-characters"
            server = create_http_server(host="127.0.0.1", port=0, manager=manager, token=token)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                get_request = urllib.request.Request(
                    f"{base}/v1/settings",
                    headers={"X-BrandBAI-Token": token},
                )
                with urllib.request.urlopen(get_request, timeout=2) as response:
                    current = json.load(response)
                self.assertFalse(current["storage"]["configured"])

                unconfirmed_start = urllib.request.Request(
                    f"{base}/v1/tasks",
                    data=json.dumps(payload()).encode("utf-8"),
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "X-BrandBAI-Token": token,
                        "Origin": EXTENSION_ORIGIN,
                    },
                )
                with self.assertRaises(urllib.error.HTTPError) as blocked_start:
                    urllib.request.urlopen(unconfirmed_start, timeout=2)
                self.assertEqual(blocked_start.exception.code, 409)
                blocked_start.exception.close()

                missing_action_header = urllib.request.Request(
                    f"{base}/v1/settings/output-root",
                    data=json.dumps({"action": "use_default"}).encode("utf-8"),
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "X-BrandBAI-Token": token,
                    },
                )
                with self.assertRaises(urllib.error.HTTPError) as rejected:
                    urllib.request.urlopen(missing_action_header, timeout=2)
                self.assertEqual(rejected.exception.code, 400)
                rejected.exception.close()

                confirm = urllib.request.Request(
                    f"{base}/v1/settings/output-root",
                    data=json.dumps({"action": "use_default"}).encode("utf-8"),
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "X-BrandBAI-Token": token,
                        "X-BrandBAI-Settings": "user-click",
                    },
                )
                with urllib.request.urlopen(confirm, timeout=2) as response:
                    confirmed = json.load(response)
                self.assertTrue(confirmed["storage"]["configured"])
                self.assertTrue(confirmed["storage"]["using_default"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_authenticated_visible_event_endpoint_deduplicates(self) -> None:
        started = threading.Event()

        def fake_recorder(config, *, stop_event):
            config.output_root.mkdir(parents=True, exist_ok=True)
            started.set()
            stop_event.wait(timeout=3)
            return RecordingResult(
                task_id="ignored",
                session_id="synthetic-session",
                outcome="recorded",
                completion_status="partial_service_stop",
                valid_mp4_count=1,
                segment_count=1,
                actual_media_duration_seconds=3.0,
                output_root=str(config.output_root),
                test_only=config.test_mode,
            )

        with scratch_dir() as root:
            manager = TaskManager(
                store=TaskStore(root / "state.sqlite3"),
                output_root=root / "deliveries",
                recorder=fake_recorder,
                min_free_space_gb=0,
            )
            token = "unit-test-token-with-at-least-32-characters"
            server = create_http_server(host="127.0.0.1", port=0, manager=manager, token=token)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            headers = {"Content-Type": "application/json", "X-BrandBAI-Token": token}
            try:
                create_request = urllib.request.Request(
                    f"{base}/v1/tasks",
                    data=json.dumps(payload()).encode("utf-8"),
                    method="POST",
                    headers=headers,
                )
                with urllib.request.urlopen(create_request, timeout=2) as response:
                    created = json.load(response)
                self.assertTrue(started.wait(timeout=2))
                task = manager.get(created["task"]["task_id"])
                collector_request = urllib.request.Request(
                    f"{base}/v1/tasks/{task['task_id']}/collector-options",
                    data=json.dumps({
                        "collect_comments": True,
                        "collect_product_cards": False,
                        "collect_room_metrics": True,
                    }).encode("utf-8"),
                    method="POST",
                    headers=headers,
                )
                with urllib.request.urlopen(collector_request, timeout=2) as response:
                    updated = json.load(response)["task"]
                self.assertTrue(updated["collect_comments"])
                self.assertFalse(updated["collect_product_cards"])
                self.assertTrue(updated["collect_room_metrics"])
                observed_ms = datetime.fromisoformat(task["started_at"]).timestamp() * 1000 + 5000
                batch_data = json.dumps(visible_batch(observed_ms)).encode("utf-8")
                endpoint = f"{base}/v1/tasks/{task['task_id']}/visible-events"
                first_request = urllib.request.Request(
                    endpoint, data=batch_data, method="POST", headers=headers
                )
                with urllib.request.urlopen(first_request, timeout=2) as response:
                    self.assertEqual(response.status, 202)
                    first = json.load(response)
                second_request = urllib.request.Request(
                    endpoint, data=batch_data, method="POST", headers=headers
                )
                with urllib.request.urlopen(second_request, timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    second = json.load(response)
                self.assertEqual(first["accepted"], 1)
                self.assertEqual(second["duplicates"], 1)
            finally:
                manager.shutdown(timeout=3)
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_health_auth_create_and_origin_boundaries(self) -> None:
        def fake_recorder(config, *, stop_event):
            return RecordingResult(
                task_id="ignored",
                session_id=None,
                outcome="not_live",
                completion_status=None,
                valid_mp4_count=0,
                segment_count=0,
                actual_media_duration_seconds=0,
                output_root=str(config.output_root),
                test_only=config.test_mode,
            )

        with scratch_dir() as root:
            manager = TaskManager(
                store=TaskStore(root / "state.sqlite3"),
                output_root=root / "deliveries",
                recorder=fake_recorder,
                min_free_space_gb=0,
            )
            token = "unit-test-token-with-at-least-32-characters"
            server = create_http_server(host="127.0.0.1", port=0, manager=manager, token=token)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urllib.request.urlopen(f"{base}/v1/health", timeout=2) as response:
                    health = json.load(response)
                self.assertEqual(health["status"], "ready")
                self.assertTrue(health["one_click_pairing"])
                self.assertTrue(health["automatic_pairing"])
                self.assertEqual(health["extension_session_ttl_seconds"], 900)

                with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                    urllib.request.urlopen(f"{base}/v1/tasks", timeout=2)
                self.assertEqual(unauthorized.exception.code, 401)
                unauthorized.exception.close()

                origin = EXTENSION_ORIGIN
                pair_request = urllib.request.Request(
                    f"{base}/v1/pair",
                    data=b"",
                    method="POST",
                    headers={
                        "Origin": origin,
                        "X-BrandBAI-Pair": "extension-popup",
                        "X-BrandBAI-Client": EXTENSION_ID,
                    },
                )
                with urllib.request.urlopen(pair_request, timeout=2) as response:
                    paired = json.load(response)
                session_token = paired["session_token"]
                self.assertGreaterEqual(len(session_token), 32)
                self.assertFalse(paired["persisted"])
                self.assertTrue(paired["origin_bound"])
                self.assertEqual(paired["pairing_mode"], "extension-popup")

                request = urllib.request.Request(
                    f"{base}/v1/tasks",
                    data=json.dumps(payload()).encode("utf-8"),
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "X-BrandBAI-Token": session_token,
                        "X-BrandBAI-Client": EXTENSION_ID,
                        "Origin": origin,
                    },
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    created = json.load(response)
                self.assertFalse(created["reused"])
                self.assertRegex(created["task"]["task_id"], r"^dy-[0-9a-f]{16}$")
                self.assertTrue(manager.wait_for_idle(timeout=2))

                missing_origin = urllib.request.Request(
                    f"{base}/v1/tasks",
                    headers={
                        "X-BrandBAI-Token": session_token,
                        "X-BrandBAI-Client": EXTENSION_ID,
                    },
                )
                with urllib.request.urlopen(missing_origin, timeout=2) as response:
                    originless_tasks = json.load(response)
                self.assertIn("tasks", originless_tasks)

                second_extension = urllib.request.Request(
                    f"{base}/v1/pair",
                    data=b"",
                    method="POST",
                    headers={
                        "Origin": SECOND_EXTENSION_ORIGIN,
                        "X-BrandBAI-Pair": "extension-popup",
                        "X-BrandBAI-Client": SECOND_EXTENSION_ID,
                    },
                )
                with self.assertRaises(urllib.error.HTTPError) as already_bound:
                    urllib.request.urlopen(second_extension, timeout=2)
                self.assertEqual(already_bound.exception.code, 403)
                already_bound.exception.close()

                blocked = urllib.request.Request(
                    f"{base}/v1/health", headers={"Origin": "https://example.com"}
                )
                with self.assertRaises(urllib.error.HTTPError) as forbidden:
                    urllib.request.urlopen(blocked, timeout=2)
                self.assertEqual(forbidden.exception.code, 403)
                forbidden.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                manager.shutdown(timeout=2)


if __name__ == "__main__":
    unittest.main()
    RecordingSettings,
