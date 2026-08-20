# 微博平台字段

## 稳定对象

- 账号：`WBU-<uid>`
- 微博：优先使用页面微博 ID；公共交付显示为 `WBP-<post-id>`
- 评论：平台 ID 可见时使用 `WBC-<comment-id>`，否则使用 `derived:comment:*`
- 转发：平台 ID 可见时使用 `WBR-<repost-id>`，否则使用 `derived:repost:*`
- 搜索或话题快照：`derived:search:*`
- 热搜榜单快照：`derived:hotlist:*`

## 账号字段

`uid`、`display_name`、`verification_text`、`description`、`following_text`、`followers_text`、`posts_text`、`canonical_url`、`collected_at`、`completion_state`。

认证和简介保存页面原文，不自动解释明星等级、机构关系或商务能力。

单微博“达人快照”使用 `nickname`、`platform_account`、`stable_creator_id`、`profile_url`、`bio`、`followers`、`total_likes`、`snapshot_at`、来源微博 ID 和链接。字段仅来自当前详情页已展示或加载的公开信息；不进入主页补齐、不保存头像，未知值留空。

## 微博字段

`post_id`、`author_uid`、`author_name`、`body`、`topics`、`mentions`、`published_at_text`、`region_text`、`source_text`、`post_type`、`metrics`、`original_post_id`、`canonical_url`、选择和搜索语境、`completion_state`。

## 评论字段

`comment_id`、`post_id`、`parent_comment_id`、`root_comment_id`、`level`、`author_id`、`author_display`、`content`、`time_text`、`region_text`、`like_count_text`、`declared_reply_count`、`saved_reply_count`、`reply_expansion_status`。

## 转发字段

`repost_id`、`source_post_id`、`upstream_repost_id`、`author_id`、`author_display`、`content`、`time_text`、`region_text`、`metrics`、`chain_status`。

## 动态指标

粉丝、微博量、浏览、转发、评论、点赞、话题阅读和讨论均保留页面原文与采集时间，不在下载阶段换算、补零或推断真实值。

## 超话字段

`supertopic_id`、`name`、`canonical_url`、`category_text`、`post_count_text`、`member_count_text`、`member_label_text`、`checkin_text`、`rank_text`、`visible_tabs`、`selected_tab`、`captured_at`、`state`。

## 热搜榜单字段

快照保存 `hotlist_snapshot_id`、`category_code`、`category_name`、`canonical_url`、`captured_at`、`requested_ranked`、`saved_ranked`、`saved_extras`、`state`。每行保存 `observed_position`、`rank_text`、`rank_numeric`、`keyword`、`heat_text`、`topic_category_text`、`label_text`、`is_pinned`、`is_special` 和 `query_url`。

数字排名、热度、分类和标签均保留页面原文；置顶或特殊行没有数字排名时使用 `rank_numeric=0`，不能伪造为 Top 1。
