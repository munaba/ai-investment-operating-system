from __future__ import annotations

import json
from typing import Any

from Core.event import Event
from Agents.tool_registry import ToolRegistry, ToolNotFoundError


class SandboxDecodeError(Exception):
    """Payload INTENT tidak bisa didecode sebagai tool-call envelope yang valid.

    Stage 8.2: tidak pernah lagi melintasi ``execute()`` sebagai exception.
    Class ini tetap ada sebagai sinyal internal murni antara ``_decode()``
    dan ``execute()`` (ditangkap di tempat, lalu diterjemahkan jadi payload
    error-as-data) -- dipertahankan sebagai type, bukan sebagai kontrak
    publik yang bisa di-``except`` pemanggil ``execute()``.
    """


class SandboxExecutionError(Exception):
    """Dipertahankan untuk kompatibilitas tipe/nama saja.

    Stage 8.2 (error-as-data, LOCKED): ``GenericSandbox.execute()`` tidak
    pernah lagi melempar ini. Kegagalan tool handler sekarang dikirim
    sebagai payload bytes ber-status "error" (lihat ``_encode_error``),
    supaya Runtime.step() selalu selesai sinkron sampai EFFECT_COMPLETED
    ter-append, tidak pernah crash di tengah jalan antara Decision dan
    Effect.
    """

    def __init__(self, tool_name: str, error: Exception) -> None:
        self.tool_name = tool_name
        self.original_error = error
        super().__init__(f"Tool '{tool_name}' raised during Sandbox.execute(): {error}")


class GenericSandbox:
    """Implementasi SandboxPort generik (Core/runtime.py Protocol, CLOSED).

    Tidak menyimpan state apa pun tentang tool yang dijalankan -- setiap
    ``execute()`` murni fungsi dari ``intent_event.payload`` ke bytes,
    memakai ``ToolRegistry`` yang di-inject saat construction.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._tool_registry = tool_registry

    def execute(self, intent_event: Event) -> bytes:
        """Jalankan tool-call yang dikodekan di ``intent_event.payload``.

        Stage 8.2 (error-as-data, LOCKED): method ini TIDAK PERNAH melempar
        exception untuk kegagalan tool normal (envelope tidak bisa didecode,
        tool_name tidak terdaftar, atau handler tool melempar exception).
        Setiap kegagalan itu dikodekan sebagai bytes ber-status "error" --
        simetris dengan happy path yang mengembalikan bytes ber-status "ok"
        -- supaya Runtime.step() selalu selesai sinkron sampai
        EFFECT_COMPLETED ter-append, tidak pernah crash di antara Decision
        dan Effect.

        Args:
            intent_event: Event bertipe INTENT yang sudah kanonik (id
                terisi) -- dikirim Runtime.step() persis seperti yang
                di-append, tidak pernah draft.

        Returns:
            bytes hasil eksekusi (sukses maupun gagal), siap dibungkus
            Runtime menjadi payload EFFECT_COMPLETED. Sandbox tidak pernah
            membuka bytes ini lagi setelah dikembalikan -- itu tanggung
            jawab Semantic Boundary di atas Runtime (di sini: Executor).
        """
        try:
            request = self._decode(intent_event.payload)
        except SandboxDecodeError as exc:
            return self._encode_error("decode_error", str(exc))

        tool_name = request["tool_name"]
        args = request.get("args", [])
        kwargs = request.get("kwargs", {})

        try:
            tool = self._tool_registry.get(tool_name)
        except ToolNotFoundError as exc:
            return self._encode_error("tool_not_found", str(exc), tool_name=tool_name)

        try:
            result = tool.handler(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - normalize any tool failure
            return self._encode_error(
                "execution_error", str(exc), tool_name=tool_name, error_class=type(exc).__name__
            )

        return self._encode(result)

    @staticmethod
    def _decode(payload: bytes) -> dict[str, Any]:
        try:
            data = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SandboxDecodeError(
                f"INTENT payload bukan UTF-8 JSON yang valid: {exc}"
            ) from exc

        if not isinstance(data, dict) or not data.get("tool_name"):
            raise SandboxDecodeError(
                f"INTENT payload envelope tidak berisi 'tool_name': {data!r}"
            )
        if "args" in data and not isinstance(data["args"], list):
            raise SandboxDecodeError("'args' harus berupa list kalau ada")
        if "kwargs" in data and not isinstance(data["kwargs"], dict):
            raise SandboxDecodeError("'kwargs' harus berupa dict kalau ada")
        return data

    @staticmethod
    def _encode(result: Any) -> bytes:
        try:
            body = json.dumps({"status": "ok", "result": result})
        except TypeError:
            # Result tidak JSON-serializable langsung -- fallback ke str(),
            # tetap opaque bagi Runtime, hanya perlu bisa round-trip
            # sebagai bytes untuk EFFECT_COMPLETED.payload.
            body = json.dumps({"status": "ok", "result": str(result)})
        return body.encode("utf-8")

    @staticmethod
    def _encode_error(
        error_type: str,
        message: str,
        *,
        tool_name: str | None = None,
        error_class: str | None = None,
    ) -> bytes:
        """Kodekan kegagalan sebagai bytes ber-status "error" (error-as-data).

        Schema: {"status": "error", "error_type": ..., "message": ...,
        "tool_name"?: ..., "error_class"?: ...}. Semantic Boundary di atas
        Runtime (Executor) yang membuka dan menafsirkan schema ini --
        Sandbox sendiri tidak pernah membaca bytes yang sudah ia hasilkan.
        """
        payload: dict[str, Any] = {"status": "error", "error_type": error_type, "message": message}
        if tool_name is not None:
            payload["tool_name"] = tool_name
        if error_class is not None:
            payload["error_class"] = error_class
        return json.dumps(payload).encode("utf-8")