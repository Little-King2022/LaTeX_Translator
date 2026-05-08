import asyncio
import threading
from collections.abc import Callable, Coroutine
from typing import Any


_running: set[tuple[Any, ...]] = set()
_lock = threading.Lock()


def run_background(coro_func: Callable[..., Coroutine[Any, Any, None]], *args: Any) -> bool:
    key = (coro_func.__name__, *args)
    with _lock:
        if key in _running:
            return False
        _running.add(key)

    def target() -> None:
        try:
            asyncio.run(coro_func(*args))
        finally:
            with _lock:
                _running.discard(key)

    thread = threading.Thread(target=target, name=f"worker:{coro_func.__name__}", daemon=True)
    thread.start()
    return True
