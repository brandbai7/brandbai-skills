---
name: brandbai-tmall-download
description: Download public Tmall or Taobao item-page data through a visible signed-in Chrome session. Use for 商品资料包、主图与详情图、可见视频、规格参数、SKU 与价格销量库存快照，以及独立下载全部评价或问大家问题和回答，生成普通版 Excel、ZIP 和可回溯原始数据。商品资料、评价和问大家是三项独立能力；默认只做下载与质量说明，不自动生成商品价值、卖点、用户语义或商业结论。
license: PolyForm-Noncommercial-1.0.0
metadata:
  author: 布兰德老白 BrandBAI
  version: "0.2.0"
  category: content-commerce
---

# BrandBAI 天猫／淘宝商品下载

把一个或多个公开天猫／淘宝商品链接整理为可回溯的商品资料、商品素材、评价或问大家数据。三类数据相互独立：下载商品资料包不要求用户先展开评价或问大家；评价和问大家只有在用户打开相应“全部”面板后才继续滚动采集。

## 先确认授权范围

只在 [PolyForm Noncommercial License 1.0.0](references/license.md) 允许的非商业范围内运行。企业内部使用、客户交付、收费服务、插件、SaaS、数据服务或其他预期商业用途，必须先通过 `brandlaobai@163.com` 取得 BrandBAI 书面商业授权。安装源码不等于取得平台数据授权或商业许可。

## 路由任务

选择运行模式：

- `product`：商品标题、店铺、参数、页面可见 SKU、价格／销量／库存快照，以及所选主图、详情图和视频。
- `reviews`：独立下载页面当前可返回的评价与追评。
- `questions`：独立下载问大家的问题和页面可见回答。
- `all`：按顺序处理三类数据；评价和问大家仍分别遵守完整面板要求。

商品资料包不包含评价和问大家。用户只需要素材或商品事实时使用 `product`，不要为两个长列表增加不必要的滚动。

## 遵守采集边界

- 只通过用户可见、正常登录的 Chrome 页面访问公开内容。
- 登录、验证码、滑块、访问确认，以及“查看全部评价／查看全部问答”的点击由用户手动完成。
- 不绕过访问控制、平台签名、频率限制、登录要求或平台折叠规则。
- 不导出 Cookie、请求头、验证码、浏览器资料夹、账户信息、收货地区或签名材料。
- 价格、促销、销量、库存、排行和选中 SKU 都是采集时点快照，不写成永久商品事实。
- “全部评价／全部问答”只表示本次页面可继续返回并收到终止信号的全部可见内容，不代表平台内部绝对全量。
- 评价和回答者默认稳定化名；其中的身份、购买、功效和体验主张仍需后续核验。

运行前阅读 [浏览器路线](references/browser-route.md)，验收前阅读 [采集完成标准](references/collection-contract.md)，交付前阅读 [导出格式](references/export-format.md)。

## 准备环境

需要 Python 3.10+、Google Chrome、可交互桌面和网络连接：

```powershell
python -m pip install -r requirements-browser.txt
```

私有 Chrome 资料夹必须放在仓库、同步盘和交付目录之外。正式采集前一律增加 `--dry-run` 核对商品 ID、数据范围、素材范围、样本上限和输出目录。

## 常用任务

### 商品资料包

```powershell
python scripts/run_foundation.py product `
  --item "<天猫或淘宝商品链接>" `
  --profile-dir "<私有Chrome资料夹>" `
  --out "<交付目录>" `
  --login-wait 180 `
  --assets "main_images,detail_images,video" `
  --zip `
  --dry-run
```

未观察到视频时记录为公开未观察到，不伪装成下载失败。商品素材只接受明确媒体白名单，不把头像、埋点、登录信标、插件图标或页面装饰混入交付。

### 独立下载评价

```powershell
python scripts/run_foundation.py reviews `
  --item "<商品链接>" `
  --profile-dir "<同一私有Chrome资料夹>" `
  --out "<交付目录>" `
  --login-wait 180 `
  --review-limit 0 `
  --zip
```

运行时 Skill 会定位并高亮“查看全部评价”。用户点击后等待采集继续；未打开完整面板时保存当前状态为 `partial_requires_full_review_panel`，不会把首页两条评价当成全部。

### 独立下载问大家

```powershell
python scripts/run_foundation.py questions `
  --item "<商品链接>" `
  --profile-dir "<同一私有Chrome资料夹>" `
  --out "<交付目录>" `
  --login-wait 180 `
  --question-limit 0 `
  --zip
```

运行时 Skill 会定位并高亮“查看全部问答”。用户点击后采集问题、展开当前可见“查看全部回答”并滚动到可见源末端。未打开完整面板时标记 `partial_requires_full_question_panel`。

### 多商品批量

重复使用 `--item`，所有商品在同一个可见 Chrome 上下文中顺序处理：

```powershell
python scripts/run_foundation.py product `
  --item "<商品链接1>" `
  --item "<商品链接2>" `
  --item "<商品链接3>" `
  --profile-dir "<私有Chrome资料夹>" `
  --out "<交付目录>" `
  --assets "main_images,detail_images" `
  --zip
```

稳定输入是明确商品链接列表，不自动抓取店铺全店、不读取购物车，也不把搜索页排名当成完整商品集合。

## 普通版交付

按实际请求生成：

- `01_商品资料.xlsx`：仅 `product` 或 `all`
- `02_评价明细.xlsx`：仅 `reviews` 或 `all`
- `03_问大家.xlsx`：仅 `questions` 或 `all`
- `03_商品素材/`
- `04_采集说明.md`
- `data/商品采集/`、`data/评价采集/`、`data/问答采集/` 与 manifest

增加 `--zip` 后在交付目录同级生成 ZIP64 压缩包。ZIP 不得包含私有 Chrome 资料夹、Cookie、任务缓存或 QA 文件。

## 判定完成状态

- 商品资料和所选媒体已写入，或明确记录公开不可用：`complete_observed_product`。
- 评价未打开完整面板：`partial_requires_full_review_panel`；滚动到当前可见源末端且无折叠提示：`complete_visible_panel_exhausted`。
- 问大家未打开完整面板：`partial_requires_full_question_panel`；问题和回答到达当前可见源末端：`complete_visible_qa_exhausted`。
- 平台显示折叠评价：`partial_platform_folded`。
- 页面提示数量大于实际保存量：保留相应 `partial_*_below_page_hint` 状态。
- 达到用户设置的正数上限：`partial_limit_sample`。
- 登录验证阻断或页面定位变化只能标记部分完成。
- 退出码 `3` 表示数据可保留和续跑，但不得写成完整下载。

## 续跑与后续分析

长列表中断后，使用完全相同的商品范围、隐私模式和输出目录，并增加 `--resume`。评价、问题和回答按稳定 ID 去重；平台没有公开 ID 时使用 `derived:` 兜底 ID，只用于本批去重与回溯。

本 Skill 只下载来源事实与状态。商品价值、卖点、用户语义、定位和竞品判断由后续 Skill 读取稳定商品 ID、原始字段与完整性状态后完成。

## 验证修改

在 `scripts/` 目录运行：

```powershell
python -m unittest test_collector_core.py test_browser_collect_tmall.py test_build_delivery.py test_run_foundation.py
```

这些测试只使用合成商品、评价和问答，不打开天猫／淘宝、不启动 Chrome，也不产生付费请求。
