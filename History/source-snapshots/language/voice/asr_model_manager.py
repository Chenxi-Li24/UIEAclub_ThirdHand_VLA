#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any, Awaitable, Callable


DEFAULT_MODEL_ID = "whisper-small"


class ModelState(str, Enum):
    STOPPED = "STOPPED"
    LOADING = "LOADING"
    READY = "READY"
    SWITCHING = "SWITCHING"
    ERROR = "ERROR"


class ModelBusyError(RuntimeError):
    pass


class ModelSwitchError(RuntimeError):
    def __init__(
        self,
        requested_model_id: str,
        restored_model_id: str | None,
        cause: Exception,
    ) -> None:
        self.requested_model_id = requested_model_id
        self.restored_model_id = restored_model_id
        self.cause = cause
        recovery = (
            f"restored {restored_model_id}"
            if restored_model_id is not None
            else "no model could be restored"
        )
        super().__init__(
            f"Failed to load {requested_model_id}: {cause}; {recovery}."
        )


class ModelManager:
    def __init__(
        self,
        factories: dict[str, Callable[[], Any]],
        *,
        default_model_id: str = DEFAULT_MODEL_ID,
    ) -> None:
        if default_model_id not in factories:
            raise ValueError(f"Unknown default model: {default_model_id}")
        self._factories = dict(factories)
        self._default_model_id = default_model_id
        self._backend: Any = None
        self._active_model_id: str | None = None
        self._state = ModelState.STOPPED
        self._error: str | None = None
        self._last_latency_ms: float | None = None
        self._recording_sessions: set[str] = set()
        self._lock = asyncio.Lock()

    async def start_default(self) -> dict[str, Any]:
        return await self._load(self._default_model_id, ModelState.LOADING)

    async def switch(
        self,
        model_id: str,
        *,
        on_transition: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        if self._state in {ModelState.LOADING, ModelState.SWITCHING}:
            raise ModelBusyError("A model switch is already in progress.")
        if self._recording_sessions:
            raise ModelBusyError("A recording is active; model switching is blocked.")
        if model_id not in self._factories:
            raise ValueError(f"Unknown model: {model_id}")
        if self._state is ModelState.READY and model_id == self._active_model_id:
            return self.status()

        # Reserve the global switch before the first await. That makes model
        # selection atomic across independent WebSocket handlers and also
        # prevents a recording from starting during the status broadcast.
        self._state = ModelState.SWITCHING
        self._error = None
        self._last_latency_ms = None
        if on_transition is not None:
            await on_transition(self.status())
        async with self._lock:
            return await self._switch_locked(model_id)

    def begin_recording(self, session_id: str) -> None:
        if not session_id:
            raise ValueError("session_id is required")
        if self._state is not ModelState.READY or self._backend is None:
            raise RuntimeError("No ASR model is ready.")
        self._recording_sessions.add(session_id)
        start_stream = getattr(self._backend, "start_stream", None)
        if start_stream is not None:
            start_stream(session_id)

    def end_recording(self, session_id: str) -> None:
        self._recording_sessions.discard(session_id)

    def cancel_recording(self, session_id: str) -> None:
        cancel_stream = getattr(self._backend, "cancel_stream", None)
        if cancel_stream is not None:
            cancel_stream(session_id)
        self._recording_sessions.discard(session_id)

    async def push_audio(self, session_id: str, pcm: bytes) -> str | None:
        if session_id not in self._recording_sessions:
            raise RuntimeError("Recording session is not active.")
        push_audio = getattr(self._backend, "push_audio", None)
        if push_audio is None:
            return None
        return await push_audio(session_id, pcm)

    async def transcribe_final(
        self,
        audio: Any,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if self._state is not ModelState.READY or self._backend is None:
            raise RuntimeError("No ASR model is ready.")
        started_at = time.monotonic()
        finish_stream = getattr(self._backend, "finish_stream", None)
        if session_id is not None and finish_stream is not None:
            result = await finish_stream(session_id, audio)
        else:
            result = await self._backend.transcribe_final(audio)
        processing_time = result.get("processing_time") if isinstance(result, dict) else None
        self._last_latency_ms = round(
            float(processing_time) * 1000
            if isinstance(processing_time, (int, float))
            else (time.monotonic() - started_at) * 1000,
            1,
        )
        return result

    def status(self) -> dict[str, Any]:
        return {
            "state": self._state.value,
            "activeModelId": self._active_model_id,
            "device": getattr(self._backend, "device", None),
            "error": self._error,
            "recordingCount": len(self._recording_sessions),
            "lastLatencyMs": self._last_latency_ms,
        }

    async def _load(
        self,
        model_id: str,
        transition: ModelState,
    ) -> dict[str, Any]:
        async with self._lock:
            return await self._load_locked(model_id, transition)

    async def _load_locked(
        self,
        model_id: str,
        transition: ModelState,
    ) -> dict[str, Any]:
        self._state = transition
        self._error = None
        self._last_latency_ms = None

        await self._unload_active_locked()
        try:
            await self._activate_locked(model_id)
        except Exception as error:
            self._state = ModelState.ERROR
            self._error = str(error)
            raise

        self._state = ModelState.READY
        return self.status()

    async def _switch_locked(self, model_id: str) -> dict[str, Any]:
        previous_model_id = self._active_model_id
        await self._unload_active_locked()

        try:
            await self._activate_locked(model_id)
        except Exception as target_error:
            recovery_errors: list[str] = []
            candidates: list[str] = []
            for candidate in (previous_model_id, self._default_model_id):
                if (
                    candidate is not None
                    and candidate != model_id
                    and candidate not in candidates
                ):
                    candidates.append(candidate)

            for candidate in candidates:
                try:
                    await self._activate_locked(candidate)
                except Exception as recovery_error:
                    recovery_errors.append(f"{candidate}: {recovery_error}")
                    continue

                self._state = ModelState.READY
                self._error = None
                raise ModelSwitchError(
                    model_id,
                    candidate,
                    target_error,
                ) from target_error

            details = [f"{model_id}: {target_error}", *recovery_errors]
            self._state = ModelState.ERROR
            self._error = "; ".join(details)
            raise ModelSwitchError(
                model_id,
                None,
                target_error,
            ) from target_error

        self._state = ModelState.READY
        self._error = None
        return self.status()

    async def _activate_locked(self, model_id: str) -> None:
        backend = self._factories[model_id]()
        try:
            await backend.load()
        except Exception:
            try:
                await backend.unload()
            except Exception:
                pass
            raise

        self._backend = backend
        self._active_model_id = model_id

    async def _unload_active_locked(self) -> None:
        backend = self._backend
        self._backend = None
        self._active_model_id = None
        if backend is None:
            return
        try:
            await backend.unload()
        except Exception as error:
            self._state = ModelState.ERROR
            self._error = f"Failed to unload the active ASR model: {error}"
            raise
