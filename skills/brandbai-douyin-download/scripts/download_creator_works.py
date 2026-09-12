"""Download pinned plus recent visible Douyin creator works through ordinary Chrome.

This is a clean-room browser route. It observes metadata returned by the normal
signed-in creator page, never exports cookies, never generates request
signatures, and never automates CAPTCHA or access-control bypasses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from package_delivery import package_directory
from selection_contract import (
    SelectionContractError,
    deduplicate as deduplicate_seeds,
    load_selection,
    seed_from_url,
)


INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MULTISPACE = re.compile(r"\s+")
PROVIDER = "douyin_visible_chrome_page"
CHINA_TIMEZONE = timezone(timedelta(hours=8))
ASSET_KINDS = {"primary", "cover", "audio", "caption"}
RESPONSE_TOKENS = (
    "aweme/post",
    "aweme/listcollection",
    "aweme/detail",
    "search/item",
    "general/search",
    "/search/",
)


class WorkDownloadError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def optional_int(*values: Any) -> int | None:
    for value in values:
        if value is None or value == "" or isinstance(value, bool):
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return None


def nested_get(value: Any, *path: str, default: Any = None) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def sanitize_name(value: Any, fallback: str = "未命名作品", max_length: int = 72) -> str:
    text = MULTISPACE.sub(" ", str(value or "")).strip().strip(".")
    text = INVALID_FILENAME.sub("_", text).strip(" ._")
    if not text:
        text = fallback
    return text[:max_length].rstrip(" ._") or fallback


def unique_urls(values: Iterable[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        url = str(value or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        output.append(url)
    return output


def url_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return unique_urls([value])
    if isinstance(value, list):
        return unique_urls(value)
    if not isinstance(value, dict):
        return []
    candidates: list[Any] = []
    for key in ("url_list", "urlList", "download_url_list", "downloadUrlList"):
        item = value.get(key)
        if isinstance(item, list):
            candidates.extend(item)
    for key in ("url", "download_url", "downloadUrl"):
        item = value.get(key)
        if isinstance(item, str):
            candidates.append(item)
        elif isinstance(item, dict):
            candidates.extend(url_list(item))
    return unique_urls(candidates)


def pick_posts(payload: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            aweme_id = str(value.get("aweme_id") or value.get("awemeId") or "")
            if aweme_id and aweme_id not in seen:
                seen.add(aweme_id)
                found.append(value)
                return
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return found


def search_dom_work_ids(page: Any) -> list[str]:
    """Return work IDs exposed by ordinary visible search result cards.

    Douyin's search page can render usable cards even when the corresponding
    JSON response was delivered before the listener was attached or uses a new
    response envelope. The public ``data-e2e-vid`` marker is therefore a safe
    discovery fallback; detail pages are still opened through normal Chrome to
    obtain the actual work metadata.
    """

    try:
        values = page.locator("[data-e2e-vid]").evaluate_all(
            "nodes => nodes.map(node => node.getAttribute('data-e2e-vid') || '')"
        )
    except Exception:
        return []
    output: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        aweme_id = str(value or "").strip()
        if not re.fullmatch(r"\d{10,24}", aweme_id) or aweme_id in seen:
            continue
        seen.add(aweme_id)
        output.append(aweme_id)
    return output


def find_chrome_path(explicit: str = "") -> str:
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        raise WorkDownloadError(f"Chrome executable does not exist: {candidate}")
    candidates: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    program_files = os.environ.get("PROGRAMFILES")
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)")
    if local:
        candidates.append(Path(local) / "Google/Chrome/Application/chrome.exe")
    if program_files:
        candidates.append(Path(program_files) / "Google/Chrome/Application/chrome.exe")
    if program_files_x86:
        candidates.append(Path(program_files_x86) / "Google/Chrome/Application/chrome.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    raise WorkDownloadError("Google Chrome was not found; pass --chrome-path")


def image_nodes(item: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [item.get("images"), nested_get(item, "image_post_info", "images")]
    for value in candidates:
        if isinstance(value, list) and value:
            return [node for node in value if isinstance(node, dict)]
    return []


def image_urls(node: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in (
        "download_url_list",
        "downloadUrlList",
        "download_url",
        "display_image",
        "displayImage",
        "origin_image",
        "originImage",
        "url_list",
    ):
        values.extend(url_list(node.get(key)))
    return unique_urls(values)


def video_urls(item: dict[str, Any]) -> list[str]:
    video = item.get("video") if isinstance(item.get("video"), dict) else {}
    ranked: list[tuple[int, list[str]]] = []
    bit_rates = video.get("bit_rate") or video.get("bitRate") or []
    if isinstance(bit_rates, list):
        for entry in bit_rates:
            if not isinstance(entry, dict):
                continue
            score = max(
                as_int(entry.get("bit_rate")),
                as_int(entry.get("bitRate")),
                as_int(entry.get("data_size")),
                as_int(entry.get("dataSize")),
            )
            urls: list[str] = []
            for key in ("play_addr", "playAddr", "play_addr_265", "playAddr265"):
                urls.extend(url_list(entry.get(key)))
            if urls:
                ranked.append((score, unique_urls(urls)))
    candidates: list[str] = []
    for _score, urls in sorted(ranked, key=lambda pair: pair[0], reverse=True):
        candidates.extend(urls)
    for key in (
        "play_addr",
        "playAddr",
        "play_addr_h264",
        "playAddrH264",
        "download_addr",
        "downloadAddr",
    ):
        candidates.extend(url_list(video.get(key)))
    return unique_urls(candidates)


def cover_urls(item: dict[str, Any]) -> list[str]:
    video = item.get("video") if isinstance(item.get("video"), dict) else {}
    candidates: list[str] = []
    for key in ("cover", "origin_cover", "originCover", "dynamic_cover", "dynamicCover"):
        candidates.extend(url_list(video.get(key)))
    if not candidates:
        for node in image_nodes(item)[:1]:
            candidates.extend(image_urls(node))
    return unique_urls(candidates)


def music_urls(item: dict[str, Any]) -> list[str]:
    music = item.get("music") if isinstance(item.get("music"), dict) else {}
    candidates: list[str] = []
    for key in ("play_url", "playUrl", "preview_url", "previewUrl"):
        candidates.extend(url_list(music.get(key)))
    return unique_urls(candidates)


def normalize_commerce_display_name(value: Any) -> str:
    text = MULTISPACE.sub(" ", str(value or "")).strip()[:180]
    if not text:
        return ""
    cleaned = re.sub(
        r"^(?:购物(?:车)?|小黄车|商品)(?:\s*[|｜:：·•-]+\s*|\s+)(?=\S)",
        "",
        text,
    ).strip()
    return cleaned or text


def normalize_commerce_anchor(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    display_name = normalize_commerce_display_name(
        value.get("display_name") or value.get("displayName") or value.get("name")
    )
    raw_url = str(value.get("url") or "").strip()
    direct_url = ""
    if raw_url:
        parsed = urllib.parse.urlparse(raw_url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            direct_url = raw_url
    declared = str(value.get("status") or "").strip()
    visible = bool(display_name or direct_url or declared.startswith("visible_"))
    status = "visible_direct_link" if direct_url else "visible_name_only" if visible else "not_observed" if declared == "not_observed" else ""
    if not status:
        return None
    return {
        "status": status,
        "display_name": display_name,
        "url": direct_url,
        "observed_at": str(value.get("observed_at") or value.get("observedAt") or ""),
        "source": str(value.get("source") or "current_work_dom"),
    }


def collect_visible_commerce_anchor(page: Any) -> dict[str, Any] | None:
    """Read only the currently rendered single-work commerce anchor surface."""
    try:
        observed = page.evaluate(
            r"""() => {
              const visible = (node) => {
                if (!(node instanceof Element)) return false;
                const rect = node.getBoundingClientRect();
                const style = getComputedStyle(node);
                if (!(rect.width > 2 && rect.height > 2 && style.display !== 'none' && style.visibility !== 'hidden')) return false;
                if (rect.bottom <= 0 || rect.right <= 0 || rect.top >= innerHeight || rect.left >= innerWidth) return false;
                const pointX = Math.min(innerWidth - 1, Math.max(0, rect.left + Math.min(rect.width / 2, 24)));
                const pointY = Math.min(innerHeight - 1, Math.max(0, rect.top + Math.min(rect.height / 2, 18)));
                const top = document.elementFromPoint(pointX, pointY);
                return !top || node.contains(top) || top.contains(node);
              };
              const root = document.querySelector('main,[role="main"],article') || document.body;
              const selector = [
                '[class~="xgplayer-shop-anchor"]','[class*="shop-anchor" i]',
                '[data-e2e*="goods" i]','[data-e2e*="product" i]','[data-e2e*="commerce" i]','[data-e2e*="shop" i]',
                '[class*="goods" i]','[class*="product" i]','[class*="commerce" i]','[class*="shopping" i]',
                '[aria-label*="小黄车"]','[aria-label*="商品"]','[title*="小黄车"]','[title*="商品"]',
                'a[href*="haohuo" i]','a[href*="jinritemai" i]','a[href*="product" i]','a[href*="goods" i]'
              ].join(',');
              const candidates = [];
              const seen = new Set();
              for (const scope of (root === document ? [document] : [root, document])) {
                for (const node of scope.querySelectorAll(selector)) {
                  if (seen.has(node)) continue;
                  seen.add(node);
                  candidates.push(node);
                }
              }
              for (const node of candidates) {
                if (!visible(node) || node.closest('[id^="brandbai-"]')) continue;
                const text = String(node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 180);
                const hints = [node.getAttribute('data-e2e'), node.getAttribute('class'), node.getAttribute('aria-label'), node.getAttribute('title')].filter(Boolean).join(' ');
                const structuredHints = hints.replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase();
                const link = node.matches('a[href]') ? node : node.closest('a[href]') || node.querySelector('a[href]');
                const rawHref = String(link?.getAttribute('href') || '').trim();
                const hasCommerceText = /小黄车|购物车|商品|去购买|立即购买|同款|购买|(?:^|\s)购物(?:$|\s|[|｜:：·•-])/.test(`${text} ${hints}`);
                const hasCommerceStructure = /(?:^|[\s_-])(?:goods?|product|commerce|shop|shopping|cart|ecom)(?:$|[\s_-])/.test(structuredHints);
                const hasCommerceLink = /haohuo|jinritemai|(?:^|[\/?#&=_-])(?:goods?|product|commerce|shopping|cart|ecom)(?:$|[\/?#&=_-])/i.test(rawHref);
                if (!hasCommerceText && !hasCommerceStructure && !hasCommerceLink) continue;
                let url = '';
                if (rawHref) {
                  try {
                    const parsed = new URL(rawHref, location.origin);
                    if (['http:', 'https:'].includes(parsed.protocol) && parsed.pathname !== '/' && parsed.href !== location.href && !/^\/(?:video|note|user|search|discover|channel|live)(?:\/|$)/.test(parsed.pathname)) url = parsed.href;
                  } catch (_error) {}
                }
                if (!text && !url) continue;
                const displayName = text.replace(/^(?:购物(?:车)?|小黄车|商品)(?:\s*[|｜:：·•-]+\s*|\s+)(?=\S)/, '').trim() || text || '页面可见小黄车';
                return {status: url ? 'visible_direct_link' : 'visible_name_only', display_name: displayName, url, observed_at: new Date().toISOString(), source: 'current_work_dom'};
              }
              return {status: 'not_observed', display_name: '', url: '', observed_at: new Date().toISOString(), source: 'current_work_dom'};
            }"""
        )
    except Exception:
        return None
    return normalize_commerce_anchor(observed)


def public_product_image_url(value: Any) -> str:
    """Accept only directly observed public image URLs, never signed credentials."""
    try:
        raw = str(value or "").strip()
        parsed = urllib.parse.urlsplit(raw)
        host = (parsed.hostname or "").lower()
        allowed = ("ecombdimg.com", "detailpage.byteimg.com")
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.port not in (None, 443)
                or not any(host == item or host.endswith("." + item) for item in allowed)):
            return ""
        # Do not retain tokens or assume stripping signatures leaves a usable URL.
        if any(re.search(r"token|sign|auth|credential|secret|cookie|session|expire|policy|key", key, re.I)
               for key, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)):
            return ""
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    except (ValueError, TypeError):
        return ""


def normalize_commerce_detail(value: Any, expected_aweme_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("status") != "detail_observed":
        raise WorkDownloadError("The current Douyin product panel did not yield a stable public product snapshot")
    source_work_id = str(value.get("source_work_id") or "")
    if source_work_id != str(expected_aweme_id):
        raise WorkDownloadError("The Douyin work changed while product details were being collected")
    products: list[dict[str, Any]] = []
    for product in value.get("products") or []:
        if not isinstance(product, dict):
            continue
        images = []
        for image in product.get("images") or []:
            if not isinstance(image, dict):
                continue
            raw_url = public_product_image_url(image.get("url"))
            if not raw_url:
                continue
            images.append({
                "url": raw_url,
                "width": as_int(image.get("width")),
                "height": as_int(image.get("height")),
                "order": len(images) + 1,
                "kind": "product_image",
            })
        products.append({
            "title": str(product.get("title") or product.get("short_title") or "")[:300],
            "short_title": str(product.get("short_title") or product.get("title") or "")[:180],
            "shop_name": str(product.get("shop_name") or "")[:100],
            "detail_url": "",
            "product_id": str(product.get("product_id") or "") if re.fullmatch(r"\d{6,30}", str(product.get("product_id") or "")) else "",
            "price_texts": [str(item)[:100] for item in product.get("price_texts") or []][:20],
            "sales_texts": [str(item)[:120] for item in product.get("sales_texts") or []][:20],
            "delivery_texts": [str(item)[:240] for item in product.get("delivery_texts") or []][:20],
            "service_texts": [str(item)[:240] for item in product.get("service_texts") or []][:40],
            "review_count_text": str(product.get("review_count_text") or "")[:100],
            "sku_groups": product.get("sku_groups") if isinstance(product.get("sku_groups"), list) else [],
            "parameters": product.get("parameters") if isinstance(product.get("parameters"), list) else [],
            "images": images,
            "observation_status": "detail_observed",
            "identity_status": "page_public_id" if re.fullmatch(r"\d{6,30}", str(product.get("product_id") or "")) else "visible_panel_only",
            "observed_at": str(product.get("observed_at") or value.get("observed_at") or ""),
        })
    if not products:
        raise WorkDownloadError("No public product detail was observed in the current Douyin product panel")
    return {
        "status": "detail_observed",
        "source": "explicit_current_product_panel",
        "source_work_id": source_work_id,
        "observed_at": str(value.get("observed_at") or utc_now()),
        "playback_paused": bool(value.get("playback_paused")),
        "products": products,
        "completeness": "partial_product_identity",
        "warnings": [
            "Only public fields rendered in the current product panel are retained.",
            "Hidden product IDs, commission, conversion and unrendered transaction facts are not inferred.",
        ],
    }


def collect_visible_commerce_detail(page: Any, expected_aweme_id: str, timeout_ms: int = 8_000) -> dict[str, Any]:
    """Freeze one work and read a product panel newly opened from its visible anchor."""
    script = Path(__file__).with_name("collect_product_detail.js").read_text(encoding="utf-8")
    observed = page.evaluate(
        script,
        {"expectedAwemeId": str(expected_aweme_id), "timeoutMs": int(timeout_ms)},
    )
    return normalize_commerce_detail(observed, str(expected_aweme_id))


def normalize_work(item: dict[str, Any]) -> dict[str, Any]:
    aweme_id = str(item.get("aweme_id") or item.get("awemeId") or "")
    if not aweme_id:
        raise WorkDownloadError("Creator work is missing aweme_id")
    statistics = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    music = item.get("music") if isinstance(item.get("music"), dict) else {}
    images = image_nodes(item)
    content_type = "图文" if images else "视频"
    content_route = "note" if images else "video"
    created = as_int(item.get("create_time") or item.get("createTime"))
    recommend_value = statistics.get("recommend_count")
    if recommend_value is None:
        recommend_value = statistics.get("recommendCount")
    account_id = str(
        author.get("unique_id") or author.get("uniqueId") or author.get("short_id") or author.get("shortId") or ""
    )
    stable_creator_id = str(author.get("sec_uid") or author.get("secUid") or author.get("uid") or "")
    creator_snapshot = {
        "nickname": str(author.get("nickname") or author.get("name") or ""),
        "platform_account": account_id,
        "stable_creator_id": stable_creator_id,
        "profile_url": f"https://www.douyin.com/user/{stable_creator_id}" if stable_creator_id else "",
        "bio": str(author.get("signature") or author.get("desc") or ""),
        "followers": optional_int(author.get("follower_count"), author.get("followerCount")),
        "total_likes": optional_int(author.get("total_favorited"), author.get("totalFavorited")),
        "snapshot_at": utc_now() if any((account_id, stable_creator_id, author.get("nickname"), author.get("name"))) else "",
        "source": "current_work_detail",
    }
    return {
        "aweme_id": aweme_id,
        "type": content_type,
        "author": str(author.get("nickname") or author.get("name") or ""),
        "title": str(item.get("desc") or item.get("description") or "").strip(),
        "create_time": created,
        "publish_time": datetime.fromtimestamp(created, CHINA_TIMEZONE).isoformat(timespec="seconds") if created else "",
        "digg_count": as_int(statistics.get("digg_count") or statistics.get("diggCount")),
        "share_count": as_int(statistics.get("share_count") or statistics.get("shareCount")),
        "comment_count": as_int(statistics.get("comment_count") or statistics.get("commentCount")),
        "collect_count": as_int(statistics.get("collect_count") or statistics.get("collectCount")),
        "recommend_count": None if recommend_value is None else as_int(recommend_value),
        "is_pinned": bool(item.get("is_top") or item.get("isTop")),
        "source_url": f"https://www.douyin.com/{content_route}/{aweme_id}",
        "cover_url": (cover_urls(item) or [""])[0],
        "music_title": str(music.get("title") or ""),
        "music_author": str(music.get("author") or ""),
        "music_unavailable_reason": str(music.get("offline_desc") or ""),
        "creator_snapshot": creator_snapshot,
        "_video_urls": video_urls(item),
        "_cover_urls": cover_urls(item),
        "_music_urls": music_urls(item),
        "_image_urls": [image_urls(node) for node in images],
    }


def select_pinned_and_recent(items: Iterable[dict[str, Any]], recent_n: int) -> list[dict[str, Any]]:
    normalized = [normalize_work(item) for item in items]
    pinned = sorted(
        (work for work in normalized if work["is_pinned"]),
        key=lambda work: (work["create_time"], work["aweme_id"]),
        reverse=True,
    )
    pinned_ids = {work["aweme_id"] for work in pinned}
    recent = sorted(
        (work for work in normalized if work["aweme_id"] not in pinned_ids),
        key=lambda work: (work["create_time"], work["aweme_id"]),
        reverse=True,
    )[:recent_n]
    for index, work in enumerate(pinned, 1):
        work["selection_reason"] = "置顶"
        work["selection_rank"] = index
    for index, work in enumerate(recent, 1):
        work["selection_reason"] = "最近"
        work["selection_rank"] = index
    return pinned + recent


def page_type(url: str) -> str:
    value = str(url or "").lower()
    if "/search/" in value or "search?" in value:
        return "search"
    if "/user/" in value:
        return "creator"
    if "/video/" in value or "/note/" in value:
        return "work"
    return "page"


def search_keyword(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url or ""))
    query = urllib.parse.parse_qs(parsed.query)
    for key in ("keyword", "query", "q"):
        if query.get(key):
            return str(query[key][0])
    match = re.search(r"/search/([^/?#]+)", parsed.path)
    return urllib.parse.unquote(match.group(1)) if match else ""


def select_visible(
    items: Iterable[dict[str, Any]],
    *,
    selected_ids: Iterable[str] = (),
    limit: int = 0,
    reason: str = "当前页面",
) -> tuple[list[dict[str, Any]], list[str]]:
    normalized = [normalize_work(item) for item in items]
    by_id = {work["aweme_id"]: work for work in normalized}
    requested = [str(value or "").strip() for value in selected_ids if str(value or "").strip()]
    missing: list[str] = []
    if requested:
        selected = []
        for aweme_id in requested:
            if aweme_id in by_id:
                selected.append(by_id[aweme_id])
            else:
                missing.append(aweme_id)
    else:
        selected = normalized
        if limit > 0:
            selected = selected[:limit]
    for index, work in enumerate(selected, 1):
        work["selection_reason"] = reason
        work["selection_rank"] = index
    return selected, missing


def merge_seed_with_observed(seed: dict[str, Any], observed: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(observed or seed)
    for key, value in seed.items():
        if key.startswith("_"):
            if value and not merged.get(key):
                merged[key] = value
            continue
        if value not in (None, "", 0, False) or key in {
            "source_url", "selection_reason", "selection_rank", "source_page_type",
            "source_keyword", "source_rank",
        }:
            if merged.get(key) in (None, "", 0, False) or key.startswith(("source_", "selection_")):
                merged[key] = value
    merged["aweme_id"] = seed["aweme_id"]
    merged["source_url"] = seed["source_url"]
    merged["selection_reason"] = seed.get("selection_reason") or "手动选择"
    merged["selection_rank"] = seed.get("selection_rank") or 1
    for key in ("_video_urls", "_cover_urls", "_music_urls", "_image_urls"):
        merged.setdefault(key, [])
    return merged


def parse_assets(value: str) -> set[str]:
    text = str(value or "").strip().lower()
    if text in {"", "all"}:
        return set(ASSET_KINDS)
    if text in {"none", "data", "metadata"}:
        return set()
    aliases = {"video": "primary", "image": "primary", "music": "audio", "text": "caption"}
    selected = {aliases.get(part.strip(), part.strip()) for part in text.split(",") if part.strip()}
    invalid = selected - ASSET_KINDS
    if invalid:
        raise WorkDownloadError(f"Unsupported --assets values: {', '.join(sorted(invalid))}")
    return selected


def work_file_base(work: dict[str, Any], index: int) -> str:
    publish = str(work.get("publish_time") or "")[:10].replace("-", "") or "日期未知"
    author = sanitize_name(work.get("author"), "作者未知", 24)
    title = sanitize_name(work.get("title"), "未命名作品", 46)
    return sanitize_name(
        f"{index:03d}_{publish}_{author}_{title}_{work['aweme_id']}",
        max_length=128,
    )


def write_caption(folder: Path, work: dict[str, Any]) -> dict[str, Any]:
    title = str(work.get("title") or "").strip()
    if not title:
        return {"status": "not_available", "file": "", "bytes": 0}
    target = folder / "发布文案.txt"
    if target.is_file() and target.stat().st_size > 0:
        return {"status": "skipped_existing", "file": target.name, "bytes": target.stat().st_size}
    lines = [title]
    anchor = normalize_commerce_anchor(work.get("commerce_anchor"))
    if anchor:
        status_labels = {
            "visible_direct_link": "页面可见，已留存直接链接",
            "visible_name_only": "页面可见，页面未直接提供链接",
            "not_observed": "本次单作品页未观察到公开可见小黄车",
        }
        lines.extend(["", f"小黄车观察状态：{status_labels.get(anchor['status'], anchor['status'])}"])
        if anchor.get("display_name"):
            lines.append(f"小黄车展示名：{anchor['display_name']}")
        if anchor.get("url"):
            lines.append(f"小黄车页面直接链接：{anchor['url']}")
        if anchor.get("observed_at"):
            lines.append(f"小黄车观察时间：{anchor['observed_at']}")
        commerce = work.get("commerce") if isinstance(work.get("commerce"), dict) else {}
        if commerce.get("status") == "detail_observed":
            lines.append(f"商品资料状态：已读取当前商品卡公开资料（{len(commerce.get('products') or [])} 个页面商品记录）")
            lines.append("商品资料边界：明确请求后冻结当前作品并暂停播放，从该作品打开的公开商品卡读取；隐藏商品ID、佣金、成交和未展示事实不推断。")
        else:
            lines.append("小黄车采集边界：仅记录当前单作品页公开可见的展示名和页面直接链接；未点击商品、未进入详情，未推断价格、店铺、销量、佣金或隐藏商品ID。")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"status": "created", "file": target.name, "bytes": target.stat().st_size}


def discovery_scroll_budget(recent_n: int, requested_scrolls: int) -> int:
    """Return a bounded discovery budget that grows with the requested sample."""
    adaptive = max(5, max(0, recent_n) * 2)
    return max(1, requested_scrolls, min(120, adaptive))


def final_works_status(has_download_errors: bool, recent_selected: int, recent_requested: int) -> str:
    selection_shortfall = recent_selected < recent_requested
    if selection_shortfall and has_download_errors:
        return "partial_selection_and_download_errors"
    if selection_shortfall:
        return "partial_selection_shortfall"
    if has_download_errors:
        return "partial_download_errors"
    return "complete"


def public_work_record(work: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in work.items() if not key.startswith("_")}


def signature_kind(header: bytes) -> str:
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    if len(header) >= 8 and header[4:8] == b"ftyp":
        return "mp4"
    if header.startswith(b"ID3") or header.startswith((b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
        return "mp3"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return "unknown"


def file_signature_kind(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            header = handle.read(12)
    except OSError:
        return "unknown"
    return signature_kind(header)


def normalize_audio_target(target: Path) -> Path:
    if target.suffix.lower() == ".mp3" and file_signature_kind(target) == "mp4":
        corrected = target.with_suffix(".m4a")
        if corrected.exists() and corrected.stat().st_size > 0:
            target.unlink(missing_ok=True)
        else:
            target.replace(corrected)
        return corrected
    return target


def download_from_candidates(
    candidates: Iterable[str],
    target: Path,
    referer: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    if target.suffix.lower() == ".mp3":
        alternate = target.with_suffix(".m4a")
        if alternate.is_file() and alternate.stat().st_size > 0:
            return {"status": "skipped_existing", "file": alternate.name, "bytes": alternate.stat().st_size}
    if target.is_file() and target.stat().st_size > 0:
        normalized_target = normalize_audio_target(target)
        return {"status": "skipped_existing", "file": normalized_target.name, "bytes": normalized_target.stat().st_size}
    normalized_candidates = unique_urls(candidates)
    if not normalized_candidates:
        return {"status": "not_available", "file": "", "bytes": 0}
    target.parent.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    partial = target.with_suffix(target.suffix + ".part")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        ),
        "Referer": referer,
        "Accept": "*/*",
    }
    for candidate in normalized_candidates:
        try:
            request = urllib.request.Request(candidate, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                with partial.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
            size = partial.stat().st_size if partial.exists() else 0
            if size <= 0:
                raise WorkDownloadError("empty response body")
            partial.replace(target)
            target = normalize_audio_target(target)
            return {
                "status": "downloaded",
                "file": target.name,
                "bytes": size,
                "host": urllib.parse.urlparse(candidate).netloc,
            }
        except Exception as exc:  # noqa: BLE001 - preserve bounded candidate failures
            failures.append(f"{type(exc).__name__}: {exc}")
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
    return {
        "status": "failed",
        "file": target.name,
        "bytes": 0,
        "errors": failures[-3:],
    }


def download_product_image(
    candidates: Iterable[str], target_base: Path, referer: str, timeout_seconds: float
) -> dict[str, Any]:
    accepted_kinds = {"jpeg": ".jpg", "webp": ".webp", "png": ".png"}
    for suffix in (".jpg", ".webp", ".png"):
        existing = target_base.with_suffix(suffix)
        if existing.is_file() and existing.stat().st_size > 0:
            kind = file_signature_kind(existing)
            if kind not in accepted_kinds:
                return {"status": "failed", "file": "", "bytes": 0,
                        "errors": ["existing_product_image_has_invalid_signature"]}
            corrected = target_base.with_suffix(accepted_kinds[kind])
            if corrected != existing:
                if corrected.exists():
                    return {"status": "failed", "file": "", "bytes": 0,
                            "errors": ["conflicting_existing_product_image"]}
                existing.replace(corrected)
            return {"status": "skipped_existing", "file": corrected.name, "bytes": corrected.stat().st_size,
                    "content_kind": kind}
    public_candidates = [url for item in candidates if (url := public_product_image_url(item))]
    if not public_candidates:
        return {"status": "not_available", "file": "", "bytes": 0,
                "reason": "no_public_unsigned_product_image"}
    result = download_from_candidates(public_candidates, target_base.with_suffix(".jpg"), referer, timeout_seconds)
    if result.get("status") not in {"downloaded", "skipped_existing"}:
        return result
    current = target_base.parent / str(result.get("file") or target_base.with_suffix(".jpg").name)
    kind = file_signature_kind(current)
    desired_suffix = accepted_kinds.get(kind)
    if not desired_suffix:
        if result.get("status") == "downloaded":
            current.unlink(missing_ok=True)  # Only the invalid response this call just created.
        return {"status": "failed", "file": "", "bytes": 0,
                "errors": ["product_image_response_is_not_a_supported_image"]}
    if desired_suffix and current.suffix.lower() != desired_suffix:
        corrected = target_base.with_suffix(desired_suffix)
        current.replace(corrected)
        result["file"] = corrected.name
    result["content_kind"] = kind
    return result


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download selected public Douyin works through visible signed-in Chrome."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--creator", help="Douyin creator profile URL")
    source.add_argument("--source-page", help="Douyin creator or search result page URL")
    source.add_argument("--selection-file", help="BrandBAI selection JSON or plugin works Excel")
    source.add_argument("--video", action="append", help="Explicit video/note URL; repeat for multiple works")
    parser.add_argument("--recent", type=int, default=5, help="Recent non-pinned works to add")
    parser.add_argument("--limit", type=int, default=0, help="Maximum works from a generic/search page; 0 keeps all observed")
    parser.add_argument("--selected-id", action="append", default=[], help="Explicit work ID to keep from --source-page")
    parser.add_argument(
        "--assets",
        default="primary,cover,audio,caption",
        help="Comma list: primary,cover,audio,caption; use none for metadata only",
    )
    parser.add_argument(
        "--commerce-detail",
        action="store_true",
        help="For exactly one explicit work: pause playback, open its visible product card and collect/download public product details",
    )
    parser.add_argument("--profile-dir", required=True, help="Persistent Chrome profile outside output")
    parser.add_argument("--out", required=True, help="New or resumable output directory")
    parser.add_argument(
        "--media-dir",
        default="",
        help="Optional media directory; defaults to <out>/media",
    )
    parser.add_argument(
        "--media-label",
        default="",
        help="Relative folder label written into works.json when --media-dir is external",
    )
    parser.add_argument("--chrome-path", default="")
    parser.add_argument(
        "--scrolls",
        type=int,
        default=5,
        help="Minimum discovery scroll rounds; automatically expands with --recent",
    )
    parser.add_argument("--login-wait", type=float, default=30.0)
    parser.add_argument("--download-timeout", type=float, default=180.0)
    parser.add_argument("--zip", action="store_true", help="Create a sibling ZIP after the works task finishes")
    parser.add_argument("--zip-path", default="", help="Optional ZIP path; must be outside --out")
    parser.add_argument("--dry-run", action="store_true")
    add_product_review_args(parser)
    parser.add_argument("--privacy-mode", choices=("hash", "raw"), default="hash")
    parser.add_argument("--resume", action="store_true", help="Reuse matching work assets and retry the product-review checkpoint")
    return parser.parse_args(argv)


def add_product_review_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--product-reviews", action="store_true", help="Explicit single work only: collect its current product evaluations separately; implies --commerce-detail")
    parser.add_argument("--max-product-reviews", type=int, default=200, help="Positive saved-review sample limit; not a full-history promise")
    parser.add_argument("--product-review-max-scrolls", type=int, default=200)
    parser.add_argument("--product-review-max-seconds", type=float, default=600.0)


def validate_product_review_args(args: argparse.Namespace) -> None:
    if not getattr(args, "product_reviews", False):
        return
    args.commerce_detail = True
    if input_mode(args) not in {"explicit_works", "selection_file"}:
        raise WorkDownloadError("--product-reviews requires exactly one explicitly selected work")
    seeds, _ = selection_seeds(args)
    if len(seeds) != 1:
        raise WorkDownloadError("--product-reviews requires exactly one explicitly selected work")
    if any(not isinstance(value, (int, float)) or not 0 < value < float("inf") for value in (
        getattr(args, "max_product_reviews", 200), getattr(args, "product_review_max_scrolls", 200),
        getattr(args, "product_review_max_seconds", 600.0),
    )):
        raise WorkDownloadError("Product-review sample, scroll and time budgets must be finite and positive")


def product_review_output_dir(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "product_reviews_out", "") or Path(args.out) / "商品评价").expanduser().resolve()


def product_review_identity(args: argparse.Namespace) -> dict[str, Any]:
    return {"requested": True, "privacy_mode": getattr(args, "privacy_mode", "hash")}


def run_product_reviews_on_page(page: Any, args: argparse.Namespace, work: dict[str, Any], product: dict[str, Any]) -> int:
    """Run one independent evaluation collector before leaving the owned product page.

    Failures are stage-local: never erase an already downloaded work or an old
    evaluation checkpoint. The caller's final status still records partial.
    """
    out_dir = product_review_output_dir(args)
    code = 3
    failure = ""
    try:
        from browser_collect_product_reviews import collect_product_reviews
        code = int(collect_product_reviews(page, str(work["aweme_id"]), product, out_dir,
            max_reviews=getattr(args, "max_product_reviews", 200),
            max_scrolls=getattr(args, "product_review_max_scrolls", 200),
            max_seconds=getattr(args, "product_review_max_seconds", 600.0),
            privacy_mode=getattr(args, "privacy_mode", "hash"), resume=bool(getattr(args, "resume", False))))
    except Exception as exc:
        # No exception string from a browser is copied into a public deliverable.
        failure = type(exc).__name__
    summary: dict[str, Any] = {"requested": True, "status": "partial", "exit_code": 3,
        "source_work_id": str(work["aweme_id"]), "privacy_mode": getattr(args, "privacy_mode", "hash"),
        "done_reason": "product_review_error" if failure else "end_not_confirmed", "error_type": failure}
    manifest_path = out_dir / "product_review_manifest.json"
    if manifest_path.is_file():
        try:
            saved = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            if str(saved.get("source_work_id")) == str(work["aweme_id"]) and saved.get("privacy_mode") == summary["privacy_mode"]:
                for key in ("status", "completeness", "done_reason", "review_count"):
                    summary[key] = saved.get(key)
                if failure:
                    summary.update(status="partial", completeness="partial_current_attempt", done_reason="product_review_error")
                elif code == 0 and saved.get("status") == "complete" and saved.get("completeness") == "complete_visible_panel_exhausted":
                    summary["exit_code"] = 0
        except (OSError, ValueError, AttributeError):
            pass
    # Pause means stop this workflow too: never navigate after a user's pause.
    safe_end = summary["exit_code"] == 0 or summary.get("done_reason") in {
        "run_budget",
    }
    summary["work_comments_safe"] = bool(safe_end and not failure)
    if summary["work_comments_safe"]:
        try:
            route = "note" if work.get("type") in {"图文", "note"} else "video"
            page.goto(f"https://www.douyin.com/{route}/{work['aweme_id']}", wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            summary.update(status="partial", exit_code=3, done_reason="work_surface_restore_failed", work_comments_safe=False)
    args._product_review_summary = summary
    args._product_review_exit_code = summary["exit_code"]
    print(json.dumps({"event": "product_reviews_stage_end", **summary}, ensure_ascii=False))
    return int(summary["exit_code"])


def completed_product_review_summary(args: argparse.Namespace, work: dict[str, Any]) -> dict[str, Any] | None:
    """Reuse only an identity/count-checked finished checkpoint, without a new panel."""
    out_dir = product_review_output_dir(args)
    path = out_dir / "product_review_manifest.json"
    if not path.is_file():
        return None
    saved = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(saved, dict) or saved.get("status") != "complete":
        return None
    from browser_collect_product_reviews import safe_product
    frozen_products = (work.get("commerce") or {}).get("products") or []
    if (saved.get("source_work_id") != str(work["aweme_id"])
        or saved.get("privacy_mode") != getattr(args, "privacy_mode", "hash")
        or saved.get("completeness") != "complete_visible_panel_exhausted"
        or saved.get("done_reason") != "source_exhausted"
        or len(frozen_products) != 1 or safe_product(frozen_products[0]) != saved.get("product")):
        raise WorkDownloadError("Completed product-review checkpoint does not match the frozen work/product/privacy request")
    rows_path = out_dir / "product_reviews.jsonl"
    if not rows_path.is_file():
        raise WorkDownloadError("Completed product-review checkpoint is missing its saved rows")
    seen: set[str] = set()
    for line in rows_path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if (not isinstance(row, dict) or not isinstance(row.get("review_id"), str) or not row["review_id"]
            or row["review_id"] in seen or row.get("source_work_id") != str(work["aweme_id"])
            or row.get("product_id") != saved["product"]["product_id"]):
            raise WorkDownloadError("Completed product-review checkpoint has mismatching or duplicate rows")
        seen.add(row["review_id"])
    if type(saved.get("review_count")) is not int or saved["review_count"] != len(seen):
        raise WorkDownloadError("Completed product-review saved count does not match its rows")
    return {"requested": True, "status": "complete", "completeness": saved["completeness"],
        "done_reason": "source_exhausted", "exit_code": 0, "review_count": len(seen),
        "source_work_id": str(work["aweme_id"]), "privacy_mode": saved["privacy_mode"],
        "work_comments_safe": True, "reused_complete": True}


def resume_product_review_stage(context: Any, args: argparse.Namespace) -> int:
    """Reuse complete work files, but never skip a requested partial review stage."""
    out_dir = Path(args.out).expanduser().resolve()
    manifest_path = out_dir / "download_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("status") != "complete" or manifest.get("input_identity") != input_identity(args):
        raise WorkDownloadError("--resume requires matching complete work assets and the same product-review/privacy request")
    payload = json.loads((out_dir / "works.json").read_text(encoding="utf-8-sig"))
    works = payload.get("works") if isinstance(payload, dict) else payload
    if not isinstance(works, list) or len(works) != 1:
        raise WorkDownloadError("Product-review resume requires one frozen source work")
    work = works[0]
    seeds, _ = selection_seeds(args)
    if len(seeds) != 1 or str(work.get("aweme_id")) != str(seeds[0]["aweme_id"]):
        raise WorkDownloadError("The resume work identity differs from the saved work")
    page = context.pages[0] if context.pages else context.new_page()
    try:
        complete = completed_product_review_summary(args, work)
        if complete:
            route = "note" if work.get("type") in {"图文", "note"} else "video"
            page.goto(f"https://www.douyin.com/{route}/{work['aweme_id']}", wait_until="domcontentloaded", timeout=60_000)
            args._product_review_summary = complete
            args._product_review_exit_code = 0
            manifest["product_reviews"] = complete
            write_json(manifest_path, manifest)
            return 0
        page.goto(seeds[0]["source_url"], wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(max(1_500, int(args.login_wait * 1000)))
        detail = collect_visible_commerce_detail(page, str(work["aweme_id"]))
        code = run_product_reviews_on_page(page, args, work, detail["products"][0])
    except Exception as exc:
        args._product_review_summary = {"requested": True, "status": "partial", "exit_code": 3,
            "source_work_id": str(work["aweme_id"]), "privacy_mode": getattr(args, "privacy_mode", "hash"),
            "done_reason": "product_review_resume_rejected", "error_type": type(exc).__name__, "work_comments_safe": False}
        args._product_review_exit_code = code = 3
    manifest["product_reviews"] = args._product_review_summary
    write_json(manifest_path, manifest)
    return code


def input_mode(args: argparse.Namespace) -> str:
    if getattr(args, "selection_file", ""):
        return "selection_file"
    if getattr(args, "video", None):
        return "explicit_works"
    if getattr(args, "source_page", ""):
        return "visible_page"
    return "creator_pinned_recent"


def source_page_url(args: argparse.Namespace) -> str:
    return str(getattr(args, "creator", "") or getattr(args, "source_page", "") or "").strip()


def selection_description(args: argparse.Namespace) -> str:
    mode = input_mode(args)
    if mode == "creator_pinned_recent":
        return f"all visible pinned works plus latest {args.recent} non-pinned works"
    if mode == "visible_page":
        if getattr(args, "selected_id", []):
            return f"{len(args.selected_id)} selected work IDs from the visible page"
        return f"up to {args.limit} observed works" if args.limit > 0 else "all observed works from the visible page"
    if mode == "selection_file":
        return "works listed in the BrandBAI selection file"
    return f"{len(args.video or [])} explicit work URLs"


def input_identity(args: argparse.Namespace) -> dict[str, Any]:
    selection_file = str(getattr(args, "selection_file", "") or "")
    selection_identity: dict[str, str] | str = ""
    if selection_file:
        path = Path(selection_file).expanduser().resolve()
        selection_identity = {
            "name": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing",
        }
    return {
        "mode": input_mode(args),
        "creator": str(getattr(args, "creator", "") or ""),
        "source_page": str(getattr(args, "source_page", "") or ""),
        "selection_file": selection_identity,
        "videos": [str(value) for value in getattr(args, "video", []) or []],
        "recent": int(getattr(args, "recent", 0) or 0),
        "limit": int(getattr(args, "limit", 0) or 0),
        "selected_ids": [str(value) for value in getattr(args, "selected_id", []) or []],
        "assets": str(getattr(args, "assets", "")),
        "commerce_detail": bool(getattr(args, "commerce_detail", False)),
        **({"product_reviews": product_review_identity(args)} if getattr(args, "product_reviews", False) else {}),
    }


def resolve_zip_path(args: argparse.Namespace) -> Path:
    return (
        Path(args.zip_path).expanduser().resolve()
        if getattr(args, "zip_path", "")
        else Path(args.out).expanduser().resolve().with_suffix(".zip")
    )


def dry_plan(args: argparse.Namespace) -> dict[str, Any]:
    source_value = args.creator or args.source_page or args.selection_file or list(args.video or [])
    return {
        "provider": PROVIDER,
        "source": source_value,
        "selection_mode": input_mode(args),
        "selection": selection_description(args),
        "recent_non_pinned": args.recent,
        "assets": sorted(parse_assets(args.assets)),
        "commerce_detail": bool(getattr(args, "commerce_detail", False)),
        "product_reviews": ({**product_review_identity(args), "max_reviews": args.max_product_reviews,
            "max_scrolls": args.product_review_max_scrolls, "max_seconds": args.product_review_max_seconds,
            "resume": bool(getattr(args, "resume", False)), "control_file": "商品评价/product_review_control.json"}
            if getattr(args, "product_reviews", False) else "not requested"),
        "browser": "one visible persistent Chrome context",
        "cookies_exported": False,
        "signature_generation": False,
        "output": str(Path(args.out).resolve()),
        "media_output": str(
            Path(args.media_dir).expanduser().resolve()
            if args.media_dir
            else Path(args.out).resolve() / "media"
        ),
        "zip_output": str(resolve_zip_path(args)) if args.zip else "",
    }


def collect_visible_works(context: Any, args: argparse.Namespace) -> tuple[list[dict[str, Any]], int, int]:
    raw_items: dict[str, dict[str, Any]] = {}
    response_count = 0
    page = context.pages[0] if context.pages else context.new_page()
    page.set_default_timeout(60_000)
    target_url = source_page_url(args)
    target_type = page_type(target_url)
    target_count = max(
        1,
        int(getattr(args, "limit", 0) or 0),
        int(getattr(args, "recent", 0) or 0),
        len(getattr(args, "selected_id", []) or []),
    )

    def on_response(response: Any) -> None:
        nonlocal response_count
        url = str(response.url or "").lower()
        if not any(token in url for token in RESPONSE_TOKENS):
            return
        try:
            if response.status != 200:
                return
            posts = pick_posts(response.json())
            if posts:
                response_count += 1
            for item in posts:
                aweme_id = str(item.get("aweme_id") or item.get("awemeId") or "")
                if aweme_id:
                    raw_items[aweme_id] = item
        except Exception:
            return

    page.on("response", on_response)
    page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(max(1_500, int(args.login_wait * 1000)))

    # A login or verification completed during the wait may not replay the first
    # creator response. Reload once when the observed first page cannot satisfy N.
    if len(raw_items) < target_count:
        page.reload(wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1_500)

    idle = 0
    for _ in range(discovery_scroll_budget(target_count, args.scrolls)):
        before = len(raw_items)
        page.mouse.wheel(0, 1_800)
        page.wait_for_timeout(1_200)
        idle = idle + 1 if len(raw_items) == before else 0
        if idle >= 2 and len(raw_items) >= target_count:
            break
    page.wait_for_timeout(1_500)
    if target_type == "search":
        for aweme_id in search_dom_work_ids(page):
            raw_items.setdefault(
                aweme_id,
                {"aweme_id": aweme_id, "__brandbai_dom_seed": True},
            )
    visible_candidate_ids = list(raw_items)
    if input_mode(args) == "creator_pinned_recent":
        selected = select_pinned_and_recent(raw_items.values(), args.recent)
        missing_ids: list[str] = []
    else:
        reason = "搜索结果" if target_type == "search" else "页面选择"
        selected, missing_ids = select_visible(
            raw_items.values(),
            selected_ids=getattr(args, "selected_id", []) or [],
            limit=int(getattr(args, "limit", 0) or 0),
            reason=reason,
        )
    # Search cards expose stable work IDs but not always the full JSON payload.
    # Enrich only the selected cards through their ordinary visible detail page.
    if target_type == "search":
        selected_ids = [work["aweme_id"] for work in selected]
        for aweme_id in selected_ids:
            item = raw_items.get(aweme_id, {})
            if not item.get("__brandbai_dom_seed"):
                continue
            page.goto(
                f"https://www.douyin.com/video/{aweme_id}",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            page.wait_for_timeout(1_500)
        candidates = [raw_items[aweme_id] for aweme_id in visible_candidate_ids if aweme_id in raw_items]
        selected, missing_ids = select_visible(
            candidates,
            selected_ids=getattr(args, "selected_id", []) or [],
            limit=int(getattr(args, "limit", 0) or 0),
            reason="搜索结果",
        )
        missing_metadata = []
        for work in selected:
            observed = not bool(raw_items[work["aweme_id"]].get("__brandbai_dom_seed"))
            work["_metadata_observed"] = observed
            if not observed:
                missing_metadata.append(work["aweme_id"])
        args._missing_metadata_ids = missing_metadata
    keyword = search_keyword(target_url) if target_type == "search" else ""
    for index, work in enumerate(selected, 1):
        work["source_page_type"] = target_type
        work["source_keyword"] = keyword
        work["source_rank"] = index
    args._missing_selected_ids = missing_ids
    try:
        page.remove_listener("response", on_response)
    except Exception:
        pass
    return selected, response_count, len(visible_candidate_ids)


def selection_seeds(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if getattr(args, "selection_file", ""):
        try:
            return load_selection(args.selection_file)
        except SelectionContractError as exc:
            raise WorkDownloadError(str(exc)) from exc
    seeds: list[dict[str, Any]] = []
    for index, url in enumerate(getattr(args, "video", []) or [], 1):
        try:
            seeds.append(seed_from_url(url, index))
        except SelectionContractError as exc:
            raise WorkDownloadError(str(exc)) from exc
    seeds = deduplicate_seeds(seeds)
    if not seeds:
        raise WorkDownloadError("No usable explicit works were provided")
    return seeds, {
        "contract": "brandbai.douyin.selection/v1",
        "page_type": "explicit",
        "selection_mode": "explicit_urls",
        "selection_reason": "明确作品",
        "download": {},
    }


def collect_seeded_works(context: Any, args: argparse.Namespace) -> tuple[list[dict[str, Any]], int, int]:
    seeds, metadata = selection_seeds(args)
    if getattr(args, "commerce_detail", False) and len(seeds) != 1:
        raise WorkDownloadError("--commerce-detail requires exactly one explicit selected work")
    requested_assets = parse_assets(getattr(args, "assets", "all"))
    observed: dict[str, dict[str, Any]] = {}
    response_count = 0
    page = context.pages[0] if context.pages else context.new_page()
    page.set_default_timeout(60_000)
    single_commerce_anchor: dict[str, Any] | None = None
    single_commerce_detail: dict[str, Any] | None = None

    def on_response(response: Any) -> None:
        nonlocal response_count
        url = str(response.url or "").lower()
        if not any(token in url for token in RESPONSE_TOKENS):
            return
        try:
            if response.status != 200:
                return
            posts = pick_posts(response.json())
            if posts:
                response_count += 1
            for item in posts:
                aweme_id = str(item.get("aweme_id") or item.get("awemeId") or "")
                if aweme_id:
                    observed[aweme_id] = item
        except Exception:
            return

    page.on("response", on_response)
    try:
        navigated = 0
        for seed in seeds:
            primary_ready = bool(seed.get("_image_urls")) if seed.get("type") == "图文" else bool(seed.get("_video_urls"))
            metadata_ready = bool(
                seed.get("author")
                and seed.get("title")
                and (seed.get("publish_time") or seed.get("create_time"))
            )
            needs_enrichment = (
                not metadata_ready
                or ("primary" in requested_assets and not primary_ready)
                or ("cover" in requested_assets and not seed.get("_cover_urls"))
                or ("audio" in requested_assets and not seed.get("_music_urls"))
                or len(seeds) == 1
            )
            if not needs_enrichment:
                continue
            page.goto(seed["source_url"], wait_until="domcontentloaded", timeout=60_000)
            wait_ms = max(1_500, int(args.login_wait * 1000)) if navigated == 0 else 1_500
            page.wait_for_timeout(wait_ms)
            if len(seeds) == 1:
                single_commerce_anchor = collect_visible_commerce_anchor(page)
                if getattr(args, "commerce_detail", False):
                    try:
                        single_commerce_detail = collect_visible_commerce_detail(page, seed["aweme_id"])
                        if getattr(args, "product_reviews", False):
                            run_product_reviews_on_page(page, args, seed, single_commerce_detail["products"][0])
                    except Exception as exc:
                        if not getattr(args, "product_reviews", False):
                            raise
                        args._product_review_exit_code = 3
                        args._product_review_summary = {"requested": True, "status": "partial", "exit_code": 3,
                            "source_work_id": seed["aweme_id"], "privacy_mode": getattr(args, "privacy_mode", "hash"),
                            "done_reason": "product_detail_unavailable", "error_type": type(exc).__name__, "work_comments_safe": False}
            navigated += 1
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    selected: list[dict[str, Any]] = []
    missing_metadata: list[str] = []
    for seed in seeds:
        raw = observed.get(seed["aweme_id"])
        rich = normalize_work(raw) if raw else None
        metadata_ready = bool(
            seed.get("author")
            and seed.get("title")
            and (seed.get("publish_time") or seed.get("create_time"))
        )
        primary_ready = bool(seed.get("_image_urls")) if seed.get("type") == "图文" else bool(seed.get("_video_urls"))
        requested_ready = all((
            kind == "caption"
            or kind == "primary" and primary_ready
            or kind == "cover" and bool(seed.get("_cover_urls"))
            or kind == "audio" and bool(seed.get("_music_urls"))
        ) for kind in requested_assets)
        if rich is None and not (requested_ready and metadata_ready):
            missing_metadata.append(seed["aweme_id"])
        merged = merge_seed_with_observed(seed, rich)
        if len(seeds) == 1 and single_commerce_anchor:
            merged["commerce_anchor"] = single_commerce_anchor
        if len(seeds) == 1 and single_commerce_detail:
            merged["commerce"] = single_commerce_detail
        merged["_metadata_observed"] = raw is not None or metadata_ready
        selected.append(merged)
    args._missing_selected_ids = []
    args._missing_metadata_ids = missing_metadata
    args._selection_metadata = metadata
    return selected, response_count, len(observed)


def run(args: argparse.Namespace, browser_context: Any = None) -> int:
    validate_product_review_args(args)
    if args.recent < 0:
        raise WorkDownloadError("--recent cannot be negative")
    if args.scrolls < 1:
        raise WorkDownloadError("--scrolls must be positive")
    if int(getattr(args, "limit", 0) or 0) < 0:
        raise WorkDownloadError("--limit cannot be negative")
    if getattr(args, "commerce_detail", False) and input_mode(args) not in {"selection_file", "explicit_works"}:
        raise WorkDownloadError("--commerce-detail is limited to exactly one explicit selected work")
    requested_assets = parse_assets(getattr(args, "assets", "all"))
    if args.dry_run:
        print(json.dumps(dry_plan(args), ensure_ascii=False, indent=2))
        return 0

    out_dir = Path(args.out).resolve()
    profile_dir = Path(args.profile_dir).expanduser().resolve()
    media_dir = (
        Path(args.media_dir).expanduser().resolve()
        if args.media_dir
        else out_dir / "media"
    )
    targets = [out_dir, media_dir]
    if getattr(args, "product_reviews", False):
        targets.append(product_review_output_dir(args))
    for target in targets:
        if target == profile_dir or target in profile_dir.parents or profile_dir in target.parents:
            raise WorkDownloadError("Keep --profile-dir and all outputs in separate directory trees")
    out_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)
    media_label = Path(args.media_label.strip()) if args.media_label.strip() else (
        Path(media_dir.name) if args.media_dir else Path("media")
    )
    manifest_path = out_dir / "download_manifest.json"
    works_path = out_dir / "works.json"
    if getattr(args, "product_reviews", False) and not getattr(args, "resume", False) and (manifest_path.exists() or works_path.exists()):
        raise WorkDownloadError("Product-review output already exists; use matching --resume or a new output directory")
    if getattr(args, "resume", False):
        if not getattr(args, "product_reviews", False):
            raise WorkDownloadError("Standalone --resume requires --product-reviews; use all --resume for work comments")
        if browser_context is not None:
            return resume_product_review_stage(browser_context, args)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(user_data_dir=str(profile_dir),
                executable_path=find_chrome_path(args.chrome_path), headless=False, accept_downloads=False,
                viewport=None, args=["--start-maximized", "--no-first-run", "--no-default-browser-check"])
            try:
                return resume_product_review_stage(context, args)
            finally:
                context.close()
    manifest: dict[str, Any] = {
        "provider": PROVIDER,
        "status": "running",
        "started_at": utc_now(),
        "creator": str(getattr(args, "creator", "") or ""),
        "source_page": source_page_url(args),
        "selection_file": Path(args.selection_file).name if getattr(args, "selection_file", "") else "",
        "selection": input_mode(args),
        "selection_description": selection_description(args),
        "requested_recent_non_pinned": args.recent,
        "requested_limit": int(getattr(args, "limit", 0) or 0),
        "requested_work_ids": list(getattr(args, "selected_id", []) or []),
        "requested_assets": sorted(requested_assets),
        "commerce_detail_requested": bool(getattr(args, "commerce_detail", False)),
        "input_identity": input_identity(args),
        "zip_requested": bool(getattr(args, "zip", False)),
        "cookies_exported": False,
        "signature_generation": False,
        "warnings": [],
        "works": [],
    }
    write_json(manifest_path, manifest)
    if browser_context is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise WorkDownloadError("Playwright is required for the browser route") from exc
        chrome_path = find_chrome_path(args.chrome_path)
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                executable_path=chrome_path,
                headless=False,
                accept_downloads=False,
                viewport=None,
                args=["--start-maximized", "--no-first-run", "--no-default-browser-check"],
            )
            try:
                collector = collect_seeded_works if input_mode(args) in {"selection_file", "explicit_works"} else collect_visible_works
                selected, response_count, visible_work_count = collector(context, args)
            finally:
                context.close()
    else:
        collector = collect_seeded_works if input_mode(args) in {"selection_file", "explicit_works"} else collect_visible_works
        selected, response_count, visible_work_count = collector(browser_context, args)

    manifest["browser_context_mode"] = (
        "shared_all_context" if browser_context is not None else "standalone_context"
    )
    manifest["browser_launches_total"] = 1
    manifest["browser_launches_owned"] = 0 if browser_context is not None else 1

    if input_mode(args) == "creator_pinned_recent" and len([work for work in selected if work["selection_reason"] == "最近"]) < args.recent:
        manifest["warnings"].append(
            f"Only {len([work for work in selected if work['selection_reason'] == '最近'])}/"
            f"{args.recent} recent non-pinned works were visible"
        )
    missing_selected_ids = list(getattr(args, "_missing_selected_ids", []) or [])
    missing_metadata_ids = list(getattr(args, "_missing_metadata_ids", []) or [])
    if missing_selected_ids:
        manifest["warnings"].append(
            f"{len(missing_selected_ids)} requested work IDs were not observed on the page"
        )
    if missing_metadata_ids:
        manifest["warnings"].append(
            f"{len(missing_metadata_ids)} selected works had no retrievable media metadata"
        )
    if not selected:
        manifest["status"] = "failed_no_visible_works"
        manifest["finished_at"] = utc_now()
        manifest["profile_responses_observed"] = response_count
        write_json(manifest_path, manifest)
        raise WorkDownloadError("No visible creator work metadata was observed; check login or verification")

    selected_recent_count = len(
        [work for work in selected if work["selection_reason"] == "最近"]
    )
    manifest.update(
        {
            "status": "downloading",
            "profile_responses_observed": response_count,
            "visible_works_observed": visible_work_count,
            "requested_scroll_rounds": args.scrolls,
            "effective_scroll_budget": discovery_scroll_budget(
                max(args.recent, int(getattr(args, "limit", 0) or 0), 1), args.scrolls
            ),
            "pinned_selected": len(
                [work for work in selected if work["selection_reason"] == "置顶"]
            ),
            "recent_selected": selected_recent_count,
            "selection_complete": not missing_selected_ids and (
                selected_recent_count >= args.recent
                if input_mode(args) == "creator_pinned_recent"
                else len(selected) > 0
            ),
            "works_selected": len(selected),
            "selected_work_ids": [work["aweme_id"] for work in selected],
            "missing_selected_work_ids": missing_selected_ids,
            "missing_metadata_work_ids": missing_metadata_ids,
            "selection_metadata": getattr(args, "_selection_metadata", {}),
        }
    )
    write_json(manifest_path, manifest)

    public_works: list[dict[str, Any]] = []
    for overall_index, work in enumerate(selected, 1):
        reason_label = str(work.get("selection_reason") or "选择")
        if reason_label == "最近":
            reason_label = f"最近{work['selection_rank']:02d}"
        folder_name = work_file_base(work, overall_index)
        folder = media_dir / folder_name
        if requested_assets:
            folder.mkdir(parents=True, exist_ok=True)
            work["local_folder"] = str(media_label / folder_name)
        else:
            work["local_folder"] = ""
        downloads: dict[str, Any] = {}
        if "primary" not in requested_assets:
            downloads["images" if work["type"] == "图文" else "video"] = {
                "status": "not_requested", "file": "", "bytes": 0
            }
        elif work["type"] == "图文":
            image_results: list[dict[str, Any]] = []
            for image_index, candidates in enumerate(work["_image_urls"], 1):
                image_results.append(
                    download_from_candidates(
                        candidates,
                        folder / f"图文_{image_index:02d}.webp",
                        work["source_url"],
                        args.download_timeout,
                    )
                )
            downloads["images"] = image_results
        else:
            downloads["video"] = download_from_candidates(
                work["_video_urls"],
                folder / "视频.mp4",
                work["source_url"],
                args.download_timeout,
            )
        downloads["cover"] = (
            download_from_candidates(
                work["_cover_urls"], folder / "封面.jpg", work["source_url"], args.download_timeout
            )
            if "cover" in requested_assets
            else {"status": "not_requested", "file": "", "bytes": 0}
        )
        downloads["music"] = (
            download_from_candidates(
                work["_music_urls"], folder / "原声.mp3", work["source_url"], args.download_timeout
            )
            if "audio" in requested_assets
            else {"status": "not_requested", "file": "", "bytes": 0}
        )
        downloads["caption"] = (
            write_caption(folder, work)
            if "caption" in requested_assets
            else {"status": "not_requested", "file": "", "bytes": 0}
        )
        commerce_image_results: list[dict[str, Any]] = []
        commerce = work.get("commerce") if isinstance(work.get("commerce"), dict) else {}
        for product_index, product in enumerate(commerce.get("products") or [], start=1):
            if not isinstance(product, dict):
                continue
            for image_index, image in enumerate(product.get("images") or [], start=1):
                if not isinstance(image, dict):
                    continue
                result = download_product_image(
                    [str(image.get("url") or "")],
                    folder / "商品资料" / f"商品_{product_index:02d}_图片_{image_index:03d}",
                    work["source_url"],
                    args.download_timeout,
                )
                result["product_index"] = product_index
                result["image_index"] = image_index
                result["source_url"] = str(image.get("url") or "")
                if result.get("file"):
                    result["file"] = str(Path("商品资料") / str(result["file"]))
                image["download"] = result
                commerce_image_results.append(result)
        if getattr(args, "commerce_detail", False):
            downloads["commerce_images"] = commerce_image_results
        work["downloads"] = downloads
        flat_results: list[dict[str, Any]] = []
        for value in downloads.values():
            flat_results.extend(value if isinstance(value, list) else [value])
        failed = [result for result in flat_results if result.get("status") == "failed"]
        metadata_shortfall = (
            not bool(work.get("_metadata_observed", True))
            and bool(requested_assets & {"primary", "cover", "audio"})
        )
        work["download_status"] = "完成" if not failed and not metadata_shortfall else "部分完成"
        public = public_work_record(work)
        public_works.append(public)
        manifest["works"] = public_works
        write_json(works_path, public_works)
        write_json(manifest_path, manifest)
        print(
            json.dumps(
                {
                    "event": "work_downloaded",
                    "index": overall_index,
                    "total": len(selected),
                    "aweme_id": work["aweme_id"],
                    "selection": reason_label,
                    "status": work["download_status"],
                },
                ensure_ascii=False,
            )
        )

    partial = [work for work in public_works if work.get("download_status") != "完成"]
    recent_selected = len([work for work in public_works if work["selection_reason"] == "最近"])
    if input_mode(args) == "creator_pinned_recent":
        status = final_works_status(bool(partial), recent_selected, args.recent)
    elif missing_selected_ids:
        status = "partial_selection_and_download_errors" if partial else "partial_selection_shortfall"
    elif missing_metadata_ids and requested_assets & {"primary", "cover", "audio"}:
        status = "partial_metadata_unavailable"
    else:
        status = "partial_download_errors" if partial else "complete"
    manifest.update(
        {
            "status": status,
            "finished_at": utc_now(),
            "profile_responses_observed": response_count,
            "visible_works_observed": visible_work_count,
            "requested_scroll_rounds": args.scrolls,
            "effective_scroll_budget": discovery_scroll_budget(
                max(args.recent, int(getattr(args, "limit", 0) or 0), 1), args.scrolls
            ),
            "pinned_selected": len([work for work in public_works if work["selection_reason"] == "置顶"]),
            "recent_selected": recent_selected,
            "selection_complete": not missing_selected_ids and (
                recent_selected >= args.recent
                if input_mode(args) == "creator_pinned_recent"
                else len(public_works) > 0
            ),
            "works_selected": len(public_works),
            "works_complete": len(public_works) - len(partial),
            "works_partial": len(partial),
            "works": public_works,
            "commerce_anchor_observation": public_works[0].get("commerce_anchor") if len(public_works) == 1 else None,
            "commerce_detail_observation": public_works[0].get("commerce") if len(public_works) == 1 else None,
            **({"product_reviews": getattr(args, "_product_review_summary", {"requested": True,
                "status": "partial", "exit_code": 3, "done_reason": "not_started"})}
                if getattr(args, "product_reviews", False) else {}),
        }
    )
    write_json(works_path, public_works)
    write_json(manifest_path, manifest)
    if getattr(args, "zip", False):
        package_result = package_directory(out_dir, resolve_zip_path(args))
        manifest["package"] = {**package_result, "zip": Path(package_result["zip"]).name}
        write_json(manifest_path, manifest)
    print(json.dumps({key: manifest[key] for key in (
        "status", "visible_works_observed", "pinned_selected", "recent_selected",
        "works_selected", "works_complete", "works_partial",
    )}, ensure_ascii=False, indent=2))
    review_code = int(manifest.get("product_reviews", {}).get("exit_code", 3)) if getattr(args, "product_reviews", False) else 0
    return 0 if manifest["status"] == "complete" and not review_code else 3


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        return run(parse_args())
    except WorkDownloadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
