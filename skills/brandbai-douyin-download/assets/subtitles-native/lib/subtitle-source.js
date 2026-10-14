/* Source labels describe where this task came from, not where OCR executes. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.BrandbaiSubtitleSource = api;
})(globalThis, function () {
  "use strict";
  const LABELS = Object.freeze({
    page_native_frames: "当前网页视频",
    completed_download: "当前网页视频（复用已下载素材）",
    local_file: "用户选择的视频文件",
    saved_text: "已保留结果"
  });
  function kind(source) { const value = source?.sourceKind || source?.kind; return Object.hasOwn(LABELS, value) ? value : "unknown"; }
  function label(source) {
    const value = kind(source);
    const original = source?.originalSourceKind;
    return value === "saved_text" && ["page_native_frames", "completed_download", "local_file"].includes(original)
      ? `已保留结果（原来源：${LABELS[original]}）` : LABELS[value] || "来源待确认";
  }
  function describe(source) {
    const sourceKind = kind(source), local = sourceKind === "local_file";
    const workId = !local && /^\d{10,25}$/.test(String(source?.workId || "")) ? String(source.workId) : "";
    const localSourceId = !workId && /^local:[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(String(source?.localSourceId || "")) ? String(source.localSourceId).toLowerCase() : "";
    return { sourceKind, label: label(source), title: String(source?.title || workId || "视频字幕结果"), workId, localSourceId,
      ...(sourceKind === "saved_text" && ["page_native_frames", "completed_download", "local_file"].includes(source?.originalSourceKind) ? { originalSourceKind:source.originalSourceKind } : {}) };
  }
  function lines(source) {
    const row = describe(source);
    return [`来源：${row.label}`, `作品：${row.title}`, `作品ID：${row.workId || "未关联网页作品"}`,
      ...(row.localSourceId ? [`文件记录ID：${row.localSourceId}`] : [])];
  }
  return { LABELS, kind, label, describe, lines };
});
