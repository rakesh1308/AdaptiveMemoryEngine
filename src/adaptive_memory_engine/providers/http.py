"""Bounded retry support shared by remote AI providers."""

from __future__ import annotations

import logging
import random
import time
from email.utils import parsedate_to_datetime

import httpx

log = logging.getLogger(__name__)

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_attempts: int = 3,
    **kwargs,
) -> httpx.Response:
    """Issue an HTTP request with bounded exponential backoff.

    Only transient transport failures and retryable HTTP statuses are retried.
    The final response is returned so callers retain their normal
    ``raise_for_status`` and response-validation behavior.
    """
    last_error: httpx.RequestError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.request(method, url, **kwargs)
            if response.status_code not in _RETRYABLE_STATUS or attempt == max_attempts:
                return response
            delay = _retry_delay(response, attempt)
            log.warning(
                "Transient provider response status=%d; retrying attempt %d/%d in %.2fs",
                response.status_code,
                attempt + 1,
                max_attempts,
                delay,
            )
        except httpx.RequestError as exc:
            last_error = exc
            if attempt == max_attempts:
                raise
            delay = _backoff(attempt)
            log.warning(
                "Transient provider transport error %s; retrying attempt %d/%d in %.2fs",
                type(exc).__name__,
                attempt + 1,
                max_attempts,
                delay,
            )
        time.sleep(delay)
    assert last_error is not None  # pragma: no cover - loop always returns or raises
    raise last_error


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    value = response.headers.get("retry-after")
    if value:
        try:
            return min(30.0, max(0.0, float(value)))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                return min(30.0, max(0.0, retry_at.timestamp() - time.time()))
            except (TypeError, ValueError, OverflowError):
                pass
    return _backoff(attempt)


def _backoff(attempt: int) -> float:
    return min(8.0, (0.5 * (2 ** (attempt - 1))) + random.uniform(0.0, 0.25))
