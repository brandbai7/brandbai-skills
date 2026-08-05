# BrandBAI Douyin foundation delivery format

Read this reference before producing an XLSX, defining a download contract, or planning free/member export quotas.

## Unified ordinary delivery

- Folder: `BrandBAI_抖音采集_{creator}_{YYYYMMDD}`.
- Ordinary files: `01_作品清单.xlsx`, `02_评论明细.xlsx`, `03_作品素材/`, `04_采集说明.md`.
- Raw resumable files: `data/作品采集/` and `data/评论采集/`.
- Keep QA previews outside the delivery folder.
- Replace Windows-invalid folder characters with `_`. Never truncate an aweme ID inside data or media folders.
- Use `complete` only when every requested work has terminal evidence; otherwise preserve the partial state in the workbook and manifest.

## Works workbook

`01_作品清单.xlsx` contains:

1. `使用说明`: creator, selection scope, counts, status, source, timestamps, and boundaries.
2. `作品清单`: work ID, type, creator, title, publish time, interactions, selection reason, real URL, media folder, and download state.
3. `素材明细`: one row per downloaded video/image/cover/audio file, including size and relative path.

Put title and human-readable content before audit fields. Keep IDs as text and link each media row back to its work.

## Comment workbook

1. `导出说明`: scope, source, privacy mode, counts, status, timestamps, and completeness caveat.
2. `视频清单`: aweme ID as text, content type, title, real `/video/` or `/note/` URL, top-level/reply counts, incomplete reply floors, completeness.
3. `DataTool兼容`: five-column human-browsing view shown before the wide detail table.
4. `评论明细`: canonical traceable evidence table.
5. `采集质量`: per-item terminal-pagination and recovery status.
6. `字段字典`: type, definition, null policy, and DataTool mapping.

Do not include `D1语义输入`, semantic labels, creator conclusions, or product-fit judgments in the foundation export. Add analysis worksheets only in a later, explicitly requested analysis workflow.

## Ordinary comment columns

The ordinary `评论明细` sheet prioritizes reading while retaining traceability:

1. `作品标题`
2. `评论内容`
3. `评论人`
4. `评论时间`
5. `点赞数`
6. `回复数`
7. `评论角色`
8. `作品链接`
9. `作品ID`
10. `评论ID`
11. `根评论ID`
12. `父评论ID`
13. `层级`
14. `IP属地`
15. `是否置顶`
16. `是否作者回复`
17. `证据状态`
18. `证据ID`
19. `采集时间`

The raw `comments.csv` remains the canonical machine-readable table. Do not remove or rename its source fields when packaging the ordinary workbook.

## Data and formatting rules

- Store aweme, comment, root, parent, evidence, and semantic sample IDs as text. Verify the exported XLSX XML/cell values preserve every digit; never accept scientific-notation precision loss.
- Store known counts as integers. Unknown counts are blank, not `-`; confirmed zero is numeric `0`.
- Store known timestamps as actual spreadsheet date-time values and display `yyyy-mm-dd hh:mm:ss`; leave unknown timestamps blank.
- Preserve the original visible comment text. Do not overwrite source text with classifications or cleaned prose.
- Use `reply_level=0` for top-level comments and `1` for replies. Keep `viewer_comment`, `viewer_reply`, and `creator_reply` distinct.
- Set `ID来源=platform` for platform IDs and `dom_fallback` for generated fallback IDs.
- Default commenter identity to a stable pseudonym. Raw identity requires explicit authorization and legitimate need.
- Add clickable hyperlinks for work URLs and relative media paths while preserving their visible values.
- Freeze the header row, enable filters, wrap long text, and use readable fixed widths. On the wide comment table, freeze the title and comment columns as well. Do not make visual styling obscure audit fields.

## DataTool compatibility view

Keep exactly these headers and order:

`评论内容`, `评论人`, `评论时间`, `点赞数`, `回复数`

Make this view a filterable table containing values copied at export time. Label it as an export-time static viewing snapshot rather than a live formula view, because cached cross-host formula results are not reliable. Use the canonical table and raw data for edits, deduplication, reply relationships, creator analysis, and evidence tracing, then regenerate the workbook.

## Quality contract

- Workbook filename status, `导出说明`, `采集质量`, `run_manifest.json`, and `collection_report.md` must agree.
- A finished top-level floor with unfinished reply floors remains `partial` when replies were requested.
- Record child-page creation, retries, crashes, action-budget stops, and remaining incomplete reply floors.
- Never put cookies, request headers, browser profiles, CAPTCHA data, or signature material in the workbook or delivery package.

For commercial quotas, count successfully written, de-duplicated comment/reply rows. Do not charge again for retries or duplicate rows.
