"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {randomUUID} = require("node:crypto");

const ROOM_URL = "https://live.douyin.com/295178185857";
const extensionRoot = path.resolve(__dirname, "..", "assets", "chrome-extension");
const contentSource = fs.readFileSync(path.join(extensionRoot, "content.js"), "utf8");

class FakeElement {
  constructor(text = "", {tagName = "DIV", role = null, cursor = "pointer"} = {}) {
    this.textContent = text;
    this.parentElement = null;
    this.visible = true;
    this.tagName = tagName;
    this.role = role;
    this.cursor = cursor;
  }

  getBoundingClientRect() {
    return this.visible
      ? {width: 220, height: 48, top: 20, bottom: 68, x: 20}
      : {width: 0, height: 0, top: 0, bottom: 0, x: 0};
  }

  matches() { return false; }
  querySelectorAll() { return []; }
  closest() { return null; }
  getAttribute(name) { return name === "role" ? this.role : null; }
}

function createHarness({
  resumeSucceeds,
  active = true,
  collectorEnabled = true,
  runtimeInvalidated = false
}) {
  const sentEvents = [];
  const intervals = [];
  const timeouts = [];
  let runtimeListener = null;
  let continueClicks = 0;
  let clientClicks = 0;
  let clearedIntervals = 0;
  let observerDisconnected = false;

  const overlay = new FakeElement("长时间无操作，已暂停播放 继续播放 使用客户端免弹窗");
  const continueButton = new FakeElement("继续播放", {tagName: "DIV"});
  const clientButton = new FakeElement("使用客户端免弹窗", {tagName: "DIV"});
  const unrelatedContinue = new FakeElement("继续播放", {tagName: "DIV"});
  continueButton.parentElement = overlay;
  clientButton.parentElement = overlay;
  continueButton.click = () => {
    continueClicks += 1;
    if (resumeSucceeds) {
      overlay.visible = false;
      continueButton.visible = false;
      clientButton.visible = false;
    }
  };
  clientButton.click = () => { clientClicks += 1; };
  unrelatedContinue.click = () => {
    throw new Error("a same-label control outside the energy-saver overlay must not be clicked");
  };

  const documentElement = new FakeElement();
  const document = {
    documentElement,
    querySelector(selector) {
      if (selector === '[data-e2e="yellowCart-container"]') return null;
      return null;
    },
    querySelectorAll(selector) {
      if (selector === 'button, [role="button"], a, div, span') {
        return [clientButton, unrelatedContinue, continueButton];
      }
      return [];
    }
  };

  const chrome = {
    runtime: {
      lastError: null,
      onMessage: {addListener(listener) { runtimeListener = listener; }},
      sendMessage(message, callback) {
        if (runtimeInvalidated) {
          throw new Error("Extension context invalidated.");
        }
        if (message.type === "brandbai-collector-probe") {
          callback({
            status: "ok",
            active,
            collectorOptions: {
              enabled: collectorEnabled,
              comments: collectorEnabled,
              productCards: false,
              roomMetrics: false
            }
          });
          return;
        }
        if (message.type === "brandbai-visible-events") {
          sentEvents.push(...message.events);
          callback({status: "ok", accepted: message.events.length});
          return;
        }
        throw new Error(`Unexpected message: ${message.type}`);
      }
    }
  };

  const context = {
    chrome,
    document,
    window: {addEventListener() {}},
    location: {href: ROOM_URL},
    performance: {getEntriesByType() { return []; }},
    crypto: {randomUUID},
    MutationObserver: class {
      observe() {}
      disconnect() { observerDisconnected = true; }
    },
    Element: FakeElement,
    URL,
    Date,
    Promise,
    WeakSet,
    Number,
    String,
    Object,
    Array,
    Boolean,
    Math,
    innerHeight: 1000,
    getComputedStyle(element) {
      return {
        display: element.visible ? "block" : "none",
        visibility: element.visible ? "visible" : "hidden",
        cursor: element.cursor
      };
    },
    queueMicrotask,
    setInterval(fn, delay) {
      intervals.push({fn, delay});
      return intervals.length;
    },
    clearInterval() { clearedIntervals += 1; },
    setTimeout(fn, delay) {
      const timer = {fn, delay, active: true};
      timeouts.push(timer);
      return timer;
    },
    clearTimeout(timer) {
      if (timer) timer.active = false;
    }
  };

  vm.runInNewContext(contentSource, context, {filename: "content.js"});

  return {
    sentEvents,
    intervals,
    timeouts,
    get continueClicks() { return continueClicks; },
    get clientClicks() { return clientClicks; },
    get clearedIntervals() { return clearedIntervals; },
    get observerDisconnected() { return observerDisconnected; },
    runtimeListener
  };
}

async function settle() {
  for (let index = 0; index < 8; index += 1) {
    await Promise.resolve();
  }
}

function statuses(harness) {
  return harness.sentEvents
    .filter((item) => item.event_type === "collector_status")
    .map((item) => item.payload.status);
}

function runRecoveryVerification(harness) {
  const timer = harness.timeouts.find((item) => item.active && item.delay === 1500);
  assert.ok(timer, "expected a pending local playback verification timer");
  timer.active = false;
  timer.fn();
}

async function drainFlushTimers(harness) {
  for (;;) {
    const timer = harness.timeouts.find((item) => item.active && item.delay === 500);
    if (!timer) return;
    timer.active = false;
    timer.fn();
    await settle();
  }
}

async function main() {
  const success = createHarness({resumeSucceeds: true});
  await settle();
  assert.ok(success.runtimeListener, "content message listener was not registered");
  assert.equal(success.continueClicks, 1, "the exact continue control should be clicked once");
  assert.equal(success.clientClicks, 0, "the client-launch control must never be clicked");
  await drainFlushTimers(success);
  const playbackInterval = success.intervals.filter((item) => item.delay === 1000).at(-1);
  assert.ok(playbackInterval, "playback state interval was not registered");
  playbackInterval.fn();
  await settle();
  await drainFlushTimers(success);
  assert.deepEqual(
    statuses(success).filter((value) => value.startsWith("playback_")),
    ["playback_paused", "playback_resume_requested", "playback_resumed"]
  );

  const failure = createHarness({resumeSucceeds: false});
  await settle();
  await drainFlushTimers(failure);
  runRecoveryVerification(failure);
  await settle();
  await drainFlushTimers(failure);
  runRecoveryVerification(failure);
  await settle();
  await drainFlushTimers(failure);
  assert.equal(failure.continueClicks, 2, "recovery attempts must stop at the bounded limit");
  assert.equal(failure.clientClicks, 0, "failure must not fall back to the client-launch control");
  assert.deepEqual(
    statuses(failure).filter((value) => value.startsWith("playback_")),
    [
      "playback_paused",
      "playback_resume_requested",
      "playback_resume_requested",
      "playback_resume_failed"
    ]
  );

  const recordingOnly = createHarness({resumeSucceeds: true, collectorEnabled: false});
  const recordingOnlyProbe = recordingOnly.intervals.find((item) => item.delay === 3000);
  assert.ok(recordingOnlyProbe, "recording task probe interval was not registered");
  recordingOnlyProbe.fn();
  await settle();
  assert.equal(
    recordingOnly.continueClicks,
    1,
    "an active recording should recover playback even when interaction collection is disabled"
  );
  assert.equal(recordingOnly.clientClicks, 0);
  assert.deepEqual(
    statuses(recordingOnly),
    [],
    "playback protection alone must not create a visible interaction session"
  );

  const inactive = createHarness({resumeSucceeds: true, active: false, collectorEnabled: false});
  const inactiveProbe = inactive.intervals.find((item) => item.delay === 3000);
  inactiveProbe.fn();
  await settle();
  assert.equal(inactive.continueClicks, 0, "an inactive room must never be controlled");
  assert.equal(inactive.clientClicks, 0);

  let immediateResponse = null;
  inactive.runtimeListener({
    type: "brandbai-playback-guard-activate",
    roomUrl: ROOM_URL
  }, null, (response) => { immediateResponse = response; });
  assert.equal(immediateResponse?.ok, true);
  assert.equal(
    inactive.continueClicks,
    1,
    "an accepted start action should immediately recover an already-paused page"
  );
  assert.equal(inactive.clientClicks, 0);

  const immediateCollected = createHarness({
    resumeSucceeds: true,
    active: false,
    collectorEnabled: false
  });
  await settle();
  immediateCollected.runtimeListener({
    type: "brandbai-collector-options-updated",
    roomUrl: ROOM_URL,
    collectorOptions: {
      enabled: true,
      comments: true,
      productCards: false,
      roomMetrics: false
    }
  }, null, () => {});
  immediateCollected.runtimeListener({
    type: "brandbai-playback-guard-activate",
    roomUrl: ROOM_URL
  }, null, () => {});
  await drainFlushTimers(immediateCollected);
  runRecoveryVerification(immediateCollected);
  await settle();
  await drainFlushTimers(immediateCollected);
  assert.deepEqual(
    statuses(immediateCollected).filter((value) => value.startsWith("playback_")),
    ["playback_paused", "playback_resume_requested", "playback_resumed"],
    "immediate start recovery should retain the playback audit trail when collection is enabled"
  );

  const wrongRoom = createHarness({resumeSucceeds: true, active: false, collectorEnabled: false});
  await settle();
  let wrongRoomResponse = null;
  wrongRoom.runtimeListener({
    type: "brandbai-playback-guard-activate",
    roomUrl: "https://live.douyin.com/other-room"
  }, null, (response) => { wrongRoomResponse = response; });
  assert.equal(wrongRoomResponse?.ok, false);
  assert.equal(wrongRoom.continueClicks, 0, "a mismatched room activation must be rejected");

  const invalidated = createHarness({
    resumeSucceeds: true,
    active: false,
    collectorEnabled: false,
    runtimeInvalidated: true
  });
  await settle();
  assert.equal(
    invalidated.clearedIntervals,
    invalidated.intervals.length,
    "an invalidated old content script must stop every registered interval"
  );
  assert.equal(
    invalidated.observerDisconnected,
    true,
    "an invalidated old content script must disconnect its page observer"
  );
  assert.equal(invalidated.continueClicks, 0);

  process.stdout.write("content playback recovery tests passed\n");
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
