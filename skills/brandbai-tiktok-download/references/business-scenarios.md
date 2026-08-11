# TikTok 品牌业务场景路由

## 先分清三类数据

| 数据层 | 来源 | 本 Skill 的职责 |
|---|---|---|
| 公开内容证据 | TikTok 详情页、主页、搜索页 | 下载、去重、双语整理、完整性说明 |
| 品牌授权经营数据 | Creative Center、TikTok One、Ads Manager、Seller／Affiliate Center | 用户提供导出时保留来源并按稳定 ID 交接；不从公开指标推算 |
| 分析结论 | BrandBAI 后续分析 Skill | 本 Skill 不生成达人匹配、爆款机制、销售归因或策略结论 |

Creative Center 用于趋势和 Top Ads 发现，TikTok One 用于达人筛选与项目报告，Ads Manager 用于 Search Ads 和 Spark Ads，Seller Center 用于联盟合作和成交。公开 TikTok 页面只能回答“当前用户能看到什么”。

## 业务预设

### `market-scan`

用于新市场、品类趋势和关键词内容扫描。

- 冻结 `market_scope`、`source_locale`、原始关键词、搜索语言、标签页、前 N 条、观察时间和时区。
- 分别运行 `general`、`video`、`photo` 时，分别保存搜索快照，不能合并后重排为平台原始名次。
- 交付作品清单、搜索快照、原文与可选中英双语文案。
- 不把一次搜索结果写成长期排名、趋势规模或市场份额。

### `influence-shortlist`

用于达人、KOL、明星或其他影响力对象合作前评估。

- 输入候选主页或插件选择清单。
- 每个主页冻结全部当前可见置顶加最近 N 条非置顶作品。
- 代表作可进入单作品素材和一级评论深采。
- 若用户提供 TikTok One 导出，区分官方达人／受众指标与公开页面快照。
- 交付给 `brandbai-influence-intelligence`；需要商品匹配时再接 `brandbai-product-value` 和 `brandbai-influence-product-fit`。

### `creative-benchmark`

用于竞品、Top Ads 链接、爆款或候选内容的创意证据归档。

- 按明确作品 ID 下载视频／全部图集、封面、可用原声、发布文案、话题和互动快照。
- Top Ads 的官方表现数据只在用户有权访问并提供时接入；不要复制受限制素材或伪造秒级表现。
- 交付给 `brandbai-content-diagnosis` 做结构、表达和母版分析。

### `campaign-reception`

用于官宣、达人合作或活动内容的公开用户接收追踪。

- 冻结活动名、作品 ID、达人、市场、语言和观察时间点。
- 用户可在 T+1、T+3、T+7 主动重复运行，分别保存互动快照和当前可检索一级评论。
- 相同评论去重，但不同时间点的作品指标不得覆盖。
- 有 TikTok One／Ads Manager 报告时，按作品 ID 对齐 Organic、Paid、内容表现和广告指标；没有官方导出时只交付公开证据。
- 交付给用户语义、影响力对象分析或内容诊断；本 Skill 不判断投放增量。

### `shop-affiliate-evidence`

用于 TikTok Shop 达人带货和联盟内容证据。

- 保存作品、发布文案、页面明确可见的商业披露、商品名称、商品链接、商品锚点和观察时间。
- 不从公开页面推断订单、GMV、佣金、退款或归因。
- 用户提供 Seller／Affiliate Center 导出时，按作品、达人、商品和时间窗口交接给商品价值、达人匹配或成交分析 Skill。

## 任务上下文字段

业务型采集至少在 `run_manifest.json` 或采集说明中保留：

- `business_preset`
- `market_scope`
- `source_surface`
- `source_locale`
- `search_query_original`
- `search_language`
- `observation_timezone`
- `observed_at`
- `authorization_mode`
- `downstream_use`

`source_surface` 使用 `public_tiktok`、`creative_center`、`tiktok_one`、`ads_manager` 或 `seller_center`。`authorization_mode` 使用 `public_visible`、`brand_owned_export` 或 `creator_authorized`。地区必须来自用户任务或授权数据，不根据语言、IP 或外观猜测。

## 能力边界

- 当前稳定范围：单视频／图集、主页置顶加最近 N 条、搜索综合／视频／照片前 N 条、媒体、发布文案、公开互动快照、可检索一级评论、原文保留的中英双语证据、Excel、ZIP、去重、续跑和完整性状态。
- 实验范围：二级回复。
- 后续付费范围：语音转写、语音翻译、OCR、云端翻译回退和大批量加速。
- 需要品牌授权导出的范围：TikTok One 受众与项目报告、Ads Manager Search Terms／Spark Ads／投放指标、Seller Center 合作／订单／GMV／佣金。

## 官方参考

- [Creative Center](https://ads.tiktok.com/help/article/creative-center)
- [TikTok One 达人发现](https://ads.tiktok.com/help/article/how-to-find-creators-who-work-with-tiktok-one?redirected=2)
- [TikTok One 项目报告](https://ads.tiktok.com/help/article/about-tiktok-one-campaign-reporting?lang=en)
- [Search Ads](https://ads.tiktok.com/help/article/how-to-set-up-a-search-ads-campaign-in-tiktok-ads-manager)
- [Spark Ads](https://ads.tiktok.com/help/article/spark-ads-creation-guide/)
- [TikTok Shop Affiliate](https://seller-us.tiktok.com/university/essay?from=feature_guide&identity=1&knowledge_id=6837873164896001&role=1&shop_region=US)
