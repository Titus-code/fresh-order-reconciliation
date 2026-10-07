"""Validated reconciliation engine used by the CLI and regression tests."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")

RAW_FILES = {
    "customers": [
        "customer_id", "customer_name", "customer_type", "service_area",
        "meal_scale_assumption", "delivery_schedule", "settlement_cycle",
        "payment_due_date", "is_simulated",
    ],
    "products": [
        "product_id", "product_name", "specification", "unit", "category",
        "simulated_price_min", "simulated_price_max", "is_simulated",
    ],
    "order_lines": [
        "order_id", "line_no", "customer_id", "order_date", "product_id",
        "unit", "ordered_qty", "delivered_qty", "returned_qty", "unit_price",
        "delivery_note", "is_simulated",
    ],
    "receipts": [
        "receipt_id", "customer_id", "payment_date", "amount", "payment_method",
        "settlement_month", "memo", "is_simulated",
    ],
    "payments": [
        "payment_id", "order_id", "payment_date", "amount", "receipt_id",
        "allocation_rule", "is_simulated",
    ],
}


def money(value: Decimal | str | int) -> Decimal:
    """Round a finite decimal amount to cents using half-up rounding."""

    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    if not amount.is_finite():
        raise ValueError(f"金额不是有限数值：{value}")
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _problem(problems: list[dict], *, source: str, line: object, key: str,
             kind: str, detail: str, classification: str = "数据质量",
             blocking: bool = False) -> None:
    problems.append({
        "source": source,
        "line": line,
        "key": key,
        "kind": kind,
        "detail": detail,
        "classification": classification,
        "blocking": "是" if blocking else "否",
    })


def _decimal(value: object, *, field: str) -> Decimal:
    if value is None or str(value).strip() == "":
        raise ValueError(f"{field} 为空")
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} 不是有效数字：{value}") from exc
    if not result.is_finite():
        raise ValueError(f"{field} 不是有限数值：{value}")
    return result


def _iso_date(value: object, *, field: str) -> str:
    if value is None or str(value).strip() == "":
        raise ValueError(f"{field} 为空")
    text = str(value).strip()
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} 不是 YYYY-MM-DD 日期：{value}") from exc
    return text


def load(name: str, raw_dir: Path, problems: list[dict]) -> list[dict]:
    """Read one CSV and report file/schema errors instead of crashing."""

    path = raw_dir / f"{name}.csv"
    if not path.exists():
        _problem(problems, source=path.name, line=1, key="", kind="文件缺失",
                 detail=f"找不到输入文件：{path}", blocking=True)
        return []
    try:
        handle = path.open(encoding="utf-8-sig", newline="")
    except OSError as exc:
        _problem(problems, source=path.name, line=1, key="", kind="文件不可读",
                 detail=str(exc), blocking=True)
        return []
    rows: list[dict] = []
    with handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        missing = [column for column in RAW_FILES[name] if column not in fields]
        if missing:
            _problem(problems, source=path.name, line=1, key="", kind="字段缺失",
                     detail="缺少字段：" + "、".join(missing), blocking=True)
        for line_no, row in enumerate(reader, start=2):
            row["_line"] = line_no
            rows.append(row)
    return rows


def _decimal_or_problem(value: object, field: str) -> Decimal:
    return _decimal(value, field=field)


def reconcile(input_dir: Path = RAW, cutoff: str = "2026-10-06") -> tuple[dict, list[dict]]:
    """Validate and calculate a reconciliation run.

    Returns ``(result, problems)``. ``result`` contains rows and totals so
    callers can test the calculation without reading generated CSV files.
    """

    cutoff = _iso_date(cutoff, field="cutoff")
    problems: list[dict] = []
    customers = load("customers", input_dir, problems)
    products = load("products", input_dir, problems)
    lines = load("order_lines", input_dir, problems)
    receipts = load("receipts", input_dir, problems)
    payments = load("payments", input_dir, problems)

    cust: dict[str, dict] = {}
    duplicate_customers: set[str] = set()
    for row in customers:
        cid = row.get("customer_id")
        if not cid:
            _problem(problems, source="customers.csv", line=row.get("_line"), key="",
                     kind="主键为空", detail="customer_id 为空", blocking=True)
            continue
        if cid in cust:
            duplicate_customers.add(cid)
            _problem(problems, source="customers.csv", line=row.get("_line"), key=cid,
                     kind="主键重复", detail="customer_id 重复", blocking=True)
        else:
            cust[cid] = row

    prod: dict[str, dict] = {}
    duplicate_products: set[str] = set()
    for row in products:
        pid = row.get("product_id")
        if not pid:
            _problem(problems, source="products.csv", line=row.get("_line"), key="",
                     kind="主键为空", detail="product_id 为空", blocking=True)
            continue
        if pid in prod:
            duplicate_products.add(pid)
            _problem(problems, source="products.csv", line=row.get("_line"), key=pid,
                     kind="主键重复", detail="product_id 重复", blocking=True)
        else:
            prod[pid] = row

    receipt_of: dict[str, dict] = {}
    duplicate_receipts: set[str] = set()
    for row in receipts:
        rid = row.get("receipt_id")
        if not rid:
            _problem(problems, source="receipts.csv", line=row.get("_line"), key="",
                     kind="主键为空", detail="receipt_id 为空", blocking=True)
            continue
        if rid in receipt_of:
            duplicate_receipts.add(rid)
            _problem(problems, source="receipts.csv", line=row.get("_line"), key=rid,
                     kind="主键重复", detail="receipt_id 重复", blocking=True)
        else:
            receipt_of[rid] = row

    valid_lines: list[dict] = []
    blocked: set[str] = set()
    seen_keys: set[tuple[str, str]] = set()
    for row in lines:
        oid = str(row.get("order_id") or "")
        line_no = str(row.get("line_no") or "")
        key = (oid, line_no)
        bad: tuple[str, str] | None = None
        if not oid or not line_no:
            bad = ("主键为空", "order_id 或 line_no 为空")
        elif key in seen_keys:
            bad = ("主键重复", f"order_id+line_no={line_no} 重复出现")
        elif row.get("customer_id") in duplicate_customers:
            bad = ("客户主键重复", str(row.get("customer_id") or ""))
        elif row.get("product_id") in duplicate_products:
            bad = ("商品主键重复", str(row.get("product_id") or ""))
        elif row.get("customer_id") not in cust:
            bad = ("客户不存在", str(row.get("customer_id") or ""))
        elif row.get("product_id") not in prod:
            bad = ("商品不存在", str(row.get("product_id") or ""))
        seen_keys.add(key)

        parsed: dict[str, Decimal | str] = {}
        if bad is None:
            for field in ("ordered_qty", "delivered_qty", "returned_qty", "unit_price"):
                try:
                    parsed[field] = _decimal_or_problem(row.get(field), field)
                except ValueError as exc:
                    bad = ("数值非法", str(exc))
                    break
            if bad is None:
                try:
                    parsed["order_date"] = _iso_date(row.get("order_date"), field="order_date")
                except ValueError as exc:
                    bad = ("日期非法", str(exc))

        if bad is None:
            product = prod[row["product_id"]]
            if row.get("unit") != product.get("unit"):
                bad = ("单位不一致", f"明细 {row.get('unit')}，商品表 {product.get('unit')}")
            else:
                ordered = parsed["ordered_qty"]
                delivered = parsed["delivered_qty"]
                returned = parsed["returned_qty"]
                if not (Decimal("0") <= returned <= delivered <= ordered) or ordered <= 0:
                    bad = ("数量非法", f"下单 {ordered}／交付 {delivered}／退货 {returned}")

        if bad:
            _problem(problems, source="order_lines.csv", line=row.get("_line"), key=oid,
                     kind=bad[0], detail=bad[1], blocking=True)
            if oid:
                blocked.add(oid)
            continue

        price = parsed["unit_price"]
        product = prod[row["product_id"]]
        try:
            lo = _decimal(product.get("simulated_price_min"), field="simulated_price_min")
            hi = _decimal(product.get("simulated_price_max"), field="simulated_price_max")
        except ValueError as exc:
            _problem(problems, source="products.csv", line=row.get("_line"), key=row.get("product_id", ""),
                     kind="价格区间非法", detail=str(exc), blocking=True)
            blocked.add(oid)
            continue
        if not (lo <= price <= hi):
            _problem(problems, source="order_lines.csv", line=row.get("_line"), key=oid,
                     kind="价格越界", detail=f"单价 {price} 不在 {lo}—{hi}",
                     classification="风险提示", blocking=False)

        delivered = parsed["delivered_qty"]
        returned = parsed["returned_qty"]
        gross = money(delivered * price)
        back = money(returned * price)
        valid_lines.append({
            "order_id": oid,
            "line_no": line_no,
            "source_line": row.get("_line"),
            "customer_id": row.get("customer_id", ""),
            "order_date": parsed["order_date"],
            "product_id": row.get("product_id", ""),
            "product_name": product.get("product_name", ""),
            "unit": row.get("unit", ""),
            "ordered_qty": parsed["ordered_qty"],
            "delivered_qty": delivered,
            "returned_qty": returned,
            "unit_price": price,
            "gross": gross,
            "back": back,
            "net": gross - back,
            "delivery_note": row.get("delivery_note", ""),
        })

    orders: dict[str, dict] = {}
    for line in valid_lines:
        oid = line["order_id"]
        entry = orders.setdefault(oid, {
            "order_id": oid, "customer_id": line["customer_id"],
            "order_date": line["order_date"], "line_count": 0, "net": ZERO,
        })
        if entry["customer_id"] != line["customer_id"] or entry["order_date"] != line["order_date"]:
            _problem(problems, source="order_lines.csv", line=line["source_line"], key=oid,
                     kind="订单归属冲突", detail="同一订单出现不同客户或不同日期", blocking=True)
            blocked.add(oid)
        entry["line_count"] += 1
        entry["net"] += line["net"]
    for oid in sorted(blocked):
        if oid in orders:
            _problem(problems, source="order_lines.csv", line="", key=oid,
                     kind="整单暂缓", detail="因存在阻断异常，该订单不计入正式账单", blocking=True)
            del orders[oid]

    paid: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)
    seen_payments: set[str] = set()
    allocation_by_receipt: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)
    for row in payments:
        pid = str(row.get("payment_id") or "")
        oid = str(row.get("order_id") or "")
        if not pid:
            _problem(problems, source="payments.csv", line=row.get("_line"), key="",
                     kind="主键为空", detail="payment_id 为空", blocking=True)
            continue
        if pid in seen_payments:
            _problem(problems, source="payments.csv", line=row.get("_line"), key=pid,
                     kind="主键重复", detail="payment_id 重复", blocking=True)
            continue
        seen_payments.add(pid)
        if oid not in orders:
            _problem(problems, source="payments.csv", line=row.get("_line"), key=oid,
                     kind="回款无匹配订单", detail="订单不存在或已暂缓", blocking=False)
            continue
        rid = str(row.get("receipt_id") or "")
        if rid in duplicate_receipts:
            _problem(problems, source="payments.csv", line=row.get("_line"), key=pid,
                     kind="流水主键重复", detail=rid, blocking=False)
            continue
        receipt = receipt_of.get(rid)
        if receipt is None:
            _problem(problems, source="payments.csv", line=row.get("_line"), key=pid,
                     kind="流水不存在", detail=rid, blocking=False)
            continue
        try:
            payment_date = _iso_date(row.get("payment_date"), field="payment_date")
            amount = money(_decimal(row.get("amount"), field="amount"))
            receipt_date = _iso_date(receipt.get("payment_date"), field="receipt.payment_date")
            declared = money(_decimal(receipt.get("amount"), field="receipt.amount"))
        except ValueError as exc:
            _problem(problems, source="payments.csv", line=row.get("_line"), key=pid,
                     kind="回款字段非法", detail=str(exc), blocking=False)
            continue
        if receipt.get("customer_id") != orders[oid]["customer_id"]:
            _problem(problems, source="payments.csv", line=row.get("_line"), key=pid,
                     kind="回款客户不一致", detail="流水客户与订单客户不同", blocking=False)
            continue
        if payment_date != receipt_date:
            _problem(problems, source="payments.csv", line=row.get("_line"), key=pid,
                     kind="回款日期不一致", detail=f"分配 {payment_date}，流水 {receipt_date}", blocking=False)
            continue
        if amount <= 0:
            _problem(problems, source="payments.csv", line=row.get("_line"), key=pid,
                     kind="金额非法", detail=f"回款金额 {amount}", blocking=False)
            continue
        allocation_by_receipt[rid] += amount
        if payment_date > cutoff:
            _problem(problems, source="payments.csv", line=row.get("_line"), key=pid,
                     kind="超出截止日", detail=f"{payment_date} 晚于 {cutoff}",
                     classification="口径排除", blocking=False)
            continue
        paid[oid] += amount

    for rid, receipt in receipt_of.items():
        try:
            declared = money(_decimal(receipt.get("amount"), field="receipt.amount"))
        except ValueError:
            continue
        if allocation_by_receipt[rid] != declared:
            _problem(problems, source="receipts.csv", line=receipt.get("_line"), key=rid,
                     kind="流水分配不相符",
                     detail=f"流水 {declared}，分配 {allocation_by_receipt[rid]}", blocking=False)

    order_rows = []
    for order in sorted(orders.values(), key=lambda item: item["order_id"]):
        received = paid[order["order_id"]]
        balance = order["net"] - received
        order_rows.append({
            "order_id": order["order_id"], "customer_id": order["customer_id"],
            "customer_name": cust[order["customer_id"]].get("customer_name", ""),
            "order_date": order["order_date"], "line_count": order["line_count"],
            "net_receivable": f"{order['net']:.2f}", "received": f"{received:.2f}",
            "balance": f"{balance:.2f}",
            "status": "已结清" if balance == 0 else "未结清",
        })

    customer_rows = []
    for customer in customers:
        cid = customer.get("customer_id", "")
        matching = [order for order in orders.values() if order["customer_id"] == cid]
        total = sum((order["net"] for order in matching), ZERO)
        received = sum((paid[order["order_id"]] for order in matching), ZERO)
        balance = total - received
        customer_rows.append({
            "customer_id": cid, "customer_name": customer.get("customer_name", ""),
            "order_count": len(matching), "net_receivable": f"{total:.2f}",
            "received": f"{received:.2f}", "balance": f"{balance:.2f}",
            "status": "已结清" if balance == 0 else "未结清",
        })

    net = sum((order["net"] for order in orders.values()), ZERO)
    received = sum(paid.values(), ZERO)
    return {
        "cutoff": cutoff, "orders": order_rows, "customers": customer_rows,
        "valid_lines": valid_lines, "blocked_orders": sorted(blocked),
        "net": net, "received": received, "balance": net - received,
    }, problems


def write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(result: dict, problems: list[dict], out: Path) -> None:
    cut = result["cutoff"].replace("-", "")
    write_csv(out / f"order_reconciliation_{cut}.csv", [
        "order_id", "customer_id", "customer_name", "order_date", "line_count",
        "net_receivable", "received", "balance", "status",
    ], result["orders"])
    write_csv(out / f"customer_reconciliation_{cut}.csv", [
        "customer_id", "customer_name", "order_count", "net_receivable",
        "received", "balance", "status",
    ], result["customers"])
    write_csv(out / f"exceptions_{cut}.csv", [
        "source", "line", "key", "kind", "detail", "classification", "blocking",
    ], problems)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff", default="2026-10-06", help="对账截止日（含当日）")
    parser.add_argument("--input-dir", type=Path, default=RAW,
                        help="原始 CSV 目录，默认 data/raw")
    parser.add_argument("--out", type=Path, default=ROOT / "outputs")
    args = parser.parse_args(argv)
    try:
        result, problems = reconcile(args.input_dir, args.cutoff)
    except ValueError as exc:
        parser.error(str(exc))
    write_outputs(result, problems, args.out)
    print(f"对账截止日 {result['cutoff']}")
    print(f"有效订单 {len(result['orders'])} 张，明细 {len(result['valid_lines'])} 行，暂缓订单 {len(result['blocked_orders'])} 张")
    print(f"净应收 {result['net']:.2f} 元，已收 {result['received']:.2f} 元，未结清 {result['balance']:.2f} 元")
    print(f"异常/排除 {len(problems)} 条；结果已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
