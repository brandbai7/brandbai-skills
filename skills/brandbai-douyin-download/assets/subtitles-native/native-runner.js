/* Candidate local-file CLI adapter. Shared algorithms are not rewritten here. */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  root.BrandbaiDetectedSubtitleRunner = api;
})(globalThis, function (root) {
  "use strict";
  const SCRIPT_PATHS = Object.freeze([
    "lib/subtitle-source.js", "lib/subtitle-output.js", "lib/subtitle-storyboard.js",
    "subtitles/recognizer.js", "lib/subtitle-visual-events.js", "lib/subtitle-caption-line.js",
    "lib/subtitle-reading-evidence.js", "lib/subtitle-finalize.js", "subtitles/engine.js",
    "lib/vendor/opencc/t2cn.js", "lib/subtitle-simplified.js", "lib/subtitle-roles.js",
    "lib/subtitle-role-style-v197.js", "lib/subtitle-cue-merge-v197.js",
    "lib/subtitle-critical-read-v197.js", "lib/subtitle-region-recovery-v197.js",
    "lib/subtitle-working-groups-v198.js", "lib/subtitle-working-candidates-v198.js",
    "lib/subtitle-progressive-working-v199.js",
    "lib/subtitle-native-short-slot-v199.js",
    "lib/subtitle-frame-queue-v201.js",
    "subtitles/new-pipeline.js"
  ]);
  function html() {
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">' +
      '<meta http-equiv="Content-Security-Policy" content="default-src \'self\' blob:; script-src \'self\'; connect-src \'self\'; worker-src \'self\' blob:; img-src \'self\' blob: data:"></head>' +
      '<body><video id="video" muted playsinline></video>' +
      [...SCRIPT_PATHS, "native-runner.js"].map(path => '<script src="/' + path + '"></script>').join("") + '</body></html>';
  }
  function outputs(result, source, collector = null) {
    const plan = collector ? collector.plan(result) : root.BrandbaiSubtitleStoryboard.textPlan(result);
    const documents = root.BrandbaiSubtitleStoryboard.documents(result, source, plan);
    return { result, source, plan, documents,
      timed: root.BrandbaiSubtitleOutput.text(result, source, "timed"),
      plain: root.BrandbaiSubtitleOutput.text(result, source, "plain"),
      review: root.BrandbaiSubtitleOutput.reviewItems(result).length ? root.BrandbaiSubtitleOutput.reviewText(result, source) : "",
      recovery: result.captionRecovery?.length ? ["待确认文字（可能是短暂字幕或强调字）", ...root.BrandbaiSubtitleSource.lines(source),
        "以下为原视频实际识别候选，未自动拼入正文，文字角色及正确性尚未确认。时间是采样观察范围。", "",
        root.BrandbaiSubtitleOutput.body({ segments: result.captionRecovery }, "timed"), ""].join("\n") : "",
      csv: root.BrandbaiSubtitleOutput.csv(result, source) };
  }
  async function encode(blob) {
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let binary = "";
    for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
    return btoa(binary);
  }
  async function run({ videoSha256, title, workId = "", includeFrames = false }) {
    if (typeof includeFrames !== "boolean") throw Error("includeFrames must be an explicit boolean");
    const captureMode = includeFrames ? "with_frames" : "text_only";
    const scheduling = root.BrandbaiSubtitleFrameQueueV201;
    if (typeof scheduling?.selectFrameConcurrency !== "function") throw Error("Incomplete local scan scheduling module");
    const scanScheduling = scheduling.selectFrameConcurrency({ hardwareConcurrency: root.navigator?.hardwareConcurrency,
      deviceMemory: root.navigator?.deviceMemory });
    if (!/^[a-f0-9]{64}$/.test(videoSha256)) throw Error("Invalid local video identity");
    if (document.characterSet.toUpperCase() !== "UTF-8") throw Error("Invalid local document encoding");
    const legacy = root.BrandbaiSubtitles, native = root.BrandbaiHighQualitySubtitles;
    if (!native?.Session || !root.BrandbaiSubtitleWorkingGroupsV198 || !root.BrandbaiSubtitleWorkingCandidatesV198 ||
        legacy.comparisonKey("。合成 字幕。") !== "合成字幕" ||
        legacy.protectedSignature("不能喝一杯") === legacy.protectedSignature("能喝一杯")) throw Error("Incomplete local subtitle modules");
    root.BrandbaiSubtitleSimplified.assertReady();
    const blob = await (await fetch("/__input_video__")).blob();
    const actualSha = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer())))
      .map(n => n.toString(16).padStart(2, "0")).join("");
    if (actualSha !== videoSha256) throw Error("Local video identity changed");
    const video = document.getElementById("video"), url = URL.createObjectURL(blob);
    const source = { title, workId, sourceKind: workId ? "completed_download" : "local_file" };
    const collector = includeFrames ? new root.BrandbaiSubtitleStoryboard.Collector({ id: "cli:" + videoSha256, source,
      region: { left: 0, top: 0, right: 1, bottom: 1 } }) : null;
    try {
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(Error("Local video decode timeout")), 15000);
        video.onloadeddata = () => { clearTimeout(timer); resolve(); };
        video.onerror = () => { clearTimeout(timer); reject(Error("Local video decode failed")); };
        video.src = url;
      });
      if (!Number.isFinite(video.duration) || video.duration <= 0 || video.duration > 180) throw Error("Local video exceeds 180 seconds");
      let progressQueue = Promise.resolve(), lastSnapshot = null;
      const persist = result => {
        // Passing the whole nested evidence graph through Playwright's object
        // argument serializer repeats a large recursive conversion every read.
        // JSON is lossless for these already JSON-cloned processing snapshots.
        // Only exact duplicate checkpoints are suppressed, never changed data.
        const snapshot = { ...result, captureMode, scanScheduling };
        const key = JSON.stringify(snapshot);
        if (key === lastSnapshot) return progressQueue;
        lastSnapshot = key;
        if (typeof root.subtitleNativeProgressSerialized === "function") {
          const serialized = key;
          progressQueue = progressQueue.then(() => root.subtitleNativeProgressSerialized(serialized));
        } else progressQueue = progressQueue.then(() => root.subtitleNativeProgress(snapshot));
        return progressQueue;
      };
      const session = new native.Session({ video, baseUrl: new URL("/subtitles/", location.href),
        sourceIdentity: { kind: "local_file_sha256", sha256: videoSha256 },
        scanConcurrency: scanScheduling.capacity,
        ...(collector ? { onFrame: ({ canvas, time, frameIndex }) => collector.capture(canvas, time, frameIndex) } : {}),
        onProgress: persist, onCheckpoint: persist });
      const result = { ...await session.run(), captureMode, scanScheduling };
      await progressQueue;
      const data = outputs(result, source, collector);
      for (const row of data.plan.rows) for (const frame of row.images) {
        await root.subtitleNativeImage({ path: frame.path, base64: await encode(frame.blob), frameIndex: frame.index,
          frameId: frame.sourceFrameId, time: frame.time, parentPixelsSha256: frame.sourcePixelSha256 });
      }
      return { result, source, timed: data.timed, plain: data.plain, review: data.review, recovery: data.recovery, csv: data.csv, documents: data.documents,
        frameStorage: { captureMode, sampled: collector?.frames.size || 0, bytes: collector?.bytes || 0, warning: collector?.warning || null },
        runtimeBrowser: { documentEncoding: document.characterSet, chineseRulesSmoke: "passed",
          sourceFileSha256: actualSha, regionMode: "native_detected_lines", regionManuallyConfirmed: false } };
    } finally { video.removeAttribute("src"); video.load(); URL.revokeObjectURL(url); }
  }
  return { SCRIPT_PATHS, html, outputs, run };
});

