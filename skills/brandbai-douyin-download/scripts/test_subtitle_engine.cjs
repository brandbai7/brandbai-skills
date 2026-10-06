"use strict";
// Public fixtures are synthetic; no collected media, creator or subtitle data.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const api = require("../assets/subtitles/engine.js");
const anchor = "这个画面的字幕清晰可见";
function reading(text, scores = {}, mode = "original") {
  const glyphs = Array.from(text).map((text, i) => ({ text, confidence: scores[i] ?? 99 }));
  return { text, mode, confidence: glyphs.reduce((n, g) => n + g.confidence, 0) / glyphs.length,
    minCharConfidence: Math.min(...glyphs.map(g => g.confidence)), charConfidences: glyphs };
}
function edge(text = anchor, glyph = "雲", side = "end", confidence = 5) {
  return side === "start" ? reading(glyph + text, { 0: confidence }) : reading(text + glyph, { [Array.from(text).length]: confidence });
}
function replay(rows, times = rows.map((_, i) => i * .5)) {
  const out = { state: "processed", processed: 0, uncertainFrames: 0, emptyFrames: 0, segments: [] };
  rows.forEach((r, i) => api.addSample(out, r, times[i], .5, [r]));
  return out;
}
const edgeGroups = result => result.segments.filter(s => s.lowConfidenceEdgeVariant);

test("shipped model identity and pinned assets agree without model execution or network", () => {
  const vendor = path.join(__dirname, "../assets/subtitles/vendor");
  const manifest = JSON.parse(fs.readFileSync(path.join(vendor, "manifest.json"), "utf8"));
  assert.equal(manifest.engine, "PP-OCRv5-mobile");
  assert.equal(new api.Session({}).result.engine, manifest.engine);
  assert.equal(manifest.sha256["rec.onnx"], "5825fc7ebf84ae7a412be049820b4d86d77620f204a041697b0494669b1742c5");
  assert.equal(manifest.sha256["keys.txt"], "d1979e9f794c464c0d2e0b70a7fe14dd978e9dc644c0e71f14158cdf8342af1b");
  for (const [relative, expected] of Object.entries(manifest.sha256)) {
    const asset = path.resolve(vendor, relative);
    assert.ok(asset.startsWith(path.resolve(vendor) + path.sep));
    assert.equal(crypto.createHash("sha256").update(fs.readFileSync(asset)).digest("hex"), expected, relative);
  }
});

test("horizontal Han/Kana gaps are comparison-only; Latin, numeric and multiline distinctions remain", () => {
  for (const gap of [" ", "\t", "\u00a0", "\u2009", "\u3000"]) {
    assert.equal(api.comparisonKey(`连续${gap}画面字幕`), "连续画面字幕");
    assert.equal(api.comparisonKey(`カタ${gap}カナ`), "カタカナ");
  }
  for (const [a, b] of [["New York", "NewYork"], ["10 克", "10克"], ["1 2", "12"], ["上行\n下行", "上行下行"], ["不适合使用", "适合使用"]]) {
    assert.notEqual(api.comparisonKey(a), api.comparisonKey(b));
  }
  const literal = "连续\u3000画面字幕", out = replay([reading(literal), reading(literal)]);
  assert.equal(out.segments[0].text, literal); assert.equal(out.segments[0].needsReview, false);
  assert.deepEqual(out.observations.map(o => o.text), [literal, literal]);
});

test("actual high-confidence short original can represent weak edge variants without losing recovery", () => {
  for (const rows of [[reading(anchor), edge(anchor, "雲", "start"), reading(anchor)], [edge(), edge(), reading(anchor)], [reading(anchor), reading(anchor), edge()]]) {
    const out = replay(rows), before = structuredClone(out.observations);
    assert.equal(edgeGroups(out).length, 1); assert.equal(out.segments[0].text, anchor);
    assert.equal(out.segments[0].needsReview, true);
    assert.ok(out.segments[0].retainedSegments.some(s => s.text !== anchor));
    const restored = api.reviewedResult(out, [0]);
    assert.deepEqual(restored.observations, before);
    assert.deepEqual(restored.segments.flatMap(s => s.observationIndices), rows.map((_, i) => i));
    assert.deepEqual([out.segments[0].firstObserved, out.segments[0].lastObserved], [0, 1]);
  }
});

test("no actual original short reading means no invented short caption", () => {
  for (const rows of [[edge(), edge()], [edge(), reading(anchor, {}, "white")]]) assert.equal(edgeGroups(replay(rows)).length, 0);
});

for (const glyph of ["1", "一", "不", "未", "无", "克", "杯", "升", "更", "最", "约", "近", "仅", "只", "超", "至", "再", "还", "已", "内", "外", "m"]) {
  test(`protected edge ${glyph} never authorizes low-confidence shortening`, () => {
    for (const side of ["start", "end"]) assert.equal(edgeGroups(replay([reading(anchor), edge(anchor, glyph, side), reading(anchor)])).length, 0);
  });
}

test("strict glyph confidence and evidence alignment are required", () => {
  assert.equal(edgeGroups(replay([reading(anchor), edge(anchor, "雲", "end", 10)])).length, 0);
  assert.equal(edgeGroups(replay([reading(anchor, { 1: 94.99 }), edge()])).length, 0);
  for (const change of [r => delete r.charConfidences, r => r.charConfidences.pop(), r => r.charConfidences[1].confidence = 94.99, r => r.charConfidences[0].text = "甲"]) {
    const row = edge(); change(row); assert.equal(edgeGroups(replay([reading(anchor), row])).length, 0);
  }
});

test("breaks, multiline content, marked names and internal edits remain separate", () => {
  for (const times of [[0, 2], [0, 0], [.5, 0]]) assert.equal(edgeGroups(replay([reading(anchor), edge()], times)).length, 0);
  for (const boundary of [{ text: "", confidence: 0, mode: "original" }, { text: "未知画面", confidence: 60, mode: "original" }, reading("这是下一句不同的描述")]) {
    assert.equal(edgeGroups(replay([reading(anchor), boundary, edge()])).length, 0);
  }
  for (const text of [anchor + "\n下一行", "今天请教作者示例的建议"]) assert.equal(edgeGroups(replay([reading(text), edge(text)])).length, 0);
  assert.equal(edgeGroups(replay([reading(anchor), reading(anchor.slice(0, 4) + "雲" + anchor.slice(4), { 4: 5 })])).length, 0);
});

test("copy/export retains observation ranges and never upgrades machine output to verified", () => {
  const out = replay([reading(anchor), edge()]);
  assert.equal(api.reviewedResult(out, [0]).candidatesConfirmed, false);
  assert.match(api.toText(out), /未全文人工核验/);
  assert.match(api.toText(out), /00:00\.00–00:00\.50/);
});
