"""Temporary, in-memory conversation memory for an agent.

This is intentionally NOT backed by a vector store (e.g. Chroma). It only
keeps a bounded, chronological list of messages for the lifetime of the
process/agent instance. Long-term memory belongs in
``Database.vector_store`` (already implemented) and is out of scope here.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from Providers import Message


@dataclass(frozen=True)
class MemoryEntry:
    """A single, timestamped entry stored in :class:`ConversationMemory`.

    Attributes:
        message: The stored :class:`Providers.Message`.
        stored_at: UTC timestamp of when the entry was stored (``Message``
            itself carries no timestamp, so it is recorded here instead).
    """

    message: Message
    stored_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationMemory:
    """Thread-safe, in-memory, chronological conversation history.

    Args:
        max_size: Optional maximum number of entries to retain. When
            exceeded, the oldest entries are dropped first (FIFO).
    """

    def __init__(self, max_size: Optional[int] = None) -> None:
        if max_size is not None and max_size <= 0:
            raise ValueError("max_size must be a positive integer when provided.")
        self._max_size = max_size
        self._entries: List[MemoryEntry] = []
        self._lock = threading.RLock()

    def add(self, message: Message) -> MemoryEntry:
        """Append ``message`` to the history and return the stored entry."""
        entry = MemoryEntry(message=message)
        with self._lock:
            self._entries.append(entry)
            if self._max_size is not None and len(self._entries) > self._max_size:
                self._entries = self._entries[-self._max_size:]
            return entry

    def history(self) -> List[MemoryEntry]:
        """Return a chronological copy of all stored entries."""
        with self._lock:
            return list(self._entries)

    def last(self) -> Optional[MemoryEntry]:
        """Return the most recently stored entry, or ``None`` if empty."""
        with self._lock:
            return self._entries[-1] if self._entries else None

    def clear(self) -> None:
        """Remove all stored entries."""
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
