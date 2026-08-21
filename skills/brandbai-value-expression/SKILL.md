---
name: brandbai-value-expression
description: Translate a current BrandBAI product-value foundation into evidence-linked selling-point perception assets. Use for 卖点可视化、卖点感知化、品牌语言转用户语言、六路卖点翻译、画面动作声音字幕道具协同、详情页现有呈现盘点、VIS感知原子、内容对象调用接口和首轮单变量验证计划. Requires a valid product-value delivery and preserves its product, SKU, facts, P0/P1/P2 and boundaries; does not reselect value, create full scripts, choose creators or claim untested assets are effective.
license: PolyForm-Noncommercial-1.0.0
metadata:
  author: 布兰德老白 BrandBAI
  version: "0.1.11"
  category: content-commerce
---

# BrandBAI 卖点呈现

把当前有效商品价值底座中的P0/P1/P2翻译成用户能看见、听见、理解、想象和记住的感知资产。本Skill生成逐价值六路扫描、十二类原子完整性、职责单一的VIS和普通版呈现卡；不重新判断商品价值，也不直接生成内容方向、钩子、脚本或达人策略。

## 先确认许可和上游边界

只在[PolyForm Noncommercial License 1.0.0](references/license.md)允许的非商业范围内运行。企业内部使用、客户交付、收费服务或其他预期商业用途，须先通过`brandlaobai@163.com`取得BrandBAI书面商业授权。

必须读取一个当前有效的`brandbai-product-value`交付目录。商品、SKU、事实、FABE、识别锚、P0决策、P1/P2、不能证明什么和下游准备度全部继承；不得因为某个卖点更好拍、包装更显眼、页面已有素材更多或参数更容易演示而重选P0。

上游为`draft`、`insufficient`、`stale`或`blocked`，P0为重开/替换/停止状态，商品或SKU不明时停止。新增素材出现新事实、跨SKU内容或冲突时，先返回商品价值Skill更新上游。

## 运行要求

宿主需要能读取上游Markdown、JSON和JSONL，并允许在使用者指定的新目录写入Markdown、JSON和JSONL。脚本只使用Python标准库，建议Python 3.10或更高版本。

本Skill设计的是感知呈现资产，不自动生成图片或视频成品。需要生成实际视觉素材时，应在本Skill交付通过后另行调用相应创作工具，并继续继承VIS边界。

## 读取工作合同

每次运行先完整阅读：

- [输入输出合同](references/input-output-contract.md)：确认上游、目录、字段和稳定ID；
- [账本分包合同](references/ledger-writing-contract.md)：把页面表达与逐价值六路拆成可恢复小包，再确定性合并；
- [卖点感知化方法](references/expression-method.md)：完成六路、十二槽位、VIS和多轨；
- [交付合同](references/delivery-contract.md)：生成普通版并判断完成状态。

收到新增页面、用户语言、上游版本变化或真实执行结果时，再阅读[版本与下游交接](references/versioning-and-handoff.md)。

## 初始化交付目录

正式写入前先Dry Run：

```powershell
python scripts/init_value_expression_delivery.py `
  --out "<新的输出目录>" `
  --product-value "<商品价值底座目录>" `
  --source-materials "<可选：当前商品详情页或素材目录>" `
  --output-version "<首次V1；保留旧版后修订用V2、V3……>" `
  --dry-run
```

确认目标目录后去掉`--dry-run`。同一商品价值底座首次输出使用`V1`；保留旧交付并生成修订版时必须显式递增为`V2`、`V3`，不得让两个并存版本复用同一个`output_version`和`value_expression_id`。初始化器校验上游状态、记录版本和文件哈希、继承上游页面`EX-`表达并创建空白资产；拒绝覆盖非空目录。实际检查补充详情页、包装或素材后，把页面怎么说、怎么拍登记为`PEX-`，不能只手工写进普通版。

## 建立结构化资产

按合同完成：

```text
data/expression_manifest.json
data/upstream_snapshot.json
data/existing_expression_ledger.jsonl
data/six_path_ledger.jsonl
data/slot_scan_ledger.jsonl
data/vis_ledger.jsonl
data/validation_ledger.jsonl
data/gap_ledger.jsonl
```

内部稳定ID使用`VE-`、`PEX-`、`PATH-`、`SLOT-01—12`、`VIS-`、`TEST-`和`GAP-`；上游`PV-`、`F-/U-/EX-`、`V-`、`ANCHOR-`与P0决策只继承，不重编号。`PEX-`只记录本轮补充素材中的传播语言与画面形式，不新增商品事实。

模型完成逐价值小包审阅后，优先把页面表达、六路角色、VIS业务键、槽位、验证任务和缺口整理为一个紧凑JSON方案，再用确定性编译器生成稳定ID与六份账本：

```powershell
python scripts/compile_value_expression_plan.py `
  --delivery "<卖点呈现交付目录>" `
  --product-value "<商品价值底座目录>" `
  --plan "<审阅后的紧凑方案.json>" `
  --dry-run
```

Dry Run通过后去掉`--dry-run`。编译器除检查上游价值/事实引用、六路覆盖、01—12槽位、业务键和稳定编号外，还前置拦截高密度字段合并、把页面截图称为原件、面向客户字段泄露内部资产ID，以及验证任务复用无原件依据的“原件”措辞；它仍不替代正式语义校验器。

## 完成卖点感知化

严格按顺序执行：

1. 核对上游商品、SKU、版本、P0状态和必需文件哈希，冻结价值分层；
2. 盘点上游`EX-`和本轮补充商品素材；补充素材使用`PEX-`记录页面怎么说、怎么拍、来源形态、用户当前能感知什么、可复用点和缺口。上游已拆开的SKU、净含量、配料、营养、储存、许可证、标准和警示不得在`PEX-`重新合成一个高密度“大主张”；正文带`*1/※1/注1`等标记时，必须同时保留对应脚注或限定语，并在`boundary`明确其作用范围；
3. 来源较多或账本较大时，按[账本分包合同](references/ledger-writing-contract.md)逐来源写`PEX`小包、逐价值写六路小包；不得等所有判断完成后一次性写完整大账本；
4. 对每个准备沟通的P0/P1/P2逐项扫描数字化、感官化、差异化、情境化、证据化和人格化；
5. 每个价值选择1条主路径和1—2条辅助路径，未选路径也写本轮不优先/不适用及理由；
6. 扫描01—12十二类感知原子槽位，适用则建立VIS，不适用写清原因，不机械凑满；
7. 每个VIS只服务一个主价值和一个主要用户决策任务，并回指有效事实和页面表达；
8. 每个VIS完整填写画面、动作、声音、字幕、道具五条基础轨；场景、特效/BGM和商品/包装/商品页承接逐项判断；
9. 写明必须保留、可变部分、不建议误用、适用经营对象、验证状态和边界；
10. 到手量只能写已确认规格；“整周、几天、一个月”、使用频次、减少补货、一次买够或够用一阵只有在关联上游事实直接出现同类语义时才能写，不得由包数、容量、重量或件数自行换算；上游事实若已声明套组清单、到手件数或装箱内容冲突，必须停止调用并返回商品价值 Skill；
11. 选择最多5个核心VIS进入普通版，至少包含推荐P0的一个感知资产并优先覆盖全部可调用P0/P1；不用同一价值的重复卡挤掉尚未覆盖的P0/P1。P2只有在确实解除当前购买阻力、获得品牌战略输入或用户证据支持时才进入核心卡，环保态度、体系信息、动态权益等不能因为页面显眼或凑满5张而机械入选；一级识别锚不得进入核心卡；
12. 如有验证条件，最多提出3个单变量建议任务；分别写清对照版、测试版、唯一变量、指标获取方式和判断规则。single_variable 必须锁定一个具体变量，不得写“截图A或截图B”等二选一，也不得同时改变字号与节奏、画面与字幕等多个呈现维度。证据画面、固定字幕、验证任务和指标必须回答同一个语义问题；安全性检测不能被用来降低、抵消孕哺禁忌或替代稳定性/失活证据。症状分层、以说明书或医务人员指导为准、禁忌、注意事项、警示和适用边界属于所有版本必须保留的护栏，不得拿“删除/不含/不区分”做实验变量。若唯一变量是证据画面，两版字幕、商品、时长、声音等保持一致；若验证单包构成，两版都必须来自当前SKU真实单包，只改变连续性等单一证明方式；未登记样本量和统计方法时不写“显著性”，只记录方向。数字化字幕中的数量必须与画面实际列出的对象一致，背景场景、工艺步骤和证据卡不得混作同一计数；
13. 对所有正向表达做语义强度复核：来源只列举用途时使用“对应/可用于”，不得升级成“一瓶搞定/解决全部”；图片或页面只能让用户想象气味时，不得写“闻得到/能闻到/香气扑鼻”，除非上游事实有直接嗅觉证据。没有直接支持时改为“看画面，先想象鲜香”等假设语言；
14. 外部品类、竞品、普通款或传统方案的同框、对照、对比只能在关联上游事实存在直接比较证据时进入路径、VIS或验证任务。当前商品的身份、资质或自身事实不能替代外部比较证据；没有比较证据时只展示当前商品与自身身份原文；
15. 记录资料缺口、完成状态、失效条件和后续内容组装接口后停止。

页面已有表达使用`page_existing_unvalidated`，新增设计默认使用`suggested_untested`。页面出现过不等于有效；只有真实内容、直播或页面版本与对应数据、评论、观察窗口和必要对照对位后，才能进入后续资产回写并升级状态。

## 生成普通版

```powershell
python scripts/build_value_expression_report.py --delivery "<输出目录>" --dry-run
python scripts/build_value_expression_report.py --delivery "<输出目录>"
```

普通入口只有：

```text
01_卖点可视化呈现.md
02_资料说明与验证计划.md
```

`01`回答品牌语言如何转成用户语言、核心价值怎样通过多轨协同被感受到、五大作业对象怎样条件式调用和第一轮怎样验证；`02`保留页面盘点、六路扫描、十二槽位、资料缺口和失效规则。普通版隐藏内部ID和本地路径，不把VIS编号当播放顺序。

## 校验正式交付

把`expression_manifest.json`的`analysis_status`更新为`complete`、`partial`、`insufficient`或`stale`，再运行：

```powershell
python scripts/validate_value_expression_delivery.py --delivery "<输出目录>"
```

只有退出码为0才能交付。校验会检查上游一致性、`EX-/PEX-`页面盘点、逐价值六路完整性、1主+1—2辅、十二槽位、VIS单一职责、事实引用、截图与原件边界、未核验精确字段、单包连续证明、嗅觉与“一瓶搞定”语义强度、无证据外部品类/竞品对照、P0/P1核心卡覆盖、五轨与扩展轨、单变量具体性、必要护栏保留、验证任务可观测性、普通版与data同步、复杂度和内部信息泄露。

## 判定完成状态

- `complete`：当前所有可沟通P0/P1/P2完成六路、槽位、VIS、多轨和验证接口；不等于资产已经有效。
- `partial`：已有可用呈现资产，但页面素材、用户语言、业务或执行输入存在重要缺口。
- `insufficient`：无法形成可靠呈现，只输出资料和缺口。
- `stale`：上游商品、SKU、事实或P0变化，旧版停止调用。

## 严格停止在感知原子

本Skill不得：

- 重新选择P0、修改事实或新增平行价值资产；
- 把识别锚、包装、检测、方便、权益或氛围升级为P0；
- 把建议资产、页面已有表达或单次测试写成已验证有效；
- 跨SKU、扩大功效、生成绝对承诺或虚构第一人称体验；
- 把详情页截图称为报告原件，或把上游未核验的单位、限值、编号、日期、标准与认证名称写成精确证据；
- 用预摆样品证明“一包／一袋”的实际内容物，或把留存与评论语义拼成平台无法直接返回的混合指标；
- 把证据画面设为唯一变量时同时改字幕，或在没有样本量和统计检验设计时使用“显著性”判断；
- 只根据包数、容量、重量或件数推导“整周、几天、一个月”、频次、减少补货、一次买够或够用一阵；
- 调用上游已声明冲突的套组清单、到手件数或装箱内容；
- 用安全性检测降低或抵消孕哺禁忌，或用安全检测替代稳定性、活性和失活证据；
- 只有当前商品身份或资质事实，却加入普通款、传统方案、同类或竞品同框对照；
- 把“截图A或截图B”写成一个变量，或同时改变字号与节奏、画面与字幕等多个呈现维度；
- 在任一实验版本中删除症状分层、说明书/医务人员指导、禁忌、注意事项、警示或适用边界；
- 把多个高密度标签字段重新并成一个页面表达，或调用带脚注主张时丢掉对应脚注、限定语与作用范围；
- 把页面真实可见的支架、容器或背景写成“实际不存在”，也不得把页面截图中的可见装置升级为报告原件或线下实物资产；
- 按VIS编号、十二槽位或P0/P1/P2顺序直接拼成内容；
- 在业务目标、人群、账号/达人、内容对象和交易承接不齐时生成确定方向、钩子、完整信息链、脚本、达人原话、Brief或动态CTA；
- 伪造样本量、阈值、数据结果、转化归因或成功结论。

完成后把当前有效`expression_manifest.json`、`upstream_snapshot.json`、`existing_expression_ledger.jsonl`、`vis_ledger.jsonl`、`validation_ledger.jsonl`和`gap_ledger.jsonl`交给后续内容组装或资产回写Skill；下游必须能解析`EX-/PEX-`来源，不得改写上游商品价值和本层资产状态。
