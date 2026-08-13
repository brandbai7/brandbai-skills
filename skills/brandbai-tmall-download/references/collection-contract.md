# 采集完成标准

## 三类独立数据集

- 商品资料：稳定商品 ID、规范链接、标题、店铺、页面参数、SKU 与时点快照，以及参数、主图、图文详情、视频四个模块各自的状态。
- 评价：评价／追评 ID、商品 ID、匿名作者、时间、规格、原文、媒体索引和采集状态。
- 问大家：问题 ID、商品 ID、问题原文、声明回答数；回答 ID、匿名作者、标签、回答原文与状态。

商品资料完成不受评价或问答面板影响。`product` 不生成评价和问大家工作簿。

| 数据集 | 完成或部分状态 | 条件 |
| --- | --- | --- |
| 商品 | `complete_observed_product` | 所选公开字段和实际观察到的所选素材已保存，详情请求已读到有效详情图 |
| 商品 | `partial_product_identity` | 页面存在 SKU ID，但没有观察到与之对应的页面选中规格；保留已知字段，不宣称 SKU 已映射 |
| 商品 | `partial_asset_failure` | 至少一项请求素材失败 |
| 商品 | `partial_detail_images_not_observed` | 已请求详情素材但页面未观察到有效详情图，不能标记完整 |
| 商品 | `partial_detail_scroll_not_restored` | 已观察到详情素材，但受控加载结束后没有恢复进入前的位置，不能标记完整 |
| 商品详情模块 | `detail_module_observed` | 已从“图文详情”模块根节点观察到有效详情图；允许模块边界内有限加载，不依赖整页滚动 |
| 商品模块 | `observed` | 当前模块已定位且观察到合格字段或素材 |
| 商品模块 | `partial`／`not_observed`／`failed` | 当前模块不完整；其他模块成果仍保留并继续合并 |
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

商品价格与优惠权益必须分开：礼金、优惠券、红包、自动扣减补贴额不得进入商品价格快照；页面下方推荐商品的价格不得归到当前商品。商品参数、主图、图文详情和视频必须按模块独立读取并记录状态，不得以一次整页滚动替代模块边界。图片文件名扩展名以响应 `Content-Type` 为准；1500×2 等分隔条和同一阿里图片的派生压缩版本不得重复计入有效素材。

当前选中规格与页面通用参数必须分开：默认标记页面参数是否适用于当前 SKU 为未确认。只有色号代码、同单位数量／重量或产品形态的明确不一致进入冲突候选；候选只提示人工确认，不自动覆盖任何来源。普通页面操作、会员权益、领券、加购、客服和跨品类入口不得进入 SKU 选项。

素材同时保存 `page_order` 与 `download_order`。前者保留页面观察到的原序，可跳号；后者表示本包实际成功下载的连续顺序。详情图片区分 `content_image`、`separator_candidate`、`low_information_candidate` 与 `excluded_quality`，不能用一个“详情图数量”替代这些状态。

商品包同时输出 `material_status` 与 `commerce_snapshot_status`。内容资料完整不等于价格、销量、榜单等经营快照完整；页面未提供可选主图视频不降低内容资料状态。

图文详情懒加载只允许在详情模块范围内有限前进：每一步重新计算模块底部和推荐区边界，最远位置不得超过两者中的较早者；无论成功、缺失或异常都恢复进入前的位置，并保存加载步数与恢复状态。不得使用 `document.body.scrollHeight` 作为详情边界。

SKU 映射使用五态合同：`selected_sku_mapped`、`sku_id_unmapped`、`visible_selection_without_sku_id`、`visible_options_no_selection`、`not_observed`。只有 `selected_sku_mapped` 表示页面同时观察到 SKU ID 和可见选中规格；其他状态不得推断二者对应关系。

退出码 `0` 表示请求范围完成，`3` 表示结果可保留并续跑但仍是部分数据，`2` 表示输入或执行失败。
