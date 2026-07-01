"""内存缓存，用于 Embedding 结果去重——同一文本不重复调 API。"""
import hashlib

_cache: dict[str, list[float]] = {}


def embedding_key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def get_embedding(text: str) -> list[float] | None:
    return _cache.get(embedding_key(text))


def set_embedding(text: str, vector: list[float]) -> None:
    _cache[embedding_key(text)] = vector


def clear() -> None:
    _cache.clear()
