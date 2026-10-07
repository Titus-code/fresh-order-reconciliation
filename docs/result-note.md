# 对账项目结果说明

## 交付内容

本项目把 2026 年 9 月生鲜配送的订单明细、实际交付、签收退货和回款分配整理成订单级、客户级对账结果。样本为固定种子生成的模拟数据，包含 143 张订单、966 条明细、6 家客户、7 笔整笔收款和 100 条订单分配记录。

Excel 原型位于 `excel/对账原型.xlsx`。`checklist` 是入口页，`calc_lines` 保留逐行计算和异常检查，`calc_orders`、`calc_customers` 依次汇总到订单和客户，`pivot_report` 提供客户、商品和日期三个交叉汇总视图，原始 CSV 保留在 `raw_*`、`dim_*` 和 `fact_*` 工作表中。

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
- 截止日之后的分配记录归类为“口径排除”，不会计入已收，也不作为数据质量异常。
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

MySQL 建表和查询脚本保留在 `sql/` 作为生产迁移参考；本地自动化验证使用 SQLite，并通过整数分换算避免 SQLite NUMERIC 亲和性引入浮点误差。
