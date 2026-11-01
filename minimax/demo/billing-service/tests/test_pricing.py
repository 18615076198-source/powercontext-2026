"""定价回归测试：对应 specs/01-pricing.md 的 BR-PRICE-01..04。"""

from __future__ import annotations

from datetime import date

from billing.models import Order
from billing.pricing import (
    apply_coupon_minor,
    apply_tier_discount_minor,
    compute_payable_minor,
)


def order(amount_minor: int, *, member_tier: str = "basic", coupon_code: str | None = None) -> Order:
    return Order(
        order_id="A-0001",
        currency="CNY",
        region="East",
        amount_minor=amount_minor,
        member_tier=member_tier,
        coupon_code=coupon_code,
        paid_on=date(2026, 9, 1),
    )


def test_amounts_are_integer_minor_units() -> None:
    assert isinstance(order(10000).amount_minor, int)


def test_tier_discount_uses_basis_points() -> None:
    assert apply_tier_discount_minor(10000, "silver") == 9700
    assert apply_tier_discount_minor(10000, "gold") == 9500
    assert apply_tier_discount_minor(10000, "platinum") == 9200
    assert apply_tier_discount_minor(10000, "basic") == 10000


def test_unknown_tier_gets_no_discount() -> None:
    assert apply_tier_discount_minor(10000, "vip") == 10000


def test_coupon_types() -> None:
    assert apply_coupon_minor(10000, "WELCOME10") == 9000
    assert apply_coupon_minor(10000, "SAVE500") == 9500
    assert apply_coupon_minor(10000, None) == 10000
    assert apply_coupon_minor(10000, "NOT_EXIST") == 10000


def test_coupon_is_applied_before_tier_discount() -> None:
    # 先券后折：10000 -> 9000 -> 9000 - 9000*500//10000 = 8550
    assert compute_payable_minor(order(10000, member_tier="gold", coupon_code="WELCOME10")) == 8550


def test_payable_never_negative() -> None:
    assert compute_payable_minor(order(300, coupon_code="SAVE500")) == 0


def test_rounding_floors_to_minor_unit() -> None:
    # 9999 * 300 // 10000 = 299 -> 9700
    assert apply_tier_discount_minor(9999, "silver") == 9700
