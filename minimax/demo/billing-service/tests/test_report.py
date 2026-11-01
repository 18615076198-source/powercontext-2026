"""报表回归测试：对应 specs/02-report.md 的 BR-REPORT-01..04。

这些用例是「原有行为」的基线，任何修改都必须保持全部通过。
"""

from __future__ import annotations

from datetime import date

import pytest

from billing.models import Order
from billing.report import build_monthly_report


def order(
    order_id: str,
    amount_minor: int,
    *,
    currency: str = "CNY",
    region: str = "East",
    member_tier: str = "basic",
    coupon_code: str | None = None,
    status: str = "paid",
    paid_on: date = date(2026, 9, 15),
) -> Order:
    return Order(
        order_id=order_id,
        currency=currency,
        region=region,
        amount_minor=amount_minor,
        member_tier=member_tier,
        coupon_code=coupon_code,
        status=status,
        paid_on=paid_on,
    )


def september_orders() -> list[Order]:
    return [
        order("A-1001", 10000, currency="CNY", region="East"),
        order("A-1002", 20000, currency="USD", region="South", member_tier="gold"),
        order("A-1003", 5000, currency="CNY", region="North", member_tier="silver"),
    ]


def test_cancelled_orders_are_excluded() -> None:
    orders = september_orders() + [
        order("A-1004", 9999, status="cancelled"),
        order("A-1005", 8888, status="refunded"),
    ]

    report = build_monthly_report(orders, 2026, 9)

    assert report.order_count == 3
    assert [row.order_id for row in report.rows] == ["A-1001", "A-1002", "A-1003"]
    assert "A-1004" not in [row.order_id for row in report.rows]


def test_currency_filter() -> None:
    report = build_monthly_report(september_orders(), 2026, 9, currency="usd")

    assert report.order_count == 1
    assert [row.order_id for row in report.rows] == ["A-1002"]


def test_unknown_currency_returns_empty_report() -> None:
    report = build_monthly_report(september_orders(), 2026, 9, currency="GBP")

    assert report.order_count == 0
    assert report.totals_by_currency == {}
    assert report.rows == ()


def test_blank_currency_raises_value_error() -> None:
    with pytest.raises(ValueError):
        build_monthly_report(september_orders(), 2026, 9, currency="   ")


def test_totals_are_grouped_by_currency() -> None:
    report = build_monthly_report(september_orders(), 2026, 9)

    # A-1003 为银卡：5000 - 5000*300//10000 = 4850
    assert report.totals_by_currency == {"CNY": 10000 + 4850, "USD": 19000}


def test_rows_are_sorted_by_order_id() -> None:
    shuffled = list(reversed(september_orders()))

    report = build_monthly_report(shuffled, 2026, 9)

    assert [row.order_id for row in report.rows] == ["A-1001", "A-1002", "A-1003"]


def test_other_month_is_empty() -> None:
    report = build_monthly_report(september_orders(), 2026, 10)

    assert report.period == "2026-10"
    assert report.order_count == 0


def test_invalid_month_raises() -> None:
    with pytest.raises(ValueError):
        build_monthly_report(september_orders(), 2026, 13)
