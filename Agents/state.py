"""Agent lifecycle state definition."""

from __future__ import annotations

from enum import Enum, auto


class AgentState(Enum):
    """Finite set of states an agent can be in during a single turn."""

    IDLE = auto()
    THINKING = auto()
    CALLING_TOOL = auto()
    WAITING_PROVIDER = auto()
    RESPONDING = auto()
    ERROR = auto()
