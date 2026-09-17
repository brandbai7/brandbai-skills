# 同一商品身份与独立下载 · 0.21.0

## 用户旅程

先看本场商品编号目录，再选择重点商品。图片规格和买家评价放在同一张“当前研究商品”卡中，只保留一个重新识别入口；两种下载仍为独立按钮、独立进度与独立 ZIP，无需先录屏或先下载另一种资料。不会自动合成一个大包，也不会批量打开其他商品。

详情与评价读取同一内容脚本的商品上下文。开始任务时冻结面板、商品和房间；切换 SKU 不改变商品身份。异步准备期间重新核对，切换商品或已知 ID 变化即停止／拒绝；不得把新商品覆盖到在途任务。无 ID 商品关闭再打开后产生新的观察标识。关闭侧栏后任务进度可恢复，商品卡继续显示在途任务的商品。

## 公共身份字段

每个目录条目、单商品资料与评价包的 `product_identity` 采用同一字段集：

| 字段 | 含义与边界 |
| --- | --- |
| platform | douyin |
| product_id | 平台商品 ID，字符串；缺失为 null |
| product_url | 实际观察到的允许列表公开商品 URL，仅保留 id；不构造缺失链接 |
| product_ref | 真实 ID：douyin:product:ID；否则 douyin:observation:UUID，仅表示本次面板观察 |
| identity_status | verified／panel_bound／unconfirmed；verified 仅表示有明确 ID 证据，不代表内容真实性 |
| product_id_source | public_product_link／visible_dom_attribute／not_observed |
| shop_id、shop_name、shop_id_source | 有明确店铺属性才保存 ID；名称不用于推算 ID |
| source_room_id、source_room_url | 公开直播间来源，不能当作商品 ID |
| catalog_position、catalog_observed_at_epoch_ms | 列表几号链接及对应观察时间；只有同房间、真实商品 ID 相同才把目录映射带入详情／评价，不按标题补配 |
| observed_at_epoch_ms | 本次商品身份观察时间；不是评价发表时间、SKU 价格时间或历史弹窗时间 |

商品／店铺／SKU ID 不转数值，避免长整数精度损失。后端验证字段、公开 URL ID 一致性、房间归属及来源枚举，未知不得伪造。禁用隐藏状态对象、网络拦截、请求头、私有接口和收货／支付字段。

## 后续关联

跨次、跨日下载：以 platform + product_id 关联；冲突的已知店铺 ID 不自动合并。product_ref 为观察标识时，只能关联同一打开面板中沿用该标识的两次下载，不能按同名跨页面合并。目录是带时间的独立快照，不宣称当前全场编号恒定，也不能回填此前话术的编号。

单商品包增加 `商品身份.json`，同时写入商品资料 JSON、下载清单及 SKU 图片映射。目录 JSON 每个条目均包含公共身份；ID 缺失时保持 null。评价包也增加 `商品身份.json`，完整性 JSON 和每条 JSONL 带公共身份，CSV 附带关联列，便于分别交给后续提示词再核对。既有历史包不改写、不推断补 ID。

SKU 资料按确认后的可见组合保存 `sku_id`、`sku_id_source` 与价格观察时间。只有当前面板明确 selected-sku 属性或唯一单规格组选中项明确 sku-id 属性才填写；多组选项的 value-id 不能当作组合 SKU ID。未知为 null。评价的 purchased_sku 保留历史原文；评价 SKU ID 未取得时为 null，不能复制当前选择的 SKU ID。`captured_at_epoch_ms` 是该批评价第一次落盘的时间，评价发表时间另存原文。

## 验收门槛

测试真实 ID 跨包关联、未知 ID 不跨观察合并、同名不同 ID 拒绝、切规格身份稳定、关闭重开未知面板换观察键、目录映射带时间、历史评价规格不误挂当前 SKU、在途侧栏恢复、额外私有字段拒绝。隔离合成测试、发布包校验、真实页面下载验收分别报告。不能因为结构字段已具备就声称平台所有商品都能取得 ID。
