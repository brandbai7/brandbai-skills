# 输入输出合同

## 1. 一次运行的对象

一次运行只处理一个品牌、一个商品、一个页面主讲 SKU／套组和一个页面版本。页面主讲 SKU 是主图与详情页主要内容实际围绕、且能在交易区可见选项中确认的成交对象。`combined` 可以同时读取主图、交易区与详情页，但仍是一套共同判断和零至五项共同改版项目。

分析对象按以下优先级确定：

1. 主图与详情页存在清晰、稳定且占主导的 SKU／套组；
2. 该对象能在交易区可见选项中找到，或由用户明确确认仍可成交；
3. 当前页面可见交易信息能明确归属于该对象；无法确认归属的价格、库存、赠品、物流和到手信息不得写入正式结论；
4. 页面没有主讲对象、主讲对象不在可见选项中，或可见选项无法确认时停止正式动作。

### 多 SKU 页面材料选择

页面存在多个可成交 SKU 时，页面共用详情与每个 SKU 的主图库必须分开判断。来自下载包的 `SKU主图映射` 可作为选择材料的索引，但不自动证明页面主张成立：

1. 目标 SKU 与某个主图库唯一匹配时，才可对该 SKU 给出正式主图顺序、规格、套组、赠品与实际到手建议；
2. 多个 SKU 共用同一主图库时，只需读取和诊断一次，并在结论中继承它适用的 SKU 范围；
3. 目标 SKU 没有成功读取主图库时，主图范围标为资料不足；共用详情页仍可继续诊断，但不得借用其他 SKU 主图补全；
4. 只有当前选中 SKU 的快照时，不得推定页面全部 SKU 都使用同一主图，也不得因当前快照与页面主讲 SKU 不同而评价采集过程；
5. 动态价格、权益、库存、赠品与实际到手仍须逐 SKU 归属，不能仅凭共用详情页迁移。

## 2. 两种分析模式

### diagnose_existing

必需输入：商品身份、当前 SKU／套组、可视觉读取的页面材料。页面本身既是待诊断对象，也是“页面现在这样说／这样展示”的观察来源。

允许形成页面结构、表达清晰度、SKU一致性、证据错位、动态信息和五决策断点判断。页面当前核心购买理由写为 `page_current_claim`，不能升级为已确认商品价值。

### enhance_with_evidence

除页面外至少提供一种补充资料，或提供可用的商品价值／卖点呈现交付。补充资料逐项登记：来源、可读状态、主张类型、适用 SKU、能证明什么、不能证明什么和时效。

可接受的补充资料包括包装、参数、成分／配方／工艺、检测／专利／认证、用户研究、评论样本、客服／退货问题、目标人群、主推 SKU、渠道任务及竞品页面。竞品与评论不得转成商品事实。

## 3. 页面范围

```text
scope: main_images | detail_page | combined
analysis_mode: diagnose_existing | enhance_with_evidence
delivery_mode: course | professional
```

`combined` 把主图、交易区和详情页视为一个购买界面。交易区单独登记在跨表面决策链中，不要求伪装成主图或详情模块。

课程模式保留一份行动单；专业模式输出两份普通文件。默认 `professional`，便于文章领取者分别完成品牌判断与改版执行交接。

## 4. 可选上游

有效 `brandbai-product-value` 与 `brandbai-value-expression` 可以作为增强输入，但不强制安装，也不自动调用。

提供后必须核对品牌、商品、SKU、版本、状态和文件哈希。上游事实、价值、VIS、`cannot_prove` 与 `misuse` 只继承，不改写；不匹配、blocked 或 stale 时退回普通补充资料处理或标记不可用。

## 5. 输出目录

### 课程模式

```text
<交付目录>/
├── 01_商品页诊断与优化建议.md
└── data/...
```

### 专业模式

```text
<交付目录>/
├── 01_商品页诊断与优化建议.md
├── 02_主图交易区详情页优化页纲.md
└── data/
    ├── page_manifest.json
    ├── upstream_snapshot.json
    ├── source_inventory.jsonl
    ├── supporting_source_inventory.jsonl
    ├── claim_ledger.jsonl
    ├── page_coverage.jsonl
    ├── page_component_ledger.jsonl
    ├── page_chain.json
    ├── content_decision_match_ledger.jsonl
    ├── decision_ledger.jsonl
    ├── action_ledger.jsonl
    ├── validation_ledger.jsonl
    └── gap_ledger.jsonl
```

`01` 同时承接资料缺口、当前资料不能证明什么和长期表达边界，不再默认拆出第三份文档。宿主具备可靠电子表格能力时，可把 `02` 同步导出为 `.xlsx`；两个版本必须使用同一数据，不得出现建议漂移。

## 6. 关键结构化字段

### page_manifest.json

```text
schema_version, skill_version, product_page_id, brand, product, category, sku,
scope, task, analysis_mode, delivery_mode, run_status, analysis_status,
delivery_status, page_snapshot_time, entry_context, cross_surface_summary,
output_version, source_count, limitations, created_at, updated_at
```

### page_chain.json 中的 analysis_target

```text
analysis_sku, target_basis, page_primary_sku_or_variant,
visible_option_match_status, visible_option_evidence,
dynamic_snapshot_applicability, decision, boundary
```

`visible_option_match_status`：`matched`、`not_found`、`ambiguous`、`not_provided`。

`decision`：`continue` 或 `stopped`。非停止交付必须是 `continue`；动态交易快照只有能明确归属于分析 SKU 时才可调用。

### page_chain.json 中的 overall_diagnosis

```text
current_page_strategy, current_conversion_logic, current_core_purchase_reason,
strengths_to_preserve, root_problems, professional_judgement
```

整体诊断先于局部动作。`root_problems` 最多三项，每项必须写明问题、页面依据、购买影响与受影响的购买判断；现有页面中建议继续保留的内容进入 `strengths_to_preserve`，不得为了显得专业而制造问题，也不得使用“做对／做错”的身份评价。

`dominant_route` 只描述页面当前真实内容顺序，必须以 `ordered_component_ids` 和页面内容节点为依据。优化后建议顺序只写入 `rebuild_strategy.proposed_purchase_logic` 与 `rebuild_strategy.narrative_route`；两者不得互相冒充。

### page_chain.json 中的 rebuild_strategy

```text
strategic_objective, proposed_purchase_logic, narrative_route, surface_roles,
preserve, deprioritize_or_remove, success_definition
```

`surface_roles` 固定说明主图、交易区、详情页和决策收口各自承担什么。新版购买逻辑必须是一条连续路径，不是把逐图建议重新排列。

### page_chain.json 中的 transaction_panel_plan

```text
status, selection_area_mode, platform_capability_status, capability_summary,
strategy_summary, selection_route, field_groups,
fixed_information, dynamic_information, boundary
```

`status`：`planned`、`preserve_only`、`insufficient_material`、`not_in_scope`、`stopped`。交易区必须检查，但不强制提出修改。只有规格难以区分、选项与主图或实际到手不一致、多个商品混在同一选择区，或动态优惠干扰用户判断时才使用 `planned`；此时天猫／淘宝的 `selection_area_mode` 必须为 `single_primary_area`，并且 `field_groups` 恰好只有一项。当前交易区已经能够支持用户选对并确认到手时使用 `preserve_only`，`field_groups` 必须为空，只记录建议保留的结构、固定信息、动态信息和发布前复核项。没有可读交易区时使用 `unknown`，不得推测选择方案。

`field_groups` 每项字段：

```text
group_id, sequence, group_name, user_question, current_expression,
recommended_structure, current_selection_display, actual_receipt_and_offer,
implementation_status, implementation_path, fallback_path, confirmation_needed,
category_task_ids, material_needed, acceptance_check, boundary
```

`selection_area_mode`：`single_primary_area`、`no_choice_needed`、`unknown`。用户先看容量、再看套组、最后确认到手，是同一组选项内的信息阅读顺序，不得据此虚构多个平台选择器。平台另有只有一个固定值的属性时，把它登记到固定信息中，不作为第二个选择区。

`platform_capability_status`：`confirmed_native`、`conditional_native`、`content_workaround`、`requires_platform_confirmation`、`unknown`。正式建议只允许写当前平台页面或品牌后台已经证明可实施的结构；无法确认能否实现的交互不得进入改版方案。`field_groups[].implementation_status` 使用同一组状态。

交易区需要调整时，方案必须让品牌直接知道：一个主要选择区里的每个选项如何同时讲清商品或规格、稳定套组、简短选择理由和实际到手；选项缩略图怎样与对应主图联动；价格／赠品／库存怎样与长期商品信息分开。当前结构已经清楚时，只说明保持现状的理由和继续保留的内容，不为完整模板制造改版建议。不得把用户理解顺序画成多个平台选择器。无法确认平台能否实现的控件、字段或交互不进入正式建议。

### page_chain.json 中的 detail_page_assessment

```text
status, assessment_basis, strengths, improvement_opportunities, boundary
```

`status`：`assessed`、`insufficient_material`、`not_in_scope`、`stopped`。只有详情页存在可读内容时才可使用 `assessed`。

`strengths` 每项字段：

```text
assessment_id, title, why_it_helps, supporting_component_ids,
category_task_ids, decision_names, preserve_requirement, boundary
```

`improvement_opportunities` 每项字段：

```text
assessment_id, title, what_is_not_yet_clear, purchase_impact,
supporting_component_ids, category_task_ids, decision_names,
improvement_direction, acceptance_check, boundary
```

详情页优势与提升空间必须同时依据细分类目购买任务链和五个买前判断：只有内容已经承接关键任务、位置合理、证据与主张相连且没有明显重复过载时，才登记为已有优势；只有双链断点确实影响某个买前判断时，才登记为提升空间。不得为了平衡版面强行制造优点或问题，也不得把审美偏好写成购买问题。

### page_chain.json 中的 detail_page_plan

```text
status, strategy_summary, narrative_route, modules, asset_migration, boundary
```

`status`：`planned`、`preserve_only`、`insufficient_material`、`not_in_scope`、`stopped`。

当任务包含详情页且存在可读详情内容时，必须使用 `planned` 或 `preserve_only`，并形成至少一个内容章节。`modules` 每项字段：

```text
module_id, sequence, module_name, user_question, page_answer,
required_content, category_task_ids, source_component_ids, source_asset_summary,
presentation_direction, material_needed, acceptance_check, boundary
```

内容章节按用户购买问题和连续叙事组织，不代表一章只能做成一张图。`source_component_ids` 只用于追溯现有详情内容；没有现成素材的新章节可以留空，但必须明确待补资料与边界。

`asset_migration` 必须完整覆盖全部已读详情内容节点，每个节点只登记一次。每项字段：

```text
migration_id, source_component_ids, current_content, handling,
destination_module_ids, execution_note, boundary
```

`handling`：`继续使用`、`集中到一个章节`、`分别放入不同章节`、`提前说明`、`放到后面`、`本轮不使用`、`确认后再安排`。除“本轮不使用”外，内容必须指向至少一个新版内容章节。品牌报告只显示业务安排，不显示内部组件 ID，也不按旧详情图张序逐张生成建议。

### page_chain.json 中的 category_decision_chain

```text
subcategory, decision_context, basis_type, maturity, tasks, boundary
```

`tasks` 至少两项，并按用户完成购买判断的顺序排列。每项字段：

```text
task_id, sequence, task_name, user_question, requirement, importance,
basis_summary, source_file_ids, boundary
```

`basis_type`：`page_visible_hypothesis`、`category_reference_hypothesis`、`page_and_supporting_evidence`、`brand_confirmed`、`user_research_supported`。只读当前商品页时，只能使用前两种假设依据。

`maturity`：`working_hypothesis`、`evidence_strengthened`、`brand_confirmed`、`user_validated`。只读当前商品页时固定为 `working_hypothesis`，不得把方法推断写成用户共识。

### source_inventory.jsonl

只登记待诊断页面：文件哈希、相对路径、页面范围、位置、顺序、可读状态、页面快照／观察时间和质量排除原因。压缩包未展开并实际读取时不能标为已读。

### supporting_source_inventory.jsonl

```text
supporting_source_id, relative_path, file_name, extension, media_type,
size_bytes, sha256, source_role, readability_status, capture_time, notes
```

`source_role`：`product_document`、`evidence_document`、`user_signal`、`business_context`、`competitor_page`、`optional_upstream`、`unknown`。

### claim_ledger.jsonl

```text
claim_id, statement, claim_type, supporting_source_ids, applicable_sku,
support_scope, evidence_status, can_support, cannot_prove, dynamic_status,
human_confirmation, boundary
```

`claim_type`：`confirmed_fact`、`page_claim`、`user_signal`、`dynamic_snapshot`、`competitor_observation`、`unverified_claim`。只有 `confirmed_fact` 且来源、SKU和边界明确时，才可作为新增页面内容依据。

### page_component_ledger.jsonl

按真实页面顺序登记主图与详情页内容节点。每个节点除既有页面位置、表达、来源、角色和证据字段外，必须填写 `category_task_ids`，说明它承接哪些细分类目购买任务。无法关联任何任务的节点不得被默认视为有效内容，应在匹配账本中记录为重复、过载、干扰或未知。

### content_decision_match_ledger.jsonl

每个细分类目任务恰好一条记录：

```text
match_id, category_task_id, component_ids, source_file_ids,
coverage_status, position_status, evidence_connection_status, redundancy_status,
current_content_summary, match_reason, user_consequence,
recommended_resolution, boundary
```

`coverage_status`：`matched`、`weak`、`missing`、`conflict`、`unknown`。

`position_status`：`right_position`、`too_early`、`too_late`、`scattered`、`not_present`、`unknown`。

`evidence_connection_status`：`connected`、`weak`、`disconnected`、`not_required`、`unknown`。

`redundancy_status`：`focused`、`necessary_repetition`、`duplicated`、`overloaded`、`not_applicable`、`unknown`。

匹配账本不是“有／没有”清单。内容存在但出现太晚、与证明材料分离、跨 SKU、重复或过载，仍属于断点。

### decision_ledger.jsonl

固定五条：认对、看懂、相信、选对、放心买。只使用“已讲清、部分讲清、未讲清、资料不足”，不生成无基准总分。每条除摘要外必须填写 `explained`、`not_explained`、`purchase_impact`、`recommended_fix`，分别说明已经讲清什么、还没讲清什么、怎样影响购买和具体怎么补。

“部分讲清”不能只复述状态。优化动作必须指向状态不是“已讲清”的购买判断，并且只修复其 `not_explained` 中的真实缺口。

### action_ledger.jsonl

零至五条。每条必须写明改版项目名称、对应整体根因、对应细分类目任务 `category_task_ids`、项目目标、主要页面落点、当前问题、依据、动作、必须保留、所需资料、人工确认、验收问题、上线验证问题、边界，以及非空的 `recommendation_label`。除“保留”外，任何项目都必须绑定至少一个整体根因和至少一个仍有断点的细分类目任务，不能从单张图直接生成。

普通版标签：

- `可直接优化`：页面可见依据足够，且不新增资料外主张；
- `补充资料后优化`：方向成立，但素材、事实或授权不足；
- `待上线验证`：可执行，但效果只能上线后观察；
- `不建议使用`：越过事实、SKU、合规或时效边界。

`recommendation_label` 只能填写以上四种标签，不能留空，也不能自造“马上提升转化”等承诺式标签。

### gap_ledger.jsonl

缺口按页面资料、补充资料、商品事实、证据、用户信号、动态信息或人工确认分类。缺少经营数据不构成静态诊断失败。

## 7. 稳定 ID

```text
PP-<12位小写十六进制>
PAGE-SF-001
SUP-SF-001
CLAIM-001
COMP-001
CAT-01
MATCH-001
DEC-01 ... DEC-05
ACT-001
TEST-001
GAP-001
```

普通版隐藏内部 ID 和本地路径，只保留人能看懂的页面位置、资料名称和依据摘要。
