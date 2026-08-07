---
name: brandbai-xiaohongshu-download
description: Collect public Xiaohongshu notes through a visible signed-in Chrome session, including image-post images in source order, video and cover assets, title, body, topics, account notes, search-result snapshots, and source-visible comments or replies. Use for 小红书单笔记下载、达人或品牌账号全部当前可见置顶加最近 N 条笔记、关键词搜索结果前 N 条批量采集、图文与视频素材下载、评论采集、DataTool 类普通版 Excel 交付，以及为后续用户语义、账号分析或内容诊断保留可回溯原始数据。默认只完成下载、采集与质量核验，不自动生成语义标签、达人结论或商业归因。
license: PolyForm-Noncommercial-1.0.0
metadata:
  author: 布兰德老白 BrandBAI
  version: "0.2.0"
  category: content-commerce
---

# BrandBAI 小红书批量下载

把明确小红书笔记、账号主页或关键词搜索结果转成可去重、可续跑、可回溯的笔记、素材、搜索快照和评论数据。下载阶段只记录页面可见事实与完整性，不替后续分析 Skill 下结论。

## 先确认授权范围

只在 [PolyForm Noncommercial License 1.0.0](references/license.md) 允许的非商业范围内运行。企业内部使用、客户交付、收费服务、插件、SaaS、数据服务或其他预期商业用途，必须先通过 `brandlaobai@163.com` 取得 BrandBAI 书面商业授权。安装源码不等于取得平台数据授权或商业许可。

## 路由任务

先把自然语言需求整理为四项：

1. 目标模式：`note`、`profile`、`search`、`comments` 或 `all`。
2. 明确范围：笔记 URL；账号主页的全部当前可见置顶加最近 N 条非置顶；或关键词、标签页、筛选条件下的前 N 条结果。
3. 下载内容：笔记数据、全部图文、视频、封面、可见评论和回复。
4. 交付预设：普通下载版，或保留搜索语境和完整性 manifest 的分析准备版。

不要把图文、视频、账号主页、搜索结果和评论拆成不同 Skill；它们共享稳定笔记 ID、同一登录资料夹、去重规则和交付合同。

## 遵守采集边界

- 只通过用户可见、正常登录的 Chrome 页面访问公开内容。
- 首次登录、验证码、访问确认或风险提示由用户手动完成。
- 不绕过访问控制、平台签名、频率限制、登录要求或回复折叠规则。
- 不导出 Cookie、请求头、验证码、浏览器资料夹、账户私密信息或签名材料。
- “前 N 条搜索结果”表示指定搜索语境和采集时点页面可见顺序中的前 N 条，不代表平台全量搜索结果。
- “全部评论”只表示本次页面能够继续返回并收到终止信号的全部可见评论；回复未逐楼展开时必须标记部分完成。
- 评论者默认稳定化名；只有得到明确授权和合法业务需要时才保留页面显示名。
- 笔记和评论中的身份、购买、功效、体验与商业主张仍需另行核验。

首次运行前阅读 [浏览器路线](references/browser-route.md)；验收前阅读 [采集完成标准](references/collection-contract.md)；生成交付前阅读 [导出格式](references/export-format.md)；开发适配器时读取 [平台字段](references/platform-fields.md)。

## 安装与首个稳定入口

在本 Skill 目录安装浏览器依赖：

```powershell
python -m pip install -r requirements-browser.txt
```

单笔记先做 Dry Run。优先使用从当前可见笔记页面地址栏复制的完整链接；运行时可以临时使用其中的页面导航上下文，但输出、日志 manifest 和 Excel 只保留规范链接，不保存 `xsec_token`：

```powershell
python scripts/run_foundation.py all `
  --note "<小红书笔记完整链接>" `
  --profile-dir "<独立私有Chrome资料夹>" `
  --out "<交付目录>" `
  --assets "images,cover" `
  --comment-limit 0 `
  --dry-run
```

确认笔记 ID、素材范围、评论上限、隐私模式和输出位置后，去掉 `--dry-run` 真跑。`--comment-limit 0` 表示继续滚动，直到页面出现终止信号或达到声明评论数量；默认只保存一级评论。只有明确需要实验性回复展开时才增加 `--include-replies`。

账号主页先做 Dry Run，默认选择全部当前可见置顶，再额外选择最近 5 条非置顶；`--recent` 可以调整 N：

```powershell
python scripts/run_foundation.py note `
  --profile "<小红书账号主页完整链接>" `
  --recent 5 `
  --profile-dir "<独立私有Chrome资料夹>" `
  --out "<交付目录>" `
  --assets "images,cover" `
  --dry-run
```

确认主页 ID、选择规则和输出位置后去掉 `--dry-run` 真跑。需要同时采集一级评论时把模式由 `note` 改为 `all`。运行会先冻结 `data/profile_selection.json`，再逐条进入已选笔记；断点续跑会重新发现主页以刷新只存在于当前页面的临时导航上下文。

私有 Chrome 资料夹必须和交付目录、仓库分开。首次需要登录或访问确认时可增加 `--login-wait 120`，在可见 Chrome 中由用户手动完成；Skill 不读取或复制现有 Chrome Cookie。

## 首版采集合同

### 单笔记

保存稳定笔记 ID、规范链接、作者、标题、正文、话题、发布时间原文、地区原文、内容类型与指标快照。图文按页面顺序保存每一张图片；视频分别记录视频、封面和可见时长；Live Photo 的静态图与动态资源分开记录，未观察到动态资源时写 `not_observed`。

### 账号主页

选择全部当前可见置顶笔记，再选择置顶之外最近 N 条非置顶笔记。置顶不占 N。滚动后发现数量不足 N 时写 `partial_selection_shortfall`，不能因为已发现笔记均下载成功而标记完整。

### 搜索结果

必须保存：关键词、标签页、筛选条件、采集时间、结果位次、笔记 ID、是否观察到推广标记，以及页面可见的“大家都在搜”等相关查询词。按笔记 ID 去重，但保留同一笔记在不同搜索快照中的不同位次。

### 评论和回复

一级评论与回复分别保存 `comment_id`、`parent_comment_id`、`root_comment_id` 和 `level`。同时记录页面声明回复数、实际保存回复数与回复展开状态，不能用“回复 0”表示尚未展开。

## 普通版交付

统一交付结构：

- `01_笔记清单.xlsx`
- `02_评论明细.xlsx`
- `03_搜索快照.xlsx`
- `04_笔记素材/`
- `05_采集说明.md`
- `data/notes.jsonl`、`comments.jsonl`、`assets.jsonl`、`search_snapshots.jsonl` 与运行 manifest

普通版只呈现笔记、素材、搜索语境、评论和采集质量，不添加用户语义、账号画像、内容机制、商品匹配或商业归因。

## 当前实现阶段

`0.2.0` 保留 `0.1.0` 已真页验证的单笔记能力，并把账号主页“全部当前可见置顶＋最近 N 条非置顶”纳入稳定入口。主页选择会保存账号可见字段、发现数、位次、置顶状态、选择原因、规范链接和选择完整性；页面临时令牌不会进入 JSON、Excel、说明或 GitHub。页面总评论数包含可见回复但本轮未请求回复时，一级评论可以完成，回复必须单独写 `not_requested`，不能伪装成回复 0。

以下仍保持实验或合同状态：

- Live Photo 动态资源和普通视频若页面只暴露 `blob:` 播放地址，记录 `not_observed`，不声明视频文件下载成功。
- `--include-replies` 为实验能力，只有逐楼展开并核对声明回复数后才能标记回复完整。
- 关键词搜索前 N 条已冻结字段与选择合同，但尚未纳入 `run_foundation.py` 稳定入口。
- 仅有不带当前页面导航上下文的规范链接，在未登录新资料夹中可能无法打开；这时应使用当前可见页面复制的完整链接，或先在该私有资料夹中正常登录。

## 验证修改

在 `scripts/` 目录运行：

```powershell
python -m unittest test_collector_core.py test_browser_collect_xiaohongshu.py test_build_delivery.py test_run_foundation.py
```

这些测试只使用合成笔记、搜索快照和评论，不打开小红书、不启动 Chrome，也不产生付费请求。
