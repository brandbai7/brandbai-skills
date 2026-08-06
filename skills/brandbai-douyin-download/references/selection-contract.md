# BrandBAI Douyin selection contract v1

Read this reference when the task starts from a Chrome plugin export, a Douyin search result page, manual work selection, or an explicit list of work URLs.

## Input priority

Use exactly one works input per task:

1. `--selection-file <作品清单.xlsx>`: preferred bridge from BrandBAI Chrome extension v0.3.0. The workbook must contain a `作品清单` sheet and a `作品ID` column.
2. `--selection-file <selection.json>`: portable selection contract for other hosts or future plugin versions.
3. Repeated `--video <URL>`: one or more explicit `/video/`, `/note/`, or `modal_id` work URLs.
4. `--source-page <URL>`: directly observe a visible creator or search page. Use `--selected-id` to freeze specific works, or `--limit` to bound all observed works.
5. `--creator <URL> --recent N`: all currently visible pinned works plus the latest N non-pinned works.

Prefer a selection file over scraping the search page again. Search results can change between page loads; the exported file preserves the user-confirmed IDs, order, keyword, and source page type.

## JSON shape

```json
{
  "contract": "brandbai.douyin.selection/v1",
  "source": {
    "page_type": "search",
    "page_url": "https://www.douyin.com/search/example",
    "keyword": "example",
    "captured_at": "2026-08-06T12:00:00+08:00"
  },
  "selection": {
    "mode": "manual",
    "label": "手动选择"
  },
  "download": {
    "primary": true,
    "cover": true,
    "audio": true,
    "caption": true,
    "comments": true
  },
  "works": [
    {
      "aweme_id": "1234567890123456789",
      "type": "video",
      "author": "示例作者",
      "title": "示例发布文案",
      "source_url": "https://www.douyin.com/video/1234567890123456789",
      "source_page_type": "search",
      "source_keyword": "example",
      "source_rank": 1
    }
  ]
}
```

Media candidates are optional. When they are absent, the Skill opens each selected work in the same visible signed-in Chrome context and enriches the metadata through the normally loaded work page.

## Selection integrity

- Deduplicate by the full text work ID; never convert IDs to floating point.
- Preserve selection order and source keyword.
- Record missing requested IDs separately from media download failures.
- Treat a search-page selection as a snapshot of the observed page, not all platform search results.
- When selected work metadata cannot be observed and requested media URLs are absent, mark the works stage `partial_metadata_unavailable`.
- Do not copy cookies, request headers, browser profile paths, tokens, or signatures into a selection file.

## Asset choices

`--assets` accepts a comma-separated subset of:

- `primary`: highest available observed video, or all observed images.
- `cover`: observed cover.
- `audio`: observed source audio, preserving its real container.
- `caption`: release caption saved as UTF-8 text; this is not ASR or spoken-word transcription.

Use `--assets none` for metadata only. Use `--skip-comments` with `all` when the delivery should contain works data and selected assets without comment collection.
