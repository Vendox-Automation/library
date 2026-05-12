"""Helpers to detect flaky-connection errors and retry a function a few times."""

from __future__ import annotations

import errno
import logging
import random
import socket
import ssl
import time
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)

try:
    import requests

    _REQUESTS_EXCEPTIONS = (
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.ChunkedEncodingError,
    )
except ImportError:  # pragma: no cover - requests is a declared dependency
    requests = None
    _REQUESTS_EXCEPTIONS = ()

try:
    from urllib3.exceptions import HTTPError as Urllib3HTTPError
    from urllib3.exceptions import MaxRetryError
    from urllib3.exceptions import NewConnectionError as Urllib3NewConnectionError
    from urllib3.exceptions import SSLError as Urllib3SSLError
    from urllib3.exceptions import TimeoutError as Urllib3TimeoutError
except ImportError:  # pragma: no cover
    Urllib3HTTPError = None
    MaxRetryError = None
    Urllib3NewConnectionError = None
    Urllib3SSLError = None
    Urllib3TimeoutError = None

# Messages that suggest misconfiguration or trust issues—not fixed by waiting.
_FATAL_TLS_OR_CERT_SUBSTRINGS = (
    "certificate verify failed",
    "certificate_verification_failed",
    "hostname mismatch",
    "hostname does not match",
    "self signed certificate",
    "ssl: wrong_version",
    "wrong ssl version",
)

# Message fragments that often mean "try again later" for network calls.
_RETRYABLE_NETWORK_MESSAGE_FRAGMENTS = (
    "ssl",
    "tls",
    "eof occurred",
    "unexpected_eof",
    "connection reset",
    "connection aborted",
    "connection refused",
    "broken pipe",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "try again",
    "connection pool",
    "httpsconnectionpool",
    "name or service not known",
    "nodename nor servname",
    "network is unreachable",
    "host is unreachable",
)


def _message_suggests_fatal_tls(msg_lower: str) -> bool:
    return any(s in msg_lower for s in _FATAL_TLS_OR_CERT_SUBSTRINGS)


def _message_suggests_retryable_network(msg_lower: str) -> bool:
    if _message_suggests_fatal_tls(msg_lower):
        return False
    return any(s in msg_lower for s in _RETRYABLE_NETWORK_MESSAGE_FRAGMENTS)


def _errno_suggests_retryable_network(err: OSError) -> bool:
    no = getattr(err, "errno", None)
    if no is None:
        return False
    retryable_errnos = {
        errno.ECONNRESET,
        errno.ECONNREFUSED,
        errno.ETIMEDOUT,
        errno.EPIPE,
        errno.ENETUNREACH,
        errno.EHOSTUNREACH,
        getattr(errno, "EAI_AGAIN", -1),
        getattr(errno, "WSAETIMEDOUT", -1),
        getattr(errno, "WSAECONNRESET", -1),
    }
    retryable_errnos.discard(-1)
    return no in retryable_errnos


def _exception_is_retryable_network_leaf(exc: BaseException) -> bool:
    """One exception object—retryable connection issue or not."""
    msg_lower = str(exc).lower()
    type_name_lower = type(exc).__name__.lower()

    if _message_suggests_fatal_tls(msg_lower):
        return False

    if requests and isinstance(exc, _REQUESTS_EXCEPTIONS):
        return True

    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True

    if requests and isinstance(exc, requests.exceptions.HTTPError):
        return False

    if (
        Urllib3TimeoutError is not None
        and Urllib3NewConnectionError is not None
        and MaxRetryError is not None
        and isinstance(
            exc, (Urllib3TimeoutError, Urllib3NewConnectionError, MaxRetryError)
        )
    ):
        return True

    if Urllib3SSLError is not None and isinstance(exc, Urllib3SSLError):
        return not _message_suggests_fatal_tls(msg_lower)

    if isinstance(exc, ssl.SSLError):
        return not _message_suggests_fatal_tls(msg_lower)

    if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
        return True

    # ConnectionError subclasses OSError — handle before generic OSError logic.
    if isinstance(exc, ConnectionError):
        return True

    if isinstance(exc, OSError):
        if _errno_suggests_retryable_network(exc):
            return True
        if _message_suggests_retryable_network(msg_lower):
            return True
        return False

    if Urllib3HTTPError is not None and isinstance(exc, Urllib3HTTPError):
        return _message_suggests_retryable_network(msg_lower)

    if any(k in type_name_lower for k in ("timeout", "connection", "ssl", "tls")):
        if not _message_suggests_fatal_tls(msg_lower):
            return _message_suggests_retryable_network(msg_lower) or True

    return _message_suggests_retryable_network(msg_lower)


def is_retryable_network_error(error: BaseException) -> bool:
    """True if ``error`` looks like a bad connection where trying again may help.

    Follows wrapped errors (``__cause__``). Wrong certs/hostname → False.
    """
    seen: set[int] = set()
    exc: Optional[BaseException] = error
    while exc is not None:
        if id(exc) in seen:
            break
        seen.add(id(exc))
        if _exception_is_retryable_network_leaf(exc):
            return True
        exc = exc.__cause__
    return False


def _compute_delay_seconds(
    attempt_index: int,
    base_delay_seconds: float,
    max_delay_seconds: float,
    jitter_seconds: float,
) -> float:
    """Seconds to wait before the next retry (0-based attempt index)."""
    exp = base_delay_seconds * (2**attempt_index)
    capped = min(exp, max_delay_seconds)
    jitter = random.uniform(0.0, max(0.0, jitter_seconds))
    return capped + jitter


def call_with_network_retry(
    fn: Callable[..., T],
    *args: Any,
    max_attempts: int = 5,
    base_delay_seconds: float = 2.0,
    max_delay_seconds: float = 60.0,
    jitter_seconds: float = 2.0,
    retry_on: Optional[Callable[[BaseException], bool]] = None,
    log: Optional[logging.Logger] = None,
    operation_name: Optional[str] = None,
    **kwargs: Any,
) -> T:
    """Run ``fn(*args, **kwargs)``.

    On a retryable connection-style error, wait and run again (up to ``max_attempts``).
    Other errors are not retried. Pass ``retry_on`` to change what counts as retryable
    (default is ``is_retryable_network_error``). Also supports ``log``, ``operation_name``,
    and the delay knobs ``base_delay_seconds``, ``max_delay_seconds``, ``jitter_seconds``.
    """
    log = log or logger
    label = operation_name or getattr(fn, "__name__", "callable")
    predicate = retry_on or is_retryable_network_error
    attempts = max(1, int(max_attempts))

    last_exc: Optional[BaseException] = None
    for attempt in range(attempts):
        try:
            return fn(*args, **kwargs)
        except BaseException as exc:
            last_exc = exc
            if attempt >= attempts - 1 or not predicate(exc):
                raise
            delay = _compute_delay_seconds(
                attempt,
                base_delay_seconds,
                max_delay_seconds,
                jitter_seconds,
            )
            log.warning(
                "%s failed (attempt %s/%s): %s — retrying in %.1fs",
                label,
                attempt + 1,
                attempts,
                exc,
                delay,
            )
            time.sleep(delay)

    assert last_exc is not None
    raise last_exc


__all__ = [
    "is_retryable_network_error",
    "call_with_network_retry",
]
