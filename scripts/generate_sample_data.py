"""Generate fictional Jiangxi monthly sales ledgers, not a reconciliation engine.

Uses Python standard library only. Existing snapshots are never overwritten.
"""
import argparse
import csv
import hashlib
import json
import random
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

D = Decimal
CENT = D('0.01')
ROOT = Path(__file__).resolve().parents[1]
SEED = 20260906


def money(value):
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def sha256_file(path):
    """Hash canonical LF bytes so generated manifests are cross-platform."""
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'data')
    args = parser.parse_args()
    out = args.output_dir.resolve()
    names = ['raw/customers.csv', 'raw/products.csv', 'raw/order_lines.csv',
             'raw/payments.csv', 'raw/receipts.csv', 'expected/order_summary.csv',
             'expected/customer_summary.csv', 'expected/manifest.json']
    existing = [str(out / name) for name in names if (out / name).exists()]
    if existing:
        parser.error('Refusing to overwrite snapshots; choose another --output-dir: ' + ', '.join(existing))
    rng = random.Random(SEED)
    # meal counts describe the customer's scale, not full procurement from this shop.
    specs = [
        ('C001', '模拟_榕树下粉面店', '粉面早餐店', '镇区', '70—100人次/日', '每周一至六', 12, 4),
        ('C002', '模拟_桥头家常菜馆', '家常菜馆', '镇区', '60—100人次/日', '每周二至日', 28, 5),
        ('C003', '模拟_兴街快餐店', '快餐店', '镇区', '100—160人次/日', '每周一至六', 42, 6),
        ('C004', '模拟_田畔饭店', '乡村饭店', '周边村庄', '平日40—60/周末80—120人次', '每周二四六', 38, 6),
        ('C005', '模拟_青禾小学食堂', '学校食堂', '镇区', '240人午餐/供餐日', '教学日', 62, 6),
        ('C006', '模拟_溪桥医院食堂', '医院食堂', '镇区', '约180人午餐/日', '每日配送', 48, 6),
    ]
    customers = [dict(customer_id=c, customer_name=n, customer_type=t, service_area=a,
                      meal_scale_assumption=m, delivery_schedule=s, settlement_cycle='自然月',
                      payment_due_date='2026-10-10', is_simulated='true')
                 for c, n, t, a, m, s, _, _ in specs]
    # Prices are delivery-sale assumptions, not copied retail quotations.
    goods = [
        ('P001', '土豆', '散装鲜菜', '公斤', '根茎菜', '2.80', '4.00'),
        ('P002', '白萝卜', '散装鲜菜', '公斤', '根茎菜', '2.00', '3.20'),
        ('P003', '包菜', '散装鲜菜', '公斤', '甘蓝菜', '2.60', '3.80'),
        ('P004', '冬瓜', '散装鲜菜', '公斤', '瓜菜', '1.80', '3.00'),
        ('P005', '南瓜', '散装鲜菜', '公斤', '瓜菜', '2.40', '3.60'),
        ('P006', '茄子', '散装鲜菜', '公斤', '茄果菜', '3.80', '5.80'),
        ('P007', '青椒', '散装鲜菜', '公斤', '茄果菜', '4.00', '6.50'),
        ('P008', '黄瓜', '散装鲜菜', '公斤', '瓜菜', '3.20', '5.20'),
        ('P009', '西红柿', '散装鲜菜', '公斤', '茄果菜', '4.00', '6.00'),
        ('P010', '空心菜', '散装鲜菜', '公斤', '叶菜', '3.60', '5.80'),
        ('P011', '红薯叶', '散装鲜菜', '公斤', '叶菜', '3.60', '5.60'),
        ('P012', '小白菜', '散装鲜菜', '公斤', '叶菜', '3.80', '6.00'),
        ('P013', '豇豆', '散装鲜菜', '公斤', '豆类菜', '4.80', '7.20'),
        ('P014', '丝瓜', '散装鲜菜', '公斤', '瓜菜', '4.00', '6.00'),
        ('P015', '小葱', '散装鲜菜', '公斤', '调味鲜菜', '6.00', '9.00'),
        ('P016', '鸡蛋', '普通鲜鸡蛋按净重', '公斤', '禽蛋', '9.20', '11.00'),
        ('P017', '籼米', '25公斤/袋普通籼米', '袋', '粮食', '112.00', '122.00'),
        ('P018', '小麦粉', '25公斤/袋普通小麦粉', '袋', '粮食', '105.00', '115.00'),
        ('P019', '菜籽油', '5升/桶普通菜籽油', '桶', '食用油', '65.00', '73.00'),
        ('P020', '大豆油', '5升/桶普通大豆油', '桶', '食用油', '54.00', '62.00'),
    ]
    products = [dict(product_id=p, product_name=n, specification=s, unit=u, category=c,
                     simulated_price_min=lo, simulated_price_max=hi, is_simulated='true')
                for p, n, s, u, c, lo, hi in goods]
    product_map = {p['product_id']: p for p in products}
    # Smooth weekly price changes shared by clients; no per-row arbitrary volatility.
    prices = {}
    for p in products:
        lo, hi = D(p['simulated_price_min']), D(p['simulated_price_max'])
        base = (lo + hi) / 2
        for week in range(5):
            step = D('0.10') if p['unit'] == '公斤' else D('1')
            prices[p['product_id'], week] = money(max(lo, min(hi, base + step * rng.randint(-3, 3))))

    orders, lines = [], []
    counts = defaultdict(int)
    school_days = {d for d in range(1, 31) if date(2026, 9, d).weekday() < 5 and d != 25} | {20}

    for day in range(1, 31):
        when = date(2026, 9, day)
        for cid, _, _, _, _, _, veg_kg, veg_count in specs:
            weekdays = {'C001': {0,1,2,3,4,5}, 'C002': {1,2,3,4,5,6},
                        'C003': {0,1,2,3,4,5}, 'C004': {1,3,5}, 'C006': {0,1,2,3,4,5,6}}
            active = day in school_days if cid == 'C005' else when.weekday() in weekdays[cid]
            if not active:
                continue
            counts[cid] += 1
            visit = counts[cid]
            oid = f'SIM-202609{day:02d}-{cid}'
            # Leafy greens appear on every delivery; menu vegetables rotate.
            selected = [rng.choice(['P010', 'P011', 'P012'])]
            selected += rng.sample(['P001','P002','P003','P004','P005','P006','P007','P008','P009','P013','P014'], veg_count-1)
            weights = [rng.randint(7, 16) for _ in selected]
            factor = D(rng.randint(88, 112)) / 100
            if cid in {'C002','C004'} and (when.weekday() >= 4 or day in {25,26,27}):
                factor *= D('1.25')
            basket = [(pid, (D(veg_kg) * factor * w / sum(weights)).quantize(D('0.1'), rounding=ROUND_HALF_UP))
                      for pid, w in zip(selected, weights)]
            if visit % 2 == 1:
                basket.append(('P016', D({'C001':3,'C002':4,'C003':6,'C004':5,'C005':12,'C006':9}[cid])))
            if visit % 3 == 1:
                basket.append(('P015', D('0.5') if cid == 'C001' else D('1.0')))
            if (visit-1) % 5 == 0:
                rice = {'C001':0,'C002':3,'C003':5,'C004':3,'C005':6,'C006':4}[cid]
                if rice:
                    basket.append(('P017', D(rice)))
                basket.append(('P019' if cid in {'C001','C002','C004'} else 'P020', D(2 if cid in {'C003','C005','C006'} else 1)))
                if cid == 'C001':
                    basket.append(('P018', D(1)))
            order_net = D('0')
            for no, (pid, quantity) in enumerate(basket, 1):
                p = product_map[pid]
                delivered, returned, note = quantity, D('0'), '正常交付'
                if p['unit'] == '公斤' and rng.random() < 0.055:
                    delivered = max(D('0'), quantity - D(rng.choice(['0.2','0.3','0.5'])))
                    note = '到货不足；按实际交付计费'
                if p['category'] == '叶菜' and rng.random() < 0.12:
                    returned = min(delivered, D(rng.choice(['0.2','0.3','0.5'])))
                    note += '；签收时挑出黄叶退回'
                elif pid == 'P016' and rng.random() < 0.08:
                    returned = D('0.1')
                    note += '；签收时破损退回'
                price = prices[pid, (day-1)//7]
                net = money(delivered * price) - money(returned * price)
                order_net += net
                lines.append(dict(order_id=oid, line_no=str(no), customer_id=cid,
                                  order_date=when.isoformat(), product_id=pid, unit=p['unit'],
                                  ordered_qty=f'{quantity:.1f}', delivered_qty=f'{delivered:.1f}',
                                  returned_qty=f'{returned:.1f}', unit_price=f'{price:.2f}',
                                  delivery_note=note, is_simulated='true'))
            orders.append(dict(order_id=oid, customer_id=cid, order_date=when.isoformat(), net=order_net))

    receivable = {c['customer_id']: sum((o['net'] for o in orders if o['customer_id'] == c['customer_id']), D('0')) for c in customers}
    # Monthly remittances are distinct from order allocation rows.
    plans = [('C001','2026-10-02',receivable['C001'],'微信转账'),
             ('C002','2026-09-30',D('1000'),'微信转账'),
             ('C002','2026-10-05',receivable['C002']-D('1000'),'银行转账'),
             ('C003','2026-10-04',D('3000'),'银行转账'),
             ('C004','2026-10-06',receivable['C004'],'微信转账'),
             ('C005','2026-09-30',D('5000'),'银行转账'),
             ('C006','2026-10-05',D('5000'),'银行转账')]
    receipts, payments = [], []
    remaining = {o['order_id']: o['net'] for o in orders}
    for i, (cid, when, total, method) in enumerate(sorted(plans, key=lambda p: (p[1],p[0])), 1):
        rid = f'SIM-R{i:04d}'
        receipts.append(dict(receipt_id=rid, customer_id=cid, payment_date=when,
                             amount=f'{total:.2f}', payment_method=method,
                             settlement_month='2026-09', memo='模拟9月月结货款', is_simulated='true'))
        rest = total
        for o in orders:
            if o['customer_id'] != cid or rest == 0:
                continue
            allocation = min(rest, remaining[o['order_id']])
            if allocation <= 0:
                continue
            payments.append(dict(payment_id=f'SIM-P{len(payments)+1:04d}', order_id=o['order_id'],
                                 payment_date=when, amount=f'{allocation:.2f}', receipt_id=rid,
                                 allocation_rule='模拟确认：按订单日期及编号先后分配', is_simulated='true'))
            remaining[o['order_id']] -= allocation
            rest -= allocation
        assert rest == 0, 'This sample does not include advance payments.'

    order_expected, customer_expected = [], []
    for cutoff in ['2026-09-30','2026-10-06']:
        for o in orders:
            paid = sum((D(p['amount']) for p in payments if p['order_id'] == o['order_id'] and p['payment_date'] <= cutoff), D('0'))
            order_expected.append(dict(as_of_date=cutoff, order_id=o['order_id'], customer_id=o['customer_id'],
                                       net_receivable=f"{o['net']:.2f}", received=f'{paid:.2f}',
                                       balance=f"{o['net']-paid:.2f}", is_simulated='true'))
        for c in customers:
            cid = c['customer_id']
            paid = sum((D(r['amount']) for r in receipts if r['customer_id']==cid and r['payment_date']<=cutoff), D('0'))
            balance = receivable[cid]-paid
            customer_expected.append(dict(as_of_date=cutoff, settlement_month='2026-09', customer_id=cid,
                                          customer_name=c['customer_name'], order_count=counts[cid],
                                          net_receivable=f'{receivable[cid]:.2f}', received=f'{paid:.2f}',
                                          balance=f'{balance:.2f}', payment_due_date='2026-10-10',
                                          status='已结清' if balance==0 else '未结清（未到约定付款日）', is_simulated='true'))

    tables = dict(zip(names[:-1], [customers, products, lines, payments, receipts, order_expected, customer_expected]))
    for relative, rows in tables.items():
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    manifest = dict(is_simulated=True, scenario='江西普通乡镇2026年9月月结配送', seed=SEED,
                    order_period_start='2026-09-01', order_period_end='2026-09-30',
                    receipt_observed_through='2026-10-06', payment_due_date='2026-10-10',
                    opening_balance_assumption='0.00', order_count=len(orders),
                    customer_count=len(customers), product_count=len(products), receipt_count=len(receipts),
                    order_line_count=len(lines), payment_allocation_count=len(payments),
                    school_delivery_days=sorted(school_days),
                    short_delivery_line_count=sum(D(l['delivered_qty']) < D(l['ordered_qty']) for l in lines),
                    return_line_count=sum(D(l['returned_qty']) > 0 for l in lines),
                    net_receivable=f'{sum(receivable.values()):.2f}',
                    received=f"{sum(D(r['amount']) for r in receipts):.2f}",
                    files={name: dict(rows=len(rows), sha256=sha256_file(out/name)) for name,rows in tables.items()})
    (out/'expected/manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
