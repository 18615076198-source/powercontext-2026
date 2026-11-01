"""功能验收：月度报表的 region 过滤（BR-REPORT-05 ~ BR-REPORT-08）。

这份用例代表「要改什么」，不改动、不实现就无法通过。
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
    status: str = "paid",
    paid_on: date = date(2026, 9, 10),
) -> Order:
    return Order(
        order_id=order_id,
        currency=currency,
        region=region,
        amount_minor=amount_minor,
        member_tier=member_tier,
        status=status,
        paid_on=paid_on,
    )


def september_orders() -> list[Order]:
    return [
        order("A-2001", 10000, currency="CNY", region="East"),
        order("A-2002", 5000, currency="CNY", region="East", member_tier="gold"),
        order("A-2003", 20000, currency="USD", region="South"),
        order("A-2004", 7000, currency="CNY", region="north", member_tier="silver"),
        order("A-2005", 3000, currency="EUR", region="East", member_tier="platinum"),
        order("A-2006", 99999, currency="CNY", region="East", status="cancelled"),
    ]


def test_region_filter_selects_matching_orders() -> None:
    report = build_monthly_report(september_orders(), 2026, 9, region="East")

    # 取消的 A-2006 不计入
    assert [row.order_id for row in report.rows] == ["A-2001", "A-2002", "A-2005"]
    assert report.order_count == 3


def test_region_filter_is_trimmed_and_case_insensitive() -> None:
    report = build_monthly_report(september_orders(), 2026, 9, region="  NORTH  ")

    assert [row.order_id for row in report.rows] == ["A-2004"]


def test_region_and_currency_filters_combine() -> None:
    report = build_monthly_report(september_orders(), 2026, 9, region="East", currency="CNY")

    assert [row.order_id for row in report.rows] == ["A-2001", "A-2002"]
    assert report.totals_by_currency == {"CNY": 10000 + 4750}


def test_region_none_keeps_previous_behaviour() -> None:
    report = build_monthly_report(september_orders(), 2026, 9)

    assert report.order_count == 5
    assert report.totals_by_currency == {"CNY": 10000 + 4750 + 6790, "USD": 20000, "EUR": 2760}


def test_unknown_region_returns_empty_report() -> None:
    report = build_monthly_report(september_orders(), 2026, 9, region="West")

    assert report.order_count == 0
    assert report.rows == ()
    assert report.totals_by_currency == {}
    assert report.totals_by_region == {}


def test_blank_region_raises_value_error() -> None:
    with pytest.raises(ValueError):
        build_monthly_report(september_orders(), 2026, 9, region="   ")


def test_totals_by_region_only_counts_filtered_orders() -> None:
    report = build_monthly_report(september_orders(), 2026, 9, currency="CNY")

    # 只统计过滤后的 CNY 订单：East 10000+4750，north 6790
    assert report.totals_by_region == {"East": 14750, "north": 6790}


def test_totals_by_region_keys_are_trimmed() -> None:
    orders = [order("A-3001", 1000, region="  East  "), order("A-3002", 2000, region="East")]

    report = build_monthly_report(orders, 2026, 9)

    assert report.totals_by_region == {"East": 3000}
