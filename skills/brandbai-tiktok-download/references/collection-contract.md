# 采集完成标准

| 对象 | 完成状态 | 含义 |
| --- | --- | --- |
| 单作品 | `complete_visible_work` | 发布文案、可见指标和用户请求的主要素材已写入，公开不可用项有明确状态 |
| 单作品 | `partial_asset_failure` | 作品字段已保存，但至少一项请求素材下载失败 |
| 主页选择 | `complete_visible_pinned_plus_recent_n` | 全部当前可见置顶和最近 N 条非置顶已冻结 |
| 主页选择 | `partial_selection_shortfall` | 非置顶少于 N，或动作预算结束仍不能确认 |
| 搜索 | `complete_first_n_visible_results` | 指定关键词、标签页和采集时点的前 N 个可见位次已冻结 |
| 搜索 | `partial_search_shortfall` | 当前可见结果少于 N，或未确认继续加载终止 |
| 明确选择 | `complete_explicit_selection` | 插件 Excel／selection JSON 中的去重作品 ID、顺序和来源快照已冻结 |
| 素材 | `partial_asset_unavailable` | 用户请求了素材，但公开页面未提供至少一项可独立下载地址 |
| 一级评论 | `complete_source_visible` | 分页接口或可信页面末端给出终止证据 |
| 一级评论 | `partial_limit_sample` | 达到用户设置的正数上限 |
| 回复 | `partial_reply_not_expanded` | 一级评论已保存，但至少一楼回复未完全展开 |
| 任意 | `partial_login_or_verification` | 登录、验证码、地区或访问确认阻断 |
| 任意 | `partial_selector_drift` | 页面结构变化导致关键字段无法定位 |

## 数量口径

- `declared_comment_count`：页面展示的评论数或接口声明数。
- `saved_first_level_count`：去重后实际保存的一级评论数。
- `declared_reply_count`：一级评论声明的回复数。
- `saved_reply_count`：实际保存的回复数。
- `media_declared_count`：图集／视频记录声明的素材数。
- `media_saved_count`：通过校验并成功写入的素材数。

页面明确显示 0、实际保存 0、没有请求、没有展示和采集失败是五种不同状态。退出码 `3` 的结果可以续跑和内部复核，但不得在对外交付中写成“全部完成”。

独立原声没有地址时写 `not_provided`，不能静默忽略，也不能写成网络下载失败。若同一作品的 MP4 已成功保存，说明视频内嵌声音仍可直接播放检查；素材计数仍按真实请求口径保留缺口，例如 `19/20`。

## 终止证据

以下任一项才可把一级评论标记为 `complete_source_visible`：

- 正常响应明确返回 `has_more=false` 或等价字段；
- 已观察到明确末页游标并成功处理；
- 页面出现可信“没有更多”状态，且连续滚动后数量不再变化。

单纯滚动若干次、评论数暂时不变或达到动作预算，不构成全量证据。
