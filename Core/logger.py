from __future__ import annotations
 
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Dict, Optional
 
_LOG_DIR: Path = Path("logs")
_LOG_FILE: Path = _LOG_DIR / "app.log"
_LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(module)s:%(lineno)d | %(message)s"
_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
 
_MAX_BYTES: int = 5 * 1024 * 1024
_BACKUP_COUNT: int = 5
 
 
class LoggerFactory:
    """Thread-safe singleton factory that creates and caches configured loggers.
 
    Ensures the ``logs`` directory exists, and that each named logger is
    configured with a console handler and a rotating file handler exactly
    once, avoiding duplicate log lines on repeated ``get_logger`` calls.
    """
 
    _instance: Optional["LoggerFactory"] = None
    _lock: Lock = Lock()
    _loggers: Dict[str, logging.Logger] = {}
 
    def __new__(cls) -> "LoggerFactory":
        """Create or return the existing singleton instance.
 
        Returns:
            The single shared ``LoggerFactory`` instance.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._ensure_log_dir()
        return cls._instance
 
    @staticmethod
    def _ensure_log_dir() -> None:
        """Create the ``logs`` directory automatically if it does not exist."""
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
 
    def get_logger(self, name: str = "agent_framework", level: int = logging.DEBUG) -> logging.Logger:
        """Get a configured logger, creating and caching it on first use.
 
        Args:
            name: Logger name, typically ``__name__`` of the calling module.
            level: Minimum severity level handled by this logger
                (``logging.DEBUG``, ``INFO``, ``WARNING``, ``ERROR`` or
                ``CRITICAL``).
 
        Returns:
            A ``logging.Logger`` instance writing to both console and file.
        """
        if name in self._loggers:
            return self._loggers[name]
 
        with self._lock:
            if name in self._loggers:
                return self._loggers[name]
 
            logger = logging.getLogger(name)
            logger.setLevel(level)
        
            logger.propagate = False
 
            if not logger.handlers:
                formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)
 
                console_handler = logging.StreamHandler(stream=sys.stdout)
                console_handler.setLevel(level)
                console_handler.setFormatter(formatter)
                logger.addHandler(console_handler)
 
                file_handler = RotatingFileHandler(
                    filename=_LOG_FILE,
                    maxBytes=_MAX_BYTES,
                    backupCount=_BACKUP_COUNT,
                    encoding="utf-8",
                )
                file_handler.setLevel(level)
                file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)
 
            self._loggers[name] = logger
            return logger
 
 
def get_logger(name: str = "agent_framework", level: int = logging.DEBUG) -> logging.Logger:
    """Convenience function to obtain the shared, configured singleton logger.
 
    Args:
        name: Logger name, typically ``__name__`` of the calling module.
        level: Minimum severity level handled by this logger.
 
    Returns:
        A ``logging.Logger`` instance configured to log to console and file.
    """
    return LoggerFactory().get_logger(name=name, level=level)