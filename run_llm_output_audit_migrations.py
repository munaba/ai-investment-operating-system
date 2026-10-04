from __future__ import annotations

import sys

from Database.migration_cli_helper import apply_domain_migrations
from Database.migrations_llm_output_audit import LLM_OUTPUT_AUDIT_MIGRATIONS

def run_llm_output_audit_migrations() -> int:
    return apply_domain_migrations(LLM_OUTPUT_AUDIT_MIGRATIONS, "llm_output_audit")

def main() -> int:
    return run_llm_output_audit_migrations()

if __name__ == "__main__":
    sys.exit(main())
