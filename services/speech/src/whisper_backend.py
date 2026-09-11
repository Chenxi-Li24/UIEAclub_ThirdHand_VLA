#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import gc
import time
from typing import Any, Awaitable, Callable


Loader = Callable[..., Any]
ReleaseCuda = Callable[[], Awaitable[None]]


def _default_loader(**kwargs: Any) -> Any:
    from faster_whisper import WhisperModel

    return WhisperModel(**kwargs)


async def _default_release_cuda() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        return


class WhisperSmallBackend:
    model_id = "whisper-small"
    device = "cuda"

    def __init__(
        self,
        model_path: str,
        *,
        loader: Loader | None = None,
        clock: Callable[[], float] = time.perf_counter,
        release_cuda: ReleaseCuda | None = None,
    ) -> None:
        self.model_path = model_path
        self._loader = loader or _default_loader
        self._clock = clock
        self._release_cuda = release_cuda or _default_release_cuda
        self._model: Any = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    async def load(self) -> None:
        if self._model is not None:
            return
        model = await asyncio.to_thread(
            self._loader,
            model_size_or_path=self.model_path,
            device=self.device,
            compute_type="float16",
            local_files_only=True,
        )
        self._model = model

    async def unload(self) -> None:
        if self._model is None:
            return
        self._model = None
        await self._release_cuda()

    async def transcribe_final(self, audio: Any) -> dict[str, Any]:
        if self._model is None:
            raise RuntimeError("Whisper Small is not loaded")
        started = self._clock()
        normalized = await asyncio.to_thread(self._transcribe_sync, audio)
        elapsed = max(0.0, self._clock() - started)
        return {
            **normalized,
            "processing_time": elapsed,
            "device": self.device,
            "model_id": self.model_id,
            "is_final": True,
        }

    def _transcribe_sync(self, audio: Any) -> dict[str, Any]:
        segments_iter, info = self._model.transcribe(
            audio,
            language=None,
            beam_size=5,
            vad_filter=False,
        )
        segments = [
            {
                "start": segment.start,
                "end": segment.end,
                "text": str(segment.text or "").strip(),
            }
            for segment in segments_iter
        ]
        return {
            "text": " ".join(
                segment["text"] for segment in segments if segment["text"]
            ).strip(),
            "language": getattr(info, "language", None),
            "language_probability": getattr(info, "language_probability", None),
            "segments": segments,
            "duration": getattr(info, "duration", None),
        }
