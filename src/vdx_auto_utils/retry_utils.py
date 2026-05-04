import time
from functools import wraps


def with_retry(max_attempts=5, delay_seconds=3):
    """
    Decorator to retry a function on exception or None return value.
    Delay increases by 2 seconds after each failed attempt.

        Args:
        max_attempts (int): Maximum number of retry attempts.
        delay_seconds (int): Initial delay between attempts in seconds.

        Returns:
        Decorated function with retry logic.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay_seconds
            result = None
            for attempt in range(1, max_attempts + 1):
                try:
                    result = func(*args, **kwargs)
                    if result is None:
                        raise ValueError("Function returned None")
                    return result
                except Exception as e:
                    if attempt == max_attempts:
                        print(
                            f"  ❌ [Attempt {attempt}/{max_attempts}] Final failure: {e}"
                        )
                        return [] if isinstance(result, list) else None
                    print(
                        f"  ⚠️ [Attempt {attempt}/{max_attempts}] Failed ({e}). Retrying in {current_delay}s..."
                    )
                    time.sleep(current_delay)
                    current_delay += 2

        return wrapper

    return decorator
