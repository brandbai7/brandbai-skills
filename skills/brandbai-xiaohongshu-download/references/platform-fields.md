# 小红书平台字段

## 笔记

必需字段：`note_id`、`canonical_url`、`note_type`、`title`、`body`、`author_id`、`author_name`、`published_at_text`、`region_text`、`topics`、`mentions`、`metrics`、`profile_id`、`profile_rank`、`selection_reason`、`is_pinned`、`collected_at`、`completion_state`。

`note_type` 取值：`image`、`video`、`live_photo`、`unknown`。正文、话题和提及必须分栏；页面只显示编辑时间时保留原文，不伪造发布时间。

## 账号主页选择

`profile_selection_id`、`profile_id`、`canonical_url`、`profile`、`captured_at`、`discovered_count`、`pinned_count`、`recent_requested`、`recent_selected`、`state`、`completion_basis`、`selected`。

`selected` 每项保存 `note_id`、`rank`、`is_pinned`、`selection_reason`、`title`、`author_name`、`canonical_url` 和无查询参数 `cover_url`。`selection_reason` 取 `pinned` 或 `recent_non_pinned`。不得保存页面临时导航链接或令牌。

## 素材

`asset_id`、`note_id`、`kind`、`order`、`source_url`、`local_file`、`width`、`height`、`bytes`、`sha256`、`status`、`error_reason`。

`kind` 取值：`cover`、`image`、`video`、`live_photo_still`、`live_photo_motion`。图文顺序从 1 开始；封面可以与第一张图指向同一源，但必须用独立资产角色表达。

## 搜索快照

`search_snapshot_id`、`keyword`、`tab`、`filters`、`captured_at`、`rank`、`result_note_id`、`result_title`、`result_author`、`promoted_state`、`related_queries`。

搜索结果按快照内位次保存。相同笔记出现在不同关键词或筛选下时，不合并搜索快照关系。

## 评论

`comment_id`、`comment_id_type`、`note_id`、`parent_comment_id`、`root_comment_id`、`level`、`author_id`、`author_display`、`content`、`time_text`、`region_text`、`like_count_text`、`declared_reply_count`、`saved_reply_count`、`reply_expansion_status`、`collected_at`。

页面没有公开评论 ID 时使用 `derived:` 前缀的稳定兜底 ID，并将 `comment_id_type` 写为 `derived`。兜底 ID 只支持本批去重与回溯，证据强度低于平台 ID。
