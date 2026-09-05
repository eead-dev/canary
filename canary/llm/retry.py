"""Bounded retries of the same provider turn for explicit transient statuses."""

import math
import random
import time


TRANSIENT = {429, 500, 502, 503, 504}


def is_transient(exc: Exception) -> bool:
    # Prefer structured HTTP status. Never guess from arbitrary exception text.
    for value in (getattr(exc, "code", None), getattr(exc, "status_code", None),
                  getattr(getattr(exc, "response", None), "status_code", None)):
        if type(value) is int or (type(value) is str and value.isdigit()):
            return int(value) in TRANSIENT
    return getattr(exc, "status", None) in ("RESOURCE_EXHAUSTED", "UNAVAILABLE") or (
        getattr(exc, "code", None) in ("RESOURCE_EXHAUSTED", "UNAVAILABLE"))


class RetryingProvider:
    """Counters accumulate over one run; retry allowance resets each model turn."""

    def __init__(self, provider, *, max_retries=3, base_delay_seconds=1.0,
                 max_delay_seconds=8.0, sleep=None, jitter=None):
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("max_retries must be a nonnegative integer")
        for value in (base_delay_seconds, max_delay_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("retry delays must be finite nonnegative numbers")
        self.provider = provider
        self.max_retries = max_retries
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.sleep = time.sleep if sleep is None else sleep
        self.jitter = random.uniform if jitter is None else jitter
        self.retry_count = 0
        self.provider_attempts = 0

    def respond(self, system, messages, tools, conclusion_schema):
        delay_cap = min(self.base_delay_seconds, self.max_delay_seconds)
        for retry in range(self.max_retries + 1):
            self.provider_attempts += 1
            try:
                return self.provider.respond(system, messages, tools, conclusion_schema)
            except Exception as exc:
                if retry == self.max_retries or not is_transient(exc):
                    raise
                # Equal jitter: exponential cap with a uniform half-to-full delay.
                delay = self.jitter(delay_cap / 2, delay_cap)
                self.sleep(delay)
                self.retry_count += 1
                delay_cap = min(delay_cap * 2, self.max_delay_seconds)
