from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EXTENSION = ROOT / "assets" / "chrome-extension"


class ChromeExtensionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
        cls.javascript = (EXTENSION / "popup.js").read_text(encoding="utf-8")
        cls.background = (EXTENSION / "background.js").read_text(encoding="utf-8")
        cls.content = (EXTENSION / "content.js").read_text(encoding="utf-8")
        cls.html = (EXTENSION / "popup.html").read_text(encoding="utf-8")
        cls.css = (EXTENSION / "sidepanel.css").read_text(encoding="utf-8")
        cls.readme = (EXTENSION / "README.md").read_text(encoding="utf-8")

    def test_manifest_is_v3_and_version_matches_skill(self) -> None:
        self.assertEqual(self.manifest["manifest_version"], 3)
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(f'version: "{self.manifest["version"]}"', skill)

    def test_permissions_are_minimal_and_scoped_to_loopback_and_live_room(self) -> None:
        self.assertEqual(
            self.manifest["permissions"],
            ["activeTab", "storage", "sidePanel", "scripting", "downloads", "alarms"],
        )
        self.assertEqual(
            self.manifest["host_permissions"],
            [
                "http://127.0.0.1:8765/*",
                "http://127.0.0.1:18765/*",
                "http://127.0.0.1:28765/*",
                "https://live.douyin.com/*",
            ],
        )
        self.assertEqual(self.manifest["optional_host_permissions"], [
            "https://www.douyin.com/*", "https://douyin.com/*",
        ])
        forbidden = {"cookies", "webRequest", "webRequestBlocking", "tabs", "debugger"}
        self.assertFalse(forbidden.intersection(self.manifest["permissions"]))
        self.assertEqual(self.manifest["background"], {"service_worker": "background.js"})
        self.assertEqual(
            self.manifest["content_scripts"],
            [{
                "matches": ["https://live.douyin.com/*"],
                "js": ["douyin-commerce-dom.js", "product-identity.js", "live-products.js", "page-materials.js", "product-review-collector.js", "review-page.js", "content.js"],
                "run_at": "document_idle",
            }],
        )

    def test_action_opens_a_persistent_side_panel(self) -> None:
        self.assertEqual(self.manifest["minimum_chrome_version"], "114")
        self.assertEqual(self.manifest["side_panel"], {"default_path": "popup.html"})
        self.assertNotIn("default_popup", self.manifest["action"])
        self.assertIn("setPanelBehavior", self.background)
        self.assertIn("openPanelOnActionClick: true", self.background)
        self.assertIn("chrome.tabs.onActivated.addListener", self.javascript)
        self.assertIn("chrome.tabs.onUpdated.addListener", self.javascript)

    def test_automatic_session_uses_chrome_memory_storage_and_media_is_not_processed(self) -> None:
        combined = self.javascript + self.background + self.content + self.html
        self.assertIn("chrome.storage.session", combined)
        self.assertNotIn("chrome.storage.local", combined)
        self.assertNotIn("chrome.storage.sync", combined)
        self.assertNotIn("localStorage", combined)
        self.assertNotIn("sessionStorage", combined)
        self.assertNotRegex(combined, r"MediaRecorder|captureStream|getDisplayMedia")
        self.assertNotIn('type="password"', self.html)
        self.assertNotIn('id="token"', self.html)
        self.assertIn('id="pair"', self.html)
        self.assertIn('let sessionToken = null', self.javascript)
        self.assertIn('api("/v1/pair"', self.javascript)
        self.assertIn('"X-BrandBAI-Pair": "extension-popup"', self.javascript)
        self.assertIn('const EXTENSION_CLIENT_ID = chrome.runtime.id', self.javascript)
        self.assertIn('"X-BrandBAI-Client": EXTENSION_CLIENT_ID', self.javascript)
        self.assertIn("文件保存在本机", self.html)
        self.assertNotIn("Chrome 内存会话", self.html)
        self.assertNotIn('id="authorized"', self.html)
        self.assertNotIn("我确认有权录制", self.html)
        self.assertIn("仅处理当前公开直播间", self.html)

    def test_progress_results_and_output_location_are_visible(self) -> None:
        self.assertIn("剩余", self.javascript)
        self.assertIn("预计", self.javascript)
        self.assertIn("实际 ", self.javascript)
        self.assertIn("output_dir", self.javascript)
        self.assertIn("查看下载", self.javascript)
        self.assertIn("提前结束并保存", self.javascript)
        self.assertIn("AUTO_REFRESH_MS", self.javascript)

    def test_one_minute_preset_and_preflight_summary_prevent_silent_default(self) -> None:
        self.assertIn('<option value="60">1 分钟</option>', self.html)
        self.assertIn('id="config-summary"', self.html)
        self.assertIn("RECORDING_PRESET_SECONDS = new Set([60,", self.javascript)
        self.assertIn("updateConfigurationSummary", self.javascript)
        self.assertIn('elements.start.textContent = activeCurrentRoom', self.javascript)
        self.assertIn('? "开始录制"', self.javascript)

    def test_primary_start_automatically_launches_and_resumes_recording(self) -> None:
        self.assertIn("let pendingRecordingRequest = null", self.javascript)
        self.assertNotIn("!(currentRoomUrl && sessionToken)", self.javascript)
        self.assertIn(': "启动并开始录制"', self.javascript)
        self.assertIn("function recordingRequestFromForm()", self.javascript)
        self.assertIn("pendingRecordingRequest = request", self.javascript)
        self.assertIn("const connected = await connectService({retry: true})", self.javascript)
        self.assertIn("await beginAssistantLaunch()", self.javascript)
        self.assertIn("async function resumePendingRecording()", self.javascript)
        self.assertIn("const request = pendingRecordingRequest", self.javascript)
        self.assertIn("pendingRecordingRequest = null", self.javascript)
        connect_start = self.javascript.index("async function connectService")
        connect_end = self.javascript.index("function recordingSeconds")
        self.assertIn("await resumePendingRecording()", self.javascript[connect_start:connect_end])
        self.assertIn("点击下方“开始录制”会自动启动助手", self.html)
        self.assertIn("取消时不会创建录制任务", self.html)

    def test_local_service_automatically_uses_a_safe_fallback_port(self) -> None:
        for port in (8765, 18765, 28765):
            self.assertIn(f'"http://127.0.0.1:{port}"', self.javascript)
            self.assertIn(f'"http://127.0.0.1:{port}"', self.background)
        self.assertIn("async function discoverService()", self.javascript)
        self.assertIn("async function discoverServiceBase()", self.background)
        self.assertIn("SERVICE_HEALTH_TIMEOUT_MS", self.javascript)
        self.assertIn("SERVICE_HEALTH_TIMEOUT_MS", self.background)
        self.assertIn("serviceBase: activeServiceBase", self.javascript)
        self.assertIn("serviceBase", self.background)

    def test_primary_flow_hides_fixed_mode_and_internal_checks(self) -> None:
        self.assertNotIn('id="mode"', self.html)
        self.assertNotIn('id="advanced-options"', self.html)
        self.assertNotIn('id="retain-original"', self.html)
        self.assertNotIn('id="full-read"', self.html)
        self.assertNotIn('id="sha256"', self.html)
        self.assertIn("retain_original: true", self.javascript)
        self.assertIn("full_read_check: false", self.javascript)
        self.assertIn("sha256: false", self.javascript)
        self.assertIn("position: sticky", self.css)
        self.assertIn("position: fixed", self.css)
        self.assertIn(":focus-visible", self.css)

    def test_customer_surface_uses_business_language_and_hides_internal_details(self) -> None:
        for visible in (
            "助手已连接",
            "拆分成多个视频",
            "同步记录直播信息",
            "录制状态",
            "预计 1 个视频",
        ):
            self.assertIn(visible, self.html + self.javascript)
        for hidden in (
            "BRANDBAI · LIVE RECORDER",
            "高级保存与校验",
            "SHA-256",
            "TS 原始切片",
            "请求头",
            "任务 c",
        ):
            self.assertNotIn(hidden, self.html)
        self.assertNotIn('class="output-path"', self.html)
        self.assertIn("currentActive || anyActive || currentLatest || lastTasks[0]", self.javascript)
        self.assertIn('document.body.classList.toggle("has-active-task"', self.javascript)

    def test_completion_clears_stale_recording_message(self) -> None:
        self.assertIn("const previousActiveTask = lastTasks.find", self.javascript)
        self.assertIn("if (previousActiveTask && !anyActive)", self.javascript)
        self.assertIn('setMessage("")', self.javascript)

    def test_background_room_completion_releases_current_room_with_clear_feedback(self) -> None:
        self.assertIn("无需切回原直播间", self.html)
        self.assertIn("previousActiveWasOtherRoom", self.javascript)
        self.assertIn("上一个直播间的录制已结束并保存，现在可以录制当前直播间", self.javascript)
        self.assertIn("当前直播间现在可以开始录制", self.javascript)

    def test_platform_energy_saver_recovers_inside_the_current_page(self) -> None:
        self.assertIn('id="playback-pause-notice"', self.html)
        self.assertIn("正在恢复直播页面", self.html)
        self.assertIn("录屏仍在后台继续", self.html)
        self.assertIn("不会切换标签页", self.html)
        self.assertIn("ENERGY_SAVER_PAUSE_MARKER", self.content)
        self.assertIn('ENERGY_SAVER_PAUSE_MARKER = "长时间无操作，已暂停播放"', self.content)
        self.assertNotIn("长期无操作，已暂停播放", self.content)
        self.assertIn('CONTINUE_PLAYBACK_LABEL = "继续播放"', self.content)
        self.assertIn('"playback_paused" : "playback_resumed"', self.content)
        self.assertIn('"playback_resume_requested"', self.content)
        self.assertIn('"playback_resume_failed"', self.content)
        self.assertIn("MAX_PLAYBACK_RECOVERY_ATTEMPTS = 2", self.content)
        self.assertIn("let playbackGuardActive = false", self.content)
        self.assertIn("setPlaybackGuardActive(response.active === true)", self.content)
        self.assertIn('message?.type === "brandbai-playback-guard-activate"', self.content)
        self.assertIn("async function activateCurrentTabPlaybackGuard", self.javascript)
        self.assertIn("async function ensureCurrentTabContentScript", self.javascript)
        self.assertIn("function maintainCurrentRoomPage", self.javascript)
        self.assertIn("restoreCollectorOptionsFromActiveTask", self.javascript)
        self.assertIn("CONTENT_SCRIPT_HEALTHCHECK_MS = 10000", self.javascript)
        self.assertIn("chrome.scripting.executeScript", self.javascript)
        self.assertIn('type: "brandbai-content-script-ping"', self.javascript)
        self.assertIn('message?.type === "brandbai-content-script-ping"', self.content)
        self.assertIn("runtimeContextInvalidated = true", self.content)
        self.assertIn("clearInterval(intervalId)", self.content)
        self.assertIn("await activateCurrentTabPlaybackGuard(request.roomUrl)", self.javascript)
        self.assertIn("/collector-options`,", self.javascript)
        self.assertIn("collect_comments: collectorOptions.enabled && collectorOptions.comments", self.javascript)
        self.assertIn("collectorOptionsFor(requestedRoom, task)", self.background)
        submit_start = self.javascript.index("async function submitRecordingRequest")
        task_created = self.javascript.index('await api("/v1/tasks"', submit_start)
        collector_saved = self.javascript.index(
            "await saveCollectorOptions(request.roomUrl, request.collectorOptions)",
            submit_start,
        )
        collector_notified = self.javascript.index(
            "await notifyCurrentTabCollectorOptions(request.roomUrl, request.collectorOptions)",
            submit_start,
        )
        content_ready = self.javascript.index(
            "await ensureCurrentTabContentScript(request.roomUrl)",
            submit_start,
        )
        immediate_guard = self.javascript.index(
            "await activateCurrentTabPlaybackGuard(request.roomUrl)",
            submit_start,
        )
        task_refresh = self.javascript.index("await refreshTasks", submit_start)
        self.assertLess(task_created, collector_saved)
        self.assertLess(collector_saved, content_ready)
        self.assertLess(content_ready, collector_notified)
        self.assertLess(collector_notified, immediate_guard)
        self.assertLess(immediate_guard, task_refresh)
        self.assertIn("if (!playbackGuardActive || !continueControl", self.content)
        self.assertIn("if (!collecting)", self.content)
        self.assertIn("continueControl.click()", self.content)
        self.assertIn("schedulePlaybackStateScan", self.content)
        self.assertIn('type: "brandbai-page-playback-state-query"', self.javascript)
        self.assertIn("refreshPagePlaybackState", self.javascript)
        self.assertNotIn("chrome.tabs.update", self.content)
        self.assertNotIn("chrome.windows.update", self.content)
        self.assertNotIn("dispatchEvent", self.content)
        pause_notice_start = self.javascript.index("function updatePlaybackPauseNotice")
        pause_notice_end = self.javascript.index("async function refreshPagePlaybackState")
        pause_refresh_end = self.javascript.index("function activeTask")
        self.assertNotIn(
            "collectPageData.checked",
            self.javascript[pause_notice_start:pause_refresh_end],
        )
        self.assertIn("录制期间会自动保持当前直播页面播放", self.html)
        self.assertIn("互动记录需主动开启", self.html)
        self.assertIn(".playback-pause-notice", self.css)

    def test_storage_choice_and_single_room_switch_state_are_customer_visible(self) -> None:
        self.assertIn('id="storage-settings"', self.html)
        self.assertIn('id="use-default-location"', self.html)
        self.assertIn('id="choose-location"', self.html)
        self.assertIn('api("/v1/settings"', self.javascript)
        self.assertIn('api("/v1/settings/output-root"', self.javascript)
        self.assertIn('"X-BrandBAI-Settings": "user-click"', self.javascript)
        self.assertIn('id="room-switch-notice"', self.html)
        self.assertIn("另一个直播间正在录制", self.html)
        self.assertIn('document.body.classList.toggle("has-other-active-task"', self.javascript)
        self.assertIn('? "另一个直播间录制中"', self.javascript)
        self.assertIn("currentActive || anyActive", self.javascript)

    def test_browser_default_delivery_has_no_first_location_choice_and_locks_pending_settings(self) -> None:
        self.assertIn('文件存到浏览器的下载文件夹', self.html)
        self.assertIn('id="browser-delivery-list"', self.html)
        self.assertIn('download-panel.js', self.html)
        self.assertIn("storage?.mode !== 'browser-zip'", self.javascript)
        self.assertIn("const configurationLocked =", self.javascript)
        self.assertIn("control.disabled = configurationLocked", self.javascript)
        self.assertIn("const pendingCollectorLocked =", self.javascript)
        self.assertIn("control.disabled = pendingCollectorLocked", self.javascript)
        self.assertIn('id="storage-required-note"', self.html)
        self.assertNotIn("首次使用，请先选择", self.html)
        self.assertIn("elements.chooseLocation.hidden = true", self.javascript)

    def test_transient_live_room_url_title_is_never_shown_to_customers(self) -> None:
        self.assertIn("const technicalTitle =", self.javascript)
        self.assertIn("action_type=", self.javascript)
        self.assertIn('return technicalTitle ? null : title', self.javascript)
        self.assertIn('roomName || "正在识别直播间"', self.javascript)
        self.assertIn("changeInfo.title", self.javascript)

    def test_offline_state_uses_primary_action_without_strong_header_prompt(self) -> None:
        self.assertIn('id="launch-assistant"', self.html)
        self.assertIn('href="brandbai-recorder://start"', self.html)
        self.assertIn('id="connection-panel" class="connection-panel" hidden', self.html)
        self.assertIn("打开 BrandBAI 直播录屏助手", self.html)
        self.assertIn("始终允许", self.html)
        self.assertIn('ASSISTANT_LAUNCH_URL = "brandbai-recorder://start"', self.javascript)
        self.assertIn('elements.badge.textContent = "使用时启动"', self.javascript)
        self.assertIn('showConnection("", {hidden: true})', self.javascript)
        offline_start = self.javascript.index('function showDeferredServiceState()')
        offline_end = self.javascript.index('\n}', offline_start)
        self.assertNotIn('hidden: false', self.javascript[offline_start:offline_end])
        self.assertIn('showConnection(connectionIssue, {retry: true, hidden: false})', self.javascript)
        self.assertIn('elements.launchAssistant.addEventListener("click", launchAssistant)', self.javascript)
        self.assertIn("let currentRoomTabId = null", self.javascript)
        self.assertIn("let currentRoomWindowId = null", self.javascript)
        self.assertIn("currentRoomTabId = Number.isInteger(tab?.id) ? tab.id : null", self.javascript)
        self.assertIn("currentRoomWindowId = Number.isInteger(tab?.windowId) ? tab.windowId : null", self.javascript)
        self.assertIn("const returnTab = await chrome.tabs.get(roomTabId)", self.javascript)
        self.assertIn("returnTab?.windowId !== roomWindowId", self.javascript)
        self.assertIn("await chrome.windows.update(roomWindowId, {focused: true})", self.javascript)
        self.assertIn("await chrome.tabs.update(roomTabId, {active: true})", self.javascript)
        self.assertIn("windowId: roomWindowId", self.javascript)
        self.assertIn("openerTabId: roomTabId", self.javascript)
        self.assertIn("await chrome.tabs.remove(tabId)", self.javascript)
        self.assertIn("await chrome.tabs.update(returnTabId, {active: true})", self.javascript)
        self.assertIn("await chrome.windows.update(returnWindowId, {focused: true})", self.javascript)
        self.assertIn("ASSISTANT_POLL_MS = 400", self.javascript)
        self.assertNotIn("ASSISTANT_VISUAL_RETURN_MS", self.javascript)
        self.assertIn("ASSISTANT_LAUNCH_TIMEOUT_MS = 60000", self.javascript)
        self.assertIn("checkHealth({launching: true, launchWatchId: watchId})", self.javascript)
        self.assertIn("async function checkHealth({launching = false, launchWatchId = null} = {})", self.javascript)
        self.assertIn("return await watchAssistantLaunch(watchId)", self.javascript)
        self.assertIn("打开后会自动返回直播间并开始录制", self.html)
        self.assertIn("if (ready)", self.javascript)
        self.assertIn("await closeAssistantLaunchTab()", self.javascript)
        for internal in ("python", "8765", "127.0.0.1", "auth_token"):
            self.assertNotIn(internal, self.html.lower())

    def test_assistant_timeout_releases_action_without_dismissing_browser_permission(self) -> None:
        start = self.javascript.index("async function watchAssistantLaunch")
        end = self.javascript.index("function beginAssistantLaunch")
        watcher = self.javascript[start:end]
        self.assertIn("if (watchId !== assistantLaunchWatchId)", watcher)
        self.assertNotIn("await closeAssistantLaunchTab()", watcher)
        self.assertIn("showDeferredServiceState()", watcher)
        self.assertIn("const hadPendingRecording = Boolean(pendingRecordingRequest)", watcher)
        self.assertIn("pendingRecordingRequest = null", watcher)
        self.assertIn("录制未开始。启动等待已结束", watcher)
        self.assertIn("await readCurrentTab()", watcher)

    def test_total_recording_and_optional_segmentation_match_contract(self) -> None:
        for seconds in (300, 600, 1800, 3600, 7200):
            self.assertGreaterEqual(self.html.count(f'value="{seconds}"'), 2)
        for boundary in (1, 1440, 60, 86400, 360, 21600):
            self.assertRegex(self.javascript, rf"\b{boundary}\b")
        self.assertIn('id="recording-preset"', self.html)
        self.assertIn('id="split-enabled"', self.html)
        self.assertIn('id="segment-options"', self.html)
        self.assertIn("max_runtime_seconds", self.javascript)
        self.assertIn("split_enabled", self.javascript)
        self.assertNotIn("test_mode", self.javascript)

    def test_visible_comment_and_controller_product_card_collection_is_observational(self) -> None:
        self.assertIn("webcast-chatroom___content-with-emoji-text", self.content)
        self.assertIn('data-e2e="yellowCart-container"', self.content)
        self.assertIn("MutationObserver", self.content)
        self.assertIn("seenCommentSignatures = new WeakMap()", self.content)
        self.assertIn("characterData: true", self.content)
        self.assertIn("scheduleCommentScan", self.content)
        self.assertIn('scanExistingComments("new_visible")', self.content)
        self.assertNotIn("seenCommentElements", self.content)
        for change_kind in (
            "baseline_visible",
            "visible_product_changed",
            "temporarily_not_visible",
            "restored_visible",
        ):
            self.assertIn(change_kind, self.content)
        self.assertIn("maskVisibleNickname", self.content)
        self.assertIn("brandbai-visible-events", self.content)
        self.assertIn("/visible-events", self.background)
        self.assertEqual(self.content.count(".click()"), 1)
        self.assertIn("continueControl.click()", self.content)
        self.assertNotIn("document.cookie", self.content)

    def test_page_collection_is_optional_and_independently_scoped(self) -> None:
        self.assertIn('<input id="collect-page-data" type="checkbox">', self.html)
        for option_id in ("collect-comments", "collect-product-cards", "collect-room-metrics"):
            self.assertRegex(
                self.html,
                rf'<input id="{option_id}" type="checkbox" checked>',
            )
        self.assertIn("COLLECTOR_OPTIONS_KEY", self.javascript)
        self.assertIn("collectorOptionsFromForm", self.javascript)
        self.assertIn("saveCollectorOptions", self.javascript)
        self.assertIn("persistCollectorOptionsFromForm", self.javascript)
        self.assertIn("notifyCurrentTabCollectorOptions", self.javascript)
        for element in (
            "collectPageData",
            "collectComments",
            "collectProductCards",
            "collectRoomMetrics",
        ):
            self.assertIn(
                f'elements.{element}.addEventListener("change", handleCollectorOptionChange)',
                self.javascript,
            )
        self.assertIn('type: "brandbai-collector-options-updated"', self.javascript)
        self.assertIn('message?.type !== "brandbai-collector-options-updated"', self.content)
        self.assertIn("updateCollectorOptions(message.collectorOptions)", self.content)
        self.assertIn("collectorOptionsFor", self.background)
        self.assertIn("enabled: false", self.content)
        self.assertIn("!collectorOptions.comments", self.content)
        self.assertIn("!collectorOptions.productCards", self.content)
        self.assertIn("!collectorOptions.roomMetrics", self.content)
        for field in (
            "collect_comments",
            "collect_product_cards",
            "collect_room_metrics",
        ):
            self.assertIn(field, self.content)
        combined = self.javascript + self.background + self.content + self.html
        self.assertNotIn("Doubao", combined)
        self.assertNotIn("compile_live_interaction", combined)

    def test_tab_close_has_a_background_collector_status_fallback(self) -> None:
        self.assertIn("ACTIVE_COLLECTORS_KEY", self.background)
        self.assertIn("rememberActiveCollector", self.background)
        self.assertIn("takeActiveCollector", self.background)
        self.assertIn("recordClosedTab", self.background)
        self.assertIn("BACKGROUND_CLOSE_SEQUENCE", self.background)
        self.assertIn("TAB_CLOSE_FALLBACK_DELAY_MS", self.background)
        self.assertIn("await waitForCloseFallback()", self.background)
        self.assertIn("chrome.tabs.onRemoved.addListener", self.background)
        self.assertIn('reason: "page_closed_or_navigated"', self.background)
        self.assertIn("chrome.storage.session", self.background)

    def test_no_remote_code_or_bypass_permissions(self) -> None:
        self.assertNotRegex(self.html, r"https?://")
        combined_js = self.javascript + self.background + self.content
        self.assertNotRegex(combined_js, r"\beval\s*\(|new Function")
        self.assertNotIn("webRequest", combined_js)
        self.assertNotIn("cookies", combined_js)
        self.assertIn("循环监控", self.readme)
        self.assertIn("自动重连", self.readme)


if __name__ == "__main__":
    unittest.main()
