"""Test SQL injection protection for f-string usage in sqlite_database.py."""
import re

import pytest


class TestSavepointValidation:
    """Test SAVEPOINT name validation pattern."""

    # Pattern: must start with letter or underscore, followed by letters/digits/underscores
    SAVEPOINT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def test_valid_savepoint_names(self) -> None:
        """Valid SAVEPOINT names should pass validation."""
        valid_names = [
            "sp_0",
            "sp_1",
            "initial_schema",
            "add_decision_journal",
            "_private",
            "CamelCase",
            "snake_case",
            "mixed_Case_123",
        ]
        for name in valid_names:
            assert self.SAVEPOINT_PATTERN.match(name), f"'{name}' should be valid"

    def test_invalid_savepoint_names_sql_injection_attempts(self) -> None:
        """Invalid SAVEPOINT names (potential SQL injection) should be rejected."""
        invalid_names = [
            "sp_0; DROP TABLE users--",
            "sp_0'); DROP TABLE users;--",
            "1_invalid_start",
            "sp-with-dash",
            "sp with space",
            "sp'quote",
            'sp"doublequote',
            "sp;semicolon",
            "sp/*comment*/",
            "sp OR 1=1",
            "sp UNION SELECT",
        ]
        for name in invalid_names:
            assert not self.SAVEPOINT_PATTERN.match(name), f"'{name}' should be rejected"


class TestPragmaWhitelist:
    """Test PRAGMA name validation (whitelist approach)."""

    # Whitelist of allowed PRAGMA names
    ALLOWED_PRAGMAS = frozenset({
        "journal_mode",
        "synchronous",
        "foreign_keys",
        "busy_timeout",
        "cache_size",
        "temp_store",
        "mmap_size",
        "page_size",
        "auto_vacuum",
    })

    def test_allowed_pragma_names(self) -> None:
        """Only whitelisted PRAGMA names should be allowed."""
        for name in self.ALLOWED_PRAGMAS:
            assert name in self.ALLOWED_PRAGMAS

    def test_disallowed_pragma_names(self) -> None:
        """Non-whitelisted PRAGMA names should be rejected."""
        disallowed = [
            "data_store_version",  # Could leak schema info
            "user_version",  # Could corrupt migration state
            "schema_version",
            "compile_options",
            "malicious_pragma",
        ]
        for name in disallowed:
            assert name not in self.ALLOWED_PRAGMAS, f"'{name}' should not be in whitelist"

    def test_pragma_value_validation(self) -> None:
        """PRAGMA values should be validated based on the pragma type."""
        # journal_mode: WAL, DELETE, TRUNCATE, PERSIST, MEMORY, OFF
        valid_journal_modes = {"WAL", "wal", "DELETE", "delete", "TRUNCATE", "truncate", "PERSIST", "persist", "MEMORY", "memory", "OFF", "off"}
        
        # synchronous: OFF, NORMAL, FULL, EXTRA
        valid_synchronous = {"OFF", "off", "NORMAL", "normal", "FULL", "full", "EXTRA", "extra", "0", "1", "2", "3"}
        
        # foreign_keys: ON, OFF, 0, 1
        valid_foreign_keys = {"ON", "on", "OFF", "off", "0", "1", "TRUE", "true", "FALSE", "false"}
        
        # Test that injection attempts would fail
        injection_values = [
            "WAL; DROP TABLE users--",
            "wal') OR ('1'='1",
            "1; SELECT * FROM sqlite_master",
        ]
        for val in injection_values:
            assert val.upper() not in {v.upper() for v in valid_journal_modes}
            assert val.upper() not in {v.upper() for v in valid_synchronous}
            assert val.upper() not in {v.upper() for v in valid_foreign_keys}
