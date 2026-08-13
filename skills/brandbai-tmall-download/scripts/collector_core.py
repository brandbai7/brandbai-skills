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
TRANSIENT_VIDEO_HOSTS = {"tbm-auth.alicdn.com"}
PLATFORM_NOTICE_IMAGE_IDS = {"O1CN01XU1Y2d1Sk7fIMOkeU"}
DENIED_HOST_PREFIXES = ("pass.", "login.", "passport.", "account.")
ITEM_ID_RE = re.compile(r"^[0-9]{5,24}$")
PRICE_LABEL_RE = re.compile(
    r"到手价|券后价|活动价|促销价|售价|现价|价格|优惠前|原价|平台加补后|店铺优惠后|补贴后|"
    r"首单礼金|专属平台礼金|平台礼金|专属礼金|优惠券|红包|满减|百亿补贴|官方立减"
)
BENEFIT_LABEL_RE = re.compile(r"首单礼金|专属平台礼金|平台礼金|专属礼金|优惠券|红包|满减|百亿补贴|官方立减")
SKU_OPTION_NOISE_RE = re.compile(
    r"点击查看大图|查看大图|查看详情|展开|收起|加入会员|开通会员|店铺会员|会员权益|会员尊享|尊享特权|立即领取|领取优惠|领券|加购|购物车|客服|咨询|分享"
)


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
    if parsed.username or parsed.password:
        raise CollectionError("Media URL must not contain embedded credentials")
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


def media_request_url(value: str, *, kind: str | None = None) -> str:
    """Return the transient request URL after allowlist validation.

    Trusted legacy Taobao CDN URLs are upgraded to HTTPS before the request.
    Query material may be needed by the CDN for the immediate transfer, but the
    caller must never persist this returned value in logs or delivery files.
    """

    sanitize_media_url(value, kind=kind)
    parsed = urlparse(str(value or "").strip())
    return urlunparse(("https", parsed.netloc, parsed.path, parsed.params, parsed.query, ""))


def sanitize_transient_video_url(value: str) -> tuple[str, bool]:
    """Validate a temporary Tmall video URL while redacting its signature.

    The caller may use the original value only for the immediate request. The
    returned URL is safe for manifests because query and fragment material are
    removed.
    """

    parsed = urlparse(str(value or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in TRANSIENT_VIDEO_HOSTS:
        raise CollectionError("The temporary video URL is not on the Tmall media host")
    if not re.search(r"\.(?:mp4|mov|webm)$", parsed.path, flags=re.I):
        raise CollectionError("The temporary video URL is not a directly downloadable video file")
    clean = urlunparse(("https", host, parsed.path, "", "", ""))
    return clean, bool(parsed.query or parsed.fragment)


def is_platform_notice_image_url(value: str) -> bool:
    text = str(value or "")
    return any(asset_id in text for asset_id in PLATFORM_NOTICE_IMAGE_IDS)


def canonical_image_asset_key(value: str) -> str:
    clean, _ = sanitize_media_url(value, kind="image")
    parsed = urlparse(clean)
    path = re.sub(r"_(?:q\d+(?:s\d+)?\.)?(?:jpg|jpeg|png)_\.(?:webp|avif)$", "", parsed.path, flags=re.I)
    path = re.sub(r"_\.(?:webp|avif)$", "", path, flags=re.I)
    return f"{(parsed.hostname or '').lower()}{path}"


def image_is_usable(width: Any, height: Any, kind: str, source_url: str = "") -> bool:
    if is_platform_notice_image_url(source_url):
        return False
    try:
        w, h = int(width or 0), int(height or 0)
    except (TypeError, ValueError):
        return False
    if w < 300 or h <= 0:
        return False
    if kind == "main_image":
        return h >= 300
    if kind == "detail_image":
        return h >= 80 and h / max(w, 1) >= 0.08
    return True


def image_content_status(
    width: Any,
    height: Any,
    kind: str,
    source_url: str = "",
    downloaded_bytes: Any = 0,
) -> str:
    if not image_is_usable(width, height, kind, source_url):
        return "excluded_quality"
    if kind != "detail_image":
        return "content_image"
    try:
        w, h, size = int(width or 0), int(height or 0), int(downloaded_bytes or 0)
    except (TypeError, ValueError):
        return "unknown"
    if h < 320 and w / max(h, 1) >= 4.5:
        return "separator_candidate"
    if size > 0 and h < 420 and size / max(w * h, 1) < 0.04:
        return "low_information_candidate"
    return "content_image"


def is_usable_sku_option(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or len(text) > 80:
        return False
    if re.fullmatch(r"[¥￥]?\d+(?:\.\d{1,2})?|[-+]|数量|有货|无货|已选", text):
        return False
    return not SKU_OPTION_NOISE_RE.search(text)


def normalize_price_candidates(values: Iterable[Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    def role_for(label: str) -> str:
        if BENEFIT_LABEL_RE.search(label):
            return "benefit_amount"
        if re.search(r"优惠前|原价|划线价", label):
            return "original_price"
        if re.search(r"到手价|券后价|活动价|促销价|平台加补后|店铺优惠后|补贴后", label):
            return "promotion_price"
        if re.search(r"售价|现价|价格", label):
            return "current_price"
        return "observed_price"

    for value in values or []:
        if isinstance(value, dict):
            page_top = value.get("page_top")
            try:
                if value.get("product_scope") is not True and page_top is not None and float(page_top) > 2200:
                    continue
            except (TypeError, ValueError):
                pass
            text = str(value.get("text") or "").strip()
            context = str(value.get("context") or "").strip()
        else:
            text, context = str(value or "").strip(), ""
        text_has_amount = bool(re.search(
            r"[¥￥]\s*\d|(?:到手价|券后价|活动价|促销价|售价|现价|价格|优惠前|原价|店铺优惠后|补贴后)[^0-9]{0,12}\d",
            text,
        ))
        combined = text if text_has_amount else re.sub(r"\s+", " ", f"{context} {text}").strip()
        observations: list[tuple[str, str]] = []
        previous_amount_end = 0
        def trim_glued_chinese_date(amount: str, following_text: str) -> str:
            if not amount:
                return amount
            following = str(following_text or "")
            if re.match(r"\s+(?:0?[1-9]|1[0-2])\s*月\s*(?:0?[1-9]|[12]\d|3[01])\s*日", following):
                return amount
            for moved_digits in (1, 2):
                if len(amount) <= moved_digits:
                    continue
                price = amount[:-moved_digits]
                date_prefix = f"{amount[-moved_digits:]}{following}"
                if not re.fullmatch(r"\d+(?:\.\d{1,2})?", price):
                    continue
                if re.match(r"(?:0?[1-9]|1[0-2])\s*月\s*(?:0?[1-9]|[12]\d|3[01])\s*日", date_prefix):
                    return price
            return amount

        for match in re.finditer(r"[¥￥]\s*(\d+(?:\.\d{1,2})?)", combined):
            before = combined[previous_amount_end : match.start()]
            after = combined[match.end() : match.end() + 24]
            prior_labels = PRICE_LABEL_RE.findall(before)
            following = re.match(r"\s*(?:元)?\s*(首单礼金|专属平台礼金|平台礼金|专属礼金|优惠券|红包|满减|百亿补贴|官方立减)", after)
            label = prior_labels[-1] if prior_labels else (following.group(1) if following else "")
            observations.append((trim_glued_chinese_date(match.group(1), combined[match.end() :]), label))
            previous_amount_end = match.end()
        if not observations:
            labelled = re.search(
                r"(到手价|券后价|活动价|促销价|售价|现价|价格|优惠前|原价|店铺优惠后|补贴后)[^0-9]{0,12}(\d+(?:\.\d{1,2})?)",
                combined,
            )
            if labelled:
                observations.append((trim_glued_chinese_date(labelled.group(2), combined[labelled.end() :]), labelled.group(1)))
        for amount, label in observations:
            if not amount or float(amount) > 100_000_000:
                continue
            role = role_for(label)
            display_label = label or "页面价格"
            key = f"{role}:{display_label}"
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "role": role,
                "amount": amount,
                "text": f"{display_label} ￥{amount}",
                "context": (context or text)[:120],
            })
    return rows[:16]


def sku_mapping_status(selected_sku_id: Any, groups: Iterable[Any]) -> str:
    """Describe how far the observed SKU selection can be mapped.

    A SKU id alone is not enough evidence for a complete product identity.  If
    the page exposes an id but none of the visible option groups expose their
    selected value, preserve the id and downgrade completion instead of
    implying that the id-to-option mapping was observed.
    """

    normalized_groups = [group for group in (groups or []) if isinstance(group, dict)]
    has_groups = any(group.get("values") for group in normalized_groups)
    has_selected_value = any(
        str(group.get("selected_value") or group.get("selectedValue") or "").strip()
        for group in normalized_groups
    )
    has_sku_id = bool(str(selected_sku_id or "").strip())
    if has_sku_id and has_selected_value:
        return "selected_sku_mapped"
    if has_sku_id:
        return "sku_id_unmapped"
    if has_selected_value:
        return "visible_selection_without_sku_id"
    if has_groups:
        return "visible_options_no_selection"
    return "not_observed"


def sku_parameter_warnings(selected_snapshot: Iterable[Any], parameters: Iterable[Any]) -> list[dict[str, str]]:
    selected = [row for row in (selected_snapshot or []) if isinstance(row, dict)]
    page_parameters = [row for row in (parameters or []) if isinstance(row, dict)]
    warnings: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(selected_row: dict[str, Any], parameter_row: dict[str, Any], reason: str) -> None:
        key = f"{selected_row.get('name')}:{selected_row.get('value')}|{parameter_row.get('name')}:{parameter_row.get('value')}|{reason}"
        if key in seen:
            return
        seen.add(key)
        warnings.append({
            "selected_name": str(selected_row.get("name") or "").strip(),
            "selected_value": str(selected_row.get("value") or "").strip(),
            "parameter_name": str(parameter_row.get("name") or "").strip(),
            "parameter_value": str(parameter_row.get("value") or "").strip(),
            "reason": reason,
            "status": "requires_human_confirmation",
        })

    def unit_values(value: str) -> list[str]:
        rows = []
        for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(片|支|袋|盒|瓶|罐|毫升|ml|克|kg|千克|g)(?:\b|以下|以上|装|$)", value, flags=re.I):
            normalized_unit = {"毫升": "ml", "千克": "kg", "克": "g"}.get(unit.lower(), unit.lower())
            rows.append(f"{float(amount):g}:{normalized_unit}")
        return rows

    def color_codes(value: str) -> list[str]:
        return [re.sub(r"\s+", "", item).upper() for item in re.findall(r"\b[A-Z]{1,4}\s*0?\d{1,3}\b", value, flags=re.I)]

    def forms(value: str) -> list[str]:
        return re.findall(r"纸尿裤|拉拉裤|成长裤|纸尿片|安睡裤|卫生巾|洗脸巾|棉柔巾", value, flags=re.I)

    for selected_row in selected:
        selected_name = str(selected_row.get("name") or "")
        selected_value = str(selected_row.get("value") or "")
        for parameter_row in page_parameters:
            parameter_name = str(parameter_row.get("name") or "")
            parameter_value = str(parameter_row.get("value") or "")
            selected_units = unit_values(selected_value)
            parameter_units = unit_values(parameter_value)
            for selected_unit in selected_units:
                unit = selected_unit.split(":", 1)[1]
                comparable = next((value for value in parameter_units if value.endswith(f":{unit}")), "")
                if comparable and comparable != selected_unit:
                    add(selected_row, parameter_row, "same_unit_value_conflict")
            if re.search(r"颜色|色号|色彩", selected_name + parameter_name):
                selected_codes = color_codes(selected_value)
                parameter_codes = color_codes(parameter_value)
                if selected_codes and parameter_codes and not set(selected_codes).intersection(parameter_codes):
                    add(selected_row, parameter_row, "color_code_conflict")
            selected_forms = forms(selected_value)
            parameter_forms = forms(parameter_value)
            if selected_forms and parameter_forms and not set(selected_forms).intersection(parameter_forms):
                add(selected_row, parameter_row, "product_form_conflict")
    return warnings[:20]


def choose_product_completion_state(
    *,
    sku_status: str,
    detail_requested: bool,
    detail_status: str,
    detail_position_restored: bool | None = True,
    failed_asset_records: bool = False,
    critical_asset_missing: bool = False,
    module_failures: bool = False,
) -> str:
    """Choose one conservative top-level state while preserving detail ledgers."""

    if sku_status == "sku_id_unmapped":
        return "partial_product_identity"
    if detail_requested and detail_status != "observed":
        return "partial_detail_images_not_observed"
    if detail_requested and detail_position_restored is False:
        return "partial_detail_scroll_not_restored"
    if failed_asset_records or critical_asset_missing or module_failures:
        return "partial_asset_failure"
    return "complete_observed_product"


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
