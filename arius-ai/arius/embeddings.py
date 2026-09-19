"""Text embeddings for semantic (similarity-based) recall.

Two backends, both exposing the same tiny interface:

  * HashingEmbedder (default, standard library only)
      Character n-gram feature hashing into a fixed-size L2-normalized vector.
      No downloads, works offline, and copes well with Korean morphology
      because n-grams catch variants like 설치 / 설치법 / 설치하기.
  * SentenceTransformerEmbedder (optional)
      Real neural sentence embeddings via `sentence-transformers`, using a
      multilingual model by default. Install: `pip install sentence-transformers`.
  * OllamaEmbedder (optional, no Python deps)
      Neural embeddings served by a local Ollama instance (`ollama pull bge-m3`).
      Keeps the whole stack offline and on your own machine.

Vectors are stored as float32 blobs in SQLite (see memory.py) so recall can
rank by cosine similarity instead of exact keyword hits.
"""

from __future__ import annotations

import math
import re
import zlib
from abc import ABC, abstractmethod
from array import array
from collections.abc import Iterable

_WS = re.compile(r"\s+")


class Embedder(ABC):
    name: str = "base"
    dim: int = 0

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return an L2-normalized vector for the text."""

    def embed_many(self, texts: Iterable[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


# --- vector helpers ---------------------------------------------------------


def cosine(a: list[float], b: list[float]) -> float:
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)


def to_blob(vec: list[float]) -> bytes:
    return array("f", vec).tobytes()


def from_blob(blob: bytes) -> list[float]:
    arr = array("f")
    arr.frombytes(blob)
    return list(arr)


def chunk_text(text: str, size: int = 500, overlap: int = 80) -> list[str]:
    """Split long text into overlapping passages, preferring natural breaks."""
    text = text.strip()
    if not text:
        return []
    if size <= 0:
        raise ValueError("size must be positive")
    overlap = max(0, min(overlap, size - 1))
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + size)
        if end < n:
            window_start = start + int(size * 0.6)
            brk = max(text.rfind("\n", window_start, end), text.rfind(" ", window_start, end))
            if brk > start:
                end = brk
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


# --- backends ---------------------------------------------------------------


class HashingEmbedder(Embedder):
    """Feature-hashing embedder: deterministic, dependency-free."""

    name = "hashing-v1"

    def __init__(self, dim: int = 512, ngrams: tuple[int, ...] = (2, 3)) -> None:
        self.dim = dim
        self.ngrams = ngrams

    def _features(self, text: str) -> list[str]:
        t = _WS.sub(" ", text.lower()).strip()
        feats: list[str] = [f"w:{w}" for w in t.split(" ") if w]
        padded = f" {t} "
        for n in self.ngrams:
            for i in range(len(padded) - n + 1):
                gram = padded[i : i + n]
                if gram.strip():
                    feats.append(f"c{n}:{gram}")
        return feats

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        counts: dict[str, int] = {}
        for f in self._features(text):
            counts[f] = counts.get(f, 0) + 1
        for f, c in counts.items():
            h = zlib.crc32(f.encode("utf-8"))
            idx = h % self.dim
            sign = 1.0 if ((h >> 31) & 1) == 0 else -1.0
            vec[idx] += sign * (1.0 + math.log(c))
        norm = math.sqrt(sum(v * v for v in vec))
        if norm:
            vec = [v / norm for v in vec]
        return vec


class SentenceTransformerEmbedder(Embedder):
    """Neural embeddings via sentence-transformers (optional dependency)."""

    def __init__(self, model: str = "paraphrase-multilingual-MiniLM-L12-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "`sentence-transformers` 패키지가 필요합니다: `pip install sentence-transformers`"
            ) from exc
        self._model = SentenceTransformer(model)
        self.name = f"st:{model}"
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, text: str) -> list[float]:
        vec = self._model.encode(text, normalize_embeddings=True)
        return [float(x) for x in vec]

    def embed_many(self, texts: Iterable[str]) -> list[list[float]]:
        vecs = self._model.encode(list(texts), normalize_embeddings=True)
        return [[float(x) for x in v] for v in vecs]


class OllamaEmbedder(Embedder):
    """Neural embeddings from a local Ollama server (no Python dependencies)."""

    def __init__(self, model: str = "bge-m3", base_url: str = "http://localhost:11434", transport=None) -> None:
        from arius.ollama import http_json, probe

        self.model = model
        self.base_url = base_url
        self._transport = transport or http_json(base_url)
        reason = probe(self._transport, model, base_url)
        if reason:
            raise RuntimeError(reason)
        self.name = f"ollama:{model}"
        self.dim = len(self.embed("차원 확인"))

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: Iterable[str]) -> list[list[float]]:
        items = list(texts)
        if not items:
            return []
        try:
            resp = self._transport("POST", "/api/embed", {"model": self.model, "input": items}, 120.0)
            raw = resp["embeddings"]
        except Exception:
            # Older Ollama servers only have /api/embeddings, one prompt at a time.
            raw = []
            for t in items:
                r = self._transport("POST", "/api/embeddings", {"model": self.model, "prompt": t}, 120.0)
                raw.append(r["embedding"])
        return [_unit(list(map(float, v))) for v in raw]


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def build_embedder(config) -> Embedder:
    """Construct the configured embedder, degrading to hashing if unavailable."""
    emb = config.embeddings
    backend = (emb.backend or "hashing").lower()
    if backend in ("sentence-transformers", "st", "neural"):
        try:
            return SentenceTransformerEmbedder(emb.model)
        except RuntimeError:
            pass
    if backend == "ollama":
        from arius.ollama import DEFAULT_EMBED_MODEL

        model = emb.model
        # The sentence-transformers default is not an Ollama model; use the local default.
        if not model or model == EmbeddingsDefaults.ST_MODEL:
            model = DEFAULT_EMBED_MODEL
        try:
            return OllamaEmbedder(model, emb.base_url)
        except RuntimeError:
            pass
    return HashingEmbedder(dim=emb.dim)


class EmbeddingsDefaults:
    ST_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
