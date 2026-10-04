from __future__ import annotations

from .migrations import Migration

LLM_OUTPUT_AUDIT_MIGRATIONS = (
    Migration(
        version=33,
        name="create_llm_output_audit_table",
        up_statements=[
            """
            CREATE TABLE IF NOT EXISTS llm_output_audit (
                audit_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp      TEXT NOT NULL,
                model          TEXT NOT NULL,
                prompt_hash    TEXT NOT NULL,
                source_data    TEXT NOT NULL,
                response       TEXT NOT NULL,
                tokens         INTEGER,
                latency_ms     INTEGER
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_llm_output_audit_timestamp ON llm_output_audit (timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_llm_output_audit_model ON llm_output_audit (model)",
            "CREATE INDEX IF NOT EXISTS idx_llm_output_audit_prompt_hash ON llm_output_audit (prompt_hash)"
        ],
    ),
)
