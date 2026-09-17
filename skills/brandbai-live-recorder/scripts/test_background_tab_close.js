"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOM_URL = "https://live.douyin.com/295178185857";
const TASK_ID = "dy-background-close-test";
const extensionRoot = path.resolve(__dirname, "..", "assets", "chrome-extension");
const backgroundSource = fs.readFileSync(path.join(extensionRoot, "background.js"), "utf8");

const storage = {};
const visibleBatches = [];
let messageListener = null;
let removedListener = null;

function response(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload
  };
}

async function fetchMock(url, options = {}) {
  const pathname = new URL(url).pathname;
  if (pathname === "/v1/health") {
    return response({service: "brandbai-live-recorder", status: "ready"});
  }
  if (pathname === "/v1/pair") {
    return response({session_token: "t".repeat(48), expires_in_seconds: 900}, 201);
  }
  if (pathname === "/v1/tasks" && (options.method || "GET") === "GET") {
    return response({tasks: [{
      task_id: TASK_ID,
      room_url: ROOM_URL,
      state: "recording",
      collect_comments: true,
      collect_product_cards: false,
      collect_room_metrics: true
    }]});
  }
  if (pathname === `/v1/tasks/${TASK_ID}/visible-events`) {
    const body = JSON.parse(options.body);
    visibleBatches.push(body);
    return response({accepted: body.events.length, duplicates: 0}, 202);
  }
  throw new Error(`Unexpected request: ${options.method || "GET"} ${pathname}`);
}

const chrome = {
  runtime: {
    id: "brandbai-background-test",
    lastError: null,
    onInstalled: {addListener() {}},
    onStartup: {addListener() {}},
    onMessage: {addListener(listener) { messageListener = listener; }}
  },
  sidePanel: {async setPanelBehavior() {}},
  storage: {
    session: {
      async get(key) { return {[key]: storage[key]}; },
      async set(values) { Object.assign(storage, values); },
      async remove(key) { delete storage[key]; }
    }
  },
  tabs: {
    onRemoved: {addListener(listener) { removedListener = listener; }}
  }
};

vm.runInNewContext(backgroundSource, {
  chrome,
  fetch: fetchMock,
  URL,
  Date,
  Promise,
  Set,
  Number,
  String,
  Object,
  Array,
  JSON,
  encodeURIComponent,
  AbortController,
  setTimeout,
  clearTimeout
}, {filename: "background.js"});

function send(message, tabId) {
  return new Promise((resolve, reject) => {
    const sender = {url: ROOM_URL, tab: {id: tabId, url: ROOM_URL}};
    const timeout = setTimeout(() => reject(new Error("Background response timed out")), 1000);
    messageListener(message, sender, (value) => {
      clearTimeout(timeout);
      resolve(value);
    });
  });
}

function statusEvent(sequence, status, reason = null) {
  return {
    sequence,
    event_type: "collector_status",
    observed_at_epoch_ms: Date.now(),
    room_url: ROOM_URL,
    payload: {
      status,
      reason,
      collect_comments: true,
      collect_product_cards: true,
      collect_room_metrics: true
    }
  };
}

function visibleMessage(sessionId, event) {
  return {
    type: "brandbai-visible-events",
    roomUrl: ROOM_URL,
    collectorSessionId: sessionId,
    events: [event]
  };
}

function fallbackBatches(sessionId) {
  return visibleBatches.filter((batch) =>
    batch.collector_session_id === sessionId &&
    batch.events.some((event) => event.sequence === 1000000000)
  );
}

async function main() {
  assert.ok(messageListener, "background message listener was not registered");
  assert.ok(removedListener, "tab removal listener was not registered");

  const restoredProbe = await send({type: "brandbai-collector-probe", roomUrl: ROOM_URL}, 16);
  assert.equal(restoredProbe.active, true);
  assert.deepEqual(
    JSON.parse(JSON.stringify(restoredProbe.collectorOptions)),
    {enabled: true, comments: true, productCards: false, roomMetrics: true},
    "an active task must restore its explicit collector scope after session storage is cleared"
  );

  const deliveredSession = "page-content-stop-delivered";
  await send(visibleMessage(deliveredSession, statusEvent(0, "started")), 17);
  removedListener(17);
  await new Promise((resolve) => setTimeout(resolve, 50));
  await send(
    visibleMessage(deliveredSession, statusEvent(1, "stopped", "page_closed_or_navigated")),
    17
  );
  await new Promise((resolve) => setTimeout(resolve, 300));
  assert.equal(
    fallbackBatches(deliveredSession).length,
    0,
    "background must not duplicate a delivered content-script stop"
  );

  const fallbackSession = "page-content-stop-missing";
  await send(visibleMessage(fallbackSession, statusEvent(0, "started")), 18);
  removedListener(18);
  await new Promise((resolve) => setTimeout(resolve, 350));
  const fallback = fallbackBatches(fallbackSession);
  assert.equal(fallback.length, 1, "background must record one missing tab-close stop");
  assert.equal(fallback[0].events[0].payload.status, "stopped");
  assert.equal(fallback[0].events[0].payload.reason, "page_closed_or_navigated");

  process.stdout.write("background tab-close fallback tests passed\n");
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
