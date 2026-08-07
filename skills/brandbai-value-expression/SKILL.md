---
name: brandbai-value-expression
description: >-
  Translate a current BrandBAI product-value foundation into evidence-linked selling-point perception assets. Use for 卖点可视化、卖点感知化、品牌语言转用户语言、六路卖点翻译、画面动作声音字幕道具协同、详情页现有呈现盘点、VIS感知原子、内容对象调用接口和首轮单变量验证计划. Requires a valid product-value delivery and preserves its product, SKU, facts, P0/P1/P2 and boundaries; does not reselect value, create full scripts, choose creators or claim untested assets are effective.
license: PolyForm-Noncommercial-1.0.0
metadata:
  author: 布兰德老白 BrandBAI
  version: "0.1.0"
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
  --dry-run
```

确认目标目录后去掉`--dry-run`。初始化器校验上游状态、记录版本和文件哈希、继承页面`EX-`表达并创建空白资产；拒绝覆盖非空目录。

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

内部稳定ID使用`VE-`、`PATH-`、`SLOT-01—12`、`VIS-`、`TEST-`和`GAP-`；上游`PV-`、`F-/U-/EX-`、`V-`、`ANCHOR-`与P0决策只继承，不重编号。

## 完成卖点感知化

严格按顺序执行：

1. 核对上游商品、SKU、版本、P0状态和必需文件哈希，冻结价值分层；
2. 盘点上游已登记的页面表达：页面怎么说、怎么拍、用户当前能感知什么、可复用点和缺口；
3. 对每个准备沟通的P0/P1/P2逐项扫描数字化、感官化、差异化、情境化、证据化和人格化；
4. 每个价值选择1条主路径和1—2条辅助路径，未选路径也写本轮不优先/不适用及理由；
5. 扫描01—12十二类感知原子槽位，适用则建立VIS，不适用写清原因，不机械凑满；
6. 每个VIS只服务一个主价值和一个主要用户决策任务，并回指有效事实和页面表达；
7. 每个VIS完整填写画面、动作、声音、字幕、道具五条基础轨；场景、特效/BGM和商品/包装/商品页承接逐项判断；
8. 写明必须保留、可变部分、不建议误用、适用经营对象、验证状态和边界；
9. 选择最多5个核心VIS进入普通版，至少包含推荐P0的一个感知资产；
10. 如有验证条件，最多提出3个单变量建议任务；没有样本和基线时不设虚假阈值；
11. 记录资料缺口、完成状态、失效条件和后续内容组装接口后停止。

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

只有退出码为0才能交付。校验会检查上游一致性、逐价值六路完整性、1主+1—2辅、十二槽位、VIS单一职责、事实引用、五轨与扩展轨、普通版复杂度、验证状态和内部信息泄露。

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
- 按VIS编号、十二槽位或P0/P1/P2顺序直接拼成内容；
- 在业务目标、人群、账号/达人、内容对象和交易承接不齐时生成确定方向、钩子、完整信息链、脚本、达人原话、Brief或动态CTA；
- 伪造样本量、阈值、数据结果、转化归因或成功结论。

完成后把当前有效`expression_manifest.json`、`upstream_snapshot.json`、`vis_ledger.jsonl`、`validation_ledger.jsonl`和`gap_ledger.jsonl`交给后续内容组装或资产回写Skill；下游不得改写上游商品价值和本层资产状态。
