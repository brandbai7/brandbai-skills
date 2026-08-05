# BrandBAI Douyin Download 0.2.4

这是 v0.2.3 单浏览器真实页面验收后的会话收尾与评论口径修正版。

## 能力

- 下载抖音账号全部当前可见置顶作品，加最近 N 条非置顶作品；
- 下载视频、全部可见图文、封面和公开可用原声；
- 批量采集可检索一级评论，二级回复保持实验性边界；
- 生成 `01_作品清单.xlsx`、`02_评论明细.xlsx`、作品素材和采集说明；
- 保留断点续跑、去重、隐私模式和采集完整性状态。

## 本次修复

- 评论阶段正常完成时不再提前关闭最后一个工作标签页；由 `all` 统一入口只关闭一次浏览器上下文，避免会话轨迹出现重复关闭产生的 `TargetClosedError`；
- 崩溃恢复仍会关闭并替换异常工作标签页，不改变断点、重试和后续作品继续处理逻辑；
- `collection_report.md` 新增“一级声明回复数”，将平台显示评论数、一级已采集、回复数字段和实际回复采集量分开报告；
- 普通版 Excel、`04_采集说明.md`、Skill 与导出规范同步说明：页面评论总数可能包含一级评论和回复，一级评论的回复数字段不等于已采集回复。

## 验收口径

- 单次 `all` 正式运行只调用一次 `launch_persistent_context`；
- 作品与评论 manifest 均标记 `browser_context_mode=shared_all_context`；
- `browser_session_trace.jsonl` 依次出现会话开始、作品阶段、评论阶段和会话结束；正常结束时 `close_error_type` 为空；
- 一级评论只有收到明确分页终止信号时才能标记 `complete_source_visible`；
- 二级回复未开启时，`replies=0` 只表示未采集，不表示作品没有回复。

## 安装包

下载 `brandbai-douyin-download.zip`。压缩包根目录直接包含 `SKILL.md`，适合支持自定义 Agent Skills 的宿主安装。可使用同名 `.sha256` 文件核验完整性。

## 授权与边界

本版本采用 PolyForm Noncommercial License 1.0.0。企业内部使用、客户交付、收费服务、插件、SaaS、数据服务及其他预期商业用途，需要通过 **brandlaobai@163.com** 取得 BrandBAI 书面商业授权。

安装本 Skill 不等于获得抖音或第三方数据授权。使用者仍需遵守适用法律、平台规则、账号权限和个人信息保护要求。
