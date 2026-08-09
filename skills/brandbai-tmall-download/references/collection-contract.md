# 采集完成标准

## 三类独立数据集

- 商品资料：稳定商品 ID、规范链接、标题、店铺、页面参数、SKU 与时点快照，以及每项所选媒体状态。
- 评价：评价／追评 ID、商品 ID、匿名作者、时间、规格、原文、媒体索引和采集状态。
- 问大家：问题 ID、商品 ID、问题原文、声明回答数；回答 ID、匿名作者、标签、回答原文与状态。

商品资料完成不受评价或问答面板影响。`product` 不生成评价和问大家工作簿。

| 数据集 | 完成或部分状态 | 条件 |
| --- | --- | --- |
| 商品 | `complete_observed_product` | 所选公开字段和素材已保存或明确不可用 |
| 商品 | `partial_asset_failure` | 至少一项请求素材失败 |
| 评价 | `partial_requires_full_review_panel` | 用户尚未打开全部评价面板 |
| 评价 | `complete_visible_panel_exhausted` | 当前可见源末端且无折叠提示 |
| 评价 | `partial_platform_folded` | 页面仍提示折叠评价 |
| 问答 | `partial_requires_full_question_panel` | 用户尚未打开全部问答面板 |
| 问答 | `complete_visible_qa_exhausted` | 问题和可见回答滚动到当前源末端 |
| 问答 | `partial_visible_count_below_page_hint` | 保存问题少于页面提示量 |
| 任意 | `partial_limit_sample` | 达到用户设置的正数上限 |
| 任意 | `partial_login_or_verification` | 登录或验证阻断 |
| 任意 | `partial_selector_drift` | 页面结构变化无法定位 |

平台没有公开 ID 时使用 `derived:` 兜底 ID，只支持本批去重与回溯。页面展示量、实际保存量、折叠量、未知和确认的 0 必须分开。

退出码 `0` 表示请求范围完成，`3` 表示结果可保留并续跑但仍是部分数据，`2` 表示输入或执行失败。
