---
name: brandbai-product-page
description: Diagnose or design one SKU's ecommerce main-image sequence and product detail page from readable page materials, a current BrandBAI product-value foundation and optional value-expression assets. Use for 商品主图诊断、首图与主图顺序、详情页结构、商品页承接、页面优先优化、共用页与分版路由、页面版本对照和课程实操行动单. Keeps product value, facts and VIS boundaries unchanged; does not download pages, reselect P0, create final artwork, write video or live scripts, or promise conversion results.
license: PolyForm-Noncommercial-1.0.0
metadata:
  author: 布兰德老白 BrandBAI
  version: "0.3.1"
  category: content-commerce
---

# BrandBAI 商品页优化

继承已经确认的商品价值和卖点呈现，检查一个 SKU 的首图、主图序列与详情页是否帮助用户完成“认对、看懂、相信、选对、放心买”，再输出少而明确的页面优化动作。主图与详情页属于同一交易承接面，不拆成两个互相重选价值的 Skill。

## 先确认许可、对象和职责

只在 [PolyForm Noncommercial License 1.0.0](references/license.md) 允许的非商业范围内运行。企业内部使用、客户交付、收费课程配套或其他预期商业用途，须先通过 `brandlaobai@163.com` 取得 BrandBAI 书面商业授权或课程内附的明确授权。

一次运行只处理一个品牌、一个商品、一个当前 SKU 和一个页面版本。多个 SKU、不同组合、不同代际或不同页面版本分别运行；需要比较版本时使用 `version_review`，不得混账。

本 Skill 把页面作为待诊断或待设计的交易承接面。若用户只是想从详情页提取商品事实、建立 P0/P1/P2，转到 `brandbai-product-value`；若只是下载天猫、淘宝或其他平台页面，转到下载助手或相应下载 Skill。页面下载成功不等于页面判断已经完成。

## 选择运行方式

默认使用：

```text
task=diagnose
scope=combined
delivery_mode=course
```

- `scope=main_images`：只看首图与主图序列；
- `scope=detail_page`：只看详情页；
- `scope=combined`：主图和详情页一起看，并检查两处的 SKU、价值、证据、权益和承接是否一致；
- `task=diagnose`：检查现状并给优先动作；
- `task=design`：在有效上游基础上生成主图序列与详情模块执行页；
- `task=route`：判断共用母版、入口适配、动态/SKU适配或独立精细页；
- `task=version_review`：比较两个真实页面版本，只形成有边界的观察与下一轮验证；
- `delivery_mode=course`：普通学员的一页行动单，只支持 `diagnose`；
- `delivery_mode=professional`：两份可读文件加结构化底稿。

不得把 `combined` 做成“主图五项＋详情页五项”。一个运行的优先动作总数始终最多五项，依据不足可以是零项。

## 每次运行先读合同

完整阅读：

- [输入输出合同](references/input-output-contract.md)：输入状态、目录和字段；
- [商品页五个用户判断](references/page-decision-framework.md)：主图、详情页和优先级方法；
- [快消品商品页判断参考](references/fmcg-page-patterns.md)：不同决策负担、信息分层与适用边界；
- [路由与能力边界](references/routing-and-boundaries.md)：READY、PARTIAL、降级和停止条件；
- [交付合同](references/delivery-contract.md)：课程版、专业版和正式交付门槛。

执行 `design`、`route`、`version_review` 或收到新页面版本时，再读 [设计、版本与下游交接](references/versioning-and-handoff.md)。

## 准备最低输入

最低需要：

1. 明确的商品名与当前 SKU；
2. 本次要看的主图、详情页或两者，至少一部分可视觉读取；
3. 页面截图、下载或观察时间；不知道时明确写 `unknown`；
4. 推荐提供当前有效的 `brandbai-product-value` 交付；
5. 推荐提供当前有效的 `brandbai-value-expression` 交付。

入口来源、搜索词、上游达人内容、活动入口和新老客数据均为可选。没有可靠入口资料时仍可做静态页面判断，但必须把入口依据标为未知，不得声称用户进页前已经完成“认对、看懂、相信、选对、放心买”中的任何一项。

经营数据、点击率、转化率、GMV、ROI 和竞品后台数据都不是课程模式的启动条件。没有这些数据时照常完成静态页面判断，不补零、不伪造结果、不降低完成状态。

页面图片必须逐张视觉打开并核对真实顺序、可读范围和页面位置，并在 `page_coverage.jsonl` 明确本次提供范围是否已看全。压缩包未解压只能标为不可读来源；未知文件类型不能直接标为可读；同一版本、同一页面范围内的确认顺序不得重复。纯分隔条、损坏文件等可以质量排除，但要逐项保留原因。不能只看文件名、缩略图、OCR 汇总或旧交付。宿主无法视觉读取时，把对应来源标为不可读；没有任何可读页面时停止正式分析。

## 初始化交付

先做 Dry Run：

```powershell
python scripts/init_product_page_delivery.py `
  --out "<新的输出目录>" `
  --page-sources "<当前主图或详情页目录>" `
  --product-value "<商品价值底座目录>" `
  --value-expression "<可选：卖点呈现目录>" `
  --scope combined `
  --task diagnose `
  --delivery-mode course `
  --page-snapshot-time "<截图或下载时间，未知写 unknown>" `
  --dry-run
```

确认目标后去掉 `--dry-run`。没有商品价值底座时可以用 `--brand`、`--product`、`--sku` 初始化降级检查；此时最多只能给三项不依赖核心价值的低风险页面动作。

脚本会建立来源清单。后续新增或比较页面时单独运行：

```powershell
python scripts/index_page_sources.py `
  --input "<页面文件或目录>" `
  --delivery "<输出目录>" `
  --version-label "current" `
  --capture-time "<该版本截图或下载时间>" `
  --dry-run
```

确认后去掉 `--dry-run`。来源清单只固定文件、哈希和初始顺序，不替代视觉核对；按真实页面更新 `page_scope`、`page_location`、`sequence`、`sequence_status` 和 `readability_status`。

`version_review` 只接受 `current` 与 `comparison` 两组真实来源；两组都要提供带时区的页面时间，并至少有一个共同可读页面范围。`task=route` 会额外生成 `data/routing_decision.json`，必须完成入口语境、共用不变量、允许变化、四项独立页闸门和证据引用；其他任务不得混入旧路由文件。

## 完成页面判断

严格按以下顺序：

1. 核对商品、SKU、页面版本、页面范围、可读性和覆盖情况；
2. 判断当前页面主要是单品价值页、多SKU／套组选择页、专属入口承接页，还是任务混合／未知；依据只允许来自可靠入口资料、页面可见推断或未知；
3. 锁定用户当前实际买到的成交单元；先保留平台原始规格组及当前选项，再把它拆成用户真实的选择维度与顺序；套组必须逐项写清单品、版本、数量和主品／辅品／赠品角色；
4. 有可靠入口资料时记录用户进页前已经完成的判断；没有时默认五项都仍需页面承接；
5. 冻结上游商品事实、P0/P1/P2、不能证明什么和 VIS 状态；
6. 分别记录页面当前说了什么、展示了什么，并给每个模块标明长期商品信息／当前活动信息／交易承接信息／信任合规信息、模块任务和当前 SKU 适用性；套组单品和专属入口内容单独标记；
7. 对“认对、看懂、相信、选对、放心买”各形成一个状态判断；多维SKU同时写清用户应当先选什么、后选什么；
8. `combined` 额外检查主图与详情页的身份、规格、价值、证据、权益和承接一致性；
9. 形成候选动作，每项绑定准确页面位置、页面来源和有效上游依据；
10. 按“用户判断的重要性、证据确定性、本轮可执行性”留下最多五项；
11. 无商品价值底座时最多保留三项页面基础清理动作，不决定核心卖点；
12. 把未看全、不可读、未提供、跨 SKU、冲突、动态待确认和需要返回上游的事项写入缺口；
13. 到页面动作、执行页和有限验证计划为止。

V0.3额外生成内部`page_chain.json`，把标题／货架外显、主图、交易区、详情页放进同一条购买决策链。普通用户不需要填写这份账本，但运行时必须核对：

- 当前成交是正装、试用、新客、补充、囤货还是礼赠；
- 当前页面角色是什么，判断依据是入口资料、页面可见推断还是未知；
- 用户进页前哪些判断有可靠证据已经完成，页面还必须补齐哪些判断；
- 规格区每个选项是真实SKU、说明入口、服务入口、关联商品还是占位项；
- 当前色号、口味、段位、月龄、产品形态或包装版本是否被锁定；
- 平台原始规格组分别混入了哪些真实选择任务；多维选择的先后顺序是否清楚；套组内每个单品的版本、数量和实际到手是否清楚；
- 高风险品类的产品身份、适用对象和使用边界是否已经讲清；
- 其他变体、品牌背书或市场表现是否被错误用来证明当前SKU；
- 量化主张是否有对象、条件、时间、口径和可读来源；
- 页面是在当前商品完成决策后自然承接，还是在闭合前过早切到其他任务；
- 展示结果、使用建议与包装实际到手是否容易混淆；
- “新一代／升级”是否说明旧版、新版、改变对象和可比证据。

页面短但已经完成购买决策时不得为了凑长度建议补模块；页面长但主导任务未闭合时也不得因信息量大判定为好页面。

动作只使用：`保留`、`删除`、`补充`、`前移`、`重新组织`、`人工核实`。每项都要写明必须保留的事实或边界、需要的素材或确认、验收问题和“待验证建议”状态。blocked/stale 的组件、动作、路由或验证任务只能留档，不得进入正式普通稿或“第一步”。

## 生成并校验交付

结构化底稿完成后先预览，再生成：

```powershell
python scripts/build_product_page_report.py --delivery "<输出目录>" --dry-run
python scripts/build_product_page_report.py --delivery "<输出目录>"
python scripts/validate_product_page_delivery.py --delivery "<输出目录>"
```

课程模式只交付：

```text
01_商品页与主图优先优化行动单.md
```

专业模式只把以下两份文件作为普通入口：

```text
01_商品页判断与优先修复.md
02_主图与详情页下一步.md
```

内部来源、组件、判断、动作、验证和缺口保留在 `data/`。只有校验退出码为 `0` 才能正式交付。

## 判定运行状态

- `ready`：SKU和页面明确，本次要求的页面范围已逐张看完，P0已进入选择、验证或边界已验证状态，并有至少一个明确适用于商品页、绑定当前价值且状态可调用的卖点呈现资产；
- `partial`：有可用商品价值，但页面或卖点呈现不完整、当前成交单元跨表面冲突、套组构成未锁定，或P0仍是有边界的待验证假设；只分析可读范围。P0是假设时，可以沿该假设给有条件页面动作，但不得写成已选定、已验证的价值优先级；
- `degraded_no_product_value`：没有可用商品价值；最多三项低风险页面动作，不判断卖点优先级；
- `stopped`：SKU不明、没有可读页面、资料损坏，或用户要求编造事实；只输出停止原因和下一步。

完成状态只表示对本次可读输入完成页面判断，不表示页面已经有效、改版会提升结果或视觉稿可以直接发布。

## 严格停止在页面承接

本 Skill 不得：

- 重选、替换或重排上游 P0/P1/P2；
- 从页面宣传语、评论、问答或 OCR 残片反推商品事实；
- 编造功效、机制、检测值、竞品优势、用户共识或第一人称体验；
- 把限时价格、赠品、库存、物流或权益固化为长期事实；
- 因页面出现、评论反馈或整体转化变化，宣称某个组件已经有效；
- 预测点击率、转化率、GMV、ROI 或销量提升；
- 生成最终主图、最终详情页视觉稿、上传页面或代替人工发布审核；
- 生成短视频脚本、达人原话、直播话术或整场直播 SOP。

需要真实视觉成稿时，在本 Skill 交付通过后交给独立创作或设计能力，并继续继承商品事实、VIS、禁用表达和页面执行边界。
