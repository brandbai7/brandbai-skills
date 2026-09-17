#!/usr/bin/env python3
"""Compile visible live-page events and machine transcripts into evidence.

The compiler aligns observation windows and transcript chunks. It creates
review candidates, not causal claims or platform-server timestamps.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "brandbai-live-recorder/live-interaction-evidence/0.1.0"
EXIT_COMPLETE = 0
EXIT_PARTIAL = 1
EXIT_CONFIG = 2

COMMENT_PATTERNS = {
    "stock_restock": re.compile(r"没了|没抢到|买不到|还有|加一波|再加|补货|能上|上吗|上么|来晚"),
    "shipping_fulfilment": re.compile(r"发货|什么时候发|今天能发|物流|快递|收到|到货"),
    "purchase_signal": re.compile(r"已拍|拍了|下单|买了|抢到|付款"),
    "offer_gift": re.compile(r"福袋|面霜|眼霜|赠品|多送|送什么|礼盒"),
}

TRANSCRIPT_PATTERNS = {
    "stock_restock": re.compile(r"没抢到|还能加|再加|最后.{0,5}单|只有.{0,5}单|捡漏|没了|抢到"),
    "shipping_fulfilment": re.compile(r"发货|今天发|物流|快递|收到|到货"),
    "purchase_signal": re.compile(r"已拍|拍了|下单|买了|抢到|付款"),
    "offer_gift": re.compile(r"福袋|面霜|眼霜|赠品|多送|送.{0,5}(霜|礼|套)"),
}

CTA_PATTERN = re.compile(r"三二一|倒数|捡漏|拍|买|抢|链接|购物车|一号|1号")
PRODUCT_VALUE_PATTERN = re.compile(r"抗皱|紧致|补水|保湿|修护|功效|效果|适合|不挑人")


class EvidenceError(RuntimeError):
    """Expected input or output contract failure."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise EvidenceError(f"找不到输入文件：{path.name}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceError(f"{path.name} 第 {line_number} 行不是有效 JSON") from exc
        if not isinstance(value, dict):
            raise EvidenceError(f"{path.name} 第 {line_number} 行必须是 JSON 对象")
        rows.append(value)
    return rows


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def finite_offset(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceError(f"{field} 必须是数字")
    result = float(value)
    if not math.isfinite(result):
        raise EvidenceError(f"{field} 必须是有限数字")
    return round(result, 3)


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_unified_events(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    comments: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for row in rows:
        event_type = str(row.get("event_type") or "")
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        offset_value = row.get("recording_offset_seconds")
        if offset_value is None:
            continue
        offset = finite_offset(offset_value, "recording_offset_seconds")
        common = {
            "event_id": str(row.get("visible_event_id") or ""),
            "media_offset_seconds": offset,
            "within_recording_window": bool(row.get("within_recording_window")),
            "observed_at": optional_text(row.get("observed_at")),
            "time_alignment_status": str(
                row.get("time_alignment_status") or "wall_clock_approximate_uncalibrated"
            ),
            "completeness": str(
                row.get("completeness") or "page_visible_first_observation_only"
            ),
        }
        if event_type == "comment_visible":
            comments.append(
                {
                    **common,
                    "masked_user": str(payload.get("masked_user") or ""),
                    "text": str(payload.get("text") or ""),
                    "observation_kind": str(payload.get("observation_kind") or "new_visible"),
                }
            )
        elif event_type == "product_state":
            products.append(
                {
                    **common,
                    "visible": bool(payload.get("visible")),
                    "product_title": optional_text(payload.get("product_title")),
                    "display_price": optional_text(payload.get("display_price")),
                    "event_type": str(payload.get("change_kind") or "product_state"),
                }
            )
        elif event_type == "room_snapshot":
            snapshots.append({**common, **payload})
        elif event_type == "collector_status":
            statuses.append({**common, **payload})
    return comments, products, snapshots, statuses


def normalize_legacy_comments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append(
            {
                "event_id": str(row.get("comment_event_id") or row.get("event_id") or ""),
                "masked_user": str(row.get("masked_user") or ""),
                "text": str(row.get("text") or ""),
                "observation_kind": str(row.get("observation_kind") or "new_visible"),
                "media_offset_seconds": finite_offset(
                    row.get("media_offset_seconds"), "comment media_offset_seconds"
                ),
                "within_recording_window": bool(row.get("within_recording_window", True)),
                "observed_at": optional_text(row.get("observed_at")),
                "time_alignment_status": "wall_clock_approximate_uncalibrated",
                "completeness": str(row.get("completeness") or "partial_visible_window"),
            }
        )
    return normalized


def normalize_legacy_products(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        title = optional_text(row.get("product_title"))
        price = optional_text(row.get("display_price"))
        normalized.append(
            {
                "event_id": str(row.get("product_event_id") or row.get("event_id") or ""),
                "event_type": str(row.get("event_type") or "product_state"),
                "visible": bool(title or price),
                "product_title": title,
                "display_price": price,
                "media_offset_seconds": finite_offset(
                    row.get("media_offset_seconds"), "product media_offset_seconds"
                ),
                "within_recording_window": bool(row.get("within_recording_window", True)),
                "observed_at": optional_text(row.get("observed_at")),
                "time_alignment_status": "wall_clock_approximate_uncalibrated",
                "completeness": str(row.get("completeness") or "partial_visible_window"),
            }
        )
    return normalized


def normalize_legacy_snapshots(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append(
            {
                **row,
                "event_id": str(row.get("snapshot_id") or row.get("event_id") or ""),
                "media_offset_seconds": finite_offset(
                    row.get("media_offset_seconds"), "snapshot media_offset_seconds"
                ),
                "within_recording_window": bool(row.get("within_recording_window", True)),
                "time_alignment_status": "wall_clock_approximate_uncalibrated",
            }
        )
    return normalized


def normalize_transcripts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        status = str(row.get("status") or row.get("transcription_status") or "completed")
        if status not in {"completed", "COMPLETED_MACHINE"}:
            continue
        start_value = row.get("media_start_seconds", row.get("start_seconds"))
        end_value = row.get("media_end_seconds", row.get("end_seconds"))
        if start_value is None or end_value is None:
            continue
        start = finite_offset(start_value, "transcript start")
        end = finite_offset(end_value, "transcript end")
        if end <= start:
            raise EvidenceError("转写片段结束时间必须晚于开始时间")
        text = str(row.get("text") or "").strip()
        if not text or text == "[NO_SPEECH]":
            continue
        normalized.append(
            {
                "transcript_segment_id": str(
                    row.get("transcript_segment_id") or f"transcript-{index + 1:04d}"
                ),
                "start_seconds": start,
                "end_seconds": end,
                "text": text,
                "resolved_model": str(row.get("resolved_model") or ""),
                "human_review_status": str(row.get("human_review_status") or "NOT_REVIEWED"),
                "time_source": str(
                    row.get("time_source") or "deterministic_local_audio_chunk_boundaries"
                ),
                "model_timestamp": bool(row.get("model_timestamp", False)),
            }
        )
    return sorted(normalized, key=lambda row: (row["start_seconds"], row["end_seconds"]))


def previous_snapshot_offset(snapshots: list[dict[str, Any]], upper: float) -> float | None:
    earlier = [
        row["media_offset_seconds"]
        for row in snapshots
        if row.get("within_recording_window") and row["media_offset_seconds"] < upper
    ]
    return max(earlier) if earlier else None


def comment_category(text: str) -> str:
    for category, pattern in COMMENT_PATTERNS.items():
        if pattern.search(text):
            return category
    if re.search(r"[?？]|吗|么|怎么|多少|哪", text):
        return "other_question"
    return "other_visible_comment"


def group_comment_clusters(
    comments: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[float, str], list[dict[str, Any]]] = {}
    for row in comments:
        if not row.get("within_recording_window") or not row.get("text"):
            continue
        category = comment_category(str(row["text"]))
        key = (float(row["media_offset_seconds"]), category)
        grouped.setdefault(key, []).append(row)
    clusters: list[dict[str, Any]] = []
    for index, ((upper, category), rows) in enumerate(sorted(grouped.items()), 1):
        baseline = all(row.get("observation_kind") == "baseline_visible" for row in rows)
        lower = None if baseline else previous_snapshot_offset(snapshots, upper)
        clusters.append(
            {
                "comment_cluster_id": f"comment-cluster-{index:04d}",
                "category": category,
                "comment_count": len(rows),
                "comments": [
                    {
                        "event_id": row.get("event_id"),
                        "masked_user": row.get("masked_user"),
                        "text": row.get("text"),
                    }
                    for row in rows
                ],
                "first_seen_lower_bound_seconds": lower,
                "first_seen_upper_bound_seconds": upper,
                "time_precision": (
                    "baseline_lower_bound_unknown"
                    if baseline or lower is None
                    else "periodic_snapshot_observation_window"
                ),
                "time_alignment_status": rows[0].get("time_alignment_status"),
            }
        )
    return clusters


def transcript_candidates(
    transcripts: list[dict[str, Any]],
    *,
    lower: float | None,
    upper: float,
    response_window_seconds: float,
) -> list[dict[str, Any]]:
    search_start = lower if lower is not None else upper
    search_end = upper + response_window_seconds
    return [
        row
        for row in transcripts
        if row["end_seconds"] >= search_start and row["start_seconds"] <= search_end
    ]


def compile_comment_relations(
    clusters: list[dict[str, Any]],
    transcripts: list[dict[str, Any]],
    response_window_seconds: float,
) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    for cluster in clusters:
        category = cluster["category"]
        candidates = transcript_candidates(
            transcripts,
            lower=cluster["first_seen_lower_bound_seconds"],
            upper=cluster["first_seen_upper_bound_seconds"],
            response_window_seconds=response_window_seconds,
        )
        pattern = TRANSCRIPT_PATTERNS.get(category)
        matches = [row for row in candidates if pattern and pattern.search(row["text"])]
        if matches:
            relation = "GROUP_RESPONSE_CANDIDATE"
            confidence = "MEDIUM"
            reason = (
                "评论主题与主播话术在观察窗口附近匹配；仍需校准播放延迟和人工听校，"
                "不能绑定到某一条评论。"
            )
        elif candidates and category in {"other_question", "other_visible_comment"}:
            relation = "POSSIBLE_RELATION"
            confidence = "LOW"
            reason = "附近存在主播话术，但规则无法确认主题匹配。"
        else:
            relation = "NOT_OBSERVED_IN_WINDOW"
            confidence = "MEDIUM"
            reason = "在本次限定观察窗口内未找到规则可识别的对应话术，不能外推为整场忽略。"
        selected = matches or candidates[:2]
        relations.append(
            {
                **cluster,
                "relation_level": relation,
                "confidence": confidence,
                "candidate_transcript_segments": selected,
                "response_window_seconds": response_window_seconds,
                "reason": reason,
                "causal_claim_allowed": False,
            }
        )
    return relations


def title_terms(title: str | None) -> list[str]:
    if not title:
        return []
    compact = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", title)
    preferred = [term for term in ("韩束", "红蛮腰", "礼盒", "环六肽", "抗皱", "紧致") if term in compact]
    return preferred


def compile_product_relations(
    products: list[dict[str, Any]],
    transcripts: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    product_window_seconds: float,
) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    last_visible: dict[str, Any] | None = None
    for row in sorted(products, key=lambda item: item["media_offset_seconds"]):
        if not row.get("within_recording_window"):
            continue
        if row.get("event_type") in {"baseline_visible"}:
            if row.get("visible"):
                last_visible = row
            continue
        if row.get("event_type") not in {"visible_product_changed", "restored_visible"}:
            if row.get("visible"):
                last_visible = row
            continue
        event_time = float(row["media_offset_seconds"])
        candidates = [
            segment
            for segment in transcripts
            if segment["end_seconds"] >= event_time - product_window_seconds
            and segment["start_seconds"] <= event_time + product_window_seconds
        ]
        joined = " ".join(segment["text"] for segment in candidates)
        terms = title_terms(row.get("product_title"))
        identity_terms = [term for term in terms if term in joined]
        cta_observed = bool(CTA_PATTERN.search(joined))
        value_observed = bool(PRODUCT_VALUE_PATTERN.search(joined))
        display_price = str(row.get("display_price") or "")
        spoken_price_verified = bool(display_price and display_price in joined)
        lower = previous_snapshot_offset(snapshots, event_time)
        relation = "VISIBLE_SWITCH_WITH_HOST_COORDINATION" if (identity_terms or cta_observed) else "VISIBLE_SWITCH_NO_RULE_MATCH"
        relations.append(
            {
                "product_relation_id": f"product-relation-{len(relations) + 1:04d}",
                "event_id": row.get("event_id"),
                "event_type": row.get("event_type"),
                "first_seen_lower_bound_seconds": lower,
                "first_seen_upper_bound_seconds": event_time,
                "time_precision": (
                    "periodic_snapshot_observation_window"
                    if lower is not None
                    else "baseline_lower_bound_unknown"
                ),
                "previous_product": (
                    {
                        "product_title": last_visible.get("product_title"),
                        "display_price": last_visible.get("display_price"),
                    }
                    if last_visible
                    else None
                ),
                "current_product": {
                    "product_title": row.get("product_title"),
                    "display_price": row.get("display_price"),
                },
                "candidate_transcript_segments": candidates,
                "identity_terms_observed": identity_terms,
                "cta_observed": cta_observed,
                "product_value_observed": value_observed,
                "spoken_price_verified": spoken_price_verified,
                "relation_level": relation,
                "confidence": "HIGH_FOR_VISIBLE_TEMPORAL_ALIGNMENT" if candidates else "UNAVAILABLE",
                "causal_claim_allowed": False,
                "reason": (
                    "商品首次可见窗口附近存在同商品身份或行动话术。"
                    if relation == "VISIBLE_SWITCH_WITH_HOST_COORDINATION"
                    else "已观察到商品变化，但附近话术未形成规则可识别的配合。"
                ),
            }
        )
        if row.get("visible"):
            last_visible = row
    return relations


def metric_summary(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    aligned = [row for row in snapshots if row.get("within_recording_window")]
    online_values = [
        row.get("online_viewers")
        for row in aligned
        if isinstance(row.get("online_viewers"), int) and not isinstance(row.get("online_viewers"), bool)
    ]
    like_values = [
        row.get("likes_count")
        for row in aligned
        if isinstance(row.get("likes_count"), int) and not isinstance(row.get("likes_count"), bool)
    ]
    cart_totals = [
        row.get("cart_total")
        for row in aligned
        if isinstance(row.get("cart_total"), int) and not isinstance(row.get("cart_total"), bool)
    ]
    commerce_observations = [
        row.get("has_commerce_goods")
        for row in aligned
        if isinstance(row.get("has_commerce_goods"), bool)
    ]
    return {
        "aligned_snapshot_count": len(aligned),
        "online_viewers_min": min(online_values) if online_values else None,
        "online_viewers_max": max(online_values) if online_values else None,
        "online_viewers_first": online_values[0] if online_values else None,
        "online_viewers_last": online_values[-1] if online_values else None,
        "likes_count_first": like_values[0] if like_values else None,
        "likes_count_last": like_values[-1] if like_values else None,
        "cart_total_first": cart_totals[0] if cart_totals else None,
        "cart_total_last": cart_totals[-1] if cart_totals else None,
        "has_commerce_goods_observed": any(commerce_observations)
        if commerce_observations
        else None,
        "causal_claim_allowed": False,
        "interpretation": "房间瞬时背景轨迹，不用于证明评论、话术或商品弹窗造成涨跌。",
    }


def fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "未知"
    milliseconds = max(0, round(seconds * 1000))
    minutes, remainder = divmod(milliseconds, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


def compact_text(text: str, limit: int = 100) -> str:
    value = re.sub(r"\s+", " ", text).strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def build_report(
    *,
    comment_relations: list[dict[str, Any]],
    product_relations: list[dict[str, Any]],
    metrics: dict[str, Any],
    manifest_status: str,
) -> str:
    lines = [
        "# 直播互动协同证据",
        "",
        "## 结论边界",
        "",
        "本文件自动对齐页面首次可见事件与机器转写窗口，只生成复核候选。页面时间不是平台发送时间；未经播放器延迟校准和人工听校，不生成逐条直接回复、成交或因果结论。",
        "",
        f"编译状态：`{manifest_status}`。评论关系 {len(comment_relations)} 组，商品关系 {len(product_relations)} 组。",
        "",
        "## 评论—主播候选",
        "",
        "| 首次观察窗口 | 评论类别与内容 | 主播候选话术 | 证据等级 |",
        "| --- | --- | --- | --- |",
    ]
    for relation in comment_relations:
        lower = fmt_time(relation.get("first_seen_lower_bound_seconds"))
        upper = fmt_time(relation.get("first_seen_upper_bound_seconds"))
        comments = "；".join(item["text"] for item in relation["comments"][:4])
        transcripts = "；".join(
            compact_text(item["text"])
            for item in relation.get("candidate_transcript_segments", [])[:2]
        ) or "未观察到对应话术"
        lines.append(
            f"| {lower}—{upper} | {relation['category']}：{comments} | {transcripts} | {relation['relation_level']} / {relation['confidence']} |"
        )
    if not comment_relations:
        lines.append("| — | 没有落在录屏窗口内的可用评论 | — | UNAVAILABLE |")
    lines.extend(
        [
            "",
            "## 商品弹窗—主播候选",
            "",
            "| 首次观察窗口 | 商品变化 | 主播候选话术 | 配合检查 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for relation in product_relations:
        lower = fmt_time(relation.get("first_seen_lower_bound_seconds"))
        upper = fmt_time(relation.get("first_seen_upper_bound_seconds"))
        before = relation.get("previous_product") or {}
        after = relation.get("current_product") or {}
        change = f"{before.get('display_price') or '未知'} → {after.get('display_price') or '未知'}；{after.get('product_title') or '标题未知'}"
        transcripts = "；".join(
            compact_text(item["text"])
            for item in relation.get("candidate_transcript_segments", [])[:3]
        ) or "未观察到对应话术"
        checks = (
            f"身份词={','.join(relation['identity_terms_observed']) or '未命中'}；"
            f"行动指令={'有' if relation['cta_observed'] else '未观察'}；"
            f"价值话术={'有' if relation['product_value_observed'] else '未观察'}；"
            f"口播价核验={'通过' if relation['spoken_price_verified'] else '未通过'}"
        )
        lines.append(f"| {lower}—{upper} | {change} | {transcripts} | {checks} |")
    if not product_relations:
        lines.append("| — | 没有可用的商品切换事件 | — | UNAVAILABLE |")
    lines.extend(
        [
            "",
            "## 房间背景轨迹",
            "",
            f"- 对齐快照：{metrics['aligned_snapshot_count']}。",
            f"- 在线人数观察范围：{metrics['online_viewers_min']}—{metrics['online_viewers_max']}；首个值 {metrics['online_viewers_first']}，末个值 {metrics['online_viewers_last']}。",
            f"- 点赞累计值：首个 {metrics['likes_count_first']}，末个 {metrics['likes_count_last']}。",
            f"- 购物车商品总数：首个 {metrics['cart_total_first']}，末个 {metrics['cart_total_last']}；观察到带货标记={metrics['has_commerce_goods_observed']}。",
            "- 带货标记与购物车数量不等于当前商品弹窗，不能替代 product_state 事件。",
            "- 该变化只作背景轨迹，不归因于评论、主播话术、商品弹窗或成交。",
            "",
            "## 人工复核要求",
            "",
            "- 先听校品牌、商品、数字、价格、赠品、功效和绝对化表述。",
            "- 校准浏览器播放器与直接直播流的时间偏差后，才能评价响应先后和响应时长。",
            "- `GROUP_RESPONSE_CANDIDATE` 只代表群体问题承接候选，不代表主播读取了某一条评论。",
            "- `NOT_OBSERVED_IN_WINDOW` 只覆盖本次观察窗口，不能外推为整场忽略。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="编译直播评论、商品弹窗与主播转写协同证据。")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--visible-events", help="本机服务统一页面事件 JSONL")
    source.add_argument("--legacy-comments", help="试跑或旧格式评论 JSONL")
    parser.add_argument("--legacy-products", help="旧格式商品事件 JSONL")
    parser.add_argument("--legacy-room-snapshots", help="旧格式房间快照 JSONL")
    parser.add_argument("--transcript-segments", required=True, help="带录屏偏移的转写 JSONL")
    parser.add_argument("--out", required=True, help="新的证据输出目录")
    parser.add_argument("--response-window-seconds", type=float, default=20.0)
    parser.add_argument("--product-window-seconds", type=float, default=10.0)
    return parser


def run(args: argparse.Namespace) -> int:
    if not 1 <= args.response_window_seconds <= 120:
        raise EvidenceError("评论回应窗口必须在 1—120 秒之间")
    if not 1 <= args.product_window_seconds <= 60:
        raise EvidenceError("商品协同窗口必须在 1—60 秒之间")
    output = Path(args.out).expanduser().resolve()
    if output.exists():
        raise EvidenceError("输出目录已存在；请使用新目录，避免覆盖既有证据")
    transcript_path = Path(args.transcript_segments).expanduser().resolve()
    input_paths = [transcript_path]
    statuses: list[dict[str, Any]] = []

    if args.visible_events:
        visible_path = Path(args.visible_events).expanduser().resolve()
        input_paths.append(visible_path)
        comments, products, snapshots, statuses = normalize_unified_events(load_jsonl(visible_path))
        source_mode = "unified_visible_page_events"
    else:
        if not args.legacy_products or not args.legacy_room_snapshots:
            raise EvidenceError("旧格式必须同时提供评论、商品事件和房间快照")
        comment_path = Path(args.legacy_comments).expanduser().resolve()
        product_path = Path(args.legacy_products).expanduser().resolve()
        snapshot_path = Path(args.legacy_room_snapshots).expanduser().resolve()
        input_paths.extend([comment_path, product_path, snapshot_path])
        comments = normalize_legacy_comments(load_jsonl(comment_path))
        products = normalize_legacy_products(load_jsonl(product_path))
        snapshots = normalize_legacy_snapshots(load_jsonl(snapshot_path))
        source_mode = "legacy_trial_jsonl"

    transcripts = normalize_transcripts(load_jsonl(transcript_path))
    comment_clusters = group_comment_clusters(comments, snapshots)
    comment_relations = compile_comment_relations(
        comment_clusters, transcripts, args.response_window_seconds
    )
    product_relations = compile_product_relations(
        products, transcripts, snapshots, args.product_window_seconds
    )
    metrics = metric_summary(snapshots)
    aligned_comments = [row for row in comments if row.get("within_recording_window")]
    aligned_products = [row for row in products if row.get("within_recording_window")]
    missing_layers = []
    if not aligned_comments:
        missing_layers.append("comments")
    if not aligned_products:
        missing_layers.append("products")
    if not transcripts:
        missing_layers.append("transcripts")
    status = "complete_evidence_compilation" if not missing_layers else "partial_evidence_compilation"

    output.mkdir(parents=True)
    data_dir = output / "data"
    data_dir.mkdir()
    write_jsonl(data_dir / "comment_host_relations.jsonl", comment_relations)
    write_jsonl(data_dir / "product_host_relations.jsonl", product_relations)
    write_json(data_dir / "room_metric_summary.json", metrics)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "source_mode": source_mode,
        "counts": {
            "comments_total": len(comments),
            "comments_aligned": len(aligned_comments),
            "comment_clusters": len(comment_clusters),
            "products_total": len(products),
            "products_aligned": len(aligned_products),
            "product_relations": len(product_relations),
            "room_snapshots": len(snapshots),
            "collector_status_events": len(statuses),
            "transcript_segments": len(transcripts),
        },
        "missing_layers": missing_layers,
        "response_window_seconds": args.response_window_seconds,
        "product_window_seconds": args.product_window_seconds,
        "time_contract": "page_first_observation_plus_uncalibrated_recording_wall_clock",
        "platform_server_timestamp_available": False,
        "frame_accurate_alignment": False,
        "machine_transcript_reviewed": all(
            row["human_review_status"] == "REVIEWED" for row in transcripts
        )
        if transcripts
        else False,
        "causal_claim_allowed": False,
        "inputs": [
            {"name": path.name, "sha256": sha256_file(path)} for path in input_paths
        ],
    }
    write_json(data_dir / "interaction_manifest.json", manifest)
    (output / "01_直播互动协同证据.md").write_text(
        build_report(
            comment_relations=comment_relations,
            product_relations=product_relations,
            metrics=metrics,
            manifest_status=status,
        ),
        encoding="utf-8",
    )
    return EXIT_COMPLETE if not missing_layers else EXIT_PARTIAL


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except EvidenceError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
