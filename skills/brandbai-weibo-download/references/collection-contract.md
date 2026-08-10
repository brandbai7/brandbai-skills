# 微博采集完成标准

## 通用原则

完成表示“采集时点、当前登录状态、当前可见页面”的范围已经收到明确终止信号，不表示微博平台内部绝对全量。

## 账号主页

- `complete_visible_pinned_plus_recent_n`：所有当前可见置顶均已纳入，且最近 N 条非置顶已选满。
- `partial_selection_shortfall`：滚动后可见非置顶数量仍少于 N。
- `partial_login_or_verification`：登录、验证码或访问确认阻断。
- `partial_selector_drift`：页面结构变化，无法稳定识别账号或微博卡片。

置顶永远不占最近 N 条名额。主页选择先冻结为 `profile_selection.json`，再进入单微博采集。

## 微博字段与素材

- `complete_visible_post`：稳定微博 ID、正文、作者、规范链接和页面可见指标已保存。
- `partial_asset_failure`：博文字段已保存，但至少一项请求素材未保存。
- `failed_no_visible_post`：页面没有可确认的目标微博。

视频播放量、粉丝量和转评赞均为采集时点快照。

## 评论

- `complete_visible_comments_exhausted`：单一页面可见排序收到明确终止信号，或到达真实底部后评论 ID 与页面高度连续稳定。
- `complete_visible_both_sorts_exhausted`：页面同时提供“按热度”和“按时间”，两个排序均满足可见范围终止条件并已按评论 ID 合并。
- `partial_limit_sample`：达到用户指定样本上限。
- `partial_login_required`：当前页面明确要求登录后才能继续显示评论。
- `partial_scroll_budget_exhausted`：达到滚动预算但尚未收到终止信号。
- `partial_sort_not_available`：页面显示了排序入口，但采集时未能激活该排序。
- `partial_reply_not_expanded`：一级评论完成，但可见声明回复未逐条展开。
- `partial_selector_drift`：列表没有终止，且无法用页面底部、评论 ID 稳定或明确终止文字证明完成。

页面显示的总评论量可能包含回复、折叠内容、删除记录或平台内部不可返回记录，不能只按总数判断完整。“全部评论”只表示指定登录状态、页面可见排序与采集时点内，微博页面实际连续返回的全部可见记录，不表示平台绝对全量。

## 转发

- `complete_visible_reposts_exhausted`：转发列表收到页面终止信号或声明转发数已达到。
- `partial_limit_sample`：达到用户指定转发样本上限。
- `partial_reposts_not_available`：页面未提供可读取转发列表。
- `partial_repost_chain_not_expanded`：保存了转发记录，但不能确认完整上游传播链。

## 搜索和话题

- `complete_first_n_visible_results`：冻结指定查询语境的前 N 条真实微博结果。
- `partial_search_shortfall`：页面可见结果不足 N 或滚动预算耗尽。
- 每个快照必须保存查询词、查询类型、排序、筛选、时间和位次。

## 明星超话

- `complete_first_n_visible_supertopic_posts`：指定可见分区已冻结前 N 条微博。
- `partial_supertopic_shortfall`：页面可见微博少于 N，或滚动／增长预算耗尽。
- 每个快照必须保存超话 ID、规范链接、页面指标原文、可见分区、本次分区、采集时间和帖子位次。

## 热搜榜单

- `complete_ranked_hotlist_plus_visible_extras`：数字排名已达到请求名次，并额外保存当前可见置顶和特殊行。
- `partial_hotlist_rank_shortfall`：当前表格可见数字排名少于请求名次。
- 榜单快照必须保存榜单类别、采集时间、页面可见顺序、排名原文、数字排名、词条、热度、标签和词条入口。
- 置顶和特殊行不伪造数字排名；榜单词条不自动解释为一条微博或历史峰值。

## 运行状态

只有所有请求对象均为 `complete*` 才把运行写为 `complete`。任一对象为 `partial*` 或失败时，运行写为 `partial`；退出码 `3` 表示结果可保留和续跑，但不得写成完整下载。
