#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import gc
import time
from dataclasses import dataclass, field
from typing import Any, Callable


Loader = Callable[..., Any]


def _default_loader(**kwargs: Any) -> Any:
    from funasr import AutoModel

    return AutoModel(**kwargs)


def _default_nano_loader(**kwargs: Any) -> Any:
    from funasr.auto.auto_model_vllm import AutoModelVLLM

    return AutoModelVLLM(**kwargs)


def _first_result(result: Any) -> dict[str, Any]:
    if isinstance(result, list) and result and isinstance(result[0], dict):
        return result[0]
    if isinstance(result, dict):
        return result
    raise RuntimeError("FunASR returned an invalid result")


async def _release_cuda() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        return


class FunASRNanoBackend:
    model_id = "fun-asr-nano"
    device = "cuda"

    def __init__(
        self,
        model_path: str,
        *,
        loader: Loader | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.model_path = model_path
        self._loader = loader or _default_nano_loader
        self._clock = clock
        self._model: Any = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    async def load(self) -> None:
        if self._model is not None:
            return
        self._model = await asyncio.to_thread(
            self._loader,
            model=self.model_path,
            tensor_parallel_size=1,
            # This 8 GiB workstation GPU shares memory with the active vision
            # process. Reserve 35% for vLLM so Nano can coexist; this is a
            # fixed deployment setting, not an automatic retry or fallback.
            gpu_memory_utilization=0.35,
            # The prebuilt FlashAttention PTX in vLLM 0.19.1 is newer than
            # this host's 570 driver accepts on RTX 5060. vLLM officially
            # supports its Triton backend for these dtypes, which compiles for
            # the local CUDA 12.8 toolchain instead of using that PTX blob.
            vllm_kwargs={
                "attention_config": {"backend": "TRITON_ATTN"},
                # The Voice Bridge serializes final ASR inference. Avoid
                # vLLM's 256-request sampler warm-up, which is wasteful and
                # exceeds VRAM while vision is active.
                "max_num_seqs": 4,
            },
        )

    async def unload(self) -> None:
        self._model = None
        await _release_cuda()

    async def transcribe_final(self, audio: Any) -> dict[str, Any]:
        if self._model is None:
            raise RuntimeError("Fun-ASR-Nano is not loaded")
        started = self._clock()
        raw = await asyncio.to_thread(
            self._model.generate,
            [audio],
            language="auto",
            temperature=0.0,
            repetition_penalty=1.0,
            max_new_tokens=200,
        )
        elapsed = max(0.0, self._clock() - started)
        item = _first_result(raw)
        return {
            "text": str(item.get("text") or "").strip(),
            "language": item.get("language"),
            "segments": item.get("timestamp") or item.get("segments") or [],
            "duration": item.get("duration"),
            "processing_time": elapsed,
            "device": self.device,
            "model_id": self.model_id,
            "is_final": True,
        }


@dataclass
class _StreamState:
    cache: dict[str, Any] = field(default_factory=dict)
    pcm: bytearray = field(default_factory=bytearray)
    pieces: list[str] = field(default_factory=list)
    total_samples: int = 0
    processing_time: float = 0.0


class ParaformerStreamingBackend:
    model_id = "paraformer-streaming"
    sample_rate = 16_000
    chunk_samples = 9_600
    chunk_bytes = chunk_samples * 2
    chunk_size = [0, 10, 5]

    def __init__(
        self,
        model_path: str,
        *,
        device: str = "cpu",
        loader: Loader | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if device not in {"cpu", "cuda"}:
            raise ValueError("Paraformer device must be cpu or cuda")
        self.model_path = model_path
        self.device = device
        self._loader = loader or _default_loader
        self._clock = clock
        self._model: Any = None
        self._streams: dict[str, _StreamState] = {}

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def active_stream_ids(self) -> set[str]:
        return set(self._streams)

    async def load(self) -> None:
        if self._model is not None:
            return
        self._model = await asyncio.to_thread(
            self._loader,
            model=self.model_path,
            device=self.device,
            disable_update=True,
        )

    async def unload(self) -> None:
        self._streams.clear()
        self._model = None
        await _release_cuda()

    def start_stream(self, session_id: str) -> None:
        if self._model is None:
            raise RuntimeError("Paraformer Streaming is not loaded")
        self._streams[session_id] = _StreamState()

    async def push_audio(self, session_id: str, pcm: bytes) -> str | None:
        stream = self._streams.get(session_id)
        if stream is None:
            raise RuntimeError("Paraformer stream is not active")
        if len(pcm) % 2:
            raise ValueError("PCM S16LE payload must contain complete samples")
        stream.pcm.extend(pcm)
        stream.total_samples += len(pcm) // 2

        emitted = False
        while len(stream.pcm) >= self.chunk_bytes:
            chunk = bytes(stream.pcm[: self.chunk_bytes])
            del stream.pcm[: self.chunk_bytes]
            text = await self._generate(stream, chunk, is_final=False)
            if text:
                stream.pieces.append(text)
                emitted = True
        return "".join(stream.pieces) if emitted else None

    async def finish_stream(self, session_id: str, _audio: Any) -> dict[str, Any]:
        stream = self._streams.pop(session_id, None)
        if stream is None:
            raise RuntimeError("Paraformer stream is not active")
        final_piece = await self._generate(stream, bytes(stream.pcm), is_final=True)
        if final_piece:
            stream.pieces.append(final_piece)
        return {
            "text": "".join(stream.pieces).strip(),
            "language": None,
            "segments": [],
            "duration": stream.total_samples / self.sample_rate,
            "processing_time": stream.processing_time,
            "device": self.device,
            "model_id": self.model_id,
            "is_final": True,
        }

    def cancel_stream(self, session_id: str) -> None:
        self._streams.pop(session_id, None)

    async def _generate(
        self,
        stream: _StreamState,
        pcm: bytes,
        *,
        is_final: bool,
    ) -> str:
        if self._model is None:
            raise RuntimeError("Paraformer Streaming is not loaded")
        import numpy as np

        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        started = self._clock()
        raw = await asyncio.to_thread(
            self._model.generate,
            input=audio,
            cache=stream.cache,
            is_final=is_final,
            chunk_size=self.chunk_size,
            encoder_chunk_look_back=4,
            decoder_chunk_look_back=1,
        )
        stream.processing_time += max(0.0, self._clock() - started)
        return str(_first_result(raw).get("text") or "").strip()
