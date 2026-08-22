# 交付与中间数据合同

## 工作顺序

1. 先用 `build_analysis_dataset.py` 生成样本数据。
2. 用 `init_analysis_delivery.py` 放入三份普通版模板和内部空白文件。
3. 分类全部近期非置顶作品，运行 `build_account_baseline.py` 生成中位数基线。
4. 深看作品、编码评论并填写下列 JSONL。
5. 依据同一份 JSONL 填写两份 Markdown。
6. 运行 `build_d1_workbook.py`，由同一份 JSONL 自动生成 D1 工作簿。
7. 运行 `validate_analysis_delivery.py`，修复所有错误后交付。

最终结论与 D1 表必须来自同一套中间数据，不分别凭印象编写。

## 管理清单

`data/delivery_manifest.json`：

```json
{
  "schema_version": "1.1",
  "analysis_status": "complete",
  "analysis_mode": "lightweight_no_asr",
  "account_name": "合成测试账号",
  "analysis_time": "2026-08-05T12:00:00+08:00",
  "deep_review_video_ids": ["synthetic-001"],
  "limitations": []
}
```

`analysis_status` 只能是 `complete`、`partial` 或 `insufficient`。初始化时为 `draft`，不可直接交付。

## 作品分类与中位数基线

`data/work_classification.jsonl` 必须覆盖每条近期非置顶作品：

```text
video_id
content_task
content_type
commercial_status           natural | commercial | activity | live_preview | unknown
account_window
comparison_group
classification_status       included | excluded
excluded_reason
```

自然、商业、活动和直播预告必须分组。排除作品必须写明原因。运行 `build_account_baseline.py` 后生成 `data/baseline_ledger.jsonl`，其中的互动中位数必须能由 `works_sample.json` 复算；置顶不进入近期基线，单作品组只能标 `conditional`。

## 视频分析卡

`data/video_analysis.jsonl` 每行一条深看作品，必填：

```text
video_id
sample_role                  pinned | recent_non_pinned
observation_level            cover_metadata | sampled_frames | direct_media | text_only
observed_sources             string[]
performance_level            high | normal | low | outlier | unknown
comparison_group
user_task
opening
key_action
visual_anchor
video_message
comment_reception_center
alignment_level              high | partial | split | low | unknown
attention_owner
commercial_memory
mechanism_candidate
counterexample
alternative_explanations     string[]
completeness                 complete | partial | unknown
source_url
```

全部置顶作品都必须有卡。非置顶代表作品最多 10 条，并覆盖有条件形成的高、常态、低或反例。默认 `observed_sources` 至少记录 `metadata`、`cover` 和 `comments`；没有视觉来源时使用 `text_only`，不得标完整。

## 评论证据账本

`data/evidence_ledger.jsonl` 每行一条编码评论，必填：

```text
evidence_id
video_id
comment_id
source_role                  top_level | viewer_reply | creator_reply
comment_text
digg_count
reply_count
comment_time
parent_id
source_file
source_row
completeness                 complete | partial | unknown
main_semantic                C | P | R | V | B | E | A
auxiliary_tags               string[]
reception_depth              S0 | S1 | S2 | S3 | S4 | S5 | S6
```

评论原文不得改写。每条只有一个主语义。单条作品进入分布计算的一级评论最多 200 条；固定抽样不等于概率样本。

## 评论采集与停止账本

`data/comment_collection_ledger.jsonl` 每条深看作品一行：

```text
video_id
platform_comment_count
encoded_top_level_count
encoded_reply_count
collected_at
sort_order
completeness                 complete | partial | unknown
activity_pollution
anomalies                    string[]
stopping_status              sufficient | continue | blocked
stopping_reason
```

编码数量必须与评论证据账本一致。`sufficient` 只表示足以支持本轮账号判断，不表示平台绝对全量；仍需补采或关键楼中楼不可见时使用 `continue` 或 `blocked`，并在资料限制中继承。

## 结论证据卡

`data/claim_cards.jsonl` 每行一条重要判断，必填：

```text
claim_id
topic
claim
evidence_status              F | P | H | U
reception_level              high | partial | split | low | unknown | not_applicable
supporting_video_ids         string[]
supporting_evidence_ids      string[]
evidence_summary
counterevidence
alternative_explanations     string[]
usable_scope
prohibited_scope
validation_next
```

标为 P 的模式至少需要两个支持作品，并且必须有评论证据。单条高表现只能形成 H 候选，不得包装成稳定公式。

## 五类稳定资产

`data/account_assets.jsonl` 必须各有且只有一行：

```text
people_judgment
content_action
method_value
relationship_asset
commercial_boundary
```

每行填写 `asset_id`、`asset_type`、`statement`、`evidence_status`、`supporting_video_ids`、`supporting_evidence_ids`、`counterevidence`、`alternative_explanations`、`usable_scope` 和 `prohibited_scope`。证据不足时保留 U，不允许缺行或用商品方向补齐。

## 创作空间地图

`data/creation_space.jsonl` 必须各有且只有一行：

```text
stable
expandable
episodic
commercial_high_risk
```

每行填写 `space_id`、`zone`、`statement`、`evidence_status`、`supporting_video_ids`、`supporting_evidence_ids`、`conditions`、`counterevidence` 和 `boundary`。它只描述账号创作空间，不生成本次选题或具体商品方向。

## D1 工作簿

使用 `assets/02_D1评论语义证据包模板.xlsx`，只保留四个页签：

1. `阅读说明`：范围、状态、编码和关键边界；
2. `作品与对齐`：视频分析卡的普通版映射；
3. `评论语义证据`：评论证据账本映射；
4. `结论证据卡`：结论卡映射。

运行顺序：

```powershell
python scripts/build_d1_workbook.py --delivery "<分析输出目录>" --dry-run
python scripts/build_d1_workbook.py --delivery "<分析输出目录>"
```

脚本只使用 Python 标准库，直接把 `video_analysis.jsonl`、`evidence_ledger.jsonl`、`claim_cards.jsonl` 和管理清单映射到初始化时复制的模板。当前模板最多容纳 40 条重点作品、4000 条评论证据和 200 张结论卡；超出容量时脚本会停止，不会静默截断。

不要在表内加入手机号、Cookie、浏览器资料或未经需要的个人信息。评论作者标识默认不进入普通版。

抖音作品 ID 和评论 ID 通常超过 Excel 的安全整数位数。内部 JSONL 必须保留原始字符串；普通版工作簿可使用 `DYV-<video_id>`、`DYC-<comment_id>` 作为显示值，并在“阅读说明”注明前缀只用于避免科学计数法，数字主体仍是平台 ID。不得把长 ID 写成数值单元格。

## 完成门槛

- `complete`：全部置顶和代表作品至少达到 `cover_metadata`，数量合规，评论足以完成对齐，三份普通版和内部数据互相一致；无需音频转写。
- `partial`：仍形成有效分析，但视觉材料、评论、回复或对照缺失，或存在 `text_only` 重点作品；必须逐项写入 `limitations`。
- `insufficient`：无法形成有效可比组；只保留可观察事实、资料缺口和下一步补充，不生成高表现模式结论。
