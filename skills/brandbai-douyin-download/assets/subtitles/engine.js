/* Local, opt-in screen-subtitle extraction. No audio, platform API or cloud calls. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.BrandbaiSubtitles = api;
})(typeof globalThis === "undefined" ? this : globalThis, function () {
  "use strict";
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
    return text.replace(/(?<=[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}])[ \t\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]+(?=[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}])/gu, "");
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
    return reading;
  }
  function readings(observation) {
    const unique = new Map();
    for (const reading of [observation, ...(observation.alternatives || [])]) {
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
  function fuseObservations(observations, interval = 0.5) {
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
    return mergeLowConfidenceEdgeVariants(mergeTransientVariants(groupForReview(segments, observations, interval), observations, interval), observations, interval);
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
  function addSample(result, data, time, interval, alternatives = []) {
    result.observations ||= [];
    const reading = copyReading(data, data?.mode || "selected");
    const observation = { ...reading, index: result.observations.length, time, accepted: Boolean(acceptable(data)), alternatives: alternatives.map(value => copyReading(value, value.mode || "original")) };
    result.observations.push(observation);
    result.processed += 1;
    if (!observation.accepted) {
      if (normalizeText(data?.text)) result.uncertainFrames += 1;
      else result.emptyFrames += 1;
    }
    result.segments = fuseObservations(result.observations, interval);
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
      "来源：本地视频画面文字识别；不是音频转写，也不是发布文案。",
      `状态：${states[result.state] || "部分结果"}`,
      `已处理：${result.processed || 0}/${result.total || 0} 帧；不确定画面：${result.uncertainFrames || 0}`,
      `可选校对提示：${result.reviewSegments || 0} 段；存在多种识别结果：${result.variationSegments || 0} 段。`,
      `自动整理归并近重复：${result.consolidatedSegments || 0} 处；未全文人工核验，可按需对照视频核对。`,
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
          let best = raw?.data || {};
          const alternatives = [{ ...best, mode: "original" }];
          await this.checkpoint();
          // Mean line confidence may be high even when one glyph is wrong or
          // missing. Read the white-glyph pass for nonempty frames too, so an
          // exact same-frame candidate can bridge adjacent OCR variants.
          if (normalizeText(best.text) || Number(best.confidence || 0) < 85) {
            let white;
            try {
              white = await withTimeout(this.worker.recognize(whiteFrame(sampled.canvas)), 15000, "辅助单帧识别超时", this.controller.signal);
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
            if (white && !acceptable(best) && acceptable(white.data)) best = white.data;
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
            addSample(this.result, best, sampled.time, this.result.interval, alternatives); this.emit();
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
        this.finished = true;
        this.controller.abort();
        await this.stopWorker(); this.emit();
      }
      return this.result;
    }
  }
  return { LIMITS, DEFAULT_REGION, region, sampleTimes, normalizeText, acceptable, comparisonKey, protectedSignature, fuseObservations, addSample, formatTime, formatSegment, reviewedResult, toText, seek, frame, whiteFrame, providerMetadata, validateProvider, providerFrame, Session };
});
