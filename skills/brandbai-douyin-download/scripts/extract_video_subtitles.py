"""Opt-in local screen-subtitle OCR for one downloaded video. No ASR or network."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlparse

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "subtitles"
ORIGIN = "https://brandbai-subtitles.invalid"
MAX_BYTES = 150 * 1024 * 1024
WRAPPER_VERSION = "0.6.3"


def validate_video(video: Path, interval: float) -> None:
    if not video.is_file() or video.stat().st_size <= 0 or video.stat().st_size > MAX_BYTES:
        raise ValueError("请选择非空且不超过 150 MB 的本地视频")
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or not .25 <= interval <= 1:
        raise ValueError("采样间隔应在 0.25—1 秒之间")


def runtime_receipt() -> dict:
    """Verify the shipped bundle and describe it, without claiming OCR accuracy."""
    for required in ["engine.js", "recognizer.js", "recognizer-worker.js", "vendor/manifest.json"]:
        if not (ASSETS / required).is_file():
            raise ValueError("字幕组件不完整，请使用含本地识别资源的完整 Skill 包")
    vendor = (ASSETS / "vendor").resolve()
    manifest_path = vendor / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    hashes = manifest.get("sha256")
    if not isinstance(manifest.get("engine"), str) or not manifest["engine"].strip() or not isinstance(hashes, dict) or not {"rec.onnx", "keys.txt"} <= hashes.keys():
        raise ValueError("字幕组件清单缺少模型身份或哈希")
    for relative, expected in hashes.items():
        if not isinstance(relative, str) or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("字幕组件哈希清单无效")
        asset = (vendor / relative).resolve()
        if vendor not in asset.parents or not asset.is_file() or hashlib.sha256(asset.read_bytes()).hexdigest() != expected:
            raise ValueError("字幕组件校验失败，不加载未经确认的识别代码")
    return {
        "wrapperVersion": WRAPPER_VERSION,
        "engineName": manifest["engine"],
        "engineVersion": manifest.get("model_version") or manifest.get("version") or manifest["engine"],
        "engineVersionBasis": "bundled_vendor_manifest",
        "modelRegistry": manifest.get("model_registry"),
        "packages": manifest.get("packages", {}),
        "modelSha256": hashes["rec.onnx"], "dictionarySha256": hashes["keys.txt"],
        "manifestSha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "codeSha256": {name: hashlib.sha256((ASSETS / name).read_bytes()).hexdigest()
                       for name in ["engine.js", "recognizer.js", "recognizer-worker.js"]},
    }


def result_record(identity: dict, state: dict, selected: dict, interval: float, runtime: dict) -> dict:
    if not isinstance(state, dict) or not isinstance(state.get("segments", []), list):
        raise ValueError("字幕引擎返回格式无效")
    reported_engine = state.get("engine")
    if reported_engine and reported_engine != runtime["engineName"]:
        raise ValueError("字幕引擎声明与随包模型不一致，请重新检查完整包")
    return {**state, **identity, "source": "screen_ocr", "region": selected, "interval": interval,
            "engine": runtime["engineName"], "runtime": runtime,
            "accuracy": "machine_unverified", "audio_transcribed": False, "uploaded": False,
            "time_basis": "sampled_observation_range"}


def verify_runtime_unchanged(expected: dict) -> None:
    if runtime_receipt() != expected:
        raise ValueError("字幕组件在处理期间发生变化，本次不能确认实际引擎版本，请使用完整固定版本重新运行")


def observed_time(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    centiseconds = math.floor(value * 100 + 1e-6)
    minutes, remainder = divmod(centiseconds, 6000)
    seconds, fraction = divmod(remainder, 100)
    return f"{minutes:02}:{seconds:02}.{fraction:02}"


def observed_segment(segment: dict) -> str:
    first, last = observed_time(segment.get("firstObserved")), observed_time(segment.get("lastObserved"))
    if first is None or last is None or segment.get("lastObserved", -1) < segment.get("firstObserved", 0):
        return f"[时间待确认] {segment.get('text', '')}"
    return f"[{first}–{last}] {segment.get('text', '')}"


def parse_region(value: str) -> dict:
    try:
        left, top, right, bottom = (float(part) for part in value.split(","))
    except (ValueError, TypeError) as exc:
        raise ValueError("区域格式应为 left,top,right,bottom，范围 0—1") from exc
    if not all(0 <= n <= 1 for n in [left, top, right, bottom]) or right - left < .05 or bottom - top < .02:
        raise ValueError("字幕区域无效")
    return dict(left=left, top=top, right=right, bottom=bottom)


def chrome_path(explicit: str = "") -> str | None:
    if explicit:
        if not Path(explicit).is_file():
            raise ValueError("指定的 Chrome 不存在")
        return explicit
    for base in [os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""), os.environ.get("LOCALAPPDATA", "")]:
        if not base:
            continue
        candidate = Path(base) / "Google/Chrome/Application/chrome.exe"
        if candidate.is_file():
            return str(candidate)
    return None  # Playwright-managed Chromium; no browser is downloaded automatically.


def local_asset(pathname: str) -> Path | None:
    candidate = (ASSETS / unquote(pathname).lstrip("/")).resolve()
    if ASSETS.resolve() not in candidate.parents or not candidate.is_file():
        return None
    return candidate


async def extract(video: Path, out: Path, selected: dict, executable: str = "", language: str = "chi_sim+eng", line_mode: str = "7", work_id: str = "", interval: float = .5) -> dict:
    video, out = video.resolve(), out.resolve()
    validate_video(video, interval)
    record = out / "字幕识别记录.json"
    text = out / "视频字幕.txt"
    if record.exists() or text.exists():
        raise ValueError("此输出目录已有字幕结果，请换一个目录；不会覆盖旧结果")
    selected = parse_region(",".join(str(selected[k]) for k in ["left", "top", "right", "bottom"]))
    if line_mode != "7":
        raise ValueError("首版仅支持固定位置的单行字幕")
    if language not in ["chi_sim", "eng", "chi_sim+eng"]:
        raise ValueError("请选择内置语言")
    runtime = runtime_receipt()
    from playwright.async_api import async_playwright
    out.mkdir(parents=True, exist_ok=True)
    state = {"state": "ready", "source": "screen_ocr", "processed": 0, "total": 0, "segments": [], "region": selected}
    identity = {"workId": work_id, "title": video.name, "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest()}
    last_printed = -20
    runtime_verification = "verified_before_run"

    def persist(result):
        nonlocal state, last_printed
        payload = result_record(identity, result, selected, interval, runtime)
        payload["runtimeVerification"] = runtime_verification
        state = result
        temporary = record.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(record)
        lines = ["视频字幕（画面识别）", f"来源文件：{video.name}", f"作品ID：{work_id}" if work_id else "来源：用户选定的本地视频",
                 f"状态：{state.get('state')}；已处理 {state.get('processed', 0)}/{state.get('total', 0)} 帧",
                 f"本地识别引擎：{runtime['engineName']}；Skill {WRAPPER_VERSION}",
                 "仅识别所选区域与采样时刻。可能错漏、混入画面文字；不是音频转写或发布文案，不代表完整口播。", "",
                 "时间为采样观察范围，供素材回看、脚本整理和剪辑定位；不是精确字幕起止。",
                 "连续重复已自动保守整理，未全文人工核验；原始观察保留在识别记录中。", "",
                 *(observed_segment(s) for s in state.get("segments", []))]
        temporary = text.with_suffix(".txt.tmp")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
        temporary.replace(text)
        if state.get("processed", 0) - last_printed >= 20 or state.get("state") != "running":
            print(json.dumps({"event": "subtitle_progress", "state": state.get("state"), "frames": state.get("processed", 0), "total": state.get("total", 0), "segments": len(state.get("segments", []))}, ensure_ascii=False), flush=True)
            last_printed = state.get("processed", 0)

    persist(state)
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, executable_path=chrome_path(executable))
            try:
                context = await browser.new_context(service_workers="block")
                async def serve(route):
                    url = urlparse(route.request.url)
                    if f"{url.scheme}://{url.netloc}" != ORIGIN:
                        return await route.abort()
                    if url.path == "/":
                        return await route.fulfill(content_type="text/html; charset=utf-8", body='<!doctype html><html><head><meta charset="utf-8"></head><body><video id="video" muted></video><script src="/recognizer.js"></script><script src="/engine.js"></script></body></html>')
                    if url.path == "/__input_video__":
                        return await route.fulfill(path=video, content_type="video/mp4")
                    asset = local_asset(url.path)
                    if not asset:
                        return await route.abort()
                    return await route.fulfill(path=asset, content_type="application/javascript; charset=utf-8" if asset.suffix in [".js", ".mjs"] else (mimetypes.guess_type(asset.name)[0] or "application/octet-stream"))
                await context.route("**/*", serve)
                page = await context.new_page()
                await page.expose_function("subtitleProgress", persist)
                await page.goto(ORIGIN)
                result = await asyncio.wait_for(page.evaluate("""async ({selected,language,lineMode,interval}) => {
                  // Classic scripts otherwise inherit the document encoding. A
                  // Latin-decoded Chinese regex still executes but silently loses
                  // punctuation and protected-word rules; fail before OCR instead.
                  const documentEncoding = document.characterSet;
                  const api = globalThis.BrandbaiSubtitles;
                  const chineseRulesValid = api?.comparisonKey('。合成 字幕。') === '合成字幕'
                    && api.protectedSignature('不能喝一杯') !== api.protectedSignature('能喝一杯');
                  if (documentEncoding.toUpperCase() !== 'UTF-8' || !chineseRulesValid)
                    throw new Error('Local subtitle page encoding or Chinese rules failed validation');
                  const video = document.getElementById('video');
                  video.src = URL.createObjectURL(await (await fetch('/__input_video__')).blob());
                  await new Promise((resolve,reject) => {
                    const timer = setTimeout(()=>reject(new Error('Video decode timeout')),15000);
                    video.onloadeddata=()=>{clearTimeout(timer);resolve();};
                    video.onerror=()=>{clearTimeout(timer);reject(new Error('Video decode failed'));};
                  });
                  const session = new BrandbaiSubtitles.Session({video,baseUrl:new URL('/',location.href),region:selected,language,lineMode,interval,onProgress:window.subtitleProgress});
                  return {...await session.run(), runtimeBrowser: {documentEncoding, chineseRulesSmoke: 'passed'}};
                }""", {"selected": selected, "language": language, "lineMode": line_mode, "interval": interval}), timeout=600)
                try:
                    verify_runtime_unchanged(runtime)
                except (ValueError, OSError):
                    runtime_verification = "changed_or_unavailable_after_run"
                    raise
                runtime_verification = "unchanged_before_after_run"
                persist(result)
            finally:
                await browser.close()
    except BaseException:
        persist({**state, "state": "failed", "error": "本地字幕任务中断或失败，已保存部分结果；无自动云端回退"})
        raise
    return {"requested": True, "state": state["state"], "segments": len(state.get("segments", [])),
            "accuracy": "machine_unverified", "engine": runtime["engineName"], "runtime": runtime,
            "runtimeVerification": runtime_verification,
            "exit_code": 0 if state["state"] == "processed" else 3}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-file", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--region", required=True, help="Confirmed subtitle crop: left,top,right,bottom (0—1)")
    parser.add_argument("--chrome-path", default="")
    parser.add_argument("--language", choices=["chi_sim", "eng", "chi_sim+eng"], default="chi_sim+eng")
    parser.add_argument("--line-mode", choices=["7"], default="7")
    parser.add_argument("--work-id", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    executing = False
    try:
        selected = parse_region(args.region)
        video = Path(args.video_file)
        validate_video(video, .5)
        if args.dry_run:
            print(json.dumps({"mode":"local_screen_subtitles", "region":selected, "upload":False, "audio_transcription":False,
                              "video_bytes":video.stat().st_size, "runtime":runtime_receipt()}, ensure_ascii=False))
            return 0
        executing = True
        summary = asyncio.run(extract(video, Path(args.out), selected, args.chrome_path, args.language, args.line_mode, args.work_id))
        print(json.dumps(summary, ensure_ascii=False))
        return summary["exit_code"]
    except (ValueError, OSError) as exc:
        if executing:
            print("本地字幕处理未完成；已保存的结果不会删除。请检查完整组件、Chrome 与输出目录后重试。", file=sys.stderr)
            return 3
        parser.error(str(exc))
    except Exception:
        print("字幕处理失败；请检查 Chrome、本地识别资源或视频格式。若已有结果，输出目录会保留部分文字。", file=sys.stderr)
        return 3


if __name__ == "__main__":
    for stream in [sys.stdout, sys.stderr]:
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
