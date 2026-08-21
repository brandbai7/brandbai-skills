# 输入输出合同

## 目录

1. 必需上游
2. 可选输入
3. 输出目录
4. 结构化数据
5. 稳定 ID

## 1. 必需上游

每次运行必须读取一个当前有效的 BrandBAI 商品价值底座目录，至少包含：

```text
data/product_manifest.json
data/fact_ledger.jsonl
data/fabe_ledger.jsonl
data/anchor_ledger.jsonl
data/value_ledger.jsonl
data/p0_decision.json
```

上游 `analysis_status` 只能是 `complete` 或 `partial`，`delivery_status` 只能是 `ready` 或 `conditional`。P0 为 `P0-REOPEN`、`P0-REPLACED` 或 `P0-STOPPED` 时停止；本 Skill 不自行修复、重选或替换商品价值。

一个运行只处理上游确认的一个商品和一个当前 SKU。P0/P1/P2、事实、识别锚、不能证明什么和下游准备度全部继承。

## 2. 可选输入

可以同时提供当前商品详情页、包装、图片、视频帧、既有页面或内容素材，用于盘点页面已经怎么说、怎么拍。补充素材中的公开传播语言和可见形式使用本轮 `PEX-` 页面表达登记，但它们不是新增商品事实；若包含尚未登记的新商品事实、跨 SKU 信息或冲突，先退回商品价值 Skill 更新上游，不得在本 Skill 静默新增事实或改变 P0。

评论或用户原声只有在上游已经登记为可用用户语义资产时才能调用。未经授权不得直接外部引用个人原话。

## 3. 输出目录

```text
<交付目录>/
├── 01_卖点可视化呈现.md
├── 02_资料说明与验证计划.md
└── data/
    ├── expression_manifest.json
    ├── upstream_snapshot.json
    ├── existing_expression_ledger.jsonl
    ├── six_path_ledger.jsonl
    ├── slot_scan_ledger.jsonl
    ├── vis_ledger.jsonl
    ├── validation_ledger.jsonl
    └── gap_ledger.jsonl
```

Markdown 是普通阅读入口；`data/` 是卖点呈现资产、版本、验证与后续内容组装的单一事实源。普通版最多显示5个核心呈现资产和3个建议验证任务，完整资产保留在数据底稿。

同一商品价值底座首次输出使用 `output_version=V1`。保留旧交付并生成修订版时必须依次使用 `V2`、`V3` 等新版本；`value_expression_id` 由 `product_value_id + output_version` 确定，两个并存版本不得复用同一组合。

## 4. 结构化数据

### expression_manifest.json

```text
schema_version, skill_version, value_expression_id, product_value_id,
brand, product, category, sku, upstream_output_version, output_version,
source_materials, analysis_status, delivery_status, limitations,
created_at, updated_at
```

### upstream_snapshot.json

保存上游商品价值 ID、版本、更新时间、状态、P0 决策、当前价值摘要、事实/页面表达/识别锚 ID、必需文件哈希和来源目录名称。只保存来源名称，不把本地绝对路径写入交付。

### existing_expression_ledger.jsonl

```text
expression_id, expression_origin, source_form, value_ids, fact_ids,
source_statement, source_id, locator,
page_says, page_shows, current_perception, reusable, gap, status, boundary
```

上游已登记表达继续继承 `EX-`，`expression_origin=upstream`、`source_form=upstream_registered`。本轮对补充商品素材实际盘点出的页面语言或可见形式使用稳定 `PEX-001` 起编号，`expression_origin=source_material`，并至少回指一个上游事实；`source_form` 使用 `detail_page`、`packaging`、`image`、`video_frame`、`original_document` 或 `other`。

`PEX-` 只登记页面怎么说、怎么拍，不得把未入上游的规格、检测小字、认证结论或其他新主张升级为事实。上游已按主张单位拆分的商品、SKU、净含量、配料、营养、储存、许可证、标准和警示不得在 `PEX-` 重新合并；一个页面区域含多个字段时分别登记表达或只选择与当前价值直接相关的一项。正文出现 `*1/※1/注1` 等标记时，`source_statement/page_says` 必须同时保留对应脚注原文，`boundary` 必须写明脚注或限定语的作用范围；调用该表达的 VIS 继续在 `must_keep/misuse/boundary` 保留。提供了补充商品素材且分析状态为 `complete` 或 `partial` 时，至少形成一条 `PEX-`；普通版页面盘点必须由本账本确定性生成，不得只手工写进 Markdown。页面出现过只表示“已有表达”，不表示“已验证有效”。

### six_path_ledger.jsonl

每个准备沟通的 P0/P1/P2 逐项保留六条路径：

```text
scan_id, value_id, route, role, translation, reason,
fact_ids, expression_ids, boundary
```

`route`：数字化、感官化、差异化、情境化、证据化、人格化。

`role`：`primary`、`supporting`、`not_prioritized`、`not_applicable`。每个价值必须有1条主路径和1—2条辅助路径，其余路径也要保留判断与理由。

### slot_scan_ledger.jsonl

固定扫描 `SLOT-01`—`SLOT-12`：

```text
slot_id, slot_number, asset_group, slot_name, status, reason, vis_ids
```

适用则关联至少一个 VIS；不适用则写明理由并保持 `vis_ids=[]`。

### vis_ledger.jsonl

```text
vis_id, value_id, secondary_value_ids, asset_group, slot_number,
user_question, target_perception, decision_task,
primary_route, supporting_routes, fact_ids, expression_ids, human_language,
visual_track, action_track, sound_track, subtitle_track, prop_track,
scene_track, effect_bgm_track, commerce_handoff_track,
must_keep, variable_parts, misuse, applicable_objects,
must_preserve_tracks, adaptable_tracks,
validation_status, boundary, external_priority
```

每个 VIS 只能有一个主价值和一个主要决策任务。画面、动作、声音、字幕、道具五条基础轨不得为空；场景、特效/BGM和商品/包装/商品页承接也必须逐项判断。`external_priority` 为空或从1开始连续的1—5，决定普通版最多5张核心呈现卡，不表示内容播放顺序。核心卡必须优先覆盖全部可调用P0/P1；P2仅在确实解除当前购买阻力、获得品牌战略输入或用户证据支持时进入核心卡，允许普通版少于5张。`SLOT-02`一级识别锚不得进入核心卡。包数、容量、重量和件数不能自行换算为使用周期、频次、减少补货、一次买够或够用一阵；这些语义必须由关联上游事实直接支持。来源只列用途时不得升级为“一瓶搞定/解决全部”；上游没有气味、香气或真实嗅觉证据时不得写“闻得到/能闻到/香气扑鼻”。关联上游事实若已声明套组/装箱冲突，该 VIS 不得生成。

### validation_ledger.jsonl

最多3条：

```text
test_id, vis_ids, validation_task, must_keep, single_variable,
control_version, test_version, primary_metrics, measurement_method,
decision_rule, writeback, status, requirements, boundary
```

对照版、测试版和唯一变量必须互相一致；single_variable 必须锁定一个具体变量，不得含二选一素材或跨多个呈现维度；证据截图是唯一变量时，两版字幕保持相同；证据画面、固定字幕、验证任务与指标必须语义同题，安全性检测不得被用于降低或抵消孕哺禁忌，也不得替代稳定性/失活证据；症状分层、说明书/医务人员指导、禁忌、注意事项、警示和适用边界在全部版本中保留，不得作为可删除变量；单包构成验证的两版均使用当前SKU真实单包，不以预摆样品替代。外部品类、竞品、普通款或传统方案的同框/对照/对比必须由关联上游事实中的同题直接比较证据支持，不能只凭当前商品的身份、资质或自身事实引入。平台行为指标与评论语义分别读取，不得写成“留存用户的评论复述比例”等平台无法直接返回的混合指标。没有样本与基线时可以给出探索性比较规则，但不得使用“显著性”判断，也不得伪造样本量、阈值、结果或已验证状态。

### gap_ledger.jsonl

```text
gap_id, category, missing, impact, minimum_needed, priority, state
```

## 5. 稳定 ID

```text
VE-<12位十六进制>
EX-001 / PEX-001
PATH-001
SLOT-01 ... SLOT-12
VIS-001
TEST-001
GAP-001
```

上游 `PV-`、`F-/U-/EX-`、`V-`、`ANCHOR-` 和 P0 决策 ID 只继承，不重编号。`PEX-` 是本轮补充商品素材的页面表达索引，不是商品事实。VIS 是资产索引，不是镜头号、页面图片号或播放顺序。
