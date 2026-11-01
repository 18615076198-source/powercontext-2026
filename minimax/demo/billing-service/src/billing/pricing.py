"""定价与优惠计算（BR-PRICE-*）。"""

from __future__ import annotations

from .models import Order

# 会员折扣，单位为基点（万分之一），BR-PRICE-02。
TIER_DISCOUNT_BP = {
    "basic": 0,
    "silver": 300,
    "gold": 500,
    "platinum": 800,
}

# 优惠券定义，value 语义由 type 决定，BR-PRICE-03。
COUPONS = {
    "WELCOME10": {"type": "percent", "value": 1000},
    "SAVE500": {"type": "fixed", "value": 500},
}


def apply_coupon_minor(amount_minor: int, coupon_code: str | None) -> int:
    """先应用优惠券，再应用会员折扣（BR-PRICE-03）。"""

    if not coupon_code:
        return amount_minor
    coupon = COUPONS.get(coupon_code)
    if coupon is None:
        return amount_minor
    if coupon["type"] == "percent":
        return amount_minor - amount_minor * coupon["value"] // 10000
    return amount_minor - int(coupon["value"])


def apply_tier_discount_minor(amount_minor: int, member_tier: str) -> int:
    """按会员等级打折，结果向下取整到分（BR-PRICE-02）。"""

    bp = TIER_DISCOUNT_BP.get(member_tier, 0)
    return amount_minor - amount_minor * bp // 10000


def compute_payable_minor(order: Order) -> int:
    """计算一笔订单的应付金额，最低为 0（BR-PRICE-04）。"""

    after_coupon = apply_coupon_minor(order.amount_minor, order.coupon_code)
    payable = apply_tier_discount_minor(after_coupon, order.member_tier)
    return max(payable, 0)
