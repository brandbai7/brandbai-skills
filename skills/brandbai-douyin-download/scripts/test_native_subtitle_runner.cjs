"use strict";
const test = require("node:test"), assert = require("node:assert/strict"), fs = require("node:fs"),
 path = require("node:path"), vm = require("node:vm"), crypto = require("node:crypto");
const BASE = path.resolve(__dirname, "../assets/subtitles-native");
const runner = require(path.join(BASE, "native-runner.js"));
test("all shared pipeline scripts and shipped model resources have verified manifest hashes", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(BASE, "runtime-manifest.json")));
  assert.deepEqual(manifest.scriptPaths, runner.SCRIPT_PATHS);
  for (const [name, digest] of Object.entries(manifest.sha256)) {
    assert.equal(crypto.createHash("sha256").update(fs.readFileSync(path.join(BASE, name))).digest("hex"), digest, name);
  }
  assert.equal(manifest.source, "workflow-v0.11.201 independently frozen local test runtime");
  assert.equal(manifest.sha256["subtitles/new-pipeline.js"], "f7bf345ea724f462d2d76814bf60f94825e224c7395b8e2faa88f177cc8e830a");
});
test("the local entry page is UTF-8 with one fixed ordered script set and no platform/CDN", () => {
  const html = runner.html();
  assert.match(html, /charset="utf-8"/);
  assert.match(html, /Content-Security-Policy/);
  assert.doesNotMatch(html, /https?:/);
  assert.equal((html.match(/new-pipeline[.]js/g) || []).length, 1);
  assert.equal((html.match(/native-runner[.]js/g) || []).length, 1);
});
function context() {
  const context = vm.createContext({ AbortController, TextEncoder, atob, btoa, setTimeout, clearTimeout, crypto: crypto.webcrypto });
  for (const name of [...runner.SCRIPT_PATHS, "native-runner.js"]) vm.runInContext(fs.readFileSync(path.join(BASE, name), "utf8"), context, { filename: name });
  return context;
}
test("all shared browser globals load without a Worker/model/browser initialization", () => {
  const contextValue = context();
  assert.equal(typeof contextValue.BrandbaiHighQualitySubtitles.Session, "function");
  assert.equal(typeof contextValue.BrandbaiSubtitleWorkingGroupsV198.groupWorkingSegments, "function");
  assert.equal(typeof contextValue.BrandbaiSubtitleWorkingCandidatesV198.groupWorkingCandidates, "function");
  contextValue.BrandbaiSubtitleSimplified.assertReady();
  assert.equal(contextValue.BrandbaiSubtitleSimplified.text("萬別繁體"), "万别繁体");
  assert.equal(contextValue.Worker, undefined);
});
test("canonical working body is once across outputs and all critical notices stay separate; raw unchanged", () => {
  const c = context(), row = { id: "work:e0,e1", text: "两杯足够", workingGroupSchema: "subtitle-working-group-v198",
    presentationOnly: true, firstObserved: .05, lastObserved: .55, rowIndices: [], observationIndices: [],
    originalEventSegments: [{ id: "e0", text: "两杯足够", criticalReadingStatus: { hasCriticalConflict: true, candidates: [{ text: "一杯足够" }, { text: "两杯足够" }] } }] };
  const result = { state: "processed", skipLegacyFinalize: true, pipelineId: "detected-lines-precision-v193",
    raw: { rows: [{ text: "一杯足够", precision: "never rewritten" }], frames: [] }, events: [{ id: "e0", precision: { reading: { text: "兩杯足夠" } } }],
    observations: [], segments: [row] }, before = JSON.stringify(result), source = { title: "synthetic fixture", sourceKind: "local_file" };
  const collector = { plan: value => ({ rows: [{ segmentIndex: 0, segment: value.segments[0], images: [], missing: true }], imageCount: 0, missingSegments: 1 }) };
  const out = c.BrandbaiDetectedSubtitleRunner.outputs(result, source, collector);
  assert.equal(c.BrandbaiSubtitleOutput.body(result, "plain"), "两杯足够［读数待核对］");
  assert.match(out.plain, /候选 1：一杯足够/);
  assert.match(out.documents.html, /<details>/);
  assert.match(out.documents.markdown, /查看本段读数差异/);
  assert.match(out.csv, /一杯足够/);
  assert.equal(out.documents.manifest.rows.length, 1);
  assert.equal(JSON.stringify(result), before);
});

