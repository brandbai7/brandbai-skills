---
name: brandbai-tmall-download
description: Collect public Tmall or Taobao item pages through a visible signed-in Chrome session, including product title, shop, parameter table, source-visible SKU options, volatile price/sales/stock snapshots, main images, detail images, available product video, and source-visible reviews or follow-ups. Use for 天猫商品详情页下载、主图与详情图下载、商品视频、规格参数和 SKU 快照、评价滚动采集、多个商品链接批量采集、DataTool 类普通版 Excel 与 ZIP 交付，以及为后续商品价值底座保留可回溯原始事实。默认只完成采集与质量说明，不自动生成商品价值、卖点、用户语义或商业结论。
license: PolyForm-Noncommercial-1.0.0
metadata:
  author: 布兰德老白 BrandBAI
  version: "0.1.0"
  category: content-commerce
---

# BrandBAI 天猫商品资料下载

把一个或多个公开天猫／淘宝商品链接转成可续跑、可回溯的商品资料、媒体、规格、SKU 快照和页面可见评价。下载阶段只记录来源事实与完整性，不替后续商品价值 Skill 下结论。

## 先确认授权范围

只在 [PolyForm Noncommercial License 1.0.0](references/license.md) 允许的非商业范围内运行。企业内部使用、客户交付、收费服务、插件、SaaS、数据服务或其他预期商业用途，必须先通过 `brandlaobai@163.com` 取得 BrandBAI 书面商业授权。安装源码不等于取得平台数据授权或商业许可。

## 路由任务

先把用户需求整理为四项：

1. 商品范围：一个或多个 `detail.tmall.com`／`item.taobao.com` 商品链接。
2. 采集模式：`product`、`reviews` 或 `all`。
3. 素材范围：`main_images`、`detail_images`、`video`、`review_media` 或 `none`。
4. 评价范围：全部当前可返回评价，或明确样本上限。

三个模式：

- `product`：商品标题、店铺、参数、页面可见 SKU 选项、快照字段和所选素材。
- `reviews`：一个或多个商品当前页面可返回的评价与追评，保留平台折叠提示和终止状态。
- `all`：商品资料、评价、普通版 Excel 与可选 ZIP 一次完成。

多个链接会在同一个可见 Chrome 上下文中顺序处理。不要为主图、详情、评价另拆登录资料夹或重复启动并行采集。

## 遵守采集边界

- 只通过用户可见、正常登录的 Chrome 页面访问公开内容。
- 首次登录、验证码、滑块或访问确认由用户手动完成。
- 不绕过访问控制、平台签名、频率限制、登录要求或平台折叠规则。
- 不导出 Cookie、请求头、验证码、浏览器资料夹、账户信息、收货地区或签名材料。
- 价格、促销、销量、库存、排行和选中 SKU 都是采集时点快照，不写成永久商品事实。
- “全部评价”只表示采集时页面能够继续返回并收到终止信号的全部可见评价。出现平台折叠提示时必须标记 `partial_platform_folded`。
- 评价者默认稳定化名；只有得到明确授权和合法业务需要时才增加 `--retain-masked-author` 保留页面遮罩名。
- 评价中的身份、购买、功效和体验主张仍需后续核验，不能因下载成功升级为商品事实。

首次运行前阅读 [浏览器路线](references/browser-route.md)；验收前阅读 [采集完成标准](references/collection-contract.md)；生成普通版交付前阅读 [导出格式](references/export-format.md)。

## 准备环境

需要 Python 3.10+、Google Chrome、可交互桌面和网络连接：

```powershell
python -m pip install -r requirements-browser.txt
```

正式采集默认启动本机 Google Chrome。私有登录资料夹必须放在仓库、同步盘和交付目录之外；第一次使用新的资料夹时，在正式命令中增加 `--login-wait 180`，在可见窗口里手动完成登录后等待采集继续。

## 先做 Dry Run

任何正式采集都先运行：

```powershell
python scripts/run_foundation.py all `
  --item "<天猫商品链接>" `
  --profile-dir "<私有Chrome资料夹>" `
  --out "<BrandBAI普通版交付目录>" `
  --assets "main_images,detail_images,video" `
  --zip `
  --dry-run
```

核对商品 ID、链接数量、素材范围、评价上限、隐私模式和输出位置，再去掉 `--dry-run`。

## 常用任务

### 商品资料与素材

```powershell
python scripts/run_foundation.py product `
  --item "<天猫商品链接>" `
  --profile-dir "<私有Chrome资料夹>" `
  --out "<交付目录>" `
  --login-wait 180 `
  --assets "main_images,detail_images,video"
```

未观察到视频时记录为未观察到，不伪造下载失败。主图和详情图只接受明确媒体白名单，不把头像、埋点、登录信标、插件图标或页面装饰混入交付。

### 页面可见评价

```powershell
python scripts/run_foundation.py reviews `
  --item "<天猫商品链接>" `
  --profile-dir "<同一私有Chrome资料夹>" `
  --out "<交付目录>" `
  --review-limit 0
```

`--review-limit 0` 表示持续滚动到页面当前不再追加。设置正整数时只采样指定条数，状态固定为 `partial_limit_sample`。若页面提示折叠评价，即使滚到当前源末端也保留 `partial_platform_folded`。

### 多商品批量采集

```powershell
python scripts/run_foundation.py all `
  --item "<商品链接1>" `
  --item "<商品链接2>" `
  --item "<商品链接3>" `
  --profile-dir "<私有Chrome资料夹>" `
  --out "<交付目录>" `
  --review-limit 500 `
  --assets "main_images,detail_images" `
  --zip
```

首发版本以明确商品链接列表为稳定输入，不自动抓取店铺全店、不读取购物车，也不把搜索页排名当成完整商品集合。

## 断点续跑

长评价列表被中断后，使用完全相同的商品范围、隐私模式和输出目录，并增加 `--resume`：

```powershell
python scripts/run_foundation.py all `
  --item "<原商品链接>" `
  --profile-dir "<原私有Chrome资料夹>" `
  --out "<原交付目录>" `
  --assets "main_images,detail_images" `
  --resume
```

续跑按稳定评价 ID 去重。平台没有公开评价 ID 时使用带 `derived:` 前缀的兜底 ID；它只支持本批去重与回溯，证据强度低于平台 ID。

## 普通版交付

`all` 模式生成：

- `01_商品资料.xlsx`
- `02_评价明细.xlsx`
- `03_商品素材/`
- `04_采集说明.md`
- `data/商品采集/`、`data/评价采集/` 和运行 manifest

增加 `--zip` 时在交付目录同级生成 ZIP64 压缩包。ZIP 不得包含私有 Chrome 资料夹、Cookie、任务缓存或 QA 文件。

普通版 Excel 只呈现商品事实、快照、素材、评价和完整性。不要在下载 Skill 中添加 P0、卖点、功效结论、用户语义、商品定位或竞品判断；这些由后续 BrandBAI Product Value Skill 读取稳定商品 ID 和原始证据后完成。

## 判定完成状态

- 商品资料与所选媒体都已写入，或明确记录公开不可用，才可标记 `complete_observed_product`。
- 页面可见评价滚动到当前源末端且无折叠提示，才可标记 `complete_visible_panel_exhausted`。
- 平台显示折叠评价：`partial_platform_folded`。
- 达到用户样本上限：`partial_limit_sample`。
- 登录或验证阻断：`partial_login_or_verification`。
- 页面结构变化无法定位：`partial_selector_drift`。
- 退出码 `3` 表示结果可以保留和续跑，但不得写成完整下载。

## 验证修改

在 `scripts/` 目录运行：

```powershell
python -m unittest test_collector_core.py test_build_delivery.py test_run_foundation.py
```

这些测试只使用合成商品与评价，不打开天猫、不启动 Chrome，也不产生付费请求。
