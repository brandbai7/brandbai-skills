/* Text-only business outputs. Observation times are never promoted to an SRT axis. */
(function (root, factory) {
  const sourceApi = typeof module === "object" && module.exports && typeof require === "function" ? require("./subtitle-source.js") : root.BrandbaiSubtitleSource;
  const api = factory(sourceApi);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.BrandbaiSubtitleOutput = api;
})(globalThis, function (sourceApi) {
  "use strict";
  function time(value) {
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "时间待确认";
    const n = Math.round(value * 100);
    return `${String(Math.floor(n / 6000)).padStart(2, "0")}:${String(Math.floor(n % 6000 / 100)).padStart(2, "0")}.${String(n % 100).padStart(2, "0")}`;
  }
  function body(result, mode = "timed") {
    return (result?.segments || []).map(row => {
      const text = result?.outputPolicy === "clean-business-text-v200" ? String(row?.text || "") : isWorkingGroup(row) ? displayText(row) : workingText(row);
      if (mode === "plain") return text;
      const first = time(row.firstObserved), last = time(row.lastObserved);
      const known = first !== "时间待确认" && last !== "时间待确认" && row.lastObserved >= row.firstObserved;
      return `${known ? `[${first}–${last}]` : "[时间待确认]"} ${text}`;
    }).join("\n");
  }
  function isWorkingGroup(row) { return ["subtitle-working-group-v198", "subtitle-progressive-working-v199"].includes(row?.workingGroupSchema) && row.presentationOnly === true; }
  // A work view groups observations, not facts. The selected actual reading is
  // shown once, while every unresolved candidate remains separately visible.
  function criticalNotices(row) {
    const notices = [], seen = new WeakSet(), keys = new Set();
    function visit(value) {
      if (!value || typeof value !== "object" || seen.has(value)) return;
      seen.add(value);
      const status = value.criticalReadingStatus;
      if (status?.hasCriticalConflict && !status.evidenceIncomplete && !["invalid_actual_read_binding", "invalid_source_bound_readings"].includes(status.status)) {
        const candidates = [...new Set((status.candidates || []).map(candidate => String(candidate.text || "")).filter(Boolean))];
        const eventId = String(value.id || value.eventId || "");
        const key = JSON.stringify([eventId, status.schema, status.status, candidates]);
        if (!keys.has(key)) {
          keys.add(key); notices.push({ eventId, status: status.status || "unresolved_reading_difference", candidates,
            selectedText: String(value.text || ""), firstObserved: value.firstObserved, lastObserved: value.lastObserved,
            hasCriticalConflict: true, semanticCorrectnessVerified: false, resolved: false });
        }
      }
      for (const child of value.originalEventSegments || []) visit(child);
      for (const child of value.originalProjectedWorkingCues || []) visit(child);
      for (const child of value.compoundLayout?.originalSegments || []) visit(child);
      for (const child of value.sourceSegments || []) visit(child);
    }
    visit(row);
    if (!notices.length && row?.presentationNotice?.hasCriticalConflict && new Set(row.presentationNotice.distinctCandidateTexts || []).size > 1) notices.push({ eventId: row.id || "", status: "retained_raw_protected_reading_difference",
      candidates: [...new Set(row.presentationNotice.distinctCandidateTexts || [])], selectedText: String(row.text || ""),
      firstObserved: row.firstObserved, lastObserved: row.lastObserved, hasCriticalConflict: true, semanticCorrectnessVerified: false, resolved: false });
    return notices;
  }
  function candidateText(row) {
    const notices = criticalNotices(row);
    if (!notices.length && !row?.ambiguousActualReadings) return "";
    const candidates = [...new Set([...notices.flatMap(notice => notice.candidates.length ? notice.candidates : [notice.selectedText]),
      ...(row?.ambiguousActualReadings ? (row.presentationVariants || row.variants || []).map(variant => variant.text || variant.actualText) : [])].filter(Boolean))];
    return ["读数有分歧，尚未核对；以下均为实际识别候选。", ...candidates.map((value, index) => `候选 ${index + 1}：${value}`)].join("\n");
  }
  function displayText(row) {
    const text = String(row?.text ?? "");
    return isWorkingGroup(row) && row.ambiguousActualReadings ? `${text}［不同读数候选，尚未确定］`
      : isWorkingGroup(row) && criticalNotices(row).length ? `${text}［读数待核对］` : text;
  }
  function hasCriticalNotice(row){return criticalNotices(row).length>0;}
  function reviewItems(result) {
    const items = [];
    for (const [segmentIndex, row] of (result?.segments || []).entries()) {
      const texts = [...new Set([...criticalNotices(row).flatMap(n => n.candidates),
        ...(row?.ambiguousActualReadings ? (row.presentationVariants || row.variants || []).map(v => v.text || v.actualText) : [])].filter(v => typeof v === "string" && v.trim()))];
      const common = { segmentIndex, text: String(row?.text || ""), firstObserved: row.firstObserved, lastObserved: row.lastObserved };
      if (texts.length > 1) items.push({ ...common, kind: "different_readings", candidates: texts, message: "这处文字有不同识别结果，可对照视频核对；正文保留当前选定原读。" });
      const seen = new WeakSet();
      function incomplete(value) {
        if (!value || typeof value !== "object" || seen.has(value)) return false;
        seen.add(value); const status = value.criticalReadingStatus;
        if (status?.evidenceIncomplete || ["invalid_actual_read_binding", "invalid_source_bound_readings"].includes(status?.status)) return true;
        return [...(value.originalEventSegments || []), ...(value.originalProjectedWorkingCues || []), ...(value.compoundLayout?.originalSegments || []), ...(value.sourceSegments || [])].some(incomplete);
      }
      if (incomplete(row)) items.push({ ...common, kind: "evidence_incomplete", candidates: [], message: "这段来源记录的校验未完成，不代表发现了不同读法；已有文字和原始记录已保留。" });
    }
    return items;
  }
  function reviewText(result, source) {
    const items = reviewItems(result);
    return ["字幕疑点与处理说明", ...(sourceApi ? sourceApi.lines(source) : []), "正文与本清单独立保存；以下时间为采样观察范围，不是精确字幕轴。", "",
      ...items.flatMap(item => [`分段 ${item.segmentIndex + 1} [${time(item.firstObserved)}–${time(item.lastObserved)}]`, item.message,
        `当前原读：${item.text}`, ...item.candidates.map((text, i) => `识别结果 ${i + 1}：${text}`), ""]),
      ...(items.length ? [] : ["本次没有需要单独列出的识别分歧；不代表已经人工核实全文。", ""])].join("\n");
  }
  function workingText(row){if(isWorkingGroup(row))return candidateText(row)?`${displayText(row)}\n${candidateText(row)}`:String(row.text||'');const text=String(row?.text??''),parts=row?.compoundLayout?.originalSegments;if(parts?.some(hasCriticalNotice))return parts.map(workingText).join('\n');const originals=row?.originalEventSegments;if(originals?.some(hasCriticalNotice)){const notices=[...new Set(originals.filter(hasCriticalNotice).map(workingText))];return `[本段有关键字读数分歧，合并前记录仍保留]\n${notices.join('\n')}`;}if(!row?.criticalReadingStatus?.hasCriticalConflict)return text;const candidates=[...new Set((row.criticalReadingStatus.candidates||[]).map(c=>String(c.text||'')).filter(Boolean))];return `[关键字读数有分歧，请对照本句画面]\n${candidates.length?candidates.map((s,i)=>`候选 ${i+1}：${s}`).join('\n'):text}`;}
  function isPipeline(result) { return typeof result?.pipelineId === "string" && Boolean(result.pipelineId) || result?.skipLegacyFinalize === true; }
  function layers(result) {
    return [{ id: "body", label: "主正文候选", rows: result?.segments || [] },
      { id: "recovery", label: "待补读与待核对文字", rows: result?.captionRecovery || [] },
      { id: "screen", label: "其他屏幕文字", rows: result?.screenText || [] }];
  }
  function text(result, source, mode, edited = null) {
    const phase = ["ready", "running", "paused", "partial", "cancelled", "failed", "restored"].includes(result?.state) ? "已有文字；处理状态请结合原始记录核对" : "已处理所选区域；未全文人工核验";
    return [`视频画面字幕 · ${mode === "plain" ? "正文" : "采样时间稿"}${edited !== null ? " · 人工编辑稿" : ""}`,
      ...(sourceApi ? sourceApi.lines(source) : [`作品：${source?.title || source?.workId || "视频字幕结果"}`, `作品ID：${source?.workId || "未关联"}`, "来源：待确认"]),
      "识别方式：画面文字识别，不是音频转写或发布文案。", `状态：${phase}`,
      mode === "plain" ? "正文不带时间；连续重复沿用原识别整理规则，不全文删重。" : "时间是采样观察范围，不是精确字幕轴。",
      ...(isPipeline(result) ? ["正文为机器分流候选，未确认全部文字角色或全文正确；其他屏幕文字和待补读内容独立保留在工作资料中。"] : []),
      edited !== null ? "人工编辑只修改当前文字稿，未改动原始识别；正文稿与时间稿的修改独立保留。" : "可能漏字、错字或混入画面文字；对外发布和商品宣称需核实。",
      "", edited ?? body(result, mode), "",
      ...(result?.outputPolicy !== "clean-business-text-v200" && edited === null && (result?.segments || []).some(row => isWorkingGroup(row) && candidateText(row))
        ? ["需要核对的读数（工作稿中的标记对应以下分段）", "",
          ...(result.segments || []).flatMap((row, index) => isWorkingGroup(row) && candidateText(row)
            ? [`分段 ${index + 1} ${`[${time(row.firstObserved)}–${time(row.lastObserved)}]`}`, candidateText(row), ""] : [])] : [])].join("\n");
  }
  function workText(result, source, mode = "timed", edited = null) {
    const main = text(result, source, mode, edited);
    if (!isPipeline(result)) return main;
    const extra = layers(result).slice(1).map(layer => [layer.label, "下列为机器原读候选，不自动拼入正文，也不代表口播或商品宣称。",
      body({ segments: layer.rows }, mode) || "本次未形成此层文字；不代表画面不存在。"].join("\n"));
    const checkpoint = result?.precisionCheckpoint;
    const count = key => Array.isArray(checkpoint?.[key]) ? checkpoint[key].length : 0;
    return [main.trimEnd(), "", ...extra.flatMap(section => [section, ""]),
      `补读记录：完成 ${count("completed")} 个事件；待补读 ${count("pending")} 个；失败 ${count("failed")} 个。完成数量不代表全文已核对正确。`, ""].join("\n");
  }
  function cell(value) {
    let text = String(value ?? "");
    // Excel formula injection includes leading whitespace/control characters.
    if (/^[\s\u0000-\u001f]*[=+@-]/u.test(text)) text = "'" + text;
    return `"${text.replace(/"/g, '""')}"`;
  }
  function csv(result, source) {
    const descriptor = sourceApi?.describe(source);
    const header = ["作品ID", "作品标题", "分段", "首次采样秒", "末次采样秒", "首次采样时间", "末次采样时间", "机器整理文字", "校对提示", "时间依据", "识别状态", "视频来源", "来源类型", "文件记录ID"];
    const pipeline = isPipeline(result);
    if (pipeline) header.push("文字层", "事件ID", "原始行索引", "实际画面索引", "实际画面ID", "行与画面证据原文", "角色依据");
    const inputRows = pipeline ? layers(result).flatMap(layer => layer.rows.map(row => ({ row, layer }))) : (result?.segments || []).map(row => ({ row }));
    const rows = inputRows.map(({ row, layer }, index) => {
      const first = time(row.firstObserved), last = time(row.lastObserved);
      const known = first !== "时间待确认" && last !== "时间待确认" && row.lastObserved >= row.firstObserved;
      const values = [descriptor?.workId || "", descriptor?.title || source?.title || "视频字幕结果", index + 1, known ? row.firstObserved : "", known ? row.lastObserved : "",
        known ? first : "时间待确认", known ? last : "时间待确认", row.text, isWorkingGroup(row) && candidateText(row) ? candidateText(row) : hasCriticalNotice(row) ? workingText(row) : row.reviewReason || "未全文人工核验",
        "采样观察范围，非精确字幕轴", result?.state || "未知", descriptor?.label || "来源待确认", descriptor?.sourceKind || "unknown", descriptor?.localSourceId || ""];
      if (pipeline) {
        const rowIndices = Array.isArray(row.rowIndices) ? row.rowIndices : [];
        const evidence = rowIndices.map(rowIndex => {
          const raw = result?.raw?.rows?.[rowIndex], frame = raw && result?.raw?.frames?.[raw.frameIndex];
          return raw && raw.index === rowIndex && frame?.frameIndex === raw.frameIndex && frame.frameId === raw.frameId && frame.time === raw.time
            ? { rowIndex, frameIndex: raw.frameIndex, frameId: raw.frameId, time: raw.time, rawReading: raw }
            : { rowIndex, status: "own_frame_evidence_missing" };
        });
        values.push(layer.label, row.id || "", JSON.stringify(rowIndices), JSON.stringify(row.observationIndices || []), JSON.stringify(row.frameIds || []),
          JSON.stringify(evidence), "机器分流候选；文字角色和全文正确性未确认");
      }
      return values;
    });
    return [header, ...rows].map(row => row.map(cell).join(",")).join("\r\n") + "\r\n";
  }
  // Export the complete inert result rather than flattening rows into captions.
  // This record is evidence only; sourceIdentity is not a player capability.
  function records(result, source) {
    return JSON.parse(JSON.stringify({ schema: "brandbai-subtitle-layered-evidence-v193", source: sourceApi?.describe(source) || source || {},
      accuracy: "machine_unverified", timeBasis: "sampled_observation_range", roleConfirmed: false, result }));
  }
  return { time, body, text, workText, workingText, displayText, isWorkingGroup, criticalNotices, candidateText, hasCriticalNotice, reviewItems, reviewText, layers, records, csv };
});
