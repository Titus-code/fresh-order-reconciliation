"""Independently verify the saved synthetic CSV snapshot using integer arithmetic."""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'data'


def read(name):
    with (ROOT / name).open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def scaled(text, places):
    whole, _, fraction = text.partition('.')
    assert len(fraction) <= places
    return int(whole) * 10**places + int(fraction.ljust(places, '0') or '0')


def cents(text):
    return scaled(text, 2)


def main():
    manifest = json.loads((ROOT / 'expected/manifest.json').read_text(encoding='utf-8'))
    for name, info in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == info['sha256'], name
        rows = read(name)
        assert len(rows) == info['rows'], name
        assert all(r['is_simulated'] == 'true' for r in rows), name
    customers = {r['customer_id']: r for r in read('raw/customers.csv')}
    products = {r['product_id']: r for r in read('raw/products.csv')}
    receipts = {r['receipt_id']: r for r in read('raw/receipts.csv')}
    assert len(customers) == len(read('raw/customers.csv')) == manifest['customer_count']
    assert len(products) == len(read('raw/products.csv')) == manifest['product_count']
    assert len(receipts) == len(read('raw/receipts.csv')) == manifest['receipt_count']
    orders, line_keys = {}, set()
    observed_products, school_dates = set(), set()
    counts = Counter()
    for row in read('raw/order_lines.csv'):
        oid, cid, pid = row['order_id'], row['customer_id'], row['product_id']
        key = oid, row['line_no']
        assert key not in line_keys
        line_keys.add(key)
        assert cid in customers and pid in products
        observed_products.add(pid)
        product = products[pid]
        assert row['unit'] == product['unit']
        when = date.fromisoformat(row['order_date'])
        assert date(2026,9,1) <= when <= date(2026,9,30)
        if cid == 'C005':
            school_dates.add(when.day)
        quantities = [scaled(row[k], 1) for k in ['ordered_qty','delivered_qty','returned_qty']]
        ordered, delivered, returned = quantities
        assert 0 <= returned <= delivered <= ordered and ordered > 0
        if product['unit'] in {'袋','桶'}:
            assert all(q % 10 == 0 for q in quantities)
        price = cents(row['unit_price'])
        assert cents(product['simulated_price_min']) <= price <= cents(product['simulated_price_max'])
        # Quantity is in tenths; half-up rounding to fen is integer division.
        net = (delivered * price + 5) // 10 - (returned * price + 5) // 10
        if oid not in orders:
            orders[oid] = dict(customer_id=cid, date=row['order_date'], net=0)
            counts[cid] += 1
        assert (orders[oid]['customer_id'], orders[oid]['date']) == (cid,row['order_date'])
        orders[oid]['net'] += net
    assert observed_products == set(products)
    assert school_dates == set(manifest['school_delivery_days'])
    assert len(orders) == manifest['order_count']
    payments = read('raw/payments.csv')
    assert len({r['payment_id'] for r in payments}) == len(payments)
    allocated = defaultdict(int)
    for row in payments:
        order, receipt = orders[row['order_id']], receipts[row['receipt_id']]
        assert order['customer_id'] == receipt['customer_id']
        assert row['payment_date'] == receipt['payment_date']
        assert order['date'] <= row['payment_date'] <= '2026-10-06'
        assert receipt['settlement_month'] == '2026-09'
        assert cents(row['amount']) > 0
        allocated[row['receipt_id']] += cents(row['amount'])
    assert all(allocated[rid] == cents(r['amount']) for rid,r in receipts.items())
    for expected in read('expected/order_summary.csv'):
        oid, cutoff = expected['order_id'], expected['as_of_date']
        paid = sum(cents(r['amount']) for r in payments if r['order_id']==oid and r['payment_date']<=cutoff)
        assert expected['customer_id'] == orders[oid]['customer_id']
        assert cents(expected['net_receivable']) == orders[oid]['net']
        assert cents(expected['received']) == paid
        assert cents(expected['balance']) == orders[oid]['net']-paid >= 0
    for expected in read('expected/customer_summary.csv'):
        cid, cutoff = expected['customer_id'], expected['as_of_date']
        net = sum(o['net'] for o in orders.values() if o['customer_id']==cid)
        paid = sum(cents(r['amount']) for r in receipts.values() if r['customer_id']==cid and r['payment_date']<=cutoff)
        assert int(expected['order_count']) == counts[cid]
        assert cents(expected['net_receivable']) == net
        assert cents(expected['received']) == paid
        assert cents(expected['balance']) == net-paid
    assert sum(o['net'] for o in orders.values()) == cents(manifest['net_receivable'])
    print(f'PASS: {len(orders)} orders; {len(line_keys)} lines; {len(payments)} allocations; {len(receipts)} receipts; 2 cutoffs.')
    print('PASS: keys, references, dates, units, quantities, price bands, hashes and independent integer-fen totals.')


if __name__ == '__main__':
    main()
