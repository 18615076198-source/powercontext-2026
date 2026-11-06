from __future__ import annotations

import logging
import os
import threading
from typing import Iterable

import numpy as np

from .config import settings

log = logging.getLogger(__name__)

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from fastembed import TextEmbedding

                log.info("loading embedding model %s", settings.embed_model)
                _model = TextEmbedding(model_name=settings.embed_model)
    return _model


def _normalize(vec: Iterable[float]) -> list[float]:
    arr = np.asarray(list(vec), dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm > 0:
        arr = arr / norm
    return arr.tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = _get_model()
    return [_normalize(v) for v in model.embed(texts)]


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def vector_literal(vec: Iterable[float]) -> str:
    return "[" + ",".join(f"{float(x):.7f}" for x in vec) + "]"
