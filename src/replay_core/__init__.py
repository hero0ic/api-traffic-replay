"""Record HTTP requests and compare replays for regressions.

Comparison is deterministic. A later service can store the report or ask a
model to explain it, but the model does not decide whether something changed.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
