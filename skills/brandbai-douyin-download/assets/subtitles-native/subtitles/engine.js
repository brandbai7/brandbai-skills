/* Local, opt-in screen-subtitle extraction. No audio, platform API or cloud calls. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.BrandbaiSubtitles = api;
})(typeof globalThis === "undefined" ? this : globalThis, function () {
  "use strict";
  const visualApi = () => globalThis.BrandbaiSubtitleVisualEvents || (typeof require === "function" ? require("../lib/subtitle-visual-events.js") : null);
  const sourceApi = () => globalThis.BrandbaiSubtitleSource || (typeof require === "function" ? require("../lib/subtitle-source.js") : null);
  const finalApi = () => globalThis.BrandbaiSubtitleFinalize || (typeof require === "function" ? require("../lib/subtitle-finalize.js") : null);
  const readingEvidenceApi = () => globalThis.BrandbaiSubtitleReadingEvidence || (typeof require === "function" ? require("../lib/subtitle-reading-evidence.js") : null);
  const READING_POLICY = "source-separated-exact-v189";
  const ENGINE_BUILD = "0.11.189";
  const LIMITS = Object.freeze({ seconds: 180, bytes: 150 * 1024 * 1024, frames: 720 });
  const DEFAULT_REGION = Object.freeze({ left: 0.05, top: 0.76, right: 0.95, bottom: 0.80 });
  // Only these fixed page-frame codes may become a user-visible diagnostic.
  // Provider/worker exception messages may contain native URLs or signatures.
  const PAGE_FRAME_MESSAGES = Object.freeze({
    PAGE_FRAMES_UNAVAILABLE: "当前页面播放器无法确认，请重新打开字幕提取",
    PAGE_CHANGED: "作品或播放器已变化，已停止读取画面",
    PAGE_HIDDEN: "页面已隐藏，已停止读取画面",
    CONSENT_REQUIRED: "使用授权已变化，已停止读取画面",
    PLAYER_NOT_READY: "视频画面尚未准备好，请播放后重试",
    PAGE_FRAME_TIMEOUT: "画面读取等待超时，本次提取暂时停止",
    SUBTITLE_INTENT_EXPIRED: "本次提取暂时停止，请重试提取",
    SUBTITLE_SENDER_REJECTED: "字幕功能暂时无法读取画面，请重试提取",
    PIXELS_UNREADABLE: "浏览器不允许读取这个播放器的画面",
    INVALID_FRAME_REQUEST: "画面读取参数无效",
    VIDEO_RANGE_UNAVAILABLE: "当前播放器无法定位整条视频，已停止读取画面",
    VIDEO_TIMEOUT: "视频缓冲或解码等待超时，已停止读取画面",
    DECODE_FAILED: "视频画面解码失败，已停止读取画面",
    USER_INTERRUPTED: "检测到播放器操作，已停止读取画面",
    FRAME_TOO_LARGE: "视频画面超出处理范围",
    SESSION_EXPIRED: "页面画面任务已过期，请重新开始",
    SESSION_CLOSED: "页面画面任务已结束，请重新开始",
    SESSION_BUSY: "页面画面任务正在读取，请稍后重试",
  });
  function region(value = DEFAULT_REGION) {
    const result = Object.fromEntries(["left", "top", "right", "bottom"].map(k => [k, Number(value[k])]));
    if (Object.values(result).some(n => !Number.isFinite(n) || n < 0 || n > 1)
      || result.right - result.left < 0.05 || result.bottom - result.top < 0.02) {
      throw new Error("请选择有效的字幕区域");
    }
    return result;
  }
  function sampleTimes(duration, interval = 0.5) {
    if (!Number.isFinite(duration) || duration <= 0 || duration > LIMITS.seconds) throw new Error("首版仅支持 3 分钟以内的视频");
    if (!Number.isFinite(interval) || interval < 0.25 || interval > 1) throw new Error("采样间隔应为 0.25—1 秒");
    const times = [];
    for (let t = 0; t < duration; t += interval) times.push(Math.min(t + 0.05, duration - 0.001));
    if (times.length > LIMITS.frames) throw new Error("视频超出本次处理预算");
    return times;
  }
  function normalizeText(text) {
    return String(text || "").normalize("NFC").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "")
      .split(/\r?\n/).map(line => line.trim().replace(/[ \t]+/g, " ")).filter(Boolean).join("\n");
  }
  // Comparison only: OCR can insert horizontal gaps inside the same Han/Kana
  // sentence. Never erase Latin/Hangul word spaces, number/unit spacing or line
  // breaks, and never substitute lookalike characters. Raw observations and
  // representative candidates retain their own actual text and sample times.
  function comparisonSpacing(text) {
    return text.replace(/(?<=[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}])[ \t\u00a0\u1680\u2000-\u200b\u202f\u205f\u2060\u3000\ufeff]+(?=[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}])/gu, "");
  }
  function acceptable(data) {
    const text = normalizeText(data?.text);
    return text && (text.match(/[\p{L}\p{N}]/gu) || []).length >= 2
      && Number.isFinite(Number(data?.confidence)) && Number(data?.confidence) >= 80;
  }
  // These keys are only for comparing adjacent observations. They are never exported
  // as captions: a chosen caption must have actually been returned by the recognizer.
  function comparisonKey(text) {
    let key = comparisonSpacing(normalizeText(text));
    if (/(?:https?:\/\/|www\.)/i.test(key)) return key;
    key = key.replace(/^[·。，、．.,!?！？:：;；"'“”‘’「」『』`~～()（）\[\]【】{}〈〉《》<>\\|_*\s]+|[·。，、．.,!?！？:：;；"'“”‘’「」『』`~～()（）\[\]【】{}〈〉《》<>\\|_*\s]+$/gu, (edge, offset, original) => {
      // A full-width decimal point can occur at the crop edge; do not interpret
      // it as punctuation around a number, including an incomplete decimal.
      if (offset === 0 && /[．.]$/u.test(edge) && /\p{Nd}/u.test(original[edge.length] || "")) return edge.at(-1);
      if (offset > 0 && /^[．.]/u.test(edge) && /\p{Nd}/u.test(original[offset - 1] || "")) return edge[0];
      return "";
    });
    // Only compare an em-dash before a long Chinese clause as edge decoration;
    // never fold signed numbers or a hyphen/Latin-unit expression this way.
    if (/^—+\p{Script=Han}/u.test(key) && (key.match(/\p{Script=Han}/gu) || []).length >= 4) key = key.replace(/^—+/u, "");
    // A single edge hash can be OCR decoration around a single Chinese line.
    // Embedded/multiple tags, multiline captions, C#, URLs and a hash-only
    // observation remain intact. This comparison never edits a displayed line.
    if (!key.includes("\n") && (key.match(/[#＃]/gu) || []).length === 1 && /(?:^[#＃]|[#＃]$)/u.test(key)
      && !/[A-Za-z]/u.test(key) && (key.match(/\p{Script=Han}/gu) || []).length >= 4) key = /^[#＃]/u.test(key) ? key.slice(1).trimStart() : key.slice(0, -1).trimEnd();
    // Only the em dash directly after the last Chinese glyph is decoration.
    // Other signs, numerical endings and interior dashes keep their meaning.
    if (!key.includes("\n") && /\p{Script=Han}—$/u.test(key)
      && (key.match(/\p{Script=Han}/gu) || []).length >= 4) key = key.slice(0, -1);
    return key;
  }
  function displayText(text) {
    const value = normalizeText(text);
    // Keep the previous version's harmless edge-dot cleanup, limited to Chinese
    // clauses. No word is added, changed or removed. Numbers, URLs, Latin tokens,
    // hashes and interior punctuation are untouched; selected raw text is retained.
    if (/[\p{N}A-Za-z#＃]/u.test(value) || (value.match(/\p{Script=Han}/gu) || []).length < 4) return value;
    return value.replace(/^[·．.]+(?=\p{Script=Han})/u, "").replace(/(?<=\p{Script=Han})[·．.]+$/u, "");
  }
  function protectedSignature(text) {
    // Keep the original decimal point, percent sign and sign instead of reducing
    // numbers to digits. Latin tokens include units such as C, mg and ml.
    return JSON.stringify([
      text.match(/[+\-−－]?\s*(?:\p{Nd}+(?:[.．]\p{Nd}*)?|[.．]\p{Nd}+)(?:\s*[%％])?/gu) || [],
      text.match(/[负正]?[零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟萬億点]+/gu) || [],
      text.match(/[A-Za-z]+|千克|公斤|毫克|毫升|分钟|小时|厘米|毫米|摄氏度|百分之|克|斤|升|杯|次|片|粒|瓶|袋|天|周|月|年|度/gu) || [],
      text.match(/不(?:能|是|会|要|再|用|需|得|可)?|没(?:有)?|无(?:需|法)?|未(?:必|能)?|非|勿|别|莫/gu) || [],
    ]);
  }
  function sameKey(a, b) { return a === b && protectedSignature(a) === protectedSignature(b); }
  function isFragment(shorter, longer) {
    const missing = Array.from(longer).length - Array.from(shorter).length;
    return Array.from(shorter).length >= 8 && missing > 0 && missing <= 2
      && (longer.startsWith(shorter) || longer.endsWith(shorter))
      && !/[不没无未非勿别莫]$/u.test(shorter)
      && !/(?:我叫|名叫|姓名|作者|嘉宾|达人|名为|叫做|先生|女士|老师|演员|明星|艺人|歌手|导演|医生)/u.test(longer)
      && protectedSignature(shorter) === protectedSignature(longer);
  }
  function sameFamily(a, b) { return sameKey(a, b) || isFragment(a, b) || isFragment(b, a); }
  function nearText(a, b) {
    const left = Array.from(a), right = Array.from(b);
    if (Math.min(left.length, right.length) < 4 || Math.abs(left.length - right.length) > 2) return false;
    let row = Array.from({ length: right.length + 1 }, (_, i) => i);
    for (let i = 1; i <= left.length; i++) {
      const next = [i];
      for (let j = 1; j <= right.length; j++) next[j] = Math.min(next[j - 1] + 1, row[j] + 1, row[j - 1] + (left[i - 1] === right[j - 1] ? 0 : 1));
      row = next;
    }
    return row[right.length] <= 2;
  }
  function copyReading(data, mode) {
    const reading = { mode, text: String(data?.text || ""), confidence: Number(data?.confidence || 0) };
    if (Array.isArray(data?.charConfidences)) reading.charConfidences = data.charConfidences
      .filter(value => Number.isFinite(value) || (typeof value?.text === "string" && Number.isFinite(value.confidence)))
      .map(value => Number.isFinite(value) ? value : { text: value.text, confidence: value.confidence });
    if (Number.isFinite(data?.minCharConfidence)) reading.minCharConfidence = data.minCharConfidence;
    const alignment = data?.tokenAlignment;
    if (alignment?.schema === "ctc-temporal-bands-v1" && ["sourceWidth", "sourceHeight", "modelWidth", "contentWidth", "steps"].every(k => Number.isSafeInteger(alignment[k]) && alignment[k] > 0)
      && Array.isArray(alignment.bands) && alignment.bands.length <= 1000 && alignment.bands.map(b => b?.text || "").join("") === reading.text
      && alignment.bands.every(b => typeof b.text === "string" && Number.isFinite(b.confidence) && b.confidence >= 0 && b.confidence <= 100
        && ["left", "right", "peak"].every(k => Number.isFinite(b[k])) && b.left >= 0 && b.left <= b.peak && b.peak <= b.right && b.right <= alignment.sourceWidth)) {
      reading.tokenAlignment = { schema: alignment.schema,
        ...Object.fromEntries(["sourceWidth", "sourceHeight", "modelWidth", "contentWidth", "steps"].map(k => [k, alignment[k]])),
        bands: alignment.bands.map(b => ({ text: b.text, confidence: b.confidence, left: b.left, right: b.right, peak: b.peak,
          ...Object.fromEntries(["firstStep", "lastStep", "peakStep"].filter(k => Number.isSafeInteger(b[k]) && b[k] >= 0 && b[k] < alignment.steps).map(k => [k, b[k]])) })) };
    }
    const cropEvidence = data?.cropEvidence;
    if (cropEvidence?.schema === "outlined-caption-spatial-crop-v1" && Number.isSafeInteger(cropEvidence.inputWidth) && Number.isSafeInteger(cropEvidence.inputHeight)
      && cropEvidence.inputWidth > 0 && cropEvidence.inputHeight > 0 && cropEvidence.box
      && ["left", "right", "top", "bottom"].every(k => Number.isSafeInteger(cropEvidence.box[k]))
      && cropEvidence.box.left >= 0 && cropEvidence.box.right <= cropEvidence.inputWidth && cropEvidence.box.right > cropEvidence.box.left
      && cropEvidence.box.top === 0 && cropEvidence.box.bottom === cropEvidence.inputHeight) {
      reading.cropEvidence = { schema: cropEvidence.schema, inputWidth: cropEvidence.inputWidth, inputHeight: cropEvidence.inputHeight, box: { ...cropEvidence.box } };
    }
    const assessment=readingEvidenceApi()?.copyAssessment(data?.cropAssessment);
    if(assessment)reading.cropAssessment=assessment;
    if(['original','white','spatial_candidate'].includes(data?.selectedReadingId))reading.selectedReadingId=data.selectedReadingId;
    return reading;
  }
  function finalizeResult(result, options = {}) { return finalApi()?.finalize(result, options) || result; }
  function restoreFinalization(result) { return finalApi()?.restore(result) || result; }
  function readings(observation) {
    const unique = new Map();
    for (const reading of [observation, ...(observation.alternatives || [])]) {
      if (["original_uncropped", "spatial_candidate"].includes(reading.mode)) continue;
      const text = normalizeText(reading.text);
      if (!acceptable(reading)) continue;
      const previous = unique.get(text);
      // Identical strings from one frozen frame are one vote. A transformed
      // image's confidence is not calibrated against the original image: keep
      // original character evidence instead of replacing it with a larger score.
      const sourcePriority = Number(reading.mode === "original") - Number(previous?.mode === "original");
      if (!previous || sourcePriority > 0 || (sourcePriority === 0 && previous.confidence < reading.confidence)) unique.set(text, { ...reading, text });
    }
    return Array.from(unique.values());
  }
  function candidateList(observations, anchor) {
    const candidates = new Map();
    for (const observation of observations) for (const reading of readings(observation)) {
      if (!sameKey(comparisonKey(reading.text), anchor)) continue;
      const previous = candidates.get(reading.text) || { text: reading.text, frames: 0, confidence: 0, firstObserved: observation.time, lastObserved: observation.time };
      previous.frames++; previous.confidence += reading.confidence; previous.lastObserved = observation.time;
      candidates.set(reading.text, previous);
    }
    return Array.from(candidates.values()).map(candidate => ({ ...candidate, confidence: candidate.confidence / candidate.frames }));
  }
  function sharedObservedAnchor(observations, allObservations = observations, interval = 0.5) {
    // This is not fuzzy replacement. Every sampled frame must itself contain
    // the same complete reading in one of its image passes. A nearby sentence,
    // a previous caption or a single-frame double pass cannot supply that vote.
    if (observations.length < 2) return "";
    const selected = observations.map(value => comparisonKey(value.text));
    if (selected.some(value => (value.match(/\p{Script=Han}/gu) || []).length < 8
      || /[A-Za-z#＃]|https?:\/\//iu.test(value)
      || /(?:我叫|名叫|姓名|作者|嘉宾|达人|名为|叫做|先生|女士|老师|演员|明星|艺人|歌手|导演|医生)/u.test(value))) return "";
    const possible = new Set(readings(observations[0]).map(value => comparisonKey(value.text)));
    const originals = observations.flatMap(value => (value.alternatives || [])
      .filter(reading => reading.mode === "original" && acceptable(reading)).map(reading => comparisonKey(reading.text)));
    const stableOriginals = originalVotes(observations).filter(candidate => candidate.frames >= 2);
    const anchors = Array.from(possible).filter(anchor =>
      (anchor.match(/\p{Script=Han}/gu) || []).length >= 8
      && !/[A-Za-z#＃]|(?:我叫|名叫|姓名|作者|嘉宾|达人|名为|叫做|先生|女士|老师|演员|明星|艺人|歌手|导演|医生)/u.test(anchor)
      &&
      selected.every(key => protectedSignature(key) === protectedSignature(anchor) && nearText(key, anchor))
      && originals.every(key => protectedSignature(key) === protectedSignature(anchor)
        && (sameKey(key, anchor) || !/(?:我叫|名叫|姓名|作者|嘉宾|达人|名为|叫做|先生|女士|老师|演员|明星|艺人|歌手|导演|医生)/u.test(key)))
      && !stableOriginals.some(candidate => candidate.key !== anchor)
      && !originalVotes(adjacentContext(allObservations, observations[0], anchor, interval))
        .some(candidate => candidate.key !== anchor && candidate.frames >= 2)
      && observations.every(observation => readings(observation).some(value => sameKey(comparisonKey(value.text), anchor))));
    const score = anchor => observations.reduce((sum, observation) => sum + Math.max(...readings(observation)
      .filter(value => sameKey(comparisonKey(value.text), anchor)).map(value => value.confidence)), 0);
    anchors.sort((a, b) => score(b) - score(a));
    return anchors[0] || "";
  }
  function adjacentContext(observations, first, anchor, interval) {
    const values = [];
    for (let index = first.index; index < observations.length; index++) {
      const value = observations[index], previous = values.at(-1);
      if (!value.accepted || value.time - first.time > 6
        || (previous && (value.time <= previous.time || value.time - previous.time > interval * 1.6))
        || !nearText(comparisonKey(value.text), anchor)
        || protectedSignature(comparisonKey(value.text)) !== protectedSignature(anchor)) break;
      values.push(value);
    }
    return values;
  }
  function reviewableKey(key) {
    return (key.match(/\p{Script=Han}/gu) || []).length >= 8
      && !/[A-Za-z#＃]|(?:我叫|名叫|姓名|作者|嘉宾|达人|名为|叫做|先生|女士|老师|演员|明星|艺人|歌手|导演|医生)/u.test(key);
  }
  function originalVotes(observations) {
    const votes = new Map();
    for (const observation of observations) {
      // A processed image is useful corroboration, but cannot invent the
      // representative or outvote the unprocessed source frames.
      const keys = new Map();
      for (const reading of observation.alternatives || []) {
        if (reading.mode !== "original" || !acceptable(reading)) continue;
        const key = comparisonKey(reading.text);
        if (!reviewableKey(key)) continue;
        const previous = keys.get(key);
        if (!previous || previous.confidence < reading.confidence) keys.set(key, reading);
      }
      for (const [key, reading] of keys) {
        const candidate = votes.get(key) || { key, frames: 0, confidence: 0 };
        candidate.frames++; candidate.confidence += reading.confidence; votes.set(key, candidate);
      }
    }
    return Array.from(votes.values()).map(value => ({ ...value, confidence: value.confidence / value.frames }));
  }
  function reviewAnchors(observations) {
    if (observations.some(value => !(value.alternatives || []).some(reading => reading.mode === "original"))) return [];
    const keys = observations.map(value => comparisonKey(value.text));
    if (!keys.every(reviewableKey)) return [];
    const audience = text => (text.match(/女生|男生|女性|男性|儿童|成人|孕妇/gu) || []).join("|");
    return originalVotes(observations).filter(candidate => keys.every(key =>
      nearText(key, candidate.key) && protectedSignature(key) === protectedSignature(candidate.key)
      && !(audience(key) && audience(candidate.key) && audience(key) !== audience(candidate.key))));
  }
  function groupForReview(segments, observations, interval) {
    const blocks = []; let block = null;
    for (const segment of segments) {
      const indices = segment.observationIndices;
      const previous = block?.segments.at(-1);
      const nextObservations = [...(block?.observations || []), ...indices.map(index => observations[index])];
      const contiguous = previous && segment.firstObserved > previous.lastObserved
        && segment.firstObserved - previous.lastObserved <= interval * 1.6
        && indices[0] === previous.observationIndices.at(-1) + 1
        && segment.lastObserved - block.observations[0].time <= 6;
      if (!contiguous || !reviewAnchors(nextObservations).length) {
        block = { segments: [], observations: [] }; blocks.push(block);
      }
      block.segments.push(segment); block.observations.push(...indices.map(index => observations[index]));
    }
    const output = [];
    for (const item of blocks) {
      const anchors = reviewAnchors(item.observations).filter(candidate => candidate.frames >= 2)
        .sort((a, b) => b.frames - a.frames || b.confidence - a.confidence);
      const chosen = anchors[0];
      const competingStable = chosen && originalVotes(item.observations).some(candidate => candidate.key !== chosen.key && candidate.frames >= 2);
      // A majority shorter reading does not authorize hiding a fuller original
      // occurrence. It may be a real caption change rather than an OCR fragment.
      const fullerOriginal = chosen && item.observations.some(observation => (observation.alternatives || [])
        .some(reading => reading.mode === "original" && isFragment(chosen.key, comparisonKey(reading.text))));
      if (item.segments.length < 2 || !chosen || competingStable || fullerOriginal) { output.push(...item.segments); continue; }
      const segment = makeSegment(item.observations, chosen.key, true);
      segment.candidateGroup = true;
      segment.reviewReason = "相似句已按多帧支持自动整理，可展开核对或恢复原分段";
      segment.originalFrameVotes = chosen.frames;
      segment.reviewOptions = Array.from(new Set(item.observations.flatMap(value => readings(value).map(reading => displayText(reading.text)))));
      segment.retainedSegments = item.segments;
      output.push(segment);
    }
    return output;
  }
  function makeSegment(observations, anchor, forceReview = false) {
    const candidates = candidateList(observations, anchor).sort((a, b) => {
      const supported = Number(b.frames >= 2) - Number(a.frames >= 2);
      const decoration = (comparisonSpacing(a.text).length - anchor.length) - (comparisonSpacing(b.text).length - anchor.length);
      return supported || decoration || b.frames - a.frames || b.confidence - a.confidence || a.firstObserved - b.firstObserved;
    });
    const chosen = candidates[0];
    const conflictingReadings = observations.some(observation => readings(observation).some(reading => !sameFamily(comparisonKey(reading.text), anchor)));
    const lowCharacterConfidence = observations.some(observation => readings(observation).some(reading => reading.text === chosen.text
      && Number.isFinite(reading.minCharConfidence) && reading.minCharConfidence < 55));
    const displayed = displayText(chosen.text);
    const segment = { text: displayed, observedText: chosen.text, edgeSymbolsCleaned: displayed !== chosen.text,
      firstObserved: observations[0].time, lastObserved: observations.at(-1).time,
      confidence: Math.min(...observations.map(observation => observation.confidence)),
      observationIndices: observations.map(observation => observation.index), candidates,
      needsReview: forceReview || conflictingReadings || lowCharacterConfidence || comparisonKey(chosen.text) !== comparisonSpacing(chosen.text),
      variation: new Set(observations.flatMap(observation => readings(observation).map(reading => reading.text))).size > 1 };
    if (segment.needsReview) segment.reviewReason = forceReview || conflictingReadings ? "邻近画面文字存在未确认的变化" : lowCharacterConfidence ? "个别字符识别不确定" : "边缘符号需核对";
    return segment;
  }
  function fuseObservations(observations, interval = 0.5, options = {}) {
    if(options.policy===READING_POLICY)return fuseExactObservations(observations,interval);
    // Compatibility for historical records only. New Session tasks never use
    // these old approximate grouping stages; their finalizer owns that decision.
    const families = []; let family = null;
    for (const observation of observations) {
      if (!observation.accepted) { family = null; continue; }
      const key = comparisonKey(observation.text);
      const previous = family?.observations.at(-1);
      const contiguous = previous && observation.time - previous.time <= interval * 1.6 && observation.time > previous.time;
      const sharedAnchor = contiguous ? sharedObservedAnchor([...family.observations, observation], observations, interval) : "";
      if (!family || observation.time - previous.time > interval * 1.6 || observation.time <= previous.time
        || (!sharedAnchor && (!sameFamily(key, family.anchor)
          || (key.length > family.anchor.length && !family.observations.every(value => sameFamily(comparisonKey(value.text), key)))))) {
        family = { anchor: key, observations: [] }; families.push(family);
      } else if (sharedAnchor) {
        if (!sameKey(key, family.anchor)) family.consensusBridge = true;
        family.anchor = sharedAnchor;
      } else if (key.length > family.anchor.length) family.anchor = key;
      family.observations.push(observation);
    }
    const segments = [];
    for (const item of families) {
      if (item.consensusBridge && sharedObservedAnchor(item.observations, observations, interval)) {
        const segment = makeSegment(item.observations, item.anchor, true);
        segment.consensusBridge = true;
        segment.frameVotes = item.observations.length;
        segment.reviewReason = "多帧原图与字形图已归并近重复，请核对代表文字";
        segments.push(segment); continue;
      }
      // A full alternative is retained evidence, but repeated preprocessing
      // errors must not outrank a stable original just because they are longer.
      const possibleAnchors = new Set(item.observations.flatMap(observation => readings(observation).map(reading => comparisonKey(reading.text))));
      const originalFrames = new Map();
      for (const observation of item.observations) {
        const keys = new Set((observation.alternatives || []).filter(reading => reading.mode === "original" && acceptable(reading))
          .map(reading => comparisonKey(reading.text)));
        for (const key of keys) originalFrames.set(key, (originalFrames.get(key) || 0) + 1);
      }
      const stableOriginals = Array.from(originalFrames).filter(([, frames]) => frames >= 2);
      // A low-quality first frame may have selected a derived fallback. Re-anchor
      // only if its text has ZERO raw original occurrences, and a stable actual
      // original remains compatible with every selected observation. An observed
      // fuller original is never deleted merely because it had only one vote.
      const rawAnchorObserved = item.observations.some(observation => (observation.alternatives || [])
        .some(reading => reading.mode === "original" && sameKey(comparisonKey(reading.text), item.anchor)));
      if (!rawAnchorObserved) {
        const supported = stableOriginals.filter(([key]) => item.observations.every(value => sameFamily(comparisonKey(value.text), key)))
          .sort((a, b) => b[1] - a[1] || b[0].length - a[0].length);
        if (supported.length) item.anchor = supported[0][0];
      }
      for (const anchor of possibleAnchors) {
        if (anchor.length <= item.anchor.length || !item.observations.every(value => sameFamily(comparisonKey(value.text), anchor))) continue;
        const support = item.observations.filter(observation => readings(observation).some(reading => sameKey(comparisonKey(reading.text), anchor))).length;
        if (support >= 2 && ((originalFrames.get(anchor) || 0) >= 2 || !stableOriginals.length)) item.anchor = anchor;
      }
      const keys = new Set(item.observations.map(observation => comparisonKey(observation.text)));
      const fullFrames = item.observations.filter(observation => readings(observation).some(reading => sameKey(comparisonKey(reading.text), item.anchor))).length;
      // Repeated shorter captions can be intentional wording/name changes. Only
      // an occasional fragment (or one with same-frame full-text evidence) may
      // borrow a supported fuller observation; stable independent wording stays.
      // Stable original shortening is itself evidence of a possible real change;
      // repeated derived full text cannot silently cancel that source change.
      const stableShorter = Array.from(keys).some(key => key !== item.anchor && item.observations.filter(observation =>
        sameKey(comparisonKey(observation.text), key) && (!readings(observation).some(reading => sameKey(comparisonKey(reading.text), item.anchor))
          || (observation.alternatives || []).some(reading => reading.mode === "original" && acceptable(reading)
            && sameKey(comparisonKey(reading.text), key)))).length >= 2);
      if (keys.size === 1 || (fullFrames >= 2 && !stableShorter)) segments.push(makeSegment(item.observations, item.anchor, keys.size > 1));
      else {
        // A single fuller observation does not authorize deleting a shorter one.
        let part = [];
        for (const observation of item.observations) {
          if (part.length && !sameKey(comparisonKey(part[0].text), comparisonKey(observation.text))) {
            segments.push(makeSegment(part, comparisonKey(part[0].text), true)); part = [];
          }
          part.push(observation);
        }
        if (part.length) segments.push(makeSegment(part, comparisonKey(part[0].text), true));
      }
    }
    for (let i = 1; i < segments.length; i++) {
      const previous = segments[i - 1], current = segments[i];
      // A possible typo may equally be a changed name or statement. Preserve both.
      if (current.firstObserved - previous.lastObserved <= interval * 1.6
        && current.observationIndices[0] === previous.observationIndices.at(-1) + 1
        && nearText(comparisonKey(previous.text), comparisonKey(current.text))) {
        for (const segment of [previous, current]) { segment.needsReview = true; segment.reviewReason = "邻近画面文字存在未确认的变化"; }
      }
    }
    let final = mergeAdjacentCaptionEvents(mergeLowConfidenceEdgeVariants(mergeTransientVariants(groupForReview(segments, observations, interval), observations, interval), observations, interval), observations, interval);
    for (let i=0;i<final.length;i++) { const next=mergeVisualCaptionEvents(final,observations,interval); if(next.length===final.length)break;final=next; }
    return final;
  }
  function exactScope(observation){
    const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'
      ?Object.fromEntries(Object.keys(value).sort().map(k=>[k,canonical(value[k])])):value;
    return JSON.stringify(['source','sourceId','sourceKind','workId','sourceWorkId','localSourceId','region','regionId','familyId',
      'sourceDocumentToken','sourceContextKey','sourceGeneration','bindingGeneration'].map(k=>[k,Object.hasOwn(observation,k),canonical(observation[k])]))
      +JSON.stringify([observation.visualEvidence?.inputWidth,observation.visualEvidence?.inputHeight,
        observation.tokenAlignment?.sourceWidth,observation.tokenAlignment?.sourceHeight]);
  }
  function fuseExactObservations(observations, interval=.5){
    const groups=[];let current=null;
    for(const observation of observations){
      if(observation?.accepted!==true||typeof observation.text!=='string'||!observation.text.trim()){current=null;continue;}
      const previous=current?.at(-1);
      if(!previous||observation.text!==previous.text||observation.index!==previous.index+1
        ||!Number.isFinite(observation.time)||!Number.isFinite(previous.time)||observation.time<=previous.time
        ||observation.time-previous.time>Math.min(.8,interval*1.6)||exactScope(observation)!==exactScope(previous)){
        current=[];groups.push(current);
      }
      current.push(observation);
    }
    return groups.map(samples=>{
      const text=samples[0].text,values=new Map();
      for(const o of samples){const seen=new Set();
        for(const r of [o,...(o.alternatives||[])]){
          if(typeof r?.text!=='string'||!r.text.trim()||seen.has(r.text))continue;seen.add(r.text);
          const value=values.get(r.text)||{text:r.text,frames:0,confidence:0,firstObserved:o.time,lastObserved:o.time};
          value.frames++;value.confidence+=Number.isFinite(r.confidence)?r.confidence:0;value.lastObserved=o.time;values.set(r.text,value);
        }
      }
      // Keep every diagnostic reading, but an unreadable transformed pass is
      // not by itself a user-facing conflict or another vote against the source.
      const variation=samples.some(o=>(o.alternatives||[]).some(r=>acceptable(r)&&r.text!==text
        &&(r.mode!=='spatial_candidate'||r.cropAssessment?.usableForConsolidation===true)));
      const low=samples.some(o=>Number.isFinite(o.minCharConfidence)&&o.minCharConfidence<55);
      return {text,observedText:text,firstObserved:samples[0].time,lastObserved:samples.at(-1).time,
        observationIndices:samples.map(o=>o.index),confidence:Math.min(...samples.map(o=>o.confidence)),
        candidates:[...values.values()].map(c=>({...c,confidence:c.confidence/c.frames})),variation,needsReview:variation||low,
        ...(variation||low?{reviewReason:'原始画面存在不同读数，已保留候选；未自动替换文字'}:{})};
    });
  }
  function mergeVisualCaptionEvents(segments, observations, interval) {
    const visual = visualApi(); if (!visual) return segments;
    const output = [];
    const restore = segment => segment.candidateGroup && Array.isArray(segment.retainedSegments) ? segment.retainedSegments.flatMap(restore) : [segment];
    for (const segment of segments) {
      const previous = output.at(-1), indices = [...(previous?.observationIndices || []), ...segment.observationIndices];
      const samples = indices.map(i => observations[i]);
      if (!previous || samples.length < 3 || samples.at(-1).time - samples[0].time > 6
        || !samples.every((s,i) => s?.accepted && visual.valid(s.visualEvidence) && (!i || s.index === samples[i-1].index+1
          && s.time > samples[i-1].time && s.time-samples[i-1].time <= interval*1.6 && visual.same(s.visualEvidence,samples[i-1].visualEvidence)))) {
        output.push(segment); continue;
      }
      const chosen = originalVotes(samples).filter(c => c.frames >= 2).sort((a,b)=>b.frames-a.frames||b.confidence-a.confidence)[0];
      if (!chosen || !reviewableKey(chosen.key) || /\n/u.test(chosen.key)) { output.push(segment); continue; }
      const anchorChars=Array.from(chosen.key), anchorSamples=samples.filter(s => comparisonKey(s.text)===chosen.key);
      const compatible = samples.every(s => {
        const source=(s.alternatives||[]).find(r=>r.mode==='original' && r.text===s.text);
        if (!source || protectedSignature(comparisonKey(s.text))!==protectedSignature(chosen.key)) return false;
        const chars=Array.from(comparisonKey(s.text)); if(chars.length!==anchorChars.length) return false;
        const changes=chars.map((c,i)=>c===anchorChars[i]?-1:i).filter(i=>i>=0);
        if(!changes.length) return true;
        // A real clear single-character change must survive even if most of a
        // long sentence looks unchanged. Only an uncertain observed glyph can
        // borrow an actual multi-frame representative, with local pixel proof.
        if(changes.length!==1 || normalizeText(s.text)!==comparisonKey(s.text)) return false;
        const p=changes[0], glyphs=source.charConfidences;
        if(!Array.isArray(glyphs)||glyphs.map(g=>g.text).join('')!==s.text || !Number.isFinite(glyphs[p]?.confidence) || glyphs[p].confidence>=85) return false;
        return anchorSamples.some(a=>visual.sameGlyph(s.visualEvidence,a.visualEvidence,p,chars.length));
      });
      if(!compatible) { output.push(segment); continue; }
      const merged=makeSegment(samples,chosen.key,true);
      merged.candidateGroup=true; merged.visualEvent=true; merged.visualEvidenceIndices=[...indices];
      merged.originalFrameVotes=chosen.frames; merged.retainedSegments=[...restore(previous),...restore(segment)];
      merged.reviewOptions=[...new Set(samples.flatMap(s=>[s.text,...readings(s).map(r=>r.text)]))];
      merged.reviewReason="同一位置的字幕字形连续稳定，已按实际多帧读数整理；原始文字和分段可恢复";
      output[output.length-1]=merged;
    }
    return output;
  }
  function spatialReading(original, candidate) {
    if(!acceptable(original)||!acceptable(candidate)) return false;
    const full=normalizeText(original.text), short=normalizeText(candidate.text);
    if (/\n/u.test(full) || !reviewableKey(short) || full.length !== short.length+1
      || !(full.startsWith(short)||full.endsWith(short)) || protectedSignature(full)!==protectedSignature(short)) return false;
    const removed=full.startsWith(short)?full.at(-1):full[0];
    if(/[\p{N}A-Za-z零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟萬億负正点不没无未非勿别莫能可会要须需必应得只仅限更最比较约近多至少超余再又也才还曾已都皆尽前后上下内外]/u.test(removed)) return false;
    const glyphs=original.charConfidences;
    if(!Array.isArray(glyphs)||glyphs.map(g=>g.text).join('')!==full) return false;
    const edge=full.startsWith(short)?glyphs.at(-1):glyphs[0];
    return Number.isFinite(edge?.confidence)&&edge.confidence<10;
  }
  // A display event can survive one low-score reading of the SAME actual text.
  // Do not treat missing pixels, empty OCR or a different caption as continuity.
  // This final reconciliation also joins neighbouring review groups whose actual
  // representatives agree. The accepted-frame index contract remains unchanged;
  // the extra event indices disclose a bridged, still-rejected observation.
  function mergeAdjacentCaptionEvents(segments, observations, interval) {
    const output = [];
    const eventKey = text => comparisonKey(text).replace(/(?<=\p{Script=Han})[,，](?=\p{Script=Han})/gu, "");
    const original = observation => (observation?.alternatives || []).filter(value => value.mode === "original");
    const eligibleText = text => reviewableKey(comparisonKey(text)) && !/[\r\n]/u.test(text);
    const restore = segment => segment.candidateGroup && Array.isArray(segment.retainedSegments)
      ? segment.retainedSegments.flatMap(restore) : [segment];
    for (const current of segments) {
      const previous = output.at(-1);
      if (!previous || !eligibleText(previous.text) || !eligibleText(current.text)
        || eventKey(previous.text) !== eventKey(current.text)
        || protectedSignature(previous.text) !== protectedSignature(current.text)
        || current.lastObserved - previous.firstObserved > 6) { output.push(current); continue; }
      const key = eventKey(previous.text);
      const first = previous.observationIndices[0], last = current.observationIndices.at(-1);
      const acceptedIndices = [...previous.observationIndices, ...current.observationIndices];
      const acceptedSet = new Set(acceptedIndices);
      const span = observations.slice(first, last + 1);
      const missing = span.filter(value => !acceptedSet.has(value.index));
      const contiguous = span.length === last - first + 1 && span.every((value, index) => value.index === first + index
        && Number.isFinite(value.time) && (!index || (value.time > span[index - 1].time
          && value.time - span[index - 1].time <= interval * 1.6)));
      if (!contiguous || missing.length > 1 || missing.some(value => value.accepted || !eligibleText(value.text)
        || eventKey(value.text) !== key || !Number.isFinite(value.confidence) || value.confidence < 60 || value.confidence >= 80
        || original(value).length !== 1 || !Number.isFinite(original(value)[0].confidence) || original(value)[0].confidence < 60 || original(value)[0].confidence >= 80
        || !eligibleText(original(value)[0].text) || eventKey(original(value)[0].text) !== key)) {
        output.push(current); continue;
      }
      const sourceFrames = span.filter(value => acceptedSet.has(value.index) && original(value).some(reading =>
        reading.confidence >= 95 && eligibleText(reading.text) && eventKey(reading.text) === key));
      // Two image passes are never two votes; at least one original source frame
      // on each side and three independent high-score frames in total are needed.
      if (sourceFrames.length < 3 || !sourceFrames.some(value => previous.observationIndices.includes(value.index))
        || !sourceFrames.some(value => current.observationIndices.includes(value.index))) { output.push(current); continue; }
      const variants = new Map();
      for (const value of span) for (const variant of new Set(original(value).filter(acceptable).map(reading => eventKey(reading.text)))) {
        if (variant !== key) variants.set(variant, (variants.get(variant) || 0) + 1);
      }
      // A stable competing original can be a real new caption or name. Existing
      // tentative representatives do not authorize silently discarding it.
      if ([...variants.values()].some(count => count >= 2)) { output.push(current); continue; }
      const samples = acceptedIndices.map(index => observations[index]);
      const anchor = comparisonKey(sourceFrames[0].alternatives.find(reading => reading.mode === "original"
        && reading.confidence >= 95 && eventKey(reading.text) === key).text);
      const merged = makeSegment(samples, anchor, true);
      merged.candidateGroup = true;
      merged.captionEvent = true;
      merged.eventObservationIndices = span.map(value => value.index);
      merged.bridgedObservationIndices = missing.map(value => value.index);
      merged.originalFrameVotes = sourceFrames.length;
      merged.reviewReason = missing.length
        ? "短暂低可信帧仍读到同句，已按前后原色画面归并；原始记录与分段可恢复"
        : "连续画面中的同句候选已归并，原始文字与分段可恢复";
      merged.reviewOptions = [...new Set(span.flatMap(value => [value.text, ...readings(value).map(reading => reading.text)])
        .filter(Boolean).map(displayText))];
      merged.retainedSegments = [...restore(previous), ...restore(current)];
      output[output.length - 1] = merged;
    }
    return output;
  }
  // A very weak extra edge glyph must not win simply because its otherwise
  // clear line has a high mean score or was repeated. This is a reversible
  // presentation choice between ACTUAL original readings, not character removal.
  function mergeLowConfidenceEdgeVariants(segments, observations, interval) {
    const output = [];
    const protectedEdge = /[\p{N}A-Za-z零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟萬億负正点不没无未非勿别莫能可会要须需必应得只仅限更最比较约近多至少超余再又也才还曾已都皆尽前后上下内外]/u;
    function source(observation) {
      if (!observation?.accepted || /[\r\n]/u.test(observation.text)) return null;
      const originals = (observation.alternatives || []).filter(value => value.mode === "original");
      if (originals.length !== 1) return null;
      const reading = originals[0];
      if (!acceptable(reading) || reading.text !== observation.text || /[\r\n]/u.test(reading.text)
        || !Array.isArray(reading.charConfidences) || !reading.charConfidences.length) return null;
      const glyphs = reading.charConfidences;
      // Missing/misaligned character evidence must never authorize shortening.
      if (glyphs.some(value => typeof value?.text !== "string" || Array.from(value.text).length !== 1
        || !Number.isFinite(value.confidence) || value.confidence < 0 || value.confidence > 100)
        || glyphs.map(value => value.text).join("") !== reading.text) return null;
      return { reading, glyphs };
    }
    function edgeKind(value, anchor) {
      if (value.reading.text === anchor) return value.glyphs.every(glyph => glyph.confidence >= 95) ? "anchor" : "";
      const text = value.reading.text, glyphs = value.glyphs;
      if (Array.from(text).length !== Array.from(anchor).length + 1
        || protectedSignature(text) !== protectedSignature(anchor)) return "";
      const edgeIndex = text.endsWith(anchor) ? 0 : text.startsWith(anchor) ? glyphs.length - 1 : -1;
      if (edgeIndex < 0) return "";
      const extra = glyphs[edgeIndex];
      if (!/^\p{Script=Han}$/u.test(extra.text) || protectedEdge.test(extra.text) || extra.confidence >= 10) return "";
      return glyphs.every((glyph, index) => index === edgeIndex || glyph.confidence >= 95) ? "edge" : "";
    }
    function proposal(samples) {
      const sources = samples.map(source);
      if (sources.some(value => !value)) return null;
      const anchors = [...new Set(sources.filter(value => value.glyphs.every(glyph => glyph.confidence >= 95))
        .map(value => value.reading.text).filter(text => reviewableKey(text) && comparisonKey(text) === text))];
      const allowed = anchors.map(anchor => ({ anchor, kinds: sources.map(value => edgeKind(value, anchor)) }))
        .filter(value => value.kinds.every(Boolean) && value.kinds.includes("anchor") && value.kinds.includes("edge"));
      return allowed.length === 1 ? allowed[0] : null;
    }
    for (let i = 0; i < segments.length;) {
      let selected = null, samples = [];
      for (let end = i; end < segments.length; end++) {
        const segment = segments[end];
        if (segment.candidateGroup || segment.consensusBridge) break;
        const next = segment.observationIndices.map(index => observations[index]);
        if (next.some(value => !value)) break;
        const expanded = [...samples, ...next];
        if (expanded.at(-1).time - expanded[0].time > 6 || expanded.some((value, index) => !Number.isFinite(value.time)
          || !Number.isInteger(value.index) || value.index < 0 || (index &&
          (value.index !== expanded[index - 1].index + 1 || value.time <= expanded[index - 1].time
            || value.time - expanded[index - 1].time > interval * 1.6)))) break;
        samples = expanded;
        const found = proposal(samples);
        if (found) selected = { ...found, samples: [...samples], end };
      }
      if (!selected) { output.push(segments[i++]); continue; }
      const merged = makeSegment(selected.samples, comparisonKey(selected.anchor), true);
      // Auxiliary punctuation votes cannot replace the actual high-confidence
      // original anchor this narrow rule specifically qualified.
      merged.text = selected.anchor;
      merged.observedText = selected.anchor;
      merged.edgeSymbolsCleaned = false;
      // Rebuild the observed runs, including a short occurrence previously
      // hidden by the old fuller-line rule. No source observation is rewritten.
      const retained = []; let part = [];
      for (const observation of selected.samples) {
        if (part.length && observation.text !== part[0].text) {
          retained.push(makeSegment(part, comparisonKey(part[0].text), true)); part = [];
        }
        part.push(observation);
      }
      if (part.length) retained.push(makeSegment(part, comparisonKey(part[0].text), true));
      merged.candidateGroup = true;
      merged.lowConfidenceEdgeVariant = true;
      merged.originalFrameVotes = selected.kinds.filter(kind => kind === "anchor").length;
      merged.reviewReason = "首尾低可信增字已按相邻原色短句整理，可恢复原分段";
      merged.reviewOptions = [...new Set(selected.samples.flatMap(value => readings(value).map(reading => displayText(reading.text))))];
      merged.retainedSegments = retained;
      output.push(merged); i = selected.end + 1;
    }
    return output;
  }
  // An isolated glyph error must not split A / noisy-A / A into three captions.
  // Require unchanged original-image readings on BOTH sides, never a dictionary
  // guess or a processed-image majority. Preserve every observation for recovery.
  function mergeTransientVariants(segments, observations, interval) {
    const output = [];
    function compatible(text, anchor) {
      let key = comparisonKey(text);
      if (sameKey(key, anchor)) return true;
      // Only these local shape confusions; no general fuzzy rewriting.
      key = key.replace(/白常/g, "日常").replace(/自已/g, "自己");
      if (key.endsWith("一") && !/[\p{N}A-Za-z零〇一二两三四五六七八九十百千万亿杯次片粒瓶袋天周月年度克斤升]/u.test(anchor)) key = key.slice(0, -1);
      return sameKey(key, anchor);
    }
    for (let i = 0; i < segments.length;) {
      const trio = segments.slice(i, i + 3), [left, middle, right] = trio;
      if (trio.length !== 3 || trio.some(value => value.candidateGroup)
        || middle.observationIndices.length !== 1
        || !sameKey(comparisonKey(left.text), comparisonKey(right.text))) {
        output.push(segments[i++]); continue;
      }
      const anchor = comparisonKey(left.text);
      const indices = trio.flatMap(value => value.observationIndices);
      const samples = indices.map(index => observations[index]);
      const original = value => (value.alternatives || []).filter(reading => reading.mode === "original" && acceptable(reading));
      const votes = values => values.filter(value => original(value).some(reading => sameKey(comparisonKey(reading.text), anchor))).length;
      const leftSamples = left.observationIndices.map(index => observations[index]);
      const rightSamples = right.observationIndices.map(index => observations[index]);
      const contiguous = indices.every((index, j) => !j || (index === indices[j - 1] + 1
        && samples[j].time > samples[j - 1].time && samples[j].time - samples[j - 1].time <= interval * 1.6));
      const middleSample = observations[middle.observationIndices[0]];
      if (!reviewableKey(anchor) || !contiguous || samples.at(-1).time - samples[0].time > 6
        || votes(leftSamples) < 1 || votes(rightSamples) < 1 || votes(samples) < 3
        || !compatible(middleSample.text, anchor) || !original(middleSample).length
        || !original(middleSample).every(reading => compatible(reading.text, anchor))) {
        output.push(segments[i++]); continue;
      }
      const merged = makeSegment(samples, anchor, true);
      merged.candidateGroup = true;
      merged.transientVariant = true;
      merged.originalFrameVotes = votes(samples);
      merged.reviewReason = "单帧字形干扰已按前后原始画面整理，可恢复原分段";
      merged.reviewOptions = Array.from(new Set(samples.flatMap(value => readings(value).map(reading => displayText(reading.text)))));
      merged.retainedSegments = trio;
      output.push(merged); i += 3;
    }
    return output;
  }
  function addSample(result, data, time, interval, alternatives = [], visualEvidence = null) {
    result.observations ||= [];
    const reading = copyReading(data, data?.mode || "selected");
    const observation = { ...reading, index: result.observations.length, time, accepted: Boolean(acceptable(data)), alternatives: alternatives.map(value => copyReading(value, value.mode || "original")) };
    if(visualApi()?.valid(visualEvidence)) observation.visualEvidence=visualEvidence;
    result.observations.push(observation);
    result.processed += 1;
    if (!observation.accepted) {
      if (normalizeText(data?.text)) result.uncertainFrames += 1;
      else result.emptyFrames += 1;
    }
    result.segments = fuseObservations(result.observations, interval, {policy:result.readingPolicy});
    result.reviewSegments = result.segments.filter(segment => segment.needsReview).length;
    result.variationSegments = result.segments.filter(segment => segment.variation).length;
    result.variationFrames = result.segments.filter(segment => segment.variation).reduce((count, segment) => count + segment.observationIndices.length, 0);
    result.candidateGroups = result.segments.filter(segment => segment.candidateGroup).length;
    result.consolidatedSegments = result.segments.filter(segment => segment.consensusBridge || segment.candidateGroup).length;
  }
  function formatTime(seconds) {
    if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "时间待确认";
    const hundredths = Math.round(seconds * 100);
    if (!Number.isSafeInteger(hundredths)) return "时间待确认";
    const minutes = Math.floor(hundredths / 6000);
    const remainingSeconds = Math.floor(hundredths % 6000 / 100);
    return `${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}.${String(hundredths % 100).padStart(2, "0")}`;
  }
  function formatSegment(segment) {
    const first = formatTime(segment?.firstObserved), last = formatTime(segment?.lastObserved);
    // These are observed sample times, not inferred subtitle onset/end times.
    // In particular, do not extend the final observation by a sampling interval.
    const known = first !== "时间待确认" && last !== "时间待确认" && segment.lastObserved >= segment.firstObserved;
    const prefix = known ? `[${first}–${last}]` : "[时间待确认]";
    const text = String(segment?.text ?? "");
    return text ? `${prefix} ${text}` : prefix;
  }
  function toText(result, source = {}) {
    const states = { ready: "未开始", running: "识别中（部分结果）", paused: "已暂停（部分结果）", cancelled: "已取消（部分结果）", processed: "已处理所选区域", partial: "部分识别，存在不确定画面", empty: "未识别到可靠字幕", failed: "处理失败（已有结果保留）" };
    return ["视频字幕（画面识别）", source.title ? `作品：${source.title}` : "", source.workId ? `作品ID：${source.workId}` : "",
      `来源：${sourceApi()?.label(source) || "来源未标注"}`,
      "识别方式：画面文字识别；不是音频转写，也不是发布文案。",
      `状态：${states[result.state] || "部分结果"}`,
      `已处理：${result.processed || 0}/${result.total || 0} 帧；不确定画面：${result.uncertainFrames || 0}`,
      `可选校对提示：${result.reviewSegments || 0} 段；存在多种识别结果：${result.variationSegments || 0} 段。`,
      `自动整理归并近重复：${result.consolidatedSegments || 0} 处；未全文人工核验，可按需对照视频核对。`,
      result.finalization?.mergedEvents ? `收尾自动整理时：${result.finalization.beforeSegments} → ${result.finalization.afterSegments} 段；当前机器分段：${result.segments?.length || 0} 段（包含保留原分段的选择）；原始分段与画面保留，可恢复。` : "",
      result.reviewCandidateGroups ? `相似候选组：${result.reviewCandidateGroups} 处；采用代表句 ${result.candidateGroups || 0} 处，保留原分段 ${result.retainedCandidateGroups || 0} 处。`
        : result.candidateGroups ? `相似候选组：${result.candidateGroups} 处；默认采用代表句，可展开核对或恢复原分段。` : "",
      "时间：采样观察区间，不是字幕精确起止，边界误差受采样间隔影响。",
      "范围：仅所选区域与采样时刻。可能漏字、错字或混入画面文字；未识别到文字不代表没有字幕。",
      "", ...(result.segments || []).map(formatSegment), ""].filter((line, i) => line !== "" || i > 5).join("\n");
  }
  function reviewedResult(result, retainedGroups = [], confirmed = false) {
    const retained = new Set(retainedGroups);
    const segments = result.segments.flatMap(segment =>
      segment.candidateGroup && retained.has(segment.observationIndices[0]) ? segment.retainedSegments : [segment]);
    return { ...result, candidatesConfirmed: confirmed === true, segments,
      // Local display choices are not evidence that a person checked every
      // character. Keep the original group count and raw ledger independently.
      reviewCandidateGroups: result.segments.filter(segment => segment.candidateGroup).length,
      retainedCandidateGroups: result.segments.filter(segment => segment.candidateGroup && retained.has(segment.observationIndices[0])).length,
      candidateGroups: segments.filter(segment => segment.candidateGroup).length,
      consolidatedSegments: segments.filter(segment => segment.consensusBridge || segment.candidateGroup).length,
      reviewSegments: segments.filter(segment => segment.needsReview).length,
      variationSegments: segments.filter(segment => segment.variation).length,
      variationFrames: segments.filter(segment => segment.variation).reduce((count, segment) => count + segment.observationIndices.length, 0),
    };
  }
  function checkAbort(signal) {
    if (signal?.aborted) { const error = new Error("已取消"); error.name = "AbortError"; throw error; }
  }
  function withTimeout(promise, milliseconds, message, signal) {
    return new Promise((resolve, reject) => {
      let timer;
      const clean = () => { clearTimeout(timer); signal?.removeEventListener("abort", onAbort); };
      const onAbort = () => { clean(); const error = new Error("已取消"); error.name = "AbortError"; reject(error); };
      signal?.addEventListener("abort", onAbort, { once: true });
      timer = setTimeout(() => { clean(); const error = new Error(message); error.name = "TimeoutError"; reject(error); }, milliseconds);
      Promise.resolve(promise).then(value => { clean(); resolve(value); }, error => { clean(); reject(error); });
      if (signal?.aborted) onAbort();
    });
  }
  function providerMetadata(provider) {
    if (!provider || typeof provider.getFrame !== "function" || (provider.validate !== undefined && typeof provider.validate !== "function")
      || !Number.isFinite(provider.duration) || provider.duration <= 0 || provider.duration > LIMITS.seconds
      || !Number.isInteger(provider.width) || !Number.isInteger(provider.height) || provider.width <= 0 || provider.height <= 0) {
      throw new Error("视频逐帧来源尚未准备好");
    }
    return { duration: provider.duration, width: provider.width, height: provider.height };
  }
  async function validateProvider(provider, signal) {
    checkAbort(signal);
    if (provider.validate) {
      const valid = await provider.validate(signal);
      checkAbort(signal);
      if (valid === false) throw new Error("视频逐帧来源已变化");
    }
  }
  async function providerFrame(provider, time, selected, signal) {
    const metadata = providerMetadata(provider), box = region(selected);
    await validateProvider(provider, signal);
    const value = await provider.getFrame(time, box, signal);
    checkAbort(signal);
    if (!value?.canvas || typeof value.canvas.getContext !== "function"
      || !Number.isInteger(value.canvas.width) || !Number.isInteger(value.canvas.height)
      || value.canvas.width <= 0 || value.canvas.height <= 0
      || typeof value.time !== "number" || !Number.isFinite(value.time) || value.time < 0 || value.time >= metadata.duration) {
      throw new Error("未收到有效的冻结视频画面");
    }
    await validateProvider(provider, signal);
    return { canvas: value.canvas, time: value.time };
  }
  function seek(video, time, signal) {
    return new Promise((resolve, reject) => {
      if (signal?.aborted) return reject(new Error("已取消"));
      if (Math.abs(video.currentTime - time) < 0.005 && video.readyState >= 2) return resolve();
      const clean = () => { clearTimeout(timer); video.removeEventListener("seeked", done); video.removeEventListener("error", fail); signal?.removeEventListener("abort", abort); };
      const done = () => { clean(); resolve(); };
      const fail = () => { clean(); reject(new Error("视频无法解码，请换用已下载的 MP4 文件")); };
      const abort = () => { clean(); reject(new Error("已取消")); };
      const timer = setTimeout(fail, 15000);
      video.addEventListener("seeked", done, { once: true }); video.addEventListener("error", fail, { once: true });
      signal?.addEventListener("abort", abort, { once: true });
      video.currentTime = time;
    });
  }
  function frame(video, selected, mode = "original") {
    const box = region(selected);
    const canvas = document.createElement("canvas");
    const width = video.videoWidth * (box.right - box.left), height = video.videoHeight * (box.bottom - box.top);
    if (!width || !height) throw new Error("视频画面尚未加载");
    const scale = Math.min(2, 1280 / width);
    canvas.width = Math.round(width * scale); canvas.height = Math.round(height * scale);
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(video, video.videoWidth * box.left, video.videoHeight * box.top, width, height, 0, 0, canvas.width, canvas.height);
    return mode === "white" ? whiteFrame(canvas) : canvas;
  }
  function whiteFrame(original) {
    // Work only from the frozen original: never ask a live player for a second
    // image pass, and never alter the provider's canvas or its retained evidence.
    const canvas = document.createElement("canvas");
    canvas.width = original.width; canvas.height = original.height;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(original, 0, 0);
    const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height);
    for (let i = 0; i < pixels.data.length; i += 4) {
      const value = Math.min(pixels.data[i], pixels.data[i + 1], pixels.data[i + 2]) > 210 ? 0 : 255;
      pixels.data[i] = pixels.data[i + 1] = pixels.data[i + 2] = value;
    }
    ctx.putImageData(pixels, 0, 0);
    return canvas;
  }
  class Session {
    constructor(options) {
      this.options = options; this.worker = null; this.paused = false; this.pauseRevision = 0; this.cancelled = false; this.resumeSignal = null; this.finished = false;
      this.controller = new AbortController();
      this.result = { state: "ready", source: "screen_ocr", accuracy: "machine_unverified", engine: "PP-OCRv5-mobile", processed: 0, total: 0, uncertainFrames: 0, emptyFrames: 0, reviewSegments: 0, variationSegments: 0, variationFrames: 0, consolidatedSegments: 0, observations: [], segments: [], region: region(options.region), interval: options.interval ?? 0.5 };
      this.result.engineBuild = ENGINE_BUILD;
      this.result.readingPolicy = READING_POLICY;
    }
    emit() { this.options.onProgress?.(JSON.parse(JSON.stringify(this.result))); }
    pause() { if (this.result.state !== "running") return; this.paused = true; this.pauseRevision++; this.result.state = "paused"; this.emit(); }
    resume() { if (!this.paused || this.cancelled) return; this.paused = false; this.result.state = "running"; this.resumeSignal?.(); this.emit(); }
    stopWorker() {
      const worker = this.worker; this.worker = null;
      if (!worker) return Promise.resolve();
      return Promise.resolve().then(() => worker.terminate()).catch(() => {});
    }
    cancel() { this.cancelled = true; this.paused = false; this.controller.abort(); this.resumeSignal?.(); this.stopWorker(); this.result.state = "cancelled"; this.emit(); }
    async checkpoint() {
      if (this.cancelled) throw new Error("已取消");
      if (this.paused && typeof this.options.onPausedCheckpoint === "function") {
        // Release an owned page player only at a boundary with no frame pull
        // or OCR request in flight. The UI owns release/reopen and its lease.
        await withTimeout(Promise.resolve().then(() => {
          checkAbort(this.controller.signal);
          return this.options.onPausedCheckpoint(this.controller.signal);
        }), 15000, "暂停清理未完成", this.controller.signal);
      }
      // Resume can arrive while the asynchronous release hook is pending.
      // Do not install a new waiter after that resume, and let cancellation win.
      if (this.cancelled) throw new Error("已取消");
      if (this.paused) {
        try { await new Promise(resolve => { this.resumeSignal = resolve; }); }
        finally { this.resumeSignal = null; }
      }
      if (this.cancelled) throw new Error("已取消");
    }
    async run() {
      if (this.result.state !== "ready") throw new Error("任务不能重复启动");
      const { video, frameProvider, baseUrl, language = "chi_sim+eng", lineMode = "7" } = this.options;
      if (!["chi_sim", "eng", "chi_sim+eng"].includes(language)) throw new Error("请选择内置语言");
      const times = sampleTimes(frameProvider ? providerMetadata(frameProvider).duration : video?.duration, this.result.interval);
      this.result.total = times.length; this.result.state = "running"; this.emit();
      try {
        await this.checkpoint();
        if (frameProvider) await withTimeout(validateProvider(frameProvider, this.controller.signal), 15000, "视频来源核验超时", this.controller.signal);
        else { video.pause(); video.muted = true; }
        const workerPromise = Promise.resolve((this.options.workerFactory || globalThis.BrandbaiCreateSubtitleRecognizer)(language, 1, {
          workerPath: new URL("vendor/worker.min.js", baseUrl).href,
          corePath: new URL("vendor/core/", baseUrl).href,
          langPath: new URL("vendor/lang/", baseUrl).href,
          workerBlobURL: false, cacheMethod: "none", legacyCore: false, legacyLang: false,
          signal: this.controller.signal,
        }));
        workerPromise.then(worker => { if (this.cancelled || this.finished) Promise.resolve(worker.terminate()).catch(() => {}); }).catch(() => {});
        this.worker = await withTimeout(workerPromise, 60000, "本地识别引擎初始化超时", this.controller.signal);
        await this.checkpoint();
        await withTimeout(this.worker.setParameters({ tessedit_pageseg_mode: lineMode === "6" ? "6" : "7", preserve_interword_spaces: "1" }), 15000, "本地识别引擎配置超时", this.controller.signal);
        let auxiliaryFailed = false;
        for (const time of times) {
          await this.checkpoint();
          let sampled;
          if (frameProvider) sampled = await withTimeout(providerFrame(frameProvider, time, this.result.region, this.controller.signal), 15000, "视频逐帧读取超时", this.controller.signal);
          else { await seek(video, time, this.controller.signal); sampled = { canvas: frame(video, this.result.region), time }; }
          await this.checkpoint();
          const raw = await withTimeout(this.worker.recognize(sampled.canvas), 15000, "单帧识别超时", this.controller.signal);
          let best = raw?.data || {}, selectedReadingId='original';
          const alternatives = [{ ...best, mode: "original" }];
          let visualEvidence = null, recognitionCanvas = sampled.canvas;
          // Analyze only the selected ROI from this exact frozen sample. Scene
          // images and storyboard thumbnails never enter subtitle continuity.
          try { const ctx=sampled.canvas.getContext('2d'); visualEvidence=visualApi()?.analyze(ctx.getImageData(0,0,sampled.canvas.width,sampled.canvas.height)) || null; } catch {}
          if(visualEvidence && visualEvidence.box.right-visualEvidence.box.left < sampled.canvas.width*.95) {
            await this.checkpoint();
            try {
              const spatialCanvas=visualApi().crop(sampled.canvas,visualEvidence);
              const spatial=await withTimeout(this.worker.recognize(spatialCanvas),15000,"字幕区域复读超时",this.controller.signal);
              const candidate={...spatial.data,mode:'spatial_candidate',cropEvidence:{schema:'outlined-caption-spatial-crop-v1',inputWidth:sampled.canvas.width,inputHeight:sampled.canvas.height,box:{...visualEvidence.box}}};
              candidate.cropAssessment=readingEvidenceApi()?.assessCrop(alternatives[0],candidate,visualEvidence)
                ||{schema:'subtitle-crop-assessment-v1',status:'unverified',reason:'assessment_unavailable',usableForConsolidation:false};
              alternatives.push(candidate);
              // The full original remains the original. A high-scored crop is
              // not permission to shorten or replace a reading in this frame.
              // Low-score originals also get one candidate, not a lower gate.
            } catch(error) {
              if(this.cancelled || this.controller.signal.aborted || error.name==='AbortError') throw error;
              await this.stopWorker(); auxiliaryFailed=true;
              this.result.error="字幕区域复读未完成，已保留原图文字；本次提取已停止";
            }
          }
          await this.checkpoint();
          // Mean line confidence may be high even when one glyph is wrong or
          // missing. Read the white-glyph pass for nonempty frames too, so an
          // exact same-frame candidate can bridge adjacent OCR variants.
          if (!auxiliaryFailed && (normalizeText(best.text) || Number(best.confidence || 0) < 85)) {
            let white;
            try {
              white = await withTimeout(this.worker.recognize(whiteFrame(recognitionCanvas)), 15000, "辅助单帧识别超时", this.controller.signal);
            } catch (error) {
              if (this.cancelled || this.controller.signal.aborted || error.name === "AbortError") throw error;
              // A failed/late auxiliary request must never be reused on the next
              // frame. Terminate first; commit only a reliable original once.
              await this.stopWorker();
              if (!acceptable(best)) throw error;
              auxiliaryFailed = true;
              this.result.error = "辅助画面识别未完成，已保留可靠原图结果；本次提取已停止";
            }
            if (white) alternatives.push({ ...white.data, mode: "white" });
            // Preprocessing can give a wrong glyph very high confidence. Keep
            // an acceptable original reading as the selected observation; the
            // derived pass supplies corroboration, not authority to overwrite it.
            if (white && !acceptable(best) && acceptable(white.data)) {best = white.data;selectedReadingId='white';}
          }
          // A pause can release the native player after an in-flight validation
          // returns. Recheck after every such boundary, including rapid
          // pause/resume while validation itself is pending. Keep the final
          // unpaused/cancel guard and ledger commit in one synchronous turn.
          for (;;) {
            await this.checkpoint();
            const revision = this.pauseRevision;
            if (frameProvider) await withTimeout(validateProvider(frameProvider, this.controller.signal), 15000, "视频来源核验超时", this.controller.signal);
            checkAbort(this.controller.signal);
            if (this.paused || revision !== this.pauseRevision) continue;
            addSample(this.result, {...best,selectedReadingId}, sampled.time, this.result.interval, alternatives, visualEvidence); this.emit();
            break;
          }
          if (auxiliaryFailed) break;
        }
        this.result.state = auxiliaryFailed ? "partial" : !this.result.segments.length ? "empty" : this.result.uncertainFrames || this.result.reviewSegments ? "partial" : "processed";
      } catch (error) {
        this.result.state = this.cancelled ? "cancelled" : "failed";
        const code = frameProvider && Object.hasOwn(PAGE_FRAME_MESSAGES, error?.code) ? error.code : "";
        this.result.error = this.cancelled ? "已取消" : code ? PAGE_FRAME_MESSAGES[code]
          : frameProvider ? "页面画面处理失败，已有结果保留；请重试或选择本地视频"
            : "本地处理失败，请检查视频格式或缩小字幕区域后重试";
        if (code && !this.cancelled) this.result.errorCode = code;
      } finally {
        try { this.result = finalizeResult(this.result); }
        catch { this.result.finalizationError = "已有文字已保留，收尾整理未完成"; }
        this.finished = true;
        this.controller.abort();
        await this.stopWorker(); this.emit();
      }
      return this.result;
    }
  }
  return { LIMITS, DEFAULT_REGION, ENGINE_BUILD, READING_POLICY, region, sampleTimes, normalizeText, acceptable, comparisonKey, protectedSignature, fuseObservations, fuseExactObservations, addSample, finalizeResult, restoreFinalization, formatTime, formatSegment, reviewedResult, toText, seek, frame, whiteFrame, providerMetadata, validateProvider, providerFrame, spatialReading, Session };
});
