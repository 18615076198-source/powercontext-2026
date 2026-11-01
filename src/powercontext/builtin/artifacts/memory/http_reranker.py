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

"""Score Memory candidates through one external HTTP reranking service."""

from __future__ import annotations

import math
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision, _validate_bounds
from powercontext.builtin.inference import InferenceUsage

HTTP_RERANK_POLICY_ID = "powercontext.memory.rerank.http.v1"
_DEFAULT_BATCH_SIZE = 16


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HTTPRerankCandidate(_StrictModel):
    """One identity-free candidate presented to the scoring service."""

    rank: int = Field(ge=1)
    text: str


class HTTPRerankRequest(_StrictModel):
    """One batched scoring request."""

    query: str
    candidates: tuple[HTTPRerankCandidate, ...]


class HTTPRerankScore(_StrictModel):
    """One scored candidate addressed by its global coarse rank."""

    rank: int
    score: float


class HTTPRerankResponse(_StrictModel):
    """The complete scored set for one batch."""

    scores: tuple[HTTPRerankScore, ...]


class HTTPMemoryReranker:
    """Select final hits from coarse candidates using an HTTP scoring service."""

    policy_id = HTTP_RERANK_POLICY_ID

    def __init__(
        self,
        url: str,
        *,
        client: httpx.AsyncClient | None = None,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        timeout_seconds: float | None = None,
    ) -> None:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("reranker url must be a non-empty string")  # noqa: TRY003
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
            raise ValueError("reranker batch_size must be a positive integer")  # noqa: TRY003
        self._url = url
        self._client = client
        self._batch_size = batch_size
        self._timeout_seconds = timeout_seconds

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Score every coarse candidate and keep the best requested ranks."""

        _validate_bounds(len(candidates), limit)
        if not isinstance(query, str) or not query.strip():
            raise ValueError("rerank query must be a non-empty string")  # noqa: TRY003
        scores: dict[int, float] = {}
        requests = 0
        for start in range(0, len(candidates), self._batch_size):
            batch = candidates[start : start + self._batch_size]
            payload = HTTPRerankRequest(
                query=query,
                candidates=tuple(
                    HTTPRerankCandidate(rank=start + offset + 1, text=candidate.text)
                    for offset, candidate in enumerate(batch)
                ),
            )
            scored = await self._score_batch(payload)
            expected = {candidate.rank for candidate in payload.candidates}
            observed = {entry.rank for entry in scored}
            if observed != expected:
                raise ValueError("rerank response must score every candidate rank exactly once")  # noqa: TRY003
            for entry in scored:
                if not math.isfinite(entry.score):
                    raise ValueError("rerank response scores must be finite")  # noqa: TRY003
                scores[entry.rank] = entry.score
            requests += 1

        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        selected = tuple(rank for rank, _score in ordered[:limit])
        return MemoryRerankDecision(
            selected_ranks=selected,
            usage=InferenceUsage(requests=requests),
            discarded_rank_count=len(candidates) - limit,
        )

    async def _score_batch(self, payload: HTTPRerankRequest) -> tuple[HTTPRerankScore, ...]:
        body: dict[str, Any] = {
            "query": payload.query,
            "candidates": [{"rank": c.rank, "text": c.text} for c in payload.candidates],
        }
        if self._client is None:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(self._url, json=body)
        else:
            response = await self._client.post(self._url, json=body)
        response.raise_for_status()
        return _parse_response(response)

    async def aclose(self) -> None:
        """Close the injected client when the caller owns no other reference."""

        if self._client is not None:
            await self._client.aclose()


def _parse_response(response: httpx.Response) -> tuple[HTTPRerankScore, ...]:
    try:
        raw = response.json()
    except ValueError as error:
        raise ValueError("rerank response must be valid JSON") from error  # noqa: TRY003
    if not isinstance(raw, dict) or set(raw) != {"scores"}:
        raise ValueError("rerank response must contain exactly one scores field")  # noqa: TRY003
    entries = raw["scores"]
    if not isinstance(entries, list):
        raise ValueError("rerank response scores must be a JSON array")  # noqa: TRY003, TRY004
    parsed: list[HTTPRerankScore] = []
    observed: set[int] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"rank", "score"}:
            raise ValueError("every rerank score must contain exactly rank and score")  # noqa: TRY003
        rank, score = entry["rank"], entry["score"]
        if not isinstance(rank, int) or isinstance(rank, bool):
            raise ValueError("rerank score rank must be an integer")  # noqa: TRY003, TRY004
        if not isinstance(score, int | float) or isinstance(score, bool):
            raise ValueError("rerank score value must be a number")  # noqa: TRY003, TRY004
        number = float(score)
        if not math.isfinite(number):
            raise ValueError("rerank score value must be finite")  # noqa: TRY003
        if rank in observed:
            raise ValueError("rerank response must not repeat a candidate rank")  # noqa: TRY003
        observed.add(rank)
        parsed.append(HTTPRerankScore(rank=rank, score=number))
    return tuple(parsed)


__all__ = [
    "HTTP_RERANK_POLICY_ID",
    "HTTPMemoryReranker",
    "HTTPRerankCandidate",
    "HTTPRerankRequest",
    "HTTPRerankResponse",
    "HTTPRerankScore",
]
