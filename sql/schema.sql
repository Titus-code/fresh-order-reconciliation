-- 建表脚本：目标环境 MySQL 8.0（utf8mb4）。
-- 字段与 data/raw/ 的 CSV 表头一一对应，全部使用 VARCHAR/INT/DECIMAL，
-- 不用 FLOAT，避免金额出现二进制浮点误差。
-- 导入顺序：customers → products → order_lines → receipts → payments。

DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS receipts;
DROP TABLE IF EXISTS order_lines;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
  customer_id           VARCHAR(16)  NOT NULL COMMENT '客户编号',
  customer_name         VARCHAR(64)  NOT NULL COMMENT '客户名称',
  customer_type         VARCHAR(32)  NOT NULL COMMENT '客户类型',
  service_area          VARCHAR(32)           COMMENT '服务区域',
  meal_scale_assumption VARCHAR(64)           COMMENT '规模假设，仅用于解释采购量',
  delivery_schedule     VARCHAR(32)           COMMENT '配送安排',
  settlement_cycle      VARCHAR(16)           COMMENT '结账周期',
  payment_due_date      DATE                  COMMENT '约定付款日',
  is_simulated          TINYINT(1)   NOT NULL DEFAULT 0,
  PRIMARY KEY (customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='客户';

CREATE TABLE products (
  product_id           VARCHAR(16) NOT NULL COMMENT '商品编号',
  product_name         VARCHAR(64) NOT NULL COMMENT '商品名称',
  specification        VARCHAR(64)          COMMENT '固定规格',
  unit                 VARCHAR(8)  NOT NULL COMMENT '计价单位',
  category             VARCHAR(16)          COMMENT '品类',
  simulated_price_min  DECIMAL(10,2)        COMMENT '模拟价格下限',
  simulated_price_max  DECIMAL(10,2)        COMMENT '模拟价格上限',
  is_simulated         TINYINT(1)  NOT NULL DEFAULT 0,
  PRIMARY KEY (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品，一行一个固定规格';

CREATE TABLE order_lines (
  order_id      VARCHAR(24)   NOT NULL COMMENT '订单编号',
  line_no       INT           NOT NULL COMMENT '订单内行号',
  customer_id   VARCHAR(16)   NOT NULL,
  order_date    DATE          NOT NULL COMMENT '下单日，本样本同时是配送日',
  product_id    VARCHAR(16)   NOT NULL,
  unit          VARCHAR(8)    NOT NULL,
  ordered_qty   DECIMAL(10,1) NOT NULL COMMENT '下单数量',
  delivered_qty DECIMAL(10,1) NOT NULL COMMENT '实际交付数量',
  returned_qty  DECIMAL(10,1) NOT NULL DEFAULT 0 COMMENT '签收退货数量',
  unit_price    DECIMAL(10,2) NOT NULL COMMENT '成交单价，不用当前价覆盖',
  delivery_note VARCHAR(128)           COMMENT '少送或退货说明',
  is_simulated  TINYINT(1)    NOT NULL DEFAULT 0,
  PRIMARY KEY (order_id, line_no),
  KEY idx_lines_customer_date (customer_id, order_date),
  KEY idx_lines_product (product_id),
  CONSTRAINT fk_lines_customer FOREIGN KEY (customer_id) REFERENCES customers (customer_id),
  CONSTRAINT fk_lines_product  FOREIGN KEY (product_id)  REFERENCES products (product_id),
  CONSTRAINT chk_lines_qty CHECK (0 <= returned_qty AND returned_qty <= delivered_qty
                                  AND delivered_qty <= ordered_qty AND ordered_qty > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单明细';

CREATE TABLE receipts (
  receipt_id      VARCHAR(16)   NOT NULL COMMENT '收款流水号',
  customer_id     VARCHAR(16)   NOT NULL,
  payment_date    DATE          NOT NULL,
  amount          DECIMAL(12,2) NOT NULL COMMENT '整笔收款金额',
  payment_method  VARCHAR(16)            COMMENT '收款方式',
  settlement_month VARCHAR(7)            COMMENT '结算月份',
  memo            VARCHAR(64),
  is_simulated    TINYINT(1)    NOT NULL DEFAULT 0,
  PRIMARY KEY (receipt_id),
  KEY idx_receipts_customer_date (customer_id, payment_date),
  CONSTRAINT fk_receipts_customer FOREIGN KEY (customer_id) REFERENCES customers (customer_id),
  CONSTRAINT chk_receipts_amount CHECK (amount > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='整笔收款流水；一张流水可覆盖多张订单';

CREATE TABLE payments (
  payment_id      VARCHAR(16)   NOT NULL COMMENT '分配记录号',
  order_id        VARCHAR(24)   NOT NULL,
  payment_date    DATE          NOT NULL,
  amount          DECIMAL(12,2) NOT NULL COMMENT '分配到该订单的金额',
  receipt_id      VARCHAR(16)   NOT NULL COMMENT '对应收款流水',
  allocation_rule VARCHAR(64)            COMMENT '分配规则说明',
  is_simulated    TINYINT(1)    NOT NULL DEFAULT 0,
  PRIMARY KEY (payment_id),
  KEY idx_payments_order (order_id),
  KEY idx_payments_receipt (receipt_id),
  -- order_id is not unique in order_lines because that table is at line grain.
  -- Referential integrity for this order-level relationship is checked by
  -- queries.sql/Q8 and the Python reconciliation engine instead of an invalid
  -- foreign key to a non-unique column.
  CONSTRAINT fk_payments_receipt FOREIGN KEY (receipt_id) REFERENCES receipts (receipt_id),
  CONSTRAINT chk_payments_amount CHECK (amount > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='收款分配到订单；与 receipts 是两个视角，不能相加';
