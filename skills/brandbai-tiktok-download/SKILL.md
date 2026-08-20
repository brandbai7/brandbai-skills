---
name: brandbai-tiktok-download
description: Download public TikTok videos, photo posts, published captions, media, single-work creator snapshots, creator-profile selections, keyword-search snapshots, BrandBAI plugin work-list selections and visible first-level comments through a visible signed-in Chrome session. Use for TikTok 单作品完整资料包与当前页达人快照、账号主页全部当前可见置顶加最近 N 条非置顶作品、搜索结果前 N 条、插件作品清单续跑、视频或图集素材、封面、可用独立原声、发布文案、基础互动数据、一级评论、Excel 与 ZIP，以及品牌海外市场扫描、达人候选池、竞品内容、官宣接收和 TikTok Shop 联盟内容的原始证据准备；默认只做采集、双语整理和质量说明，不自动进入达人主页、不下载头像、不做语音转写、语义分析、经营指标推算或商业结论。
license: PolyForm-Noncommercial-1.0.0
metadata:
  author: 布兰德老白 BrandBAI
  version: "0.2.3"
  category: content-commerce
---

# BrandBAI TikTok 下载

把 TikTok 单条视频、图集、达人主页和关键词搜索结果整理为可去重、可回溯、可续跑的普通版交付。单作品可保存媒体、发布文案、基础数据和页面可返回的一级评论；主页和搜索批量先冻结选择范围，再逐项下载用户请求的素材。

单作品的 `01_作品清单.xlsx` 会增加“达人快照”，只写当前作品页已展示或加载的公开作者字段。昵称、账号、稳定 ID、主页链接、简介、粉丝数和累计获赞未展示时留空，不补 0；不自动进入达人主页，也不下载头像。

## 先确认授权范围

只在 [PolyForm Noncommercial License 1.0.0](references/license.md) 允许的非商业范围内运行。企业内部使用、客户交付、收费服务、插件、SaaS、数据服务或其他预期商业用途，必须先通过 `brandlaobai@163.com` 取得 BrandBAI 书面商业授权。安装源码不等于取得 TikTok 数据授权或第三方作品版权。

## 路由任务

- `work`：明确单条视频或图集的发布文案、基础数据和所选素材，不采评论。
- `comments`：明确单作品的页面可见一级评论；回复只有在用户明确要求时实验采集。
- `all`：明确单作品或一组作品的素材、数据、一级评论、Excel 与可选 ZIP。
- `batch`：达人主页、关键词搜索或 BrandBAI 插件导出的 `作品清单.xlsx`／`selection/v1` JSON；主页选择全部当前可见置顶加最近 N 条非置顶，搜索冻结指定标签页前 N 个可见结果，选择文件按稳定作品 ID 续跑。

支持的页面路由见 [浏览器路线](references/browser-route.md)。正式运行前阅读 [采集完成标准](references/collection-contract.md)，交付前阅读 [导出格式](references/export-format.md) 与 [平台字段](references/platform-fields.md)。用户要求跨国家内容理解、中英双语文案或评论时，另读 [翻译策略](references/translation-policy.md)。

## 先选品牌业务预设

用户描述的是市场、达人、竞品、官宣或带货问题时，先读 [品牌业务场景路由](references/business-scenarios.md)，再冻结具体下载范围。不要把业务问题直接变成分析结论。

| 预设 | 适用任务 | 默认采集对象 |
|---|---|---|
| `market-scan` | 新市场、类目趋势、关键词内容占位 | 指定市场和语言下的搜索标签页前 N 条 |
| `influence-shortlist` | 达人、KOL、明星合作前评估 | 候选主页全部当前可见置顶加最近 N 条 |
| `creative-benchmark` | 竞品、爆款、Top Ads 链接或创意对标 | 明确作品列表的完整素材和内容事实 |
| `campaign-reception` | 官宣、合作或活动的公开用户接收 | 指定作品的多时点互动快照和一级评论 |
| `shop-affiliate-evidence` | TikTok Shop 达人带货内容研究 | 可购物作品、页面可见商品引用和评论 |

Creative Center、TikTok One、Ads Manager 和 Seller／Affiliate Center 的指标属于官方发现或品牌授权经营数据。用户提供这些导出时保留来源并按作品、达人、商品和时间窗口交接；不得从公开播放、点赞或评论数推算受众、投放或成交结果。

## 免费能力与付费占位

首版免费能力包括：

- 视频 MP4、图集全部图片、封面、页面可用原声；
- 平台发布文案和话题，不把音频识别结果冒充发布文案；
- 播放、点赞、评论、收藏、分享等采集时点快照；
- 单作品一级评论、达人主页批量、搜索普通／视频／照片页批量；
- 断点续跑、去重、Excel、ZIP 和完整性状态。
- 读取 BrandBAI TikTok 插件导出的 `作品清单`，进入作品详情补齐所选素材并保留原始选择快照。

文本翻译不应一概归入付费能力：BrandBAI 下载助手 v0.9.0 在支持的 Chrome 桌面版中，可由用户主动生成发布文案、已采集一级评论和当前可见作品文案的中英双语 Excel。它使用浏览器内置语言识别与本机翻译，默认保留原文并补充中文和英文，不消耗云端字符额度；不支持或失败时不得静默回退到云端计费。

`AI 语音转文案`、画面 OCR、云端翻译回退和大批量加速仍需要推理服务与计量体系。未接入 BrandBAI 服务端前只显示“即将上线”，不得把第三方密钥写入公开插件，也不得静默调用付费接口。

## 遵守采集边界

- 只通过用户可见、正常登录的 Chrome 页面访问公开内容。
- 登录、验证码、访问确认或风险提示由用户手动完成。
- 不读取或导出 Cookie、请求头、浏览器资料夹、验证码、签名参数或访问令牌。
- 不绕过访问控制、签名、频率限制、地区限制或折叠规则。
- 资源链接只作为当次下载线索；带时效签名的 URL 不作为长期证据保存。
- 搜索“前 N 条”只对应指定关键词、标签页、筛选和采集时点的页面可见顺序。
- “全部评论”只表示页面继续返回并收到终止证据的全部可检索一级评论，不代表平台内部绝对全量。

## 准备环境

需要 Python 3.10+、Google Chrome、可交互桌面和网络连接：

```powershell
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
```

Chrome 私有资料夹必须放在仓库、同步盘和交付目录之外。任何正式采集先运行 `--dry-run` 核对范围。

## 常用任务

### 单视频或图集完整资料包

```powershell
python scripts/run_foundation.py all `
  --work "<TikTok 视频或图集完整链接>" `
  --profile-dir "<私有Chrome资料夹>" `
  --out "<交付目录>" `
  --assets "media,cover,audio" `
  --comment-limit 0 `
  --zip `
  --dry-run
```

### 达人主页批量

```powershell
python scripts/run_foundation.py batch `
  --profile "https://www.tiktok.com/@handle" `
  --recent 20 `
  --profile-dir "<私有Chrome资料夹>" `
  --out "<交付目录>" `
  --assets "media,cover" `
  --zip `
  --dry-run
```

置顶作品为额外项，不占最近 N 条非置顶名额。发现不足 N 条时保留 `partial_selection_shortfall`，不把短缺补成 0。

### 关键词搜索批量

```powershell
python scripts/run_foundation.py batch `
  --search "skincare" `
  --search-tab photo `
  --search-limit 20 `
  --profile-dir "<私有Chrome资料夹>" `
  --out "<交付目录>" `
  --assets "media,cover" `
  --zip `
  --dry-run
```

`search-tab` 支持 `general`、`video`、`photo`。照片搜索也可批量，这是本 Skill 相比调研样本工具补足的场景。

### 从 BrandBAI 插件作品清单继续下载

```powershell
python scripts/run_foundation.py batch `
  --selection-file "<BrandBAI_TikTok作品清单_YYYYMMDD.xlsx>" `
  --profile-dir "<私有Chrome资料夹>" `
  --out "<交付目录>" `
  --assets "media,cover,audio" `
  --zip `
  --dry-run
```

选择文件只保存作品 ID、规范链接、页面可见字段和选择范围，不包含 Cookie、请求头或临时签名资源地址。独立原声未提供时保留 `not_provided`，并说明对应 MP4 已保存时仍可播放视频内嵌声音；不得把 19/20 改写成 19/19。

品牌市场扫描时同时冻结业务上下文：

```powershell
python scripts/run_foundation.py batch `
  --search "sensitive skin moisturizer" `
  --search-tab video `
  --search-limit 20 `
  --business-preset market-scan `
  --market-scope US `
  --source-locale en-US `
  --search-language en `
  --observation-timezone America/New_York `
  --downstream-use content-diagnosis `
  --profile-dir "<私有Chrome资料夹>" `
  --out "<交付目录>" `
  --dry-run
```

市场来自用户业务任务，不根据作者语言、IP 或外观自动猜测。多语言关键词分别运行并分别保存原始位次，不能合并后冒充平台排序。

## 普通版交付

按实际请求生成：

- `01_作品清单.xlsx`
- `02_评论明细.xlsx`：仅请求评论时生成
- `03_搜索快照.xlsx`：仅搜索批量时生成
- `04_作品素材/`
- `05_采集说明.md`
- `data/`：原始规范记录、插件／文件选择快照、主页／搜索选择快照、完成状态和交付 manifest

单作品时，`01_作品清单.xlsx` 额外包含“达人快照”；批量模式继续使用“账号信息／主页选择／输入选择”等原有范围，不将单条作者字段扩写为达人画像。

增加 `--zip` 后生成 ZIP64 压缩包。ZIP 不得包含 Chrome 资料夹、Cookie、任务缓存、带时效签名的原始请求或 QA 文件。

## 完成状态与续跑

- 单作品内容与所选主要素材已保存或明确公开不可用：`complete_visible_work`。
- 主页所选作品已冻结并写入：`complete_visible_pinned_plus_recent_n`。
- 搜索前 N 个可见位次已冻结：`complete_first_n_visible_results`。
- 插件 Excel／selection JSON 的作品 ID 与顺序已冻结：`complete_explicit_selection`。
- 用户请求的素材中至少一项公开页面未提供：`partial_asset_unavailable`；与下载失败分开记录。
- 一级评论收到平台分页终止或可信页面末端证据：`complete_source_visible`。
- 达到正数上限、回复未完全展开、登录验证阻断、选择数量不足或页面定位变化，只能标记部分完成。
- 退出码 `3` 表示数据可保留和续跑，但不得对外写“完整下载”。

同一目标、同一范围和同一隐私模式可在原输出目录增加 `--resume`；目标、关键词、搜索标签页或范围改变时新建输出目录。

## 与后续分析分工

本 Skill 只采集和整理来源事实。达人深度分析、用户语义、商品匹配、传播机制与商业判断必须由后续 Skill 读取稳定作品 ID、搜索快照、原文和完整性状态后完成。

## 验证修改

在 `scripts/` 目录运行：

```powershell
python -m unittest test_collector_core.py test_selection_contract.py test_browser_collect_tiktok.py test_build_delivery.py test_run_foundation.py
```

测试只使用合成数据，不打开 TikTok、不启动 Chrome，也不产生付费请求。
