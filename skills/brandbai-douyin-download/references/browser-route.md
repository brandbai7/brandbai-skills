# 独立 Chrome 评论采集路线

## 适用场景

用于公开抖音视频或达人主页的评论研究，且用户能够在普通 Chrome 页面中正常查看目标内容。它不需要 TikHub Key，也不依赖 DataTool、MediaCrawler 或浏览器扩展。

## 工作原理

1. 以 Playwright 启动用户可见的 Google Chrome 持久资料夹，不开放远程调试端口。
2. 用户在首次运行中手动完成抖音登录或验证码；Skill 不自动绕过验证。
3. 作品任务从主页当前可见内容中选择全部置顶作品与最近 N 条非置顶作品；评论任务优先读取该任务生成的 `works.json`，确保范围一致。
4. 每个作品打开后，采集器等待 SPA 页面稳定，依次读取可见标题、页面元信息和浏览器标题，再监听网页正常交互产生的评论与回复 JSON 返回，并保存平台评论 ID、层级、时间、点赞、回复数和 IP 标签等可用字段。
5. 采集器使用真实指针点击可见的“展开回复/更多回复”控件，并滚动当前评论容器触发下一页。
6. 若首次评论由页面预渲染而没有产生可观察响应，则读取 `[data-e2e="comment-item"]` 可见一级评论卡片作为兜底。后续拿到平台 ID 时会按评论文字与隐私化身份去重并替换兜底 ID。
7. 每页立即写入 SQLite，退出或中断后可使用同一输出目录续跑。

## 首次配置

建议使用项目专用虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-browser.txt
```

Google Chrome 必须已安装。一般会自动发现；找不到时传入 `--chrome-path`。

为采集器创建一个独立、长期复用的资料夹，例如 `<私有目录>\brandbai_douyin_profile`。该资料夹保存登录态，必须位于输出数据包之外，不得压缩、上传或交付。

## 单视频试跑

```powershell
.\.venv\Scripts\python scripts\run_foundation.py comments `
  --video "https://www.douyin.com/video/<视频ID>" `
  --max-comments-per-video 20 `
  --profile-dir "<私有目录>\brandbai_douyin_profile" `
  --login-wait 180 `
  --out "<输出目录>\smoke_test"
```

Chrome 出现后，用户只需完成普通登录/验证并保持窗口打开。测试通过的最低标准：`comments_exported > 0`、平台 ID 行能进入 `comments.csv`、重复 DOM 行已清理、未验证的分页保持 `done=false`。

## 达人作品对应的一级评论

```powershell
.\.venv\Scripts\python scripts\run_foundation.py comments `
  --works-json "<作品输出目录>\works.json" `
  --profile-dir "<私有目录>\brandbai_douyin_profile" `
  --login-wait 60 `
  --max-ui-actions 5000 `
  --out "<输出目录>\creator_comments"
```

`--max-comments-per-video 0` 表示不主动设置一级评论上限。`--max-ui-actions` 是异常页面的硬停止保险，不代表请求并发；浏览器路线按顺序逐个作品执行。二级回复不在当前稳定完成承诺内，只有明确测试时才增加 `--include-replies`。

## 完整性判定

- `complete_source_visible`：所选视频的一级评论分页均收到终止信号；请求回复时，所有显示有回复的根评论也收到回复终止信号。
- `partial_browser_visibility`：页面空闲或不可继续，但至少一个层级没有终止信号。
- `partial_action_budget`：达到界面动作硬上限，可用同一输出目录续跑。
- `partial_browser_error`：页面或浏览器异常；已写入 SQLite 的证据仍保留。
- `done_reason=limit`：用户设置了正数上限，只能称为限额样本，不能称全量。

DOM 兜底只提供当前可见的一级评论，不用于推测隐藏回复或完成状态。页面显示“7 条回复”但只拿到 3 条且 `has_more=true` 时，必须报告 3/7、未完成。

## 隐私与安全

- 默认 `--privacy-mode hash`，普通评论者身份只保存稳定化名。
- `--privacy-mode raw` 只能在用户明确授权且确有业务需要时使用。
- 输出中不保存 Cookie、请求头、浏览器资料夹或验证码信息。
- 不使用隐身绕过、签名生成、接口伪造、验证码自动化或高并发。
- 评论文本的存在属于可观察 F 证据；评论中的购买、效果和身份主张仍需核验。

## 页面隔离与崩溃恢复

- `comments` 任务只启动一个可见的专用 Chrome，并复用一个工作标签页顺序采集，不为每条作品新开窗口或新标签页。
- `all` 任务在作品与评论阶段之间复用同一个持久 Chrome 上下文；作品阶段完成后不关闭窗口再重新启动。
- 正常完成时保留最后一个工作标签页，由浏览器上下文所有者统一关闭一次会话；只在崩溃恢复时关闭并替换异常标签页。
- 保留达人主页发现的真实 `/video/` 或 `/note/` 路径，不把图文作品强制改写成视频路径。
- 回复展开默认每轮不超过 5 个控件，降低单页 DOM 和媒体解码压力；仍按顺序单并发执行。
- 工作标签页发生 `Page crashed`、页面跳转中断或执行上下文销毁时，立即保留 SQLite 断点、关闭该标签页、创建新标签页并重试一次。
- 单条作品连续失败后继续处理后续作品，并在 `run_manifest.json` 中记录重建页数、重试数和崩溃数；不得把未验证终止分页的作品标记为完整。
- 默认保存安全运行轨迹：`all` 阶段写入 `data/browser_session_trace.jsonl`，评论阶段写入 `browser_runtime_trace.jsonl`。只有显式启用诊断模式时才额外保存界面样本或截图。

## 宿主超时与重复任务防护

- WorkBuddy、Codex 或其他宿主显示的调用超时，只代表宿主等待窗口结束，不代表 Python 或 Chrome 采集进程已经停止。
- 超时后先检查输出目录中的 manifest 状态、文件更新时间和原进程；状态为 `running`、文件仍增长或原进程仍存在时，继续等待并轮询。
- 不得因宿主超时自动重跑同一作品任务，否则可能重复下载媒体并同时占用同一个 Chrome 资料夹。
- 只有确认原进程已经结束，且 manifest 明确为部分完成或失败时，才使用同一输出目录续跑；目标范围或隐私模式改变时使用新目录。
