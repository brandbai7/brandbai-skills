from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest import mock

import recorder_assistant


class RecorderAssistantTests(unittest.TestCase):
    def test_rename_preserves_protocol_and_private_directory(self) -> None:
        self.assertEqual(recorder_assistant.SERVICE_NAME, "brandbai-live-recorder")
        self.assertEqual(recorder_assistant.CUSTOM_PROTOCOL_URL, "brandbai-recorder://start")
        with mock.patch.dict("os.environ", {"LOCALAPPDATA": "C:/synthetic"}):
            self.assertEqual(recorder_assistant.default_private_root(), Path("C:/synthetic/BrandBAI/LiveRecorder"))

    def test_owned_legacy_shortcut_is_replaced_and_new_one_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as root, mock.patch.dict("os.environ", {"APPDATA": root}):
            programs = Path(root) / "Microsoft/Windows/Start Menu/Programs"
            programs.mkdir(parents=True)
            legacy = programs / recorder_assistant.LEGACY_START_MENU_NAME
            legacy.write_text("[InternetShortcut]\nURL=brandbai-recorder://start\n", encoding="utf-8-sig")
            current = recorder_assistant._write_start_menu_shortcut()
            self.assertEqual(current.name, recorder_assistant.START_MENU_NAME)
            self.assertTrue(recorder_assistant._is_owned_shortcut(current))
            self.assertFalse(legacy.exists())
            self.assertEqual(recorder_assistant._write_start_menu_shortcut(), current)

    def test_rename_preserves_user_modified_shortcut_and_rejects_name_collision(self) -> None:
        with tempfile.TemporaryDirectory() as root, mock.patch.dict("os.environ", {"APPDATA": root}):
            current = recorder_assistant._write_start_menu_shortcut()
            legacy = current.with_name(recorder_assistant.LEGACY_START_MENU_NAME)
            other = "[InternetShortcut]\nURL=https://example.invalid/\n"
            legacy.write_text(other, encoding="utf-8")
            recorder_assistant._write_start_menu_shortcut()
            self.assertEqual(legacy.read_text(encoding="utf-8"), other)
            current.write_text(other, encoding="utf-8")
            with self.assertRaises(OSError):
                recorder_assistant._write_start_menu_shortcut()
            self.assertEqual(current.read_text(encoding="utf-8"), other)

    def test_protocol_can_only_request_service_start(self) -> None:
        self.assertTrue(recorder_assistant._valid_protocol_request(None))
        self.assertTrue(
            recorder_assistant._valid_protocol_request("brandbai-recorder://start")
        )
        self.assertFalse(
            recorder_assistant._valid_protocol_request(
                "brandbai-recorder://start?room=https://live.douyin.com/123"
            )
        )

    def test_protocol_command_uses_only_the_branded_launcher(self) -> None:
        launcher = Path("C:/BrandBAI/BrandBAI直播采集助手.exe")
        command = recorder_assistant._protocol_command(launcher)
        self.assertEqual(command, f'"{launcher}" "%1"')
        self.assertNotIn("python", command.lower())
        self.assertNotIn(".py", command.lower())
        self.assertNotIn("live.douyin.com", command.lower())

    def test_branded_launcher_source_keeps_protocol_scope_narrow(self) -> None:
        source = (
            recorder_assistant.application_root()
            / "assets"
            / "windows-assistant"
            / "BrandBAIRecorderLauncher.cs"
        ).read_text(encoding="utf-8")
        self.assertIn('AssemblyProduct("BrandBAI 直播采集助手")', source)
        self.assertIn('AllowedRequest = "brandbai-recorder://start"', source)
        self.assertNotIn("live.douyin.com", source)
        self.assertNotIn("room_url", source)

    def test_service_command_keeps_state_and_output_separate(self) -> None:
        root = Path("C:/brandbai-live-recorder-test")
        with mock.patch.object(Path, "is_file", return_value=True):
            command = recorder_assistant.build_service_command(
                app_root=root,
                state_dir=root / "private-state",
                output_root=root / "recordings",
            )
        self.assertIn("serve", command)
        self.assertIn("--state-dir", command)
        self.assertIn("--output-root", command)
        self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
        self.assertEqual(command[command.index("--port") + 1], "8765")

    def test_ready_service_is_reused_without_starting_a_second_process(self) -> None:
        spawn = mock.Mock()
        result = recorder_assistant.start_assistant(
            probe=mock.Mock(return_value={"status": "ready", "service_version": "0.10.2"}),
            spawn=spawn,
        )
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["already_running"])
        spawn.assert_not_called()

    def test_unrelated_loopback_service_blocks_start(self) -> None:
        spawn = mock.Mock()
        probe = mock.Mock(return_value={"status": "occupied"})
        result = recorder_assistant.start_assistant(
            probe=probe,
            spawn=spawn,
        )
        self.assertEqual(result, {"status": "blocked", "reason": "local_ports_unavailable"})
        self.assertEqual(probe.call_count, len(recorder_assistant.SERVICE_PORTS))
        spawn.assert_not_called()

    def test_occupied_primary_port_uses_the_next_available_loopback_port(self) -> None:
        process = mock.Mock(pid=2468)
        process.poll.return_value = None
        probe = mock.Mock(
            side_effect=[
                {"status": "occupied"},
                {"status": "offline"},
                {"status": "occupied"},
                {"status": "offline"},
                {"status": "ready", "service_version": recorder_assistant.ASSISTANT_VERSION},
            ]
        )
        spawn = mock.Mock(return_value=process)
        root = Path("C:/brandbai-live-recorder-test")
        with (
            mock.patch.object(Path, "mkdir"),
            mock.patch.object(Path, "is_file", return_value=True),
        ):
            result = recorder_assistant.start_assistant(
                app_root=root / "app",
                state_dir=root / "state",
                output_root=root / "recordings",
                wait_seconds=2,
                probe=probe,
                spawn=spawn,
            )
        command = spawn.call_args.args[0]
        self.assertEqual(command[command.index("--port") + 1], "18765")
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["service_port"], 18765)

    def test_offline_service_is_started_and_polled_until_ready(self) -> None:
        process = mock.Mock(pid=2468)
        process.poll.return_value = None
        probe = mock.Mock(
            side_effect=[
                {"status": "offline"},
                {"status": "offline"},
                {"status": "ready", "service_version": recorder_assistant.ASSISTANT_VERSION},
            ]
        )
        root = Path("C:/brandbai-live-recorder-test")
        with (
            mock.patch.object(Path, "mkdir"),
            mock.patch.object(Path, "is_file", return_value=True),
        ):
            result = recorder_assistant.start_assistant(
                app_root=root / "app",
                state_dir=root / "state",
                output_root=root / "recordings",
                port=recorder_assistant.DEFAULT_PORT,
                wait_seconds=2,
                probe=probe,
                spawn=mock.Mock(return_value=process),
            )
        self.assertEqual(result["status"], "ready")
        self.assertFalse(result["already_running"])
        self.assertEqual(result["process_id"], 2468)

    def test_customer_messages_do_not_expose_internal_paths_or_ports(self) -> None:
        message = recorder_assistant._customer_message(
            {"status": "failed", "reason": "assistant_start_failed"}
        )
        self.assertNotIn("127.0.0.1", message)
        for port in recorder_assistant.SERVICE_PORTS:
            self.assertNotIn(str(port), message)
        self.assertNotIn(".py", message)
        self.assertIn("重新运行安装程序", message)


if __name__ == "__main__":
    unittest.main()
