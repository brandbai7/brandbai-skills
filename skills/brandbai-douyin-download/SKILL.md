---
name: brandbai-douyin-download
description: Download public Douyin account, search-result, or explicitly selected works through a visible signed-in Chrome session, including video or image-post media, covers, available audio, release captions, metadata, single-work creator snapshots, and retrievable comments. Use for 抖音达人主页置顶加最近 N 条、搜索结果批量下载、插件作品清单 Excel 接力、任意作品多选、单作品作品包与当前页达人快照、批量一级评论、实验性二级回复、可选 ZIP、DataTool 类普通版导出，以及为后续分析保留可回溯原始数据。默认只完成下载、采集与质量核验，不自动进入达人主页、不下载头像、不生成语义标签或商业结论。
license: PolyForm-Noncommercial-1.0.0
metadata:
  author: 布兰德老白 BrandBAI
  version: "0.4.1"
  category: content-commerce
---

# BrandBAI 抖音批量下载

提供一个类似 DataTool 的抖音下载总入口，把公开抖音账号或明确作品转化为可续跑、可去重、可回溯的作品、媒体和评论数据。本 Skill 的稳定边界是作品与媒体下载、一级评论下载和质量核验；语义分析、影响力对象洞察与商业结论属于后续 Skill。

## 先确认授权范围

只在 [PolyForm Noncommercial License 1.0.0](references/license.md) 允许的非商业范围内运行本 Skill。企业内部使用、客户交付、收费服务、插件、SaaS、数据服务或其他预期商业用途必须先通过 `brandlaobai@163.com` 取得 BrandBAI 书面商业授权。安装源码不等于取得商业试用或平台数据授权。

## 路由下载任务

先把自然语言需求整理为以下四项，再选择运行模式：

1. 下载目标：达人、KOC、KOL、明星艺人等公开账号主页，或一个以上明确作品 URL。
2. 作品范围：单作品、明确作品列表、插件作品清单、搜索页当前选择，或主页全部当前可见置顶作品加最近 N 条非置顶作品。
3. 下载内容：作品清单与基础数据、视频或图文、封面、可用原声、发布文案、一级评论，以及明确要求时的实验性二级回复。
4. 交付预设：普通下载版，或保留全部原始数据和完整性状态的分析准备版。

当前统一入口提供三个运行模式：

- `works`：下载主页所选作品的基础数据、视频或全部图文、封面和可用原声。
- `comments`：下载明确作品或 `works.json` 对应作品的可检索评论。
- `all`：依次完成 `works`、`comments` 和普通版交付。

单作品包会在 `01_作品清单.xlsx` 增加“达人快照”，仅记录当前作品页已经展示或加载的昵称、抖音号、稳定达人 ID、主页链接、简介、粉丝数和累计获赞。页面未展示的字段留空，不补 0；不为补字段自动进入达人主页，也不下载头像。

不要把视频、图文、评论分别拆成不同 Skill；它们共享同一登录资料夹、作品范围、断点状态和交付合同。

当输入来自插件、搜索页或任意多选时，先阅读 [作品选择合同](references/selection-contract.md)。优先使用插件导出的 `作品清单.xlsx` 固定作品 ID；不要重新搜索后假设结果顺序不变。

## 收集必要输入

运行前确认：

1. 账号主页、搜索页、一个以上明确作品 URL，或 BrandBAI 插件导出的作品清单。
2. 选择口径：置顶＋最近 N 条、搜索页当前观察、明确 ID，或选择文件内的作品集合。
3. 独立 Chrome 登录资料夹和新的输出目录。两者不得互相嵌套。
4. 是否只采一级评论。除非用户明确要求实验能力，否则不要开启二级回复。
5. 隐私模式。默认使用稳定化名；只有得到明确授权和合法业务需要时才保留原始评论者名称。
6. 素材范围：`primary`、`cover`、`audio`、`caption` 的任意组合；`caption` 是发布文案，不是口播转写。

## 遵守采集边界

- 只通过用户可见、正常登录的 Chrome 页面访问公开内容。
- 首次登录、验证码或访问确认由用户手动完成。
- 不绕过验证码、访问控制、平台签名、频率限制或登录要求。
- 不导出 Cookie、请求头、浏览器资料夹、验证码信息或签名材料。
- “全部评论”只表示本次页面能够分页返回并收到终止信号的全部可检索评论，不代表平台内部绝对全量。
- 将平台评论 ID 与页面可见卡片生成的兜底 ID 分开记录；兜底 ID 只支持本次数据去重与回溯，证据强度低于平台 ID。
- 将评论文字视为可观察事实；评论中的身份、购买、效果和体验主张仍需另行核验。

首次运行前阅读 [浏览器路线](references/browser-route.md)。验收结果前阅读 [采集完成标准](references/collection-contract.md)。生成普通版交付前阅读 [导出格式](references/export-format.md)。

## 准备本地环境

需要本地 Python 3.10+、Google Chrome、互联网连接和可交互桌面。安装一次浏览器依赖：

```powershell
python -m pip install -r requirements-browser.txt
```

不要把登录资料夹放进 Git 仓库、同步盘、压缩包或客户交付目录。
当前版本自动寻找 Windows 上的 Chrome；macOS 或 Linux 运行时给命令增加 `--chrome-path "<Chrome可执行文件>"`。Windows Chrome 已完成主要路线验证，其他桌面系统需要宿主自行验证。

## 先做 Dry Run

任何正式运行都先加 `--dry-run`，核对达人、N、输出目录和隐私模式。确认后去掉该参数。

### 从插件作品清单继续

当前 Chrome 插件导出的 `作品清单.xlsx` 可直接作为输入，包括达人主页手选和搜索结果手选：

```powershell
python scripts/run_foundation.py all `
  --selection-file "<插件导出的作品清单.xlsx>" `
  --assets "primary,cover,audio,caption" `
  --profile-dir "<私有登录资料夹>" `
  --out "<BrandBAI普通版交付目录>" `
  --zip `
  --dry-run
```

去掉 `--dry-run` 后，Skill 会在同一个可见 Chrome 会话中补齐所选作品的网页元数据，再按同一作品集合采集评论。只需要作品数据与素材时增加 `--skip-comments`；只需要数据时同时使用 `--assets none --skip-comments`。

### 下载明确单作品或作品列表

```powershell
python scripts/run_foundation.py all `
  --video "<作品URL或带 modal_id 的链接>" `
  --video "<另一个视频或图文URL>" `
  --profile-dir "<私有登录资料夹>" `
  --out "<交付目录>" `
  --dry-run
```

当最终作品包只有 1 条时，交付按单作品规则附带“达人快照”；多作品批量不把作者字段拼成达人分析表。

### 下载搜索页当前结果

优先使用插件作品清单。没有清单时可直接观察搜索页，并用 `--limit` 限定当前已加载作品数量：

```powershell
python scripts/run_foundation.py works `
  --source-page "<抖音搜索结果URL>" `
  --limit 20 `
  --assets "primary,cover,audio,caption" `
  --profile-dir "<私有登录资料夹>" `
  --out "<作品输出目录>" `
  --dry-run
```

搜索页结果是本次页面观察快照，不代表平台全部搜索结果。需要固定特定作品时重复使用 `--selected-id`，或改用选择文件。

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

主页默认保持选择规则：全部当前可见置顶作品，加最近 N 条非置顶作品。视频保存最高可用已观察视频、封面、可用原声和发布文案；图文保存全部可用图片、封面、可用原声和发布文案。公开原声不存在时记录 `not_available`，不要伪装成下载失败。

主页发现的滚动预算必须随 N 自动增加；登录等待后若首屏元数据不足，应刷新一次再继续滚动。实际发现的近期非置顶作品少于 N 时，作品任务只能标记为 `partial_selection_shortfall`，不得因为已发现作品均下载成功而写成 `complete`。

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

宿主界面显示“执行超时”不等于采集进程已经失败。先检查输出目录中的 manifest、运行进程和文件更新时间；只要状态仍为 `running` 或文件仍在增长，就等待原任务完成，不得自动重新执行同一任务。只有确认原进程已经结束，且 manifest 为部分完成或失败状态时，才使用同一输出目录续跑。

### 一次完成普通版交付

正式交付优先使用 `all`，它会依次下载作品与素材、采集一级评论并生成两份 Excel：

```powershell
python scripts/run_foundation.py all `
  --creator "<达人主页URL>" `
  --recent 5 `
  --profile-dir "<私有登录资料夹>" `
  --login-wait 180 `
  --comment-login-wait 60 `
  --out "<BrandBAI普通版交付目录>" `
  --dry-run
```

先检查 Dry Run 的作品范围和输出目录，再去掉 `--dry-run` 正式运行。默认只采一级评论；只有用户明确接受实验性完整性边界时才增加 `--include-replies`。

`all` 模式只启动一个可见的持久 Chrome 上下文：作品阶段完成后不关闭浏览器，直接在同一窗口和登录态中进入评论阶段。评论阶段仍复用一个工作标签页；只有页面崩溃或导航中断时才重建标签页。

`--login-wait` 只控制作品主页和首次登录等待；`--comment-login-wait` 控制每条作品的评论面等待，默认 60 秒。不要把作品登录等待时间重复套到每条评论页。

正常完成时，评论阶段保留最后一个工作标签页，由拥有浏览器上下文的统一入口关闭一次整个会话；不得先关闭最后标签页再重复关闭上下文。

### 适配有调用时限的宿主

预计任务可能超过宿主单次调用时限时，使用随 Skill 提供的长任务包装，不要让宿主直接等待 `all`：

```powershell
python scripts/run_long_job.py start `
  --job-dir "<交付目录同级的独立任务目录>" `
  --cwd "<Skill目录>" `
  -- python scripts/run_foundation.py all `
  --creator "<达人主页URL>" `
  --recent 5 `
  --profile-dir "<私有登录资料夹>" `
  --login-wait 180 `
  --comment-login-wait 60 `
  --out "<BrandBAI普通版交付目录>"
```

启动命令会立即返回。后续只轮询同一个任务，不得再次启动：

```powershell
python scripts/run_long_job.py status `
  --job-dir "<同一个独立任务目录>" `
  --tail-lines 30
```

只有 `state=completed` 且 `exit_code=0` 才进入完整验收；`state=partial` 对应退出码 3，必须保留断点；`state=failed` 或 `observed_state=interrupted` 时读取日志和 manifest 后再决定是否续跑。任务目录必须放在交付目录之外，不得随客户包交付。

## 选择交付预设

### 普通下载版

基础交付应包含：

- `01_作品清单.xlsx`
- `02_评论明细.xlsx`
- `03_作品素材/`
- `04_采集说明.md`
- `data/作品采集/` 与 `data/评论采集/`

增加 `--zip` 时，在交付目录同级生成 ZIP64 兼容压缩包；视频、音频、图片和 Excel 不重复高强度压缩。ZIP 只包含交付目录，不得包含登录资料夹、QA 预览或任务目录。

统一入口的 `all` 模式会使用随 Skill 提供的 Python 脚本直接生成两份 Excel，不依赖某个模型宿主内置的电子表格工具。也可在采集完成后单独运行 `scripts/build_foundation_workbooks.py`。生成结构必须遵守 [导出格式](references/export-format.md)。

普通版只呈现作品、素材、评论和采集质量，不添加 D1、语义标签、达人画像、商品匹配或商业结论。

### 分析准备版

需要交给后续 BrandBAI Skill 时，在普通版之外完整保留：

- `works.json` 与 `download_manifest.json`；
- `comments.csv`、`comments.jsonl` 与 `comments.sqlite3`；
- `videos.csv`、`run_manifest.json` 与 `collection_report.md`；
- `browser_session_trace.jsonl` 与 `browser_runtime_trace.jsonl`；
- 作品选择范围、采集时间、隐私模式、评论显示量与实际保存量、分页终止和部分完成原因。

插件或搜索选择同时保留来源页面类型、搜索词、来源排序和选择顺序，供后续账号分析按稳定作品 ID 接力。

分析准备版只保证来源、字段和完成状态可回溯，不在下载阶段填充 D1、SEM、UE、REL、MIG、人设、匹配或归因结论。

## 判定完成状态

- 作品任务只有在每条所选作品的主要素材成功写入，或明确记录为公开不可用时，才能标记 `complete`。
- 一级评论任务只有在每条所选作品都收到一级评论分页终止信号时，才能标记 `complete_source_visible`。
- 平台显示评论数可能同时包含一级评论和其下回复；一级评论中的回复数字段只表示该评论声明的子回复数量，不等于本次实际采集的回复。
- 正数评论上限、动作预算耗尽、页面不可见、登录要求或异常停止都只能标记部分完成。
- 请求二级回复后，只要任一显示有回复的楼层未收到终止信号，整批仍是部分完成。
- 退出码 `3` 表示结果可保留并续跑，但不得对外写“完整下载”。

## 续跑与交付

- 同一目标、同一隐私模式可复用原输出目录；SQLite 和已有素材用于跳过重复数据。
- `all` 中断且作品 manifest 已为 `complete` 时，使用完全相同的达人、N、隐私模式和输出目录并增加 `--resume`；统一入口会校验作品范围、跳过作品下载，并直接续跑评论断点和普通版构建。
- 一级评论进度已是 `done_reason=exhausted` 的作品在续跑时直接跳过页面导航；未完成作品从 SQLite 断点继续。
- 宿主超时后先轮询原任务，不并行启动重复任务；确认原进程已结束后再续跑。
- 目标作品集合或隐私模式改变时新建目录，避免混入上一批结果。
- 普通用户先看 Excel 和素材；`data/` 只用于断点续跑和审计。
- 普通版汇总中的“素材文件”只统计实际写入或确认已存在的文件；`素材明细` 同时保留公开不可用等资产记录。
- 评论页面只显示“1年前”等相对时间时保留页面原文，不伪造绝对日期。
- 不把登录资料夹、QA 预览、运行缓存、Cookie 或任何凭据放进交付包。
- `all` 模式的浏览器阶段轨迹写入 `data/browser_session_trace.jsonl`；评论事件轨迹写入 `data/评论采集/browser_runtime_trace.jsonl`。每次浏览器运行带独立 `session_id`；续跑时按 `session_id` 分组验收，不把上一次被强制中断的会话和本次正常结束事件混成一条会话。轨迹只记录阶段、状态、作品 ID 和数量等审计字段，不记录 Cookie、请求头或签名材料。

## 验证修改

在 `scripts/` 目录运行：

```powershell
python -m unittest test_download_creator_works.py test_browser_collect_comments.py test_run_foundation.py test_run_long_job.py test_build_foundation_workbooks.py
python -m unittest test_selection_contract.py test_package_delivery.py
```

这些测试只使用本地模拟数据，不打开抖音、不启动 Chrome，也不产生付费请求。
