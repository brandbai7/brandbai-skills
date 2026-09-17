"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {randomUUID} = require("node:crypto");

const ROOM_URL = "https://live.douyin.com/123456789";
const COMMENT_SELECTOR = ".webcast-chatroom___content-with-emoji-text";
const COMMENT_WRAPPER_SELECTOR = ".webcast-chatroom___item-wrapper";
const extensionRoot = path.resolve(__dirname, "..", "assets", "chrome-extension");
const contentSource = fs.readFileSync(path.join(extensionRoot, "content.js"), "utf8");

class FakeElement {
  constructor(text = "", {selector = null, tagName = "DIV"} = {}) {
    this.textContent = text;
    this.selector = selector;
    this.tagName = tagName;
    this.parentElement = null;
    this.visible = true;
    this.namedChildren = [];
    this.commentContent = null;
  }

  getBoundingClientRect() {
    return this.visible
      ? {width: 240, height: 36, top: 20, bottom: 56, x: 20}
      : {width: 0, height: 0, top: 0, bottom: 0, x: 0};
  }

  matches(selector) {
    return this.selector === selector;
  }

  closest(selector) {
    for (let current = this; current; current = current.parentElement) {
      if (current.matches(selector)) return current;
    }
    return null;
  }

  querySelector(selector) {
    return selector === COMMENT_SELECTOR ? this.commentContent : null;
  }

  querySelectorAll(selector) {
    if (selector === "span") return this.namedChildren;
    if (selector === COMMENT_SELECTOR && this.commentContent) return [this.commentContent];
    return [];
  }

  getAttribute() {
    return null;
  }
}

class FakeTextNode {
  constructor(parentElement) {
    this.parentElement = parentElement;
  }
}

function createHarness() {
  const sentEvents = [];
  const intervals = [];
  const timeouts = [];
  let observerCallback = null;
  let observerOptions = null;
  let offline = false;
  const controls = [];

  const wrapper = new FakeElement("", {selector: COMMENT_WRAPPER_SELECTOR});
  const nickname = new FakeElement("观众甲：", {tagName: "SPAN"});
  const content = new FakeElement("第一条评论", {selector: COMMENT_SELECTOR, tagName: "SPAN"});
  nickname.parentElement = wrapper;
  content.parentElement = wrapper;
  wrapper.namedChildren = [nickname];
  wrapper.commentContent = content;

  const documentElement = new FakeElement();
  const document = {
    documentElement,
    querySelector() { return null; },
    querySelectorAll(selector) {
      if (selector === COMMENT_SELECTOR) return [content];
      if (selector === 'button, [role="button"], a, div, span') return controls;
      return [];
    }
  };

  const chrome = {
    runtime: {
      lastError: null,
      onMessage: {addListener() {}},
      sendMessage(message, callback) {
        if (offline) { callback({status:'offline',active:false}); return; }
        if (message.type === "brandbai-collector-probe") {
          callback({
            status: "ok",
            active: true,
            taskId: 'synthetic-task',
            taskStartedAt: context.testRun || '2026-01-01T00:00:00Z',
            collectorOptions: {
              enabled: true,
              comments: true,
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
      constructor(callback) { observerCallback = callback; }
      observe(_target, options) { observerOptions = options; }
      disconnect() {}
    },
    Element: FakeElement,
    URL,
    Date,
    Promise,
    WeakMap,
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
        cursor: "default"
      };
    },
    queueMicrotask,
    setInterval(fn, delay) {
      intervals.push({fn, delay});
      return intervals.length;
    },
    clearInterval() {},
    setTimeout(fn, delay) {
      const timer = {fn, delay, active: true};
      timeouts.push(timer);
      return timer;
    },
    clearTimeout(timer) {
      if (timer) timer.active = false;
    }
  };

  // Test-only access to the collector's lexical state. The shipped script
  // remains an idempotent closure and does not expose mutable internals.
  const inspectedSource=contentSource.replace(/\}\)\(\);\s*$/, 'globalThis.inspectForTest = code => eval(code);\n})();');
  vm.runInNewContext(inspectedSource, context, {filename: "content.js"});
  return {
    run: code => context.inspectForTest(code),
    offline: value => { offline = value; },
    controls,
    content,
    intervals,
    timeouts,
    sentEvents,
    get observerCallback() { return observerCallback; },
    get observerOptions() { return observerOptions; }
  };
}

async function settle() {
  for (let index = 0; index < 8; index += 1) {
    await Promise.resolve();
  }
}

async function runPendingTimers(harness, delay) {
  for (;;) {
    const timer = harness.timeouts.find((item) => item.active && item.delay === delay);
    if (!timer) return;
    timer.active = false;
    timer.fn();
    await settle();
  }
}

async function flushEvents(harness) {
  await settle();
  await runPendingTimers(harness, 500);
}

function commentTexts(harness) {
  return harness.sentEvents
    .filter((item) => item.event_type === "comment_visible")
    .map((item) => item.payload.text);
}

async function main() {
  const harness = createHarness();
  await flushEvents(harness);

  assert.ok(harness.observerCallback, "the comment mutation observer must be registered");
  assert.equal(harness.observerOptions?.characterData, true);
  assert.deepEqual(commentTexts(harness), ["第一条评论"]);

  harness.content.textContent = "第二条评论";
  harness.observerCallback([{
    target: new FakeTextNode(harness.content),
    addedNodes: []
  }]);
  await runPendingTimers(harness, 50);
  await flushEvents(harness);
  assert.deepEqual(
    commentTexts(harness),
    ["第一条评论", "第二条评论"],
    "reused comment elements must emit again when their visible text changes"
  );

  harness.observerCallback([{
    target: new FakeTextNode(harness.content),
    addedNodes: []
  }]);
  await runPendingTimers(harness, 50);
  await flushEvents(harness);
  assert.deepEqual(
    commentTexts(harness),
    ["第一条评论", "第二条评论"],
    "an unchanged element signature must not be emitted twice"
  );

  harness.content.textContent = "第三条评论";
  const probeInterval = harness.intervals.find((item) => item.delay === 3000);
  assert.ok(probeInterval, "the low-frequency task probe must be registered");
  probeInterval.fn();
  await flushEvents(harness);
  assert.deepEqual(
    commentTexts(harness),
    ["第一条评论", "第二条评论", "第三条评论"],
    "the task probe must provide a low-frequency safety rescan"
  );

  process.stdout.write("content comment reuse tests passed\n");

  // Background tabs remain collectable; temporary helper failure must not reset session/dedup.
  const retainedSession = harness.run('collectorSessionId');
  harness.run("document.visibilityState = 'hidden'");
  harness.offline(true);
  await harness.run('probeTask()');
  assert.equal(harness.run('collecting'), true);
  assert.equal(harness.run('collectorSessionId'), retainedSession);
  harness.offline(false);
  harness.content.textContent = '后台标签的新评论';
  await harness.run('probeTask()');
  await flushEvents(harness);
  assert.equal(commentTexts(harness).at(-1), '后台标签的新评论');
  assert.equal(harness.run('collectorSessionId'), retainedSession);

  harness.run('lastCommentObservedAt = Date.now() - 181000; scanInteractionHealth()');
  await flushEvents(harness);
  assert.equal(harness.run('commentsStale'), true);
  assert.ok(harness.sentEvents.some(e => e.payload.status === 'comment_stream_stale'));
  harness.content.textContent = '停滞后重新出现';
  await harness.run('probeTask()'); await flushEvents(harness);
  assert.equal(harness.run('commentsStale'), false);

  const overlay = new FakeElement('账号已在其他地方进入直播间 继续看播');
  const button = new FakeElement('继续看播'); button.parentElement = overlay;
  button.click = () => { throw new Error('must never compete for account viewing session'); };
  harness.controls.push(button);
  harness.run('scanInteractionHealth()'); await flushEvents(harness);
  assert.equal(harness.run('accountConflict'), true);
  assert.ok(harness.sentEvents.some(e => e.payload.status === 'interaction_interrupted'));
  harness.controls.length = 0;
  harness.run('scanInteractionHealth()'); await flushEvents(harness);
  assert.equal(harness.run('accountConflict'), false);
  const priorRunSession = harness.run('collectorSessionId');
  harness.run("globalThis.testRun = '2026-01-01T00:05:00Z'");
  await harness.run('probeTask()'); await flushEvents(harness);
  assert.notEqual(harness.run('collectorSessionId'), priorRunSession);
  assert.equal(harness.run('collectorTaskRun'), 'synthetic-task:2026-01-01T00:05:00Z');
  process.stdout.write('background comments, helper outage preservation, stale detection and no account takeover passed\n');

  // Review collection suppresses popup observation, not comments or page metrics.
  harness.run("collectorOptions.productCards=true;collectorOptions.roomMetrics=true;pageReviews={busy:()=>true};scanProductState();captureRoomSnapshot();scanProductState()");
  harness.content.textContent='商品评价读取期间的新评论';
  await harness.run('scanExistingComments()');await flushEvents(harness);
  assert.equal(commentTexts(harness).at(-1),'商品评价读取期间的新评论');
  assert.equal(harness.sentEvents.filter(e=>e.payload.status==='popup_observation_paused').length,1);
  assert.equal(harness.sentEvents.filter(e=>e.event_type==='room_snapshot').at(-1).payload.product_card_visible,null);
  harness.run('pageReviews=null;materialSurface=null;scanProductState()');await flushEvents(harness);
  assert.equal(harness.sentEvents.filter(e=>e.payload.status==='popup_observation_resumed').length,1);
  harness.run("collectorOptions.productCards=false;pageReviews={busy:()=>{throw Error('unselected product must not be read')}};captureRoomSnapshot()");
  process.stdout.write('popup observation gaps remain separate from comments and metrics passed\n');
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
