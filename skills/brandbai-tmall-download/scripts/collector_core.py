"""Pure helpers for BrandBAI Tmall collection.

This module deliberately contains no browser credential handling. It validates
targets, removes tracking parameters from persisted URLs, classifies media, and
keeps completeness states explicit.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


ITEM_HOSTS = {"detail.tmall.com", "item.taobao.com"}
IMAGE_HOSTS = {"img.alicdn.com", "gw.alicdn.com"}
VIDEO_HOSTS = {"cloud.video.taobao.com", "video.alicdn.com"}
DENIED_HOST_PREFIXES = ("pass.", "login.", "passport.", "account.")
ITEM_ID_RE = re.compile(r"^[0-9]{5,24}$")


class CollectionError(RuntimeError):
    """Raised when an input or output violates the collection contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def extract_item_id(value: str) -> str:
    value = str(value or "").strip()
    if ITEM_ID_RE.fullmatch(value):
        return value
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if host not in ITEM_HOSTS:
        raise CollectionError("Only public detail.tmall.com or item.taobao.com item URLs are supported")
    item_id = (parse_qs(parsed.query).get("id") or [""])[0]
    if not ITEM_ID_RE.fullmatch(item_id):
        raise CollectionError("The product URL does not contain a valid numeric item id")
    return item_id


def canonical_item_url(value: str) -> str:
    """Return a tracking-free canonical URL, retaining only the item id."""

    item_id = extract_item_id(value)
    host = (urlparse(value).hostname or "detail.tmall.com").lower()
    if host == "item.taobao.com":
        return f"https://item.taobao.com/item.htm?id={item_id}"
    return f"https://detail.tmall.com/item.htm?id={item_id}"


def navigation_item_url(value: str) -> str:
    """Return a safe navigation URL containing only item id and optional SKU id."""

    canonical = canonical_item_url(value)
    parsed = urlparse(str(value or ""))
    sku_id = (parse_qs(parsed.query).get("skuId") or [""])[0]
    if not ITEM_ID_RE.fullmatch(sku_id):
        return canonical
    separator = "&" if "?" in canonical else "?"
    return canonical + separator + urlencode({"skuId": sku_id})


def normalize_item_targets(values: Iterable[str]) -> list[str]:
    """Deduplicate product targets by item id while keeping the first SKU context."""

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item_id = extract_item_id(value)
        if item_id in seen:
            continue
        seen.add(item_id)
        result.append(navigation_item_url(value))
    return result


def sanitize_media_url(value: str, *, kind: str | None = None) -> tuple[str, bool]:
    """Validate a media URL and redact its query before persistence.

    The second return value records whether query or fragment material was
    removed. The original URL may be used only transiently for the immediate
    download request and must never be written to logs or manifests.
    """

    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"}:
        raise CollectionError("Media URL must use http or https")
    host = (parsed.hostname or "").lower()
    if not host or host.startswith(DENIED_HOST_PREFIXES):
        raise CollectionError("Credential, account, or tracking hosts are not media sources")
    allowed = IMAGE_HOSTS | VIDEO_HOSTS
    if host not in allowed:
        raise CollectionError(f"Media host is not allowlisted: {host}")
    if kind == "image" and host not in IMAGE_HOSTS:
        raise CollectionError("The requested image is not on an allowlisted image host")
    if kind == "video" and host not in VIDEO_HOSTS:
        raise CollectionError("The requested video is not on an allowlisted video host")
    clean = urlunparse(("https", host, parsed.path, "", "", ""))
    return clean, bool(parsed.query or parsed.fragment or parsed.scheme != "https")


def stable_hash(*parts: Any, length: int = 32) -> str:
    material = "\u241f".join(str(part or "").strip() for part in parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:length]


def pseudonymize_author(name: str, *, salt: str = "brandbai-tmall-public") -> str:
    name = str(name or "").strip()
    return f"reviewer_{stable_hash(salt, name, length=12)}" if name else ""


def derived_review_id(
    item_id: str,
    author: str,
    date_text: str,
    purchased_sku: str,
    content: str,
    role: str = "review",
) -> str:
    return "derived:" + stable_hash(item_id, author, date_text, purchased_sku, content, role)


def derived_question_id(item_id: str, content: str) -> str:
    return "question:" + stable_hash(item_id, content)


def derived_answer_id(item_id: str, question_id: str, author: str, content: str, meta_text: str) -> str:
    return "answer:" + stable_hash(item_id, question_id, author, content, meta_text)


def pseudonymize_qa_author(name: str, *, salt: str = "brandbai-tmall-qa-public") -> str:
    name = str(name or "").strip()
    return f"answerer_{stable_hash(salt, name, length=12)}" if name else ""


def dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def choose_review_status(
    *,
    exhausted: bool,
    folded_count: int = 0,
    limit_reached: bool = False,
    login_or_verification: bool = False,
    selector_drift: bool = False,
) -> str:
    if login_or_verification:
        return "partial_login_or_verification"
    if selector_drift:
        return "partial_selector_drift"
    if limit_reached:
        return "partial_limit_sample"
    if folded_count > 0:
        return "partial_platform_folded"
    if exhausted:
        return "complete_visible_panel_exhausted"
    return "partial_not_exhausted"


def safe_filename(value: str, *, fallback: str, limit: int = 72) -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "_", str(value or "")).strip(" ._")
    value = re.sub(r"\s+", " ", value)
    return (value[:limit].rstrip(" ._") or fallback)


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    partial.replace(path)


def read_jsonl_ids(path: Path, key: str) -> set[str]:
    ids: set[str] = set()
    if not path.is_file():
        return ids
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = str(value.get(key) or "") if isinstance(value, dict) else ""
        if item:
            ids.add(item)
    return ids


@dataclass
class RunManifest:
    mode: str
    item_ids: list[str]
    requested_assets: list[str]
    privacy_mode: str = "pseudonymized"
    started_at: str = field(default_factory=utc_now)
    finished_at: str = ""
    state: str = "running"
    product_states: dict[str, str] = field(default_factory=dict)
    review_states: dict[str, str] = field(default_factory=dict)
    question_states: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "mode": self.mode,
            "item_ids": self.item_ids,
            "requested_assets": self.requested_assets,
            "privacy_mode": self.privacy_mode,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "state": self.state,
            "product_states": self.product_states,
            "review_states": self.review_states,
            "question_states": self.question_states,
            "warnings": self.warnings,
        }
