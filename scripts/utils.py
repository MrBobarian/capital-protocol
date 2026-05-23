"""Shared helpers for Capital Protocol data collection pipeline."""

import json
import logging
import math
import os
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any


def retry(max_attempts: int = 4, base_delay: float = 2.0):
    """Decorator. Retries wrapped function on any Exception with exponential
    backoff and jitter: delays are roughly 2s, 5s, 11s (base_delay * 2^n + jitter).
    Jitter prevents thundering-herd re-triggers when multiple tickers retry together.
    Logs each retry attempt at WARNING level. Re-raises after all attempts exhausted.
    """
    import functools
    import time

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if attempt < max_attempts:
                        delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1)
                        logging.warning(
                            "Retry %d/%d for %s — %s: %s. Waiting %.1fs.",
                            attempt,
                            max_attempts - 1,
                            func.__name__,
                            type(e).__name__,
                            e,
                            delay,
                        )
                        time.sleep(delay)
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator


def safe_float(value: Any, round_digits: int = 4) -> float | None:
    """Returns rounded float or None if value is None, NaN, or non-numeric.
    Handles strings, ints, floats. Returns None for inf values too.
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, round_digits)


def load_json(path: str | Path) -> dict:
    """Loads JSON from path. Returns empty dict if file does not exist or is
    not valid JSON (logs a warning in that case).
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as e:
        logging.warning("Could not load JSON from %s: %s", path, e)
        return {}


class _SafeEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy scalars and other non-standard types.
    Falls back gracefully so a stray numpy.bool_ or numpy.float32 never
    crashes the whole pipeline.
    """

    def default(self, obj: Any) -> Any:
        # numpy scalar types (bool_, int_, float32, float64, …)
        try:
            import numpy as np  # optional dep — only import when needed

            if isinstance(obj, np.bool_):
                return bool(obj)
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                f = float(obj)
                return None if (math.isnan(f) or math.isinf(f)) else f
            if isinstance(obj, np.ndarray):
                return obj.tolist()
        except ImportError:
            pass
        return super().default(obj)


def write_json(path: str | Path, data: dict) -> None:
    """Writes data to path as formatted JSON (indent=2).
    Creates parent directories as needed.
    Writes atomically: writes to a .tmp file first, then renames.
    Uses _SafeEncoder to handle numpy scalar types without crashing.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, cls=_SafeEncoder)
    os.replace(tmp, p)


def trading_days_back(n: int) -> list[str]:
    """Returns list of ISO date strings (YYYY-MM-DD) for the last n weekdays
    (Monday–Friday), most recent first. Does not account for holidays —
    weekdays only.
    """
    results: list[str] = []
    current = date.today()
    while len(results) < n:
        current -= timedelta(days=1)
        if current.weekday() < 5:  # 0=Monday … 4=Friday
            results.append(current.isoformat())
    return results
