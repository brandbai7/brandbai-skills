---
name: brandbai-douyin-account-analysis
description: Analyze a qualified Douyin collection package into an evidence-backed account study and D1 comment semantic evidence pack. Use for 抖音达人、KOC、KOL、明星艺人等账号的近期作品基线、置顶作品意图线索、重点作品观察、评论接收、内容—评论语义对齐、注意力归属、高表现候选机制、信任边界和资料缺口分析。默认读取全部当前可见置顶作品加最近最多30条非置顶作品；默认轻量模式无需音频转写、无需第三方上传，不自动下载数据，不进行具体商品匹配或生成商品合作Brief。
license: PolyForm-Noncommercial-1.0.0
metadata:
  author: 布兰德老白 BrandBAI
  version: "0.3.0"
  category: content-commerce
---

# BrandBAI 抖音账号深度分析

把合格的抖音采集包转化为商品无关的账号事实、视频—评论语义对齐和高表现候选机制。本 Skill 只完成账号分析；下载、具体商品匹配、合作策略和商品 Brief 属于其他任务。

## 先确认使用边界

只在 [PolyForm Noncommercial License 1.0.0](references/license.md) 允许的非商业范围内运行本 Skill。企业内部使用、客户交付、收费服务或其他预期商业用途，须先通过 `brandlaobai@163.com` 取得 BrandBAI 书面商业授权。

分析必须使用有合法来源和适当权限的数据。不要把第三方作品、评论、用户信息、客户数据或分析输出提交到本仓库。

## 接收输入

优先读取 `brandbai-douyin-download` 生成的交付目录。也可以读取其他来源，但至少需要：

- 作品 ID、标题、发布时间、真实链接、是否置顶和可见互动数据；
- 至少可读取的作品封面；若宿主能直接读取视频或图文素材，可作为增强证据；
- 能回到具体作品的评论原文和来源角色；
- 采集时间、评论层级、完成状态和异常说明。

先阅读 [输入输出合同](references/input-output-contract.md)。输入不足时只输出资料缺口，不自动调用下载 Skill，也不自动打开抖音补采。

## 固定样本范围

默认纳入：

1. 主页当前可见的全部置顶作品；
2. 置顶之外，按发布时间排序的最近最多 30 条非置顶作品。

置顶不占 30 条非置顶名额。使用非置顶作品建立近期表现基线；单独分析置顶作品代表的身份信号、内容资产或主动展示意图，不把置顶作品混入近期基线。

“处于置顶状态”是 F（可观察事实）；“为什么置顶”没有达人或团队确认时只能标 H（待验证假设）。

重点观察全部置顶作品，再从非置顶样本中选择最多 10 条代表作品，覆盖高、常态、低表现或反例、主要内容类型及存在的商业或异常内容。

## 默认使用轻量无转写模式

默认使用 `lightweight_no_asr`：只依赖采集包内的标题或简介、封面、互动数据和对应评论完成分析，不调用 ChatCut、ASR 或其他第三方转写服务，也不上传媒体。

按实际材料记录观察层级：

- `cover_metadata`：已读取标题或简介、封面和评论，是默认完整路径；
- `sampled_frames`：在默认路径上额外读取了本地抽帧；
- `direct_media`：宿主原生读取了视频或图文素材；
- `text_only`：只读取标题、数据和评论，缺少视觉材料，必须降级为 `partial`。

音频转写不是完成门槛。若输入包已自带合法来源的字幕或转写，可作为补充，但本 Skill 不负责生成，也不得因为缺少转写而停止分析。所有视频表达判断必须限定在实际可见证据内；没有观察到的口播、动作、开头或剧情写“未从本次材料确认”，不要用标题补写。

## 运行输入检查

脚本只使用 Python 3.10+ 标准库。先运行：

```powershell
python scripts/validate_analysis_input.py --input "<抖音采集包目录>"
```

退出码：

- `0`：输入可进入完整分析流程；
- `3`：输入可用但部分缺失，后续必须降级；
- `2`：缺少作品主数据，停止分析。

不要把 `partial` 或 `invalid` 包装成完整输入。

## 构建分析样本

任何正式构建先做 Dry Run：

```powershell
python scripts/build_analysis_dataset.py `
  --input "<抖音采集包目录>" `
  --out "<新的分析输出目录>" `
  --dry-run
```

确认后去掉 `--dry-run`。脚本生成：

```text
data/analysis_manifest.json
data/works_sample.json
data/comment_inventory.json
```

这些是分析准备数据，不是最终账号结论。不得根据脚本的筛选结果自动生成商业判断。

## 初始化交付模板

构建完成后先做 Dry Run：

```powershell
python scripts/init_analysis_delivery.py --out "<分析输出目录>" --dry-run
```

确认后去掉 `--dry-run`。脚本放入三份普通版模板，并创建：

```text
data/delivery_manifest.json
data/video_analysis.jsonl
data/evidence_ledger.jsonl
data/claim_cards.jsonl
```

初始化模板不是正式交付。不要覆盖已有分析；需要重做时使用新的输出目录。

## 建立分类中位数基线

初始化后，先为 `works_sample.json` 中每一条近期非置顶作品填写 `data/work_classification.jsonl`。字段和口径见[交付与中间数据合同](references/delivery-contract.md)。必须把自然、商业、活动和直播预告分开，按用户任务、内容类型和账号阶段建立可比组；置顶作品不进入基线。

正式构建前先做 Dry Run：

```powershell
python scripts/build_account_baseline.py --delivery "<分析输出目录>" --dry-run
python scripts/build_account_baseline.py --delivery "<分析输出目录>"
```

脚本依据原始互动字段计算各可比组的赞、评、藏、转中位数，写入 `data/baseline_ledger.jsonl`。只有一个作品的组会标记为 `conditional`，不能据此形成稳定模式；无播放量时仍不得计算互动率、完播率或播放效率。

## 完成账号分析

阅读 [精简分析方法](references/analysis-method.md)和[交付与中间数据合同](references/delivery-contract.md)，依次完成：

1. 使用非置顶样本建立近期作品基线；
2. 单独理解全部置顶作品及其与近期基线的差异；
3. 按用户任务和内容类型建立同类可比组；
4. 按观察层级重点查看置顶作品和最多 10 条非置顶代表作品；
5. 对应读取评论，按固定规则取样；
6. 按 [评论与证据编码](references/coding-schema.md) 编码；
7. 生成视频—评论语义对齐卡；
8. 检查注意力归属、语义接管、反例和替代解释；
9. 逐视频填写评论采集与停止判断，不把“停止补采”写成“平台全量”；
10. 提炼五类稳定资产：人物判断、内容动作、方法价值、关系资产和商业边界；
11. 形成稳定创作区、可扩展区、偶发机制区和商业高风险区；
12. 输出高表现候选机制、失效条件、完成状态和资料缺口后停止。

默认不做音频转写。标题或简介、封面和评论均已读取时，可以完成轻量模式；只能读取标题和评论、连封面都不可读时标记为部分完成。不得把封面观察写成完整视频剧情，也不得把评论中的观众说法改写为已直接观察到的事实。

把深看结果逐行写入 `video_analysis.jsonl`，把评论原文和编码写入 `evidence_ledger.jsonl`，把评论覆盖与停止判断写入 `comment_collection_ledger.jsonl`，把重要结论写入 `claim_cards.jsonl`，并分别填写 `account_assets.jsonl` 与 `creation_space.jsonl`。三份普通版必须由这些账本生成，不要分别凭印象填写。

## 生成普通版交付

普通入口只保留：

```text
01_账号深度分析.md
02_D1评论语义证据包.xlsx
03_分析说明与资料缺口.md
```

原始分析数据放入 `data/`。重要结论至少保留：判断、F/P/H/U 状态、视频证据、评论证据、对齐等级、反例、替代解释、可用范围和不可用范围。

D1 使用 `assets/02_D1评论语义证据包模板.xlsx` 的四个固定页签。三份 JSONL 和 `delivery_manifest.json` 填写完成后，先预检、再自动生成工作簿：

```powershell
python scripts/build_d1_workbook.py --delivery "<分析输出目录>" --dry-run
python scripts/build_d1_workbook.py --delivery "<分析输出目录>"
```

该脚本只使用 Python 标准库，把视频分析卡、评论证据和结论卡写入初始化时复制的模板，并保留下拉选项和样式。JSONL 始终是事实来源；工作簿只是同一份数据的普通版映射。生成失败时不得交付空模板，也不得手工编造与 JSONL 不一致的表格。

评论语义证据包只描述本次编码样本，不外推完整粉丝比例。S0—S6 是接收深度，不是购买漏斗；求链接、自报购买或自报体验都不能直接证明成交或商品事实。

## 校验正式交付

先把 `delivery_manifest.json` 的 `analysis_status` 从 `draft` 改为 `complete`、`partial` 或 `insufficient`，填写实际深看作品 ID 和资料限制，并运行 `build_d1_workbook.py` 生成 D1。然后运行：

```powershell
python scripts/validate_analysis_delivery.py --delivery "<分析输出目录>"
```

只有退出码为 `0` 才能交付。校验会检查：全部近期非置顶是否已分类并形成可复算的中位数基线、全部置顶是否有分析卡、非置顶深看是否不超过 10 条、评论账本是否覆盖全部深看作品、P 模式是否至少有两个支持作品和评论证据、五类稳定资产与四类创作空间是否齐全、评论编码是否合法、三份普通版是否仍有模板占位符，以及 Excel 与内部证据行数是否一致。

## 判定完成状态

- `complete`：至少按 `cover_metadata` 完成作品基线、置顶作品、代表作品、对应评论、语义对齐和反例检查；无需音频转写。
- `partial`：已形成有效分析，但视觉材料、评论、回复或可比样本存在影响结论的缺口，或代表作品仍为 `text_only`。
- `insufficient`：无法形成至少一个有效可比组，只能输出事实和资料缺口。

完成只表示对本次输入完成分析，不表示平台数据绝对完整，也不表示候选机制已被投放或成交数据验证。

## 严格停止在账号分析

本 Skill 不得：

- 自动下载作品或评论；
- 为了完成默认分析而调用外部音频转写或上传媒体；
- 分析超过最近 30 条非置顶作品；
- 遗漏当前可见置顶作品；
- 将置顶作品直接混入近期非置顶基线；
- 推断完整粉丝画像；
- 将互动、兴趣或自报购买写成成交；
- 判断某个具体商品是否适合达人；
- 生成某个商品的合作策略或 Brief；
- 把单条高表现写成“必爆公式”。
