"""订单读取：JSON 文件与内存两种来源。"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from .models import Order, order_from_dict


class OrderRepository:
    """订单集合，支持按订单号读取与迭代。"""

    def __init__(self, orders: Iterable[Order]) -> None:
        self._orders: list[Order] = list(orders)
        self._by_id: dict[str, Order] = {order.order_id: order for order in self._orders}

    def __iter__(self) -> Iterator[Order]:
        return iter(self._orders)

    def __len__(self) -> int:
        return len(self._orders)

    def get(self, order_id: str) -> Order | None:
        return self._by_id.get(order_id)

    @classmethod
    def from_json_file(cls, path: str | Path) -> OrderRepository:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(order_from_dict(item) for item in payload["orders"])

    @classmethod
    def from_json_list(cls, items: Iterable[dict]) -> OrderRepository:
        return cls(order_from_dict(item) for item in items)
