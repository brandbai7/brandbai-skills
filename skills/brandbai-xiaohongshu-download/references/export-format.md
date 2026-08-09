# 普通版导出格式

```text
BrandBAI_小红书采集_对象_YYYYMMDD/
├─ 01_笔记清单.xlsx
├─ 02_评论明细.xlsx          # 仅明确请求单篇评论时
├─ 03_搜索快照.xlsx          # 仅搜索批量时
├─ 04_笔记素材/
├─ 05_采集说明.md
└─ data/
   ├─ run_manifest.json
   ├─ notes.jsonl
   ├─ comments.jsonl
   ├─ assets.jsonl
   ├─ profile_selection.json
   ├─ search_snapshots.jsonl
   └─ delivery_manifest.json
```

## 01_笔记清单.xlsx

- `笔记总览`：笔记 ID、主页／搜索位次、选择原因、标题、作者、类型、互动快照、置顶、规范链接、字段范围、是否进入详情、时间和状态。
- `账号信息`、`主页选择`：仅主页批量生成，保留公开账号字段和选择证据。
- `话题明细`：仅进入明确单笔记详情并观察到时生成有效记录。
- `素材索引`：素材类型、顺序、文件、来源 URL、下载状态和失败原因。
- `完整性`：列表选择、详情内容、素材和评论分别写状态。

## 条件工作簿

- `02_评论明细.xlsx`：仅明确请求单篇评论时生成。
- `03_搜索快照.xlsx`：仅搜索批量生成，保留关键词、标签页、筛选和原始位次。

## 空值规则

- 页面明确显示 0：写 `0`。
- 页面未展示：值留空，状态 `not_visible`。
- 批量模式未进入详情：状态 `not_requested`，不得写成失败。
- 公开不可用：`not_available`。
- 采集异常：`failed` 并保留简短原因。

交付和 ZIP 不保存 `xsec_token`、Cookie、请求头、浏览器资料夹或临时导航链接。
