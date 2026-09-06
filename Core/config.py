from __future__ import annotations
 
import os
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional
 
from dotenv import load_dotenv
 
from .exceptions import ConfigurationError
 
_TRUTHY_VALUES: frozenset[str] = frozenset({"1", "true", "yes", "on", "y"})
_FALSY_VALUES: frozenset[str] = frozenset({"0", "false", "no", "off", "n"})
 
 
class Config:
    """Thread-safe singleton for reading application configuration.
 
    The class loads variables from a ``.env`` file the first time it is
    instantiated (subsequent instantiations return the same instance and do
    not reload the file unless :meth:`reload` is called explicitly).
 
    Attributes:
        env_file: Path to the ``.env`` file that was loaded.
    """
 
    _instance: Optional["Config"] = None
    _lock: Lock = Lock()
    _initialized: bool = False
 
    def __new__(cls, env_file: str = ".env") -> "Config":
        """Create or return the existing singleton instance.
 
        Args:
            env_file: Path to the ``.env`` file to load. Only used the first
                time the singleton is created.
 
        Returns:
            The single shared ``Config`` instance.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
 
    def __init__(self, env_file: str = ".env") -> None:
        """Initialize the singleton exactly once.
 
        Args:
            env_file: Path to the ``.env`` file to load.
        """
        if self._initialized:
            return
        self.env_file: Path = Path(env_file)
        self._load_environment()
        self._initialized = True
 
    def _load_environment(self) -> None:
        """Load environment variables from the configured ``.env`` file.
 
        If the file does not exist at ``self.env_file``, ``python-dotenv``
        still attempts its default search (current directory and parents),
        so the application can run using variables already present in the
        OS environment (e.g. in production/containers).
        """
        if self.env_file.exists():
            load_dotenv(dotenv_path=self.env_file, override=False)
        else:
            load_dotenv(override=False)
 
    def reload(self) -> None:
        """Force a reload of the ``.env`` file, overriding existing values."""
        if self.env_file.exists():
            load_dotenv(dotenv_path=self.env_file, override=True)
        else:
            load_dotenv(override=True)
 
    def get(self, key: str, default: Any = None) -> Any:
        """Get a raw (string) configuration value.
 
        Args:
            key: Name of the environment variable.
            default: Value returned if the key is not set.
 
        Returns:
            The raw string value from the environment, or ``default``.
        """
        return os.getenv(key, default)
 
    def get_str(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a configuration value as a string.
 
        Args:
            key: Name of the environment variable.
            default: Value returned if the key is not set.
 
        Returns:
            The value as a string, or ``default`` if not set.
        """
        value = os.getenv(key)
        return value if value is not None else default
 
    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get a configuration value as a boolean.
 
        Accepts (case-insensitive): ``1/0``, ``true/false``, ``yes/no``,
        ``on/off``, ``y/n``.
 
        Args:
            key: Name of the environment variable.
            default: Value returned if the key is not set.
 
        Returns:
            The parsed boolean value, or ``default`` if not set.
 
        Raises:
            ConfigurationError: If the value is set but is not a recognized
                boolean string.
        """
        value = os.getenv(key)
        if value is None:
            return default
 
        normalized = value.strip().lower()
        if normalized in _TRUTHY_VALUES:
            return True
        if normalized in _FALSY_VALUES:
            return False
        raise ConfigurationError(
            f"Environment variable '{key}' is not a valid boolean: {value!r}"
        )
 
    def get_int(self, key: str, default: int = 0) -> int:
        """Get a configuration value as an integer.
 
        Args:
            key: Name of the environment variable.
            default: Value returned if the key is not set.
 
        Returns:
            The parsed integer value, or ``default`` if not set.
 
        Raises:
            ConfigurationError: If the value is set but is not a valid integer.
        """
        value = os.getenv(key)
        if value is None:
            return default
        try:
            return int(value.strip())
        except ValueError as exc:
            raise ConfigurationError(
                f"Environment variable '{key}' is not a valid integer: {value!r}"
            ) from exc
 
    def get_float(self, key: str, default: float = 0.0) -> float:
        """Get a configuration value as a float.
 
        Args:
            key: Name of the environment variable.
            default: Value returned if the key is not set.
 
        Returns:
            The parsed float value, or ``default`` if not set.
 
        Raises:
            ConfigurationError: If the value is set but is not a valid float.
        """
        value = os.getenv(key)
        if value is None:
            return default
        try:
            return float(value.strip())
        except ValueError as exc:
            raise ConfigurationError(
                f"Environment variable '{key}' is not a valid float: {value!r}"
            ) from exc
 
    def validate(self, required_keys: List[str]) -> None:
        """Validate that all required environment variables are present.
 
        Args:
            required_keys: List of environment variable names that must be
                set (non-``None``) for the application to run correctly.
 
        Raises:
            ConfigurationError: If one or more required keys are missing.
                The exception's ``details`` contain the list of missing keys.
        """
        missing = [key for key in required_keys if os.getenv(key) is None]
        if missing:
            raise ConfigurationError(
                f"Missing required environment variable(s): {', '.join(missing)}",
                details={"missing_keys": missing},
            )
 
    def as_dict(self, keys: List[str]) -> Dict[str, Optional[str]]:
        """Return a snapshot of selected configuration values as a dict.
 
        Useful for debugging/logging (be careful not to log secrets).
 
        Args:
            keys: List of environment variable names to include.
 
        Returns:
            A dictionary mapping each key to its current raw string value
            (or ``None`` if not set).
        """
        return {key: os.getenv(key) for key in keys}
 
config: Config = Config()