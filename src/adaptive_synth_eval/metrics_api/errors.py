"""Service-level failures exposed by the standalone metrics API."""


class EvaluationServiceUnavailable(RuntimeError):
    """The initialized evaluation dependency is temporarily unavailable."""

