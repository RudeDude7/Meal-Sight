"""A tiny observer for the FINAL outcome of each provider call (after retries are exhausted).

The provider layer retries and the perception/reasoning layers above it deliberately swallow failures
into fallbacks, so a caller that only looks at return values cannot tell "the model answered badly" from
"the provider rejected every call". The evaluation harness subscribes here to tell those apart; nothing
in the product depends on a listener being present.
"""

from __future__ import annotations

from collections.abc import Callable

OK = "ok"
RATE_LIMITED = "rate_limited"  # HTTP 429 on every attempt
PROVIDER_ERROR = "provider_error"  # 5xx / timeout / unreachable on every attempt
AUTH_ERROR = "auth_error"  # 401 / 403: the key itself is rejected

Listener = Callable[[str, str], None]
_listeners: list[Listener] = []


def subscribe(listener: Listener) -> None:
    if listener not in _listeners:
        _listeners.append(listener)


def unsubscribe(listener: Listener) -> None:
    if listener in _listeners:
        _listeners.remove(listener)


def record(provider: str, outcome: str) -> None:
    for listener in list(_listeners):
        listener(provider, outcome)
