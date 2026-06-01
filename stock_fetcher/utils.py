import time
import functools
import logging

logger = logging.getLogger(__name__)


def retry(max_retries=3, base_delay=1.0, backoff_factor=2.0, exceptions=(Exception,)):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (backoff_factor ** attempt)
                        logger.warning(
                            "Attempt %d/%d for %s failed: %s. Retrying in %.1fs...",
                            attempt + 1, max_retries, func.__name__, e, delay,
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "All %d attempts for %s failed.", max_retries, func.__name__
                        )
            raise last_exception
        return wrapper
    return decorator
