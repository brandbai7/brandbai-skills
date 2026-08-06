# BrandBAI Skills

> Content-commerce Agent Skills that turn public evidence into usable deliverables.<br>
> 面向内容电商的专业 Agent Skills：让公开信息变成可执行、可复核、可交付的结果。

BrandBAI Skills 是一个遵循 [Agent Skills 开放标准](https://agentskills.io) 的内容电商技能库。每个 Skill 都以 `SKILL.md` 为入口，可附带脚本、参考资料和模板，并坚持同一套交付原则：事实优先、证据可回溯、边界说清楚、普通用户看得懂。

本仓库源码公开，但不是允许任意商用的开源软件。免费使用限于 [PolyForm Noncommercial 1.0.0](LICENSE) 允许的非商业范围；企业内部使用、客户交付、收费产品或其他预期商业用途需要单独取得 [BrandBAI 商业授权](COMMERCIAL_LICENSING.md)。

同一份 Skill 可以被支持 Agent Skills 的模型或本地智能体安装，不绑定某一个大模型厂商。具体发现路径和授权方式由宿主工具决定。

## Skill catalog

| Skill | Version | What it does | Status |
| --- | --- | --- | --- |
| [`brandbai-douyin-download`](skills/brandbai-douyin-download/) | 0.2.6 | DataTool 式抖音下载总入口：作品清单、视频、图文、封面、可用原声和可检索评论，支持长任务轮询与断点续跑 | Community beta · Noncommercial |
| [`brandbai-douyin-account-analysis`](skills/brandbai-douyin-account-analysis/) | 0.2.0 | 轻量无音频转写，基于“全部置顶＋最近最多 30 条非置顶作品”连接作品表达、评论接收和候选机制 | Prototype · Noncommercial |

首发采集脚本已在 Windows Chrome 完成真实页面验证；macOS 和 Linux 需要显式提供 Chrome 可执行文件路径，目前列为待扩大验证范围。Skill 格式本身可跨模型安装，不等于所有宿主都具备本地浏览器、终端或文件权限。

## Install

推荐使用跨智能体 Skills CLI：

```bash
npx skills add brandbai7/brandbai-skills
```

也可以把某个 Skill 目录复制到宿主支持的技能目录：

```bash
git clone https://github.com/brandbai7/brandbai-skills.git
```

- ChatGPT / Codex：可让 `$skill-installer` 从 GitHub 仓库安装，或复制到用户／项目的 `.agents/skills/`。
- Claude Code：可使用 Skills CLI 安装，或把 Skill 目录放到 Claude Code 支持的技能位置。
- Gemini CLI：可使用 Skills CLI 安装，或放到项目的 `.agents/skills/`。
- 其他工具：只要支持 Agent Skills 标准，就可直接读取对应 `SKILL.md`；执行脚本仍需本地文件、终端和相应权限。

安装后可直接说：

```text
使用 brandbai-douyin-download，下载这个抖音账号全部可见置顶作品和最近 5 条作品，
包括视频、图文、封面、可用原声和全部可检索一级评论，生成 BrandBAI 普通版交付。
```

```text
使用 brandbai-douyin-account-analysis，分析这份抖音采集包。纳入全部置顶作品和置顶之外
最近最多 30 条作品，默认不做音频转写、不上传媒体，输出账号深度分析和 D1 评论语义证据包。
```

### WorkBuddy 一键安装

腾讯 WorkBuddy 用户可点击下面的链接唤起自定义 Skill 安装：

[在 WorkBuddy 安装 brandbai-douyin-download](https://www.codebuddy.cn/work/launch?skillname=brandbai-douyin-download&downloadurl=https%3A%2F%2Fgithub.com%2Fbrandbai7%2Fbrandbai-skills%2Freleases%2Flatest%2Fdownload%2Fbrandbai-douyin-download.zip&channelType=github)

如果宿主不支持网页唤起，也可以从 [最新 GitHub Release](https://github.com/brandbai7/brandbai-skills/releases/latest) 下载 `brandbai-douyin-download.zip` 手动安装。压缩包根目录直接包含 `SKILL.md`；下载后可使用同名 `.sha256` 文件核验完整性。

首次安装、环境检查、常用任务话术和转发说明见 [BrandBAI 抖音下载 Skill 安装与使用说明](DOUYIN_DOWNLOAD_USER_GUIDE.md)。

## Why BrandBAI

- **Content-commerce first**：围绕达人、内容、商品、用户表达和交易承接设计，不做泛化工具堆砌。
- **Evidence before conclusions**：保留来源、时间、ID、原文和采集状态，不把观察写成未经验证的归因。
- **Human-readable delivery**：普通用户先看到清晰表格和素材，原始数据留在 `data/` 供续跑与审计。
- **Explicit boundaries**：区分完整、部分完成、未知、空白和确认的 0，不用技术成功掩盖数据不完整。
- **Model-portable**：以开放 `SKILL.md` 为单一事实源，宿主差异只放在安装和工具适配层。

## Responsible use

首个 Skill 只使用用户可见、正常登录的浏览器页面，不绕过验证码、访问控制、签名保护或平台限速，不导出 Cookie 或浏览器登录资料。安装本 Skill 不代表平台授权；使用者应遵守所在地法律、平台条款、个人信息保护要求和自身获得的数据授权。商业部署应优先采用平台正式开放接口、客户授权数据或其他合法数据来源。

“全部评论”表示采集时点页面可分页返回并收到终止信号的全部可检索评论，不代表平台内部绝对全量。

通过 Skill 下载的作品、评论、账号信息和其他第三方材料不会因为进入导出文件而自动采用本仓库许可证，也不会转变为 BrandBAI 或使用者自有知识产权。公开仓库、私有方法资产和第三方数据的边界见 [`IP_AND_DATA_POLICY.md`](IP_AND_DATA_POLICY.md)。

## Roadmap

1. BrandBAI Download：抖音作品、媒体和评论下载。
2. BrandBAI Douyin Account Analysis：抖音账号作品基线、视频表达、用户接收与候选机制。
3. BrandBAI User Semantics：评论与用户语义证据。
4. BrandBAI Influence Intelligence：KOC、KOL、达人、明星艺人等影响力对象洞察与匹配。
5. BrandBAI Product Value：商品价值、P0 与卖点感知化。
6. BrandBAI Content & Performance：内容诊断、千川测试与复盘。

详细能力边界与现有方法资产的迁移规则见 [`SKILL_SYSTEM.md`](SKILL_SYSTEM.md)。每个新 Skill 都按一个顶层用户任务组织子能力，独立触发、独立验证、独立版本化，避免把每个提示词拆成一个 Skill，也避免把所有方法论塞进一个万能提示词。

## Development

```bash
python -m pip install -r requirements-dev.txt
python scripts/validate_repo.py
python -m unittest scripts/test_build_skill_release.py
cd skills/brandbai-douyin-download/scripts
python -m unittest test_download_creator_works.py test_browser_collect_comments.py test_run_foundation.py test_run_long_job.py test_build_foundation_workbooks.py
cd ../../brandbai-douyin-account-analysis/scripts
python -m unittest test_analysis_dataset.py test_analysis_delivery.py
```

提交新 Skill 前请阅读 [`AGENTS.md`](AGENTS.md)。不要提交登录资料、Cookie、客户数据、真实评论样本、输出目录或本地绝对路径。

## License and brand

代码与公开 Skill 内容采用 [PolyForm Noncommercial License 1.0.0](LICENSE)，免费授权仅覆盖该许可证定义的非商业用途。企业内部使用、客户交付、收费服务、插件、SaaS、数据服务及其他预期商业用途需要单独取得 [书面商业授权](COMMERCIAL_LICENSING.md)。

BrandBAI 商业授权由 **杭州岂飞品牌管理有限公司**（统一社会信用代码：`91330109MAEPG1CB16`，对外品牌：`布兰德老白 BrandBAI`）统一签发，指定联系邮箱为 **brandlaobai@163.com**。

项目使用的第三方依赖仍分别遵守其原始许可证，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

`布兰德老白 BrandBAI` 名称和标识不因源码许可证获得商标授权；描述性引用和准确注明来源不受影响，详见 [TRADEMARKS.md](TRADEMARKS.md)。参与贡献前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，知识产权与第三方数据范围见 [IP_AND_DATA_POLICY.md](IP_AND_DATA_POLICY.md)。
