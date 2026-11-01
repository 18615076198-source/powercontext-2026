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
