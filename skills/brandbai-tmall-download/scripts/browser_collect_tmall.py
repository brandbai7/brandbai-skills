"""Collect public Tmall item facts and source-visible reviews in visible Chrome.

The collector uses a normal persistent Playwright Chrome context. It never
exports cookies, headers, browser profiles, signatures, or verification data.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from collector_core import (
    CollectionError,
    RunManifest,
    atomic_write_json,
    canonical_item_url,
    choose_review_status,
    dedupe_preserve_order,
    derived_answer_id,
    derived_question_id,
    derived_review_id,
    extract_item_id,
    navigation_item_url,
    normalize_item_targets,
    pseudonymize_author,
    pseudonymize_qa_author,
    read_jsonl_ids,
    safe_filename,
    sanitize_media_url,
    utc_now,
)


PRODUCT_SCRIPT = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const leafText = (root = document) => [...root.querySelectorAll('*')]
    .filter((el) => visible(el) && el.children.length === 0 && clean(el.textContent))
    .map((el) => ({el, text: clean(el.textContent)}));
  const leaves = leafText();
  const titleFromDocument = clean(document.title).replace(/[-_]tmall\.com.*$/i, '').replace(/-天猫.*$/i, '');
  const titleCandidates = [...document.querySelectorAll('h1,[class*="title" i],[class*="Title"]')]
    .filter(visible).map((el) => clean(el.textContent)).filter((text) => text.length >= 8 && text.length <= 220);
  const title = titleFromDocument || titleCandidates.sort((a,b) => b.length - a.length)[0] || '';
  const itemId = new URL(location.href).searchParams.get('id') || document.querySelector('[data-item]')?.getAttribute('data-item') || '';
  const skuId = new URL(location.href).searchParams.get('skuId') || '';

  const shopLinks = [...document.querySelectorAll('a[href]')].filter(visible).map((el) => ({
    text: clean(el.textContent), href: el.href ? el.href.split('?')[0].split('#')[0] : ''
  })).filter((row) => row.text && row.text.length <= 60 && /(旗舰店|专卖店|专营店|企业店|官方店)/.test(row.text));

  const labelValue = (label) => {
    const node = leaves.find((row) => row.text === label)?.el;
    if (!node) return '';
    for (const parent of [node.parentElement, node.parentElement?.parentElement, node.parentElement?.parentElement?.parentElement]) {
      if (!parent) continue;
      const parts = leafText(parent).map((row) => row.text).filter((text) => text !== label && text.length <= 160);
      if (parts.length) return parts[0];
    }
    return '';
  };
  const parameterLabels = [
    '品牌','系列','规格','净含量','包装方式','产地','省份','城市','保质期','储藏方法','生产日期',
    '厂名','厂址','厂家联系方式','生产许可证编号','产品标准号','配料表','食品添加剂','适用对象',
    '商品条形码','进口食品','口味','是否含糖','生鲜储存温度','原产国/地区'
  ];
  const parameters = parameterLabels.map((label) => ({name: label, value: labelValue(label)})).filter((row) => row.value);

  const skuRoots = leaves.filter((row) => /^(套餐类型|颜色分类|口味|规格|净含量|尺寸|款式|型号)$/.test(row.text)
    && row.el.closest('[class*="skuItem" i],[class*="labelWrap" i]'));
  const skuGroups = skuRoots.map(({el, text}) => {
    const root = el.closest('[class*="skuItemClip" i],[class*="skuItem" i]') || el.parentElement?.parentElement;
    const valueNodes = [...(root || el.parentElement).querySelectorAll('[class*="valueItemText--"]')].filter(visible);
    const values = (valueNodes.length ? valueNodes.map((node) => clean(node.textContent)) : leafText(root || el.parentElement).map((row) => row.text))
      .filter((value) => value !== text && value.length <= 80 && !/^(¥|￥|[-+]|数量|有货|无货)$/.test(value));
    const selected = valueNodes.find((node) => node.closest('[class*="isSelected--"]'));
    return {name: text, values: [...new Set(values)].slice(0, 40), selected_value: clean(selected?.textContent)};
  }).filter((group) => group.values.length);

  const priceTexts = leaves.map((row) => row.text).filter((text) => /^(¥|￥)?\s*\d+(?:\.\d{1,2})?$/.test(text)).slice(0, 20);
  const salesTexts = leaves.map((row) => row.text).filter((text) => /(?:已售|月销|付款|销量)\s*[0-9.万+]+/.test(text)).slice(0, 12);
  const stockTexts = leaves.map((row) => row.text).filter((text) => /^(有货|无货|库存\s*\d+.*)$/.test(text)).slice(0, 10);

  const images = [...document.querySelectorAll('img')].filter(visible).map((img, index) => {
    const src = img.currentSrc || img.src || '';
    const rect = img.getBoundingClientRect();
    const classTrail = [img, img.parentElement, img.parentElement?.parentElement, img.parentElement?.parentElement?.parentElement,
      img.parentElement?.parentElement?.parentElement?.parentElement]
      .map((el) => typeof el?.className === 'string' ? el.className : '').join(' ');
    const context = clean(img.closest('[class*="detail" i],[class*="gallery" i],main,section')?.textContent).slice(0, 120);
    let kind = 'other';
    if (/(?:thumbnailPic|mainPic|picGallery|thumbnailsWrap)/i.test(classTrail) && img.naturalWidth >= 300) kind = 'main_image';
    else if (/(?:desc-root|descV8|imageTextInfo|detailContent)/i.test(classTrail) && img.naturalWidth >= 300) kind = 'detail_image';
    return {index, src, kind, width: img.naturalWidth || Math.round(rect.width), height: img.naturalHeight || Math.round(rect.height), context};
  }).filter((row) => /^(https?:)?\/\/(img|gw)\.alicdn\.com\//i.test(row.src) && row.kind !== 'other');

  const videoUrls = [...document.querySelectorAll('video,video source')].map((el) => el.currentSrc || el.src || el.getAttribute('src') || '')
    .filter((src) => /^(https?:)?\/\/(cloud\.video\.taobao\.com|video\.alicdn\.com)\//i.test(src));

  return {
    item_id: itemId,
    selected_sku_id: skuId,
    title,
    shop: shopLinks[0] || {text:'',href:''},
    parameters,
    sku_groups: skuGroups,
    snapshot: {
      price_texts: [...new Set(priceTexts)],
      sales_texts: [...new Set(salesTexts)],
      stock_texts: [...new Set(stockTexts)]
    },
    media: {images, videos: [...new Set(videoUrls)]}
  };
}
"""


REVIEW_CARD_SCRIPT = r"""
(card) => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const text = clean(card.innerText);
  const lines = (card.innerText || '').split(/\n+/).map(clean).filter(Boolean);
  const username = clean(card.querySelector('[class*="userName--"]')?.textContent || lines[0] || '');
  const contentNodes = [...card.querySelectorAll('[class^="content--"],[class*=" content--"]')]
    .filter(visible).map((el) => ({
      text: clean(el.textContent),
      role: el.closest('[class*="append--"]') ? 'followup' : 'review',
      relative_event: clean(el.closest('[class*="append--"]')?.textContent).match(/\d+\s*天后追评|追评/)?.[0] || ''
    })).filter((row) => row.text);
  const seenContent = new Set();
  const contents = contentNodes.filter((row) => {
    const key = row.role + '\u241f' + row.text;
    if (row.text.length < 2 || seenContent.has(key)) return false;
    seenContent.add(key);
    return true;
  });
  const headerLines = (card.querySelector('[class*="header--"]')?.innerText || '').split(/\n+/).map(clean).filter(Boolean);
  const purchasedLine = headerLines.find((line) => /已购[：:]/.test(line)) || lines.find((line) => /已购[：:]/.test(line)) || '';
  const purchasedIndex = purchasedLine.search(/已购[：:]/);
  const purchased = purchasedIndex >= 0 ? purchasedLine.slice(purchasedIndex) : purchasedLine;
  const datePrefix = purchasedIndex > 0 ? clean(purchasedLine.slice(0, purchasedIndex).replace(/[|·]+$/, '')) : '';
  const dates = [datePrefix, ...[...text.matchAll(/(?:20\d{2}(?:[-/.年]\d{1,2})?(?:[-/.月]\d{1,2}日?)?|\d{1,2}[-/.]\d{1,2}|\d+\s*(?:天|月|年)前)(?:\s+\d{1,2}:\d{2})?/g)].map((m) => m[0])].filter(Boolean);
  const platformId = card.getAttribute('data-review-id') || card.getAttribute('data-id') || card.id || '';
  const media = [...card.querySelectorAll('img,video,video source')]
    .filter((el) => !el.closest('[class*="userInfo" i],[class*="avatar" i],[class*="header--"]'))
    .map((el) => ({
    kind: el.tagName === 'IMG' ? 'image' : 'video',
    src: el.currentSrc || el.src || el.getAttribute('src') || ''
  })).filter((row) => /^(https?:)?\/\/(img|gw)\.alicdn\.com\//i.test(row.src) || /^(https?:)?\/\/(cloud\.video\.taobao\.com|video\.alicdn\.com)\//i.test(row.src));
  return {username, contents, dates, purchased_sku: purchased, platform_review_id: platformId, media};
}
"""


QA_CARDS_SCRIPT = r"""
(root) => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  return [...root.querySelectorAll('[class*="qaItem--"]')].map((card) => {
    const question = clean(card.querySelector('[class*="questionTitle--"]')?.textContent);
    const cardText = clean(card.innerText || card.textContent);
    const declared = Number((cardText.match(/(?:查看全部|共)\s*(\d+)\s*(?:个|条)?回答/) || [])[1] || 0);
    const answers = [...card.querySelectorAll('[class*="answerItem--"]')].map((answer) => ({
      author: clean(answer.querySelector('[class*="userNick--"]')?.textContent),
      buyer_tag: clean(answer.querySelector('[class*="userTag--"]')?.textContent || answer.querySelector('[class*="timeAgo--"]')?.textContent),
      content: clean(answer.querySelector('[class*="answerContent--"]')?.textContent),
      meta_text: clean(answer.querySelector('[class*="answerMeta--"]')?.textContent)
    })).filter((row) => row.content);
    return {question, declared_answer_count: Math.max(declared, answers.length), answers};
  }).filter((row) => row.question);
}
"""


def find_chrome_executable(explicit: str | None = None) -> str:
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            return str(path)
        raise CollectionError(f"Chrome executable not found: {path}")
    candidates: list[Path] = []
    if sys.platform == "win32":
        for root in [os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")]:
            if root:
                candidates.append(Path(root) / "Google/Chrome/Application/chrome.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    else:
        for name in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]:
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
    for path in candidates:
        if path.is_file():
            return str(path)
    raise CollectionError("Google Chrome was not found; pass --chrome-path explicitly")


def normalize_assets(value: str) -> list[str]:
    allowed = {"main_images", "detail_images", "video", "review_media", "none"}
    parts = dedupe_preserve_order(part.strip() for part in str(value or "").split(",") if part.strip())
    unknown = [part for part in parts if part not in allowed]
    if unknown:
        raise CollectionError(f"Unknown asset type(s): {', '.join(unknown)}")
    if "none" in parts and len(parts) > 1:
        raise CollectionError("assets=none cannot be combined with other asset types")
    return [] if parts == ["none"] else parts


def _extension_from_response(clean_url: str, content_type: str, kind: str) -> str:
    suffix = Path(urlparse(clean_url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm", ".mov"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ""
    if guessed == ".jpe":
        guessed = ".jpg"
    return guessed or (".mp4" if kind == "video" else ".bin")


def download_asset(context: Any, source_url: str, target_base: Path, *, kind: str, max_bytes: int) -> dict[str, Any]:
    clean_url, redacted = sanitize_media_url(source_url, kind=kind)
    response = context.request.get(source_url, timeout=90_000)
    if not response.ok:
        raise CollectionError(f"Asset request returned HTTP {response.status}")
    body = response.body()
    if len(body) > max_bytes:
        raise CollectionError(f"Asset exceeds the configured size limit ({len(body)} bytes)")
    content_type = response.headers.get("content-type", "")
    extension = _extension_from_response(clean_url, content_type, kind)
    target = target_base.with_suffix(extension)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    partial.write_bytes(body)
    partial.replace(target)
    return {
        "file": str(target),
        "source_url": clean_url,
        "source_url_query_redacted": redacted,
        "content_type": content_type,
        "bytes": len(body),
        "status": "downloaded",
    }


def collect_product(page: Any, context: Any, source_url: str, out: Path, assets: list[str], max_asset_bytes: int) -> dict[str, Any]:
    item_id = extract_item_id(source_url)
    canonical_url = canonical_item_url(source_url)
    navigation_url = navigation_item_url(source_url)
    requested_sku_id = (parse_qs(urlparse(navigation_url).query).get("skuId") or [""])[0]
    page.goto(navigation_url, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(3_000)
    if any(page.get_by_text(label, exact=False).count() for label in ["滑动验证", "安全验证", "请完成验证"]):
        raise CollectionError("Tmall requires manual verification in the visible Chrome window")
    # Trigger ordinary lazy loading without reading hidden browser state.
    try:
        detail = page.get_by_text("图文详情", exact=True).first
        if detail.count():
            detail.scroll_into_view_if_needed(timeout=10_000)
            page.wait_for_timeout(1_000)
        height = min(int(page.evaluate("() => document.documentElement.scrollHeight")), 60_000)
        for position in range(0, height, 1_200):
            page.evaluate("(top) => window.scrollTo({top, behavior: 'instant'})", position)
            page.wait_for_timeout(120)
        page.evaluate("() => window.scrollTo({top: 0, behavior: 'instant'})")
        page.wait_for_timeout(500)
    except Exception:
        pass
    raw = page.evaluate(PRODUCT_SCRIPT)
    if not str(raw.get("title") or "").strip():
        raise CollectionError("No visible product title was found")

    # Product video sources often appear only after the normal visible tab is selected.
    if "video" in assets and not raw.get("media", {}).get("videos"):
        candidates = page.get_by_text("视频", exact=True)
        for index in range(min(candidates.count(), 8)):
            candidate = candidates.nth(index)
            try:
                box = candidate.bounding_box()
                if box and box["y"] < 1_100 and box["x"] < 1_200:
                    candidate.click(timeout=5_000)
                    page.wait_for_timeout(1_200)
                    video_urls = page.eval_on_selector_all(
                        "video,video source",
                        "els => [...new Set(els.map(el => el.currentSrc || el.src || el.getAttribute('src') || '').filter(Boolean))]",
                    )
                    raw.setdefault("media", {}).setdefault("videos", []).extend(video_urls)
                    break
            except Exception:
                continue
    raw["item_id"] = str(raw.get("item_id") or item_id)
    raw["selected_sku_id"] = str(raw.get("selected_sku_id") or requested_sku_id)
    raw["product_id"] = f"tmall:{raw['item_id']}"
    raw["canonical_url"] = canonical_url
    raw["source_page_type"] = "tmall_item" if "tmall.com" in canonical_url else "taobao_item"
    raw["collected_at"] = utc_now()
    raw["snapshot"]["observed_at"] = raw["collected_at"]
    raw["snapshot"]["selected_sku_id"] = raw.get("selected_sku_id") or ""
    raw["media_records"] = []

    media_root = out / "03_商品素材" / safe_filename(raw.get("title") or "", fallback=item_id)
    counters = {"main_image": 0, "detail_image": 0, "video": 0}
    requested_map = {"main_image": "main_images", "detail_image": "detail_images", "video": "video"}
    observed: list[tuple[str, str]] = []
    for image in raw.get("media", {}).get("images", []):
        observed.append((str(image.get("kind") or ""), str(image.get("src") or "")))
    for video in raw.get("media", {}).get("videos", []):
        observed.append(("video", str(video or "")))

    seen_urls: set[str] = set()
    for kind, source in observed:
        requested = requested_map.get(kind)
        if not source or not requested:
            continue
        try:
            clean_url, redacted = sanitize_media_url(source, kind="video" if kind == "video" else "image")
        except CollectionError:
            continue
        if clean_url in seen_urls:
            continue
        seen_urls.add(clean_url)
        counters[kind] += 1
        folder = {"main_image": "主图", "detail_image": "详情图", "video": "视频"}[kind]
        record: dict[str, Any] = {
            "asset_id": f"tmall:{item_id}:{kind}:{counters[kind]:03d}",
            "item_id": item_id,
            "kind": kind,
            "order": counters[kind],
            "source_url": clean_url,
            "source_url_query_redacted": redacted,
            "status": "observed_not_requested",
            "file": "",
        }
        if requested in assets:
            base = media_root / folder / f"{counters[kind]:03d}_{kind}"
            try:
                downloaded = download_asset(
                    context,
                    source,
                    base,
                    kind="video" if kind == "video" else "image",
                    max_bytes=max_asset_bytes,
                )
                downloaded["file"] = str(Path(downloaded["file"]).relative_to(out))
                record.update(downloaded)
            except Exception as exc:  # keep an auditable partial record
                record["status"] = "failed"
                record["error"] = type(exc).__name__
        raw["media_records"].append(record)

    for kind, request_name in requested_map.items():
        if request_name in assets and counters[kind] == 0:
            raw["media_records"].append({
                "asset_id": f"tmall:{item_id}:{kind}:000",
                "item_id": item_id,
                "kind": kind,
                "order": 0,
                "source_url": "",
                "source_url_query_redacted": False,
                "status": "not_observed",
                "file": "",
            })

    requested_records = [row for row in raw["media_records"] if requested_map.get(row["kind"]) in assets]
    failed_records = [row for row in requested_records if row["status"] != "downloaded"]
    critical_missing = any(row["kind"] == "main_image" and row["status"] == "not_observed" for row in requested_records)
    raw["completion_state"] = "partial_asset_failure" if failed_records or critical_missing else "complete_observed_product"
    raw.pop("media", None)
    product_dir = out / "data" / "商品采集" / item_id
    atomic_write_json(product_dir / "product.json", raw)
    atomic_write_json(product_dir / "asset_manifest.json", raw["media_records"])
    return raw


def _folded_count(page: Any) -> int:
    body = page.locator("body").inner_text(timeout=10_000)
    match = re.search(r"已折叠\s*([0-9]+)\s*条", body)
    return int(match.group(1)) if match else 0


def _find_review_root(page: Any) -> Any | None:
    roots = page.locator('div[class*="comments--"]')
    best = None
    best_height = -1
    for index in range(roots.count()):
        candidate = roots.nth(index)
        try:
            if not candidate.is_visible():
                continue
            state = candidate.evaluate("(el) => ({height: el.scrollHeight, client: el.clientHeight})")
            score = int(state.get("height") or 0)
            if score > best_height:
                best, best_height = candidate, score
        except Exception:
            continue
    return best


def _open_review_panel(page: Any, wait_seconds: int = 0) -> Any | None:
    root = _find_review_root(page)
    if root is not None:
        try:
            state = root.evaluate("(el) => ({height: el.scrollHeight, client: el.clientHeight})")
            if int(state.get("height") or 0) > int(state.get("client") or 0) + 100:
                return root
        except Exception:
            pass
    for label in ["查看全部评价", "全部评价"]:
        candidates = page.get_by_text(label, exact=True)
        for index in range(min(candidates.count(), 5)):
            candidate = candidates.nth(index)
            if candidate.is_visible():
                candidate.scroll_into_view_if_needed(timeout=10_000)
                candidate.evaluate("el => { el.style.outline='4px solid #ff7a00'; el.style.outlineOffset='5px'; }")
                print("Please click 查看全部评价 in the visible product page, then return to this task.")
                if wait_seconds > 0:
                    page.wait_for_timeout(wait_seconds * 1_000)
                    root = _find_review_root(page)
                    if root is not None:
                        return root
    return None


def _review_rows_from_raw(raw: dict[str, Any], item_id: str, *, retain_masked_author: bool) -> list[dict[str, Any]]:
    author = str(raw.get("username") or "")
    contents = [value for value in raw.get("contents") or [] if isinstance(value, dict) and str(value.get("text") or "").strip()]
    if not contents:
        return []
    dates = [str(value) for value in raw.get("dates") or []]
    purchased = str(raw.get("purchased_sku") or "")
    platform_id = str(raw.get("platform_review_id") or "")
    media_records: list[dict[str, Any]] = []
    for media in raw.get("media") or []:
        try:
            clean_url, redacted = sanitize_media_url(str(media.get("src") or ""), kind=str(media.get("kind") or "image"))
        except CollectionError:
            continue
        media_records.append({
            "kind": media.get("kind"),
            "source_url": clean_url,
            "source_url_query_redacted": redacted,
            "status": "observed_not_requested",
            "file": "",
            "_transient_source_url": str(media.get("src") or ""),
        })
    rows: list[dict[str, Any]] = []
    for index, content_row in enumerate(contents):
        content = str(content_row.get("text") or "").strip()
        role = str(content_row.get("role") or "review")
        date_text = str(content_row.get("relative_event") or "") if role == "followup" else (dates[min(index, len(dates) - 1)] if dates else "")
        review_id = platform_id if platform_id and index == 0 else derived_review_id(item_id, author, date_text, purchased, content, role)
        row = {
            "review_id": review_id,
            "review_id_type": "platform" if platform_id and index == 0 else "derived",
            "item_id": item_id,
            "product_id": f"tmall:{item_id}",
            "role": role,
            "author_id": pseudonymize_author(author),
            "author_masked": author if retain_masked_author else "",
            "date_text": date_text,
            "purchased_sku_text": purchased,
            "content": content,
            "media": media_records if index == 0 else [],
            "collected_at": utc_now(),
        }
        rows.append(row)
    return rows


def _review_rows_from_card(card: Any, item_id: str, *, retain_masked_author: bool) -> list[dict[str, Any]]:
    return _review_rows_from_raw(
        card.evaluate(REVIEW_CARD_SCRIPT),
        item_id,
        retain_masked_author=retain_masked_author,
    )


def collect_reviews(
    page: Any,
    context: Any,
    source_url: str,
    out: Path,
    *,
    assets: list[str],
    max_asset_bytes: int,
    limit: int,
    max_scroll_actions: int,
    retain_masked_author: bool,
    resume: bool,
    panel_wait: int = 0,
) -> dict[str, Any]:
    item_id = extract_item_id(source_url)
    canonical_url = canonical_item_url(source_url)
    navigation_url = navigation_item_url(source_url)
    if extract_item_id(page.url) != item_id if "item.htm" in page.url else True:
        page.goto(navigation_url, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(3_500)
    review_dir = out / "data" / "评价采集" / item_id
    review_dir.mkdir(parents=True, exist_ok=True)
    rows_path = review_dir / "reviews.jsonl"
    saved_ids = read_jsonl_ids(rows_path, "review_id") if resume else set()
    if not resume and rows_path.exists():
        rows_path.unlink()
    root = _open_review_panel(page, panel_wait)
    if root is None:
        manifest = {
            "schema_version": "1.0",
            "item_id": item_id,
            "canonical_url": canonical_url,
            "state": "partial_requires_full_review_panel",
            "saved_reviews": len(saved_ids),
            "folded_count": 0,
            "exhausted": False,
            "finished_at": utc_now(),
        }
        atomic_write_json(review_dir / "review_manifest.json", manifest)
        return manifest

    no_growth_rounds = 0
    exhausted = False
    limit_reached = False
    scroll_actions = 0
    with rows_path.open("a", encoding="utf-8", newline="\n") as handle:
        while scroll_actions <= max_scroll_actions:
            before = len(saved_ids)
            cards = root.locator('[class*="Comment--"]')
            # Parse the newest cards in one browser call. Tmall keeps prior cards in the
            # DOM, so re-reading every historical card on every scroll made long review
            # lists progressively slower. A 250-card overlap is deliberately larger than
            # one lazy-load batch; saved_ids still provides exact de-duplication on resume.
            raw_cards = cards.evaluate_all(
                f"(cards) => cards.slice(Math.max(0, cards.length - 250)).map({REVIEW_CARD_SCRIPT})"
            )
            for raw_card in raw_cards:
                for row in _review_rows_from_raw(raw_card, item_id, retain_masked_author=retain_masked_author):
                    if row["review_id"] in saved_ids:
                        continue
                    if limit > 0 and len(saved_ids) >= limit:
                        limit_reached = True
                        break
                    if "review_media" in assets:
                        media_folder = out / "03_商品素材" / item_id / "评价素材"
                        for media_index, media in enumerate(row.get("media") or [], start=1):
                            transient = str(media.pop("_transient_source_url", "") or "")
                            try:
                                downloaded = download_asset(
                                    context,
                                    transient,
                                    media_folder / f"{row['review_id'].replace(':', '_')}_{media_index:02d}",
                                    kind=str(media.get("kind") or "image"),
                                    max_bytes=max_asset_bytes,
                                )
                                downloaded["file"] = str(Path(downloaded["file"]).relative_to(out))
                                media.update(downloaded)
                            except Exception as exc:
                                media["status"] = "failed"
                                media["error"] = type(exc).__name__
                    else:
                        for media in row.get("media") or []:
                            media.pop("_transient_source_url", None)
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    handle.flush()
                    saved_ids.add(row["review_id"])
            if limit_reached:
                break
            state = root.evaluate("(el) => ({top: el.scrollTop, height: el.scrollHeight, client: el.clientHeight})")
            at_bottom = state["top"] + state["client"] >= state["height"] - 4
            no_growth_rounds = no_growth_rounds + 1 if len(saved_ids) == before else 0
            if at_bottom and no_growth_rounds >= 3:
                exhausted = True
                break
            root.evaluate("(el) => el.scrollTo({top: Math.min(el.scrollHeight, el.scrollTop + Math.max(500, el.clientHeight * 0.85)), behavior: 'instant'})")
            page.wait_for_timeout(550)
            scroll_actions += 1

    folded_count = _folded_count(page)
    status = choose_review_status(exhausted=exhausted, folded_count=folded_count, limit_reached=limit_reached)
    manifest = {
        "schema_version": "1.0",
        "item_id": item_id,
        "canonical_url": canonical_url,
        "state": status,
        "saved_reviews": len(saved_ids),
        "folded_count": folded_count,
        "exhausted": exhausted,
        "limit": limit,
        "limit_reached": limit_reached,
        "scroll_actions": scroll_actions,
        "privacy_mode": "masked_author_retained" if retain_masked_author else "pseudonymized",
        "finished_at": utc_now(),
    }
    atomic_write_json(review_dir / "review_manifest.json", manifest)
    return manifest


def _find_question_root(page: Any) -> Any | None:
    roots = page.locator('[class*="AskAnswersWrap--"]')
    for index in range(roots.count()):
        candidate = roots.nth(index)
        try:
            if candidate.is_visible() and candidate.locator('[class*="qaItem--"]').count():
                return candidate
        except Exception:
            continue
    return None


def _open_question_panel(page: Any, wait_seconds: int = 0) -> Any | None:
    root = _find_question_root(page)
    if root is not None:
        return root
    candidates = page.get_by_text("查看全部问答", exact=True)
    for index in range(min(candidates.count(), 5)):
        candidate = candidates.nth(index)
        try:
            if not candidate.is_visible():
                continue
            candidate.scroll_into_view_if_needed(timeout=10_000)
            candidate.evaluate("el => { el.style.outline='4px solid #ff7a00'; el.style.outlineOffset='5px'; }")
            print("Please click 查看全部问答 in the visible product page, then return to this task.")
            if wait_seconds > 0:
                page.wait_for_timeout(wait_seconds * 1_000)
                return _find_question_root(page)
        except Exception:
            continue
    return None


def _question_scroll_root(root: Any) -> Any:
    candidates = root.locator("*")
    best = root
    best_gap = 0
    for index in range(candidates.count()):
        candidate = candidates.nth(index)
        try:
            if not candidate.is_visible():
                continue
            state = candidate.evaluate("el => ({height: el.scrollHeight, client: el.clientHeight})")
            gap = int(state.get("height") or 0) - int(state.get("client") or 0)
            if gap > best_gap:
                best, best_gap = candidate, gap
        except Exception:
            continue
    return best


def _append_jsonl_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()


def collect_questions(
    page: Any,
    source_url: str,
    out: Path,
    *,
    limit: int,
    max_scroll_actions: int,
    retain_masked_author: bool,
    resume: bool,
    panel_wait: int = 0,
) -> dict[str, Any]:
    item_id = extract_item_id(source_url)
    canonical_url = canonical_item_url(source_url)
    navigation_url = navigation_item_url(source_url)
    if extract_item_id(page.url) != item_id if "item.htm" in page.url else True:
        page.goto(navigation_url, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(3_500)
    question_dir = out / "data" / "问答采集" / item_id
    question_dir.mkdir(parents=True, exist_ok=True)
    questions_path = question_dir / "questions.jsonl"
    answers_path = question_dir / "answers.jsonl"
    question_ids = read_jsonl_ids(questions_path, "question_id") if resume else set()
    answer_ids = read_jsonl_ids(answers_path, "answer_id") if resume else set()
    if not resume:
        questions_path.unlink(missing_ok=True)
        answers_path.unlink(missing_ok=True)
    root = _open_question_panel(page, panel_wait)
    if root is None:
        manifest = {
            "schema_version": "1.0", "item_id": item_id, "canonical_url": canonical_url,
            "state": "partial_requires_full_question_panel", "saved_questions": len(question_ids),
            "saved_answers": len(answer_ids), "total_hint": 0, "exhausted": False,
            "limit": limit, "limit_reached": False, "finished_at": utc_now(),
        }
        atomic_write_json(question_dir / "question_manifest.json", manifest)
        return manifest

    scroll_root = _question_scroll_root(root)
    no_growth_rounds = 0
    exhausted = False
    limit_reached = False
    scroll_actions = 0
    while scroll_actions <= max_scroll_actions:
        before = len(question_ids)
        expanders = root.get_by_text(re.compile(r"^查看全部回答$"))
        for index in range(min(expanders.count(), 6)):
            try:
                candidate = expanders.nth(index)
                if candidate.is_visible():
                    candidate.click(timeout=5_000)
                    page.wait_for_timeout(120)
            except Exception:
                continue
        raw_cards = root.evaluate(QA_CARDS_SCRIPT)
        new_questions: list[dict[str, Any]] = []
        new_answers: list[dict[str, Any]] = []
        for raw in raw_cards or []:
            content = str(raw.get("question") or "").strip()
            if not content:
                continue
            question_id = derived_question_id(item_id, content)
            if limit > 0 and len(question_ids) >= limit and question_id not in question_ids:
                limit_reached = True
                break
            if question_id not in question_ids:
                new_questions.append({
                    "question_id": question_id,
                    "item_id": item_id,
                    "product_id": f"tmall:{item_id}",
                    "content": content,
                    "declared_answer_count": int(raw.get("declared_answer_count") or 0),
                    "canonical_url": canonical_url,
                    "collected_at": utc_now(),
                })
                question_ids.add(question_id)
            for answer in raw.get("answers") or []:
                answer_content = str(answer.get("content") or "").strip()
                if not answer_content:
                    continue
                author = str(answer.get("author") or "")
                meta_text = str(answer.get("meta_text") or "")
                answer_id = derived_answer_id(item_id, question_id, author, answer_content, meta_text)
                if answer_id in answer_ids:
                    continue
                new_answers.append({
                    "answer_id": answer_id,
                    "question_id": question_id,
                    "item_id": item_id,
                    "author_id": pseudonymize_qa_author(author),
                    "author_masked": author if retain_masked_author else "",
                    "buyer_tag": str(answer.get("buyer_tag") or ""),
                    "content": answer_content,
                    "meta_text": meta_text,
                    "collected_at": utc_now(),
                })
                answer_ids.add(answer_id)
        _append_jsonl_rows(questions_path, new_questions)
        _append_jsonl_rows(answers_path, new_answers)
        if limit_reached:
            break
        state = scroll_root.evaluate("el => ({top: el.scrollTop, height: el.scrollHeight, client: el.clientHeight})")
        at_bottom = state["top"] + state["client"] >= state["height"] - 4
        no_growth_rounds = no_growth_rounds + 1 if len(question_ids) == before else 0
        if at_bottom and no_growth_rounds >= 3:
            exhausted = True
            break
        scroll_root.evaluate("el => el.scrollTo({top: Math.min(el.scrollHeight, el.scrollTop + Math.max(420, el.clientHeight * .78)), behavior: 'instant'})")
        page.wait_for_timeout(420)
        scroll_actions += 1

    body_text = page.locator("body").inner_text(timeout=10_000)
    total_match = re.search(r"问大家\s*[·・]?\s*(\d+)", body_text)
    total_hint = int(total_match.group(1)) if total_match else 0
    if limit_reached:
        status = "partial_limit_sample"
    elif exhausted and (not total_hint or len(question_ids) >= total_hint):
        status = "complete_visible_qa_exhausted"
    elif exhausted:
        status = "partial_visible_count_below_page_hint"
    else:
        status = "partial_not_exhausted"
    manifest = {
        "schema_version": "1.0", "item_id": item_id, "canonical_url": canonical_url,
        "state": status, "saved_questions": len(question_ids), "saved_answers": len(answer_ids),
        "total_hint": total_hint, "exhausted": exhausted, "limit": limit,
        "limit_reached": limit_reached, "scroll_actions": scroll_actions,
        "privacy_mode": "masked_author_retained" if retain_masked_author else "pseudonymized",
        "finished_at": utc_now(),
    }
    atomic_write_json(question_dir / "question_manifest.json", manifest)
    return manifest


def collect(
    *,
    item_urls: list[str],
    profile_dir: Path,
    out: Path,
    mode: str,
    assets: list[str],
    review_limit: int,
    question_limit: int,
    max_scroll_actions: int,
    login_wait: int,
    retain_masked_author: bool,
    resume: bool,
    chrome_path: str | None,
    max_asset_mb: int,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CollectionError("Playwright is missing; install requirements-browser.txt first") from exc

    normalized_urls = normalize_item_targets(item_urls)
    item_ids = [extract_item_id(value) for value in normalized_urls]
    out.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    manifest = RunManifest(mode=mode, item_ids=item_ids, requested_assets=assets, privacy_mode="masked_author_retained" if retain_masked_author else "pseudonymized")
    manifest_path = out / "data" / "run_manifest.json"
    atomic_write_json(manifest_path, manifest.as_dict())

    executable = find_chrome_executable(chrome_path)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir.resolve()),
            executable_path=executable,
            headless=False,
            viewport=None,
            args=["--start-maximized"],
            accept_downloads=True,
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            if login_wait > 0:
                page.goto("https://www.tmall.com/", wait_until="domcontentloaded", timeout=120_000)
                print(f"Visible Chrome is ready. Complete any required login or verification within {login_wait} seconds.")
                page.wait_for_timeout(login_wait * 1_000)
            for url in normalized_urls:
                item_id = extract_item_id(url)
                if mode in {"product", "all"}:
                    try:
                        product = collect_product(page, context, url, out, assets, max_asset_mb * 1024 * 1024)
                        manifest.product_states[item_id] = product["completion_state"]
                    except Exception as exc:
                        manifest.product_states[item_id] = "failed_no_visible_product"
                        manifest.warnings.append(f"{item_id}: product collection failed ({type(exc).__name__})")
                if mode in {"reviews", "all"}:
                    try:
                        review = collect_reviews(
                            page, context, url, out,
                            assets=assets,
                            max_asset_bytes=max_asset_mb * 1024 * 1024,
                            limit=review_limit,
                            max_scroll_actions=max_scroll_actions,
                            retain_masked_author=retain_masked_author,
                            resume=resume,
                            panel_wait=login_wait,
                        )
                        manifest.review_states[item_id] = review["state"]
                    except Exception as exc:
                        manifest.review_states[item_id] = "partial_runtime_error"
                        manifest.warnings.append(f"{item_id}: review collection failed ({type(exc).__name__})")
                if mode in {"questions", "all"}:
                    try:
                        question = collect_questions(
                            page, url, out,
                            limit=question_limit,
                            max_scroll_actions=max_scroll_actions,
                            retain_masked_author=retain_masked_author,
                            resume=resume,
                            panel_wait=login_wait,
                        )
                        manifest.question_states[item_id] = question["state"]
                    except Exception as exc:
                        manifest.question_states[item_id] = "partial_runtime_error"
                        manifest.warnings.append(f"{item_id}: question collection failed ({type(exc).__name__})")
                atomic_write_json(manifest_path, manifest.as_dict())
        finally:
            context.close()

    states = list(manifest.product_states.values()) + list(manifest.review_states.values()) + list(manifest.question_states.values())
    manifest.state = "complete" if states and all(value.startswith("complete") for value in states) else "partial"
    manifest.finished_at = utc_now()
    atomic_write_json(manifest_path, manifest.as_dict())
    return manifest.as_dict()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect visible Tmall product facts and reviews")
    parser.add_argument("mode", choices=["product", "reviews", "questions", "all"])
    parser.add_argument("--item", action="append", required=True, help="Tmall/Taobao item URL or numeric item id")
    parser.add_argument("--profile-dir", required=True, type=Path, help="Private persistent Chrome profile outside the delivery folder")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--assets", default="main_images,detail_images", help="main_images,detail_images,video,review_media,none")
    parser.add_argument("--review-limit", type=int, default=0, help="0 means continue until the visible source is exhausted")
    parser.add_argument("--question-limit", type=int, default=0, help="0 means continue until the visible question panel is exhausted")
    parser.add_argument("--max-scroll-actions", type=int, default=800)
    parser.add_argument("--login-wait", type=int, default=0)
    parser.add_argument("--retain-masked-author", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--chrome-path")
    parser.add_argument("--max-asset-mb", type=int, default=200)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = collect(
            item_urls=args.item,
            profile_dir=args.profile_dir,
            out=args.out,
            mode=args.mode,
            assets=normalize_assets(args.assets),
            review_limit=max(0, args.review_limit),
            question_limit=max(0, args.question_limit),
            max_scroll_actions=max(1, args.max_scroll_actions),
            login_wait=max(0, args.login_wait),
            retain_masked_author=args.retain_masked_author,
            resume=args.resume,
            chrome_path=args.chrome_path,
            max_asset_mb=max(1, args.max_asset_mb),
        )
    except (CollectionError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("state") == "complete" else 3


if __name__ == "__main__":
    raise SystemExit(main())
