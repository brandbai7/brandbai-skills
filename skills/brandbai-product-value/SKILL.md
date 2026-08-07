---
name: brandbai-product-value
description: >-
  Build an evidence-backed product value foundation from product links, product pages, product cards, briefs, packaging, manuals, parameter sheets, SKU files, reports, certifications, user feedback or mixed product materials. Use for 商品资料整理、商品事实建账、商品价值分析、P0候选与P0/P1/P2分层、商品表达边界、资料缺口、增量资料合并和下游卖点呈现或达人匹配前置。This Skill stops at product value; it does not create selling-point visuals, content ideas, scripts, creator matching or commercial attribution.
license: PolyForm-Noncommercial-1.0.0
metadata:
  author: 布兰德老白 BrandBAI
  version: "0.1.0"
  category: content-commerce
---

# BrandBAI 商品价值底座

把不同形态的商品资料整理成可回溯的商品事实、完整 FABE 推导、价值候选、P0 决策和表达边界，为卖点呈现、达人匹配、内容诊断及其他内容电商任务提供稳定上游。本 Skill 只完成商品价值建模，不生成 VIS、拍摄方案、内容方向、脚本或达人合作结论。

## 先确认许可、资料与商品边界

只在 [PolyForm Noncommercial License 1.0.0](references/license.md) 允许的非商业范围内运行本 Skill。企业内部使用、客户交付、收费服务或其他预期商业用途，须先通过 `brandlaobai@163.com` 取得 BrandBAI 书面商业授权。

只处理使用者有权提供和分析的资料。不要把客户资料、商品证据原件、账号凭据、个人信息或实际交付结果提交到本仓库。

开始前确认一个具体商品和当前 SKU。多个商品、多个 SKU、不同代际或不同组合分别建账；无法确认当前商品或 SKU 时，只输出资料缺口。

## 运行要求

宿主需要能够读取使用者提供的商品资料，并允许在使用者指定的新目录中写入 Markdown、JSON 和 JSONL。随附脚本只使用 Python 标准库，建议 Python 3.10 或更高版本；宿主无法运行 Python 时，仍可按合同手工建立底稿，但必须保留相同字段、状态和校验边界。

## 读取工作合同

每次运行先阅读：

- [输入输出合同](references/input-output-contract.md)：确认输入、目录和数据字段；
- [商品价值方法](references/value-method.md)：完成事实、利益、候选和价值分层；
- [交付合同](references/delivery-contract.md)：生成普通版并判断完成状态。

收到增量资料、旧版商品价值底座或 P0 争议时，再阅读 [版本与下游交接](references/versioning-and-handoff.md)。

## 路由商品资料

接受商品链接或页面导出、详情页 PDF/图片、商品手卡、包装说明、参数和 SKU 表、检测认证、用户反馈、混合资料或增量补充。宿主无法读取某种格式时，明确能力缺口并请求可读替代格式；链接不可访问时不得声称已读取。

将资料分为：

- `F-PAGE`：当前商品或 SKU 的页面、包装、说明书、官方 FAQ 和品牌手卡中明确的信息；
- `F-EVIDENCE`：检测、认证、报告、专利、研究或凭证中可核对的信息；
- `STRAT`：品牌战略方向、目标用户、创新任务和经营意图；
- `DYN`：价格、券、赠品、库存、物流和活动等动态交易信息；
- `U`：评论、问答、客服或调研中的用户语言、体验、场景和顾虑；
- `EX`：商品页或既有内容中已经存在的表达；
- `H`：分析推导、竞争判断和待验证解释。

`F-PAGE` 是当前商品价值建模的有效事实来源。对品牌或商家公开发布、且与当前商品和 SKU 明确对应的详情页、包装、说明书和官方 FAQ，可直接作为当前公开商品主张使用；缺少第三方报告不构成自动降级或禁用理由。`F-EVIDENCE` 用于增强证据等级，而不是决定商品价值能否存在。只有来源冲突、SKU 不明、页面过期、明显超出资料范围或涉及需要额外审慎判断的医疗与绝对化承诺时，才降级、暂缓或停止。`STRAT` 不得写成用户已认可事实；`U` 不得替代商品事实；`DYN` 必须绑定时间与 SKU。

## 判断资料成熟度

分别记录 `FC0—FC3` 商品事实完整度、`SC0—SC3` 战略信息完整度和 `PKG-L0—PKG-L4` 综合可用程度。事实多不等于战略清楚，战略明确也不能替代商品事实。

只有商品名或模糊描述时标 `FC0`，停止价值定稿并输出缺口。只有简单商品手卡时可以建立初步底座，但不得固定唯一长期 P0 或写成已证明竞争优势。

## 初始化交付目录

任何正式写入先运行 Dry Run：

```powershell
python scripts/init_product_value_delivery.py `
  --out "<新的输出目录>" `
  --brand "<品牌>" `
  --product "<商品名>" `
  --category "<品类>" `
  --sku "<当前SKU或版本>" `
  --input-mode mixed `
  --dry-run
```

确认目标目录后去掉 `--dry-run`。脚本只初始化模板和底稿，不读取商品内容，也不自动得出价值结论。不要覆盖已有交付；重做使用新目录，增量更新按版本合同处理。

## 建立结构化底稿

按合同填充：

```text
data/product_manifest.json
data/source_ledger.jsonl
data/fact_ledger.jsonl
data/fabe_ledger.jsonl
data/anchor_ledger.jsonl
data/value_ledger.jsonl
data/p0_decision.json
data/gap_ledger.jsonl
```

稳定编号使用 `PV-`、`SRC-`、`ID-`、`ANCHOR-`、`F-/STRAT-/DYN-/U-/EX-/H-`、`V-`、`P0D-` 和 `GAP-`。编号只表示稳定资产身份，不表示优先级；不得固定 `V-001 = P0`。

## 完成商品价值建模

严格按以下顺序执行：

1. 确认商品身份、当前 SKU、版本和标准成交单元；
2. 建立来源账本，保留标题、类型、时间、定位和适用 SKU；
3. 穷举当前可确认事实，隔离跨 SKU、历史版本、动态字段和冲突；
4. 为每个准备进入 P0/P1/P2 的价值建立独立 FABE 记录，完整写出 Feature、Advantage、Benefit、Evidence、参照系、用户语言、推导状态和边界；参数不能直接当用户利益；
5. 分离商品身份、一级识别锚、P0 候选、P1、P2 与 DYN；
6. 建立完整 P0 候选池，将品牌指定方向纳入候选但不自动判胜；
7. 分别判断战略价值潜力和当前执行成熟度，不机械合并总分；
8. 形成推荐战略 P0 及状态、当前执行主轴、P1、P2、暂缓价值和表达边界；
9. 写清当前能证明什么、不能证明什么和下一步验证问题；
10. 记录资料缺口、完成状态和下游可用范围后停止。

P0 必须是一个用户价值，不得只写成分、技术名、包装、价格或赠品。可拍性、页面篇幅、识别度、已有呈现或单次内容表现都不能单独决定 P0。

## 生成普通版交付

结构化底稿完成后，先预检、再生成：

```powershell
python scripts/build_product_value_report.py --delivery "<输出目录>" --dry-run
python scripts/build_product_value_report.py --delivery "<输出目录>"
```

普通入口只保留：

```text
01_商品价值底座.md
02_资料说明与缺口.md
```

`01` 回答“这是什么、为什么值得选、凭什么信”，固定展示用户问题、FABE 价值证据链、P0/P1/P2、为什么这样分层和条件式下游接口；`02` 说明资料来源、成熟度、冲突、未知、停止边界和下一步补充。普通版隐藏 `PV-/F-/FABE-/V-` 等内部资产 ID，完整底稿放入 `data/`，供后续 Skill 或审计继续使用。

## 校验正式交付

把 `product_manifest.json` 的 `analysis_status` 更新为 `complete`、`partial`、`insufficient` 或 `stale`，再运行：

```powershell
python scripts/validate_product_value_delivery.py --delivery "<输出目录>"
```

只有退出码为 `0` 才能作为正式交付。校验会检查商品与 SKU、来源和事实引用、稳定 ID、P0 决策、完成状态、资料缺口、普通版占位符和下游边界。

## 判定完成状态

- `complete`：已确认商品与 SKU，完成事实、价值候选、P0 决策、P1/P2、证据边界和资料缺口；P0 可以是明确标注的假设，不代表已被市场验证。
- `partial`：已形成可用价值底座，但事实、战略、证据、用户或竞争资料存在影响使用的缺口。
- `insufficient`：无法确认商品/SKU或没有足够事实形成可靠价值，只输出资料说明与缺口。
- `stale`：新增资料、SKU、证据或战略输入挑战当前版本，旧输出停止下游使用。

完成表示对本次输入完成建模，不表示商品功效、竞争优势、用户心智或成交效果已获得独立验证。

## 严格停止在商品价值

本 Skill 不得：

- 自动把不可访问链接写成已读取；
- 混用不同商品、SKU、历史版本或动态权益；
- 把品牌战略愿望写成用户已认可事实；
- 把评论频次写成商品事实或自动决定 P0；
- 把成分、技术、识别锚、价格或赠品直接写成用户价值；
- 把页面显眼、好拍或已有素材多写成战略优先级；
- 编造添加量、功效、比较结论、绝对承诺或第一人称体验；
- 生成 VIS、卖点呈现卡、拍摄动作、画面、声音、字幕或道具方案；
- 生成选题、钩子、内容方向、完整信息链、脚本或 Brief；
- 判断某个达人是否适合商品或生成达人合作策略；
- 将点击、互动、求链接或自报购买写成成交归因。

完成后把当前有效的 `product_manifest.json`、`fact_ledger.jsonl`、`value_ledger.jsonl` 和 `p0_decision.json` 交给 `brandbai-value-expression` 或后续商品匹配 Skill；下游不得改写上游事实和 P0 决策。
