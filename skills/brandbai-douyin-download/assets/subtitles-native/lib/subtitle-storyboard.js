/* A subtitle event and its actual sampled full-video frames, not semantic shot analysis. */
(function (root, factory) {
  const sourceApi = typeof module === "object" && module.exports && typeof require === "function" ? require("./subtitle-source.js") : root.BrandbaiSubtitleSource;
  const outputApi = typeof module === "object" && module.exports && typeof require === "function" ? require("./subtitle-output.js") : root.BrandbaiSubtitleOutput;
  const api = factory(sourceApi,outputApi);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.BrandbaiSubtitleStoryboard = api;
})(globalThis, function (sourceApi,outputApi) {
  "use strict";
  const MAX_FRAME_BYTES = 60 * 1024 * 1024, MAX_FRAMES = 361;
  const FULL = Object.freeze({ left: 0, top: 0, right: 1, bottom: 1 });
  const GRID_WIDTH = 12, GRID_HEIGHT = 16, GRID_CELLS = GRID_WIDTH * GRID_HEIGHT;
  function fingerprint(canvas, region) {
    const small = document.createElement("canvas"); small.width = 12; small.height = 16;
    const ctx = small.getContext("2d", { willReadFrequently: true }); ctx.drawImage(canvas, 0, 0, 12, 16);
    const data = ctx.getImageData(0, 0, 12, 16).data, vector = []; let sharpness = 0, previous = 0;
    for (let y = 0; y < 16; y++) for (let x = 0; x < 12; x++) {
      // Caption changes must not masquerade as scene changes. Compare only
      // full-frame visual areas outside the selected subtitle band.
      const excluded = region && (y + .5) / 16 >= region.top && (y + .5) / 16 <= region.bottom;
      const offset = (y * 12 + x) * 4;
      for (let c = 0; c < 3; c++) vector.push(excluded ? -1 : Math.round(data[offset + c] / 255 * 1000) / 1000);
      const grey = (data[offset] + data[offset + 1] + data[offset + 2]) / 3;
      if (!excluded && x) sharpness += Math.abs(grey - previous); previous = grey;
    }
    return { vector, sharpness: sharpness / (12 * 16 * 255) };
  }
  function distance(a, b) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length || !a.length) return null;
    let sum = 0, n = 0;
    for (let i = 0; i < a.length; i++) {
      if (![a[i], b[i]].every(value => Number.isFinite(value) && value >= -1 && value <= 1)) return null;
      if (a[i] >= 0 && b[i] >= 0) { sum += Math.abs(a[i] - b[i]); n++; }
    }
    return n ? sum / n : null;
  }
  function nativeMasks(frame) {
    if (!Array.isArray(frame.rawRowEvidence) || !frame.rawRowEvidence.length) return { error: "verified_caption_bounds_missing" };
    const masks = []; let width = null, height = null;
    for (const evidence of frame.rawRowEvidence) {
      const b = evidence.sourceRect, receipt = evidence.cropReceipt, w = evidence.sourceWidth, h = evidence.sourceHeight;
      if (!Number.isSafeInteger(w) || !Number.isSafeInteger(h) || w <= 0 || h <= 0
        || !b || !["left", "right", "top", "bottom"].every(k => Number.isSafeInteger(b[k]))
        || b.left < 0 || b.top < 0 || b.right <= b.left || b.bottom <= b.top || b.right > w || b.bottom > h
        || evidence.frameIndex !== frame.index || evidence.frameId !== frame.sourceFrameId || !Number.isFinite(evidence.time) || Math.abs(evidence.time - frame.time) > .005
        || receipt?.schema !== "source-rect-native-crop-v190" || receipt.frameId !== evidence.frameId || !Number.isFinite(receipt.time) || Math.abs(receipt.time - evidence.time) > .005
        || !["left", "right", "top", "bottom"].every(k => receipt.sourceRect?.[k] === b[k])
        || receipt.inputWidth !== b.right - b.left || receipt.inputHeight !== b.bottom - b.top || receipt.interpolation !== "none_integer_1_to_1") return { error: "verified_caption_bounds_invalid" };
      if (width !== null && (width !== w || height !== h)) return { error: "caption_source_dimensions_inconsistent" };
      width = w; height = h; masks.push({ ...b, sourceWidth: w, sourceHeight: h });
    }
    return { masks, width, height };
  }
  function legacyMask(frame, region) {
    const b = frame.captionRegion || region;
    if (!b) return { masks: [] };
    if (![b.top, b.bottom].every(Number.isFinite) || b.top < 0 || b.bottom > 1 || b.bottom <= b.top) return { error: "legacy_caption_bounds_invalid" };
    // Legacy region callers historically excluded the entire subtitle y-band.
    return { masks: [{ left: 0, right: 1, top: b.top, bottom: b.bottom, sourceWidth: 1, sourceHeight: 1 }] };
  }
  function compareAppearance(a, b, options = {}) {
    const out = { schema: "brandbai-appearance-comparison-v195", status: "unknown", distance: null, comparableCells: 0, maskedCells: 0, unavailableCells: 0, totalCells: GRID_CELLS,
      maskBasis: options.native ? "verified_actual_caption_rect_pair_union_xy" : "legacy_subtitle_y_band", semanticAnalysis: false };
    const valid = vector => Array.isArray(vector) && vector.length === GRID_CELLS * 3 && Array.from(vector).every(n => Number.isFinite(n) && n >= -1 && n <= 1);
    if (!valid(a?.vector) || !valid(b?.vector)) return { ...out, reason: "appearance_grid_invalid" };
    const am = options.native ? nativeMasks(a) : legacyMask(a, options.region), bm = options.native ? nativeMasks(b) : legacyMask(b, options.region);
    if (am.error || bm.error) return { ...out, reason: am.error || bm.error };
    if (options.native && (am.width !== bm.width || am.height !== bm.height)) return { ...out, reason: "caption_source_dimensions_changed" };
    const masks = [...am.masks, ...bm.masks]; let sum = 0;
    for (let y = 0; y < GRID_HEIGHT; y++) for (let x = 0; x < GRID_WIDTH; x++) {
      // Positive footprint overlap, not just the cell center. Integer source
      // cross-products keep exact boundaries from masking neighboring cells.
      const masked = masks.some(r => r.left * GRID_WIDTH < (x + 1) * r.sourceWidth && r.right * GRID_WIDTH > x * r.sourceWidth
        && r.top * GRID_HEIGHT < (y + 1) * r.sourceHeight && r.bottom * GRID_HEIGHT > y * r.sourceHeight);
      if (masked) { out.maskedCells++; continue; }
      const i = (y * GRID_WIDTH + x) * 3;
      if ([0, 1, 2].some(c => a.vector[i + c] < 0 || b.vector[i + c] < 0)) { out.unavailableCells++; continue; }
      out.comparableCells++; for (let c = 0; c < 3; c++) sum += Math.abs(a.vector[i + c] - b.vector[i + c]);
    }
    if (!out.comparableCells) return { ...out, reason: "no_comparable_pixels" };
    return { ...out, status: "compared", distance: sum / (out.comparableCells * 3), reason: "available_rgb_outside_caption_union" };
  }
  function frameName(segmentIndex, order, frame) {
    return `画面/${String(segmentIndex + 1).padStart(3, "0")}_${String(order + 1).padStart(2, "0")}_${frame.time.toFixed(2)}秒.jpg`;
  }
  function isNative(result) {
    return ["detected-lines-precision-v193", "native-lines-v193"].includes(result?.pipelineId) || result?.skipLegacyFinalize === true;
  }
  function uniqueMap(values, key) {
    const map = new Map(), duplicates = new Set();
    for (const value of values || []) {
      if (!value) continue;
      const id = key(value);
      if (!Number.isSafeInteger(id) || id < 0) continue;
      if (map.has(id)) duplicates.add(id); else map.set(id, value);
    }
    // A duplicate identity is ambiguous, never resolved by array order.
    for (const id of duplicates) map.delete(id);
    return map;
  }
  function actualFrameIndex(value) {
    if (value?.frameIndex !== undefined) {
      if (!Number.isSafeInteger(value.frameIndex)) return null;
      if (Number.isSafeInteger(value.index) && value.index !== value.frameIndex) return null;
      return value.frameIndex;
    }
    return value?.index;
  }
  function nativeContext(result, frames) {
    return { observations: uniqueMap(result.observations, actualFrameIndex),
      captured: uniqueMap(frames.filter(f => Number.isFinite(f?.time) && f.blob?.size > 0), actualFrameIndex),
      frames: uniqueMap(result.frames || result.raw?.frames, f => f.frameIndex), rows: uniqueMap(result.rows || result.raw?.rows, r => r.index) };
  }
  function nativeSamples(result, segment, context) {
    // The pipeline has already separated main segments, captionRecovery and
    // screenText. Only the selected layer's explicit rowIndices authorize a picture;
    // raw row.role belongs to an older selector and must not be reinterpreted.
    if (!Array.isArray(segment.rowIndices) || !Array.isArray(segment.observationIndices)
      || !Number.isFinite(segment.firstObserved) || !Number.isFinite(segment.lastObserved)
      || segment.lastObserved < segment.firstObserved) return [];
    const authorized = new Set(segment.observationIndices.filter(Number.isSafeInteger)), grouped = new Map();
    for (const rowIndex of new Set(segment.rowIndices)) {
      const row = context.rows.get(rowIndex), index = row?.frameIndex;
      if (!Number.isSafeInteger(rowIndex) || !Number.isSafeInteger(index) || !authorized.has(index)
        || Array.isArray(segment.frameIndices) && !segment.frameIndices.includes(index)) continue;
      const frame = context.captured.get(index), observed = context.observations.get(index), sourceFrame = context.frames.get(index);
      if (!frame || !sourceFrame || observed?.accepted !== true || sourceFrame.status !== "observed"
        || ![row.time, sourceFrame.time, observed.time].every(t => Number.isFinite(t) && Math.abs(t - frame.time) <= .005)
        || row.frameTime !== undefined && (!Number.isFinite(row.frameTime) || Math.abs(row.frameTime - frame.time) > .005)
        || frame.time < segment.firstObserved - .05 || frame.time > segment.lastObserved + .05
        || typeof row.frameId !== "string" || !row.frameId || row.frameId !== sourceFrame.frameId
        || typeof frame.sourceFrameId === "string" && frame.sourceFrameId !== row.frameId
        || typeof frame.frameId === "string" && frame.frameId !== row.frameId
        || typeof frame.sourceId === "string" && frame.sourceId !== row.sourceId
        || typeof observed.frameId === "string" && observed.frameId !== row.frameId
        || typeof result.sourceId === "string" && row.sourceId !== result.sourceId
        || typeof segment.sourceId === "string" && row.sourceId !== segment.sourceId) continue;
      const b = row.sourceRect, receipt = row.cropReceipt;
      if (!b || !["left", "right", "top", "bottom"].every(k => Number.isSafeInteger(b[k]))
        || b.left < 0 || b.top < 0 || b.right <= b.left || b.bottom <= b.top
        || !Number.isSafeInteger(row.sourceWidth) || !Number.isSafeInteger(row.sourceHeight)
        || b.right > row.sourceWidth || b.bottom > row.sourceHeight
        || !receipt || receipt.schema !== "source-rect-native-crop-v190" || receipt.frameId !== row.frameId || !Number.isFinite(receipt.time) || Math.abs(receipt.time - row.time) > .005
        || !["left", "right", "top", "bottom"].every(k => receipt.sourceRect?.[k] === b[k])
        || receipt.inputWidth !== b.right - b.left || receipt.inputHeight !== b.bottom - b.top
        || receipt.interpolation !== "none_integer_1_to_1") continue;
      const sourceRect = { left: b.left, right: b.right, top: b.top, bottom: b.bottom };
      const evidence = { rowIndex, frameIndex: index, frameId: row.frameId, time: row.time, sourceRect,
        sourceWidth: row.sourceWidth, sourceHeight: row.sourceHeight,
        cropReceipt: { schema: "source-rect-native-crop-v190", frameId: row.frameId, time: receipt.time, sourceRect: { ...sourceRect },
          inputWidth: receipt.inputWidth, inputHeight: receipt.inputHeight, interpolation: receipt.interpolation } };
      if (!grouped.has(index)) grouped.set(index, { ...frame, index, frameIndex: index, sourceFrameId: row.frameId,
        ...(/^[a-f0-9]{64}$/.test(sourceFrame.sourcePixelSha256 || "") ? { sourcePixelSha256: sourceFrame.sourcePixelSha256 } : {}), rawRowEvidence: [] });
      grouped.get(index).rawRowEvidence.push(evidence);
    }
    return [...grouped.values()].sort((a, b) => a.time - b.time);
  }
  function select(result, frames) {
    const byIndex = new Map(frames.filter(frame => Number.isInteger(frame.index) && Number.isFinite(frame.time) && frame.blob?.size > 0).map(frame => [frame.index, frame]));
    const observations = result?.observations || [];
    const native = isNative(result), context = native ? nativeContext(result, frames) : null;
    const observationFor = frame => native ? context.observations.get(frame.index) : observations[frame.index];
    // Recovery text remains a separate, unconfirmed layer. Its own receipts can
    // authorize its own pictures, never a main caption or a neighboring scene.
    // No screenText inference or role upgrade is performed by this work view.
    const main = result?.segments || [], recovery = native ? result?.captionRecovery || [] : [];
    const mainOwners = new Set(main.flatMap(segment => segment.rowIndices || []));
    const recoveryOwners = new Map();
    for (const segment of recovery) for (const index of new Set(segment.rowIndices || []))
      recoveryOwners.set(index, (recoveryOwners.get(index) || 0) + 1);
    const input = [...main.map((segment, layerIndex) => ({ segment, layer: "body", layerIndex })),
      ...recovery.map((segment, layerIndex) => ({ segment, layer: "recovery", layerIndex }))];
    const rows = input.map(({ segment, layer, layerIndex }, segmentIndex) => {
      const identity = { segmentIndex, segment, layer, layerIndex };
      const indices = segment.observationIndices || [];
      const ownershipConflict = layer === "recovery" && (segment.rowIndices || []).some(index => mainOwners.has(index) || recoveryOwners.get(index) !== 1);
      const available = ownershipConflict ? [] : native ? nativeSamples(result, segment, context) : indices.map(index => byIndex.get(index)).filter(frame => {
        const observation = frame && observations[frame.index];
        return frame && observation?.accepted === true && Number.isFinite(observation.time) && Math.abs(observation.time - frame.time) <= .005
          && frame.time >= segment.firstObserved - .05 && frame.time <= segment.lastObserved + .05;
      }).sort((a, b) => a.time - b.time);
      if (!available.length) return { ...identity, images: [], missing: true, ...(ownershipConflict ? { missingReason: "ambiguous_layer_row_ownership" } : {}) };
      const middle = (segment.firstObserved + segment.lastObserved) / 2;
      const score = frame => {
        const observation = observationFor(frame);
        return (observation?.text === segment.text ? 3 : 0) + (Number(observation?.confidence) || 0) / 100
          + (frame.sharpness || 0) - Math.abs(frame.time - middle) / Math.max(.5, segment.lastObserved - segment.firstObserved + .5);
      };
      const representative = available.reduce((best, frame) => score(frame) > score(best) ? frame : best, available[0]);
      // Add genuine appearance changes across the event. There is no arbitrary
      // one/two-image cap; a long sentence can keep several distinct views.
      const views = [{ frame: available[0], basis: "sampled_representative" }], appearanceComparisons = [];
      for (const frame of available.slice(1)) {
        const last = views.at(-1).frame;
        if (frame.time - last.time < .75) continue;
        const comparison = compareAppearance(last, frame, { native, region: result.region });
        appearanceComparisons.push({ fromFrameIndex: last.index, toFrameIndex: frame.index, ...comparison });
        if (comparison.status === "unknown") views.push({ frame, basis: "sampled_appearance_unknown" });
        else if (comparison.distance >= .14) views.push({ frame, basis: "sampled_appearance_change" });
      }
      const chosen = views.length === 1 ? [{ frame: representative, basis: "sampled_representative" }] : views.map((view, i) => {
        const end = views[i + 1]?.frame.time ?? Infinity;
        const region = available.filter(frame => frame.time >= view.frame.time && frame.time < end);
        return { frame: region.reduce((best, frame) => score(frame) > score(best) ? frame : best, view.frame), basis: view.basis };
      });
      const multiple = chosen.length > 1, firstBoundaryKnownChange = views[1]?.basis === "sampled_appearance_change";
      return { ...identity, missing: false, appearanceComparisons, appearanceUnknown: appearanceComparisons.some(c => c.status === "unknown"),
        images: [...new Map(chosen.map(value => [value.frame.index, value])).values()].sort((a, b) => a.frame.time - b.frame.time)
          .map(({ frame, basis }, order) => ({ ...frame, path: frameName(segmentIndex, order, frame), basis: multiple && firstBoundaryKnownChange && basis === "sampled_representative" ? "sampled_appearance_change" : basis })) };
    });
    return { rows, bodyCount: main.length, recoveryCount: recovery.length,
      imageCount: rows.reduce((n, row) => n + row.images.length, 0), missingSegments: rows.filter(row => row.missing).length };
  }
  function htmlEscape(value) { return String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]); }
  function textPlan(result) {
    const main = result?.segments || [], recovery = isNative(result) ? result?.captionRecovery || [] : [];
    const entries = [...main.map((segment, layerIndex) => ({ segment, layerIndex, layer: "body" })),
      ...recovery.map((segment, layerIndex) => ({ segment, layerIndex, layer: "recovery" }))];
    return { captureMode: "text_only", rows: entries.map((entry, segmentIndex) => ({ ...entry, segmentIndex, images: [], missing: false, imageRequested: false })),
      bodyCount: main.length, recoveryCount: recovery.length, imageCount: 0, missingSegments: 0 };
  }
  function mdEscape(value) { return String(value ?? "").replace(/[\\`*_{}\[\]<>#|]/g, "\\$&"); }
  function csvCell(value) { let text = String(value ?? ""); if (/^[\s\u0000-\u001f]*[=+@-]/u.test(text)) text = "'" + text; return `"${text.replace(/"/g, '""')}"`; }
  function time(value) { if (!Number.isFinite(value) || value < 0) return "待确认"; const n = Math.round(value * 100); return `${String(Math.floor(n / 6000)).padStart(2, "0")}:${String(Math.floor(n % 6000 / 100)).padStart(2, "0")}.${String(n % 100).padStart(2, "0")}`; }
  function range(row) { return `[${time(row.firstObserved)}–${time(row.lastObserved)}]`; }
  function layerLabel(row) { return row.layer === "recovery" ? "待确认文字（可能是短暂字幕或强调字）" : "字幕正文候选"; }
  function rowHeading(row) { return `${layerLabel(row)} ${Number.isSafeInteger(row.layerIndex) ? row.layerIndex + 1 : row.segmentIndex + 1}. ${range(row.segment)}`; }
  function documents(result, source, plan, edits = {}) {
    const textOnly = plan.captureMode === "text_only";
    const descriptor = sourceApi?.describe(source);
    const title = String(descriptor?.title || source?.title || source?.workId || "视频字幕结果");
    const display = segment => result?.outputPolicy === "clean-business-text-v200" ? String(segment.text || "") : outputApi?.isWorkingGroup(segment) ? outputApi.displayText(segment) : outputApi?.workingText(segment) || segment.text;
    const notice = segment => outputApi?.isWorkingGroup(segment) ? outputApi.candidateText(segment) : outputApi?.workingText(segment) !== segment.text ? outputApi?.workingText(segment) || "" : "";
    const htmlNotes = segment => outputApi?.isWorkingGroup(segment) && notice(segment) ? `<details><summary>查看本段读数差异</summary><pre>${htmlEscape(notice(segment))}</pre></details>` : "";
    const manifest = { schema: "brandbai-subtitle-storyboard-v1", workId: descriptor ? descriptor.workId : String(source?.workId || ""), title,
      sourceKind: descriptor?.sourceKind || String(source?.sourceKind || "unknown"), sourceLabel: descriptor?.label || "来源待确认",
      localSourceId: descriptor?.localSourceId || "", ...(descriptor?.originalSourceKind ? {originalSourceKind:descriptor.originalSourceKind} : {}),
      accuracy: "machine_unverified", timeBasis: "sampled_observation_range",
      imageBasis: textOnly ? "not_requested_text_only" : "same_capture_full_video_frame_visual_changes_not_semantic_analysis", state: result.state,
      ...(textOnly ? { captureMode: "text_only" } : {}),
      ...(isNative(result) ? { pipelineId: result.pipelineId || "native-lines-v193", frameMapping: "explicit_layer_row_to_actual_frame_index" } : {}),
      segmentCount: plan.rows.length, bodyCount: plan.rows.filter(row => row.layer !== "recovery").length,
      recoveryCount: plan.rows.filter(row => row.layer === "recovery").length, imageCount: plan.imageCount, missingSegments: plan.missingSegments,
      completeness: textOnly ? "text_only_no_images_requested" : plan.missingSegments ? "partial_images" : "all_current_segments_have_images",
      rows: plan.rows.map(row => ({ segment: row.segmentIndex + 1, layer: row.layer || "body", layerLabel: layerLabel(row), roleConfirmed: false,
        text: row.segment.text, workingText:display(row.segment), criticalNotices:outputApi?.criticalNotices(row.segment)||[],...(row.segment.criticalReadingStatus?{criticalReadingStatus:row.segment.criticalReadingStatus}:{}),firstObserved: row.segment.firstObserved,
        lastObserved: row.segment.lastObserved, observationIndices: row.segment.observationIndices || [],
        ...(row.appearanceComparisons ? { appearanceComparisons: row.appearanceComparisons, appearanceUnknown: row.appearanceUnknown } : {}),
        ...(isNative(result) ? { rowIndices: row.segment.rowIndices || [] } : {}),
        images: row.images.map(frame => ({ path: frame.path, time: frame.time, observationIndex: frame.index, basis: frame.basis,
          ...(isNative(result) ? { frameIndex: frame.index, sourceFrameId: frame.sourceFrameId,
            ...(frame.sourcePixelSha256 ? { sourcePixelSha256: frame.sourcePixelSha256 } : {}), rawRowEvidence: frame.rawRowEvidence || [] } : {}) })) })) };
    const limits = textOnly ? "本次仅提取字幕，没有要求保存视频配图。正文与候选文字分开保留；时间是画面采样观察范围，不是精确字幕轴，也不代表完整口播。机器识别可能漏字或错字，未进行全文人工核实。" : "画面与文字来自同一次视频采样。正文候选与待确认文字分开保留；后者可能是短暂字幕或强调字，未自动拼入正文。时间为观察范围，不是精确字幕轴；可能漏字或错字。代表画面按可比较的外观变化选取；无法比较时保留实际采样并标记不确定，不认定为同景或换景。不是语义分析、效果证明或商品事实。";
    const md = [`# ${mdEscape(title)}`, "", `来源：${mdEscape(manifest.sourceLabel)}`, "", `作品ID：${mdEscape(manifest.workId || "未关联网页作品")}`,
      ...(manifest.localSourceId ? ["", `文件记录ID：${mdEscape(manifest.localSourceId)}`] : []), "", limits, "",
      ...plan.rows.flatMap(row => [`## ${rowHeading(row)}`, "", mdEscape(outputApi?.isWorkingGroup(row.segment)?display(row.segment):row.segment.text), "", ...(notice(row.segment)?outputApi?.isWorkingGroup(row.segment)?["<details><summary>查看本段读数差异</summary>","",mdEscape(notice(row.segment)),"","</details>",""]:[mdEscape(notice(row.segment)),""]:[]),
        ...row.images.flatMap(frame => [`![${time(frame.time)} 采样画面](${frame.path})`, "", `画面采样：${time(frame.time)}`, ""]), ...(row.missing ? ["本句画面未保留；不以其他句或其他视频的图片替代。", ""] : [])])];
    if (typeof edits.timed === "string" || typeof edits.plain === "string") md.push("## 另存的人工编辑稿", "", "编辑稿独立保存，未自动重绑原时间和配图。", "", mdEscape(edits.plain ?? edits.timed), "");
    const header = ["作品ID", "分段", "首次观察秒", "末次观察秒", "机器整理文字", "画面文件", "画面采样秒", "画面依据", "视频来源", "来源类型", "文件记录ID", "读数分歧说明", "文字层", "角色状态"];
    const csv = [header, ...plan.rows.flatMap(row => (row.images.length ? row.images : [null]).map(frame => [manifest.workId, row.segmentIndex + 1, row.segment.firstObserved, row.segment.lastObserved, row.segment.text, frame?.path || (textOnly ? "本次未选择配图" : "未保留"), frame?.time ?? "", frame?.basis || (textOnly ? "not_requested" : "missing"), manifest.sourceLabel, manifest.sourceKind, manifest.localSourceId,notice(row.segment),layerLabel(row),"机器候选，未人工确认"] ))].map(row => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
    const html = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"><title>${htmlEscape(title)}</title><style>body{font:16px/1.7 system-ui;margin:24px auto;max-width:1000px;padding:0 20px;color:#162c45}section{border-top:1px solid #dce5ef;padding:24px 0}section[data-layer="recovery"]{background:#fffaf2;padding:20px;border:1px solid #f3dfbc;border-radius:12px;margin:18px 0}figure{display:inline-block;vertical-align:top;margin:12px 14px 12px 0;max-width:44%}img{max-width:100%;max-height:480px;object-fit:contain;background:#0c1725}figcaption,small{color:#526a82}pre{white-space:pre-wrap;overflow-wrap:anywhere}details{background:#fff9ef;padding:10px;border:1px solid #f3dfbc;border-radius:8px}@media(max-width:600px){figure{max-width:100%;margin-right:0}h2{font-size:19px}}</style><h1>${htmlEscape(title)}</h1><p>来源：${htmlEscape(manifest.sourceLabel)}</p>${manifest.localSourceId ? `<p>文件记录ID：${htmlEscape(manifest.localSourceId)}</p>` : ""}<p>作品ID：${htmlEscape(manifest.workId || "未关联本地视频")}</p><p>${htmlEscape(limits)}</p><p>${manifest.bodyCount} 段正文候选${manifest.recoveryCount ? ` / ${manifest.recoveryCount} 段待确认文字` : ""} / ${plan.imageCount} 张画面${plan.missingSegments ? ` / ${plan.missingSegments} 段缺图` : ""}</p>${plan.rows.map(row => `<section data-layer="${row.layer === "recovery" ? "recovery" : "body"}"><h2>${htmlEscape(rowHeading(row))}</h2><p>${htmlEscape(display(row.segment)).replace(/\n/g,"<br>")}</p>${htmlNotes(row.segment)}${row.images.map(frame => `<figure><img loading="lazy" src="${encodeURI(frame.path)}" alt="${time(frame.time)} 视频采样画面"><figcaption>${time(frame.time)} 采样</figcaption></figure>`).join("")}${row.missing ? "<p>本句画面未保留，未使用其他句的画面替代。</p>" : ""}</section>`).join("")}${typeof edits.plain === "string" || typeof edits.timed === "string" ? `<section><h2>独立人工编辑稿</h2><p>未自动重绑原时间和配图。</p><pre>${htmlEscape(edits.plain ?? edits.timed)}</pre></section>` : ""}</html>`;
    return { manifest, markdown: md.join("\n"), html, csv };
  }
  function jpeg(canvas, signal) { return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (error, blob) => { if (settled) return; settled = true; clearTimeout(timer); signal?.removeEventListener("abort", aborted); error ? reject(error) : resolve(blob); };
    const aborted = () => finish(new Error("画面保存已停止"));
    const timer = setTimeout(() => finish(new Error("采样画面保留超时")), 5000);
    signal?.addEventListener("abort", aborted, { once: true });
    if (signal?.aborted) return aborted();
    try { canvas.toBlob(blob => blob?.size ? finish(null, blob) : finish(new Error("未能保留采样画面")), "image/jpeg", .82); }
    catch (error) { finish(error); }
  }); }
  class Collector {
    constructor({ id, source, region, store, isCurrent = () => true }) { this.id = id; this.source = source; this.region = region; this.store = store; this.isCurrent = isCurrent; this.frames = new Map(); this.persistedIndices = new Set(); this.bytes = 0; this.warning = ""; this.persistenceComplete = Boolean(store); }
    async capture(canvas, time, index, signal) {
      if (signal?.aborted || !this.isCurrent()) return;
      try {
        const copy = document.createElement("canvas"), scale = Math.min(1, 720 / canvas.width, 1280 / canvas.height);
        copy.width = Math.max(1, Math.round(canvas.width * scale)); copy.height = Math.max(1, Math.round(canvas.height * scale));
        copy.getContext("2d").drawImage(canvas, 0, 0, copy.width, copy.height);
        // Sampling extent is not a caption mask. Persist the complete RGB grid
        // through the existing vector field so IDB restoration keeps it too.
        const facts = fingerprint(copy), blob = await jpeg(copy, signal);
        if (signal?.aborted || !this.isCurrent()) return;
        const previous = this.frames.get(index), bytes = this.bytes + blob.size - (previous?.blob.size || 0);
        if ((!previous && this.frames.size >= MAX_FRAMES) || bytes > MAX_FRAME_BYTES) throw new Error("本次画面保留达到容量上限，字幕仍继续提取");
        const frame = { index, time, width: copy.width, height: copy.height, ...facts, blob,
          ...(this.region ? { captionRegion: { top: this.region.top, bottom: this.region.bottom } } : {}) };
        this.frames.set(index, frame); this.bytes = bytes;
        if (this.store) {
          try { await this.store.put(this.id, this.source, frame, signal); this.persistedIndices.add(index); }
          catch (error) {
            // A blocked disk store must not add a timeout to every later OCR
            // frame. Current in-memory pictures remain exportable.
            this.persistenceComplete = false;
            if (!signal?.aborted) { this.store = null; this.warning = String(error?.message || "画面未能保留到本机；请在关闭前导出工作包"); }
          }
        }
      } catch (error) { this.warning = String(error?.message || "部分画面未能保留"); }
    }
    plan(result) { return select(result, [...this.frames.values()]); }
    isPersisted(result) { return this.plan(result).rows.every(row => row.images.every(frame => this.persistedIndices.has(frame.index))); }
  }
  return { MAX_FRAME_BYTES, MAX_FRAMES, FULL, GRID_WIDTH, GRID_HEIGHT, fingerprint, distance, compareAppearance, nativeSamples, select, textPlan, documents, Collector };
});
