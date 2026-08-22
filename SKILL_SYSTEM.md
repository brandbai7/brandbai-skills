# BrandBAI Skill system

BrandBAI Skills 面向内容电商，把既有专家方法、确定性脚本、数据合同和交付模板组织成可跨模型安装的顶层能力。一个 Skill 对应一个用户能够直接说清楚的主要任务；该任务下面可以包含多个共享数据、工具和交付合同的子能力。

## Naming

公开 Skill 使用 `brandbai-<domain-or-platform>-<capability>`：

- `brandbai` 提供跨宿主唯一命名空间与品牌识别；
- 中间字段说明平台或业务领域；
- 末尾字段说明用户要完成的顶层能力；
- 子任务、批量范围、输出预设和版本号不进入 Skill 名称。

平台原始字段可以保留 `creator_id` 等平台术语，但 BrandBAI 的分析对象不统一称为 creator。KOC、KOL、内容达人、明星艺人、专家、运动员、企业家、主持人和虚拟 IP 等统一进入 Influence Intelligence，并先按对象类型选择分析尺度。

## Capability families

| Skill | Main job | Example sub-capabilities |
| --- | --- | --- |
| `brandbai-douyin-download` | 下载公开抖音作品、媒体和评论 | 单作品当前页达人快照、主页、搜索结果、插件自选、视频、图文、封面、原声、发布文案、评论、普通版与分析准备版 |
| `brandbai-tmall-download` | 下载公开天猫／淘宝商品事实与用户表达 | 参数、主图、图文详情、视频按模块读取；SKU 映射、结构化价格与权益；评价和问大家独立下载 |
| `brandbai-xiaohongshu-download` | 下载公开小红书笔记、素材、搜索快照和评论 | 单笔记当前页达人快照、账号置顶加最近 N 条、关键词搜索前 N 条、图文、视频、评论、普通版与分析准备版 |
| `brandbai-tiktok-download` | 下载公开 TikTok 作品、跨市场搜索快照、素材和评论 | 单作品当前页达人快照、主页置顶加最近 N 条、综合／视频／照片搜索、双语证据、市场扫描、达人候选、创意对标、官宣接收与联盟内容证据 |
| `brandbai-weibo-download` | 下载公开微博账号、单微博、传播与查询快照 | 单微博当前页达人快照、账号主页、关键词、话题、超话、热搜、评论、回复、转发与普通版交付 |
| `brandbai-douyin-account-analysis` | 分析抖音影响力账号的内容表达与用户接收 | 分类中位数基线、视频表达、评论语义与停止判断、五类稳定资产、创作空间、候选机制、证据包 |
| `brandbai-product-value` | 建立可回溯的商品事实与商品价值底座 | 资料路由、FC/SC、商品身份、识别锚、FABE、P0/P1/P2、证据边界、资料缺口、版本交接 |
| `brandbai-value-expression` | 把已确认商品价值转成可感知的卖点呈现 | 六条翻译路径、十二类感知槽位、画面/动作/声音/字幕/道具五轨、场景与商品承接、单变量验证 |
| `brandbai-influence-product-fit` | 判断影响力对象与商品价值是否匹配 | 双上游读取、用户与场景交集、内容承载、风险边界、候选比较 |
| `brandbai-user-semantics` | 从用户原声形成可回溯选择逻辑 | 单品、多品牌迁移、品类问题、价值命题、SEM/UE/REL/MIG |
| `brandbai-influence-intelligence` | 分析影响力对象的长期资产 | KOC/KOL/达人/明星艺人等对象深析、身份结构、内容机制与用户关系 |
| `brandbai-content-diagnosis` | 诊断内容并沉淀可复用资产 | 单条、对象专项、对照、向量簇、素材池、母版家族、测试队列 |
| `brandbai-qianchuan-analysis` | 接入和分析千川素材经营数据 | Preflight、字段与覆盖、素材池扫描、生命周期、归因边界、实验设计 |
| `brandbai-live-commerce` | 分析直播内容、流量与承接 | 录屏转写、循环、引流、承接、对标、多主播、执行话术卡 |
| `brandbai-commerce-conversion` | 诊断购买前后决策接口 | 商品页、SKU、标准成交单元、咨询、评价、售后退款复购 |
| `brandbai-brand-geo` | 治理品牌长期事实与 AI 回答面 | 品牌源代码、内容宪法、事实总账、冲突治理、GEO 审计 |
| `brandbai-growth-planning` | 把判断编译为可执行增长循环 | 新品启动、阶段策略、Brief、拍摄任务、责任、回写与停止条件 |

以上是能力架构，不代表所有 Skill 已发布或承诺免费开放。每个能力必须单独完成实现、脱敏、验证和发布判断。

## Map existing prompt assets

既有专家提示词资产不按文件数量直接转换为 Skill：

| Existing asset | Skill role |
| --- | --- |
| Quick Start | 任务路由、触发示例和预设 |
| 业务模块 | `references/` 中按需加载的方法 |
| 交付模板 | `assets/` 中的输出结构 |
| 检查清单 | 验收规则和发布前 QA |
| 治理文档 | 相关 Skill 必须继承的安全、证据、隐私、合规和因果边界 |
| Schema | 输入、输出、证据状态和运行元数据合同 |
| Adapter | 平台、API、浏览器和字段适配层 |
| Tool | `scripts/` 中的确定性执行与校验工具 |
| Golden case | 仓库级或 Skill 级自动化测试 |
| Expert master | 私有能力源头，不作为一个巨型 Skill 整体加载 |

## Packaging rules

- 每个已发布 Skill 必须能够单独安装，所需脚本、参考资料和必要模板随 Skill 提供。
- 不跨 Skill 引用安装目录外的相对路径；公共规则由构建流程提取必要子集，避免运行时依赖整个母版。
- 不公开浏览器资料、Cookie、令牌、客户数据、真实评论样本、内部路径或未决定开放的商业方法资产。
- 静态校验、合同测试和真实目标模型运行验证必须分开声明；局部通过不得包装为全量生产验证。
- 下载、证据、分析、决策和执行是不同层级。上游数据不完整时，下游 Skill 必须降级或停止。

## First public data flow

```text
brandbai-douyin-download
        |
        +--> ordinary delivery: Excel + media + collection notes
        |
        +--> analysis-ready raw data and completeness manifests
                    |
                    +--> brandbai-user-semantics
                    +--> brandbai-influence-intelligence
                    +--> brandbai-content-diagnosis
```

商品侧采用独立上游：`brandbai-tmall-download` 只负责商品页面、素材、规格与评价的可回溯采集，再把稳定商品 ID、字段来源和完整性状态交给 `brandbai-product-value`；下载阶段不直接生成 P0、卖点优先级或内容结论。

`brandbai-douyin-download` 当前只负责下载、采集与质量核验。后续 Skill 可以读取其标准化原始数据，但不得把下载成功自动写成语义结论、影响力结论或商业归因。

`brandbai-xiaohongshu-download` 采用相同阶段边界，同时额外保留主页选择位次、置顶与近期选择原因，以及关键词、标签页、筛选、结果位次、相关查询和采集时点，避免把主页或搜索结果脱离原始语境。`0.2.0` 的稳定执行入口覆盖单笔记图文、字段、一级评论，以及账号主页全部当前可见置顶加最近 N 条非置顶；关键词搜索批量模式继续沿用合同，但在真页验证前不得标为稳定。

`brandbai-tiktok-download` 在相同采集边界上增加市场、语言、来源界面、观察时区和授权模式。公开 TikTok 页面负责作品、搜索、主页、素材、评论和双语证据；Creative Center、TikTok One、Ads Manager 与 Seller Center 只作为官方发现或品牌授权经营数据入口。公开互动不得替代受众、投放、订单、GMV 或佣金字段。

```text
brandbai-tiktok-download
        |
        +--> public evidence: works + search + profile + comments + bilingual text
        |
        +--> brand-authorized exports: TikTok One + Ads Manager + Seller Center
                    |
                    +--> brandbai-influence-intelligence
                    +--> brandbai-content-diagnosis
                    +--> brandbai-user-semantics
                    +--> brandbai-influence-product-fit
                    +--> brandbai-growth-planning
```

```text
brandbai-product-value
        |
        +--> product facts, anchors, P0/P1/P2 and evidence boundaries
                    |
                    +--> brandbai-value-expression
                    |
                    +--> brandbai-influence-product-fit

brandbai-douyin-account-analysis
        |
        +--------------------------------> brandbai-influence-product-fit
```

`brandbai-product-value` 只决定“商品价值是什么、依据是什么、能说到哪里”；`brandbai-value-expression` 才决定“怎样让用户看见、听懂和感受到”；匹配 Skill 必须同时读取商品价值与影响力对象分析，任何一侧为 `blocked` 或 `stale` 时停止正式匹配。
