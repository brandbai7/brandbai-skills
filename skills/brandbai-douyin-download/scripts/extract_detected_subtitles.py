"""Candidate opt-in shared detected-line pipeline for one local video; no platform/ASR."""
from __future__ import annotations
import asyncio
import base64
import hashlib
import json
import math
import mimetypes
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlparse
import zipfile

from extract_video_subtitles import chrome_path, validate_video, observed_segment

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "subtitles-native"
ORIGIN = "https://brandbai-native-subtitles.invalid"
WRAPPER_VERSION = "0.6.6-candidate"
OUTPUTS = ["视频字幕.txt", "字幕正文.txt", "字幕识别记录.json", "逐句图文.md", "逐句图文.html",
           "机器分段.csv", "逐句配图.csv", "配图清单.json", "字幕画面工作包.zip", "字幕工作包.zip",
           "待确认字幕候选.txt", "字幕疑点.txt"]


def safe_failure(error: BaseException, phase: str, operation: str) -> dict:
    name = type(error).__name__
    if isinstance(error, ModuleNotFoundError):
        kind = "missing_playwright" if str(getattr(error, "name", "")).startswith("playwright") else "missing_dependency"
    elif isinstance(error, TimeoutError):
        kind = "deadline_exceeded"
    elif type(error).__module__.startswith("playwright"):
        kind = "playwright_error"
    elif isinstance(error, (ValueError, OSError)):
        kind = "validation_or_io_error"
    elif isinstance(error, asyncio.CancelledError):
        kind = "cancelled"
    else:
        kind = "local_execution_error"
    return {"schema": "local-subtitle-safe-failure-v064-r1", "errorKind": kind,
            "errorType": name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name) else "Exception",
            "phase": phase if phase in ("frames", "roles", "precision", "extent_precision") else "initialization",
            "operation": operation if operation in ("dependency", "browser_launch", "page_load", "pipeline_run", "verify_runtime", "export_files", "close_browser") else "unknown",
            "sensitivePathsOrUrlsIncluded": False}


def validate_precision_resume_record(record: dict, runtime: dict) -> None:
    """Host preflight only; browser still proves every native pixel before any model call."""
    raw, events, queue = record.get("raw"), record.get("events"), record.get("precisionCheckpoint")
    total = record.get("total")
    if type(total) is not int or total < 1 or record.get("processed") != total or not isinstance(raw, dict):
        raise ValueError("精读续跑必须保留完整采样")
    frames, rows = raw.get("frames"), raw.get("rows")
    if not isinstance(frames, list) or len(frames) != total or not isinstance(rows, list) or not isinstance(events, list) or record.get("engineBuild") != "196":
        raise ValueError("精读续跑缺少完整原生帧、文字行或事件")
    sha_pattern = re.compile(r"[a-f0-9]{64}")
    prefix = "file:" + record["video_sha256"] + ":frame:"
    previous = -1.0
    for index, frame in enumerate(frames):
        time = frame.get("time")
        if frame.get("frameIndex") != index or frame.get("frameId") != prefix + str(index) or not isinstance(time, (int, float)) or isinstance(time, bool) or not math.isfinite(time) or time <= previous or not sha_pattern.fullmatch(str(frame.get("sourcePixelSha256", ""))):
            raise ValueError("精读续跑原生帧身份或顺序无效")
        previous = time
    roles = record.get("roleDecisions")
    if not isinstance(roles, list) or len(roles) != len(rows) or any(type(role.get("rowIndex")) is not int for role in roles) or {role["rowIndex"] for role in roles} != set(range(len(rows))):
        raise ValueError("精读续跑原始角色映射不完整")
    by_role = {role["rowIndex"]: role for role in roles}
    for index, row in enumerate(rows):
        frame_index, box = row.get("frameIndex"), row.get("sourceRect")
        if row.get("index") != index or type(frame_index) is not int or not 0 <= frame_index < total or not isinstance(box, dict):
            raise ValueError("精读续跑文字行身份无效")
        frame = frames[frame_index]
        if row.get("frameId") != frame["frameId"] or row.get("time") != frame["time"] or row.get("frameTime") != frame["time"] or not isinstance(row.get("text"), str) or not sha_pattern.fullmatch(str(row.get("cropPixelsSha256", ""))):
            raise ValueError("精读续跑文字行不属于原生帧")
        if any(type(box.get(key)) is not int for key in ("left", "top", "right", "bottom")) or not 0 <= box["left"] < box["right"] <= row.get("sourceWidth", -1) or not 0 <= box["top"] < box["bottom"] <= row.get("sourceHeight", -1) or row.get("inputWidth") != box["right"] - box["left"] or row.get("inputHeight") != box["bottom"] - box["top"]:
            raise ValueError("精读续跑原生裁剪无效")
    seen_rows, event_ids, jobs = set(), set(), []
    for event in events:
        event_id, indices = event.get("id"), event.get("rowIndices")
        if not isinstance(event_id, str) or not event_id or event_id in event_ids or event.get("layer") not in ("body", "recovery", "screen") or not isinstance(indices, list) or not indices or event.get("selectedRowIndex") not in indices:
            raise ValueError("精读续跑事件身份无效或重复")
        event_ids.add(event_id)
        if any(not isinstance(event.get(key), list) or len(event[key]) != len(indices) for key in ("frameIndices", "frameIds", "observationTimes")):
            raise ValueError("精读续跑事件原生归属不完整")
        if event.get("firstObserved") != event["observationTimes"][0] or event.get("lastObserved") != event["observationTimes"][-1]:
            raise ValueError("精读续跑事件观察时间无效")
        for position, row_index in enumerate(indices):
            if type(row_index) is not int or not 0 <= row_index < len(rows) or row_index in seen_rows:
                raise ValueError("精读续跑事件重复使用或伪造原始行")
            row, role = rows[row_index], by_role[row_index]
            layer = "body" if role.get("decision") == "proposed_caption" else "recovery" if role.get("decision") == "visible_recovery_candidate" else "screen"
            if event["frameIndices"][position] != row["frameIndex"] or event["frameIds"][position] != row["frameId"] or event["observationTimes"][position] != row["time"] or event.get("text") != row["text"] or event.get("rawMobileText") != row["text"] or event["layer"] != layer or event.get("familyId") != role.get("familyId") or (event.get("captionLaneId") or None) != (role.get("captionLaneId") or None):
                raise ValueError("精读续跑事件与原始行、角色不一致")
            seen_rows.add(row_index)
        if event["layer"] != "screen":
            jobs.append(event)
        if event.get("nativeExpandedReads") or event.get("nativeGlyphReceipts") or event.get("nativeExpansion") is not None or event.get("nativeGlyphStatus") is not None:
            raise ValueError("精读检查点混入后续补读阶段")
    if any(row["text"].strip() and row["index"] not in seen_rows for row in rows):
        raise ValueError("精读续跑遗漏原始文字行")
    if not isinstance(queue, dict) or any(not isinstance(queue.get(key), list) for key in ("completed", "pending", "failed")) or queue["failed"] or record.get("extentPrecisionCheckpoint") is not None:
        raise ValueError("精读续跑队列无效或含失败/后续阶段")
    completed, pending = [], []
    for event in jobs:
        precision = event.get("precision")
        if precision is None:
            if event.get("precisionCalibration") is not None:
                raise ValueError("未完成精读混入校准读数")
            pending.append(event["id"])
            continue
        row, calibration = rows[event["selectedRowIndex"]], event.get("precisionCalibration")
        saved_reading = {"text": row["text"], "confidence": row["confidence"], "charConfidences": row.get("charConfidences") or [], "minCharConfidence": row.get("minCharConfidence") if isinstance(row.get("minCharConfidence"), (int, float)) else 0}
        if row.get("tokenAlignment"):
            saved_reading["tokenAlignment"] = row["tokenAlignment"]
        if not isinstance(precision, dict) or precision.get("status") != "read" or precision.get("rowIndex") != row["index"] or precision.get("frameIndex") != row["frameIndex"] or precision.get("frameId") != row["frameId"] or precision.get("time") != row["time"] or precision.get("cropPixelsSha256") != row["cropPixelsSha256"] or precision.get("sourceRect") != row["sourceRect"] or precision.get("modelId") != "PP-OCRv6_medium_rec" or precision.get("modelSha256") != runtime.get("sha256", {}).get("subtitles/vendor/precision-rec.onnx") or precision.get("calibrationExact") is not True or precision.get("nativeOriginalColor") is not True or precision.get("representativeOnly") is not True or not isinstance(calibration, dict) or calibration.get("rowIndex") != row["index"] or calibration.get("exact") is not True or calibration.get("reading") != saved_reading:
            raise ValueError("已完成精读缺少严格原图、模型与校准回执")
        completed.append(event["id"])
    if not pending or queue["completed"] != completed or queue["pending"] != pending or len(set(completed + pending)) != len(jobs) or [event["id"] for event in jobs] != completed + pending:
        raise ValueError("精读续跑必须是未重叠、无遗漏的原始已读前缀与待办后缀")


def load_resume_record(path: Path, expected_sha: str, video: Path, runtime: dict, work_id: str = "") -> dict:
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha or "") or digest(path) != expected_sha:
        raise ValueError("续跑记录SHA不一致")
    record = json.loads(path.read_text(encoding="utf-8-sig"))
    source_sha = digest(video)
    if record.get("video_sha256") != source_sha or record.get("sourceIdentity") != {"kind": "local_file_sha256", "sha256": source_sha}:
        raise ValueError("续跑记录不属于当前原片")
    if record.get("runtime") != runtime:
        raise ValueError("续跑识别资源与原记录不相同")
    if work_id and record.get("workId", "") != work_id:
        raise ValueError("续跑作品身份不一致")
    if record.get("phase") not in ("precision", "extent_precision") or record.get("processingComplete") is True or record.get("state") not in ("partial", "cancelled"):
        raise ValueError("当前候选只支持完整采样后仍有精读或补读待办的检查点")
    if record.get("phase") == "precision":
        validate_precision_resume_record(record, runtime)
    elif record.get("processed") != record.get("total") or record.get("precisionCheckpoint", {}).get("pending") or not record.get("extentPrecisionCheckpoint", {}).get("pending"):
        raise ValueError("续跑检查点未完成先前阶段或没有待补读项")
    return record


def resume_plan(record: dict, checkpoint_sha: str, adapter_sha: str) -> dict:
    pending = record.get("precisionCheckpoint", {}).get("pending", []) if record["phase"] == "precision" else []
    return {"checkpointSha256": checkpoint_sha, "adapterSha256": adapter_sha, "phase": record["phase"],
            "strictNativeValidationRequiredBeforeExecution": True, "expectedNewDetectionCalls": 0,
            "expectedNewMobileCalls": 0, "expectedNewBasePrecisionCalls": len(pending),
            "basePendingEventIds": list(pending), "expectedCachedMobileCalibrationReads": len(pending),
            "expandedQueueDerivedAfterBasePrecision": bool(pending),
            "maximumNewExpandedPrecisionCalls": sum(event.get("layer") == "body" for event in record.get("events", [])) if pending else len(record["extentPrecisionCheckpoint"]["pending"]),
            "nativeFramesToRecapture": len(record["raw"]["frames"])}


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        value = hashlib.sha256()
        for part in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(part)
        return value.hexdigest()


def runtime_receipt() -> dict:
    manifest_file = ASSETS / "runtime-manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    hashes = manifest.get("sha256")
    required = {"native-runner.js", "subtitles/new-pipeline.js", "subtitles/recognizer-worker.js",
                "subtitles/vendor/det.onnx", "subtitles/vendor/rec.onnx", "subtitles/vendor/precision-rec.onnx",
                "lib/vendor/opencc/t2cn.js", "lib/subtitle-working-groups-v198.js",
                "lib/subtitle-frame-queue-v201.js",
                "lib/subtitle-working-candidates-v198.js", "lib/subtitle-storyboard.js", "lib/subtitle-output.js"}
    if not isinstance(hashes, dict) or not required <= hashes.keys():
        raise ValueError("高质量字幕组件不完整")
    for relative, expected in hashes.items():
        if not isinstance(relative, str) or not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise ValueError("高质量字幕组件清单无效")
        candidate = (ASSETS / relative).resolve()
        if ASSETS.resolve() not in candidate.parents or not candidate.is_file() or digest(candidate) != expected:
            raise ValueError("高质量字幕组件校验失败")
    return {"wrapperVersion": WRAPPER_VERSION, "mode": "native_detected_lines", "pipelineId": manifest["pipelineId"],
            "engineName": manifest["engine"], "manifestSha256": digest(manifest_file), "sha256": hashes,
            "accuracy": "machine_unverified", "releaseStatus": "candidate_not_accepted"}


def asset(pathname: str) -> Path | None:
    candidate = (ASSETS / unquote(pathname).lstrip("/")).resolve()
    return candidate if ASSETS.resolve() in candidate.parents and candidate.is_file() else None


def validate_outputs(out: Path) -> None:
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError("高质量字幕输出目录必须为空，不覆盖已有资料")


def safe_image_path(out: Path, name: str) -> Path:
    if not re.fullmatch(r"(?:画面/[0-9]{3,5}_[0-9]{2,3}_[0-9]{1,3}[.][0-9]{2}秒|images/[A-Za-z0-9_.-]+)[.]jpg", name):
        raise ValueError("逐句画面路径无效")
    path = (out / name).resolve()
    if out.resolve() not in path.parents:
        raise ValueError("逐句画面不能写到输出目录外")
    return path


def persist_json(path: Path, payload: dict, *, compact: bool = False) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    # Progress keeps every complete, awaited checkpoint; only whitespace differs.
    # Final user-facing records retain the default readable representation.
    options = {"separators": (",", ":")} if compact else {"indent": 2}
    temporary.write_text(json.dumps(payload, ensure_ascii=False, **options), encoding="utf-8")
    temporary.replace(path)


def decode_progress_snapshot(serialized: str) -> dict:
    """Avoid recursive browser argument conversion without changing evidence."""
    if not isinstance(serialized, str) or len(serialized) > 256 * 1024 * 1024:
        raise ValueError("本地字幕进度数据无效或过大")
    value = json.loads(serialized)
    if not isinstance(value, dict):
        raise ValueError("本地字幕进度不是有效记录")
    return value


def record_result(result: dict, identity: dict, runtime: dict, verification: str) -> dict:
    if not isinstance(result, dict) or not isinstance(result.get("raw", {}), dict):
        raise ValueError("原生字幕记录格式无效")
    if result.get("sourceIdentity") != {"kind": "local_file_sha256", "sha256": identity["video_sha256"]}:
        raise ValueError("原生字幕记录不属于当前文件")
    return {**result, **identity, "runtime": runtime, "runtimeVerification": verification,
            "mode": "native_detected_lines", "regionMode": "automatic_detected_native_lines",
            "regionManuallyConfirmed": False, "accuracy": "machine_unverified", "uploaded": False,
            "audio_transcribed": False, "time_basis": "sampled_observation_range"}


def journal_candidates(segment: dict) -> list[tuple[str, str]]:
    """Inert presentation of actual recorded candidates; never select or merge."""
    candidates, seen, keys = [], set(), set()
    def add(event_id, value):
        text = value.get("text") or value.get("actualText") if isinstance(value, dict) else value
        if isinstance(text, str) and text and (event_id, text) not in keys:
            keys.add((event_id, text))
            candidates.append((event_id, text))
    def visit(value):
        if not isinstance(value, dict) or id(value) in seen:
            return
        seen.add(id(value))
        event_id = str(value.get("id") or value.get("eventId") or "")
        status = value.get("criticalReadingStatus") or {}
        if status.get("hasCriticalConflict"):
            for candidate in status.get("candidates", []):
                add(event_id, candidate)
        notice = value.get("presentationNotice") or {}
        if notice.get("hasCriticalConflict"):
            for candidate in notice.get("distinctCandidateTexts", []):
                add(event_id, candidate)
        if value.get("ambiguousActualReadings") or value.get("presentationChoiceRequired"):
            for candidate in value.get("presentationVariants") or value.get("variants") or []:
                add(event_id, candidate)
        for key in ("originalEventSegments", "originalProjectedWorkingCues", "sourceSegments"):
            for child in value.get(key) or []:
                visit(child)
        for child in (value.get("compoundLayout") or {}).get("originalSegments") or []:
            visit(child)
    visit(segment)
    return candidates


def journal_text(result: dict, identity: dict) -> str:
    lines = ["视频画面字幕（自动逐行检测 · 候选检查点）", "作品：" + identity["title"],
             "状态：" + str(result.get("state")),
             "时间是采样观察范围，不是精确字幕轴。以下均为机器工作读数，未全文人工核验；JSON保留所有原始证据。", ""]
    for index, segment in enumerate(result.get("segments", []), 1):
        candidates = journal_candidates(segment)
        ambiguous = bool(segment.get("ambiguousActualReadings") or segment.get("presentationChoiceRequired"))
        text = str(segment.get("text", ""))
        if ambiguous:
            text = "［候选导航标题，非确定读数］" + text
        elif candidates or (segment.get("criticalReadingStatus") or {}).get("hasCriticalConflict") or (segment.get("presentationNotice") or {}).get("hasCriticalConflict"):
            text += "［关键读数待核对］"
        lines.append(observed_segment({**segment, "text": text}))
        if candidates:
            lines.append("本段实际识别候选（不作为多句正文，未选择正确答案）：")
            for number, (event_id, candidate) in enumerate(candidates, 1):
                lines.append(f"候选 {number}" + (f"（事件 {event_id}）" if event_id else "") + "：" + candidate)
        elif ambiguous:
            lines.append("候选读数尚未完整形成；请查看JSON，不能将导航标题视为确定识别结果。")
        lines.append("")
    return "\n".join(lines)


def write_final(out: Path, value: dict, record: dict) -> None:
    with_frames = record.get("captureMode", "with_frames") == "with_frames"
    package_name = "字幕画面工作包.zip" if with_frames else "字幕工作包.zip"
    package = out / package_name
    temporary_package = out / (package_name + ".tmp")
    if any((out / name).exists() or (out / (name + ".tmp")).exists() for name in ("字幕画面工作包.zip", "字幕工作包.zip")):
        raise ValueError("工作包已存在，不覆盖先前产物")
    files = [("视频字幕.txt", value["timed"]), ("字幕正文.txt", value["plain"]), ("机器分段.csv", value["csv"])]
    if with_frames:
        files.extend([("逐句图文.md", value["documents"]["markdown"]),
                      ("逐句图文.html", value["documents"]["html"]), ("逐句配图.csv", value["documents"]["csv"])])
    for name, body in files:
        (out / name).write_text(body, encoding="utf-8-sig" if name.endswith((".txt", ".csv")) else "utf-8")
    if value.get("review"):
        (out / "字幕疑点.txt").write_text(value["review"], encoding="utf-8-sig")
    if value.get("recovery"):
        (out / "待确认字幕候选.txt").write_text(value["recovery"], encoding="utf-8-sig")
    persist_json(out / "字幕识别记录.json", record)
    if with_frames:
        persist_json(out / "配图清单.json", value["documents"]["manifest"])
    with zipfile.ZipFile(temporary_package, "x", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for file in sorted(out.rglob("*")):
            if file.is_file() and file.name not in ("字幕画面工作包.zip", "字幕工作包.zip") and not file.name.endswith(".tmp"):
                archive.write(file, file.relative_to(out).as_posix())
    if package.exists():
        raise ValueError("工作包已存在，不覆盖先前产物")
    temporary_package.rename(package)


async def extract_detected(video: Path, out: Path, executable: str = "", work_id: str = "", deadline: int = 1200,
                           resume_record: Path | None = None, resume_sha256: str = "", include_frames: bool = False) -> dict:
    video, out = video.resolve(), out.resolve()
    validate_video(video, .5)
    validate_outputs(out)
    if type(include_frames) is not bool:
        raise ValueError("配图开关必须是明确布尔值")
    capture_mode = "with_frames" if include_frames else "text_only"
    if not isinstance(deadline, int) or not 60 <= deadline <= 1800:
        raise ValueError("本地检测处理时限应为 60—1800 秒")
    runtime = runtime_receipt()
    identity = {"video_sha256": digest(video), "title": video.name, "workId": work_id}
    resume = load_resume_record(resume_record.resolve(), resume_sha256, video, runtime, work_id) if resume_record else None
    adapter_sha = digest(ASSETS / "resume-runner.js") if resume else None
    if resume:
        identity.update(title=resume.get("title", video.name), workId=resume.get("workId", ""))
    out.mkdir(parents=True, exist_ok=True)
    state = resume or {"state": "ready", "sourceIdentity": {"kind": "local_file_sha256", "sha256": identity["video_sha256"]},
                       "raw": {"frames": [], "rows": []}, "segments": [], "phase": "frames"}
    state = {**state, "captureMode": capture_mode}
    images, last_progress = [], None
    verification = "verified_before_run"
    operation = "dependency"
    diagnostic = None
    resume_eligibility = {"status": "not_checked", "strictNativeValidated": False, "canResumePrecision": False, "canResumeExtent": False}

    def persist(result):
        nonlocal state, last_progress
        state = {**result, "captureMode": capture_mode}
        record = record_result(state, identity, runtime, verification)
        if diagnostic:
            record["safeFailure"] = diagnostic
            record["resumeEligibility"] = resume_eligibility
        if resume:
            record["resumeSource"] = {"checkpointSha256": resume_sha256, "adapterSha256": adapter_sha,
                                      "originalRuntimeManifestSha256": runtime["manifestSha256"], "originalPhase": resume["phase"],
                                      "priorSafeFailure": resume.get("safeFailure"), "priorResumeEligibility": resume.get("resumeEligibility")}
            if not diagnostic:
                record.pop("safeFailure", None)
                record.pop("resumeEligibility", None)
        persist_json(out / "字幕识别记录.json", record, compact=True)
        (out / "视频字幕.txt").write_text(journal_text(state, identity), encoding="utf-8-sig")
        count = (state.get("extentPrecisionCheckpoint") if state.get("phase") == "extent_precision" else state.get("precisionCheckpoint")) or {}
        marker = (state.get("phase"), state.get("processed"), len(count.get("completed", [])), state.get("state"))
        if marker != last_progress:
            print(json.dumps({"event": "subtitle_progress", "mode": "native_detected_lines",
                              "phase": state.get("phase"), "state": state.get("state"), "frames": state.get("processed", 0),
                              "total": state.get("total", 0), "queueCounts": {
                                  "completed": len(count.get("completed", [])), "pending": len(count.get("pending", [])),
                                  "failed": len(count.get("failed", [])), "skipped": len(count.get("skipped", []))}}, ensure_ascii=False), flush=True)
            last_progress = marker

    async def save_image(value):
        if not include_frames:
            raise ValueError("纯文本字幕任务未请求保存配图")
        path = safe_image_path(out, value["path"])
        content = base64.b64decode(value["base64"], validate=True)
        if not content.startswith(b"\xff\xd8") or len(content) > 8 * 1024 * 1024:
            raise ValueError("逐句图不是有效的受限JPEG")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(content)
        images.append({k: v for k, v in value.items() if k != "base64"} | {"jpegSha256": hashlib.sha256(content).hexdigest()})

    persist(state)
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            operation = "browser_launch"
            browser = await playwright.chromium.launch(headless=True, executable_path=chrome_path(executable))
            try:
                context = await browser.new_context(service_workers="block")
                async def serve(route):
                    parsed = urlparse(route.request.url)
                    if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
                        return await route.abort()
                    if parsed.path == "/":
                        # Script order is declared in the shipped runner, not inherited from a platform page.
                        paths = json.loads((ASSETS / "runtime-manifest.json").read_text(encoding="utf-8"))["scriptPaths"]
                        paths = paths + (["native-runner.js", "resume-runner.js"] if resume else ["native-runner.js"])
                        html = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"></head><body><video id="video" muted playsinline></video>' + "".join('<script src="/' + p + '"></script>' for p in paths) + "</body></html>"
                        return await route.fulfill(content_type="text/html; charset=utf-8", body=html)
                    if parsed.path == "/__input_video__":
                        return await route.fulfill(path=video, content_type="video/mp4")
                    if parsed.path == "/__resume_checkpoint__" and resume:
                        return await route.fulfill(path=resume_record, content_type="application/json; charset=utf-8")
                    file = asset(parsed.path)
                    if file is None:
                        return await route.abort()
                    kind = "application/javascript; charset=utf-8" if file.suffix in (".js", ".mjs") else mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                    return await route.fulfill(path=file, content_type=kind)
                await context.route("**/*", serve)
                page = await context.new_page()
                await page.expose_function("subtitleNativeProgress", persist)
                await page.expose_function("subtitleNativeProgressSerialized", lambda value: persist(decode_progress_snapshot(value)))
                if include_frames:
                    await page.expose_function("subtitleNativeImage", save_image)
                operation = "page_load"
                await page.goto(ORIGIN)
                operation = "pipeline_run"
                parameters = {"videoSha256": identity["video_sha256"], "title": identity["title"], "workId": identity["workId"],
                              "includeFrames": include_frames}
                if resume:
                    parameters.update(checkpointSha256=resume_sha256, runtime=runtime, adapterSha256=adapter_sha)
                function = "parameters => BrandbaiDetectedSubtitleResume.run(parameters)" if resume else "parameters => BrandbaiDetectedSubtitleRunner.run(parameters)"
                value = await asyncio.wait_for(page.evaluate(function, parameters), timeout=deadline)
                operation = "verify_runtime"
                if runtime_receipt() != runtime or digest(video) != identity["video_sha256"]:
                    verification = "changed_after_run"
                    raise ValueError("源视频或字幕组件在处理期间变化")
                if resume and (digest(resume_record) != resume_sha256 or digest(ASSETS / "resume-runner.js") != adapter_sha):
                    verification = "changed_after_run"
                    raise ValueError("续跑检查点或独立恢复适配器在处理期间变化")
                verification = "unchanged_before_after_run"
                state = {**value["result"], "captureMode": capture_mode}
                record = record_result(state, identity, runtime, verification)
                record["runtimeBrowser"] = value["runtimeBrowser"]
                record["storyboardImages"] = images
                record["frameStorage"] = value["frameStorage"]
                if resume:
                    record["resumeExecution"] = value["resumeExecution"]
                    record["resumeSource"] = {"checkpointSha256": resume_sha256, "adapterSha256": adapter_sha,
                                              "originalRuntimeManifestSha256": runtime["manifestSha256"], "originalPhase": resume["phase"],
                                              "priorSafeFailure": resume.get("safeFailure"), "priorResumeEligibility": resume.get("resumeEligibility")}
                    record.pop("safeFailure", None)
                    record.pop("resumeEligibility", None)
            finally:
                active_error = sys.exc_info()[0] is not None
                if not active_error:
                    operation = "close_browser"
                if active_error and "page" in locals():
                    try:
                        unchanged = runtime_receipt() == runtime and digest(video) == identity["video_sha256"]
                        eligibility = await asyncio.wait_for(page.evaluate("serialized => ({valid: BrandbaiHighQualitySubtitles.validResume(JSON.parse(serialized))})", json.dumps(state, ensure_ascii=False, separators=(",", ":"))), timeout=5)
                        valid = unchanged and eligibility.get("valid") is True
                        can_resume = valid and state.get("phase") == "extent_precision" and bool(state.get("extentPrecisionCheckpoint", {}).get("pending")) and not state.get("precisionCheckpoint", {}).get("pending") and state.get("processingComplete") is not True
                        can_precision = False
                        if valid and state.get("phase") == "precision" and state.get("processingComplete") is not True:
                            try:
                                validate_precision_resume_record({**state, **identity}, runtime)
                                can_precision = True
                            except (ValueError, KeyError, TypeError):
                                pass
                        resume_eligibility = {"status": "validated" if valid else "rejected", "strictNativeValidated": valid, "canResumePrecision": can_precision, "canResumeExtent": can_resume}
                    except BaseException:
                        resume_eligibility = {"status": "unavailable", "strictNativeValidated": False, "canResumePrecision": False, "canResumeExtent": False}
                try:
                    await browser.close()
                except Exception:
                    if not active_error:
                        operation = "close_browser"
                        raise
        # Commit a final package only after browser and Playwright cleanup both
        # succeeded. A cleanup error leaves an explicitly partial journal and
        # diagnostic, not a stale processed ZIP.
        operation = "verify_runtime"
        if runtime_receipt() != runtime or digest(video) != identity["video_sha256"] or resume and (
                digest(resume_record) != resume_sha256 or digest(ASSETS / "resume-runner.js") != adapter_sha):
            verification = "changed_after_run"
            raise ValueError("最终保存前原片、识别资源或恢复回执发生变化")
        operation = "export_files"
        write_final(out, value, record)
    except BaseException as error:
        diagnostic = safe_failure(error, state.get("phase", ""), operation)
        persist_json(out / "运行诊断.json", {**diagnostic, "processedFrames": state.get("processed", 0),
                     "totalFrames": state.get("total", 0), "resumeEligibility": resume_eligibility})
        persist({**state, "state": "partial", "error": "本地检测处理未完成，已有原始记录保留，无云端回退"})
        print(json.dumps({"event": "subtitle_error", **diagnostic}, ensure_ascii=False), file=sys.stderr, flush=True)
        raise
    complete = state.get("processingComplete") is True and state.get("state") in ("processed", "empty")
    return {"requested": True, "mode": "native_detected_lines", "state": state["state"],
            "captureMode": capture_mode,
            "segments": len(state.get("segments", [])), "images": len(images), "runtime": runtime,
            "runtimeVerification": verification, "accuracy": "machine_unverified", "exit_code": 0 if complete else 3,
            "releaseStatus": "candidate_not_accepted"}
