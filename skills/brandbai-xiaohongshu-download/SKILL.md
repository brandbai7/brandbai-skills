---
name: brandbai-xiaohongshu-download
description: Download public Xiaohongshu notes through a visible signed-in Chrome session. Use for 单篇笔记完整资料包与可见评论、账号主页当前可见置顶加最近 N 条列表卡片、关键词搜索前 N 条列表卡片、封面与基础互动数据、普通版 Excel、ZIP，以及为后续账号研究和内容分析保留稳定笔记 ID 与完整性状态。账号主页和搜索批量模式只采当前列表页可见数据，不逐篇进入详情；默认只做下载与质量核验，不自动生成语义标签或商业结论。
license: PolyForm-Noncommercial-1.0.0
metadata:
  author: 布兰德老白 BrandBAI
  version: "0.4.2"
  category: content-commerce
---

# BrandBAI 小红书下载

把公开小红书笔记、账号主页或关键词搜索结果整理为可去重、可回溯的下载包。本 Skill 明确区分“单篇完整下载”和“列表页批量下载”：单篇可以进入详情读取正文、素材和评论；账号主页与搜索批量只读取列表页已经展示的卡片数据和封面，避免逐篇跳转带来的低速与访问风险。

## 先确认授权范围

只在 [PolyForm Noncommercial License 1.0.0](references/license.md) 允许的非商业范围内运行。企业内部使用、客户交付、收费服务、插件、SaaS、数据服务或其他预期商业用途，必须先通过 `brandlaobai@163.com` 取得 BrandBAI 书面商业授权。安装源码不等于取得平台数据授权或商业许可。

## 路由任务

根据来源和交付目标选择模式：

- `note`：明确单篇笔记的正文、指标与所选素材，不采评论。
- `comments`：明确单篇笔记的页面可见评论；回复仅在明确要求时实验采集。
- `all`：明确单篇笔记的完整资料包、评论、Excel 与可选 ZIP。
- `batch`：账号主页或关键词搜索的列表页批量下载；只保存当前列表卡片可见字段、封面、选择位次和上下文，不逐篇进入详情。

输入限制：

- `--note` 只能搭配 `note`、`comments` 或 `all`。
- `--profile`、`--search` 只能搭配 `batch`。
- 不要用账号主页或搜索批量模式承诺正文、全部图片、视频源或评论；这些内容需要用户明确选择单篇后再运行。

## 遵守采集边界

- 只通过用户可见、正常登录的 Chrome 页面访问公开内容。
- 登录、验证码、访问确认或风险提示由用户手动完成。
- 不绕过访问控制、签名、频率限制、登录要求或回复折叠规则。
- 不导出 Cookie、请求头、验证码、浏览器资料夹、账户私密信息、`xsec_token` 或签名材料。
- 搜索“前 N 条”只代表指定关键词、标签页、筛选和采集时点的页面可见顺序。
- “全部评论”只表示本次页面可继续返回并收到终止信号的全部可见评论，不代表平台内部绝对全量。
- 笔记和评论中的身份、购买、功效、体验与商业主张仍需另行核验。

运行前阅读 [浏览器路线](references/browser-route.md)，验收前阅读 [采集完成标准](references/collection-contract.md)，交付前阅读 [导出格式](references/export-format.md)。

## 准备环境

需要 Python 3.10+、Google Chrome、可交互桌面和网络连接：

```powershell
python -m pip install -r requirements-browser.txt
```

私有 Chrome 资料夹必须放在仓库、同步盘和交付目录之外。任何正式采集先增加 `--dry-run` 核对范围，确认后再去掉。

首次运行默认预留 180 秒供用户手动登录或完成访问确认；目标页面一旦可见就立即继续，不再等待完整倒计时。已登录且不希望等待时可显式设置 `--login-wait 0`。

## 常用任务

### 单篇完整资料包

```powershell
python scripts/run_foundation.py all `
  --note "<当前可见笔记完整链接>" `
  --profile-dir "<私有Chrome资料夹>" `
  --out "<交付目录>" `
  --assets "images,cover,video" `
  --comment-limit 0 `
  --zip `
  --dry-run
```

正式执行前从当前可见页面地址栏复制完整链接。临时导航上下文只用于打开页面；输出只保留规范笔记链接。

动态照片或视频若在播放器中显示为 `blob`，允许从同一公开页面的内嵌数据中恢复 `xhscdn.com` 白名单内的 MP4 地址；签名查询参数只用于当前内存下载，Excel、JSON、说明与 ZIP 仍只保留去参数后的来源地址。

### 只下载单篇评论

```powershell
python scripts/run_foundation.py comments `
  --note "<笔记完整链接>" `
  --profile-dir "<同一私有Chrome资料夹>" `
  --out "<交付目录>" `
  --comment-limit 0
```

默认只保存一级评论。只有用户明确接受实验性边界时才增加 `--include-replies`。

### 账号主页列表批量下载

```powershell
python scripts/run_foundation.py batch `
  --profile "<账号主页链接>" `
  --recent 20 `
  --profile-dir "<私有Chrome资料夹>" `
  --out "<交付目录>" `
  --assets "cover" `
  --zip `
  --dry-run
```

选择范围为全部当前可见置顶笔记，加最近 N 条非置顶笔记。置顶是额外项，不占 N。批量交付保存列表卡片的标题、作者、笔记类型、互动快照、封面、位次、选择原因与规范链接；不进入详情页。

### 关键词搜索列表批量下载

```powershell
python scripts/run_foundation.py batch `
  --search "<关键词>" `
  --search-limit 20 `
  --search-tab 全部 `
  --search-filter 综合 `
  --profile-dir "<私有Chrome资料夹>" `
  --out "<交付目录>" `
  --assets "cover" `
  --zip `
  --dry-run
```

搜索批量保存搜索词、标签页、筛选、采集时间和原始可见位次。不要先去重后重排名，也不要把当前页面快照描述为平台全量。

## 普通版交付

按实际请求生成：

- `01_笔记清单.xlsx`
- `02_评论明细.xlsx`：仅明确请求单篇评论时生成
- `03_搜索快照.xlsx`：仅搜索批量时生成
- `04_笔记素材/`
- `05_采集说明.md`
- `data/`：原始记录、选择快照、完成状态和交付 manifest

增加 `--zip` 后在交付目录同级生成 ZIP64 压缩包。ZIP 不得包含登录资料夹、Cookie、任务缓存或 QA 文件。

## 判定完成状态

- 单篇正文和所选主要素材已保存，或明确记录公开不可用：`complete_visible_note`。
- 主页所选列表卡片和封面已保存：`complete_visible_list_cards`；非置顶发现少于 N 时为 `partial_selection_shortfall`。
- 搜索前 N 个可见位次已冻结：`complete_first_n_visible_results`；结果不足或未确认终止时为 `partial_search_shortfall`。
- 评论到达当前页面可见源末端：`complete_visible_panel_exhausted`。
- 回复未完全展开、达到正数上限、登录验证阻断或页面定位变化都只能标记部分完成。
- 退出码 `3` 表示数据可保留和续跑，但不得对外写“完整下载”。

## 续跑与后续分析

同一目标、同一范围和同一隐私模式可使用原输出目录加 `--resume` 续跑。目标、搜索词、筛选或范围改变时新建输出目录。

本 Skill 只下载和整理来源事实。账号深度分析、内容拆解、搜索洞察、用户语义和商业判断应由后续 Skill 读取稳定笔记 ID、搜索快照和完整性状态后完成，不在下载阶段填充结论。

## 验证修改

在 `scripts/` 目录运行：

```powershell
python -m unittest test_collector_core.py test_browser_collect_xiaohongshu.py test_build_delivery.py test_run_foundation.py
```

这些测试只使用合成数据，不打开小红书、不启动 Chrome，也不产生付费请求。
