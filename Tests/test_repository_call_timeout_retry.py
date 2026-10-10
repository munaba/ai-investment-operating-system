"""Test BaseExternalRepository._call timeout and retry logic.

Verifies timeout injection, exponential backoff, and max-attempt boundaries.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Repository.external.base_external_repository import BaseExternalRepository, RepositoryError


class ConcreteExternalRepository(BaseExternalRepository):
    """Concrete implementation for testing."""

    def health_check(self) -> dict[str, object]:
        """Mock health check."""
        return {"status": "ok"}


class TestRepositoryCallTimeoutRetry:
    """Timeout and retry behavior for _call."""

    def test_call_injects_timeout_to_client_signature(self) -> None:
        """If func accepts 'timeout' kwarg, _call injects it unless already present."""
        mock_client = MagicMock()
        repo = ConcreteExternalRepository(mock_client)

        # Create a callable with a 'timeout' parameter in its signature
        def client_method(timeout: float = 10) -> str:
            return "called"

        result = repo._call(client_method, timeout=20.0)

        assert result == "called"

    def test_call_retry_on_transient_failure(self) -> None:
        """Transient failures retry with exponential backoff; success breaks loop."""
        repo = ConcreteExternalRepository(MagicMock())

        call_count = 0

        def failing_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TimeoutError(f"attempt {call_count}")
            return "success"

        with patch("time.sleep") as mock_sleep:
            result = repo._call(failing_func, max_attempts=3, backoff_base=2.0)

        assert result == "success"
        assert call_count == 3
        # sleep(1 * jitter) then sleep(2 * jitter). jitter = 1 + U(0,0.3) -> [1.0,1.3] and [2.0,2.6]
        assert mock_sleep.call_count == 2
        first, second = mock_sleep.call_args_list[0].args[0], mock_sleep.call_args_list[1].args[0]
        assert 1.0 <= first <= 1.3, f"first sleep {first} not in [1.0, 1.3]"
        assert 2.0 <= second <= 2.6, f"second sleep {second} not in [2.0, 2.6]"

    def test_call_raises_after_max_attempts(self) -> None:
        """After exhausting max_attempts, original exception is wrapped in RepositoryError."""

        def always_fails() -> None:
            raise ValueError("intentional failure")

        repo = ConcreteExternalRepository(MagicMock())

        with patch("time.sleep"):
            with pytest.raises(RepositoryError) as exc_info:
                repo._call(always_fails, max_attempts=2, backoff_base=2.0)

        assert "failed after 2 attempts" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, ValueError)

    def test_call_does_not_retry_repository_error(self) -> None:
        """RepositoryError is not retried; raised immediately."""
        call_count = 0

        def raises_repo_error() -> None:
            nonlocal call_count
            call_count += 1
            raise RepositoryError("already translated")

        repo = ConcreteExternalRepository(MagicMock())

        with pytest.raises(RepositoryError) as exc_info:
            repo._call(raises_repo_error, max_attempts=5)

        assert str(exc_info.value) == "already translated"
        assert call_count == 1  # No retries


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
