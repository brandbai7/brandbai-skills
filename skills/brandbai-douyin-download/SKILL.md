---
name: brandbai-douyin-download
description: Download public Douyin account works, video or image-post media, covers, available audio, metadata, and retrievable comments through a visible signed-in Chrome session. Use for 抖音达人、KOC、KOL、明星艺人等主页作品批量下载、全部可见置顶加最近 N 条作品、单作品或批量一级评论下载、二级回复实验采集、DataTool 类普通版导出，以及为后续分析保留可回溯原始数据。默认只完成下载、采集与质量核验，不自动生成语义标签或商业结论。
license: PolyForm-Noncommercial-1.0.0
metadata:
  author: 布兰德老白 BrandBAI
  version: "0.2.0"
  category: content-commerce
---

# BrandBAI 抖音批量下载

提供一个类似 DataTool 的抖音下载总入口，把公开抖音账号或明确作品转化为可续跑、可去重、可回溯的作品、媒体和评论数据。本 Skill 的稳定边界是作品与媒体下载、一级评论下载和质量核验；语义分析、影响力对象洞察与商业结论属于后续 Skill。

## 先确认授权范围

只在 [PolyForm Noncommercial License 1.0.0](references/license.md) 允许的非商业范围内运行本 Skill。企业内部使用、客户交付、收费服务、插件、SaaS、数据服务或其他预期商业用途必须先通过 `brandlaobai@163.com` 取得 BrandBAI 书面商业授权。安装源码不等于取得商业试用或平台数据授权。

## 路由下载任务

先把自然语言需求整理为以下四项，再选择运行模式：

1. 下载目标：达人、KOC、KOL、明星艺人等公开账号主页，或一个以上明确作品 URL。
2. 作品范围：单作品、明确作品列表，或主页全部当前可见置顶作品加最近 N 条非置顶作品。
3. 下载内容：作品清单与基础数据、视频或图文、封面、可用原声、一级评论，以及明确要求时的实验性二级回复。
4. 交付预设：普通下载版，或保留全部原始数据和完整性状态的分析准备版。

当前统一入口提供三个运行模式：

- `works`：下载主页所选作品的基础数据、视频或全部图文、封面和可用原声。
- `comments`：下载明确作品或 `works.json` 对应作品的可检索评论。
- `all`：依次完成 `works`、`comments` 和普通版交付。

不要把视频、图文、评论分别拆成不同 Skill；它们共享同一登录资料夹、作品范围、断点状态和交付合同。

## 收集必要输入

运行前确认：

1. 抖音账号主页 URL，或一个以上明确作品 URL。
2. 最近非置顶作品数量 N；主页全部当前可见置顶作品不计入 N。
3. 独立 Chrome 登录资料夹和新的输出目录。两者不得互相嵌套。
4. 是否只采一级评论。除非用户明确要求实验能力，否则不要开启二级回复。
5. 隐私模式。默认使用稳定化名；只有得到明确授权和合法业务需要时才保留原始评论者名称。

## 遵守采集边界

- 只通过用户可见、正常登录的 Chrome 页面访问公开内容。
- 首次登录、验证码或访问确认由用户手动完成。
- 不绕过验证码、访问控制、平台签名、频率限制或登录要求。
- 不导出 Cookie、请求头、浏览器资料夹、验证码信息或签名材料。
- “全部评论”只表示本次页面能够分页返回并收到终止信号的全部可检索评论，不代表平台内部绝对全量。
- 将评论文字视为可观察事实；评论中的身份、购买、效果和体验主张仍需另行核验。

首次运行前阅读 [浏览器路线](references/browser-route.md)。验收结果前阅读 [采集完成标准](references/collection-contract.md)。生成普通版交付前阅读 [导出格式](references/export-format.md)。

## 准备本地环境

需要本地 Python 3.10+、Google Chrome、互联网连接和可交互桌面。安装一次浏览器依赖：

```powershell
python -m pip install -r requirements-browser.txt
```

不要把登录资料夹放进 Git 仓库、同步盘、压缩包或客户交付目录。
当前版本自动寻找 Windows 上的 Chrome；macOS 或 Linux 运行时给命令增加 `--chrome-path "<Chrome可执行文件>"`。首发版本已在 Windows Chrome 实测，其他桌面系统需要宿主自行验证。

## 先做 Dry Run

任何正式运行都先加 `--dry-run`，核对达人、N、输出目录和隐私模式。确认后去掉该参数。

### 采集主页作品

```powershell
python scripts/run_foundation.py works `
  --creator "<达人主页URL>" `
  --recent 5 `
  --profile-dir "<私有登录资料夹>" `
  --login-wait 180 `
  --out "<作品输出目录>" `
  --dry-run
```

必须保持选择规则：全部当前可见置顶作品，加最近 N 条非置顶作品。视频保存视频、封面和可用原声；图文保存全部可用图片、封面和可用原声。公开原声不存在时记录 `not_available`，不要伪装成下载失败。

### 采集上述作品的一级评论

优先读取作品阶段生成的 `works.json`，避免主页顺序、置顶作品或图文识别不一致：

```powershell
python scripts/run_foundation.py comments `
  --works-json "<作品输出目录>\works.json" `
  --profile-dir "<同一个私有登录资料夹>" `
  --login-wait 60 `
  --out "<评论输出目录>" `
  --dry-run
```

也可重复传入明确作品：

```powershell
python scripts/run_foundation.py comments `
  --video "<视频或图文URL>" `
  --video "<另一个作品URL>" `
  --profile-dir "<私有登录资料夹>" `
  --out "<评论输出目录>"
```

评论任务在一个可见 Chrome 窗口中顺序处理并复用工作标签页；只有页面崩溃或导航中断时才重建标签页并从 SQLite 断点重试。

### 一次完成普通版交付

正式交付优先使用 `all`，它会依次下载作品与素材、采集一级评论并生成两份 Excel：

```powershell
python scripts/run_foundation.py all `
  --creator "<达人主页URL>" `
  --recent 5 `
  --profile-dir "<私有登录资料夹>" `
  --login-wait 180 `
  --out "<BrandBAI普通版交付目录>" `
  --dry-run
```

先检查 Dry Run 的作品范围和输出目录，再去掉 `--dry-run` 正式运行。默认只采一级评论；只有用户明确接受实验性完整性边界时才增加 `--include-replies`。

## 选择交付预设

### 普通下载版

基础交付应包含：

- `01_作品清单.xlsx`
- `02_评论明细.xlsx`
- `03_作品素材/`
- `04_采集说明.md`
- `data/作品采集/` 与 `data/评论采集/`

统一入口的 `all` 模式会使用随 Skill 提供的 Python 脚本直接生成两份 Excel，不依赖某个模型宿主内置的电子表格工具。也可在采集完成后单独运行 `scripts/build_foundation_workbooks.py`。生成结构必须遵守 [导出格式](references/export-format.md)。

普通版只呈现作品、素材、评论和采集质量，不添加 D1、语义标签、达人画像、商品匹配或商业结论。

### 分析准备版

需要交给后续 BrandBAI Skill 时，在普通版之外完整保留：

- `works.json` 与 `download_manifest.json`；
- `comments.csv`、`comments.jsonl` 与 `comments.sqlite3`；
- `videos.csv`、`run_manifest.json` 与 `collection_report.md`；
- 作品选择范围、采集时间、隐私模式、评论显示量与实际保存量、分页终止和部分完成原因。

分析准备版只保证来源、字段和完成状态可回溯，不在下载阶段填充 D1、SEM、UE、REL、MIG、人设、匹配或归因结论。

## 判定完成状态

- 作品任务只有在每条所选作品的主要素材成功写入，或明确记录为公开不可用时，才能标记 `complete`。
- 一级评论任务只有在每条所选作品都收到一级评论分页终止信号时，才能标记 `complete_source_visible`。
- 正数评论上限、动作预算耗尽、页面不可见、登录要求或异常停止都只能标记部分完成。
- 请求二级回复后，只要任一显示有回复的楼层未收到终止信号，整批仍是部分完成。
- 退出码 `3` 表示结果可保留并续跑，但不得对外写“完整下载”。

## 续跑与交付

- 同一目标、同一隐私模式可复用原输出目录；SQLite 和已有素材用于跳过重复数据。
- 目标作品集合或隐私模式改变时新建目录，避免混入上一批结果。
- 普通用户先看 Excel 和素材；`data/` 只用于断点续跑和审计。
- 不把登录资料夹、QA 预览、运行缓存、Cookie 或任何凭据放进交付包。

## 验证修改

在 `scripts/` 目录运行：

```powershell
python -m unittest test_download_creator_works.py test_browser_collect_comments.py test_run_foundation.py test_build_foundation_workbooks.py
```

这些测试只使用本地模拟数据，不打开抖音、不启动 Chrome，也不产生付费请求。
