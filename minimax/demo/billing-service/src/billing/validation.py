"""订单校验（BR-VALID-*）。"""

from __future__ import annotations

from .models import Order
from .pricing import COUPONS, TIER_DISCOUNT_BP

SUPPORTED_CURRENCIES = {"CNY", "USD", "EUR", "JPY"}


class ValidationError(ValueError):
    """订单数据不满足规格时抛出。"""


def validate_order(order: Order) -> None:
    """校验单笔订单，失败时抛出 ValidationError。

    规则见 ``specs/03-validation.md``：

    - BR-VALID-01：金额必须是非负整数（分）。
    - BR-VALID-02：币种必须在支持列表内。
    - BR-VALID-03：会员等级必须已登记。
    - BR-VALID-04：优惠券代码必须已登记，允许为空。
    - BR-VALID-05：区域不得为空。
    """

    if not isinstance(order.amount_minor, int) or isinstance(order.amount_minor, bool):
        raise ValidationError(f"{order.order_id}: 金额必须是整数分，收到 {order.amount_minor!r}")
    if order.amount_minor < 0:
        raise ValidationError(f"{order.order_id}: 金额不能为负，收到 {order.amount_minor}")
    if order.currency.upper() not in SUPPORTED_CURRENCIES:
        raise ValidationError(f"{order.order_id}: 不支持的币种 {order.currency!r}")
    if order.member_tier not in TIER_DISCOUNT_BP:
        raise ValidationError(f"{order.order_id}: 未登记的会员等级 {order.member_tier!r}")
    if order.coupon_code and order.coupon_code not in COUPONS:
        raise ValidationError(f"{order.order_id}: 未登记的优惠券 {order.coupon_code!r}")
    if not order.region.strip():
        raise ValidationError(f"{order.order_id}: 区域不能为空")
