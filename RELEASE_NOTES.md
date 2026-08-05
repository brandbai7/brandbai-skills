# BrandBAI Douyin Download 0.2.3

这是第三轮 WorkBuddy 真实页面验收后的浏览器会话与审计修正版。

## 能力

- 下载抖音账号全部当前可见置顶作品，加最近 N 条非置顶作品；
- 下载视频、全部可见图文、封面和公开可用原声；
- 批量采集可检索一级评论，二级回复保持实验性边界；
- 生成 `01_作品清单.xlsx`、`02_评论明细.xlsx`、作品素材和采集说明；
- 保留断点续跑、去重、隐私模式和采集完整性状态。

## 本次改进

- `all` 模式改为作品与评论阶段共用一个可见的持久 Chrome 上下文，不再在两阶段之间关闭并重新启动浏览器；
- 评论阶段继续复用同一个工作标签页，只有页面崩溃或导航中断时才重建；
- Dry Run 明确回显 `privacy_mode`、单一浏览器会话计划和运行轨迹位置；
- `download_manifest.json` 与 `run_manifest.json` 增加浏览器上下文模式及启动归属字段；
- `all` 默认保存 `data/browser_session_trace.jsonl`，评论阶段默认保存 `browser_runtime_trace.jsonl`，用于核对阶段顺序、退出状态和采集事件；
- 运行轨迹不包含 Cookie、请求头、验证码、浏览器资料夹或签名材料；界面样本与截图仍只在显式诊断模式下保存。

## 验收口径

- 单次 `all` 正式运行应只调用一次 `launch_persistent_context`；
- 作品与评论 manifest 都应标记 `browser_context_mode=shared_all_context`；
- `browser_session_trace.jsonl` 应依次出现会话开始、作品阶段、评论阶段和会话结束；
- 一级评论只有收到明确分页终止信号时才能标记 `complete_source_visible`；
- 二级回复没有开启时，`replies=0` 只表示未采集，不表示作品没有回复。

## 安装包

下载 `brandbai-douyin-download.zip`。压缩包根目录直接包含 `SKILL.md`，适合支持自定义 Agent Skills 的宿主安装。可使用同名 `.sha256` 文件核验完整性。

## 授权与边界

本版本采用 PolyForm Noncommercial License 1.0.0。企业内部使用、客户交付、收费服务、插件、SaaS、数据服务及其他预期商业用途，需要通过 **brandlaobai@163.com** 取得 BrandBAI 书面商业授权。

安装本 Skill 不等于获得抖音或第三方数据授权。使用者仍需遵守适用法律、平台规则、账号权限和个人信息保护要求。
