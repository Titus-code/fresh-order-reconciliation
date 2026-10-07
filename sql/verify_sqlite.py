"""在 SQLite 中跑一遍 sql/queries.sql，验证 SQL 口径与 Python、Excel 结果一致。

MySQL 与 SQLite 的差异只有两处，这个脚本自动改写，不改动 sql/queries.sql 本身：
  1. CREATE OR REPLACE VIEW -> DROP VIEW IF EXISTS + CREATE VIEW
  2. SET @cutoff = '...'    -> 直接把 @cutoff 替换成字面量

queries.sql 已避开 CONCAT、日期函数等引擎差异；金额走整数分运算，
CAST(... AS INTEGER) 与 COALESCE 两边都支持，所以两个引擎结果一致。

前置：先把 data/raw/ 的 CSV 导入 SQLite（见本文件 load()）。

用法：
    python sql/verify_sqlite.py --cutoff 2026-10-06
"""
import argparse
import csv
import json
import re
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
TABLES = ['customers', 'products', 'order_lines', 'receipts', 'payments']

SQLITE_SCHEMA = """
CREATE TABLE customers (customer_id TEXT PRIMARY KEY, customer_name TEXT, customer_type TEXT,
  service_area TEXT, meal_scale_assumption TEXT, delivery_schedule TEXT,
  settlement_cycle TEXT, payment_due_date TEXT, is_simulated INTEGER);
-- 所有涉及小数位数的列一律声明为 TEXT，而不是 NUMERIC/REAL。
-- SQLite 的 NUMERIC 亲和性会把 '4.1'、'2.30' 这类值转成浮点，带来两个后果：
--   1. SUM(delivered_qty*unit_price) 得到 1212.6799999999998，
--      客户余额变成 -2.27e-13 而不是 0，与 Excel、Python 对不上。
--   2. 更隐蔽的一个：'2.30' 变成浮点 2.3，再去 REPLACE('.','') 得到 '23'，
--      而明细里的 unit_price 仍是 '2.30' -> 230，于是每一行都误报"单价超出区间"。
--      这个坑是 Q7 先报出 966 行假异常才暴露的。
-- 声明成 TEXT 后原样保存，由 queries.sql 里的显式 CAST 完成乘 10 / 乘 100。
-- MySQL 侧不需要这层处理：schema.sql 用 DECIMAL(10,1)/(10,2)，本身就精确。
CREATE TABLE products (product_id TEXT PRIMARY KEY, product_name TEXT, specification TEXT,
  unit TEXT, category TEXT, simulated_price_min TEXT, simulated_price_max TEXT,
  is_simulated INTEGER);
CREATE TABLE order_lines (order_id TEXT, line_no INTEGER, customer_id TEXT, order_date TEXT,
  product_id TEXT, unit TEXT, ordered_qty TEXT, delivered_qty TEXT, returned_qty TEXT,
  unit_price TEXT, delivery_note TEXT, is_simulated INTEGER, PRIMARY KEY (order_id, line_no));
CREATE TABLE receipts (receipt_id TEXT PRIMARY KEY, customer_id TEXT, payment_date TEXT,
  amount TEXT, payment_method TEXT, settlement_month TEXT, memo TEXT, is_simulated INTEGER);
CREATE TABLE payments (payment_id TEXT PRIMARY KEY, order_id TEXT, payment_date TEXT,
  amount TEXT, receipt_id TEXT, allocation_rule TEXT, is_simulated INTEGER);
"""


def load(con, tables=TABLES):
    """CSV 原样入库，不做任何数值转换。

    数量与金额列在 SQLITE_SCHEMA 中声明为 TEXT，SQLite 因此按字符串保存，
    不会引入浮点误差；乘 10 / 乘 100 的换算由 queries.sql 的 CAST 完成。
    """
    con.executescript(SQLITE_SCHEMA)
    for table in tables:
        rows = list(csv.reader((RAW / f'{table}.csv').open(encoding='utf-8-sig')))
        header, body = rows[0], rows[1:]
        con.executemany(
            f"INSERT INTO {table} ({','.join(header)}) VALUES ({','.join('?' * len(header))})",
            body)
    con.commit()


def split_statements(script):
    """按分号切分，跳过纯注释片段。"""
    out = []
    for chunk in script.split(';'):
        body = '\n'.join(l for l in chunk.splitlines() if not l.strip().startswith('--'))
        if body.strip():
            out.append((chunk.strip(), body.strip()))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cutoff', default='2026-10-06')
    parser.add_argument('--db', default=':memory:')
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    load(con)

    script = (ROOT / 'sql' / 'queries.sql').read_text(encoding='utf-8')
    script = re.sub(r'^SET .*$', '', script, flags=re.M)
    script = script.replace('@cutoff', f"'{args.cutoff}'")
    script = re.sub(r'CREATE OR REPLACE VIEW (\w+) AS',
                    r'DROP VIEW IF EXISTS \1; CREATE VIEW \1 AS', script)

    expected = {}
    with (ROOT / 'data' / 'expected' / 'customer_summary.csv').open(encoding='utf-8-sig') as fh:
        for row in csv.DictReader(fh):
            if row['as_of_date'] == args.cutoff:
                expected[row['customer_id']] = row
    with (ROOT / 'data' / 'expected' / 'manifest.json').open(encoding='utf-8') as fh:
        manifest = json.load(fh)

    printed = 0
    failures = []
    for label, body in split_statements(script):
        for stmt in [s.strip() for s in body.split(';') if s.strip()]:
            cur = con.execute(stmt)
            if cur.description is None:
                continue
            columns = [d[0] for d in cur.description]
            rows = cur.fetchall()
            printed += 1
            title = next((l.strip('- ').strip() for l in label.splitlines()
                          if l.strip().startswith('--')), stmt[:40])
            if 'customer_id' in columns and 'net_receivable' in columns and 'order_id' not in columns:
                print(f'\n[{title}]  与 expected 对比：')
                ok = True
                seen = set()
                for row in rows:
                    cid = row[columns.index('customer_id')]
                    seen.add(cid)
                    got = dict(zip(columns, row))
                    exp = expected.get(cid)
                    if not exp:
                        print(f'  {cid}: expected 中没有该客户')
                        ok = False
                        continue
                    for key in ('net_receivable', 'received', 'balance'):
                        if f"{float(got[key]):.2f}" != f"{float(exp[key]):.2f}":
                            print(f'  {cid}.{key}: SQL {float(got[key]):.2f} vs expected {exp[key]}')
                            ok = False
                    if str(got['order_count']) != str(exp['order_count']):
                        print(f'  {cid}.order_count: SQL {got["order_count"]} vs expected {exp["order_count"]}')
                        ok = False
                missing = set(expected) - seen
                extra = seen - set(expected)
                if missing:
                    print(f'  expected 中缺少：{sorted(missing)}')
                    ok = False
                if extra:
                    print(f'  SQL 多出客户：{sorted(extra)}')
                    ok = False
                print('  PASS 全部一致' if ok else '  FAIL 存在差异')
                if not ok:
                    failures.append('Q5 客户汇总')
                continue
            print(f'\n[{title}]  {columns}  共 {len(rows)} 行')
            for row in rows[:5]:
                print('   ', row)
            if len(rows) > 5:
                print(f'    ...... 其余 {len(rows) - 5} 行省略')
            column_set = set(columns)
            if column_set >= {'source_file', 'record_key', 'dup_count', 'kind'}:
                if rows:
                    failures.append('Q6 主键重复')
            elif column_set >= {'order_id', 'line_no', 'customer_id', 'product_id', 'kind'}:
                if rows:
                    failures.append('Q7 数量、单位、金额不合规')
            elif column_set >= {'kind', 'record_key', 'detail'}:
                if rows:
                    failures.append('Q8 回款关联异常')
            elif column_set >= {'receipt_id', 'receipt_amount', 'allocated_amount'}:
                if rows:
                    failures.append('Q9 流水与分配金额不相符')
            elif column_set >= {'scope', 'received_total'}:
                if len(rows) != 2 or len({Decimal(str(row[1])).quantize(Decimal('0.01')) for row in rows}) != 1:
                    failures.append('Q10 流水与分配总额不一致')
            elif column_set >= {'total_net_fen', 'total_net_receivable'}:
                expected_net = int(Decimal(manifest['net_receivable']) * 100)
                if not rows or rows[0][0] != expected_net:
                    failures.append('Q11 总账净应收不一致')
    print(f'\n共执行 {printed} 条返回结果的查询。')

    total = con.execute('SELECT SUM(net_fen) FROM v_order_net').fetchone()[0]
    print(f'SQL 总计净应收 {total / 100:.2f} 元')
    if failures:
        print('校验失败：' + '、'.join(dict.fromkeys(failures)))
        return 1
    print('SQL 校验门禁：PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
