from __future__ import annotations

import json
from typing import Callable, FrozenSet, Iterable

from Core.event import Event
from Core.runtime import ApprovalOutcome


class AlwaysApproveApprovalPort:
    """ApprovalPort yang selalu menyetujui setiap INTENT.

    ``version`` wajib (kontrak ApprovalPort.version di runtime.py) --
    opaque, ikut tercatat di payload Decision lewat
    ``Runtime._encode_decision_payload`` untuk keperluan audit/provenance,
    tidak pernah dibaca ulang oleh Runtime untuk keputusan.
    """

    version: str = "always-approve-v1"

    def check(self, event: Event) -> ApprovalOutcome:  # noqa: ARG002 - Event sengaja tidak dibuka
        return ApprovalOutcome.APPROVED


class DenyAllApprovalPort:
    """ApprovalPort yang selalu menolak setiap INTENT.

    Stage 9.2: bukti bahwa DI Stage 9.1 benar-benar dikonsumsi Runtime --
    setiap tool-call lewat port ini berakhir sebagai
    ``ApprovalOutcome.DENIED``, tanpa pernah memanggil ``Sandbox.execute()``
    (ditegakkan Runtime, bukan di sini -- lihat Core/runtime.py, LOCKED).
    """

    version: str = "deny-all-v1"

    def check(self, event: Event) -> ApprovalOutcome:  # noqa: ARG002 - Event sengaja tidak dibuka
        return ApprovalOutcome.DENIED


def _decode_tool_name(event: Event) -> str:
    """Buka payload INTENT untuk membaca ``tool_name``.

    Sah dilakukan di sini (bukan pelanggaran Law III): ApprovalPort
    berada di sisi Implementation/Semantic Boundary, bukan di sisi
    Runtime -- payload hanya wajib opaque bagi Runtime (Core/runtime.py),
    bukan bagi Port yang memutuskan berdasarkan isinya. Bentuk payload
    ini sendiri (JSON ``{"tool_name": ..., "args": [...], "kwargs": {...}}``)
    adalah kontrak yang sudah dipakai ``Agents/executor.py::execute()``
    sejak Stage 8.2, tidak diubah di sini.
    """
    envelope = json.loads(event.payload.decode("utf-8"))
    return envelope["tool_name"]


class ToolWhitelistApprovalPort:
    """ApprovalPort berbasis daftar tool yang diizinkan.

    Tool yang namanya ada di ``allowed_tools`` -> APPROVED.
    Tool lainnya -> DENIED.
    """

    version: str = "tool-whitelist-v1"

    def __init__(self, allowed_tools: Iterable[str]) -> None:
        self._allowed_tools: FrozenSet[str] = frozenset(allowed_tools)

    def check(self, event: Event) -> ApprovalOutcome:
        tool_name = _decode_tool_name(event)
        if tool_name in self._allowed_tools:
            return ApprovalOutcome.APPROVED
        return ApprovalOutcome.DENIED


class ToolBlacklistApprovalPort:
    """ApprovalPort berbasis daftar tool yang dilarang.

    Kebalikan dari ``ToolWhitelistApprovalPort``: tool yang namanya ada
    di ``blocked_tools`` -> DENIED. Tool lainnya -> APPROVED.
    """

    version: str = "tool-blacklist-v1"

    def __init__(self, blocked_tools: Iterable[str]) -> None:
        self._blocked_tools: FrozenSet[str] = frozenset(blocked_tools)

    def check(self, event: Event) -> ApprovalOutcome:
        tool_name = _decode_tool_name(event)
        if tool_name in self._blocked_tools:
            return ApprovalOutcome.DENIED
        return ApprovalOutcome.APPROVED


class PredicateApprovalPort:
    """ApprovalPort berbasis predicate/callback sederhana.

    ``predicate(event)`` dipanggil sinkron, tanpa I/O -- kontrak yang
    sama seperti ``ApprovalPort.check()`` sendiri (Core/runtime.py,
    LOCKED). Predicate menerima Event INTENT mentah (bukan hanya
    tool_name) supaya caller bebas memutuskan berdasarkan payload apa
    pun yang relevan baginya, tanpa ApprovalPort ini memaksakan bentuk
    keputusan tertentu.

    True  -> APPROVED
    False -> DENIED
    """

    version: str = "predicate-v1"

    def __init__(self, predicate: Callable[[Event], bool]) -> None:
        self._predicate = predicate

    def check(self, event: Event) -> ApprovalOutcome:
        if self._predicate(event):
            return ApprovalOutcome.APPROVED
        return ApprovalOutcome.DENIED