# 月度报表规格

本文件是 `billing.report` 的唯一规格来源。每条 `BR-REPORT-*` 都是可独立验证的条目，
实现与测试都必须能追溯到条目编号。

## BR-REPORT-01 报表统计范围

- 优先级：必须
- 适用接口：`billing.report.build_monthly_report`
- 规则：只统计 `status == "paid"` 且 `paid_on` 落在目标年月的订单；`cancelled`、`refunded` 一律不计入 `order_count`，也不参与金额汇总。
- 验证：`tests/test_report.py::test_cancelled_orders_are_excluded`

## BR-REPORT-02 币种过滤

- 优先级：必须
- 适用接口：`billing.report.build_monthly_report(currency=...)`
- 规则：
  - `currency=None` 表示不限币种，返回该月全部已支付订单。
  - 传入币种时按 ISO-4217 代码匹配，比较前对入参与订单币种都做 `strip().upper()`。
  - 入参为纯空白字符串时抛 `ValueError`，不允许静默当作不过滤。
  - 过滤后没有任何订单时，返回 `order_count == 0`、`totals_by_currency == {}`、`rows == ()` 的空报表，不抛异常。
- 验证：`tests/test_report.py::test_currency_filter`、`tests/test_report.py::test_unknown_currency_returns_empty_report`

## BR-REPORT-03 金额汇总口径

- 优先级：必须
- 适用接口：`billing.report.MonthlyReport.totals_by_currency`
- 规则：按币种分组后累加「应付金额」（`billing.pricing.compute_payable_minor`），不同币种绝不混加；金额始终是整数分。
- 验证：`tests/test_report.py::test_totals_are_grouped_by_currency`

## BR-REPORT-04 明细行排序

- 优先级：必须
- 适用接口：`billing.report.MonthlyReport.rows`
- 规则：明细行按 `order_id` 的字典序升序排列，保证同一份数据每次导出的行序稳定。
- 验证：`tests/test_report.py::test_rows_are_sorted_by_order_id`

## BR-REPORT-05 区域过滤

- 优先级：必须
- 适用接口：`billing.report.build_monthly_report(region=...)`
- 规则：
  - 新增关键字参数 `region: str | None = None`，必须带默认值 `None`，保证既有调用方式不受影响。
  - `region=None` 表示不限区域。
  - 传入区域时与订单 `region` 比较，双方都先 `strip()` 再 `casefold()`，即去空白且大小写不敏感。
  - 入参 `strip()` 后为空字符串时抛 `ValueError`。
  - 过滤后无订单时返回空报表（`order_count == 0`、`totals_by_currency == {}`、`totals_by_region == {}`、`rows == ()`），不抛异常。
- 验证：`test_acceptance_report_region.py::test_region_filter_selects_matching_orders`、`::test_region_filter_is_trimmed_and_case_insensitive`、`::test_unknown_region_returns_empty_report`、`::test_blank_region_raises_value_error`

## BR-REPORT-06 过滤条件组合语义

- 优先级：必须
- 适用接口：`billing.report.build_monthly_report(currency=..., region=...)`
- 规则：`currency` 与 `region` 同时给出时取交集（AND），先按 `BR-REPORT-01` 的范围筛选，再依次应用两个过滤条件，顺序不影响结果。
- 验证：`test_acceptance_report_region.py::test_region_and_currency_filters_combine`

## BR-REPORT-07 区域汇总

- 优先级：必须
- 适用接口：`billing.report.MonthlyReport.totals_by_region`
- 规则：
  - `MonthlyReport` 新增字段 `totals_by_region: dict[str, int]`，默认空字典，键为区域名、值为该区域内应付金额合计（分）。
  - 只统计 **过滤后** 的订单；未应用 `region` 过滤时按订单自带的区域分组。
  - 键使用订单 `region` 去首尾空白后的原文，不做大小写归一，避免静默改写业务名称。
  - `to_dict()` 输出中必须包含 `totals_by_region`，且键按字典序排列。
- 验证：`test_acceptance_report_region.py::test_totals_by_region_only_counts_filtered_orders`、`::test_totals_by_region_keys_are_trimmed`

## BR-REPORT-08 向后兼容

- 优先级：必须
- 适用接口：`billing.report.build_monthly_report`、`billing.report.MonthlyReport`
- 规则：不传 `region` 时，`order_count`、`totals_by_currency`、`rows` 的内容与顺序必须与本次改动前完全一致；`tests/` 下既有用例必须全部通过。
- 验证：`test_acceptance_report_region.py::test_region_none_keeps_previous_behaviour` 与 `tests/` 全量回归
