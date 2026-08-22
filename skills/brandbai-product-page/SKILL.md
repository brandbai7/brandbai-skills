---
name: brandbai-product-page
description: Diagnose and optimize one ecommerce product page from readable main images, transaction-area information and detail-page materials. Use for 商品页诊断、详情页优化、主图顺序、SKU选择、证据边界、页面改版优先级，以及在补充商品资料后形成更完整的静态页面方案. Works from the existing page alone or with optional supporting evidence; does not require another BrandBAI skill, download pages, create final artwork, write video/live scripts, or promise conversion results.
license: PolyForm-Noncommercial-1.0.0
metadata:
  author: 布兰德老白 BrandBAI
  version: "0.4.1"
  category: content-commerce
---

# BrandBAI 商品页诊断优化

围绕当前商品页实际表达的一个核心购买理由，检查主图、交易区和图文详情是否帮助用户完成“认对、看懂、相信、选对、放心买”，再收敛为零至五项可执行优化。页面长度不是质量指标，购买决策是否闭合才是。

## 先确认许可与对象

只在 [PolyForm Noncommercial License 1.0.0](references/license.md) 允许的非商业范围内运行。企业内部使用、客户交付、收费课程配套或其他预期商业用途，须先通过 `brandlaobai@163.com` 取得 BrandBAI 书面商业授权或课程内附的明确授权。

一次运行只处理一个品牌、一个商品、一个当前可成交 SKU／套组和一个页面版本。多个规格、代际或链接可以同时出现在页面里，但必须先锁定本次实际要优化的成交单元；无法锁定时停止正式改版，只输出核实清单。

本 Skill 只处理静态商品页。下载页面、建立完整商品价值底座、生成短视频／达人／直播内容、制作最终视觉稿和发布页面都属于其他任务，不自动串联。

## 选择两种模式

默认根据输入自动选择：

### `diagnose_existing`

只有当前商品页也可以运行。允许：

- 盘点页面当前在说什么、展示什么；
- 识别页面目前试图建立的核心购买理由，并明确它只是“页面当前主张”；
- 检查一核、五决策、SKU／套组、主图—交易区—详情一致性；
- 给出保留、删除、补充、前移、重新组织、人工核实中的零至五项动作；
- 标出哪些建议可直接做，哪些必须补资料后再做。

不得从页面宣传语反推客观商品事实，不得新造卖点、功效、数字、竞品优势或用户共识。

### `enhance_with_evidence`

除页面外，用户又提供了包装、参数、配方／工艺、检测／专利／认证、用户研究、评论样本、客服／退货问题、目标人群、主推 SKU、渠道任务或竞品页面等资料时使用。

先逐份登记资料能证明什么、适用于哪个 SKU、不能证明什么，再把可用内容编译为更完整的主图顺序、交易区信息和详情页模块。竞品页面只能支持结构与表达比较，不能证明本商品事实。评论只能作为顾虑、语言和场景信号，不能单独裁定功效。

若用户已经提供有效的 `brandbai-product-value` 或 `brandbai-value-expression` 交付，可以直接继承其事实、价值、VIS 与限制；它们是可选增强输入，不是启动本 Skill 的强制前置。

## 每次运行先读合同

完整阅读：

- [输入输出合同](references/input-output-contract.md)：两种模式、输入层级与结构化账本；
- [一核五决策法](references/page-decision-framework.md)：诊断与优先级方法；
- [快消品商品页判断参考](references/fmcg-page-patterns.md)：不同决策负担与跨品类边界；
- [路由与能力边界](references/routing-and-boundaries.md)：结论权限、停止条件与可选上游；
- [交付合同](references/delivery-contract.md)：普通版文件、动作标签和验收门槛。

## 准备最低输入

最低需要：

1. 商品名；
2. 当前 SKU、套组或实际到手；不知道时明确写 `unknown`，并先核实；
3. 至少一部分可视觉读取的主图、交易区或详情页材料；
4. 页面截图、下载或观察时间；不知道时写 `unknown`。

模型必须逐张打开图片或逐页打开 PDF，确认真实顺序、页面位置和可读范围。不能只看文件名、缩略图、OCR 汇总或旧报告。未提供的页面范围写“未提供／无法确认”，不能写成“页面没有”。

补充资料是可选项，不要为了启动诊断向用户索要经营后台、GMV、ROI 或完整商品价值工程。资料减少时结论变弱，但诊断仍可完成。

## 初始化交付

先 Dry Run：

```powershell
python scripts/init_product_page_delivery.py `
  --out "<新的输出目录>" `
  --page-sources "<主图、交易区截图和详情页目录>" `
  --brand "<品牌>" `
  --product "<商品>" `
  --sku "<当前SKU或unknown>" `
  --analysis-mode diagnose_existing `
  --scope combined `
  --delivery-mode professional `
  --page-snapshot-time "<时间，未知写unknown>" `
  --dry-run
```

增强模式可增加：

```powershell
  --analysis-mode enhance_with_evidence `
  --supporting-sources "<补充资料目录>" `
  --product-value "<可选：商品价值交付目录>" `
  --value-expression "<可选：卖点呈现交付目录>"
```

确认目标后去掉 `--dry-run`。输出目录非空时拒绝覆盖。

## 完成诊断与优化

按顺序完成：

1. 锁定商品、当前 SKU／套组、页面版本、范围、真实顺序与可读性；
2. 逐项登记页面原话、可见画面、动态权益和适用对象；
3. 写出“页面当前试图让用户因为什么购买”，并判断它是否清晰、一致、有依据；
4. 依次判断认对、看懂、相信、选对、放心买，状态只用“已讲清、部分讲清、未讲清、资料不足”；
5. 给每张主图、交易区字段和详情模块分配一个主要购买任务；
6. 找出缺失、过早、过晚、跳跃、过密、孤立、不一致和只催动作；
7. 增强模式把补充资料登记为事实、页面主张、用户信号、动态快照或待核实主张，并继承适用范围；
8. 按“决策影响、证据确定性、本轮可执行性”排序，只留下零至五项动作；
9. 每项标为“可直接优化／补充资料后优化／待上线验证／不建议使用”；
10. 输出模块页纲、资料缺口、禁用表达和上线后的最小验证问题。

五决策不是五张图，页面模块也不必凑齐固定数量。页面短但决策已闭合，不为凑长度补内容；页面长但关键任务未闭合，也不能因信息多判定为好。

## 生成与校验

```powershell
python scripts/build_product_page_report.py --delivery "<输出目录>" --dry-run
python scripts/build_product_page_report.py --delivery "<输出目录>"
python scripts/validate_product_page_delivery.py --delivery "<输出目录>"
```

普通入口固定为：

```text
01_商品页诊断与优化建议.md
02_主图交易区详情页优化页纲.md
03_资料缺口与证据边界.md
```

宿主具备可靠电子表格能力时，可按 `02` 的相同字段另导出 `.xlsx`；Markdown 是跨模型必交底稿，Excel 不是完成门槛。内部来源、模块、判断、动作、验证和缺口保留在 `data/`。只有校验退出码为 `0` 才能正式交付。

## 严格边界

- 页面出现不等于事实成立，公开主张不等于独立验证；
- 高销样本只支持方法覆盖，不证明页面结构导致销量；
- 静态诊断不等于改版已经提升点击、转化、GMV、ROI 或销量；
- 限时价格、赠品、库存、物流和权益只能作为带时间的动态快照；
- 其他 SKU、色号、口味、尺码、段位、月龄、包装和套组证据不能自动迁移；
- 页面承诺、交易区选择与实际到手冲突时，先核实，不继续美化；
- 最终视觉稿、完整成品文案、合规审核和发布仍需对应负责人确认。
