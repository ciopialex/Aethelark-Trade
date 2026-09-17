"""Shared value objects for the 7-layer engine."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LayerScore:
    """One layer's contribution to the composite.

    ``score`` is None exactly when ``available`` is False, and the two are
    checked against each other at construction. That pairing used to live only
    in this docstring: ``unavailable()`` returned ``score=50``, the engine put
    it straight into the --json payload, and any consumer reading ``score``
    without also reading ``available`` was handed a fabricated neutral.

    Making the field None puts the rule where a type checker can see it, and
    makes arithmetic on a missing layer raise instead of quietly producing 50.
    Callers requiring a fallback specify it at the call site, via
    ``score_or``, where the substitution is visible in the code depending on it.
    """

    score: int | None
    summary: str
    available: bool = True
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.available and self.score is None:
            raise ValueError(
                "an available layer must carry a score; use "
                "LayerScore.unavailable(reason) when there is no data")
        if not self.available and self.score is not None:
            raise ValueError(
                f"an unavailable layer must not carry a score, got {self.score!r}; "
                "a number you have declared meaningless will be read as meaningful")

    @classmethod
    def unavailable(cls, reason: str) -> "LayerScore":
        """A layer we could not source. Carries a reason, never a number."""
        return cls(score=None, summary=reason, available=False)

    def score_or(self, default: int) -> int:
        """The score, or a default the caller has named explicitly."""
        return default if self.score is None else self.score
