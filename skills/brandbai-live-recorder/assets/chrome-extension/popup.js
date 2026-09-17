"use strict";

const SERVICE_BASES = Object.freeze([
  "http://127.0.0.1:8765",
  "http://127.0.0.1:18765",
  "http://127.0.0.1:28765"
]);
const SERVICE_HEALTH_TIMEOUT_MS = 900;
const SERVICE_REQUEST_TIMEOUT_MS = 6000;
const CONNECTION_RETRY_MS = 30000;
const ASSISTANT_LAUNCH_URL = "brandbai-recorder://start";
const EXTENSION_CLIENT_ID = chrome.runtime.id;
const SESSION_KEY = "brandbaiLiveRecorderSession";
const COLLECTOR_OPTIONS_KEY = "brandbaiLiveRecorderCollectorOptions";
const ACTIVE_STATES = new Set(["queued", "checking", "recording", "stopping"]);
const RECORDING_PRESET_SECONDS = new Set([60, 300, 600, 1800, 3600, 7200]);
const SEGMENT_PRESET_SECONDS = new Set([300, 600, 1800, 3600, 7200]);
const AUTO_REFRESH_MS = 3000;
const ASSISTANT_POLL_MS = 400;
const ASSISTANT_LAUNCH_TIMEOUT_MS = 60000;
const CONTENT_SCRIPT_HEALTHCHECK_MS = 10000;
const ROOM_TAB_TIMEOUT_MS = 3000;
const DOUYIN_OPTIONAL_ORIGINS = Object.freeze(["https://www.douyin.com/*", "https://douyin.com/*"]);
let roomReadGeneration = 0;
let roomAccessRequestInFlight = false;
let productSnapshots = false;
let productCatalog = false;

const STATE_LABELS = {
  queued: "准备中",
  checking: "检查直播状态",
  recording: "录制中",
  stopping: "正在保存",
  complete: "录制完成",
  partial: "已保存",
  not_live: "当前未开播",
  failed: "录制失败",
  stopped: "已保存"
};

const COMPLETION_LABELS = {
  complete_observed_session: "直播结束，录制已保存",
  partial_disconnect: "录制中断，已保存可用部分",
  partial_conversion: "部分视频生成失败，已保留可用文件",
  partial_manual_stop: "已提前结束并保存",
  partial_service_stop: "已提前结束并保存",
  partial_time_limit: "已按设置完成",
  partial_service_restart: "录制意外中断，已保留可用部分",
  failed_no_media: "未生成可用视频",
  failed_service_worker: "录制未完成"
};

const elements = {
  badge: document.querySelector("#service-badge"),
  roomName: document.querySelector("#room-name"),
  roomState: document.querySelector("#room-state"),
  roomStateLabel: document.querySelector("#room-state-label"),
  pageStatus: document.querySelector("#page-status"),
  roomAccessNotice: document.querySelector("#room-access-notice"),
  roomAccessTitle: document.querySelector("#room-access-title"),
  roomAccessMessage: document.querySelector("#room-access-message"),
  roomAccessScope: document.querySelector("#room-access-scope"),
  allowRoomAccess: document.querySelector("#allow-room-access"),
  retryRoomAccess: document.querySelector("#retry-room-access"),
  connectionPanel: document.querySelector("#connection-panel"),
  launchAssistant: document.querySelector("#launch-assistant"),
  installHint: document.querySelector("#install-hint"),
  pair: document.querySelector("#pair"),
  connectionStatus: document.querySelector("#connection-status"),
  quality: document.querySelector("#quality"),
  recordingPreset: document.querySelector("#recording-preset"),
  customRecordingDuration: document.querySelector("#custom-recording-duration"),
  recordingValue: document.querySelector("#recording-value"),
  recordingUnit: document.querySelector("#recording-unit"),
  splitEnabled: document.querySelector("#split-enabled"),
  segmentOptions: document.querySelector("#segment-options"),
  segmentPreset: document.querySelector("#segment-preset"),
  customSegmentDuration: document.querySelector("#custom-segment-duration"),
  segmentValue: document.querySelector("#segment-value"),
  segmentUnit: document.querySelector("#segment-unit"),
  collectPageData: document.querySelector("#collect-page-data"),
  collectorOptions: document.querySelector("#collector-options"),
  collectComments: document.querySelector("#collect-comments"),
  collectProductCards: document.querySelector("#collect-product-cards"),
  collectRoomMetrics: document.querySelector("#collect-room-metrics"),
  playbackPauseNotice: document.querySelector("#playback-pause-notice"),
  roomSwitchNotice: document.querySelector("#room-switch-notice"),
  storageSettings: document.querySelector("#storage-settings"),
  storageTitle: document.querySelector("#storage-title"),
  storageRequiredNote: document.querySelector("#storage-required-note"),
  storageSummary: document.querySelector("#storage-summary"),
  storageHelp: document.querySelector("#storage-help"),
  useDefaultLocation: document.querySelector("#use-default-location"),
  chooseLocation: document.querySelector("#choose-location"),
  configSummary: document.querySelector("#config-summary"),
  start: document.querySelector("#start"),
  stopRecording: document.querySelector("#stop-recording"),
  message: document.querySelector("#message"),
  taskList: document.querySelector("#task-list")
};

let currentRoomUrl = null;
let currentRoomTabId = null;
let currentRoomWindowId = null;
let sessionToken = null;
let sessionExpiresAt = null;
let activeServiceBase = null;
let lastTasks = [];
let pairing = false;
let connectionPromise = null;
let connectionIssue = "";
let connectionRetryAt = 0;
let startInFlight = false;
let pendingRecordingRequest = null;
let refreshInFlight = false;
let refreshTasksPromise = null;
let tabRefreshTimer = null;
let collectorOptionSaveChain = Promise.resolve();
const stopRequests = new Set();
let pagePlaybackPaused = false;
let assistantLaunchTabId = null;
let assistantReturnTabId = null;
let assistantReturnWindowId = null;
let assistantLaunchWatchId = 0;
let assistantLaunchPromise = null;
let storageSettings = null;
let storageBusy = false;
let contentRecoveryInFlight = null;
let contentRecoveryRoomUrl = null;
let contentRecoveryLastAttemptAt = 0;

function setMessage(message, isError = false) {
  elements.message.textContent = message || "";
  elements.message.style.color = isError ? "var(--danger)" : "var(--success)";
}

function showConnection(message, {retry = false, launch = false, hidden = true} = {}) {
  elements.connectionPanel.hidden = hidden;
  elements.connectionStatus.textContent = message;
  elements.launchAssistant.hidden = !launch;
  elements.launchAssistant.href = ASSISTANT_LAUNCH_URL;
  elements.installHint.hidden = !launch;
  elements.pair.hidden = !retry;
  elements.pair.disabled = !retry;
  elements.pair.textContent = "重新检测";
}

function showDeferredServiceState() {
  elements.badge.textContent = "使用时启动";
  elements.badge.className = "badge pending";
  showConnection("", {hidden: true});
}

function getConnectionIssue() {
  return connectionIssue;
}

function showConnectionIssue() {
  elements.badge.textContent = "连接待恢复";
  elements.badge.className = "badge error";
  showConnection(connectionIssue, {retry: true, hidden: false});
}

function failConnection(error) {
  const refused = error?.status === 401 || error?.status === 403;
  connectionIssue = refused
    ? "助手已运行，但未允许当前插件连接。请先结束录制和下载，再重启助手并点击“重新检测”。"
    : "助手已运行，但连接尚未完成。请点击“重新检测”；仍失败时，请在录制和下载结束后重启助手。";
  connectionRetryAt = Date.now() + CONNECTION_RETRY_MS;
  // A failed action must not be submitted later by a background reconnect.
  pendingRecordingRequest = null;
  showConnectionIssue();
  setMessage(connectionIssue, true);
  updateStartAvailability();
}

async function closeAssistantLaunchTab() {
  const tabId = assistantLaunchTabId;
  const returnTabId = assistantReturnTabId;
  const returnWindowId = assistantReturnWindowId;
  assistantLaunchTabId = null;
  assistantReturnTabId = null;
  assistantReturnWindowId = null;
  if (Number.isInteger(tabId)) {
    try {
      const tab = await chrome.tabs.get(tabId);
      // Never close a user page that replaced our temporary protocol page.
      if ([ASSISTANT_LAUNCH_URL, "about:blank", ""].includes(tab?.pendingUrl || tab?.url || "")) {
        await chrome.tabs.remove(tabId);
      }
    } catch (_error) {
      // The user may already have closed the temporary launch page.
    }
  }
  if (Number.isInteger(returnTabId)) {
    try {
      await chrome.tabs.update(returnTabId, {active: true});
    } catch (_error) {
      // The original live-room tab may already have been closed.
    }
  }
  if (Number.isInteger(returnWindowId)) {
    try {
      await chrome.windows.update(returnWindowId, {focused: true});
    } catch (_error) {
      // The original Chrome window may already have been closed.
    }
  }
}

async function watchAssistantLaunch(watchId) {
  const deadline = Date.now() + ASSISTANT_LAUNCH_TIMEOUT_MS;
  while (watchId === assistantLaunchWatchId && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, ASSISTANT_POLL_MS));
    if (watchId !== assistantLaunchWatchId) return false;
    if (await checkHealth({launching: true, launchWatchId: watchId})) {
      if (watchId !== assistantLaunchWatchId) return false;
      if (await connectService()) return true;
    }
    if (getConnectionIssue()) return false;
  }
  if (watchId !== assistantLaunchWatchId) {
    return false;
  }
  const hadPendingRecording = Boolean(pendingRecordingRequest);
  pendingRecordingRequest = null;
  // A timeout does not mean the user dismissed Chrome's native confirmation.
  // Release the pending action, but leave its tab/prompt alone until explicit
  // cancellation, retry, or verified service readiness.
  showDeferredServiceState();
  setMessage(
    hadPendingRecording
      ? "录制未开始。启动等待已结束，请处理浏览器确认后重试。"
      : "启动等待已结束。请处理浏览器确认后重试。",
    true
  );
  try {
    await readCurrentTab();
  } catch (_error) {
    // Returning to the known room is best-effort if the room was closed meanwhile.
  }
  updateStartAvailability();
  return false;
}

function beginAssistantLaunch() {
  // A running but refusing helper cannot be repaired by reopening its protocol.
  if (getConnectionIssue()) {
    showConnectionIssue();
    return Promise.resolve(false);
  }
  if (!assistantLaunchPromise) {
    assistantLaunchPromise = launchAssistantOnce().finally(() => { assistantLaunchPromise = null; });
  }
  return assistantLaunchPromise;
}

async function launchAssistantOnce() {
  const watchId = ++assistantLaunchWatchId;
  elements.badge.textContent = "正在启动";
  elements.badge.className = "badge pending";
  showConnection("", {hidden: true});
  setMessage("");
  try {
    await closeAssistantLaunchTab();
    if (watchId !== assistantLaunchWatchId) return false;
    const roomTabId = currentRoomTabId;
    const roomWindowId = currentRoomWindowId;
    if (!Number.isInteger(roomTabId) || !Number.isInteger(roomWindowId) || !currentRoomUrl) {
      throw new Error("missing_live_room_context");
    }
    const returnTab = await chrome.tabs.get(roomTabId);
    if (watchId !== assistantLaunchWatchId) return false;
    if (
      returnTab?.windowId !== roomWindowId ||
      canonicalRoomUrl(returnTab?.url || "") !== currentRoomUrl
    ) {
      throw new Error("stale_live_room_context");
    }
    assistantReturnTabId = roomTabId;
    assistantReturnWindowId = roomWindowId;
    await chrome.windows.update(roomWindowId, {focused: true});
    await chrome.tabs.update(roomTabId, {active: true});
    if (watchId !== assistantLaunchWatchId) return false;
    const tab = await chrome.tabs.create({
      windowId: roomWindowId,
      openerTabId: roomTabId,
      url: ASSISTANT_LAUNCH_URL,
      active: true
    });
    assistantLaunchTabId = Number.isInteger(tab?.id) ? tab.id : null;
    if (watchId !== assistantLaunchWatchId) {
      await closeAssistantLaunchTab();
      return false;
    }
    return await watchAssistantLaunch(watchId);
  } catch (_error) {
    const hadPendingRecording = Boolean(pendingRecordingRequest);
    pendingRecordingRequest = null;
    showDeferredServiceState();
    setMessage(
      hadPendingRecording
        ? "录制未开始。请回到已识别的抖音直播间后重试。"
        : "请先回到已识别的抖音直播间，再启动录屏助手。",
      true
    );
    updateStartAvailability();
    return false;
  }
}

async function cancelAssistantLaunch() {
  assistantLaunchWatchId += 1;
  pendingRecordingRequest = null;
  await closeAssistantLaunchTab();
  showDeferredServiceState();
  updateStartAvailability();
}

async function launchAssistant(event) {
  event.preventDefault();
  await beginAssistantLaunch();
}

function hasActiveCurrentRoom() {
  return lastTasks.some(
    (task) => ACTIVE_STATES.has(task.state) && canonicalRoomUrl(task.room_url) === currentRoomUrl
  );
}

function updatePlaybackPauseNotice() {
  elements.playbackPauseNotice.hidden = !(
    pagePlaybackPaused &&
    hasActiveCurrentRoom()
  );
}

async function refreshPagePlaybackState() {
  const roomUrl = currentRoomUrl;
  const tabId = currentRoomTabId;
  if (!roomUrl || !Number.isInteger(tabId) || !hasActiveCurrentRoom()) {
    pagePlaybackPaused = false;
    updatePlaybackPauseNotice();
    return false;
  }
  try {
    const response = await chrome.tabs.sendMessage(tabId, {
      type: "brandbai-page-playback-state-query"
    });
    if (currentRoomUrl !== roomUrl || canonicalRoomUrl(response?.roomUrl || "") !== roomUrl) {
      return false;
    }
    pagePlaybackPaused = response?.energySaverPaused === true;
  } catch (_error) {
    pagePlaybackPaused = false;
  }
  updatePlaybackPauseNotice();
  return pagePlaybackPaused;
}

function activeTask() {
  return lastTasks.find((task) => ACTIVE_STATES.has(task.state)) || null;
}

function updateStartAvailability() {
  const activeCurrentRoom = hasActiveCurrentRoom();
  const currentActiveTask = activeTask();
  const activeOtherRoom = Boolean(
    currentActiveTask && canonicalRoomUrl(currentActiveTask.room_url) !== currentRoomUrl
  );
  const awaitingStorage = Boolean(
    pendingRecordingRequest && storageSettings && storageSettings.configured !== true
  );
  const configurationLocked =
    startInFlight || Boolean(pendingRecordingRequest) || Boolean(currentActiveTask) || storageBusy;
  const pendingCollectorLocked = startInFlight || Boolean(pendingRecordingRequest) || storageBusy;
  for (const control of [
    elements.quality,
    elements.recordingPreset,
    elements.recordingValue,
    elements.recordingUnit,
    elements.splitEnabled,
    elements.segmentPreset,
    elements.segmentValue,
    elements.segmentUnit
  ]) {
    control.disabled = configurationLocked;
  }
  for (const control of [
    elements.collectPageData,
    elements.collectComments,
    elements.collectProductCards,
    elements.collectRoomMetrics
  ]) {
    control.disabled = pendingCollectorLocked;
  }
  document.body.classList.toggle("has-active-task", Boolean(currentActiveTask));
  document.body.classList.toggle("has-other-active-task", activeOtherRoom);
  const resultCard = elements.taskList.closest?.('.results-card');
  const recordCard = document.querySelector('.record-card');
  const helpCard = document.querySelector('#help-contact');
  // Move actual nodes, so keyboard order follows the visual order too.
  if (resultCard && recordCard && helpCard) {
    if (currentActiveTask && resultCard.nextElementSibling !== recordCard) recordCard.before(resultCard);
    if (!currentActiveTask && resultCard.nextElementSibling !== elements.storageSettings) elements.storageSettings.before(resultCard);
    if (elements.storageSettings.nextElementSibling !== helpCard) helpCard.before(elements.storageSettings);
    resultCard.hidden = !lastTasks.length;
  }
  if (elements.stopRecording) {
    elements.start.hidden = Boolean(currentActiveTask);
    elements.stopRecording.hidden = !currentActiveTask;
    const stopping = currentActiveTask?.state === 'stopping' || stopRequests.has(currentActiveTask?.task_id);
    elements.stopRecording.disabled = !currentActiveTask || stopping;
    elements.stopRecording.textContent = stopping ? '正在停止并保存……' : '停止录制并保存';
    elements.stopRecording.setAttribute('aria-busy', String(stopping));
  }
  elements.roomSwitchNotice.hidden = !activeOtherRoom;
  elements.start.disabled =
    !currentRoomUrl || startInFlight || Boolean(pendingRecordingRequest) || Boolean(currentActiveTask) || storageBusy;
  elements.start.textContent = activeCurrentRoom
    ? "录制进行中"
    : activeOtherRoom
      ? "另一个直播间录制中"
    : startInFlight
      ? "正在开始录制……"
      : pendingRecordingRequest
        ? awaitingStorage
          ? "请先选择保存位置"
          : "正在启动并开始录制……"
        : sessionToken
          ? "开始录制"
          : "启动并开始录制";
}

function revealStorageSettings() {
  elements.storageSettings.open = true;
  requestAnimationFrame(() => {
    elements.storageSettings.scrollIntoView({behavior: "smooth", block: "center"});
    const primaryChoice = elements.useDefaultLocation.hidden
      ? elements.chooseLocation
      : elements.useDefaultLocation;
    primaryChoice.focus({preventScroll: true});
  });
}

async function clearSession(message = "正在恢复录制功能……", showRetry = false) {
  sessionToken = null;
  sessionExpiresAt = null;
  try {
    await chrome.storage.session.remove(SESSION_KEY);
  } catch (_error) {
    // A failed cleanup must not keep an invalid token active in this side panel.
  }
  showConnection(message, {retry: showRetry, hidden: true});
  updateStartAvailability();
}

async function restoreSession() {
  try {
    const stored = await chrome.storage.session.get(SESSION_KEY);
    const session = stored?.[SESSION_KEY];
    if (
      !session ||
      session.clientId !== EXTENSION_CLIENT_ID ||
      !SERVICE_BASES.includes(session.serviceBase) ||
      (activeServiceBase !== null && session.serviceBase !== activeServiceBase) ||
      typeof session.token !== "string" ||
      session.token.length < 32 ||
      !Number.isFinite(session.expiresAt) ||
      Date.now() >= session.expiresAt
    ) {
      await clearSession("正在准备录制功能……");
      return false;
    }
    activeServiceBase = session.serviceBase;
    sessionToken = session.token;
    sessionExpiresAt = session.expiresAt;
    updateStartAvailability();
    return true;
  } catch (_error) {
    await clearSession("正在重新准备录制功能……");
    return false;
  }
}

async function saveSession() {
  await chrome.storage.session.set({
    [SESSION_KEY]: {
      token: sessionToken,
      expiresAt: sessionExpiresAt,
      clientId: EXTENSION_CLIENT_ID,
      serviceBase: activeServiceBase,
      productSnapshots, productCatalog
    }
  });
}

function canonicalRoomUrl(rawUrl) {
  try {
    const parsed = new URL(rawUrl);
    if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.port) return null;
    if (parsed.hostname === "live.douyin.com") {
      const match = parsed.pathname.match(/^\/(\d{1,30})\/?$/);
      return match ? `https://live.douyin.com/${match[1]}` : null;
    }
    // A user-opened live room can remain inside the Douyin search route.
    // Keep only its explicit room id, never the search text or tracking query.
    if (!["www.douyin.com", "douyin.com"].includes(parsed.hostname) || !/^\/(?:jingxuan\/)?search\/[^/]+\/?$/.test(parsed.pathname)) return null;
    const ids = parsed.searchParams.getAll("live_web_rid");
    const types = parsed.searchParams.getAll("type");
    return ids.length === 1 && /^\d{1,30}$/.test(ids[0]) && types.length === 1 && types[0] === "live"
      ? `https://live.douyin.com/${ids[0]}` : null;
  } catch (_error) {
    return null;
  }
}

function roomNameFromTab(tab) {
  const title = String(tab?.title || "")
    .replace(/的抖音直播间\s*-\s*抖音直播$/u, "")
    .replace(/\s*-\s*抖音直播$/u, "")
    .trim();
  const technicalTitle =
    !title ||
    title.length > 48 ||
    /^(?:https?:\/\/)?live\.douyin\.com\//iu.test(title) ||
    /(?:[?&][a-z0-9_]+|action_type=|enter_from|request_id=|room_id=)/iu.test(title);
  return technicalTitle ? null : title;
}

function qualityLabel(value) {
  return {SD: "标清", HD: "高清", OD: "原画"}[value] || "默认画质";
}

function friendlyErrorMessage(message) {
  const original = String(message || "").trim();
  const normalized = original.toLowerCase();
  if (original === connectionIssue && connectionIssue) return original;
  if (
    normalized.includes("时长") ||
    normalized.includes("必须拆分") ||
    normalized.includes("至少选择")
  ) {
    return original;
  }
  if (normalized.includes("not_live") || normalized.includes("未开播")) {
    return "当前直播间尚未开播，请确认直播状态后重试。";
  }
  if (normalized.includes("当前页面不是") || normalized.includes("抖音直播间")) {
    return "请先打开一个抖音直播间。";
  }
  if (normalized.includes("another live room") || normalized.includes("already recording")) {
    return "已有另一个直播间正在录制，请先结束并保存当前任务。";
  }
  if (normalized.includes("folder selection")) {
    return "暂时无法打开文件夹选择，请稍后重试。";
  }
  if (normalized.includes("recording location")) {
    elements.storageSettings.open = true;
    return "请先确认一次保存位置。";
  }
  if (normalized.includes("storage") || normalized.includes("空间")) {
    return "本机可用空间不足，请清理空间后重试。";
  }
  if (
    normalized.includes("本机服务") ||
    normalized.includes("录制功能") ||
    normalized.includes("录屏助手")
  ) {
    return "录屏助手尚未启动，请点击“启动录屏助手”。";
  }
  if (
    normalized.includes("network") ||
    normalized.includes("timeout") ||
    normalized.includes("连接") ||
    normalized.includes("resolver")
  ) {
    return "暂时无法连接直播间，请稍后重试。";
  }
  return "操作未完成，请稍后重试。";
}

function updateCollectorOptionVisibility() {
  elements.collectorOptions.hidden = !elements.collectPageData.checked;
}

function collectorOptionsFromForm() {
  const options = {
    enabled: elements.collectPageData.checked,
    comments: elements.collectComments.checked,
    productCards: elements.collectProductCards.checked,
    roomMetrics: elements.collectRoomMetrics.checked
  };
  if (options.enabled && !options.comments && !options.productCards && !options.roomMetrics) {
    throw new Error("开启互动记录后，请至少选择评论、商品卡或人数与点赞中的一项。 ");
  }
  return options;
}

function collectorOptionsFromTask(task) {
  const comments = task?.collect_comments === true;
  const productCards = task?.collect_product_cards === true;
  const roomMetrics = task?.collect_room_metrics === true;
  return {
    enabled: comments || productCards || roomMetrics,
    comments,
    productCards,
    roomMetrics
  };
}

function applyCollectorOptionsToForm(options) {
  elements.collectPageData.checked = options.enabled === true;
  elements.collectComments.checked = options.comments !== false;
  elements.collectProductCards.checked = options.productCards !== false;
  elements.collectRoomMetrics.checked = options.roomMetrics !== false;
  updateCollectorOptionVisibility();
}

async function loadCollectorOptions(roomUrl, isCurrent = () => currentRoomUrl === roomUrl) {
  const stored = await chrome.storage.session.get(COLLECTOR_OPTIONS_KEY);
  if (!isCurrent()) return;
  const saved = stored?.[COLLECTOR_OPTIONS_KEY]?.[roomUrl];
  if (!saved || typeof saved !== "object") {
    applyCollectorOptionsToForm({
      enabled: false,
      comments: true,
      productCards: true,
      roomMetrics: true
    });
  } else {
    applyCollectorOptionsToForm(saved);
  }
}

async function saveCollectorOptions(roomUrl, options) {
  const stored = await chrome.storage.session.get(COLLECTOR_OPTIONS_KEY);
  const allOptions = stored?.[COLLECTOR_OPTIONS_KEY];
  const next = allOptions && typeof allOptions === "object" ? {...allOptions} : {};
  next[roomUrl] = {...options, updatedAt: Date.now()};
  await chrome.storage.session.set({[COLLECTOR_OPTIONS_KEY]: next});
}

async function notifyCurrentTabCollectorOptions(roomUrl, options) {
  try {
    const tabs = await chrome.tabs.query({active: true, currentWindow: true});
    const tab = tabs[0];
    if (!tab?.id || canonicalRoomUrl(tab.url || "") !== roomUrl) {
      return false;
    }
    const response = await chrome.tabs.sendMessage(tab.id, {
      type: "brandbai-collector-options-updated",
      roomUrl,
      productSnapshots,
      productCatalog,
      collectorOptions: options
    });
    return response?.ok === true;
  } catch (_error) {
    // Storage remains authoritative; the content script also polls it as a fallback.
    return false;
  }
}

async function ensureCurrentTabContentScript(roomUrl, expectedTabId = null) {
  try {
    const tabs = await chrome.tabs.query({active: true, currentWindow: true});
    const tab = tabs[0];
    if (!tab?.id || (expectedTabId !== null && tab.id !== expectedTabId) || canonicalRoomUrl(tab.url || "") !== roomUrl) {
      return false;
    }
    try {
      const response = await chrome.tabs.sendMessage(tab.id, {
        type: "brandbai-content-script-ping",
        roomUrl
      });
      if (response?.ok === true) {
        return true;
      }
    } catch (_error) {
      // A reloaded extension invalidates scripts already present in open pages.
    }
    await chrome.scripting.executeScript({
      target: {tabId: tab.id},
      files: ["douyin-commerce-dom.js", "product-identity.js", "live-products.js", "page-materials.js", "product-review-collector.js", "review-page.js", "content.js"]
    });
    const response = await chrome.tabs.sendMessage(tab.id, {
      type: "brandbai-content-script-ping",
      roomUrl
    });
    return response?.ok === true;
  } catch (_error) {
    return false;
  }
}

async function restoreCollectorOptionsFromActiveTask(task) {
  const roomUrl = canonicalRoomUrl(task?.room_url || "");
  if (!roomUrl) {
    return null;
  }
  const stored = await chrome.storage.session.get(COLLECTOR_OPTIONS_KEY);
  const saved = stored?.[COLLECTOR_OPTIONS_KEY]?.[roomUrl];
  if (saved && typeof saved === "object") {
    return {
      enabled: saved.enabled === true,
      comments: saved.comments === true,
      productCards: saved.productCards === true,
      roomMetrics: saved.roomMetrics === true
    };
  }
  const taskOptions = collectorOptionsFromTask(task);
  const restored = taskOptions.enabled
    ? taskOptions
    : {enabled: false, comments: true, productCards: true, roomMetrics: true};
  await saveCollectorOptions(roomUrl, restored);
  if (currentRoomUrl === roomUrl) {
    applyCollectorOptionsToForm(restored);
  }
  return restored;
}

function maintainCurrentRoomPage(task, {force = false} = {}) {
  const roomUrl = canonicalRoomUrl(task?.room_url || "");
  if (!roomUrl || roomUrl !== currentRoomUrl) {
    return Promise.resolve(false);
  }
  if (contentRecoveryInFlight && contentRecoveryRoomUrl === roomUrl) {
    return contentRecoveryInFlight;
  }
  const now = Date.now();
  if (
    !force &&
    contentRecoveryRoomUrl === roomUrl &&
    now - contentRecoveryLastAttemptAt < CONTENT_SCRIPT_HEALTHCHECK_MS
  ) {
    return Promise.resolve(true);
  }
  contentRecoveryRoomUrl = roomUrl;
  contentRecoveryLastAttemptAt = now;
  const recovery = (async () => {
    const options = await restoreCollectorOptionsFromActiveTask(task);
    const ready = await ensureCurrentTabContentScript(roomUrl);
    if (!ready) {
      return false;
    }
    if (options) {
      await notifyCurrentTabCollectorOptions(roomUrl, options);
    }
    await activateCurrentTabPlaybackGuard(roomUrl);
    return true;
  })();
  contentRecoveryInFlight = recovery;
  return recovery.finally(() => {
    if (contentRecoveryInFlight === recovery) {
      contentRecoveryInFlight = null;
    }
  });
}

async function activateCurrentTabPlaybackGuard(roomUrl) {
  try {
    const tabs = await chrome.tabs.query({active: true, currentWindow: true});
    const tab = tabs[0];
    if (!tab?.id || canonicalRoomUrl(tab.url || "") !== roomUrl) {
      return false;
    }
    const response = await chrome.tabs.sendMessage(tab.id, {
      type: "brandbai-playback-guard-activate",
      roomUrl
    });
    return response?.ok === true;
  } catch (_error) {
    // The content script's task probe remains the bounded fallback.
    return false;
  }
}

function persistCollectorOptionsFromForm() {
  const roomUrl = currentRoomUrl;
  if (!roomUrl) {
    return;
  }
  let options;
  try {
    options = collectorOptionsFromForm();
  } catch (error) {
    setMessage(error.message, true);
    return;
  }
  collectorOptionSaveChain = collectorOptionSaveChain
    .then(async () => {
      const currentTask = lastTasks.find(
        (task) => ACTIVE_STATES.has(task.state) && canonicalRoomUrl(task.room_url) === roomUrl
      );
      if (currentTask) {
        await api(`/v1/tasks/${encodeURIComponent(currentTask.task_id)}/collector-options`, {
          method: "POST",
          body: {
            collect_comments: options.enabled && options.comments,
            collect_product_cards: options.enabled && options.productCards,
            collect_room_metrics: options.enabled && options.roomMetrics
          }
        });
      }
      await saveCollectorOptions(roomUrl, options);
      if (hasActiveCurrentRoom()) {
        await ensureCurrentTabContentScript(roomUrl);
      }
      const delivered = await notifyCurrentTabCollectorOptions(roomUrl, options);
      const active = hasActiveCurrentRoom();
      const timing = active
        ? delivered
          ? "已在录制中生效"
          : "已保存，互动记录将在数秒内同步"
        : "已保存";
      setMessage(`${timing}：${collectorSelectionLabel(options)}。 `);
    })
    .catch(() => setMessage("互动记录设置暂时无法保存，请重试。", true));
}

function handleCollectorOptionChange() {
  updateCollectorOptionVisibility();
  void refreshPagePlaybackState();
  persistCollectorOptionsFromForm();
}

function collectorSelectionLabel(options) {
  if (!options.enabled) {
    return "未开启互动记录";
  }
  const labels = [];
  if (options.comments) labels.push("评论");
  if (options.productCards) labels.push("商品卡");
  if (options.roomMetrics) labels.push("人数与点赞");
  return `互动记录：${labels.join("、")}`;
}

function roomTabWithTimeout(promise) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("room_tab_timeout")), ROOM_TAB_TIMEOUT_MS);
    Promise.resolve(promise).then(resolve, reject).finally(() => clearTimeout(timer));
  });
}

function classifyRoomTab(tab) {
  if (!tab) return "no_tab";
  // URL can be withheld by Chrome. Never claim this proves a non-live page.
  if (typeof tab.url !== "string" || !tab.url) return "access_required";
  if (canonicalRoomUrl(tab.url)) return "recognized";
  try {
    const url = new URL(tab.url);
    if (["www.douyin.com", "douyin.com", "live.douyin.com"].includes(url.hostname) &&
        (url.searchParams.has("live_web_rid") || url.searchParams.get("type") === "live")) return "entry_unconfirmed";
  } catch (_error) { /* Unsupported URLs never establish room identity. */ }
  return "not_live";
}

function showRoomAccessState(state) {
  const copy = {
    access_required: ["需要允许读取当前页面", "尚未取得当前页地址，无法判断是否为直播。若已在抖音直播页，请允许识别。", "待授权"],
    entry_unconfirmed: ["直播入口尚未确认", "当前地址未提供唯一有效的直播间编号。请重新打开直播入口后再试。", "待确认"],
    unavailable: ["暂时无法读取当前页面", "读取页面超时或连接中断，请重新识别；不会启动录制。", "待重试"],
    no_tab: ["请打开一个抖音直播间", "当前窗口没有可读取的标签页。", "等待识别"],
    not_live: ["当前不是可识别的直播页面", "请打开抖音直播间，打开后会自动识别。", "等待识别"]
  }[state];
  elements.roomAccessNotice.hidden = state === "recognized" || state === "not_live" || state === "no_tab";
  elements.allowRoomAccess.hidden = state !== "access_required";
  elements.roomAccessScope.hidden = state !== "access_required";
  elements.allowRoomAccess.disabled = roomAccessRequestInFlight;
  elements.retryRoomAccess.disabled = roomAccessRequestInFlight;
  if (!copy) return;
  elements.roomAccessTitle.textContent = copy[0];
  elements.roomAccessMessage.textContent = copy[1];
  elements.roomName.textContent = copy[0];
  elements.pageStatus.textContent = copy[1];
  elements.roomState.className = "room-state pending";
  elements.roomStateLabel.textContent = copy[2];
}

function clearCurrentRoomContext() {
  currentRoomUrl = null;
  currentRoomTabId = null;
  currentRoomWindowId = null;
  pagePlaybackPaused = false;
  updateStartAvailability();
  updatePlaybackPauseNotice();
}

async function requestRoomAccess() {
  if (roomAccessRequestInFlight) return;
  roomAccessRequestInFlight = true;
  elements.allowRoomAccess.disabled = true;
  elements.retryRoomAccess.disabled = true;
  elements.roomAccessMessage.textContent = "请在 Chrome 确认框中选择是否允许读取抖音站点。";
  let granted = false;
  let failed = false;
  try {
    // Must be called directly in the click gesture, before any await/query.
    granted = await chrome.permissions.request({origins: [...DOUYIN_OPTIONAL_ORIGINS]});
  } catch (_error) { failed = true; }
  finally { roomAccessRequestInFlight = false; }
  await readCurrentTab(); // Always inspect the current tab, never the pre-dialog tab.
  if (!granted && !elements.roomAccessNotice.hidden && !elements.allowRoomAccess.hidden) {
    elements.roomAccessMessage.textContent = failed
      ? "未能打开站点授权。可重试，或在当前直播页点击工具栏插件图标临时使用。"
      : "尚未授权。可以再次允许，或在当前直播页点击工具栏插件图标临时使用；没有开始录制。";
  }
}

async function readCurrentTab() {
  const generation = ++roomReadGeneration;
  let tabs;
  try {
    tabs = await roomTabWithTimeout(chrome.tabs.query({active: true, currentWindow: true}));
  } catch (_error) {
    if (generation !== roomReadGeneration) return;
    clearCurrentRoomContext();
    showRoomAccessState("unavailable");
    return;
  }
  if (generation !== roomReadGeneration) return;
  const tab = tabs[0];
  const state = classifyRoomTab(tab);
  const room = canonicalRoomUrl(tab?.url || "");
  showRoomAccessState(state);
  if (!room) {
    clearCurrentRoomContext();
  } else {
    currentRoomUrl = room;
    currentRoomTabId = Number.isInteger(tab?.id) ? tab.id : null;
    currentRoomWindowId = Number.isInteger(tab?.windowId) ? tab.windowId : null;
    const roomName = roomNameFromTab(tab);
    elements.roomName.textContent = roomName || "正在识别直播间";
    elements.pageStatus.textContent = roomName
      ? "可以开始录制。"
      : "直播间已识别，正在读取名称。";
    elements.roomState.className = roomName ? "room-state ready" : "room-state pending";
    elements.roomStateLabel.textContent = roomName ? "已识别" : "识别中";
    await loadCollectorOptions(room, () => generation === roomReadGeneration);
    if (generation !== roomReadGeneration) return;
    void refreshPagePlaybackState();
    if (sessionToken) {
      void refreshTasks({silent: true});
    }
  }
  updateStartAvailability();
  updatePlaybackPauseNotice();
}

function scheduleCurrentTabRead() {
  // Invalidate pending reads immediately, not after the debounce delay.
  roomReadGeneration += 1;
  clearCurrentRoomContext();
  if (tabRefreshTimer !== null) {
    clearTimeout(tabRefreshTimer);
  }
  tabRefreshTimer = setTimeout(() => {
    tabRefreshTimer = null;
    readCurrentTab().catch((error) => setMessage(error.message, true));
  }, 120);
}

async function fetchWithTimeout(url, options, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {...options, signal: controller.signal});
  } finally {
    clearTimeout(timer);
  }
}

async function discoverService() {
  activeServiceBase = null;
  for (const serviceBase of SERVICE_BASES) {
    try {
      const response = await fetchWithTimeout(
        `${serviceBase}/v1/health`,
        {headers: {"Accept": "application/json"}, cache: "no-store"},
        SERVICE_HEALTH_TIMEOUT_MS
      );
      const payload = await response.json().catch(() => ({}));
      if (
        response.ok &&
        payload.service === "brandbai-live-recorder" &&
        payload.status === "ready"
      ) {
        activeServiceBase = serviceBase;
        productSnapshots = payload.product_snapshots === true;
        productCatalog = payload.product_catalog === true;
        return payload;
      }
    } catch (_error) {
      // Offline, occupied, or unresponsive candidates are skipped automatically.
    }
  }
  throw new Error("录屏助手尚未启动。 ");
}

async function api(path, {method = "GET", body = null, auth = true, extraHeaders = {}} = {}) {
  if (!auth && path === "/v1/health") {
    return discoverService();
  }
  if (!activeServiceBase) {
    await discoverService();
  }
  const headers = {"Accept": "application/json", "X-BrandBAI-Delivery": "browser-zip", ...extraHeaders};
  if (auth) {
    if (sessionExpiresAt && Date.now() >= sessionExpiresAt) {
      await clearSession();
    }
    if (!sessionToken) {
      throw new Error("录制功能正在恢复，请稍候。 ");
    }
    headers["X-BrandBAI-Token"] = sessionToken;
    headers["X-BrandBAI-Client"] = EXTENSION_CLIENT_ID;
  }
  if (body !== null) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetchWithTimeout(
    `${activeServiceBase}${path}`,
    {
      method,
      headers,
      body: body === null ? undefined : JSON.stringify(body),
      cache: "no-store"
    },
    SERVICE_REQUEST_TIMEOUT_MS
  );
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (auth && response.status === 401) {
      await clearSession();
    }
    const error = new Error(payload.message || `本机服务返回 ${response.status}`);
    error.status = response.status;
    throw error;
  }
  const delivery = payload?.task?.delivery || payload?.product_download?.delivery;
  if (method === 'POST' && delivery && !path.startsWith('/v1/deliveries/')) {
    void chrome.runtime.sendMessage({type:'brandbai-delivery',action:'watch',id:delivery.id}).catch(()=>{});
  }
  return payload;
}

function renderStorageSettings({collapse = false} = {}) {
  elements.storageSettings.classList.remove('requires-choice');
  elements.storageRequiredNote.hidden = true;
  elements.storageTitle.textContent = '下载记录';
  elements.storageSummary.textContent = '文件存到浏览器的下载文件夹';
  elements.storageHelp.textContent = '无需另选目录。更换位置请到浏览器下载设置；旧文件不移动。';
  elements.useDefaultLocation.hidden = true;
  elements.chooseLocation.hidden = true;
  if (collapse) elements.storageSettings.open = false;
}

async function refreshStorageSettings({silent = false} = {}) {
  if (!sessionToken) {
    return false;
  }
  try {
    const payload = await api("/v1/settings");
    if (payload.storage?.mode !== 'browser-zip') throw new Error('助手尚不支持浏览器 ZIP 下载，请空闲后更新。');
    storageSettings = payload.storage || null;
    renderStorageSettings();
    updateStartAvailability();
    return Boolean(storageSettings);
  } catch (error) {
    storageSettings = null;
    renderStorageSettings();
    if (!silent) {
      setMessage("请空闲后更新本机助手，才能使用浏览器 ZIP 下载。", true);
    }
    updateStartAvailability();
    return false;
  }
}

async function updateOutputRoot(action) {
  if (!sessionToken || storageBusy) {
    return;
  }
  storageBusy = true;
  renderStorageSettings();
  updateStartAvailability();
  try {
    const payload = await api("/v1/settings/output-root", {
      method: "POST",
      body: {action},
      extraHeaders: {"X-BrandBAI-Settings": "user-click"}
    });
    storageSettings = payload.storage || storageSettings;
    renderStorageSettings({collapse: !payload.canceled});
    if (payload.canceled) {
      setMessage("保存位置没有更改。 ");
    } else {
      setMessage("保存位置已记住，只影响之后开始的录制和商品下载。 ");
      await resumePendingRecording();
    }
  } catch (error) {
    setMessage(friendlyErrorMessage(error.message), true);
  } finally {
    storageBusy = false;
    renderStorageSettings();
    updateStartAvailability();
  }
}

async function checkHealth({launching = false, launchWatchId = null} = {}) {
  try {
    const health = await api("/v1/health", {auth: false});
    if (launchWatchId !== null && launchWatchId !== assistantLaunchWatchId) return false;
    document.querySelector("#product-upgrade-note").hidden = health.product_downloads === true;
    const ready = health.status === "ready" && (health.automatic_pairing || health.one_click_pairing);
    elements.badge.textContent = connectionIssue ? "连接待恢复" : ready ? "助手已连接" : "暂不可用";
    elements.badge.className = `badge ${ready && !connectionIssue ? "ready" : "error"}`;
    if (ready) {
      await closeAssistantLaunchTab();
      if (connectionIssue) showConnectionIssue();
    }
    if (!ready) {
      connectionIssue = "助手已运行，但版本暂不支持当前插件。请在录制和下载结束后更新助手，再点击“重新检测”。";
      connectionRetryAt = Date.now() + CONNECTION_RETRY_MS;
      pendingRecordingRequest = null;
      showConnectionIssue();
      setMessage(connectionIssue, true);
    }
    return ready;
  } catch (_error) {
    connectionIssue = "";
    connectionRetryAt = 0;
    if (launching) {
      elements.badge.textContent = "正在启动";
      elements.badge.className = "badge pending";
      showConnection("", {hidden: true});
    } else {
      showDeferredServiceState();
    }
    updateStartAvailability();
    return false;
  }
}

async function pairService() {
  if (pairing) {
    return false;
  }
  pairing = true;
  elements.badge.textContent = "正在准备";
  elements.badge.className = "badge pending";
  showConnection("", {hidden: true});
  try {
    const payload = await api("/v1/pair", {
      method: "POST",
      auth: false,
      extraHeaders: {
        "X-BrandBAI-Pair": "extension-popup",
        "X-BrandBAI-Client": EXTENSION_CLIENT_ID
      }
    });
    if (!payload.session_token || payload.persisted !== false || payload.origin_bound !== true) {
      throw new Error("本机服务返回了无效的短时会话。 ");
    }
    sessionToken = payload.session_token;
    const seconds = Number(payload.expires_in_seconds || 0);
    sessionExpiresAt = seconds > 0 ? Date.now() + seconds * 1000 : Date.now() + 15 * 60 * 1000;
    await saveSession();
    showConnection("录制功能已准备好。", {hidden: true});
    updateStartAvailability();
    if (!(await refreshTasks({silent: true})) || !(await refreshStorageSettings({silent: true}))) {
      throw new Error("assistant_not_ready");
    }
    return true;
  } catch (error) {
    await clearSession();
    failConnection(error);
    return false;
  } finally {
    pairing = false;
  }
}

function connectService({retry = false} = {}) {
  // Share the full health/session/pairing operation between polling and clicks.
  if (!connectionPromise) {
    connectionPromise = connectServiceOnce({retry}).finally(() => { connectionPromise = null; });
  }
  return connectionPromise;
}

async function connectServiceOnce({retry = false} = {}) {
  if (!(await checkHealth())) {
    return false;
  }
  if (!retry && connectionIssue && Date.now() < connectionRetryAt) {
    showConnectionIssue();
    return false;
  }
  let connected = false;
  if (await restoreSession()) {
    const restored = await refreshTasks({silent: true});
    if (restored) {
      showConnection("录制功能已准备好。", {hidden: true});
      connected = await refreshStorageSettings({silent: true});
    }
  }
  if (!connected) {
    connected = await pairService();
  }
  if (connected) {
    const recovered = Boolean(connectionIssue);
    connectionIssue = "";
    connectionRetryAt = 0;
    elements.badge.textContent = "助手已连接";
    elements.badge.className = "badge ready";
    showConnection("", {hidden: true});
    if (recovered) setMessage("");
    await resumePendingRecording();
  }
  return connected;
}

function recordingSeconds() {
  if (elements.recordingPreset.value !== "custom") {
    const value = Number(elements.recordingPreset.value);
    if (!RECORDING_PRESET_SECONDS.has(value)) {
      throw new Error("录制时长快捷值无效。 ");
    }
    return value;
  }
  const number = Number(elements.recordingValue.value);
  if (!Number.isInteger(number)) {
    throw new Error("自定义录制时长必须是正整数。 ");
  }
  if (elements.recordingUnit.value === "minutes") {
    if (number < 1 || number > 1440) {
      throw new Error("录制分钟范围为 1—1440。 ");
    }
    return number * 60;
  }
  if (number < 60 || number > 86400) {
    throw new Error("录制秒数范围为 60—86400。 ");
  }
  return number;
}

function segmentSeconds(totalSeconds) {
  if (!elements.splitEnabled.checked) {
    return Math.min(totalSeconds, 21600);
  }
  let value;
  if (elements.segmentPreset.value !== "custom") {
    value = Number(elements.segmentPreset.value);
    if (!SEGMENT_PRESET_SECONDS.has(value)) {
      throw new Error("分段时长快捷值无效。 ");
    }
  } else {
    const number = Number(elements.segmentValue.value);
    if (!Number.isInteger(number)) {
      throw new Error("自定义分段时长必须是正整数。 ");
    }
    if (elements.segmentUnit.value === "minutes") {
      if (number < 1 || number > 360) {
        throw new Error("分段分钟范围为 1—360。 ");
      }
      value = number * 60;
    } else {
      if (number < 60 || number > 21600) {
        throw new Error("分段秒数范围为 60—21600。 ");
      }
      value = number;
    }
  }
  if (value > totalSeconds) {
    throw new Error("每段时长不能超过总录制时长。 ");
  }
  return value;
}

function formatDuration(totalSeconds) {
  const safe = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = safe % 60;
  return hours > 0
    ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function formatCompactDuration(totalSeconds) {
  const seconds = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  if (seconds > 0 && seconds % 3600 === 0) {
    return `${seconds / 3600} 小时`;
  }
  if (seconds > 0 && seconds % 60 === 0) {
    return `${seconds / 60} 分钟`;
  }
  return `${seconds} 秒`;
}

function formatHumanDuration(totalSeconds) {
  const seconds = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  const parts = [];
  if (hours) parts.push(`${hours}小时`);
  if (minutes) parts.push(`${minutes}分钟`);
  if (remainder || !parts.length) parts.push(`${remainder}秒`);
  return parts.join("");
}

function formatTaskTime(raw) {
  const date = new Date(raw || "");
  if (!Number.isFinite(date.getTime())) {
    return "最近一次录制";
  }
  const now = new Date();
  const time = date.toLocaleTimeString("zh-CN", {hour: "2-digit", minute: "2-digit"});
  const sameDay = date.toDateString() === now.toDateString();
  return sameDay ? `今天 ${time}` : `${date.getMonth() + 1}月${date.getDate()}日 ${time}`;
}

function expectedVideoCount(totalSeconds) {
  if (!elements.splitEnabled.checked) {
    return 1;
  }
  return Math.max(1, Math.ceil(totalSeconds / segmentSeconds(totalSeconds)));
}

function completionTone(task) {
  if (task.state === "failed" || String(task.completion_status || "").startsWith("failed_")) {
    return "error";
  }
  if (task.state === "not_live") {
    return "warning";
  }
  if (["partial_disconnect", "partial_conversion", "partial_service_restart"].includes(task.completion_status)) {
    return "warning";
  }
  return "success";
}

function taskStatePresentation(task) {
  if (ACTIVE_STATES.has(task.state)) {
    return {label: STATE_LABELS[task.state] || "录制中", tone: "active"};
  }
  const tone = completionTone(task);
  if (tone === "error") return {label: "录制失败", tone};
  if (task.state === "not_live") return {label: "当前未开播", tone: "warning"};
  if (task.completion_status === "partial_disconnect") {
    return {label: "已保存可用部分", tone: "warning"};
  }
  if (task.completion_status === "partial_conversion") {
    return {label: "部分视频未生成", tone: "warning"};
  }
  if (task.completion_status === "partial_service_restart") {
    return {label: "意外中断，已保存", tone: "warning"};
  }
  if (tone === "warning") return {label: "需要留意", tone};
  if (["partial_manual_stop", "partial_service_stop"].includes(task.completion_status)) {
    return {label: "已提前结束并保存", tone: "success"};
  }
  if (task.completion_status === "complete_observed_session") {
    return {label: "直播结束并保存", tone: "success"};
  }
  if (task.completion_status === "partial_time_limit") {
    return {label: "已按设置完成", tone: "success"};
  }
  return {label: "录制完成", tone: "success"};
}

function updateConfigurationSummary() {
  try {
    const totalSeconds = recordingSeconds();
    const count = expectedVideoCount(totalSeconds);
    elements.configSummary.textContent = `预计 ${count} 个视频 · ${formatCompactDuration(totalSeconds)} · ${qualityLabel(elements.quality.value)}`;
  } catch (_error) {
    elements.configSummary.textContent = "请检查录制时长设置";
  }
  updateStartAvailability();
}

function taskElapsedSeconds(task) {
  const started = Date.parse(task.started_at || "");
  if (!Number.isFinite(started)) {
    return 0;
  }
  const ended = Date.parse(task.ended_at || "");
  const endTime = Number.isFinite(ended) ? ended : Date.now();
  return Math.max(0, Math.floor((endTime - started) / 1000));
}

function addProgress(wrapper, task) {
  const totalTarget = Math.max(1, Number(task.max_runtime_seconds) || 1);
  const segmentTarget = Math.max(1, Number(task.segment_duration_seconds) || totalTarget);
  const elapsed = taskElapsedSeconds(task);
  const remainingSeconds = Math.max(0, totalTarget - elapsed);
  const segmentCount = Math.max(1, Math.ceil(totalTarget / segmentTarget));
  const segmentIndex = Math.min(segmentCount, Math.floor(elapsed / segmentTarget) + 1);
  const expectedEnd = new Date(Date.parse(task.started_at || "") + totalTarget * 1000);
  const expectedEndText = Number.isFinite(expectedEnd.getTime())
    ? expectedEnd.toLocaleTimeString("zh-CN", {hour: "2-digit", minute: "2-digit"})
    : "--:--";
  const summary = document.createElement("div");
  summary.className = "progress-summary";
  const remaining = document.createElement("p");
  remaining.className = "remaining-time";
  remaining.textContent = `剩余 ${formatDuration(remainingSeconds)}`;
  const detail = document.createElement("p");
  detail.className = "muted progress-detail";
  const segmentNote = task.split_enabled
    ? `第 ${segmentIndex}/${segmentCount} 个视频`
    : "单文件录制";
  detail.textContent = `已运行 ${formatDuration(elapsed)}\n预计 ${expectedEndText} 结束 · ${segmentNote}`;
  if (Number.isFinite(task.recording_health?.media_seconds)) {
    detail.textContent += `\n本段已接收 ${formatDuration(task.recording_health.media_seconds)} 视频`;
  }
  summary.append(remaining, detail);
  const track = document.createElement("div");
  track.className = "progress-track";
  const bar = document.createElement("div");
  bar.className = "progress-bar";
  bar.style.width = `${Math.min(100, (elapsed / totalTarget) * 100)}%`;
  track.setAttribute("role", "progressbar");
  track.setAttribute("aria-label", "任务时间进度，不代表有效视频时长");
  track.setAttribute("aria-valuemin", "0");
  track.setAttribute("aria-valuemax", String(totalTarget));
  track.setAttribute("aria-valuenow", String(Math.min(totalTarget, elapsed)));
  track.append(bar);
  wrapper.append(summary, track);
}

async function copyOutputPath(path) {
  try {
    await navigator.clipboard.writeText(path);
    setMessage("保存位置已复制。 ");
  } catch (_error) {
    const temporary = document.createElement("textarea");
    temporary.value = path;
    temporary.setAttribute("readonly", "");
    temporary.style.position = "fixed";
    temporary.style.opacity = "0";
    document.body.append(temporary);
    temporary.select();
    const copied = document.execCommand("copy");
    temporary.remove();
    setMessage(copied ? "保存位置已复制。 " : "暂时无法复制保存位置，请重试。 ", !copied);
  }
}

function taskElement(task) {
  const wrapper = document.createElement("article");
  wrapper.className = "task";
  wrapper.dataset.taskId = task.task_id;

  const head = document.createElement("div");
  head.className = "task-head";
  const title = document.createElement("strong");
  title.className = "task-title";
  const activeOtherRoom =
    ACTIVE_STATES.has(task.state) && canonicalRoomUrl(task.room_url) !== currentRoomUrl;
  title.textContent = ACTIVE_STATES.has(task.state)
    ? activeOtherRoom
      ? "后台录制"
      : "当前录制"
    : `最近录制 · ${formatTaskTime(task.started_at)}`;
  const presentation = taskStatePresentation(task);
  const state = document.createElement("span");
  state.className = `task-state ${presentation.tone}`;
  state.textContent = presentation.label;
  head.append(title, state);

  const meta = document.createElement("p");
  meta.className = "task-meta";
  const targetSeconds = Math.max(0, Number(task.max_runtime_seconds) || 0);
  const segmentSecondsValue = Math.max(1, Number(task.segment_duration_seconds) || targetSeconds || 1);
  const plannedFiles = task.split_enabled ? Math.max(1, Math.ceil(targetSeconds / segmentSecondsValue)) : 1;
  meta.textContent = `${formatCompactDuration(targetSeconds)} · ${plannedFiles} 个视频 · ${qualityLabel(task.quality)}`;
  wrapper.append(head, meta);

  if (ACTIVE_STATES.has(task.state)) {
    const mediaHealth = task.recording_health;
    const interactionHealth = task.interaction_health;
    const messages = [];
    if (mediaHealth?.state === 'reconnecting') messages.push(`视频流已中断，正在重新连接（${mediaHealth.retry_index}/${mediaHealth.retry_limit}）。已录片段保留，总录制截止时间不延长。`);
    else if (mediaHealth?.state === 'stalled') messages.push('视频数据已停止增长，正在结束异常连接并准备恢复；计时继续不代表视频完整。');
    else if (mediaHealth?.state === 'connecting') messages.push('正在等待视频数据；收到有效进度后才算开始接收。');
    if (interactionHealth?.status === 'interaction_interrupted') messages.push('评论采集已受阻：当前账号在别处进入了直播间。请回到原直播页确认是否继续看播；插件不会自动争抢观看状态。视频录制状态请单独查看。');
    else if (interactionHealth?.status === 'comment_stream_stale') messages.push('已超过 3 分钟未观察到新评论，可能页面停止更新。请检查原直播页；这不代表期间没有人发言。');
    else if (interactionHealth?.status === 'stopped' && interactionHealth.reason === 'page_closed_or_navigated') messages.push('原直播页面已关闭或离开，评论无法继续采集；视频流录制独立进行。');
    else if (interactionHealth?.status === 'failed') messages.push('互动采集出现异常，部分记录可能缺失；结束后请查看资料包中的采集状态。');
    for (const message of messages) {
      const notice = document.createElement('p');
      notice.className = 'interaction-safety-note';
      notice.setAttribute('role', 'status');
      notice.textContent = message;
      wrapper.append(notice);
    }
  }

  const eventCount = Math.max(0, Number(task.visible_event_count) || 0);
  const interactionRequested = task.collect_comments || task.collect_product_cards || task.collect_room_metrics;
  if (eventCount > 0 || interactionRequested) {
    const interactions = document.createElement("p");
    interactions.className = "interaction-count";
    const counts = task.visible_event_counts;
    interactions.textContent = counts
      ? `评论 ${counts.comment_visible || 0} 条 · 商品弹窗变化 ${counts.product_state || 0} 次 · 人数等数据 ${counts.room_snapshot || 0} 次`
      : `已记录 ${eventCount} 条直播页面信息`;
    wrapper.append(interactions);
    if (!ACTIVE_STATES.has(task.state)) {
      const note = document.createElement('p'); note.className = 'muted';
      note.textContent = !eventCount ? '本次开启了互动记录，但未收到页面事件；不能按互动完整使用。'
        : task.recording_sections_available
        ? `同一直播 ZIP 内分区保存：评论与互动、弹窗商品、直播指标。弹窗共 ${task.popup_observation_group_count || 0} 个卡片观察组，仅含可见卡片资料，不是完整商品详情。`
        : task.interaction_export_available
        ? '互动已单独保存为可阅读记录和表格，见同一目录「05_直播互动」。'
        : eventCount ? '互动原始记录已保存；可阅读文件尚未确认，请查看 data 中的记录。'
        : '本次开启了互动记录，但未收到页面事件；不能按互动完整使用。';
      wrapper.append(note);
    }
  }

  if (task.state === "recording") {
    addProgress(wrapper, task);
  } else if (task.state === "checking" || task.state === "queued") {
    const preparing = document.createElement("p");
    preparing.textContent = "正在确认直播状态并准备录制……";
    wrapper.append(preparing);
  } else if (task.state === "stopping") {
    const stopping = document.createElement("p");
    stopping.textContent = "正在结束并保存，请稍候……";
    wrapper.append(stopping);
  }

  if (!ACTIVE_STATES.has(task.state)) {
    const videoCount = Math.max(0, Number(task.valid_mp4_count) || 0);
    const actualSeconds = Math.max(0, Number(task.actual_media_duration_seconds) || 0);
    if (videoCount > 0 || actualSeconds > 0) {
      const stats = document.createElement("div");
      stats.className = "result-stats";
      const video = document.createElement("span");
      video.textContent = `${videoCount} 个视频`;
      const duration = document.createElement("span");
      duration.textContent = `· 实际 ${formatHumanDuration(actualSeconds)}`;
      stats.append(video, duration);
      wrapper.append(stats);
    }
  }

  if (task.last_error) {
    const error = document.createElement("p");
    error.className = "muted";
    error.textContent = friendlyErrorMessage(task.last_error);
    wrapper.append(error);
  }

  if (ACTIVE_STATES.has(task.state)) {
    const stop = document.createElement("button");
    stop.type = "button";
    stop.className = "task-stop";
    stop.dataset.taskRole = 'stop';
    stop.textContent = task.state === "stopping" || stopRequests.has(task.task_id) ? "正在停止并保存……" : "提前结束并保存";
    stop.disabled = task.state === "stopping" || stopRequests.has(task.task_id);
    stop.addEventListener("click", () => stopTask(task.task_id));
    wrapper.append(stop);
  } else if (task.delivery) {
    const receipt = document.createElement('div');
    receipt.className = 'inline-delivery';
    receipt.dataset.deliveryId = task.delivery.id;
    receipt.dataset.taskRole = 'delivery';
    wrapper.append(receipt);
  } else if (task.output_dir) {
    const outputRow = document.createElement("div");
    outputRow.className = "output-row";
    const copy = document.createElement("button");
    copy.type = "button";
    copy.textContent = task.delivery ? '查看下载' : '复制保存位置';
    copy.addEventListener("click", () => task.delivery ? window.BrandbaiDownloads?.reveal(task.delivery.id) : copyOutputPath(task.output_dir));
    outputRow.append(copy);
    wrapper.append(outputRow);
  }
  return wrapper;
}

function renderTasks(tasks) {
  const previousActiveTask = lastTasks.find((task) => ACTIVE_STATES.has(task.state)) || null;
  const previousActiveWasOtherRoom = Boolean(
    previousActiveTask && canonicalRoomUrl(previousActiveTask.room_url) !== currentRoomUrl
  );
  lastTasks = Array.isArray(tasks) ? tasks : [];
  const currentActive = lastTasks.find(
    (task) => ACTIVE_STATES.has(task.state) && canonicalRoomUrl(task.room_url) === currentRoomUrl
  );
  const anyActive = lastTasks.find((task) => ACTIVE_STATES.has(task.state));
  if (currentActive) {
    void maintainCurrentRoomPage(currentActive);
  }
  if (previousActiveTask && !anyActive) {
    const finishedTask =
      lastTasks.find((task) => task.task_id === previousActiveTask.task_id) || previousActiveTask;
    if (previousActiveWasOtherRoom && currentRoomUrl) {
      const saved =
        Math.max(0, Number(finishedTask.valid_mp4_count) || 0) > 0 ||
        Math.max(0, Number(finishedTask.actual_media_duration_seconds) || 0) > 0;
      setMessage(
        saved
          ? "上一个直播间的录制已结束并保存，现在可以录制当前直播间。"
          : "上一个直播间的录制已结束，请查看结果；当前直播间现在可以开始录制。",
        !saved
      );
    } else {
      setMessage("");
    }
  }
  if (!lastTasks.length) {
    elements.taskList.replaceChildren();
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "还没有录制结果，完成后会在这里显示。";
    elements.taskList.append(empty);
    updateConfigurationSummary();
    updateStartAvailability();
    void refreshPagePlaybackState();
    return;
  }
  const currentLatest = lastTasks.find((task) => canonicalRoomUrl(task.room_url) === currentRoomUrl);
  const visibleTask = currentActive || anyActive || currentLatest || lastTasks[0];
  const nextCard = taskElement(visibleTask), existingCard = elements.taskList.firstElementChild;
  if (existingCard?.dataset.taskId === visibleTask.task_id && globalThis.BrandbaiTaskView) {
    globalThis.BrandbaiTaskView.patch(existingCard, nextCard);
  } else {
    elements.taskList.replaceChildren(nextCard);
  }
  window.BrandbaiDownloads?.renderInline?.();
  if (currentActive || anyActive) {
    const shown = currentActive || anyActive;
    elements.configSummary.textContent = shown.state === 'stopping' ? '正在保存已录制的内容' : '录制中 · 结束后自动下载资料包';
  } else {
    updateConfigurationSummary();
  }
  updateStartAvailability();
  void refreshPagePlaybackState();
}

function refreshTasks(options = {}) {
  // Polling, pairing and clicks share the result; "already running" is not a failed connection.
  if (!refreshTasksPromise) {
    refreshTasksPromise = refreshTasksOnce(options).finally(() => { refreshTasksPromise = null; });
  }
  return refreshTasksPromise;
}

async function refreshTasksOnce({silent = false} = {}) {
  if (!sessionToken) {
    return false;
  }
  refreshInFlight = true;
  updateStartAvailability();
  try {
    const payload = await api("/v1/tasks");
    renderTasks(payload.tasks || []);
    if (!silent) {
      setMessage("录制状态已更新。 ");
    }
    return true;
  } catch (error) {
    if (!silent) {
      setMessage(friendlyErrorMessage(error.message), true);
    }
    return false;
  } finally {
    refreshInFlight = false;
    updateStartAvailability();
  }
}

function recordingRequestFromForm() {
  if (!currentRoomUrl) {
    throw new Error("当前页面不是受支持的抖音直播间。 ");
  }
  const totalSeconds = recordingSeconds();
  const splitEnabled = elements.splitEnabled.checked;
  const collectorOptions = collectorOptionsFromForm();
  if (!splitEnabled && totalSeconds > 21600) {
    throw new Error("总录制超过 360 分钟时必须拆分成多个视频。 ");
  }
  return {
    roomUrl: currentRoomUrl,
    collectorOptions,
    taskBody: {
      room_url: currentRoomUrl,
      mode: "immediate",
      quality: elements.quality.value,
      max_runtime_seconds: totalSeconds,
      split_enabled: splitEnabled,
      segment_duration_seconds: segmentSeconds(totalSeconds),
      retain_original: true,
      full_read_check: false,
      sha256: false,
      collect_comments: collectorOptions.enabled && collectorOptions.comments,
      collect_product_cards: collectorOptions.enabled && collectorOptions.productCards,
      collect_room_metrics: collectorOptions.enabled && collectorOptions.roomMetrics,
      authorized_public_content: true
    }
  };
}

async function submitRecordingRequest(request) {
  startInFlight = true;
  updateStartAvailability();
  try {
    const payload = await api("/v1/tasks", {method: "POST", body: request.taskBody});
    await saveCollectorOptions(request.roomUrl, request.collectorOptions);
    const contentReady = await ensureCurrentTabContentScript(request.roomUrl);
    await notifyCurrentTabCollectorOptions(request.roomUrl, request.collectorOptions);
    await activateCurrentTabPlaybackGuard(request.roomUrl);
    const actionMessage = payload.reused
      ? "这个直播间正在录制，互动记录设置已更新。"
      : "录制已开始。";
    const pageSupportNote = contentReady
      ? ""
      : " 直播页面辅助功能暂未连接，请刷新直播页；录屏仍会正常保存。";
    setMessage(`${actionMessage} ${collectorSelectionLabel(request.collectorOptions)}。${pageSupportNote} `);
    await refreshTasks({silent: true});
    void refreshPagePlaybackState();
    return true;
  } catch (error) {
    setMessage(friendlyErrorMessage(error.message), true);
    return false;
  } finally {
    startInFlight = false;
    updateStartAvailability();
  }
}

async function resumePendingRecording() {
  if (!pendingRecordingRequest || !sessionToken || startInFlight) {
    return false;
  }
  if (!(await refreshStorageSettings())) {
    pendingRecordingRequest = null;
    setMessage("请先更新本机助手，再使用浏览器 ZIP 下载。", true);
    return false;
  }
  if (storageSettings.configured !== true) {
    pendingRecordingRequest = null;
    setMessage("浏览器下载尚未准备好，请更新助手后重试。 ");
    updateStartAvailability();
    return false;
  }
  const request = pendingRecordingRequest;
  pendingRecordingRequest = null;
  updateStartAvailability();
  return submitRecordingRequest(request);
}

async function startTask() {
  if (startInFlight || pendingRecordingRequest) {
    return;
  }
  try {
    if (activeTask()) {
      throw new Error("another live room is already recording");
    }
    const request = recordingRequestFromForm();
    pendingRecordingRequest = request;
    updateStartAvailability();
    setMessage(
      sessionToken
        ? "正在确认录制功能，准备好后会自动开始录制。 "
        : "正在启动录屏助手，准备好后会自动开始录制。 "
    );
    const connected = await connectService({retry: true});
    if (!connected && pendingRecordingRequest && !pairing) {
      if (getConnectionIssue()) {
        pendingRecordingRequest = null;
        setMessage(getConnectionIssue(), true);
        updateStartAvailability();
      } else {
        await beginAssistantLaunch();
      }
    }
  } catch (error) {
    pendingRecordingRequest = null;
    setMessage(friendlyErrorMessage(error.message), true);
    updateStartAvailability();
  }
}

async function stopTask(taskId) {
  if (stopRequests.has(taskId)) return;
  stopRequests.add(taskId);
  renderTasks(lastTasks);
  try {
    const payload = await api(`/v1/tasks/${encodeURIComponent(taskId)}/stop`, {method: "POST"});
    setMessage(payload.already_stopped ? "录制已经结束。" : "正在提前结束并保存，请稍候。 ");
    await refreshTasks({silent: true});
  } catch (error) {
    setMessage(friendlyErrorMessage(error.message), true);
  } finally {
    stopRequests.delete(taskId);
    renderTasks(lastTasks);
  }
}

elements.recordingPreset.addEventListener("change", () => {
  elements.customRecordingDuration.hidden = elements.recordingPreset.value !== "custom";
  updateConfigurationSummary();
});
elements.recordingUnit.addEventListener("change", () => {
  const minutes = elements.recordingUnit.value === "minutes";
  elements.recordingValue.min = minutes ? "1" : "60";
  elements.recordingValue.max = minutes ? "1440" : "86400";
  elements.recordingValue.value = minutes ? "30" : "1800";
  updateConfigurationSummary();
});
elements.splitEnabled.addEventListener("change", () => {
  elements.segmentOptions.hidden = !elements.splitEnabled.checked;
  updateConfigurationSummary();
});
elements.segmentPreset.addEventListener("change", () => {
  elements.customSegmentDuration.hidden = elements.segmentPreset.value !== "custom";
  updateConfigurationSummary();
});
elements.segmentUnit.addEventListener("change", () => {
  const minutes = elements.segmentUnit.value === "minutes";
  elements.segmentValue.min = minutes ? "1" : "60";
  elements.segmentValue.max = minutes ? "360" : "21600";
  elements.segmentValue.value = minutes ? "10" : "600";
  updateConfigurationSummary();
});
elements.quality.addEventListener("change", updateConfigurationSummary);
elements.recordingValue.addEventListener("input", updateConfigurationSummary);
elements.segmentValue.addEventListener("input", updateConfigurationSummary);
elements.collectPageData.addEventListener("change", handleCollectorOptionChange);
elements.collectComments.addEventListener("change", handleCollectorOptionChange);
elements.collectProductCards.addEventListener("change", handleCollectorOptionChange);
elements.collectRoomMetrics.addEventListener("change", handleCollectorOptionChange);
elements.launchAssistant.addEventListener("click", launchAssistant);
elements.pair.addEventListener("click", () => connectService({retry: true}));
elements.start.addEventListener("click", startTask);
elements.stopRecording?.addEventListener('click', () => {
  const task = activeTask();
  if (task) void stopTask(task.task_id);
});
elements.useDefaultLocation.addEventListener("click", () => updateOutputRoot("use_default"));
elements.chooseLocation.addEventListener("click", () => updateOutputRoot("choose"));
elements.allowRoomAccess.addEventListener("click", requestRoomAccess);
elements.retryRoomAccess.addEventListener("click", scheduleCurrentTabRead);

chrome.permissions?.onAdded?.addListener(scheduleCurrentTabRead);
chrome.permissions?.onRemoved?.addListener(scheduleCurrentTabRead);
window.addEventListener("focus", scheduleCurrentTabRead);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") scheduleCurrentTabRead();
});

chrome.tabs.onActivated.addListener(scheduleCurrentTabRead);
chrome.tabs.onUpdated.addListener((_tabId, changeInfo, tab) => {
  if (tab.active && (changeInfo.url || changeInfo.title || changeInfo.status)) {
    scheduleCurrentTabRead();
  }
});

setInterval(() => {
  if (lastTasks.some((task) => task.state === "recording")) {
    renderTasks(lastTasks);
  }
}, 1000);

setInterval(async () => {
  if (sessionToken) {
    const refreshed = await refreshTasks({silent: true});
    if (!refreshed) {
      await connectService();
    }
  } else if (!pairing) {
    await connectService();
  }
}, AUTO_REFRESH_MS);

updateConfigurationSummary();
Promise.all([readCurrentTab(), connectService()]).catch((error) =>
  setMessage(friendlyErrorMessage(error.message), true)
);
