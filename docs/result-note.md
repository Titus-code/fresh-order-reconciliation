# 对账项目结果说明

## 项目输出

本项目把 2026 年 9 月生鲜配送的订单明细、实际交付、签收退货和回款分配整理成订单级、客户级对账结果。样本为固定种子生成的模拟数据，包含 143 张订单、966 条明细、6 家客户、7 笔整笔收款和 100 条订单分配记录。

Excel 工作簿位于 [对账原型.xlsx](../excel/对账原型.xlsx)。`checklist` 提供截止日控制和核对指标，`calc_lines` 保留逐行计算和检查，`calc_orders`、`calc_customers` 依次汇总到订单和客户，`pivot_report` 提供公式交叉汇总，`native_pivots` 包含三张原生透视表。原始数据保留在 `raw_*`、`dim_*` 和 `fact_*` 工作表中。工作表与公式说明见 [Excel 工作簿说明](../excel/Excel原型分步指南.md)。

## 核心结果

| 对账截止日 | 净应收 | 已收 | 未结清 |
| --- | ---: | ---: | ---: |
| 2026-09-30 | 44,914.30 | 6,000.00 | 38,914.30 |
| 2026-10-06 | 44,914.30 | 26,254.15 | 18,660.15 |

抽样订单 `SIM-20260901-C001` 的 8 条明细合计 256.60 元。截止 2026-10-06，该订单已由 10 月 2 日回款结清。

## 口径与异常

- 按实际交付数量计费，少送部分不计入应收。
- 交付金额和退货金额分别按成交单价四舍五入到分，再相减。
- `receipts` 是整笔到账视角，`payments` 是分配到订单视角，两者只做一致性核对，不能相加。
- 截止日之后的分配记录归类为“口径排除”，写入异常与排除清单，不计入已收；9 月 30 日有 84 条，10 月 6 日为 0 条。
- 重复主键、未知商品、单位不一致和数量关系错误会阻断整张订单；价格区间越界保留为风险提示。

当前正式快照没有数据质量异常。`tests/fixtures/dirty` 构造了重复主键、数量非法和未知商品，回归测试确认坏订单被暂缓、正常订单仍可出账。

## 复现命令

```bash
python -m unittest discover -s tests -v
python scripts/check_sample_data.py
python src/reconcile.py --cutoff 2026-09-30 --out outputs
python src/reconcile.py --cutoff 2026-10-06 --out outputs
python sql/verify_sqlite.py --cutoff 2026-09-30
python sql/verify_sqlite.py --cutoff 2026-10-06
```

## 验证范围

自动化验证覆盖样本快照完整性、Python 正常与异常样本回归测试，以及 SQLite 在两个截止日的客户汇总、异常检查和总账核对。Excel 工作簿提供模拟快照的公式计算与汇总，不参与 GitHub Actions 的自动重算。

MySQL 建表脚本位于 `sql/schema.sql`，作为目标环境参考；当前自动化未包含 MySQL 服务上的执行验证。SQLite 通过整数分换算保留样本的金额取整口径，具体规则见 [金额计算与交叉核对](calculation-notes.md)。
