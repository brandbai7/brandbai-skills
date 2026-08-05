#!/usr/bin/env python3
"""Shared SQLite, normalization, and export core for the visible browser collector."""

from __future__ import annotations

import csv
import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

PROVIDER = "douyin_web_browser_ui"

class CollectionError(RuntimeError):
    pass

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def iso_from_timestamp(value: Any) -> str:
    try:
        number = int(value)
        if number > 10_000_000_000:
            number //= 1000
        return datetime.fromtimestamp(number, timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""

def normalize_time(value: Any) -> str:
    converted = iso_from_timestamp(value)
    if converted:
        return converted
    return str(value or "").strip()

def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)

def pick(mapping: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default

def find_scalar(obj: Any, keys: Sequence[str], max_depth: int = 6) -> Any:
    if max_depth < 0:
        return None
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if isinstance(value, (str, int, float)) and value != "":
                return value
        for value in obj.values():
            found = find_scalar(value, keys, max_depth - 1)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj[:50]:
            found = find_scalar(value, keys, max_depth - 1)
            if found is not None:
                return found
    return None

def find_list(obj: Any, keys: Sequence[str], max_depth: int = 6) -> Optional[List[Any]]:
    if max_depth < 0:
        return None
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if isinstance(value, list):
                return value
        for value in obj.values():
            found = find_list(value, keys, max_depth - 1)
            if found is not None:
                return found
    return None

def redact_params(params: Dict[str, Any]) -> Dict[str, Any]:
    redacted: Dict[str, Any] = {}
    for key, value in params.items():
        if "token" in key.lower() or "cookie" in key.lower() or "key" in key.lower():
            redacted[key] = "[REDACTED]"
        else:
            redacted[key] = value
    return redacted

class CommentStore:
    def __init__(self, db_path: Path, privacy_mode: str) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.privacy_mode = privacy_mode
        self._init_schema()
        salt = self.get_meta("privacy_salt")
        if not salt:
            salt = secrets.token_hex(16)
            self.set_meta("privacy_salt", salt)
        self.privacy_salt = salt

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS videos (
                aweme_id TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                creator_sec_user_id TEXT,
                creator_name TEXT,
                description TEXT,
                publish_time TEXT,
                duration_ms INTEGER DEFAULT 0,
                digg_count INTEGER DEFAULT 0,
                comment_count_expected INTEGER DEFAULT 0,
                collect_count INTEGER DEFAULT 0,
                share_count INTEGER DEFAULT 0,
                is_pinned INTEGER DEFAULT 0,
                collected_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS comments (
                evidence_id TEXT PRIMARY KEY,
                comment_id TEXT NOT NULL UNIQUE,
                aweme_id TEXT NOT NULL,
                parent_comment_id TEXT,
                root_comment_id TEXT,
                reply_level INTEGER DEFAULT 0,
                source_url TEXT NOT NULL,
                source_role TEXT NOT NULL,
                evidence_state TEXT NOT NULL DEFAULT 'F',
                author_pseudonym TEXT,
                author_unique_id TEXT,
                is_creator_reply INTEGER DEFAULT 0,
                text TEXT NOT NULL,
                create_time TEXT,
                digg_count INTEGER DEFAULT 0,
                reply_count INTEGER DEFAULT 0,
                ip_label TEXT,
                is_pinned INTEGER DEFAULT 0,
                collected_at TEXT NOT NULL,
                FOREIGN KEY (aweme_id) REFERENCES videos(aweme_id)
            );
            CREATE INDEX IF NOT EXISTS idx_comments_aweme ON comments(aweme_id);
            CREATE INDEX IF NOT EXISTS idx_comments_root ON comments(root_comment_id);
            CREATE TABLE IF NOT EXISTS progress (
                kind TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                cursor TEXT,
                done INTEGER NOT NULL DEFAULT 0,
                meta_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(kind, entity_id)
            );
            CREATE TABLE IF NOT EXISTS request_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requested_at TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                params_json TEXT NOT NULL,
                http_status INTEGER,
                provider_request_id TEXT,
                outcome TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def get_meta(self, key: str) -> str:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else ""

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def log_request(
        self,
        endpoint: str,
        params: Dict[str, Any],
        http_status: int,
        provider_request_id: str,
        outcome: str,
    ) -> None:
        self.conn.execute(
            "INSERT INTO request_log(requested_at,endpoint,params_json,http_status,provider_request_id,outcome) "
            "VALUES(?,?,?,?,?,?)",
            (
                utc_now(),
                endpoint,
                json.dumps(redact_params(params), ensure_ascii=False, sort_keys=True),
                http_status,
                provider_request_id,
                outcome,
            ),
        )
        self.conn.commit()

    def pseudonymize(self, user: Any) -> Tuple[str, str]:
        user = user if isinstance(user, dict) else {}
        nickname = str(pick(user, "nickname", "name", default="") or "")
        unique_id = str(pick(user, "unique_id", "short_id", default="") or "")
        identity = str(pick(user, "sec_uid", "sec_user_id", "uid", "user_id", default="") or "")
        if not identity:
            identity = unique_id or nickname or "unknown"
        digest = hashlib.blake2b(
            f"{self.privacy_salt}:{identity}".encode("utf-8"), digest_size=8
        ).hexdigest()
        if self.privacy_mode == "raw":
            return nickname or f"user_{digest[:10]}", unique_id
        return f"user_{digest[:10]}", ""

    def upsert_video(self, item: Dict[str, Any], fallback_aweme_id: str = "") -> str:
        aweme_id = str(pick(item, "aweme_id", "item_id", "video_id", "id", default=fallback_aweme_id) or "")
        if not aweme_id:
            raise CollectionError("Video response did not include an aweme_id")
        source_url = str(
            pick(
                item,
                "source_url",
                "share_url",
                "url",
                default=f"https://www.douyin.com/video/{aweme_id}",
            )
            or f"https://www.douyin.com/video/{aweme_id}"
        )
        author = pick(item, "author", "user", default={})
        author = author if isinstance(author, dict) else {}
        stats = pick(item, "statistics", "stats", default={})
        stats = stats if isinstance(stats, dict) else {}
        video = pick(item, "video", default={})
        video = video if isinstance(video, dict) else {}
        self.conn.execute(
            """
            INSERT INTO videos(
                aweme_id,source_url,creator_sec_user_id,creator_name,description,publish_time,
                duration_ms,digg_count,comment_count_expected,collect_count,share_count,is_pinned,collected_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(aweme_id) DO UPDATE SET
                source_url=COALESCE(NULLIF(excluded.source_url,''),videos.source_url),
                creator_sec_user_id=COALESCE(NULLIF(excluded.creator_sec_user_id,''),videos.creator_sec_user_id),
                creator_name=COALESCE(NULLIF(excluded.creator_name,''),videos.creator_name),
                description=COALESCE(NULLIF(excluded.description,''),videos.description),
                publish_time=COALESCE(NULLIF(excluded.publish_time,''),videos.publish_time),
                duration_ms=MAX(excluded.duration_ms,videos.duration_ms),
                digg_count=MAX(excluded.digg_count,videos.digg_count),
                comment_count_expected=MAX(excluded.comment_count_expected,videos.comment_count_expected),
                collect_count=MAX(excluded.collect_count,videos.collect_count),
                share_count=MAX(excluded.share_count,videos.share_count),
                is_pinned=MAX(excluded.is_pinned,videos.is_pinned),
                collected_at=excluded.collected_at
            """,
            (
                aweme_id,
                source_url,
                str(pick(author, "sec_uid", "sec_user_id", default="") or ""),
                str(pick(author, "nickname", "name", default="") or ""),
                str(pick(item, "desc", "description", "title", default="") or ""),
                normalize_time(pick(item, "create_time", "publish_time", default="")),
                as_int(pick(video, "duration", default=pick(item, "duration", default=0))),
                as_int(pick(stats, "digg_count", "like_count", default=0)),
                as_int(pick(stats, "comment_count", default=0)),
                as_int(pick(stats, "collect_count", "favorite_count", default=0)),
                as_int(pick(stats, "share_count", default=0)),
                int(as_bool(pick(item, "is_top", "is_pinned", default=False))),
                utc_now(),
            ),
        )
        self.conn.execute(
            "UPDATE comments SET source_url=? WHERE aweme_id=? AND source_url<>?",
            (source_url, aweme_id, source_url),
        )
        self.conn.commit()
        return aweme_id

    def ensure_video(self, aweme_id: str) -> None:
        if self.get_video(aweme_id) is None:
            self.upsert_video({"aweme_id": aweme_id}, fallback_aweme_id=aweme_id)

    def get_video(self, aweme_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM videos WHERE aweme_id=?", (aweme_id,)).fetchone()

    def upsert_comment(
        self,
        item: Dict[str, Any],
        aweme_id: str,
        reply_level: int = 0,
        root_comment_id: str = "",
        parent_comment_id: str = "",
    ) -> str:
        text = str(pick(item, "text", "content", "comment_text", default="") or "").strip()
        raw_comment_id = str(pick(item, "cid", "comment_id", "id", default="") or "")
        if not raw_comment_id:
            stable = "|".join(
                [aweme_id, root_comment_id, text, str(pick(item, "create_time", default=""))]
            )
            raw_comment_id = "generated_" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]
        user = pick(item, "user", "author", default={})
        user = user if isinstance(user, dict) else {}
        pseudonym, unique_id = self.pseudonymize(user)
        video = self.get_video(aweme_id)
        creator_sec_uid = str(video["creator_sec_user_id"] or "") if video else ""
        source_url = (
            str(video["source_url"] or "")
            if video
            else f"https://www.douyin.com/video/{aweme_id}"
        )
        commenter_sec_uid = str(pick(user, "sec_uid", "sec_user_id", default="") or "")
        is_creator = as_bool(pick(item, "is_author", "is_creator", default=False))
        if creator_sec_uid and commenter_sec_uid and creator_sec_uid == commenter_sec_uid:
            is_creator = True
        root_id = root_comment_id or raw_comment_id
        parent_id = parent_comment_id or str(pick(item, "reply_id", "parent_comment_id", default="") or "")
        evidence_id = f"DY-{aweme_id}-{raw_comment_id}"
        self.conn.execute(
            """
            INSERT INTO comments(
                evidence_id,comment_id,aweme_id,parent_comment_id,root_comment_id,reply_level,
                source_url,source_role,evidence_state,author_pseudonym,author_unique_id,is_creator_reply,
                text,create_time,digg_count,reply_count,ip_label,is_pinned,collected_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(comment_id) DO UPDATE SET
                parent_comment_id=excluded.parent_comment_id,
                root_comment_id=excluded.root_comment_id,
                reply_level=excluded.reply_level,
                source_url=COALESCE(NULLIF(excluded.source_url,''),comments.source_url),
                source_role=excluded.source_role,
                is_creator_reply=excluded.is_creator_reply,
                text=excluded.text,
                create_time=excluded.create_time,
                digg_count=MAX(excluded.digg_count,comments.digg_count),
                reply_count=MAX(excluded.reply_count,comments.reply_count),
                ip_label=COALESCE(NULLIF(excluded.ip_label,''),comments.ip_label),
                is_pinned=MAX(excluded.is_pinned,comments.is_pinned),
                collected_at=excluded.collected_at
            """,
            (
                evidence_id,
                raw_comment_id,
                aweme_id,
                parent_id,
                root_id,
                reply_level,
                source_url,
                "creator_reply" if is_creator else ("viewer_reply" if reply_level else "viewer_comment"),
                "F",
                pseudonym,
                unique_id,
                int(is_creator),
                text,
                normalize_time(pick(item, "create_time", "timestamp", default="")),
                as_int(pick(item, "digg_count", "like_count", default=0)),
                as_int(pick(item, "reply_comment_total", "reply_count", default=0)),
                str(pick(item, "ip_label", "ip_location", default="") or ""),
                int(as_bool(pick(item, "is_top", "is_pinned", default=False))),
                utc_now(),
            ),
        )
        self.conn.commit()
        return raw_comment_id

    def get_progress(self, kind: str, entity_id: str) -> Dict[str, Any]:
        row = self.conn.execute(
            "SELECT cursor,done,meta_json FROM progress WHERE kind=? AND entity_id=?",
            (kind, entity_id),
        ).fetchone()
        if not row:
            return {"cursor": "0", "done": False, "meta": {}}
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        return {"cursor": row["cursor"] or "0", "done": bool(row["done"]), "meta": meta}

    def set_progress(
        self,
        kind: str,
        entity_id: str,
        cursor: Any,
        done: bool,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO progress(kind,entity_id,cursor,done,meta_json,updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(kind,entity_id) DO UPDATE SET
                cursor=excluded.cursor,done=excluded.done,meta_json=excluded.meta_json,updated_at=excluded.updated_at
            """,
            (kind, entity_id, str(cursor), int(done), json.dumps(meta or {}, ensure_ascii=False), utc_now()),
        )
        self.conn.commit()

    def root_comments_with_replies(self, aweme_id: str) -> List[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT comment_id,reply_count FROM comments "
                "WHERE aweme_id=? AND reply_level=0 AND reply_count>0 ORDER BY create_time,comment_id",
                (aweme_id,),
            )
        )

    def count_top_level_comments(self, aweme_id: str) -> int:
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM comments WHERE aweme_id=? AND reply_level=0", (aweme_id,)
            ).fetchone()[0]
        )

    def count_replies(self, aweme_id: str, root_comment_id: str) -> int:
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM comments WHERE aweme_id=? AND reply_level>0 AND root_comment_id=?",
                (aweme_id, root_comment_id),
            ).fetchone()[0]
        )

VIDEO_FIELDS = [
    "aweme_id", "source_url", "creator_sec_user_id", "creator_name", "description",
    "publish_time", "duration_ms", "digg_count", "comment_count_expected", "collect_count",
    "share_count", "is_pinned", "collected_at",
]

COMMENT_FIELDS = [
    "evidence_id", "comment_id", "id_source", "aweme_id", "parent_comment_id", "root_comment_id",
    "reply_level", "source_url", "source_role", "evidence_state", "author_pseudonym",
    "author_unique_id", "is_creator_reply", "text", "create_time", "digg_count",
    "reply_count", "ip_label", "is_pinned", "collected_at",
]

def write_csv(path: Path, rows: Iterable[Dict[str, Any]], fields: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

def export_bundle(
    store: CommentStore,
    out_dir: Path,
    manifest: Dict[str, Any],
    include_replies: bool,
) -> None:
    videos = [dict(row) for row in store.conn.execute("SELECT * FROM videos ORDER BY publish_time DESC,aweme_id")]
    comments = [
        dict(row)
        for row in store.conn.execute(
            "SELECT * FROM comments ORDER BY aweme_id,reply_level,create_time,comment_id"
        )
    ]
    for row in comments:
        row["id_source"] = (
            "dom_fallback"
            if str(row.get("comment_id") or "").startswith("generated_")
            else "platform"
        )
    write_csv(out_dir / "videos.csv", videos, VIDEO_FIELDS)
    write_csv(out_dir / "comments.csv", comments, COMMENT_FIELDS)
    with (out_dir / "comments.jsonl").open("w", encoding="utf-8") as handle:
        for row in comments:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest["finished_at"] = utc_now()
    manifest["videos_exported"] = len(videos)
    manifest["comments_exported"] = len(comments)
    manifest["top_level_comments_exported"] = sum(1 for row in comments if row["reply_level"] == 0)
    manifest["replies_exported"] = sum(1 for row in comments if row["reply_level"] > 0)
    manifest["platform_id_comments_exported"] = sum(
        1 for row in comments if row["id_source"] == "platform"
    )
    manifest["dom_fallback_comments_exported"] = sum(
        1 for row in comments if row["id_source"] == "dom_fallback"
    )
    (out_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_report(store, out_dir / "collection_report.md", manifest, include_replies)

def write_report(
    store: CommentStore,
    path: Path,
    manifest: Dict[str, Any],
    include_replies: bool,
) -> None:
    lines = [
        "# 抖音评论采集报告",
        "",
        f"- 状态：{manifest.get('status', 'unknown')}",
        f"- 数据源：{manifest.get('provider', PROVIDER)}",
        f"- 开始时间：{manifest.get('started_at', '')}",
        f"- 完成时间：{manifest.get('finished_at', '')}",
        f"- API 请求数：{manifest.get('requests_used', 0)} / 预算 {manifest.get('request_budget', 0)}",
        f"- 隐私模式：{manifest.get('privacy_mode', '')}",
        f"- 平台 ID 评论：{manifest.get('platform_id_comments_exported', 0)}",
        f"- 页面兜底评论：{manifest.get('dom_fallback_comments_exported', 0)}",
        "",
        "## 覆盖情况",
        "",
        "| 视频ID | 标题/描述 | 平台显示评论数 | 一级已采集 | 回复已采集 | 平台ID | 页面兜底ID | 完整性 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    videos = list(store.conn.execute("SELECT * FROM videos ORDER BY publish_time DESC,aweme_id"))
    for video in videos:
        aweme_id = str(video["aweme_id"])
        top_count = store.conn.execute(
            "SELECT COUNT(*) FROM comments WHERE aweme_id=? AND reply_level=0", (aweme_id,)
        ).fetchone()[0]
        reply_count = store.conn.execute(
            "SELECT COUNT(*) FROM comments WHERE aweme_id=? AND reply_level>0", (aweme_id,)
        ).fetchone()[0]
        platform_id_count = store.conn.execute(
            "SELECT COUNT(*) FROM comments WHERE aweme_id=? AND comment_id NOT GLOB 'generated_*'",
            (aweme_id,),
        ).fetchone()[0]
        dom_fallback_count = store.conn.execute(
            "SELECT COUNT(*) FROM comments WHERE aweme_id=? AND comment_id GLOB 'generated_*'",
            (aweme_id,),
        ).fetchone()[0]
        p = store.get_progress("comments", aweme_id)
        if not p.get("done"):
            completeness = "未完成，可续跑"
        elif p.get("meta", {}).get("done_reason") == "exhausted":
            completeness = "一级评论分页完成"
        else:
            completeness = f"按{p.get('meta', {}).get('done_reason', '限制')}停止"
        if include_replies:
            pending_replies = 0
            for root in store.root_comments_with_replies(aweme_id):
                rp = store.get_progress("replies", f"{aweme_id}:{root['comment_id']}")
                if not rp.get("done"):
                    pending_replies += 1
            if pending_replies:
                completeness += f"；{pending_replies}个回复楼层未完成"
            else:
                completeness += "；回复任务完成"
        else:
            completeness += "；未采二级回复"
        description = str(video["description"] or "").replace("|", "\\|").replace("\n", " ")[:50]
        lines.append(
            f"| {aweme_id} | {description} | {video['comment_count_expected']} | "
            f"{top_count} | {reply_count} | {platform_id_count} | {dom_fallback_count} | "
            f"{completeness} |"
        )
    lines.extend(
        [
            "",
            "## 口径与限制",
            "",
            "- “全部评论”指采集时点该数据源可分页返回的全部可见评论，不等于平台内部的绝对全量。删除、折叠、风控、地区、登录态和个性化排序都可能造成差异。",
            "- 评论存在本身可标为 F（可观察事实）；评论中声称的购买、体验、身份或效果仍需核验，不能直接当作商品事实。",
            "- 本基础数据包不生成语义标签、D1 证据或达人结论；需要分析时另开分析任务。",
            "- 默认对普通评论者做稳定化名处理；目标达人名称、视频链接和评论 ID 保留用于业务回溯。",
            "- `ID来源=platform` 表示平台评论 ID；`ID来源=dom_fallback` 表示从当前可见评论卡片生成的稳定兜底 ID，回溯强度低于平台 ID。",
            "",
            "## 文件",
            "",
            "- `comments.sqlite3`：断点续跑与去重主库",
            "- `videos.csv`：视频样本账本",
            "- `comments.csv` / `comments.jsonl`：标准化评论与回复",
            "- `run_manifest.json`：采集参数、状态和请求审计摘要",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
