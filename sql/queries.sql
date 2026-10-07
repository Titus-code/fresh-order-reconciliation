-- 对账查询。整段可直接在 MySQL 8.0 执行；
-- 也支持 SQLite（见 sql/verify_sqlite.py，脚本会自动改写 CREATE OR REPLACE VIEW 与 @cutoff）。
-- 只需把 @cutoff 改成需要的对账日，例如 2026-09-30。
--
-- 金额一律走"分"（整数）运算，这是刻意的设计，不是绕弯：
--   1. 数量一位小数，乘 10 存成整数；单价两位小数，乘 100 存成整数。
--   2. 明细净额 = (交付量×10 × 单价×100 + 5) / 10，整数除法天然等于四舍五入到分，
--      与 Python Decimal(ROUND_HALF_UP) 和 Excel ROUND 完全一致。
--   3. 如果直接用 DECIMAL 相乘，SQLite 的 NUMERIC 亲和性会先转成浮点，
--      汇总后出现 1212.6799999999998、余额 -2.27e-13 这类结果；
--      MySQL 的 DECIMAL 本身精确，但两套引擎就对不上了。
--      统一用整数分，两个引擎结果完全一致。
--   4. CAST(x AS INTEGER) 是"截断"，但输入本身已是整数值，截断不会损失精度；
--      这一句同时兼容 MySQL 和 SQLite。
--
-- 注意：数量列字段名沿用 _qty，内部按"十分之一公斤"整数处理。

-- 换算约定（本文件内所有 REPLACE(x,'.','') 都依赖它）：
--   数量列固定一位小数，REPLACE 后即"十分之一公斤"整数：'4.1' -> 41、'0.0' -> 00
--   金额列固定两位小数，REPLACE 后即"分"整数：       '4.60' -> 460、'71.00' -> 7100
-- 这两个位数不变式由 scripts/generate_sample_data.py 和 check_sample_data.py 保证：
-- 生成器对数量统一 quantize 到 0.1、金额统一 quantize 到 0.01，
-- 检查脚本也断言每个值的位数合法（assert len(fraction) <= places）。
-- 换成真实数据前，务必先跑一次位数检查，否则这里会算错。
--
-- 为什么不写 CAST(x * 10 AS INTEGER)：那是浮点乘法。
-- SQLite 里 CAST('4.60' AS REAL) * 100 = 459.99999999999994，截断成 459，
-- 每行少一分，整月汇总差 8 元；MySQL 用 DECIMAL 列时不会踩到，
-- 但两套引擎结果就对不上了。走字符串去掉小数点，全程只有整数运算。

SET @cutoff = '2026-10-06';

-- Q1 明细净应收：交付金额、退货金额分别四舍五入到分，再相减。
SELECT
  order_id,
  line_no,
  customer_id,
  order_date,
  product_id,
  unit,
  ordered_qty,
  delivered_qty,
  returned_qty,
  unit_price,
  CAST((CAST(REPLACE(delivered_qty, '.', '') AS INTEGER) * CAST(REPLACE(unit_price, '.', '') AS INTEGER) + 5) / 10 AS INTEGER) AS gross_fen,
  CAST((CAST(REPLACE(returned_qty,  '.', '') AS INTEGER) * CAST(REPLACE(unit_price, '.', '') AS INTEGER) + 5) / 10 AS INTEGER) AS return_fen,
  CAST((CAST(REPLACE(delivered_qty, '.', '') AS INTEGER) * CAST(REPLACE(unit_price, '.', '') AS INTEGER) + 5) / 10 AS INTEGER)
 - CAST((CAST(REPLACE(returned_qty,  '.', '') AS INTEGER) * CAST(REPLACE(unit_price, '.', '') AS INTEGER) + 5) / 10 AS INTEGER) AS net_fen
FROM order_lines
ORDER BY order_id, line_no;

-- Q2 订单级应收。先把 966 行明细汇总到 143 张订单，得到订单层唯一一行。
CREATE OR REPLACE VIEW v_order_net AS
SELECT
  order_id,
  MIN(customer_id) AS customer_id,
  MIN(order_date)  AS order_date,
  COUNT(*)         AS line_count,
  SUM(CAST((CAST(REPLACE(delivered_qty, '.', '') AS INTEGER) * CAST(REPLACE(unit_price, '.', '') AS INTEGER) + 5) / 10 AS INTEGER)
    - CAST((CAST(REPLACE(returned_qty,  '.', '') AS INTEGER) * CAST(REPLACE(unit_price, '.', '') AS INTEGER) + 5) / 10 AS INTEGER)) AS net_fen
FROM order_lines
GROUP BY order_id;

-- Q3 订单级已收（截至对账日）。同样先汇总，再去关联。
CREATE OR REPLACE VIEW v_order_received AS
SELECT order_id, SUM(CAST(REPLACE(amount, '.', '') AS INTEGER)) AS received_fen
FROM payments
WHERE payment_date <= @cutoff
GROUP BY order_id;

-- Q4 订单对账表。LEFT JOIN 保证还没收到款的订单也在结果里，不会被漏掉。
SELECT
  n.order_id,
  n.customer_id,
  c.customer_name,
  n.order_date,
  n.line_count,
  n.net_fen / 100.0 AS net_receivable,
  COALESCE(r.received_fen, 0) / 100.0 AS received,
  (n.net_fen - COALESCE(r.received_fen, 0)) / 100.0 AS balance,
  CASE WHEN n.net_fen = COALESCE(r.received_fen, 0) THEN '已结清' ELSE '未结清' END AS status
FROM v_order_net n
JOIN customers c ON c.customer_id = n.customer_id
LEFT JOIN v_order_received r ON r.order_id = n.order_id
ORDER BY n.order_id;

-- Q5 客户对账汇总。这是最终交付结果，必须与 Excel 透视表、Python 输出完全一致。
-- 输出金额转成两位小数字符串，避免 0.0000000001 这类尾数影响肉眼核对。
SELECT
  n.customer_id,
  c.customer_name,
  COUNT(*)                                 AS order_count,
  SUM(n.net_fen)                   / 100.0 AS net_receivable,
  SUM(COALESCE(r.received_fen, 0)) / 100.0 AS received,
  (SUM(n.net_fen) - SUM(COALESCE(r.received_fen, 0))) / 100.0 AS balance
FROM v_order_net n
JOIN customers c ON c.customer_id = n.customer_id
LEFT JOIN v_order_received r ON r.order_id = n.order_id
GROUP BY n.customer_id, c.customer_name
ORDER BY n.customer_id;

-- Q6 异常：主键重复。本样本应返回 0 行。
SELECT 'order_lines' AS source_file, order_id AS record_key, COUNT(*) AS dup_count,
       '订单明细主键重复' AS kind
FROM order_lines GROUP BY order_id, line_no HAVING COUNT(*) > 1
UNION ALL
SELECT 'payments', payment_id, COUNT(*), '分配记录主键重复'
FROM payments GROUP BY payment_id HAVING COUNT(*) > 1;

-- Q7 异常：数量、单位、金额不合规。本样本应返回 0 行。
-- 比较数量必须先把字符串去掉小数点变成整数，不能直接拿文本比大小：
-- 文本比较是按字符逐位比的，'9.6' > '10.1' 成立（因为 '9' > '1'），
-- 会报出一堆假的"交付大于下单"。这是本次构建真实踩到的坑。
SELECT line.order_id, line.line_no, line.customer_id, line.product_id,
       CASE
         WHEN CAST(REPLACE(line.returned_qty,  '.', '') AS INTEGER)
            > CAST(REPLACE(line.delivered_qty, '.', '') AS INTEGER) THEN '退货大于交付'
         WHEN CAST(REPLACE(line.delivered_qty, '.', '') AS INTEGER)
            > CAST(REPLACE(line.ordered_qty,   '.', '') AS INTEGER) THEN '交付大于下单'
         WHEN line.unit <> p.unit                    THEN '单位与商品表不一致'
         WHEN CAST(REPLACE(line.unit_price, '.', '') AS INTEGER) < CAST(REPLACE(p.simulated_price_min, '.', '') AS INTEGER)
           OR CAST(REPLACE(line.unit_price, '.', '') AS INTEGER) > CAST(REPLACE(p.simulated_price_max, '.', '') AS INTEGER)
                                                     THEN '单价超出模拟区间'
         ELSE '其他'
       END AS kind
FROM order_lines line
JOIN products p ON p.product_id = line.product_id
WHERE CAST(REPLACE(line.ordered_qty, '.', '') AS INTEGER) <= 0
   OR CAST(REPLACE(line.returned_qty,  '.', '') AS INTEGER)
    > CAST(REPLACE(line.delivered_qty, '.', '') AS INTEGER)
   OR CAST(REPLACE(line.delivered_qty, '.', '') AS INTEGER)
    > CAST(REPLACE(line.ordered_qty,   '.', '') AS INTEGER)
   OR line.unit <> p.unit
   OR CAST(REPLACE(line.unit_price, '.', '') AS INTEGER) < CAST(REPLACE(p.simulated_price_min, '.', '') AS INTEGER)
   OR CAST(REPLACE(line.unit_price, '.', '') AS INTEGER) > CAST(REPLACE(p.simulated_price_max, '.', '') AS INTEGER);

-- Q8 异常：回款关联不到订单 / 同一订单出现不同客户。本样本应返回 0 行。
SELECT '回款无匹配订单' AS kind, p.payment_id AS record_key, p.order_id AS detail
FROM payments p
LEFT JOIN order_lines l ON l.order_id = p.order_id
WHERE l.order_id IS NULL
UNION ALL
SELECT '订单归属冲突', order_id, customer_id
FROM order_lines
GROUP BY order_id
HAVING COUNT(DISTINCT customer_id) > 1;

-- Q9 收款流水金额与分配金额是否相符。两边都转成整数分再比，本样本应返回 0 行。
SELECT r.receipt_id, r.amount AS receipt_amount,
       COALESCE(SUM(p.amount), 0) AS allocated_amount
FROM receipts r
LEFT JOIN payments p ON p.receipt_id = r.receipt_id
GROUP BY r.receipt_id, r.amount
HAVING SUM(CAST(COALESCE(REPLACE(p.amount, '.', ''), 0) AS INTEGER)) <> CAST(REPLACE(r.amount, '.', '') AS INTEGER);

-- Q10 两个口径的已收总额，必须相等。禁止把二者相加。
SELECT 'receipts 流水口径' AS scope, SUM(CAST(REPLACE(amount, '.', '') AS INTEGER)) / 100.0 AS received_total
FROM receipts WHERE payment_date <= @cutoff
UNION ALL
SELECT 'payments 分配口径', SUM(CAST(REPLACE(amount, '.', '') AS INTEGER)) / 100.0
FROM payments WHERE payment_date <= @cutoff;

-- Q11 总账核对：与 data/expected/manifest.json 的 net_receivable 对拍，应为 44914.30。
SELECT SUM(net_fen) AS total_net_fen, SUM(net_fen) / 100.0 AS total_net_receivable
FROM v_order_net;

-- 对照实验：下面这句用 DECIMAL 直接相乘。在 SQLite 下会看到浮点尾数，
-- 在 MySQL 的 DECIMAL 下则正常——这就是本项目坚持整数分运算的原因。
-- SELECT order_id, SUM(delivered_qty * unit_price) FROM order_lines GROUP BY order_id;
