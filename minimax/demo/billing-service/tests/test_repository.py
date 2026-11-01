"""仓储回归测试。"""

from __future__ import annotations

from pathlib import Path

from billing.repository import OrderRepository
from billing.report import build_monthly_report

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "orders_2026_09.json"


def test_load_orders_from_json_file() -> None:
    repo = OrderRepository.from_json_file(DATA_FILE)

    assert len(repo) == 7
    assert repo.get("A-1003") is not None
    assert repo.get("A-1003").coupon_code == "WELCOME10"  # type: ignore[union-attr]
    assert repo.get("not-there") is None


def test_report_over_repository_uses_paid_orders_of_the_month() -> None:
    repo = OrderRepository.from_json_file(DATA_FILE)

    report = build_monthly_report(repo, 2026, 9)

    # A-1004 取消、A-1006 退款、A-1007 落在 10 月，均不计入
    assert [row.order_id for row in report.rows] == ["A-1001", "A-1002", "A-1003", "A-1005"]
    # A-1003：6600 --WELCOME10--> 5940 --silver 300bp--> 5762
    assert report.totals_by_currency["CNY"] == 128000 + 5762
