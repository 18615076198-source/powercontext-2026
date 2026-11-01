"""结算域模型。

金额一律使用「分」为单位的整数（BR-PRICE-01），禁止出现浮点数金额。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Order:
    """一笔已支付订单。

    Attributes:
        order_id: 订单号，全局唯一。
        currency: ISO-4217 币种代码，如 CNY / USD。
        region: 销售区域，如 华东 / 华南 / 华北。
        amount_minor: 订单原始金额（分）。
        member_tier: 会员等级，见 pricing.TIER_DISCOUNT。
        coupon_code: 使用的优惠券代码，可为空。
        status: 订单状态，paid / cancelled / refunded。
        paid_on: 支付日期。
    """

    order_id: str
    currency: str
    region: str
    amount_minor: int
    member_tier: str = "basic"
    coupon_code: str | None = None
    status: str = "paid"
    paid_on: date = date(1970, 1, 1)

    @property
    def is_paid(self) -> bool:
        return self.status == "paid"


@dataclass(frozen=True)
class ReportRow:
    """报表中的一行，对应一笔已支付订单。"""

    order_id: str
    currency: str
    region: str
    amount_minor: int
    payable_minor: int


def _as_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def order_from_dict(payload: dict) -> Order:
    """从 JSON 结构构造订单，日期字段接受 ISO 字符串。"""

    return Order(
        order_id=payload["order_id"],
        currency=payload["currency"],
        region=payload["region"],
        amount_minor=int(payload["amount_minor"]),
        member_tier=payload.get("member_tier", "basic"),
        coupon_code=payload.get("coupon_code"),
        status=payload.get("status", "paid"),
        paid_on=_as_date(payload.get("paid_on", "1970-01-01")),
    )
