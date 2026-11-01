# 订单校验规格

## BR-VALID-01 金额合法性

- 优先级：必须
- 适用接口：`billing.validation.validate_order`
- 规则：`amount_minor` 必须是非负整数，`bool` 不视为整数。

## BR-VALID-02 币种白名单

- 优先级：必须
- 适用接口：`billing.validation.validate_order`
- 规则：币种必须属于 `SUPPORTED_CURRENCIES`（CNY/USD/EUR/JPY），比较时不区分大小写。

## BR-VALID-03 会员等级

- 优先级：必须
- 适用接口：`billing.validation.validate_order`
- 规则：`member_tier` 必须在 `TIER_DISCOUNT_BP` 中登记，未登记抛 `ValidationError`。

## BR-VALID-04 优惠券登记

- 优先级：必须
- 适用接口：`billing.validation.validate_order`
- 规则：`coupon_code` 允许为空；非空时必须在 `COUPONS` 中登记。

## BR-VALID-05 销售区域

- 优先级：必须
- 适用接口：`billing.validation.validate_order`
- 规则：`region` 去除首尾空白后不得为空，否则抛 `ValidationError`。
