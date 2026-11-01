# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Coalesce concurrent embedding requests and cache vectors across calls."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any

from powercontext.builtin.inference.models import EmbeddingResult, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel

_DEFAULT_MAX_BATCH_SIZE = 8
_DEFAULT_CACHE_SIZE = 256


class CoalescingEmbeddingModel:
    """Batch duplicate and concurrent embeds behind one provider budget."""

    def __init__(
        self,
        base: EmbeddingModel,
        *,
        max_batch_size: int = _DEFAULT_MAX_BATCH_SIZE,
        coalesce_ms: int = 0,
        cache_size: int = _DEFAULT_CACHE_SIZE,
    ) -> None:
        if not isinstance(max_batch_size, int) or isinstance(max_batch_size, bool) or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if not isinstance(coalesce_ms, int | float) or isinstance(coalesce_ms, bool) or coalesce_ms < 0:
            raise ValueError("coalesce_ms must be a non-negative number")  # noqa: TRY003
        if not isinstance(cache_size, int) or isinstance(cache_size, bool) or cache_size < 0:
            raise ValueError("cache_size must be a non-negative integer")  # noqa: TRY003
        self._base = base
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = float(coalesce_ms) / 1000.0
        self._cache_size = cache_size
        self._cache: OrderedDict[str, tuple[float, ...]] = OrderedDict()
        self._pending: dict[str, asyncio.Future[tuple[tuple[float, ...], InferenceUsage]]] = {}
        self._drain_task: asyncio.Task[None] | None = None

    @property
    def profile(self) -> Any:
        return self._base.profile

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        """Return one vector per input text in request order."""

        values = tuple(texts)
        if not values:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))

        futures: dict[str, asyncio.Future[tuple[tuple[float, ...], InferenceUsage]]] = {}
        loop = asyncio.get_running_loop()
        for text in values:
            if text in futures or self._cached(text) is not None:
                continue
            future = self._pending.get(text)
            if future is None:
                future = loop.create_future()
                future.add_done_callback(_consume)
                self._pending[text] = future
            futures[text] = future

        if futures:
            if self._drain_task is None or self._drain_task.done():
                self._drain_task = loop.create_task(self._drain())
            await asyncio.gather(*(asyncio.shield(future) for future in futures.values()))

        vectors: list[tuple[float, ...]] = []
        usages: dict[int, InferenceUsage] = {}
        for text in values:
            if text in futures:
                vector, usage = futures[text].result()
                usages[id(usage)] = usage
            else:
                vector = self._cached(text)
                if vector is None:
                    raise ValueError("coalesced embedding result is missing a requested text")  # noqa: TRY003
            vectors.append(vector)
        return EmbeddingResult(vectors=tuple(vectors), usage=_aggregate(tuple(usages.values())))

    def _cached(self, text: str) -> tuple[float, ...] | None:
        if self._cache_size <= 0:
            return None
        vector = self._cache.get(text)
        if vector is not None:
            self._cache.move_to_end(text)
        return vector

    def _store(self, texts: tuple[str, ...], vectors: tuple[tuple[float, ...], ...]) -> None:
        if self._cache_size <= 0:
            return
        for text, vector in zip(texts, vectors, strict=True):
            self._cache[text] = vector
            self._cache.move_to_end(text)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    async def _drain(self) -> None:
        try:
            await asyncio.sleep(self._coalesce_seconds)
            while self._pending:
                batch = list(self._pending.items())[: self._max_batch_size]
                for text, _future in batch:
                    del self._pending[text]
                texts = tuple(text for text, _future in batch)
                futures = [future for _text, future in batch]
                try:
                    result = await self._base.embed(texts)
                    _validate(result, len(texts))
                    self._store(texts, result.vectors)
                except Exception as error:
                    for future in futures:
                        if not future.done():
                            future.set_exception(error)
                else:
                    for future, vector in zip(futures, result.vectors, strict=True):
                        if not future.done():
                            future.set_result((vector, result.usage))
        finally:
            self._drain_task = None


def _consume(future: asyncio.Future[Any]) -> None:
    if not future.cancelled():
        future.exception()


def _validate(result: EmbeddingResult, expected: int) -> None:
    if len(result.vectors) != expected:
        raise ValueError(  # noqa: TRY003
            f"embedding provider returned {len(result.vectors)} vectors for {expected} texts",
        )


def _aggregate(usages: tuple[InferenceUsage, ...]) -> InferenceUsage:
    requests = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    for usage in usages:
        requests += usage.requests
        if usage.input_tokens is not None:
            input_tokens = (input_tokens or 0) + usage.input_tokens
        if usage.output_tokens is not None:
            output_tokens = (output_tokens or 0) + usage.output_tokens
    return InferenceUsage(requests=requests, input_tokens=input_tokens, output_tokens=output_tokens)


__all__ = ["CoalescingEmbeddingModel"]
