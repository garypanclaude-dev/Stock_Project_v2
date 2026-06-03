"""In-memory TTL cache for expensive external API calls."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)

_store: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def ttl_cache(ttl_seconds: int = 300):
    """
    Decorator that caches function results in memory with a TTL.
    Cache key is derived from function name + all arguments.
    Thread-safe.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = _make_key(func.__name__, args, kwargs)

            with _lock:
                if key in _store:
                    expires_at, value = _store[key]
                    if time.time() < expires_at:
                        logger.debug("Cache HIT: %s (ttl=%ds)", func.__name__, ttl_seconds)
                        return value
                    else:
                        del _store[key]

            logger.debug("Cache MISS: %s (ttl=%ds)", func.__name__, ttl_seconds)
            result = func(*args, **kwargs)

            with _lock:
                _store[key] = (time.time() + ttl_seconds, result)

            return result
        return wrapper
    return decorator


def invalidate(func_name: str | None = None):
    """Clear cache entries. If func_name given, only clear that function's entries."""
    with _lock:
        if func_name is None:
            _store.clear()
            logger.info("Cache fully cleared")
        else:
            keys_to_del = [k for k in _store if k.startswith(f"{func_name}:")]
            for k in keys_to_del:
                del _store[k]
            logger.info("Cache cleared for %s (%d entries)", func_name, len(keys_to_del))


def cache_stats() -> dict:
    """Return cache size and per-function entry counts."""
    with _lock:
        now = time.time()
        active = {k: v for k, v in _store.items() if v[0] > now}
        funcs: dict[str, int] = {}
        for k in active:
            name = k.split(":")[0]
            funcs[name] = funcs.get(name, 0) + 1
        return {"total_entries": len(active), "by_function": funcs}


def _make_key(func_name: str, args: tuple, kwargs: dict) -> str:
    raw = json.dumps({"a": [str(a) for a in args], "k": {str(k): str(v) for k, v in sorted(kwargs.items())}}, sort_keys=True)
    h = hashlib.md5(raw.encode()).hexdigest()[:12]
    return f"{func_name}:{h}"
