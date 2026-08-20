# TikTok 平台字段

## 跨市场任务上下文

- `business_preset`：`market-scan`、`influence-shortlist`、`creative-benchmark`、`campaign-reception` 或 `shop-affiliate-evidence`；普通下载可留空。
- `market_scope`：用户业务任务指定的国家／地区；没有明确来源时留空，不按语言、IP 或作者外观猜测。
- `source_surface`：`public_tiktok`、`creative_center`、`tiktok_one`、`ads_manager` 或 `seller_center`。
- `source_locale`：页面界面语言或用户明确提供的区域设置。
- `search_query_original`、`search_language`：搜索原词及其语言；多语扩展词作为独立搜索任务，不覆盖原词。
- `observation_timezone`、`observed_at`：观察时区和采集时点。
- `authorization_mode`：`public_visible`、`brand_owned_export` 或 `creator_authorized`。
- `downstream_use`：达人分析、内容诊断、用户语义、商品匹配、投放复盘或增长规划。

公开页面、Creative Center、TikTok One、Ads Manager 和 Seller Center 的字段不得混成同一来源。用户提供官方导出时保留原始来源文件、导出时间和授权范围，再按稳定作品 ID、达人 handle、商品 ID 和时间窗口对齐。

## 作品主键

- `work_id`：来自 `/video/<id>` 或 `/photo/<id>` 的稳定作品 ID。
- `work_type`：`video` 或 `photo`。
- `canonical_url`：`https://www.tiktok.com/@<handle>/<type>/<id>`。
- `author_handle`：含或不含 `@` 均可读取，导出统一不含 `@`。

## 发布内容

- `title`：页面用于列表显示的短标题；没有独立标题时可与发布文案相同，但要保留来源说明。
- `caption`：平台发布文案，不包含自动语音转写。
- `hashtags`、`mentions`：从页面可见文案或正常返回数据中提取。
- `published_at`：优先标准时间；无法精确时保存页面时间原文。

## 互动与素材

- `plays`、`likes`、`comments`、`collects`、`shares`：同时保留原文和可选解析值。
- `cover`、`video`、`audio`、`photo`：每项保留顺序、状态、本地文件、字节数与哈希。
- `audio` 只表示平台提供的可独立下载原声；页面未提供独立地址时写 `not_provided`，不代表 MP4 没有声音。
- 图集顺序从 1 开始；封面不代替图集第一张，也不把视频海报当作已下载视频。
- TikTok 页面媒体可能以 `blob:` 播放，真实下载地址应来自页面正常加载的资源响应，不从 `blob:` 直接拼接。

## 账号与搜索

- 账号：`author_handle`、显示名、简介、关注／粉丝／获赞原文和解析值、规范主页链接。
- 主页选择：可见位次、是否置顶、选择原因、发现时间。
- 搜索快照：关键词、`general|video|photo` 标签页、筛选、原始位次、作品 ID、类型、作者和采集时间。
- 插件／文件选择：选择顺序、来源页面类型、来源关键词、原始位次、作品 ID、规范链接和选择文件合同版本。

## 单作品达人快照

- `nickname`、`platform_account`、`stable_creator_id`、`profile_url`、`bio`、`followers`、`total_likes`、`snapshot_at`、来源作品 ID 和链接。
- 字段只来自当前作品页可见 DOM 或该页正常加载的公开数据；不自动进入主页，也不保存头像。
- 页面没有展示的字段保持空值；明确显示 0 才写数字 `0`。

## 商品关联

作品页出现 TikTok Shop 商品锚点时，首版只保存页面可见商品名称、链接和观察时间，状态为 `visible_product_reference`；不在本 Skill 中下载完整商品详情，也不生成销售归因。

页面明确显示商业内容披露或合作标签时保存 `commercial_disclosure_visible=true` 和页面文字快照；没有显示时写 `not_visible`，不能据此断言不存在商业合作。页面明确出现商品锚点时保存 `product_anchor_visible=true`，订单、GMV、佣金、样品与退款只接受品牌授权后台导出。
