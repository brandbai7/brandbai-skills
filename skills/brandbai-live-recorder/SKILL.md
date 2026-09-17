---
name: brandbai-live-recorder
description: Record authorized public Douyin live rooms to verified local video, with optional segments and online-viewer snapshots. Use for 抖音直播录屏、多直播间录制、直播评论与互动记录、在线人数轨迹、直播商品编号目录、单商品主图详情及全部可选规格、买家评价下载、直播资料包检查。Browser-free recording uses StreamGet and FFmpeg; visible comments, product catalogs, product materials and buyer reviews require the bundled Chrome extension and local helper, with the relevant page open. Route recording, independent product downloads, review downloads and explicitly authorized later transcription separately; never imply complete historical comments or automatic business analysis.
license: PolyForm-Noncommercial-1.0.0
metadata:
  author: 布兰德老白 BrandBAI
  version: "0.22.10"
  category: content-commerce
---

# BrandBAI 直播录屏 Skill

保存公开直播视频，并按使用者选择整理直播互动、人数快照、商品与买家评价，供后续研究使用。下载、转写、分析分别发起，不自动串联。

本次为能力入口与文档同步：配套界面能力基线为扩展 0.22.9、本机助手 0.22.7；Skill 包内扩展版本随发布号更新，不改变采集行为。已有上述版本无需因本次说明更新重启助手或重载插件。安装 Skill 不等于已经安装浏览器插件及本机助手。

## 先按任务选择入口

| 使用者想做什么 | 使用入口 | 必读合同 |
| --- | --- | --- |
| 检查环境、查看是否开播、录制一个或多个房间 | 无浏览器 Python 脚本 | [运行](references/runtime-contract.md)、[录制输入](references/input-contract.md) |
| 录制时同步记录可见评论、弹窗商品或页面人数 | Chrome 配套助手；明确选择采集项 | [运行](references/runtime-contract.md)、[直播互动](references/live-interaction-contract.md)、[录制资料包](references/recording-bundle-contract.md) |
| 保存本场商品编号与轻量目录 | Chrome“商品资料 → 下载商品目录” | [商品下载](references/product-download-contract.md)、[商品身份](references/product-identity-contract.md) |
| 保存单商品图片、参数与全部页面可选规格 | 打开唯一商品详情 →“下载图片与规格” | [商品下载](references/product-download-contract.md)、[商品身份](references/product-identity-contract.md) |
| 保存单商品买家评价 | 在同一商品打开“商品评价” →“下载评价” | [评价下载](references/product-review-contract.md)、[商品身份](references/product-identity-contract.md) |
| 检查 ZIP 是否完整、解释保存状态或关联不同资料 | 只读现有包与清单，不自动重新采集 | [ZIP 交付](references/browser-delivery-contract.md)、[命名与关联](references/export-naming-contract.md)，再读相应数据合同 |
| 把已有录屏转成文字、对照评论与商品事件 | 使用者另行发起，云端转写另获上传授权 | [直播互动](references/live-interaction-contract.md) |
| 给客户介绍能力 | 输出清洁客户稿，不混入运行日志 | [客户能力说明](assets/customer/02_Skill能力说明.md) |

商品目录、图片规格和买家评价都可独立下载，不需要先录制，也不必先读目录。图片与评价共用当前商品身份，但分别生成资料包。CLI 没有脱离网页的商品／评价抓取入口；不要把插件能力写成任意宿主装上 Skill 即可自动采集。

未安装配套工具时，按 [安装与快速使用](assets/customer/01_安装与快速使用.md) 引导。宿主无法操作可见浏览器时，请使用者在插件完成页面操作，再读取导出文件；不得改用隐藏接口或未经授权的浏览器会话。

## 授权与安全

- 只保存使用者有权访问和保存的公开内容。直接要求录制并给出链接就是本次操作指令，不重复询问同一授权；这不是传播、商用或再发布授权。
- 本项目源代码按 [PolyForm Noncommercial 1.0.0](references/license.md) 提供。企业使用、客户交付等商业用途须取得 BrandBAI 书面商业授权：brandlaobai@163.com。
- 不绕过登录、验证码、访问限制、签名保护或限速。不读取收货信息、支付信息、Cookie、浏览器凭据或令牌；私有服务状态不进入交付包。
- 只执行所选任务；不购买、抽奖、点赞、发评论、联系买家，不自动打开全部商品详情。
- 更新或重启本机助手前，先确认录制与下载全部空闲。仅更新 Skill 文档不需要停止或重启助手。

## 无浏览器录制

需要 Python 3.10+、FFmpeg、FFprobe 和 StreamGet。先做本地检查；缺依赖时走宿主正常安装审批，不绕过环境权限。以下命令从 Skill 根目录运行，房间链接替换成使用者给出的真实链接：

```powershell
python scripts/run_live_recorder.py doctor
python scripts/run_live_recorder.py probe --room-url "https://live.douyin.com/<room-id>"
python scripts/run_simple_recording.py "https://live.douyin.com/<room-id>"
python scripts/run_simple_recording.py "https://live.douyin.com/<room-id>" --recording-minutes 30 --split --segment-minutes 10
```

默认标清、30 分钟、不分段，保留 TS 原片并转封装为 MP4。总时长 1—1440 分钟；单文件超过 360 分钟必须分段，分段默认 10 分钟。未开播只报告当次结果并退出，不后台等开播。命令行默认保存到用户视频目录下的独立场次，不使用浏览器下载位置。

多房使用 `run_multi_recording.py`，先读取其 `--help`；至少两个不同公开房间，默认最多 3 路、硬上限 5 路并行，分别交付。不承诺每路同时收集网页评论；Chrome 界面全局只控制一个活动录制任务。

有限时录制发生短暂断流时，在原截止时间内最多重新解析同房间两次，保留已得媒体及缺口。不是无限重连、不补回断流期间内容、不自动开录下一场。后台服务连接异常与直播源断流必须分别判断。

## 页面采集工作流

1. 先核对当前房间、唯一商品面板和页面授权；未就绪时说明具体动作，不凭标题猜商品。
2. 用户明确点击相应入口后才采集。目录可尝试打开当前唯一“全部商品”；失败给手动提示。单商品允许有界翻图、滚动及切换可选规格，结束后核对恢复原选择。评价按当前筛选和排序向下读取。
3. 保持原商品／评价页打开。关闭侧栏不等于停止任务；重开查询原任务，不新建重复任务。评价页转后台先有界等待，回来复核后继续；不承诺后台仍在滚动采集。
4. 展示已确认保存的数量，区分读取、整理资料包和浏览器文件下载。状态连接异常只报告最后确认结果，不以页面还在滚动推断持续落盘。
5. 停止时保存已确认部分；目标未达、页面变化、超时或缺图都如实保留原因。不要擅自重复采集或把“部分”改成“完整”。

当前有界范围：

- 目录：每轮最多新增 100 条；明确继续时累计最多 1000 条。每商品保留编号、名称、展示价格、1 张缩略图和可见讲解标注。缺号可短暂复核；推测与确认分开，绝不把列表位置当真实编号或商品 ID。
- 单商品：主图、详情图、公开文字参数、全部页面可选规格及价格图片对应；最多 40 个规格组合、200 张图片，有时间和体积上限。没有规格选项不等于确认只有一个 SKU。
- 评价：默认目标 200 条，可选 50／500 条；50 条每轮最多 3 分钟，200／500 条最多 10 分钟。目标不保证读满；原页、原商品和原筛选检查点有效时可手动继续，新累计包不覆盖旧包，也不能把两包条数相加。
- 商品视频、评价附图／视频文件下载尚未实现；评价仅记录可见正文、历史所购规格、显示的追评／商家回复和附图数量。商品图片中的文字不自动 OCR。

## 正确解释资料

- 无浏览器人数快照默认每 15 秒一次，只保存当时可取得的字段。在线人数是同时在线快照，不是进房人数、独立访客或留存率；缺值不写成 0。
- 直播评论与商品弹窗依赖原网页持续更新。切换应用／标签不主动停止媒体录制，但网页冻结、关闭或同账号在其他地方进入直播间可能造成互动空档。建议保持原直播页前台，不自动抢回账号。
- 商品面板遮住直播弹窗时，弹窗记录可能中断；视频、评论与指标分别核验，不能一概承诺互不影响或都已完整。
- 弹窗商品是直播中的可见卡片及变化记录，不是完整商品详情，也不是观众评论。后补商品资料不能证明此前价格、主播实际讲解或成交原因。
- 商品真实 ID 只取公开明确证据；缺失留空，保留原面板观察标识。同标题、房间 ID、链接编号或 SKU ID 不能替代商品 ID。跨包可靠关联优先使用平台＋真实商品 ID；无 ID 不自动跨页面合并。
- Chrome 每次任务一个 ZIP，使用浏览器默认下载位置；只有浏览器确认文件完成才称下载完成。CLI 按独立目录交付。保留历史文件，名称不展示“待核”或内部编号；未知标题省略，内部关联字段仍保留。
- 先查包内完整性说明和原始台账，再报告已取得、未取得、停止原因及可继续条件。视频时长、评论条数、目录编号、图片／规格覆盖和文件下载状态分别核对。

## 转写、证据整理与后续交接

录制或下载完成后停止，不自动运行下一阶段。用户明确要求转写时，先确认把指定媒体音频上传给模型服务的授权与模型配置，再使用 `scripts/run_doubao_lite_transcription.py`；API 密钥只从环境读取，不索要其明文到对话或交付文件。

已有对齐的转写与事件时，`scripts/compile_live_interaction_evidence.py` 可整理评论—话术、商品—话术的对照证据。保留媒体偏移、页面首次可见时间、证据等级和缺口；自动对照不是因果结论。两者运行前先读对应合同和 `--help`。

商品价值分析、直播复盘和经营建议属于另行发起的分析任务。本 Skill 不生成 GMV、转化归因、销售承诺或账号后台私有数据。验证声明分清源码存在、合成测试、发布包校验和本次真实页面结果，不把其中一层当作全功能实测。
