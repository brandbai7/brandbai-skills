# 采集完成标准

## 范围状态

| 对象 | 完成状态 | 含义 |
| --- | --- | --- |
| 单笔记 | `complete_visible_note` | 页面可见正文、指标和用户请求的主要素材已写入；未请求素材另记 `observed_not_requested` |
| 单笔记 | `partial_asset_failure` | 笔记字段已保存，但至少一项用户请求素材未下载成功或只观察到 `blob:` 播放地址 |
| 账号选择 | `complete_visible_pinned_plus_recent_n` | 全部当前可见置顶和最近 N 条非置顶已冻结 |
| 账号选择 | `partial_selection_shortfall` | 发现的非置顶少于 N，或滚动预算结束仍无法确认 |
| 搜索选择 | `complete_first_n_visible_results` | 指定搜索语境下前 N 个可见位次已冻结 |
| 搜索选择 | `partial_search_shortfall` | 当前页面返回少于 N，或未能确认继续加载终止 |
| 评论 | `complete_visible_panel_exhausted` | 一级评论滚动到当前页面可见源末端 |
| 评论 | `complete_visible_declared_count_reached` | 已观察评论与可见回复记录数达到页面声明总数；未请求保存的回复仍单独写 `not_requested` |
| 评论 | `partial_reply_not_expanded` | 一级评论已保存，但至少一楼声明有回复而未全部展开 |
| 任意 | `partial_limit_sample` | 达到用户设置的正数上限 |
| 任意 | `partial_login_or_verification` | 登录、验证码或访问确认阻断 |
| 任意 | `partial_selector_drift` | 页面结构变化导致关键字段无法定位 |

## 不能混淆的数量

- `declared_comment_count`：笔记页面显示的评论数原文或规范值。
- `saved_first_level_count`：实际保存的一级评论数。
- `declared_reply_count`：某一级评论页面声明的回复数。
- `saved_reply_count`：该楼实际保存的回复数。
- `reply_expansion_status`：`not_applicable`、`not_requested`、`complete`、`partial` 或 `blocked`。

“显示 0”“实际保存 0”“尚未展开”必须是不同状态。

## 退出与交付

运行状态为 `partial` 的数据可以保留、续跑和内部复核，但不得在 `05_采集说明.md` 中写成完整下载。下游分析只能读取明确写入且有稳定 ID 的记录；范围状态为部分完成时必须把样本边界带入分析输入。
