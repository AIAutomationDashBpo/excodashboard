import json
import hashlib
import functools
from typing import Any, Optional
from cachetools import TTLCache
from app.config import settings

_cache: TTLCache = TTLCache(maxsize=512, ttl=settings.cache_ttl_seconds)


def _make_key(*args, **kwargs) -> str:
    raw = json.dumps({"a": [str(a) for a in args], "k": kwargs}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def cache_get(key: str) -> Optional[Any]:
    return _cache.get(key)


def cache_set(key: str, value: Any) -> None:
    _cache[key] = value


def cache_invalidate_prefix(prefix: str) -> None:
    keys = [k for k in list(_cache.keys()) if k.startswith(prefix)]
    for k in keys:
        _cache.pop(k, None)


def cached(prefix: str):
    """Decorator for async service functions."""
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            key = prefix + _make_key(*args, **kwargs)
            hit = cache_get(key)
            if hit is not None:
                return hit
            result = await fn(*args, **kwargs)
            cache_set(key, result)
            return result
        return wrapper
    return decorator
