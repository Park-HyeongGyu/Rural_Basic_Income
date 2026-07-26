from __future__ import annotations


class AnalysisError(ValueError):
    """Base error for invalid analysis input or an unfit panel."""


class AnalysisSpecError(AnalysisError):
    """Raised when treatment/control/request settings are invalid."""


class PanelConstructionError(AnalysisError):
    """Raised when clean rows cannot produce a valid normalized panel."""


class RegressionError(AnalysisError):
    """Raised when the regression package cannot fit the requested model."""


class RegressionDependencyError(RegressionError):
    """Raised when PyFixest is unavailable in the current Python environment."""
