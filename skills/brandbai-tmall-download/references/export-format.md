# 普通版导出格式

```text
BrandBAI_天猫商品资料_<对象>_<日期>/
├─ 01_商品资料.xlsx          # product / all
├─ 02_评价明细.xlsx          # reviews / all
├─ 03_问大家.xlsx            # questions / all
├─ 03_商品素材/
├─ 04_采集说明.md
└─ data/
   ├─ run_manifest.json
   ├─ delivery_manifest.json
   ├─ 商品采集/<item_id>/
   ├─ 评价采集/<item_id>/
   └─ 问答采集/<item_id>/
```

- `01_商品资料.xlsx`：商品总览、规格参数、SKU 快照、素材索引、商品完整性。
- `02_评价明细.xlsx`：评价与追评原文、稳定或兜底 ID、匿名作者、规格、媒体数量和采集状态。
- `03_问大家.xlsx`：问题清单、回答明细和采集状态。

没有请求的数据集不生成空工作簿。三项数据各自保留独立状态，不能因为其中一项成功就覆盖另一项的部分状态。

后续商品价值或用户语义 Skill 读取稳定 `product_id`、`item_id`、原始字段和完整性状态；分析可以新增结论，但不得改写下载包中的来源字段。
