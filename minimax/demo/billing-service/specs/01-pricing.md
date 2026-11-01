# 定价与优惠规格

## BR-PRICE-01 金额单位

- 优先级：必须
- 适用接口：`billing.models.Order.amount_minor`
- 规则：所有金额字段以「分」为单位的整数存储与计算，禁止使用浮点数；比率一律用基点（万分之一）整数表示。

## BR-PRICE-02 会员折扣

- 优先级：必须
- 适用接口：`billing.pricing.apply_tier_discount_minor`
- 规则：折扣率见 `TIER_DISCOUNT_BP`，`basic` 0bp、`silver` 300bp、`gold` 500bp、`platinum` 800bp；折扣结果向下取整到分。

## BR-PRICE-03 优惠券与折扣的叠加顺序

- 优先级：必须
- 适用接口：`billing.pricing.compute_payable_minor`
- 规则：先应用优惠券（`percent` 按比例、`fixed` 按固定金额），再应用会员折扣；未登记的优惠券按不使用处理。

## BR-PRICE-04 应付金额下限

- 优先级：必须
- 适用接口：`billing.pricing.compute_payable_minor`
- 规则：优惠后应付金额不得为负，最低为 0 分。
