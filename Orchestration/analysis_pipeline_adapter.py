from typing import Any

class AnalysisPipelineAdapter:
    """Pure delegation adapter around an existing ``AnalysisPipeline``.

    This class stores a reference to an ``AnalysisPipeline`` instance and
    forwards every call directly to it, unchanged.

    Attributes:
        _analysis_pipeline: The wrapped ``AnalysisPipeline`` object,
            stored exactly as received.
    """

    def __init__(self, analysis_pipeline: Any) -> None:
        """Initialize the adapter with an existing pipeline instance.

        Args:
            analysis_pipeline: The ``AnalysisPipeline`` object to wrap.
                Stored exactly as received, with no validation,
                isinstance checks, or transformation.
        """
        self._analysis_pipeline = analysis_pipeline

    def health_check(self) -> bool:
        """Delegate the health check to the wrapped pipeline.

        Returns:
            bool: The result of ``self._analysis_pipeline.health_check()``.
        """
        return self._analysis_pipeline.health_check()

    def run(self, context: Any) -> Any:
        """Delegate execution to the wrapped pipeline.

        Args:
            context: The execution context to pass through unchanged.

        Returns:
            Any: The result of ``self._analysis_pipeline.run(context)``.
        """
        return self._analysis_pipeline.run(context)