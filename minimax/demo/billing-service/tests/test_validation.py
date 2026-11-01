"""校验回归测试：对应 specs/03-validation.md 的 BR-VALID-01..05。"""

from __future__ import annotations

import pytest

from billing.models import Order
from billing.validation import ValidationError, validate_order


def order(**overrides) -> Order:
    payload = {
        "order_id": "A-0001",
        "currency": "CNY",
        "region": "East",
        "amount_minor": 10000,
    }
    payload.update(overrides)
    return Order(**payload)


def test_valid_order_passes() -> None:
    validate_order(order())


def test_negative_amount_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_order(order(amount_minor=-1))


def test_bool_amount_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_order(order(amount_minor=True))


def test_unsupported_currency_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_order(order(currency="GBP"))


def test_currency_is_case_insensitive() -> None:
    validate_order(order(currency="cny"))


def test_unknown_tier_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_order(order(member_tier="vip"))


def test_unknown_coupon_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_order(order(coupon_code="NOT_EXIST"))


def test_blank_region_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_order(order(region="   "))
