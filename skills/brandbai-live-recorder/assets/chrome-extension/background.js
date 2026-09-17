"use strict";

const SERVICE_BASES = Object.freeze([
  "http://127.0.0.1:8765",
  "http://127.0.0.1:18765",
  "http://127.0.0.1:28765"
]);
const SERVICE_HEALTH_TIMEOUT_MS = 900;
const SERVICE_REQUEST_TIMEOUT_MS = 6000;
const EXTENSION_CLIENT_ID = chrome.runtime.id;
const SESSION_KEY = "brandbaiLiveRecorderSession";
const COLLECTOR_OPTIONS_KEY = "brandbaiLiveRecorderCollectorOptions";
const ACTIVE_COLLECTORS_KEY = "brandbaiLiveRecorderActiveCollectors";
const BACKGROUND_CLOSE_SEQUENCE = 1000000000;
const TAB_CLOSE_FALLBACK_DELAY_MS = 250;
const ACTIVE_STATES = new Set(["queued", "checking", "recording", "stopping"]);
const REVIEW_LEASE_FIELDS = Object.freeze(['documentToken','contextKey','generation','sourceWorkId','sourceSurfaceInstance','productPanelInstanceId','reviewSurfaceInstanceId','filterKey']);
function sameReviewLease(left, right) {
  // chrome.storage round trips must not turn object key order into identity.
  return Boolean(left && right && Object.keys(left).length === REVIEW_LEASE_FIELDS.length
    && Object.keys(right).length === REVIEW_LEASE_FIELDS.length
    && REVIEW_LEASE_FIELDS.every(key => typeof left[key] === 'string' && left[key].length > 0 && left[key] === right[key]));
}

let pairingPromise = null;
let activeServiceBase = null;
let productSnapshots = false;
let productCatalog = false;

async function enableActionSidePanel() {
  if (!chrome.sidePanel?.setPanelBehavior) {
    return;
  }
  try {
    await chrome.sidePanel.setPanelBehavior({openPanelOnActionClick: true});
  } catch (_error) {
    // Chrome may reject while the extension is still initializing; retry on the next worker start.
  }
}

chrome.runtime.onInstalled.addListener(() => {
  void enableActionSidePanel();
});

chrome.runtime.onStartup.addListener(() => {
  void enableActionSidePanel();
});

void enableActionSidePanel();

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

async function storedSession() {
  const stored = await chrome.storage.session.get(SESSION_KEY);
  const session = stored?.[SESSION_KEY];
  if (
    session &&
    session.clientId === EXTENSION_CLIENT_ID &&
    SERVICE_BASES.includes(session.serviceBase) &&
    typeof session.token === "string" &&
    session.token.length >= 32 &&
    Number.isFinite(session.expiresAt) &&
    Date.now() < session.expiresAt
  ) {
    activeServiceBase = session.serviceBase;
    return session;
  }
  await chrome.storage.session.remove(SESSION_KEY);
  return null;
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

async function discoverServiceBase() {
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
        return serviceBase;
      }
    } catch (_error) {
      // Offline, occupied, or unresponsive candidates are skipped automatically.
    }
  }
  throw new Error("本机录屏服务尚未启动");
}

async function pairService() {
  if (pairingPromise) {
    return pairingPromise;
  }
  pairingPromise = (async () => {
    const serviceBase = await discoverServiceBase();
    const response = await fetchWithTimeout(
      `${serviceBase}/v1/pair`,
      {
        method: "POST",
        headers: {
          "Accept": "application/json",
          "X-BrandBAI-Pair": "extension-popup",
          "X-BrandBAI-Client": EXTENSION_CLIENT_ID
        },
        cache: "no-store"
      },
      SERVICE_REQUEST_TIMEOUT_MS
    );
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || typeof payload.session_token !== "string") {
      throw new Error(payload.message || "本机录屏服务自动连接失败");
    }
    const seconds = Number(payload.expires_in_seconds || 900);
    const session = {
      token: payload.session_token,
      expiresAt: Date.now() + Math.max(60, seconds) * 1000,
      clientId: EXTENSION_CLIENT_ID,
      serviceBase,
      productSnapshots, productCatalog
    };
    await chrome.storage.session.set({[SESSION_KEY]: session});
    return session;
  })();
  try {
    return await pairingPromise;
  } finally {
    pairingPromise = null;
  }
}

async function api(path, {method = "GET", body = null, retry = true} = {}) {
  const session = (await storedSession()) || (await pairService());
  activeServiceBase = session.serviceBase;
  const headers = {
    "Accept": "application/json",
    "X-BrandBAI-Token": session.token,
    "X-BrandBAI-Client": EXTENSION_CLIENT_ID,
    "X-BrandBAI-Delivery": "browser-zip"
  };
  if (body !== null) {
    headers["Content-Type"] = "application/json";
  }
  let response;
  try {
    response = await fetchWithTimeout(
      `${activeServiceBase}${path}`,
      {
        method,
        headers,
        body: body === null ? undefined : JSON.stringify(body),
        cache: "no-store"
      },
      SERVICE_REQUEST_TIMEOUT_MS
    );
  } catch (error) {
    if (retry) {
      activeServiceBase = null;
      await chrome.storage.session.remove(SESSION_KEY);
      return api(path, {method, body, retry: false});
    }
    throw error;
  }
  const payload = await response.json().catch(() => ({}));
  if ((!response.ok || response.status === 401) && retry) {
    activeServiceBase = null;
    await chrome.storage.session.remove(SESSION_KEY);
    return api(path, {method, body, retry: false});
  }
  if (!response.ok) {
    throw new Error(payload.message || `本机服务返回 ${response.status}`);
  }
  await globalThis.BrandbaiDelivery?.observe(payload, method, path);
  return payload;
}

async function matchingTask(roomUrl, {allowRecentFinal = false} = {}) {
  const canonical = canonicalRoomUrl(roomUrl);
  if (!canonical) {
    return null;
  }
  const payload = await api("/v1/tasks");
  const matching = (payload.tasks || []).filter(
    (task) => canonicalRoomUrl(task.room_url) === canonical
  );
  return matching.find((task) => ACTIVE_STATES.has(task.state)) ||
    (allowRecentFinal ? matching[0] || null : null);
}

function senderRoom(sender) {
  return canonicalRoomUrl(sender?.url || sender?.tab?.url || "");
}

async function collectorOptionsFor(roomUrl, task = null) {
  const stored = await chrome.storage.session.get(COLLECTOR_OPTIONS_KEY);
  const saved = stored?.[COLLECTOR_OPTIONS_KEY]?.[roomUrl];
  const comments = saved
    ? saved.comments === true
    : task?.collect_comments === true;
  const productCards = saved
    ? saved.productCards === true
    : task?.collect_product_cards === true;
  const roomMetrics = saved
    ? saved.roomMetrics === true
    : task?.collect_room_metrics === true;
  return {
    enabled: saved ? saved.enabled === true && (comments || productCards || roomMetrics) :
      comments || productCards || roomMetrics,
    comments,
    productCards,
    roomMetrics
  };
}

async function activeCollectors() {
  const stored = await chrome.storage.session.get(ACTIVE_COLLECTORS_KEY);
  const value = stored?.[ACTIVE_COLLECTORS_KEY];
  return value && typeof value === "object" ? value : {};
}

async function rememberActiveCollector(tabId, roomUrl, collectorSessionId, taskId, events) {
  if (!Number.isInteger(tabId) || typeof collectorSessionId !== "string" || !taskId) {
    return;
  }
  const statusEvents = events.filter(
    (item) => item?.event_type === "collector_status" && item?.payload
  );
  if (!statusEvents.length) {
    return;
  }
  const latestStatus = statusEvents[statusEvents.length - 1];
  const collectors = await activeCollectors();
  const key = String(tabId);
  if (latestStatus.payload.status === "stopped") {
    delete collectors[key];
  } else {
    collectors[key] = {
      roomUrl,
      collectorSessionId,
      taskId,
      collectComments: latestStatus.payload.collect_comments === true,
      collectProductCards: latestStatus.payload.collect_product_cards === true,
      collectRoomMetrics: latestStatus.payload.collect_room_metrics === true
    };
  }
  await chrome.storage.session.set({[ACTIVE_COLLECTORS_KEY]: collectors});
}

async function takeActiveCollector(tabId) {
  const collectors = await activeCollectors();
  const key = String(tabId);
  const state = collectors[key] || null;
  if (state) {
    delete collectors[key];
    await chrome.storage.session.set({[ACTIVE_COLLECTORS_KEY]: collectors});
  }
  return state;
}

function waitForCloseFallback() {
  return new Promise((resolve) => setTimeout(resolve, TAB_CLOSE_FALLBACK_DELAY_MS));
}

async function recordClosedTab(tabId, observedAtEpochMs) {
  await waitForCloseFallback();
  const state = await takeActiveCollector(tabId);
  if (!state) {
    return;
  }
  try {
    await api(`/v1/tasks/${encodeURIComponent(state.taskId)}/visible-events`, {
      method: "POST",
      body: {
        collector_session_id: state.collectorSessionId,
        events: [{
          sequence: BACKGROUND_CLOSE_SEQUENCE,
          event_type: "collector_status",
          observed_at_epoch_ms: observedAtEpochMs,
          room_url: state.roomUrl,
          payload: {
            status: "stopped",
            reason: "page_closed_or_navigated",
            collect_comments: state.collectComments,
            collect_product_cards: state.collectProductCards,
            collect_room_metrics: state.collectRoomMetrics
          }
        }]
      }
    });
  } catch (_error) {
    // Closing a tab is best-effort evidence; recording remains independent of Chrome.
  }
}

async function handleMessage(message, sender) {
  const requestedRoom = canonicalRoomUrl(message?.roomUrl || "");
  const actualRoom = senderRoom(sender);
  if (!requestedRoom || !actualRoom || requestedRoom !== actualRoom) {
    return {status: "rejected", active: false, reason: "room_mismatch"};
  }
  if(message.type==='brandbai-review-bridge') {
    if(sender.id!==chrome.runtime.id || !Number.isInteger(sender.tab?.id) || !sender.documentId) return {ok:false};
    const key='brandbai.reviewBindings', stored=await chrome.storage.session.get(key), bindings=stored[key]||{};
    if(message.action==='start') {
      const body=message.body;
      if(body?.room_url!==requestedRoom || !/^[a-f0-9-]{36}$/.test(body?.request_id||'')) return {ok:false};
      const old=bindings[body.request_id];
      if(old && (old.tab!==sender.tab.id || old.document!==sender.documentId)) return {ok:false};
      if(body.resume_from) {
        const parent=bindings[body.resume_from];
        if(!parent || parent.tab!==sender.tab.id || parent.document!==sender.documentId
          || parent.room!==requestedRoom || !sameReviewLease(parent.lease,body.lease)) return {ok:false};
      }
      if(Object.keys(bindings).length>=100 && !old) return {ok:false};
      const response=await api('/v1/product-reviews',{method:'POST',body});
      bindings[body.request_id]={tab:sender.tab.id,document:sender.documentId,room:requestedRoom,lease:body.lease};
      await chrome.storage.session.set({[key]:bindings});return response;
    }
    const binding=bindings[message.request_id];
    if(message.action!=='event' || !binding || binding.tab!==sender.tab.id || binding.document!==sender.documentId
      || binding.room!==requestedRoom || !sameReviewLease(binding.lease,message.body?.lease)) return {ok:false};
    return await api(`/v1/product-reviews/${message.request_id}/events`,{method:'POST',body:message.body});
  }
  if (message.type === "brandbai-collector-probe") {
    const task = await matchingTask(requestedRoom);
    const collectorOptions = await collectorOptionsFor(requestedRoom, task);
    return {
      status: "ok",
      active: Boolean(task),
      taskId: task?.task_id || null,
      taskStartedAt: task?.started_at || null,
      productSnapshots: (await storedSession())?.productSnapshots === true,
      productCatalog: (await storedSession())?.productCatalog === true,
      collectorOptions
    };
  }
  if (message.type !== "brandbai-visible-events") {
    return {status: "ignored", active: false};
  }
  const events = Array.isArray(message.events) ? message.events : [];
  if (!events.length || events.length > 50) {
    return {status: "rejected", active: false, reason: "invalid_batch_size"};
  }
  const allowRecentFinal = events.some(
    (event) => event?.event_type === "collector_status" && event?.payload?.status === "stopped"
  );
  const task = await matchingTask(requestedRoom, {allowRecentFinal});
  if (!task) {
    return {status: "inactive", active: false};
  }
  if (message.taskRun && message.taskRun !== `${task.task_id}:${task.started_at}`) {
    return {status: "rejected", active: false, reason: "recording_run_changed"};
  }
  const result = await api(`/v1/tasks/${encodeURIComponent(task.task_id)}/visible-events`, {
    method: "POST",
    body: {
      collector_session_id: message.collectorSessionId,
      events
    }
  });
  await rememberActiveCollector(
    sender?.tab?.id,
    requestedRoom,
    message.collectorSessionId,
    task.task_id,
    events
  );
  return {
    status: "accepted",
    active: ACTIVE_STATES.has(task.state),
    taskId: task.task_id,
    accepted: result.accepted,
    duplicates: result.duplicates
  };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === 'brandbai-delivery') return false;
  handleMessage(message, sender)
    .then(sendResponse)
    .catch(() => sendResponse({status: "offline", active: false}));
  return true;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  void recordClosedTab(tabId, Date.now());
});

if (typeof importScripts === 'function') importScripts('browser-delivery.js');
