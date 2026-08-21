# 卖点呈现账本分包合同

本合同用于避免模型把页面盘点、五个价值的六路扫描、十二槽位、VIS 与验证任务全部积压到最后一次写入。模型负责证据判断和呈现设计；脚本负责固定路由骨架、稳定编号、分包合并、计数和原子落盘。

## 一、四个强制检查点

1. 每完成一个来源或一组同页表达，立即写一份 `PEX` 小包；全部完成后合并为 `existing_expression_ledger.jsonl`。
2. 每完成一个价值的六条路径，立即写一份 `V-xxx.jsonl`；五个价值不能留到同一轮最后一起写。全部完成后合并并检查总数、每价值六条、1 主和 1—2 辅。
3. 先写核心 VIS，再扫描十二槽位；每个适用槽位必须关联现有 VIS，不适用必须空数组并写理由。
4. 最多三项验证任务和缺口完成后，更新 manifest，先 Dry Run 构建，再正式构建和完整校验。

出现以下任一情况必须停止当前大事务并改用分包：目标账本在 60 秒持续推理后仍为空、过程事件持续增加但文件没有修改、单次准备写超过 12 条长记录、或需要同时重新打开多个高文字密度来源。

## 二、准备逐价值工作包

页面表达初步盘点完成后，用当前上游和交付目录生成小型输入与固定六路骨架：

```powershell
python scripts/prepare_value_expression_work_packets.py `
  --delivery "<卖点呈现交付目录>" `
  --product-value "<商品价值底座目录>" `
  --work-dir "<交付目录之外的新工作目录>" `
  --dry-run

python scripts/prepare_value_expression_work_packets.py `
  --delivery "<卖点呈现交付目录>" `
  --product-value "<商品价值底座目录>" `
  --work-dir "<同上>"
```

工作目录生成：

```text
inputs/V-001.json       当前价值、真正支撑事实、关联页面表达和 P0 决策
six_path/V-001.jsonl    固定六条 route 与稳定 PATH 编号骨架
```

每轮只读取一个 `inputs/V-xxx.json`，只填写同名 `six_path/V-xxx.jsonl` 的 `role/translation/reason/fact_ids/expression_ids/boundary`。不得更改 `scan_id/value_id/route`，也不得跨价值借用事实。

## 三、确定性合并

所有工作分包必须位于正式交付之外。完成后先 Dry Run，再合并：

```powershell
python scripts/merge_value_expression_ledger_parts.py `
  --delivery "<卖点呈现交付目录>" `
  --ledger "<existing_expressions|six_path|slots|vis|validation|gaps>" `
  --parts-dir "<对应分包目录>" `
  --expected-count <预期总条数> `
  --dry-run

python scripts/merge_value_expression_ledger_parts.py `
  --delivery "<卖点呈现交付目录>" `
  --ledger "<同上>" `
  --parts-dir "<同上>" `
  --expected-count <同上>
```

合并器只做 JSON/JSONL 解析、稳定 ID 去重、计数和原子写入。语义、事实引用、角色数量、槽位、VIS、验证任务与边界仍由正式校验器判断。

## 四、逐阶段校验

- 使用紧凑 JSON 方案时，必须先运行 `compile_value_expression_plan.py --dry-run`；页面表达合并多个高密度标签、截图被称为原件、客户可见字段泄露内部资产 ID 或必需价值/事实引用为空时，本轮方案不得写入正式账本。
- PEX 合并后：确认每条 `PEX-` 至少回指一个有效事实，页面已有只标 `page_existing_unvalidated`。
- 六路合并后：先自行统计，再进入 VIS；不得为了凑 1 主 1 辅跨价值借事实。
- VIS 与槽位合并后：运行正式校验器；若报告尚未构建，只处理账本错误，不把报告占位提示误当内容错误。
- 验证任务合并后：检查唯一变量、两版其余条件、高风险护栏、平台行为指标与评论语义分读。
- 全部账本通过后：使用官方构建器生成 Markdown，再进行最终完整校验。

## 五、失败恢复

- 只重做失败的小包，不能清空已通过的其他价值或来源。
- 续跑默认保留当前交付与工作包；只有使用者明确要求重置时才新建版本或可恢复历史。
- 模型无法运行脚本时，说明执行能力缺口并停止，不得手写占位 ID、伪造校验通过或把运行失败写入客户版限制。
- 正式交付根目录和 `data/` 不保留工作包、生成器、修复脚本或调试文件。
