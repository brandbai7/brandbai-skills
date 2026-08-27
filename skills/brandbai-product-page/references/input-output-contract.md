# 输入输出合同

## 1. 一次运行的对象

一次运行只处理一个品牌、一个商品、一个页面主讲 SKU／套组和一个页面版本。页面主讲 SKU 是主图与详情页主要内容实际围绕、且能在交易区可见选项中确认的成交对象。`combined` 可以同时读取主图、交易区与详情页，但仍是一套共同判断和零至五项共同改版项目。

分析对象按以下优先级确定：

1. 主图与详情页存在清晰、稳定且占主导的 SKU／套组；
2. 该对象能在交易区可见选项中找到，或由用户明确确认仍可成交；
3. 当前页面可见交易信息能明确归属于该对象；无法确认归属的价格、库存、赠品、物流和到手信息不得写入正式结论；
4. 页面没有主讲对象、主讲对象不在可见选项中，或可见选项无法确认时停止正式动作。

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

课程模式保留一份行动单；专业模式输出三份普通文件。默认 `professional`，便于文章领取者直接完成诊断与交接。

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
├── 03_资料缺口与证据边界.md
└── data/
    ├── page_manifest.json
    ├── upstream_snapshot.json
    ├── source_inventory.jsonl
    ├── supporting_source_inventory.jsonl
    ├── claim_ledger.jsonl
    ├── page_coverage.jsonl
    ├── page_component_ledger.jsonl
    ├── page_chain.json
    ├── decision_ledger.jsonl
    ├── action_ledger.jsonl
    ├── validation_ledger.jsonl
    └── gap_ledger.jsonl
```

宿主具备可靠电子表格能力时，可把 `02` 同步导出为 `.xlsx`；两个版本必须使用同一数据，不得出现建议漂移。

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

整体诊断先于局部动作。`root_problems` 最多三项，每项必须写明问题、页面依据、购买影响与受影响的购买判断；已经做对的部分进入 `strengths_to_preserve`，不得为了显得专业而制造问题。

### page_chain.json 中的 rebuild_strategy

```text
strategic_objective, proposed_purchase_logic, narrative_route, surface_roles,
preserve, deprioritize_or_remove, success_definition
```

`surface_roles` 固定说明主图、交易区、详情页和决策收口各自承担什么。新版购买逻辑必须是一条连续路径，不是把逐图建议重新排列。

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

### decision_ledger.jsonl

固定五条：认对、看懂、相信、选对、放心买。只使用“已讲清、部分讲清、未讲清、资料不足”，不生成无基准总分。每条除摘要外必须填写 `explained`、`not_explained`、`purchase_impact`、`recommended_fix`，分别说明已经讲清什么、还没讲清什么、怎样影响购买和具体怎么补。

“部分讲清”不能只复述状态。优化动作必须指向状态不是“已讲清”的购买判断，并且只修复其 `not_explained` 中的真实缺口。

### action_ledger.jsonl

零至五条。每条必须写明改版项目名称、对应整体根因、项目目标、主要页面落点、当前问题、依据、动作、必须保留、所需资料、人工确认、验收问题、上线验证问题、边界，以及非空的 `recommendation_label`。除“保留”外，任何项目都必须绑定至少一个整体根因，不能从单张图直接生成。

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
DEC-01 ... DEC-05
ACT-001
TEST-001
GAP-001
```

普通版隐藏内部 ID 和本地路径，只保留人能看懂的页面位置、资料名称和依据摘要。
