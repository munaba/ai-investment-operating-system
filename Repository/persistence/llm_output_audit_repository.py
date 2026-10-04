from __future__ import annotations

from typing import Optional
from Repository.persistence.base_persistence_repository import BasePersistenceRepository

class LlmOutputAuditRepository(BasePersistenceRepository):
    def create(
        self,
        timestamp: str,
        model: str,
        prompt_hash: str,
        source_data: str,
        response: str,
        tokens: Optional[int],
        latency_ms: Optional[int]
    ) -> int:
        cursor = self._execute(
            """
            INSERT INTO llm_output_audit
                (timestamp, model, prompt_hash, source_data, response, tokens, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (timestamp, model, prompt_hash, source_data, response, tokens, latency_ms),
        )
        return cursor.lastrowid
