# 采集完成标准

| 对象 | 完成状态 | 含义 |
| --- | --- | --- |
| 单笔记 | `complete_visible_note` | 页面可见正文、指标和用户请求的主要素材已写入 |
| 单笔记 | `partial_asset_failure` | 字段已保存，但至少一项请求素材未成功 |
| 单笔记达人快照 | `current_note_detail` | 仅复用当前笔记详情已展示或加载的公开作者字段，不进入主页补齐 |
| 主页批量 | `complete_visible_list_cards` | 所选主页列表卡片字段与请求封面已写入；未进入详情 |
| 主页选择 | `complete_visible_pinned_plus_recent_n` | 全部当前可见置顶和最近 N 条非置顶已冻结 |
| 主页选择 | `partial_selection_shortfall` | 非置顶少于 N，或预算结束仍无法确认 |
| 搜索批量 | `complete_first_n_visible_results` | 指定搜索语境下前 N 个可见位次已冻结并写入列表字段 |
| 搜索批量 | `partial_search_shortfall` | 当前页面少于 N，或未确认继续加载终止 |
| 评论 | `complete_visible_panel_exhausted` | 一级评论滚动到当前页面可见源末端 |
| 评论 | `partial_reply_not_expanded` | 一级评论已保存，但至少一楼回复未完全展开 |
| 任意 | `partial_limit_sample` | 达到用户设置的正数上限 |
| 任意 | `partial_login_or_verification` | 登录、验证码或访问确认阻断 |
| 任意 | `partial_selector_drift` | 页面结构变化导致关键字段无法定位 |

## 列表与详情不可混淆

- `detail_page_opened=false` 表示主页／搜索批量没有进入详情。
- `field_scope=visible_list_card_only` 表示标题、作者、类型、互动、封面等仅来自列表卡片。
- 批量列表中正文、全部图片、视频源和评论没有采集时，必须留空并写 `not_requested` 或 `not_visible`，不得用封面或标题替代。

## 评论数量

- `declared_comment_count`：页面显示的评论数。
- `saved_first_level_count`：实际保存的一级评论数。
- `declared_reply_count`：某一级评论声明的回复数。
- `saved_reply_count`：实际保存的回复数。

“显示 0”“实际保存 0”“没有请求”“尚未展开”必须是不同状态。运行状态为 `partial` 的数据可以保留、续跑和内部复核，但不得在采集说明中写成完整下载。

单篇“达人快照”通常可稳定保留作者名称、公开稳定 ID 和主页链接；账号号、简介、粉丝或获赞未在当前详情展示时必须留空。不得自动进入作者主页补齐，也不得下载头像。
