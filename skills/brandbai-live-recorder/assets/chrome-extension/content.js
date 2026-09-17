"use strict";

// Injection can race with another sidebar probe. Keep one collector/listener
// per extension context; reconnecting must not reset a recording or identity.
(() => {
if (globalThis.__brandbaiLiveContent?.active()) return;

const COMMENT_SELECTOR = ".webcast-chatroom___content-with-emoji-text";
const COMMENT_WRAPPER_SELECTOR = ".webcast-chatroom___item-wrapper";
const COMMENT_RESCAN_DELAY_MS = 50;
const CART_SELECTOR = '[data-e2e="yellowCart-container"]';
const PROBE_INTERVAL_MS = 3000;
const PRODUCT_SCAN_INTERVAL_MS = 1000;
const ROOM_SNAPSHOT_INTERVAL_MS = 15000;
const PLAYBACK_STATE_SCAN_INTERVAL_MS = 1000;
const PLAYBACK_RECOVERY_VERIFY_MS = 1500;
const MAX_PLAYBACK_RECOVERY_ATTEMPTS = 2;
const ENERGY_SAVER_PAUSE_MARKER = "长时间无操作，已暂停播放";
const CONTINUE_PLAYBACK_LABEL = "继续播放";
const ACCOUNT_CONFLICT_MARKER = "账号已在其他地方进入直播间";
const COMMENT_STALE_MS = 180000;
const PLAYBACK_CONTROL_CANDIDATE_SELECTOR = 'button, [role="button"], a, div, span';
const DEFAULT_COLLECTOR_OPTIONS = Object.freeze({
  enabled: false,
  comments: false,
  productCards: false,
  roomMetrics: false
});

let collecting = false;
let accountConflict = false;
let commentsStale = false;
let lastCommentObservedAt = Date.now();
let collectorConnectionLost = false;
let collectorTaskRun = null;
let droppedPendingEvents = 0;
let playbackGuardActive = false;
let collectorOptions = {...DEFAULT_COLLECTOR_OPTIONS};
let collectorSessionId = null;
let sequence = 0;
let seenCommentSignatures = new WeakMap();
let commentRescanTimer = null;
let pendingEvents = [];
let sending = false;
let productVisible = false;
let productSeen = false;
let currentProductSignature = null;
let missingProductScans = 0;
let playbackPausedByEnergySaver = null;
let playbackRecoveryAttempts = 0;
let playbackRecoveryTimer = null;
let playbackScanScheduled = false;
let runtimeContextInvalidated = false;
const runtimeIntervals = [];
let pageObserver = null;
let productCollector = null;
let productSnapshotSupport = false;
let productCatalogSupport = false;
let productPreviewReader = null;
let pageMaterials = null;
let pageReviews = null;
function productRendered(node) {
  if(!node?.isConnected||node.closest('[hidden],[inert],[aria-hidden="true"]'))return false;
  for(let n=node;n&&n!==document;n=n.parentElement){const s=getComputedStyle(n);if(s.display==='none'||s.visibility==='hidden')return false;}
  return node.getBoundingClientRect().width>0;
}
function getPageReviews() {
  if(!pageReviews && globalThis.BrandbaiLiveReviews && globalThis.BrandbaiDouyinCommerceDom) {
    const rendered=n=>Boolean(n?.isConnected && !n.closest('[hidden],[inert],[aria-hidden="true"]')
      && n.getBoundingClientRect().width>0 && getComputedStyle(n).display!=='none' && getComputedStyle(n).visibility!=='hidden');
    pageReviews=globalThis.BrandbaiLiveReviews.create({document,window,roomUrl:()=>canonicalRoomUrl(location.href),isVisible,isRendered:rendered,
      inspector:globalThis.BrandbaiDouyinCommerceDom.createInspector({document,window,isVisible,isRendered:rendered}),
      getProductContext:()=>getProductPreviewReader()?.identityCurrent(),
      send:m=>chrome.runtime.sendMessage(m),materialBusy:()=>pageMaterials?.status().state==='collecting'});
  }
  return pageReviews;
}
let materialSurface = null;
let popupObservationPaused = false;
function updatePopupObservation(covered) {
  if(!collecting || !collectorOptions.productCards) { popupObservationPaused=false; return; }
  if(covered===popupObservationPaused)return;
  popupObservationPaused=covered;
  recordPlaybackCollectorStatus(covered?'popup_observation_paused':'popup_observation_resumed',
    covered?'product_panel_obscures_popup':'product_panel_closed');
}
function getProductPreviewReader() {
  if (!productPreviewReader && globalThis.BrandbaiLiveProducts && globalThis.BrandbaiDouyinCommerceDom) {
    productPreviewReader = globalThis.BrandbaiLiveProducts.createCollector({
      document, isVisible, roomUrl: () => canonicalRoomUrl(location.href), emit() {},
      newId: () => crypto.randomUUID(),
      inspector: globalThis.BrandbaiDouyinCommerceDom.createInspector({document, window, isVisible, isRendered: productRendered})
    });
  }
  return productPreviewReader;
}
function getPageMaterials() {
  if (!pageMaterials && globalThis.BrandbaiPageMaterials && getProductPreviewReader()) {
    const isRendered = node => {
      if (!node?.isConnected || node.closest('[hidden],[inert],[aria-hidden="true"]')) return false;
      for (let n=node; n && n!==document; n=n.parentElement) {
        const style=getComputedStyle(n);
        if(style.display==='none' || style.visibility==='hidden') return false;
      }
      return node.getBoundingClientRect().width>0;
    };
    const inspector=globalThis.BrandbaiDouyinCommerceDom.createInspector({document,window,isVisible,isRendered});
    pageMaterials=globalThis.BrandbaiPageMaterials.create({document,window,inspector,
      reader:productPreviewReader, roomUrl:()=>canonicalRoomUrl(location.href), publicUrl:globalThis.BrandbaiLiveProducts.publicUrl});
  }
  return pageMaterials;
}
function materialCollectionOwnsSurface() {
  if(pageReviews?.busy()) return true;
  if(pageMaterials?.status().state==='collecting') return true;
  // Keep suppressing the automatically opened surface after capture ends.
  if(materialSurface && (materialSurface.kind==='product'
    ? getProductPreviewReader()?.previewCurrent().status==='recognized'
    : getProductPreviewReader()?.catalogSurface())) return true;
  materialSurface=null;
  return false;
}

function getProductCollector() {
  if (!productSnapshotSupport) return null;
  if (!productCollector && globalThis.BrandbaiLiveProducts && globalThis.BrandbaiDouyinCommerceDom) {
    productCollector = globalThis.BrandbaiLiveProducts.createCollector({
      document, isVisible,
      catalogEnabled: () => productCatalogSupport,
      inspector: globalThis.BrandbaiDouyinCommerceDom.createInspector({document, window,
        isVisible, isRendered: isVisible}),
      roomUrl: () => canonicalRoomUrl(location.href),
      emit: (kind, payload) => enqueue(event(kind, payload)),
      newId: () => `card-${crypto.randomUUID()}`
    });
  }
  return productCollector;
}

window.addEventListener("click", (clickEvent) => {
  if (collecting && collectorOptions.productCards && !runtimeContextInvalidated && !materialCollectionOwnsSurface()) {
    getProductCollector()?.clicked(clickEvent);
  }
}, true);

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

function cleanText(value, limit) {
  const text = String(value || "")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit);
  if (!text || /https?:\/\//i.test(text)) {
    return null;
  }
  return text;
}

function maskVisibleNickname(value) {
  const name = cleanText(String(value || "").replace(/[：:]\s*$/, ""), 80);
  if (!name) {
    return null;
  }
  if (name.includes("*")) {
    return name;
  }
  return `${Array.from(name)[0] || "用"}***`;
}

function isVisible(element) {
  if (!(element instanceof Element)) {
    return false;
  }
  const style = getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  return style.display !== "none" && style.visibility !== "hidden" &&
    rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < innerHeight;
}

function findEnergySaverContinueControl() {
  const controls = document.querySelectorAll(PLAYBACK_CONTROL_CANDIDATE_SELECTOR);
  for (const control of controls) {
    if (!isVisible(control)) {
      continue;
    }
    const label = cleanText(control.textContent, 80);
    if (label !== CONTINUE_PLAYBACK_LABEL) {
      continue;
    }
    const tagName = String(control.tagName || "").toLowerCase();
    const role = String(control.getAttribute?.("role") || "").toLowerCase();
    const cursor = String(getComputedStyle(control).cursor || "").toLowerCase();
    if (tagName !== "button" && tagName !== "a" && role !== "button" && cursor !== "pointer") {
      continue;
    }
    let current = control;
    for (let depth = 0; current && depth < 7; depth++, current = current.parentElement) {
      if (String(current.textContent || "").includes(ENERGY_SAVER_PAUSE_MARKER)) {
        return control;
      }
    }
  }
  return null;
}

function detectEnergySaverPause() {
  return Boolean(findEnergySaverContinueControl());
}

function detectAccountConflict() {
  for (const control of document.querySelectorAll(PLAYBACK_CONTROL_CANDIDATE_SELECTOR)) {
    if (!isVisible(control) || cleanText(control.textContent, 80) !== '继续看播' ||
        control.closest?.(COMMENT_WRAPPER_SELECTOR)) continue;
    let node = control.parentElement;
    for (let depth = 0; node && depth < 6 && node !== document.body; depth++, node = node.parentElement) {
      if (String(node.textContent || '').length < 1600 && String(node.textContent || '').includes(ACCOUNT_CONFLICT_MARKER)) return true;
    }
  }
  return false;
}

function scanInteractionHealth() {
  if (!collecting) return;
  const blocked = detectAccountConflict();
  if (blocked !== accountConflict) {
    accountConflict = blocked;
    recordPlaybackCollectorStatus(blocked ? 'interaction_interrupted' : 'interaction_resumed',
      blocked ? 'account_entered_another_live_room' : 'account_conflict_cleared_waiting_new_comments');
  }
  if (!blocked && collectorOptions.comments && !commentsStale && Date.now() - lastCommentObservedAt >= COMMENT_STALE_MS) {
    commentsStale = true;
    recordPlaybackCollectorStatus('comment_stream_stale', 'no_new_visible_comments_180s_not_proof_of_zero_comments');
  }
}

function clearPlaybackRecoveryTimer() {
  if (playbackRecoveryTimer !== null) {
    clearTimeout(playbackRecoveryTimer);
    playbackRecoveryTimer = null;
  }
}

function clearCommentRescanTimer() {
  if (commentRescanTimer !== null) {
    clearTimeout(commentRescanTimer);
    commentRescanTimer = null;
  }
}

function recordPlaybackCollectorStatus(status, reason) {
  if (!collecting) {
    return;
  }
  enqueue(event("collector_status", collectorStatusPayload(status, reason)));
}

function attemptEnergySaverRecovery(continueControl = findEnergySaverContinueControl()) {
  if (!playbackGuardActive || !continueControl || playbackRecoveryTimer !== null ||
      playbackRecoveryAttempts >= MAX_PLAYBACK_RECOVERY_ATTEMPTS) {
    return false;
  }
  playbackRecoveryAttempts += 1;
  recordPlaybackCollectorStatus(
    "playback_resume_requested",
    `platform_energy_saver_attempt_${playbackRecoveryAttempts}`
  );
  try {
    continueControl.click();
  } catch (_error) {
    // The verification timer records one bounded retry or a stable failure.
  }
  playbackRecoveryTimer = setTimeout(() => {
    playbackRecoveryTimer = null;
    const stillPaused = scanPlaybackState({attemptRecovery: false});
    if (!stillPaused) {
      return;
    }
    if (playbackRecoveryAttempts < MAX_PLAYBACK_RECOVERY_ATTEMPTS) {
      attemptEnergySaverRecovery();
      return;
    }
    recordPlaybackCollectorStatus(
      "playback_resume_failed",
      "platform_energy_saver_continue_no_effect"
    );
  }, PLAYBACK_RECOVERY_VERIFY_MS);
  return true;
}

function scanPlaybackState({forceCollectorEvent = false, attemptRecovery = true} = {}) {
  scanInteractionHealth();
  const continueControl = findEnergySaverContinueControl();
  const paused = Boolean(continueControl);
  const changed = playbackPausedByEnergySaver !== null && paused !== playbackPausedByEnergySaver;
  playbackPausedByEnergySaver = paused;
  if (!paused) {
    playbackRecoveryAttempts = 0;
    clearPlaybackRecoveryTimer();
  }
  if (changed || (forceCollectorEvent && paused)) {
    recordPlaybackCollectorStatus(
      paused ? "playback_paused" : "playback_resumed",
      paused ? "platform_energy_saver" : "platform_energy_saver_cleared"
    );
  }
  if (paused && attemptRecovery && playbackGuardActive && !accountConflict) {
    attemptEnergySaverRecovery(continueControl);
  }
  return paused;
}

function schedulePlaybackStateScan() {
  if (!playbackGuardActive || playbackScanScheduled) {
    return;
  }
  playbackScanScheduled = true;
  queueMicrotask(() => {
    playbackScanScheduled = false;
    scanPlaybackState();
  });
}

function setPlaybackGuardActive(active) {
  const next = active === true;
  playbackGuardActive = next;
  if (!next) {
    playbackPausedByEnergySaver = null;
    playbackRecoveryAttempts = 0;
    clearPlaybackRecoveryTimer();
    return;
  }
  scanPlaybackState();
}

function mutationContainsEnergySaverSignal(mutations) {
  for (const mutation of mutations) {
    for (const node of mutation.addedNodes) {
      if (!(node instanceof Element)) {
        continue;
      }
      const text = String(node.textContent || "");
      if (text.includes(ENERGY_SAVER_PAUSE_MARKER) ||
          text.includes(CONTINUE_PLAYBACK_LABEL)) {
        return true;
      }
    }
  }
  return false;
}

function event(eventType, payload) {
  return {
    sequence: sequence++,
    event_type: eventType,
    observed_at_epoch_ms: Date.now(),
    room_url: canonicalRoomUrl(location.href),
    payload
  };
}

function normalizeCollectorOptions(value) {
  const comments = value?.comments === true;
  const productCards = value?.productCards === true;
  const roomMetrics = value?.roomMetrics === true;
  return {
    enabled: value?.enabled === true && (comments || productCards || roomMetrics),
    comments,
    productCards,
    roomMetrics
  };
}

function sameCollectorOptions(left, right) {
  return left.enabled === right.enabled &&
    left.comments === right.comments &&
    left.productCards === right.productCards &&
    left.roomMetrics === right.roomMetrics;
}

function collectorStatusPayload(status, reason = null) {
  return {
    status,
    reason,
    collect_comments: collectorOptions.enabled && collectorOptions.comments,
    collect_product_cards: collectorOptions.enabled && collectorOptions.productCards,
    collect_room_metrics: collectorOptions.enabled && collectorOptions.roomMetrics
  };
}

function stopInvalidatedRuntime() {
  if (runtimeContextInvalidated) {
    return;
  }
  runtimeContextInvalidated = true;
  pageMaterials?.stop();
  for (const intervalId of runtimeIntervals) {
    clearInterval(intervalId);
  }
  clearPlaybackRecoveryTimer();
  clearCommentRescanTimer();
  playbackGuardActive = false;
  collecting = false;
  pendingEvents = [];
  pageObserver?.disconnect();
}

function sendRuntimeMessage(message) {
  return new Promise((resolve) => {
    if (runtimeContextInvalidated) {
      resolve({status: "offline", active: false});
      return;
    }
    try {
      chrome.runtime.sendMessage(message, (response) => {
        try {
          if (chrome.runtime.lastError) {
            resolve({status: "offline", active: false});
            return;
          }
        } catch (_error) {
          stopInvalidatedRuntime();
          resolve({status: "offline", active: false});
          return;
        }
        resolve(response || {status: "offline", active: false});
      });
    } catch (_error) {
      stopInvalidatedRuntime();
      resolve({status: "offline", active: false});
    }
  });
}

function enqueue(item) {
  if (!item.room_url) {
    return;
  }
  pendingEvents.push(item);
  if (pendingEvents.length > 300) {
    droppedPendingEvents += pendingEvents.length - 300;
    pendingEvents = pendingEvents.slice(-300);
  }
  void flush();
}

async function flush() {
  if (sending || !collectorSessionId || !pendingEvents.length) {
    return;
  }
  sending = true;
  // Keep rich product snapshots and dense comment batches below the service
  // request ceiling (UTF-8 <= 3 bytes per UTF-16 code unit, plus envelope).
  const batch = [];
  let estimatedBytes = 2000;
  while (pendingEvents.length && batch.length < 50) {
    const bytes = JSON.stringify(pendingEvents[0]).length * 3;
    if (batch.length && estimatedBytes + bytes > 60000) break;
    batch.push(pendingEvents.shift());
    estimatedBytes += bytes;
  }
  try {
    const response = await sendRuntimeMessage({
      type: "brandbai-visible-events",
      roomUrl: canonicalRoomUrl(location.href),
      collectorSessionId,
      taskRun: collectorTaskRun,
      events: batch
    });
    if (response.status === "offline") {
      const requeued = batch.concat(pendingEvents);
      droppedPendingEvents += Math.max(0, requeued.length - 300);
      pendingEvents = requeued.slice(-300);
    }
  } finally {
    sending = false;
    if (pendingEvents.length) {
      setTimeout(() => void flush(), 500);
    }
  }
}

function commentParts(content) {
  if (!isVisible(content)) {
    return null;
  }
  const wrapper = content.closest(COMMENT_WRAPPER_SELECTOR) || content.parentElement?.parentElement;
  if (!wrapper) {
    return null;
  }
  const nicknameElement = [...wrapper.querySelectorAll("span")].find((element) => {
    const text = (element.textContent || "").trim();
    return element !== content && /[：:]$/.test(text) && text.length <= 90;
  });
  const maskedUser = maskVisibleNickname(nicknameElement?.textContent || "");
  const text = cleanText(content.textContent, 500);
  return maskedUser && text ? {maskedUser, text} : null;
}

function captureComment(content, observationKind) {
  if (!collecting || accountConflict || !collectorOptions.comments ||
      !(content instanceof Element)) {
    return;
  }
  const parts = commentParts(content);
  if (!parts) {
    return;
  }
  const signature = `${parts.maskedUser}\u241f${parts.text}`;
  if (seenCommentSignatures.get(content) === signature) {
    return;
  }
  seenCommentSignatures.set(content, signature);
  lastCommentObservedAt = Date.now();
  if (commentsStale) {
    commentsStale = false;
    recordPlaybackCollectorStatus('comment_stream_resumed', 'new_visible_comment_observed');
  }
  enqueue(event("comment_visible", {
    masked_user: parts.maskedUser,
    text: parts.text,
    observation_kind: observationKind
  }));
}

function scanExistingComments(observationKind) {
  if (!collecting || !collectorOptions.comments) {
    return;
  }
  for (const content of document.querySelectorAll(COMMENT_SELECTOR)) {
    captureComment(content, observationKind);
  }
}

function commentContentForNode(node) {
  const element = node instanceof Element ? node : node?.parentElement;
  if (!(element instanceof Element)) {
    return null;
  }
  if (element.matches?.(COMMENT_SELECTOR)) {
    return element;
  }
  const containingContent = element.closest?.(COMMENT_SELECTOR);
  if (containingContent) {
    return containingContent;
  }
  const wrapper = element.matches?.(COMMENT_WRAPPER_SELECTOR)
    ? element
    : element.closest?.(COMMENT_WRAPPER_SELECTOR);
  return wrapper?.querySelector?.(COMMENT_SELECTOR) ||
    element.querySelector?.(COMMENT_SELECTOR) || null;
}

function mutationContainsCommentSignal(mutations) {
  for (const mutation of mutations) {
    if (commentContentForNode(mutation.target)) {
      return true;
    }
    for (const node of mutation.addedNodes || []) {
      if (commentContentForNode(node)) {
        return true;
      }
    }
  }
  return false;
}

function scheduleCommentScan() {
  if (!collecting || !collectorOptions.comments || commentRescanTimer !== null) {
    return;
  }
  commentRescanTimer = setTimeout(() => {
    commentRescanTimer = null;
    scanExistingComments("new_visible");
  }, COMMENT_RESCAN_DELAY_MS);
}

function findProductCard() {
  const cart = document.querySelector(CART_SELECTOR);
  if (!cart || !isVisible(cart)) {
    return null;
  }
  const cartRect = cart.getBoundingClientRect();
  let best = null;
  for (const priceElement of document.querySelectorAll("span,div")) {
    if (!isVisible(priceElement)) {
      continue;
    }
    const priceText = cleanText(priceElement.textContent, 80);
    if (!priceText || !/^[¥￥]\s*\d[\d,.]*/.test(priceText)) {
      continue;
    }
    let current = priceElement;
    for (let depth = 0; current && depth < 8; depth++, current = current.parentElement) {
      const rect = current.getBoundingClientRect();
      const text = cleanText(current.textContent, 450);
      const aligned = Math.abs(rect.x - cartRect.x) <= 48 &&
        Math.abs(rect.width - cartRect.width) <= 96;
      const aboveCart = rect.top < cartRect.top && rect.bottom <= cartRect.top + 12;
      const plausibleSize = rect.height >= 60 && rect.height <= 520;
      if (!aligned || !aboveCart || !plausibleSize || !text || text.length <= priceText.length + 2) {
        continue;
      }
      if (!best || rect.height > best.rect.height) {
        best = {element: current, rect, text, priceText};
      }
    }
  }
  if (!best) {
    return null;
  }
  const priceMatch = best.text.match(/[¥￥]\s*\d[\d,.]*/);
  const displayPrice = cleanText(priceMatch?.[0], 80);
  let title = best.text
    .replace(/[¥￥]\s*\d[\d,.]*/g, " ")
    .replace(/^x\s*\d+\s*/i, "")
    .replace(/(?:全部商品|讲解中|立即抢|去抢|抢购)\s*$/g, "")
    .replace(/\s+/g, " ")
    .trim();
  title = cleanText(title, 300);
  if (!title && !displayPrice) {
    return null;
  }
  return {
    element: best.element,
    visible: true,
    product_title: title,
    display_price: displayPrice,
    signature: `${title || ""}\u241f${displayPrice || ""}`
  };
}

function scanProductState() {
  if (!collecting || !collectorOptions.productCards) {
    popupObservationPaused=false;
    return;
  }
  if (materialCollectionOwnsSurface()) {updatePopupObservation(true);return;}
  const product = findProductCard();
  const enhanced = getProductCollector();
  if (enhanced) {
    enhanced.scan(product);
    updatePopupObservation(Boolean(enhanced.isSurfaceCovered()));
    return;
  }
  updatePopupObservation(false);
  if (product) {
    missingProductScans = 0;
    let changeKind = null;
    if (!productVisible) {
      changeKind = productSeen ? "restored_visible" : "baseline_visible";
    } else if (product.signature !== currentProductSignature) {
      changeKind = "visible_product_changed";
    }
    if (changeKind) {
      enqueue(event("product_state", {
        visible: true,
        product_title: product.product_title,
        display_price: product.display_price,
        change_kind: changeKind
      }));
    }
    productVisible = true;
    productSeen = true;
    currentProductSignature = product.signature;
    return;
  }
  missingProductScans += 1;
  if (productVisible && missingProductScans >= 2) {
    enqueue(event("product_state", {
      visible: false,
      product_title: null,
      display_price: null,
      change_kind: "temporarily_not_visible"
    }));
    productVisible = false;
    currentProductSignature = null;
  }
}

function visibleText(selector, limit) {
  const element = document.querySelector(selector);
  return element && isVisible(element) ? cleanText(element.textContent, limit) : null;
}

function integerText(selector) {
  const text = visibleText(selector, 80);
  if (!text) {
    return null;
  }
  const digits = text.replace(/[^0-9]/g, "");
  return digits ? Number(digits) : null;
}

function captureRoomSnapshot() {
  if (!collecting || !collectorOptions.roomMetrics) {
    return;
  }
  const infoBar = visibleText('[data-e2e="rooom-info-bar-anchor"]', 200);
  const likesMatch = infoBar?.match(/[\d.]+\s*[万亿]?\s*本场点赞/);
  const visibleComments = collectorOptions.comments
    ? [...document.querySelectorAll(COMMENT_SELECTOR)].filter(isVisible).length
    : null;
  const productCovered=collectorOptions.productCards && (materialCollectionOwnsSurface()||Boolean(getProductCollector()?.isSurfaceCovered()));
  updatePopupObservation(productCovered);
  const productCardVisible = collectorOptions.productCards && !productCovered
    ? Boolean(findProductCard()) : null;
  enqueue(event("room_snapshot", {
    account_name: visibleText('[data-e2e="live-room-nickname"]', 120),
    online_viewers: integerText('[data-e2e="live-room-audience"]'),
    likes_display: cleanText(likesMatch?.[0], 80),
    hour_rank: visibleText('[data-e2e="hour-rank-entrance"]', 80),
    visible_comment_pairs: visibleComments,
    product_card_visible: productCardVisible
  }));
}

function startCollector(options) {
  collectorOptions = normalizeCollectorOptions(options);
  if (!collectorOptions.enabled) {
    return;
  }
  collecting = true;
  popupObservationPaused=false;
  accountConflict = false;
  commentsStale = false;
  lastCommentObservedAt = Date.now();
  productCollector?.reset();
  collectorSessionId = `page-${crypto.randomUUID()}`;
  sequence = 0;
  pendingEvents = [];
  seenCommentSignatures = new WeakMap();
  clearCommentRescanTimer();
  productVisible = false;
  productSeen = false;
  currentProductSignature = null;
  missingProductScans = 0;
  const navigation = performance.getEntriesByType?.("navigation")?.[0];
  const status = navigation?.type === "reload" ? "page_reloaded" : "started";
  enqueue(event("collector_status", collectorStatusPayload(status)));
  scanPlaybackState({forceCollectorEvent: true});
  if (collectorOptions.comments) scanExistingComments("baseline_visible");
  if (collectorOptions.productCards) scanProductState();
  if (collectorOptions.roomMetrics) captureRoomSnapshot();
}

function updateCollectorOptions(options) {
  const next = normalizeCollectorOptions(options);
  if (!next.enabled) {
    stopCollector("collection_disabled");
    collectorOptions = next;
    return;
  }
  if (!collecting) {
    startCollector(next);
    return;
  }
  if (sameCollectorOptions(collectorOptions, next)) {
    return;
  }
  const previous = collectorOptions;
  collectorOptions = next;
  if (previous.productCards !== next.productCards) productCollector?.reset();
  enqueue(event("collector_status", collectorStatusPayload("options_changed")));
  if (!previous.comments && next.comments) {
    commentsStale = false;
    lastCommentObservedAt = Date.now();
    seenCommentSignatures = new WeakMap();
    scanExistingComments("baseline_visible");
  } else if (previous.comments && !next.comments) {
    clearCommentRescanTimer();
  }
  if (!previous.productCards && next.productCards) {
    productVisible = false;
    productSeen = false;
    currentProductSignature = null;
    missingProductScans = 0;
    scanProductState();
  }
  if (!previous.roomMetrics && next.roomMetrics) {
    captureRoomSnapshot();
  }
}

function stopCollector(reason = "recording_task_inactive") {
  if (!collecting) {
    return;
  }
  enqueue(event("collector_status", collectorStatusPayload("stopped", reason)));
  collecting = false;
  productCollector?.reset();
  clearCommentRescanTimer();
  void flush();
}

async function probeTask() {
  const roomUrl = canonicalRoomUrl(location.href);
  if (!roomUrl) {
    stopCollector();
    setPlaybackGuardActive(false);
    return;
  }
  const response = await sendRuntimeMessage({
    type: "brandbai-collector-probe",
    roomUrl
  });
  if (response.status === 'offline') {
    collectorConnectionLost = true;
    // Unknown helper status is not an inactive recording. Keep bounded pending events and dedup state.
    return;
  }
  const nextRun = response.taskId && response.taskStartedAt ? `${response.taskId}:${response.taskStartedAt}` : null;
  if (nextRun && collectorTaskRun && nextRun !== collectorTaskRun) {
    // Do not attach an old run's buffered comments to a new recording in the same room.
    collecting = false;
    pendingEvents = [];
    collectorSessionId = null;
    droppedPendingEvents = 0;
    clearCommentRescanTimer();
    productCollector?.reset();
  }
  if (nextRun) collectorTaskRun = nextRun;
  if (collectorConnectionLost && response.active && collecting) {
    collectorConnectionLost = false;
    recordPlaybackCollectorStatus('interaction_resumed', 'helper_connection_restored');
    if (droppedPendingEvents) {
      recordPlaybackCollectorStatus('failed', `connection_buffer_overflow_dropped_${droppedPendingEvents}_events`);
      droppedPendingEvents = 0;
    }
  }
  const options = normalizeCollectorOptions(response.collectorOptions);
  productSnapshotSupport = response.productSnapshots === true;
  productCatalogSupport = response.productCatalog === true;
  if (response.active && options.enabled) {
    updateCollectorOptions(options);
  } else if (collecting) {
    stopCollector(response.active ? "collection_disabled" : "recording_task_inactive");
  }
  setPlaybackGuardActive(response.active === true);
  if (collecting && collectorOptions.comments) {
    scanExistingComments("new_visible");
  }
}

pageObserver = new MutationObserver((mutations) => {
  if (!playbackGuardActive && !collecting) {
    return;
  }
  if (playbackGuardActive && mutationContainsEnergySaverSignal(mutations)) {
    schedulePlaybackStateScan();
  }
  if (!collecting || !collectorOptions.comments) {
    return;
  }
  if (mutationContainsCommentSignal(mutations)) {
    scheduleCommentScan();
  }
});

pageObserver.observe(document.documentElement, {
  childList: true,
  characterData: true,
  subtree: true
});
window.addEventListener("pagehide", () => {
  pageMaterials?.stop();
  void pageReviews?.stop();
  setPlaybackGuardActive(false);
  stopCollector("page_closed_or_navigated");
});
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if(['brandbai-review-preview','brandbai-review-start','brandbai-review-status','brandbai-review-stop'].includes(message?.type)) {
    if(runtimeContextInvalidated || canonicalRoomUrl(location.href)!==message.roomUrl) {sendResponse({error:'直播间已变化，请重新识别。'});return false;}
    Promise.resolve().then(()=>{
      const reviews=getPageReviews();
      if(!reviews) return {error:'评价读取模块尚未就绪，请重新加载扩展并刷新直播页。'};
      if(message.type==='brandbai-review-start'){materialSurface={kind:'product'};productCollector?.reset();return reviews.start(message);}
      if(message.type==='brandbai-review-stop')return reviews.stop(message);
      return message.type==='brandbai-review-preview'?reviews.preview():reviews.status();
    }).then(sendResponse).catch(error=>sendResponse({error:error.message}));
    return true;
  }
  if (['brandbai-material-start','brandbai-material-status','brandbai-material-stop','brandbai-material-ack'].includes(message?.type)) {
    if(runtimeContextInvalidated || canonicalRoomUrl(location.href)!==message.roomUrl) { sendResponse({state:'failed',reason:'page_changed'}); return false; }
    try {
      const collector=getPageMaterials();
      if(!collector) throw new Error('collector_unavailable');
      if(message.type==='brandbai-material-start') {
        if(pageReviews?.busy()) throw new Error('review_collection_running');
        materialSurface={kind:message.kind};
        // A previous trusted click must not be completed by automated browsing.
        productCollector?.reset();
        sendResponse(collector.start(message));
      } else if(message.type==='brandbai-material-stop') sendResponse(collector.stop());
      else if(message.type==='brandbai-material-ack') { collector.acknowledge(message.request_id); sendResponse({ok:true}); }
      else sendResponse(collector.status());
    } catch (_) { sendResponse({state:'failed',reason:'collector_unavailable'}); }
    return false;
  }
  if (message?.type === 'brandbai-product-preview') {
    const room = canonicalRoomUrl(location.href);
    if (runtimeContextInvalidated || !room || room !== message.roomUrl) {
      sendResponse({status: 'unavailable'});
      return false;
    }
    try {
      sendResponse(getProductPreviewReader()?.previewCurrent() || {status: 'unavailable'});
    } catch (_) {
      // A parser failure is not a disconnected message port. Never return
      // arbitrary page/error text (which could contain private checkout data).
      sendResponse({status: 'read_failed'});
    }
    return false;
  }
  if (message?.type === "brandbai-content-script-ping") {
    const pageRoomUrl = canonicalRoomUrl(location.href);
    sendResponse({
      ok: Boolean(!runtimeContextInvalidated && pageRoomUrl && canonicalRoomUrl(message.roomUrl) === pageRoomUrl),
      roomUrl: pageRoomUrl
    });
    return false;
  }
  if (message?.type === "brandbai-page-playback-state-query") {
    sendResponse({
      ok: true,
      roomUrl: canonicalRoomUrl(location.href),
      energySaverPaused: detectEnergySaverPause(),
      accountConflict: detectAccountConflict(),
      commentsStale
    });
    return false;
  }
  if (message?.type === "brandbai-playback-guard-activate") {
    const pageRoomUrl = canonicalRoomUrl(location.href);
    if (!pageRoomUrl || canonicalRoomUrl(message.roomUrl) !== pageRoomUrl) {
      sendResponse({ok: false});
      return false;
    }
    setPlaybackGuardActive(true);
    sendResponse({ok: true});
    return false;
  }
  if (message?.type !== "brandbai-collector-options-updated") {
    return false;
  }
  const pageRoomUrl = canonicalRoomUrl(location.href);
  if (!pageRoomUrl || canonicalRoomUrl(message.roomUrl) !== pageRoomUrl) {
    sendResponse({ok: false});
    return false;
  }
  productSnapshotSupport = message.productSnapshots === true;
  productCatalogSupport = message.productCatalog === true;
  updateCollectorOptions(message.collectorOptions);
  sendResponse({ok: true});
  return false;
});
runtimeIntervals.push(setInterval(() => void probeTask(), PROBE_INTERVAL_MS));
runtimeIntervals.push(setInterval(scanProductState, PRODUCT_SCAN_INTERVAL_MS));
runtimeIntervals.push(setInterval(captureRoomSnapshot, ROOM_SNAPSHOT_INTERVAL_MS));
runtimeIntervals.push(setInterval(scanPlaybackState, PLAYBACK_STATE_SCAN_INTERVAL_MS));
void probeTask();
scanPlaybackState();
globalThis.__brandbaiLiveContent = {active: () => !runtimeContextInvalidated};
})();
