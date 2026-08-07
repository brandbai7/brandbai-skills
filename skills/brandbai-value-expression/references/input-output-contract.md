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

可以同时提供当前商品详情页、包装、图片、视频帧、既有页面或内容素材，用于盘点页面已经怎么说、怎么拍。补充素材若包含尚未登记的新商品事实、跨 SKU 信息或冲突，先退回商品价值 Skill 更新上游；不得在本 Skill 静默新增事实或改变 P0。

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
expression_id, value_ids, source_statement, source_id, locator,
page_says, page_shows, current_perception, reusable, gap, status, boundary
```

`expression_id` 继承上游 `EX-`，不另建平行页面表达编号。页面出现过只表示“已有表达”，不表示“已验证有效”。

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

每个 VIS 只能有一个主价值和一个主要决策任务。画面、动作、声音、字幕、道具五条基础轨不得为空；场景、特效/BGM和商品/包装/商品页承接也必须逐项判断。`external_priority` 为空或1—5，决定普通版最多5张核心呈现卡，不表示内容播放顺序。

### validation_ledger.jsonl

最多3条：

```text
test_id, vis_ids, validation_task, must_keep, single_variable,
primary_metrics, writeback, status, requirements, boundary
```

只有建议验证任务时使用 `suggested`；不得伪造样本量、阈值、结果或已验证状态。

### gap_ledger.jsonl

```text
gap_id, category, missing, impact, minimum_needed, priority, state
```

## 5. 稳定 ID

```text
VE-<12位十六进制>
PATH-001
SLOT-01 ... SLOT-12
VIS-001
TEST-001
GAP-001
```

上游 `PV-`、`F-/U-/EX-`、`V-`、`ANCHOR-` 和 P0 决策 ID 只继承，不重编号。VIS 是资产索引，不是镜头号、页面图片号或播放顺序。
