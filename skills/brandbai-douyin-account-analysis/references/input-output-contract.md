# 输入输出合同

## 输入目录

优先接受 `brandbai-douyin-download` 普通版交付：

```text
01_作品清单.xlsx
02_评论明细.xlsx
03_作品素材/
04_采集说明.md
data/作品采集/works.json
data/作品采集/download_manifest.json
data/评论采集/comments.csv
data/评论采集/run_manifest.json
```

脚本以 `works.json` 和 `comments.csv` 为确定性数据源；Excel 用于普通阅读，不作为优先解析源。

## 最低字段

### 作品

- `aweme_id` 或 `video_id`
- `title`
- `publish_time` 或 `create_time`
- `source_url`
- `is_pinned`
- `digg_count`
- `comment_count`
- `collect_count`
- `share_count`
- `local_folder` 或可定位素材的其他相对路径

默认轻量模式至少需要能定位封面。视频文件、音频、字幕和转写都不是必需输入；已有且宿主可直接读取时，只作为增强证据。

### 评论

- `aweme_id` 或 `video_id`
- `comment_id`
- `text`
- `source_role`
- `reply_level`
- `digg_count`
- `reply_count`
- `create_time`
- `evidence_id` 或可生成稳定证据编号的来源 ID

### 完整性

- 作品采集状态
- 评论采集状态
- 采集时间
- 是否包含回复
- 每条作品的异常或缺失说明

## 样本合同

- 纳入全部当前可见置顶作品。
- 另取最近最多 30 条非置顶作品。
- 置顶不占 30 条名额。
- 同一作品只保留一次；只要任一来源将其标为置顶，就按置顶处理。
- 非置顶作品按发布时间倒序选择。
- 非置顶样本用于近期基线；置顶作品单独分析。
- 深看全部置顶作品，并从非置顶样本中选最多 10 条代表作品。

## 评论合同

- 只对置顶和非置顶代表作品进行语义编码。
- 单条作品有效一级评论不超过 200 条时全部编码。
- 超过 200 条时保留高互动、具体问题、质疑和反向经验，再固定间隔补足到最多 200 条。
- 回复不是首版完成门槛；结论依赖回复但回复缺失时标 H 或 U。
- 固定抽样不是概率样本，不外推完整粉丝比例。

## 普通版输出

```text
01_账号深度分析.md
02_D1评论语义证据包.xlsx
03_分析说明与资料缺口.md
```

## 内部输出

```text
data/analysis_manifest.json
data/works_sample.json
data/comment_inventory.json
data/delivery_manifest.json
data/video_analysis.jsonl
data/evidence_ledger.jsonl
data/claim_cards.jsonl
```

`build_analysis_dataset.py` 只生成前三个确定性文件。`init_analysis_delivery.py` 创建后四个空白合同文件和普通版模板；宿主在语义分析阶段填写，不得把空模板交付。

## 编号

保持以下回溯链：

```text
video_id → evidence_id → claim_id → mechanism_id
```

任何重要结论必须能回到作品、评论原文和输入文件。

## 观察层级

- `cover_metadata`：标题或简介、封面、互动数据和评论均已读取；可完成默认轻量模式。
- `sampled_frames`：在 `cover_metadata` 基础上读取了本地抽帧。
- `direct_media`：宿主直接读取了视频或图文素材。
- `text_only`：只有标题、数据和评论，没有视觉证据；必须标记 `partial`。

默认 `analysis_mode` 为 `lightweight_no_asr`。Skill 不主动生成音频转写，不将媒体上传给第三方。已有字幕或转写可作为补充，但缺失不降低默认模式的完成状态。

## 完成状态

- `complete`：本次输入支持的必做分析全部完成，所有重点作品至少达到 `cover_metadata`；无需音频转写。
- `partial`：可分析，但视觉材料、评论、回复或对照存在影响结论的缺口，或存在 `text_only` 重点作品。
- `insufficient`：无法形成有效可比组，只输出事实和资料缺口。
