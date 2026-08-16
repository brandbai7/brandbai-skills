---
name: brandbai-weibo-download
description: Collect public Weibo accounts, individual posts, profile posts, keyword or hashtag search results, supertopic posts, hot-search ranking snapshots, source-visible comments, comment replies, repost propagation records, images, video and interaction snapshots through a visible signed-in Chrome session. Use for 微博明星主页采集、品牌或明星账号全部当前可见置顶加最近 N 条微博、单条微博下载、明星代言与品牌事件关键词搜索、普通话题与明星超话留证、热搜主榜或文娱榜快照、评论与转发扩散采集、DataTool 类普通版 Excel 与 ZIP 交付，以及为后续明星营销、舆情传播或账号分析保留可回溯原始数据。默认只完成下载、结构化与完整性说明，不自动生成明星口碑、粉丝质量、代言效果、情感标签或商业归因。
license: PolyForm-Noncommercial-1.0.0
metadata:
  author: 布兰德老白 BrandBAI
  version: "0.1.3"
  category: content-commerce
---

# BrandBAI 微博明星营销资料下载

把明确微博、明星或品牌主页、关键词和话题页转成可去重、可续跑、可回溯的账号、博文、素材、评论、回复、转发和搜索快照。下载阶段只记录页面可见事实与完成状态，不替后续分析 Skill 下结论。

## 先确认授权范围

只在 [PolyForm Noncommercial License 1.0.0](references/license.md) 允许的非商业范围内运行。企业内部使用、客户交付、收费服务、插件、SaaS、数据服务或其他预期商业用途，必须先通过 `brandlaobai@163.com` 取得 BrandBAI 书面商业授权。安装源码不等于取得微博数据授权、明星肖像授权、内容版权或商业许可。

## 路由任务

先把自然语言需求整理为五项：

1. 目标入口：明确微博 `post`、账号 `profile`、关键词 `search`、普通话题 `topic`、明星超话 `supertopic` 或榜单 `hotlist`。
2. 选择范围：一个或多个微博链接；全部当前可见置顶加最近 N 条非置顶；或指定查询语境的前 N 条结果。
3. 互动范围：不采集、一级评论、实验性评论回复、转发扩散记录。
4. 素材范围：图片、视频、封面或不下载素材。
5. 交付预设：普通下载版，或保留搜索、话题和传播关系的分析准备版。

运行模式：

- `posts`：账号、微博字段和所选素材。
- `comments`：微博字段、一级评论和可选回复。
- `reposts`：微博字段和页面可见转发扩散记录。
- `all`：账号、微博、素材、评论、转发、搜索或话题快照一次完成。

热搜榜单只做榜单快照，使用 `posts --hotlist`；它不会自动把榜单词条当成一条微博。需要查看某个榜单词条的内容供给时，再以该词条运行 `--topic` 或 `--search`。

不要把评论和转发合并成一种互动。评论用于观察用户接收，转发用于观察传播扩散，两者必须保留独立稳定 ID、原文和完成状态。

## 遵守采集边界

- 只通过用户可见、正常登录的 Chrome 页面访问公开内容。
- 首次登录、验证码、访问确认或风险提示由用户手动完成。
- 不绕过访问控制、平台签名、频率限制、登录要求、内容可见范围或折叠规则。
- 不导出 Cookie、请求头、验证码、浏览器资料夹、账户私密信息、手机号、登录二维码或签名材料。
- 账号主页与搜索结果只对应本次采集时点页面可见顺序，不代表平台内部绝对全量。
- “全部评论”或“全部转发”只表示本次页面能够继续返回并收到终止信号的全部可见记录。
- 评论者和转发者默认使用稳定化名；只有得到明确授权和合法业务需要时才保留页面显示名。
- 地区、认证、粉丝身份、购买、体验、评价和商业关系均为页面显示或用户表达，下载成功不等于事实核验完成。
- 不把点赞、评论、转发、热搜或粉丝量直接写成代言效果、销售转化或品牌资产归因。

明星营销任务先阅读 [明星营销采集场景矩阵](references/celebrity-marketing-scenarios.md)；首次运行前阅读 [浏览器路线](references/browser-route.md)；验收前阅读 [采集完成标准](references/collection-contract.md)；生成交付前阅读 [导出格式](references/export-format.md)；开发适配器时读取 [平台字段](references/platform-fields.md)。

## 准备环境

需要 Python 3.10+、Google Chrome、可交互桌面和网络连接：

```powershell
python -m pip install -r requirements-browser.txt
```

正式采集使用独立私有 Chrome 资料夹。资料夹必须放在仓库、同步盘和交付目录之外；第一次运行时增加 `--login-wait 180`，在可见 Chrome 中手动完成微博登录。

## 先做 Dry Run

单微博：

```powershell
python scripts/run_foundation.py all `
  --post "<微博完整链接>" `
  --profile-dir "<独立私有Chrome资料夹>" `
  --out "<BrandBAI普通版交付目录>" `
  --assets "images,video,cover" `
  --comment-limit 0 `
  --repost-limit 0 `
  --zip `
  --dry-run
```

明星主页默认选择全部当前可见置顶，再额外选择最近 5 条非置顶：

```powershell
python scripts/run_foundation.py all `
  --profile "<微博数字UID或 /u/数字UID 主页链接>" `
  --recent 5 `
  --profile-dir "<独立私有Chrome资料夹>" `
  --out "<交付目录>" `
  --assets "images,video,cover" `
  --dry-run
```

关键词或明星代言事件搜索：

```powershell
python scripts/run_foundation.py all `
  --search "明星名 品牌名" `
  --search-limit 5 `
  --profile-dir "<独立私有Chrome资料夹>" `
  --out "<交付目录>" `
  --assets "images,cover" `
  --dry-run
```

话题入口使用不带井号或带井号的主题词均可：

```powershell
python scripts/run_foundation.py all `
  --topic "明星代言活动" `
  --search-limit 5 `
  --profile-dir "<独立私有Chrome资料夹>" `
  --out "<交付目录>" `
  --assets "images,cover" `
  --dry-run
```

明星超话可选择页面可见的热门、最新或精华分区：

```powershell
python scripts/run_foundation.py posts `
  --supertopic "<weibo.com/p/100808.../super_index 链接>" `
  --supertopic-tab "最新" `
  --search-limit 5 `
  --profile-dir "<独立私有Chrome资料夹>" `
  --out "<交付目录>" `
  --assets "images,cover" `
  --dry-run
```

热搜主榜或文娱榜保存数字排名，并把当前可见置顶／特殊行作为额外记录：

```powershell
python scripts/run_foundation.py posts `
  --hotlist "文娱" `
  --hotlist-limit 50 `
  --profile-dir "<独立私有Chrome资料夹>" `
  --out "<交付目录>" `
  --assets "none" `
  --zip `
  --dry-run
```

核对稳定 ID、选择范围、评论和转发上限、隐私模式、素材与输出位置后去掉 `--dry-run`。`--comment-limit 0` 和 `--repost-limit 0` 表示继续滚动，直到可见列表终止或达到页面声明数量。

## 首版采集合同

### 账号与主页选择

保存账号 UID、规范主页链接、名称、认证原文、简介、关注／粉丝／微博数量原文和采集时点。选择全部当前可见置顶微博，再选择置顶之外最近 N 条非置顶微博；置顶不占 N。数量不足时写 `partial_selection_shortfall`。

### 微博

保存微博 ID、规范链接、作者 UID、正文、原微博关系、话题、@对象、发布时间原文、发布地原文、来源、内容类型、浏览／转发／评论／点赞快照和素材状态。动态指标只代表采集时点。

### 评论与回复

一级评论与回复分别保存 `comment_id`、`parent_comment_id`、`root_comment_id` 和 `level`。同时记录页面声明回复数、实际保存回复数与展开状态，不能用“回复 0”表示未展开。

评论页存在“按热度”和“按时间”时，分别滚动到真实页面底部并采集，按评论 ID 合并去重，同时保留观察排序、各排序首次位次、终止依据和断点续跑总集。仅当到达底部后评论 ID 与页面高度连续稳定，或页面出现明确终止标记，才能把对应排序写成完成；连续数屏没有新增但尚未到底时必须继续。

### 转发扩散

单独保存转发 ID、源微博 ID、转发用户稳定 ID、转发文案、发布时间原文、地区原文、互动快照与可见上游关系。页面没有返回完整转发链时保留 `partial_reposts_not_available` 或 `partial_repost_chain_not_expanded`。

### 搜索、话题、超话与榜单

保存查询词、查询类型、采集时间、页面可见排序／筛选、结果位次、微博 ID、账号 UID、推广标记和话题上下文。结果按微博 ID 去重，但保留同一微博在不同快照中的不同位次。

超话额外保存超话 ID、名称、分类、帖子数、成员数、今日签到、排行、页面可见分区和本次采集分区。热搜榜单额外保存榜单类别、页面可见顺序、排名原文、数字排名、词条、热度、分类、标签、置顶／特殊行标记和词条入口。所有数字均为采集时点原文。

## 普通版交付

- `01_账号资料.xlsx`
- `02_微博清单.xlsx`
- `03_评论明细.xlsx`
- `04_转发扩散.xlsx`
- `05_搜索与话题快照.xlsx`
- `06_微博素材/`
- `07_采集说明.md`
- `data/accounts.jsonl`、`posts.jsonl`、`comments.jsonl`、`reposts.jsonl`、`assets.jsonl`、`search_snapshots.jsonl`、`hotlist_snapshots.jsonl` 与运行 manifest

普通版只呈现账号、微博、互动、素材、搜索语境和采集质量，不添加明星口碑、粉丝画像、舆情倾向、传播机制、代言匹配或商业归因。

## 当前实现阶段

`0.1.3` 在既有单微博、账号主页、关键词、普通话题、超话与热搜能力上，增加多任务项目计划、同一可见 Chrome 会话顺序执行、断点恢复、合并交付、本地合成压力测试和低频真实页面耐久测试；同时缩短隐藏回复控件造成的等待，并支持登录恢复。完整转发链、平台不返回的评论与回复、超话成员关系、热搜历史峰值、长图 OCR、视频语音转写和商业效果分析不属于稳定承诺。

## 验证修改

在 `scripts/` 目录运行：

```powershell
python -B -m unittest test_collector_core.py test_project_plan.py test_project_runner.py test_project_delivery.py test_browser_collect_weibo.py test_build_delivery.py test_package_delivery.py test_run_foundation.py test_stress_test_local.py test_live_resilience_test.py
```

这些测试只使用合成账号、微博、评论、转发和搜索快照，不打开微博、不启动 Chrome，也不产生付费请求。

需要验证多任务合并、较大评论／转发集合、素材打包、SHA-256 和断点恢复时，运行本地合成压力测试：

```powershell
python stress_test_local.py --preset standard --report "<结果文件.json>"
```

`quick`、`standard` 和 `full` 依次提高项目数、互动记录数与合成素材体积。该脚本不访问微博，不能代替低频真实页面耐久测试；发布时必须分别报告自动化回归、本地压力结果、真实页面验收和仍未完成的项目。
