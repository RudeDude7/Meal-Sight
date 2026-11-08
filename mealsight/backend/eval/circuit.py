"""Circuit breaker: an infrastructure failure must not be recorded as a quality score.

If the provider rejects the calls (429 on every attempt, 5xx, a rejected key), the pipeline above it
swallows each failure into a fallback and the dimension finishes "successfully" with a score near zero.
That number measures the outage, not the product, and if the regression gate ever accepted it as a
baseline it would poison every later comparison. So the harness watches the FINAL outcome of every
provider call (mealsight.providers.outcomes) and aborts the run when too many are failures.

THRESHOLD: within one dimension, once at least MIN_CALLS provider calls have finished, abort if
FAILURE_RATIO or more of them failed (rate limited, provider error, or rejected key).
  * Each counted failure has ALREADY survived the retry schedule (4 attempts, 2/5/10 s backoff), so one
    is a real outage-grade event, not a blip. A healthy run records none.
  * 5 calls is the smallest sample where "half failed" is not one unlucky call; it also bounds the cost of
    a systemic outage to roughly five calls' retry time (about a minute and a half) instead of the whole run.
  * 0.5 leaves room for a few genuine transient failures in a long dimension without tripping, while a
    systemic failure (ratio ~1.0) trips as soon as MIN_CALLS is reached.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from mealsight.providers import outcomes

MIN_CALLS = 5
FAILURE_RATIO = 0.5


class InfrastructureFailure(Exception):
    """The run was aborted because the provider, not the product, was failing."""

    def __init__(self, dimension: str, detail: dict[str, object]) -> None:
        self.dimension = dimension
        self.detail = detail
        super().__init__(self.reason)

    @property
    def reason(self) -> str:
        d = self.detail
        return (
            f"{self.dimension}: {d['failed']} of {d['calls']} provider calls failed after retries "
            f"({d['by_outcome']}); threshold {d['threshold']}. This is an infrastructure failure "
            "(rate limiting, provider errors or a rejected key), not a quality score."
        )


@dataclass
class CircuitBreaker:
    min_calls: int = MIN_CALLS
    failure_ratio: float = FAILURE_RATIO
    dimension: str = ""
    counts: Counter[str] = field(default_factory=Counter)

    def start(self, dimension: str) -> None:
        self.dimension = dimension
        self.counts = Counter()
        outcomes.subscribe(self._on_outcome)

    def stop(self) -> None:
        outcomes.unsubscribe(self._on_outcome)

    def _on_outcome(self, provider: str, outcome: str) -> None:
        self.counts[outcome] += 1

    @property
    def calls(self) -> int:
        return sum(self.counts.values())

    @property
    def failed(self) -> int:
        return self.calls - self.counts[outcomes.OK]

    def check(self) -> None:
        """Call between cases. Raises InfrastructureFailure when the dimension is systemically failing."""
        if self.calls >= self.min_calls and self.failed / self.calls >= self.failure_ratio:
            raise InfrastructureFailure(
                self.dimension,
                {
                    "calls": self.calls,
                    "failed": self.failed,
                    "by_outcome": dict(self.counts),
                    "threshold": f">= {self.failure_ratio:.0%} of at least {self.min_calls} calls",
                },
            )


breaker = CircuitBreaker()
