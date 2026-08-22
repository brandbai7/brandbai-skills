# 输入输出合同

## 1. 一次运行的对象

一次运行只处理一个品牌、一个商品、一个当前 SKU 和一个页面版本。`combined` 可以同时读取主图与详情页，但仍是同一个 SKU、同一个页面版本和同一组优先动作。

## 2. 输入层级

### 页面输入

至少提供当前范围内一份可视觉读取的页面材料：图片、PDF、网页导出、下载助手资料包或品牌自行整理的页面文件。每份来源记录文件哈希、相对路径、页面位置、顺序、可读状态和截图/下载时间。

页面未覆盖某模块只能写“未提供或不可确认”，不能写“页面没有”。压缩包只作为来源容器登记，未解压时不能声称已读取内部页面。

### 商品价值上游

正式页面优先级需要一个当前有效的 `brandbai-product-value` 交付，至少包含：

```text
data/product_manifest.json
data/fact_ledger.jsonl
data/value_ledger.jsonl
data/p0_decision.json
```

上游 `analysis_status` 只能为 `complete` 或 `partial`，`delivery_status` 只能为 `ready` 或 `conditional`；P0 可以处于 `P0-HYPOTHESIS`、`P0-SELECTED`、`P0-VALIDATING` 或 `P0-BOUNDARY-VALIDATED`，推荐价值的 `downstream_readiness` 必须为 `ready` 或 `conditional`。`P0-HYPOTHESIS` 只允许进入 `partial` 有条件分析，所有优先级与页面动作必须继承待验证边界；它不得被包装成已选定或已验证的核心价值。商品、SKU、事实、价值分层和边界只继承，不改写。

商品页动作还必须继承推荐价值的 `cannot_prove` 与卖点呈现的 `misuse`：可以明确排除、保留为未知或转入“人工核实”，但非人工核实动作不得重新把受限主张写成主图重点、详情页证明或购买理由。

### 卖点呈现上游

推荐读取当前有效的 `brandbai-value-expression` 交付：

```text
data/expression_manifest.json
data/upstream_snapshot.json
data/vis_ledger.jsonl
```

它必须与商品价值的 `product_value_id`、版本、P0、商品和 SKU 一致；只有明确适用于“商品页”、绑定当前价值且状态可调用的 VIS 才能进入本 Skill。缺少卖点呈现时可以指出“缺哪类感知或证明”，不能在本 Skill 静默新建完整 VIS。

### 经营数据

课程模式不要求经营数据。专业版可把有时间窗、口径、页面版本和流量范围的数据作为版本观察，但数据缺失不能转成零，整体变化不能自动归因到单张主图或详情模块。

## 3. 运行参数

```text
scope: main_images | detail_page | combined
task: diagnose | design | route | version_review
delivery_mode: course | professional
```

课程模式只运行 `diagnose`。`version_review` 至少要有两个真实页面版本和各自页面时间；`route` 要有明确入口语境；`design` 与 `route` 都必须有可用商品价值上游。

## 4. 输出目录

### 课程模式

```text
<交付目录>/
├── 01_商品页与主图优先优化行动单.md
└── data/
    ├── page_manifest.json
    ├── upstream_snapshot.json
    ├── source_inventory.jsonl
    ├── page_coverage.jsonl
    ├── page_component_ledger.jsonl
    ├── page_chain.json
    ├── decision_ledger.jsonl
    ├── action_ledger.jsonl
    ├── validation_ledger.jsonl
    └── gap_ledger.jsonl
```

### 专业模式

```text
<交付目录>/
├── 01_商品页判断与优先修复.md
├── 02_主图与详情页下一步.md
└── data/...
```

`task=route` 时，专业版 `data/` 额外包含 `routing_decision.json`；其他任务不得混入旧路由结论。

## 5. 结构化字段

### page_manifest.json

```text
schema_version, skill_version, product_page_id, brand, product, category, sku,
scope, task, delivery_mode, run_status, analysis_status, delivery_status,
page_snapshot_time, entry_context, cross_surface_summary, output_version, source_count,
limitations, created_at, updated_at
```

### upstream_snapshot.json

保存商品价值和卖点呈现是否提供、是否可用、上游 ID、版本、状态、商品/SKU、推荐价值、有效事实/价值/VIS 摘要和必需文件哈希。只保存来源目录名，不写本地绝对路径。

### source_inventory.jsonl

```text
source_file_id, source_version, relative_path, file_name, extension, media_type,
size_bytes, sha256, page_scope, page_location, sequence, sequence_status,
readability_status, quality_excluded, quality_exclusion_reason,
capture_time, duplicate_of, notes
```

`readability_status`：`not_reviewed`、`readable`、`partially_readable`、`unreadable`、`unsupported_archive`。

### page_coverage.jsonl

```text
coverage_id, source_version, scope, page_declared_count,
observed_source_count, quality_excluded_count, readable_source_count,
sequence_gap, coverage_status, basis, boundary
```

`coverage_status`：`complete_observed`、`partial_observed`、`unknown`、`not_applicable`。这里的“看全”只指本次提供资料已经逐张核对；不知道平台页面总数时，仍要明确边界，不能推断未提供模块不存在。`ready` 要求本次范围均为 `complete_observed`；其他状态必须保留页面资料缺口。

### page_component_ledger.jsonl

```text
component_id, scope, page_location, sequence, source_file_ids,
readability_status, current_observation, page_says, page_shows,
decision_names, fact_ids, value_ids, vis_ids, dynamic_status,
content_layer, module_role, support_target,
information_node_type, primary_decision_name, match_status,
predecessor_requirement, next_node_or_touchpoint, comparison_dimension,
package_version_status, component_applicability, target_user_or_object,
variant_id, claim_scope, adjacency_status, valid_time_or_unknown, claim_level,
current_role, recommended_role, change_type, execution_instruction,
required_material, acceptance_check, status, boundary
```

页面原话和页面画面是页面观察，不自动升级为商品事实。`dynamic_status`：`not_dynamic`、`current_snapshot`、`expired`、`unknown`。

- `content_layer`：`evergreen_product`、`current_campaign`、`transaction_support`、`trust_and_compliance`；活动信息不能伪装成长期商品信息。
- `module_role`：商品识别、问题教育、价值主张、机制、证据、体验演示、SKU 选择、活动权益、履约服务、使用边界、品牌信任或其他对应的内部枚举。
- `component_applicability`：`current_sku`、`current_bundle_component`、`current_product`、`selectable_variant`、`entry_specific`、`related_product`、`brand_general`、`unknown`。套组中的单品证据不能自动证明整套；专属入口内容没有可靠入口依据时不能直接进入正式结论。其他变体、关联商品、品牌信息或适用性未知内容只能先进入人工核实，不能直接证明当前SKU。
- `support_target`：机制、证据与体验演示必须写清正在支持哪项主张；没有对应主张时不得把材料当作泛化“证明”。

### page_chain.json

保存跨模块与跨表面的购买决策链，不重复抄写组件内容：

```text
schema_version, page_role, page_role_basis, entry_context_basis,
precompleted_decisions, remaining_decision_tasks,
dominant_route, parallel_routes, category_must_answer_tasks,
surface_coverage, ordered_component_ids, decision_closure, continuation_handoffs,
chain_findings, aggregate_implications, cross_surface_consistency,
presentation_actuality_checks, eligibility_gate, variant_routes,
quantified_claim_checks, current_transaction, cross_surface_sku_consistency,
post_purchase_handoff, limitations
```

- `page_role`：`single_product_page`、`selection_hub_page`、`entry_landing_page`、`mixed`、`unknown`。页面角色只描述当前页面主要承担什么，不等于推荐的分版路线；
- `page_role_basis`与`entry_context_basis`：`provided_evidence`、`page_visible_inference`、`unknown`。没有可靠入口资料时，不得声称用户进页前已经完成某项决策；
- `precompleted_decisions`与`remaining_decision_tasks`共同覆盖五项决策且不能重叠。入口未知时，默认保留五项页面任务，不假装品牌知名度已经替当前商品完成理解；
- `current_transaction`区分正装、试用、新客、补充、囤货与礼赠，并锁定监管身份、当前SKU、变体、数量和升级对照状态；
- `current_transaction.raw_spec_groups`保留平台原始规格组名、当前选择值、它实际包含的规范化选择维度、是否混合／信息不足及解释边界。平台叫“口味”或“颜色分类”，不等于用户只在选口味或颜色；
- `current_transaction.selection_dimension_order`保存用户应当先选什么、后选什么；多维度正式交付必须完整覆盖当前变体维度；
- `current_transaction.bundle_contents`保存套组内每个单品的名称、版本、数量和主品／辅品／赠品角色；套组构成未锁定时不得`ready`；
- `variant_routes`区分容量、数量、色号、口味、段位、月龄、产品形态等变体，同时把真实SKU与说明、服务、关联商品和占位项分开；
- `eligibility_gate`只判断页面是否讲清适用对象和条件，不代替医学、营养、科学或法律判断；
- `quantified_claim_checks`只检查量化主张的对象、条件、时间、口径和页面可读支持，不宣称研究设计或功效已独立核验；
- `cross_surface_sku_consistency`核对货架外显、主图、交易区与详情页是否在表达同一成交单元；
- `decision_closure`记录当前商品到哪里完成主要购买决策，页面结束或篇幅很长都不自动等于闭合。

### decision_ledger.jsonl

固定五条：

```text
decision_id, decision_name, status, summary, source_file_ids,
component_ids, fact_ids, value_ids, vis_ids, unknowns, boundary
```

`decision_name`：`认对`、`看懂`、`相信`、`选对`、`放心买`。`status`：`已讲清`、`部分讲清`、`未讲清`、`资料不足`。不生成总分。

### action_ledger.jsonl

```text
action_id, priority, scope, page_location, decision_name,
current_observation, gap_or_risk, basis_type, basis_summary,
source_file_ids, component_ids, fact_ids, value_ids, vis_ids,
action_type, action_detail, must_preserve, material_needed,
human_confirmation, acceptance_check, validation_question,
status, boundary
```

`action_type`：`保留`、`删除`、`补充`、`前移`、`重新组织`、`人工核实`。`status` 默认 `suggested_untested`。正式动作必须回到页面来源和有效上游；降级动作的 `basis_type=page_visible_only`，上游 ID 全部留空。

### validation_ledger.jsonl

专业版按需使用，最多三条：

```text
test_id, scope, version_a, version_b, must_keep, single_variable,
observation_needed, comparability, status, boundary
```

课程模式保持空表。没有真实比较条件时只写建议，不设虚假阈值、不判版本胜负。

### gap_ledger.jsonl

```text
gap_id, category, missing, impact, minimum_needed, return_to,
source_file_ids, priority, state
```

`return_to`：`product_value`、`value_expression`、`page_material`、`human_confirmation`。

### routing_decision.json

只用于 `task=route`：

```text
routing_decision_id, recommended_route, entry_context, decision_summary,
shared_invariants, change_scope, activation_conditions, standalone_gate,
source_file_ids, component_ids, fact_ids, value_ids, vis_ids,
human_confirmation, status, boundary
```

`recommended_route`：`shared_master`、`entry_adaptation`、`dynamic_sku_adaptation`、`standalone_page`。独立精细页只有在入口差异、业务规模、证据和维护能力四项闸门都被支持时才能建议。

## 6. 稳定 ID

```text
PP-<12位小写十六进制>
PAGE-SF-001
COMP-001
DEC-01 ... DEC-05
ACT-001
TEST-001
GAP-001
```

上游 `PV-`、`F-/U-/EX-`、`V-`、`VIS-` 只继承，不重编号。普通版隐藏这些内部 ID，但保留人能看懂的页面位置和依据摘要。
