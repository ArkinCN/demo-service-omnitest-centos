"""
Throttle decorator - 限制函数调用频率
"""
import time
import threading
from typing import Callable, Any, Optional
from functools import wraps


def throttle(interval: float = 60.0):
    """
    装饰器：限制函数在指定时间间隔内只执行一次

    Args:
        interval: 节流间隔（秒），默认 60 秒

    使用方式：
        @throttle(60)
        def update_something(user_id: int):
            ...

    节流按参数区分，即不同 user_id 独立计时
    """
    def decorator(func: Callable) -> Callable:
        last_calls: dict = {}
        lock = threading.Lock()

        @wraps(func)
        def wrapper(*args, **kwargs) -> Optional[Any]:
            if interval is None or interval <= 0:
                return func(*args, **kwargs)

            # 用参数作为 key，实现按用户独立节流
            # 注意：只用简单可哈希的参数作为 key
            try:
                key = (args, tuple(sorted(kwargs.items())))
            except Exception:
                key = str(args) + str(kwargs)

            now = time.time()

            with lock:
                last_call = last_calls.get(key, 0)
                if now - last_call < interval:
                    return None  # 节流中，跳过执行
                last_calls[key] = now

            return func(*args, **kwargs)

        return wrapper
    return decorator
