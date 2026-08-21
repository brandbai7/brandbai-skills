# 账本填写与分阶段校验

本文件解决“业务内容大致正确，但 JSON 字段、枚举、数组、时间、哈希或引用关系不符合机器合同”的问题。正式 JSON/JSONL 不允许注释；下列记录是字段形状示例，实际值必须来自本次输入和受信工具。

## 一、四个强制检查点

1. 图片正序与逆序完成后，立即写 `source_observation.jsonl`，运行：

```text
python scripts/validate_product_value_delivery.py --delivery "<交付目录>" --stage observations
```

2. 全部 `claim_extract` 完成、再全部 `claim_recheck` 完成后，立即写 `source_claim_ledger.jsonl` 与 `source_ledger.jsonl`，运行 `--stage claims`。
3. 写完来源与事实后运行 `--stage facts`。
4. 写完 FABE、识别锚、价值、P0 决策和缺口后运行 `--stage analysis`。通过后再生成普通版，并运行不带 `--stage` 的完整最终校验。

任何阶段失败，只修本阶段及更早阶段的账本。不得继续堆积后续账本，也不得等到所有工作完成后一次性落盘。

## 二、大账本必须分包写入

来源、原文主张或事实数量较多时，禁止先在上下文中累积全部记录、最后一次写完整 JSONL。出现以下任一情况即使用分包：图片或来源超过 8 个、预计主张或事实超过 40 条、单一来源为营养表/FAQ/高密度参数表，或宿主在 60 秒内持续推理但目标账本仍为空。

- 观察、主张、来源和事实按 `source_file_id/source_id` 分包；FABE、价值和缺口按 `value_id` 或单一决策对象分包。
- 每完成一个来源或一个价值，立即把该小包写到正式交付目录之外的工作目录；不要在 `data/` 内创建临时文件。
- 分包只能含本次输入，不得复制旧交付。每个稳定 ID 只能出现在一个分包中。
- 使用确定性合并脚本预检计数，再原子覆盖正式账本：

```powershell
python scripts/merge_product_value_ledger_parts.py `
  --delivery "<交付目录>" `
  --ledger "<observations|claims|sources|facts|fabe|anchors|values|gaps>" `
  --parts-dir "<交付目录之外的分包目录>" `
  --expected-count <预期总条数> `
  --dry-run

python scripts/merge_product_value_ledger_parts.py `
  --delivery "<交付目录>" `
  --ledger "<同上>" `
  --parts-dir "<同上>" `
  --expected-count <同上>
```

合并器只负责逐行解析、稳定 ID 去重、计数和原子写入，不替模型决定事实类型、证据等级、价值或 P0。合并后立即运行对应阶段校验；失败只修发生问题的小包，再重新合并，不重写已通过的其他来源。

## 二-A、原文主张使用候选选择包

原文主张层默认把判断和写入拆开：确定性脚本从正式 Observation、真实 XLSX/XLSM 单元格和 `claim_extract` 受信事件生成候选；模型只提交候选 ID 和可选类型修正；全部 `claim_recheck` 完成后，脚本再生成正式主张分包。

候选包字段固定为：

```json
{
  "format_version": "1.0",
  "source_file_id": "SF-001",
  "observation_id": "OBS-001",
  "relative_path": "01_商品资料.xlsx",
  "source_sha256": "64位来源哈希",
  "extract_recorded_at": "2026-08-16T10:00:00+08:00",
  "extract_sequence": 1,
  "candidate_count": 2,
  "candidates": [
    {
      "candidate_id": "CAND-001",
      "verbatim_text": "当前选中规格：100g×10袋",
      "suggested_claim_type": "sku",
      "visual_locator": "商品概览!A4:B4"
    }
  ]
}
```

`CAND-` 只在单一来源候选包内稳定，不是跨来源资产 ID。模型选择包使用：

```json
{"source_file_id":"SF-001","selected_claims":[{"candidate_id":"CAND-001"}],"notes":"保留当前SKU；动态字段另设时间边界。"}
```

- 模型不得改写 `verbatim_text`、定位、来源、时间或哈希；
- `claim_type_override` 只在建议类型明显不合适时使用，且必须属于正式 `claim_type` 枚举；
- SKU、配料、营养、储存、警示、冲突双方和观察标记要求的主张不得为缩短输出而删除；
- 动态价格、销量、赠品和权益可以选择，但正式事实必须继续绑定时间，不得升级成稳定价值；
- 页面广告语、背书、代言、检测与认证仍只是原文主张，是否形成事实及其证据等级由后续账本判断；
- 图片候选只使用正式 Observation 中双遍一致或仲裁后的摘录；被仲裁移除的争议小字禁止重新补入；
- 高密度标签页中的 SKU、净含量、配料、营养、储存、许可证、标准、警示等字段逐项拆为独立候选；一个候选不得同时承载两个以上字段标签和值；
- 正文主张出现 `*1/※1/注1` 等脚注标记时，候选包必须同时保留同来源对应脚注。模型选择正文后，确定性编译器自动加入绑定脚注并固定为 `evidence`；不得靠模型记忆手工补脚注；
- 已受信检查且 `inspection_status=unreadable / not_applicable` 的来源必须生成 0 条候选包和空选择包，保留全来源编译身份；这只表示当前不可读取，不能解释为来源没有主张，最终必须登记缺口并降低完成状态；
- 候选和选择目录始终位于交付目录之外，不进入客户交付或 `data/`。

编译器只接受全部来源同时具备候选包、选择包、`claim_extract` 和 `claim_recheck` 的批次。它按来源清单顺序和候选顺序生成全局连续 `CLM-`，自动复制 `claimed_at/rechecked_at` 并设置关键字段 `critical=true`。生成分包后仍须使用 `merge_product_value_ledger_parts.py --ledger claims` 合并，并运行 `--stage claims`；脚本成功不代表本阶段已经通过。

## 三、受信工具字段映射

- 工具返回 `tabular_read_status=readable` 表示表格成功读取；写入观察账本时必须使用 `inspection_status="inspected"`，不能把 `readable` 直接复制为观察枚举。
- `inspection_status` 只允许 `inspected / unreadable / not_applicable`。
- 图片 `inspection_method="visual_stamped_card"`；XLSX/XLSM 使用 `structured_spreadsheet`；原始 PDF 文本身份使用 `document_text`；未解压归档使用 `unsupported_archive`。
- 图片 `audit_card_sha256` 必须从同一 `source_file_id` 的审计卡台账复制；非图片必须为空字符串。
- 图片 `inspected_at/first_pass_sequence` 来自 `visual_first` 事件，`second_pass_at/second_pass_sequence` 来自 `visual_second` 事件。
- 主张 `claimed_at` 来自同一来源 `claim_extract` 事件，`rechecked_at` 来自 `claim_recheck` 事件。同一来源的多条主张共享这两个时间。
- 非图片来源若由同一次 `claim_extract` 打开同时完成观察和摘录，观察 `inspected_at` 可以与主张 `claimed_at` 相同；不得虚构更早时间。
- 换新上下文后，受信事件元数据本身不能替代来源正文。宿主提供只读 `review_source` 时，必须逐来源重开并立即写完该来源的观察补充、原文主张与来源记录；高文字密度表格、FAQ、营养表默认单来源单轮，普通图片每轮不超过 3—4 个。只读重开不产生新事件，时间、序号与哈希仍复制既有受信事件。
- 图片双遍后的 `observations` 阶段只要求图片观察已经落盘；尚未执行 `claim_extract` 的非图片来源可暂缺观察记录。进入 `claims` 阶段时，所有非图片观察、原文主张与来源记录必须一并补齐，完整最终校验不放宽。
- 工具事件、清单路径、哈希和序号逐字复制，不改时、不重排、不补零、不从文件名猜测。

## 四、观察记录示例

图片记录：

```json
{"observation_id":"OBS-001","source_file_id":"SF-001","relative_path":"images/page_001.webp","content_type":"visual_stamped_card","title":"页面可见标题","visible_heading":"页面可见标题","visible_text_excerpt":"本次实际看见并复核一致的页面文字","inspection_method":"visual_stamped_card","inspection_status":"inspected","inspected_at":"2026-08-15T08:00:01.000Z","audit_card_sha256":"64位审计卡哈希","first_pass_sequence":1,"second_pass_sequence":3,"second_pass_heading":"页面可见标题","second_pass_excerpt":"本次实际看见并复核一致的页面文字","second_pass_status":"match","second_pass_at":"2026-08-15T08:10:01.000Z","text_density":"high","content_flags":["identity","sku","warning"]}
```

图片正逆序先严格比较关键事实、数字与单位、主张单位、限定语和脚注；这些内容必须一致。只有引号、空白、版式顺序或极小的描述性文字差异可以由宿主的确定性比较器判为一致，且必须保留比较模式；超出范围时重新打开来源仲裁，不能保留两套业务含义继续下游。

表格记录：

```json
{"observation_id":"OBS-002","source_file_id":"SF-002","relative_path":"01_商品资料.xlsx","content_type":"structured_spreadsheet","title":"商品资料表","visible_heading":"商品概览、商品参数、可见规格、价格与权益","visible_text_excerpt":"商品ID、当前选择SKU、规格、价格、品牌、生产企业、警示等已逐工作表读取","inspection_method":"structured_spreadsheet","inspection_status":"inspected","inspected_at":"2026-08-15T08:20:01.000Z","audit_card_sha256":"","first_pass_sequence":0,"second_pass_sequence":0,"second_pass_heading":"","second_pass_excerpt":"","second_pass_status":"not_applicable","second_pass_at":"","text_density":"high","content_flags":["identity","sku","transaction","warning"]}
```

## 五、原文主张与来源示例

```json
{"claim_id":"CLM-001","source_file_id":"SF-002","observation_id":"OBS-002","claim_type":"sku","label":"当前选择","verbatim_text":"当前选择 1盒（内含5片）","normalized_value":"1盒（内含5片）","unit":"","visual_locator":"工作表：可见规格 A2:C2","critical":true,"claim_status":"match","claimed_at":"2026-08-15T08:20:01.000Z","rechecked_at":"2026-08-15T08:30:01.000Z"}
```

规则：

- `normalized_value` 必须是 `verbatim_text` 中原样存在的连续文本；不能写分析者摘要。无法保证时可以使用空字符串。
- `sku / ingredient / nutrition / storage / warning` 的 `critical` 必须为 `true`。
- `source_quotes` 在事实中必须逐条完整复制这里的 `verbatim_text`，不得缩写或换词。

```json
{"source_id":"SRC-001","source_file_id":"SF-002","observation_id":"OBS-002","source_type":"product_page","title":"商品资料表","locator":"01_商品资料.xlsx｜工作表：可见规格 A2:C2","captured_at":"2026-08-15T08:20:01.000Z","sku_scope":"当前选择 1盒（内含5片）","status":"read","notes":"价格和销量为采集时点快照"}
```

`title` 必须与对应观察记录 `title` 完全一致；`locator` 必须包含清单中的真实 `relative_path`。

## 六、事实示例

页面事实：

```json
{"fact_id":"F-001","fact_type":"F-PAGE","statement":"当前选择为1盒（内含5片）。","source_id":"SRC-001","claim_ids":["CLM-001"],"source_quotes":["当前选择 1盒（内含5片）"],"locator":"01_商品资料.xlsx｜工作表：可见规格 A2:C2","sku_scope":"当前选择 1盒（内含5片）","time_scope":"采集时点快照","status":"active","boundary":"只确认当前可见选择，不外推其他规格。"}
```

一条事实只合并能被其 `claim_ids/source_quotes` 完整覆盖的字段。数字、警示对象、动作、配料、储存、证号和规格不能靠另一条未引用主张补链。必要时拆成多条原子事实。

证据事实除普通字段外还必须增加：

```json
{"fact_id":"F-002","fact_type":"F-EVIDENCE","statement":"页面公开展示一项检测结论。","source_id":"SRC-002","claim_ids":["CLM-010"],"source_quotes":["页面可见检测结论原文"],"locator":"images/page_010.webp","sku_scope":"当前SKU","time_scope":"页面采集时点","status":"active","boundary":"当前只有页面截图级证据，不引用未核验小字。","evidence_detail_confidence":"medium","exact_fields_verified":false,"verification_locator":"页面截图可见区域"}
```

`evidence_detail_confidence` 只允许 `high / medium / low`，`exact_fields_verified` 必须是布尔值。页面图片通常是 `medium + false`；只有报告原件/PDF可定位文本或官方验证页才可把精确字段标为已核验。

## 七、FABE 示例

```json
{"fabe_id":"FABE-001","value_id":"V-001","feature":"页面列出当前SKU的三步使用方法。","feature_fact_ids":["F-003"],"advantage":"把当前商品的使用动作按顺序列出，减少当次查找步骤的负担。","benefit":"用户更容易按页面顺序完成使用。","evidence":"页面可核对三步使用方法原文。","evidence_fact_ids":["F-003"],"reference_frame":"当前操作任务是是否需要在多个页面寻找使用顺序。","reference_fact_ids":["F-003"],"user_language":"先做什么、后做什么","derivation_status":"reasoned","boundary":"这是基于页面用法的任务推导，不证明效果更好或不需要专业指导。"}
```

- 模型添加了“用户更容易、减少步骤、便于选择”等任务翻译时，通常使用 `reasoned`，不能写 `page_supported`。
- 只有 Advantage 和 Benefit 的完整句子都能在所引原文中逐字找到，才使用 `page_supported`。
- 不写“相比普通产品”“其他产品没有”“一件搞定全部”等无真实参照的比较。
- Feature、Evidence、Reference 三组文字中的数字与关键语义必须分别由自己对应的事实数组支持。

## 八、识别锚、价值与 P0 示例

```json
{"anchor_id":"ANCHOR-001","anchor_type":"main","statement":"包装正面显示品牌名与商品名。","fact_ids":["F-001"],"status":"active","boundary":"识别锚只用于认出商品，不等于购买理由。"}
```

JSON 字符串内部需要引号时必须写 `\"被引用文字\"`，不能直接嵌入未转义双引号。

```json
{"value_id":"V-001","layer":"P0","p0_candidate":true,"p0_status":"P0-HYPOTHESIS","user_task":"用户希望按明确页面说明完成当前商品的使用。","value_statement":"页面把当前SKU的使用动作按顺序列出，帮助用户完成当次操作。","supporting_fact_ids":["F-003"],"strategic_potential":"medium","execution_maturity":"medium","user_perception_goal":"看懂并记住关键使用顺序。","sku_scope":"当前SKU","scope":"当前已分析SKU","cannot_prove":["不能证明所有用户都能独立完成。","不能证明使用效果优于同类。"],"downstream_readiness":"conditional"}
```

`cannot_prove` 永远是 JSON 数组，不能写成分号连接的字符串。没有用户资料和竞争对照、且 `SC0/SC1` 时，推荐 P0 的 `p0_status` 与决策状态都使用 `P0-HYPOTHESIS`。

```json
{"decision_id":"P0D-001","candidate_value_ids":["V-001","V-002"],"recommended_value_id":"V-001","status":"P0-HYPOTHESIS","rationale":"当前先把页面支持更完整的使用任务作为优先验证方向。","public_rationale":"当前优先验证用户是否重视清晰的使用顺序。","current_execution_axis":"页面把当前SKU的使用动作按顺序列出，帮助用户完成当次操作。","current_execution_value_ids":["V-001"],"cannot_prove":["不能证明该方向已获多数用户认可。"],"validation_questions":["用户是否能准确复述关键使用顺序？"],"decided_at":"","valid_until":"","supersedes":""}
```

- `candidate_value_ids` 必须与所有 `p0_candidate=true` 的价值完全一致；P2 资质和参数不能为凑候选机械进入。
- `current_execution_axis` 必须按 `current_execution_value_ids` 顺序逐字拼接对应 `value_statement`，不得自由改写。

## 九、缺口示例

```json
{"gap_id":"GAP-001","category":"用户资料","missing":"缺少当前目标用户原声。","impact":"无法确认优先验证方向是否是多数用户的核心购买理由。","minimum_needed":"补充同一SKU的用户访谈或评论抽样。","priority":"P1","state":"open"}
```

## 十、最终原则

- 示例只规定字段和边界，不替代本次商品事实。
- 不为通过校验删除真实警示、降低文字密度、取消关键标记或改写受信时间。
- 分阶段通过不等于正式交付；两份报告生成后仍必须执行完整最终校验，退出码为 0、错误 0、警告 0 才能交付。

## 十一、长样本分析包

当事实超过 40 条、来源超过 8 个或一次分析调用无法返回计划时，先生成只含 Claim 短索引的只读包，再显式选择最多 120 个已经进入事实账本的真实 `claim_id` 生成紧凑分析包。索引默认每页最多120条并披露总数、本页数、省略数和 offset；定向包只附带本次选中索引。紧凑包必须保留总事实数、稳定事实数、动态事实数、实际返回数、省略数和选择列表；默认不把动态交易事实送入长期价值分析。

紧凑分析只优化上下文，不改变正式账本：

- 不得删除未入包事实、改写事实状态或声称未入包内容不存在；
- 冲突事实、高风险警示、适用边界、关键身份、候选机制与不可读来源缺口优先纳入；
- 模型只能引用包中事实已绑定的真实 `claim_id`，需要补充时另生成补包；
- 分析完成后仍对完整正式账本运行 `--stage analysis` 和最终校验。
