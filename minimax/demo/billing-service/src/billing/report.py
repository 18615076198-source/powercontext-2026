"""月度结算报表（BR-REPORT-*）。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .models import Order, ReportRow
from .pricing import compute_payable_minor


@dataclass(frozen=True)
class MonthlyReport:
    """一个自然月的结算报表。

    Attributes:
        period: 报表周期，形如 ``2026-09``。
        order_count: 纳入报表的订单数。
        totals_by_currency: 各币种的应计金额合计（分），BR-REPORT-03。
        rows: 明细行，按订单号升序，BR-REPORT-04。
        totals_by_region: 各区域的应计金额合计（分），BR-REPORT-07。
    """

    period: str
    order_count: int
    totals_by_currency: dict[str, int] = field(default_factory=dict)
    rows: tuple[ReportRow, ...] = ()
    totals_by_region: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "order_count": self.order_count,
            "totals_by_currency": dict(sorted(self.totals_by_currency.items())),
            "totals_by_region": dict(sorted(self.totals_by_region.items())),
            "rows": [
                {
                    "order_id": row.order_id,
                    "currency": row.currency,
                    "region": row.region,
                    "amount_minor": row.amount_minor,
                    "payable_minor": row.payable_minor,
                }
                for row in self.rows
            ],
        }


def _in_period(order: Order, year: int, month: int) -> bool:
    return order.paid_on.year == year and order.paid_on.month == month


def build_monthly_report(
    orders: Iterable[Order],
    year: int,
    month: int,
    currency: str | None = None,
    region: str | None = None,
) -> MonthlyReport:
    """构造月度报表。

    Args:
        orders: 待统计订单，未支付订单不计入（BR-REPORT-01）。
        year: 年份。
        month: 月份，1-12。
        currency: 币种过滤，``None`` 表示不限币种（BR-REPORT-02）。
        region: 区域过滤，``None`` 表示不限区域（BR-REPORT-05）。

    Returns:
        MonthlyReport: 报表对象；过滤后无订单时返回空报表。
    """

    if not 1 <= month <= 12:
        raise ValueError(f"month 必须在 1-12 之间，收到 {month!r}")

    selected = [order for order in orders if order.is_paid and _in_period(order, year, month)]

    if currency is not None:
        wanted = currency.strip().upper()
        if not wanted:
            raise ValueError("currency 不能是空字符串，请传 None 表示不过滤")
        selected = [
            order for order in selected if order.currency.strip().upper() == wanted
        ]

    if region is not None:
        wanted_region = region.strip().casefold()
        if not wanted_region:
            raise ValueError("region 不能是空字符串，请传 None 表示不过滤")
        selected = [
            order
            for order in selected
            if order.region.strip().casefold() == wanted_region
        ]

    selected.sort(key=lambda order: order.order_id)

    totals: dict[str, int] = {}
    totals_by_region: dict[str, int] = {}
    rows: list[ReportRow] = []
    for order in selected:
        payable = compute_payable_minor(order)
        rows.append(
            ReportRow(
                order_id=order.order_id,
                currency=order.currency,
                region=order.region,
                amount_minor=order.amount_minor,
                payable_minor=payable,
            )
        )
        totals[order.currency] = totals.get(order.currency, 0) + payable

        region_key = order.region.strip()
        totals_by_region[region_key] = totals_by_region.get(region_key, 0) + payable

    return MonthlyReport(
        period=f"{year:04d}-{month:02d}",
        order_count=len(rows),
        totals_by_currency=totals,
        rows=tuple(rows),
        totals_by_region=totals_by_region,
    )
