# BrandBAI 抖音下载 Skill 安装与使用说明

适用版本：`brandbai-douyin-download v0.2.5`

这是一个面向抖音公开账号和公开作品的本地采集 Skill。它通过用户可见、已经正常登录的 Chrome 页面工作，可下载作品基础数据、视频或图文、封面、公开可用原声和页面可检索的一级评论，并生成普通用户可直接查看的 Excel 交付。

## 一、目前能做什么

- 下载一个达人、KOC、KOL 或明星艺人主页的全部当前可见置顶作品；
- 在置顶作品之外，再下载最近 N 条非置顶作品；
- 下载视频、全部可见图文、封面和公开可用原声；
- 下载单条作品或多条作品的可检索一级评论；
- 中断后从已有数据继续运行，避免重复下载；
- 生成作品清单、评论明细、作品素材和采集说明。

当前稳定能力是作品、媒体和一级评论采集。二级回复仍属于实验能力；本 Skill 也不会自动生成评论语义、达人画像、商品匹配或商业结论。

“全部评论”指采集当时页面能够分页返回并收到结束信号的全部可检索评论，不代表抖音平台内部绝对全量。

## 二、使用前准备

电脑需要具备：

1. Windows 电脑；
2. Python 3.10 或以上版本；
3. Google Chrome；
4. 可以正常打开抖音的网络；
5. WorkBuddy、Codex 或其他能够调用本地文件、终端和浏览器的智能体宿主。

首次运行时，Skill 会打开可见的 Chrome。请本人完成抖音登录、验证码或访问确认。不要把 Cookie、验证码、Chrome 登录资料夹或账号信息发给其他人。

普通 ChatGPT 网页聊天如果不能访问本机 Python、文件和 Chrome，就无法直接执行采集；建议改用 WorkBuddy、Codex 桌面端/CLI，或其他支持本地 Agent Skills 的工具。

## 三、安装方法

### 方法 A：WorkBuddy 一键安装

[点击安装 BrandBAI 抖音下载 Skill v0.2.5](https://www.codebuddy.cn/work/launch?skillname=brandbai-douyin-download&downloadurl=https%3A%2F%2Fgithub.com%2Fbrandbai7%2Fbrandbai-skills%2Freleases%2Fdownload%2Fv0.2.5%2Fbrandbai-douyin-download.zip&channelType=github)

如果点击后没有自动唤起 WorkBuddy，请使用下面的手动安装包。

### 方法 B：下载 ZIP 手动安装

- [下载 v0.2.5 安装包](https://github.com/brandbai7/brandbai-skills/releases/download/v0.2.5/brandbai-douyin-download.zip)
- [查看 v0.2.5 Release](https://github.com/brandbai7/brandbai-skills/releases/tag/v0.2.5)

在宿主的“自定义 Skill”“导入 Skill”或类似入口选择 ZIP。安装包根目录已经包含 `SKILL.md`，不要把压缩包里的单个脚本拆散安装。

### 方法 C：Codex 安装

在 Codex 中发送：

```text
请使用 $skill-installer，从下面的 GitHub 地址安装 Skill：
https://github.com/brandbai7/brandbai-skills/tree/v0.2.5/skills/brandbai-douyin-download
```

### 方法 D：其他支持 Agent Skills 的工具

电脑已安装 Node.js 时，可以使用：

```text
npx skills add https://github.com/brandbai7/brandbai-skills/tree/v0.2.5/skills/brandbai-douyin-download -g
```

安装时选择自己正在使用的智能体宿主。宿主即使能识别 Skill，也仍需具备本地 Python、文件和 Chrome 权限才能完成采集。

## 四、安装后先做环境检查

第一次使用不要直接下载，先把下面这段话发给智能体：

```text
请读取 brandbai-douyin-download 的 SKILL.md，只检查本机是否具备 Python 3.10+、Google Chrome、所需依赖、本地文件权限和可交互桌面。缺少依赖时先告诉我需要安装什么，不要开始采集，也不要修改或删除我的现有文件。
```

环境检查通过后，再开始正式任务。

## 五、推荐使用话术

### 下载主页作品和一级评论

把其中的主页链接和数字 5 换成自己的目标：

```text
请使用 brandbai-douyin-download v0.2.5。

达人主页：<粘贴抖音达人主页链接>
作品范围：全部当前可见置顶作品，加最近 5 条非置顶作品。
下载内容：作品基础数据、视频或全部图文、封面、公开可用原声，以及全部可检索一级评论。
隐私模式：使用稳定化名，不保留原始评论者名称。
交付方式：生成 BrandBAI 普通版，包括作品清单、评论明细、作品素材和采集说明。

请先做 Dry Run，把达人、作品范围、最近 N、输出目录和隐私模式发给我确认。确认后再正式运行。任务时间较长时只启动一次长任务并持续查看同一个任务状态，不要因界面超时重复启动。
```

### 只下载作品和素材

```text
请使用 brandbai-douyin-download v0.2.5，只运行 works。
达人主页：<粘贴主页链接>
范围：全部当前可见置顶作品，加最近 5 条非置顶作品。
下载作品基础数据、视频或全部图文、封面和公开可用原声。
先做 Dry Run，等我确认后再正式运行。
```

### 只下载单条作品评论

```text
请使用 brandbai-douyin-download v0.2.5，只下载下面这条抖音作品的全部可检索一级评论：
<粘贴作品链接>
使用稳定化名，不采集二级回复。先做 Dry Run，等我确认后再正式运行。
```

## 六、运行过程中你需要做什么

- Skill 打开 Chrome 后，如页面要求登录或验证，请本人手动完成；
- 登录完成后不要主动关闭采集使用的 Chrome 窗口；
- 智能体显示“等待超时”不一定代表采集失败，应先查看原任务状态，不能重复启动；
- 如果任务中断，应让智能体读取原任务状态并从原输出目录续跑；
- 二级回复默认不采集，不要把“回复为 0”理解成作品没有回复。

## 七、正常交付里有什么

- `01_作品清单.xlsx`：作品标题、链接、基础数据和素材状态；
- `02_评论明细.xlsx`：本次成功保存的一级评论；
- `03_作品素材/`：视频、图文、封面和公开可用原声；
- `04_采集说明.md`：采集范围、时间、完成状态和数据边界；
- `data/`：用于断点续跑和质量核验的原始数据，普通用户一般不需要打开。

只有当每条作品都收到明确的评论分页结束信号时，才能把一级评论任务写成完成。部分完成的数据可以保留和续跑，但不能包装成完整下载。

## 八、授权与合规

本 Skill 的公开版本采用 PolyForm Noncommercial License 1.0.0。个人非商业研究、学习和测试可在许可证范围内使用。

BrandBAI 商业授权由以下主体统一签发：

- 公司名称：杭州岂飞品牌管理有限公司
- 统一社会信用代码：91330109MAEPG1CB16
- 对外品牌：布兰德老白 BrandBAI
- 指定联系邮箱：brandlaobai@163.com

以下用途需要提前取得 BrandBAI 书面商业授权：

- 企业、工作室、机构或个体经营者内部使用；
- 客户项目、咨询、培训、研究或运营交付；
- 收费服务、会员产品、插件、SaaS、API 或数据服务；
- 转售、白标、付费分发或集成到商业产品。

联系邮箱：brandlaobai@163.com

取得商业授权后，不需要把授权文件上传到 GitHub，也不需要放进 Skill 安装目录。双方应私下保存最终授权书、授权编号和签署证据；不要在公开 Issue、公开网盘或公开仓库中上传身份证明、签字、印章或完整合同。

安装 Skill 不代表已经取得抖音、账号、视频、评论、个人信息或其他第三方数据的授权。使用者应自行遵守适用法律、平台规则、账号权限和个人信息保护要求。

## 九、遇到问题时怎么反馈

请一次性提供：

1. 使用的宿主名称和版本；
2. Windows、Python 和 Chrome 版本；
3. 使用的 Skill 版本；
4. 运行模式是 works、comments 还是 all；
5. 报错文字或测试报告；
6. 是否已经完成抖音登录；
7. 输出目录中 manifest 显示的是 running、partial、failed 还是 completed。

不要发送 Cookie、验证码、账号密码、浏览器登录资料夹或客户隐私数据。
