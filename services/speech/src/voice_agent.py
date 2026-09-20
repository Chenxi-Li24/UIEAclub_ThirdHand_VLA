#!/usr/bin/env python3
"""
Ubuntu PC Voice Agent (VAD + faster-whisper + Claude + Robot + TTS)

  Mic (USB/BT) -> Silero VAD -> faster-whisper -> Claude API -> TTS -> Speaker (USB/BT)

Audio I/O auto-routing: same device for input and output, priority USB > BT > built-in.

Usage:
  python3 voice_agent.py
  python3 voice_agent.py --list-devices
  python3 voice_agent.py --test          # 5s record + transcribe + playback
"""

import os
import sys
import time
import json
import queue
import threading
import argparse
import warnings
import importlib.util
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, List, Dict, Callable

import numpy as np

warnings.filterwarnings("ignore")


# ═══════════════════════════════════════════════════════════════════
# Audio device manager
# ═══════════════════════════════════════════════════════════════════

def list_input_devices():
    """List all available audio input devices."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        print("\nAvailable input devices:")
        print("-" * 60)
        for i, d in enumerate(devices):
            if d['max_input_channels'] > 0:
                print(f"  [{i}] {d['name']}")
                print(f"       channels={d['max_input_channels']}, "
                      f"samplerate={d['default_samplerate']:.0f}Hz")
        print("-" * 60)
        return devices
    except Exception as e:
        print(f"Error listing devices: {e}")
        return []


def select_mic(prefer: str = "auto") -> tuple:
    """
    Select best microphone.
    Priority: 2.4GHz USB > Bluetooth > built-in

    Returns (device_name, device_type, sample_rate)
    """
    import sounddevice as sd
    return _select_audio_device(sd.query_devices(), 'input', prefer)


def select_speaker(prefer: str = "auto") -> tuple:
    """
    Select best speaker.
    Priority: 2.4GHz USB > Bluetooth > built-in

    Returns (device_name, device_type, sample_rate)
    """
    import sounddevice as sd
    return _select_audio_device(sd.query_devices(), 'output', prefer)


def _select_audio_device(devices, direction, prefer):
    """Shared device selection logic for input and output."""
    candidates = []
    key = 'max_input_channels' if direction == 'input' else 'max_output_channels'
    dtype = 'input' if direction == 'input' else 'output'

    for d in devices:
        if d.get(key, 0) > 0:
            name = d['name'].lower()
            rate = int(d['default_samplerate'])

            if prefer != "auto" and prefer.lower() in name:
                print(f"[audio] Using preferred {dtype}: {d['name']}")
                return d['name'], 'preferred', rate

            if 'usb' in name and direction == 'input':
                candidates.append((0, d['name'], '2.4GHz USB', rate))
            elif 'usb' in name:
                # USB output: prefer ALSA direct over PipeWire (avoids PipeWire lock bug)
                candidates.append((0, d['name'], '2.4GHz USB', rate))
            elif 'bluez' in name or 'bluetooth' in name:
                candidates.append((1, d['name'], 'Bluetooth', rate))
            elif 'default' == name.strip() or 'demixer' == name.strip():
                candidates.append((2, d['name'], 'PipeWire', rate))
            elif 'pipewire' == name.strip() or 'hdmi' == name.strip():
                continue
            else:
                candidates.append((4, d['name'], 'built-in', rate))

    if not candidates:
        raise RuntimeError(f"No {dtype} device found")

    candidates.sort()
    name = candidates[0][1]
    devtype = candidates[0][2]
    rate = candidates[0][3]
    print(f"[audio] Selected {dtype}: {name} ({devtype}, {rate}Hz)")
    return name, devtype, rate


# ═══════════════════════════════════════════════════════════════════
# Voice Activity Detection (Silero VAD)
# ═══════════════════════════════════════════════════════════════════

class SileroVAD:
    """
    Lightweight VAD using Silero model.
    Ranges: less than 1ms per frame, very accurate.

    Usage:
        vad = SileroVAD()
        for audio_chunk in stream:
            if vad.is_speech(audio_chunk):
                # accumulate for ASR
    """

    SAMPLE_RATE = 16000
    WINDOW_SAMPLES = 512  # 32ms at 16kHz — good balance

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        self._model = None
        self._init_model()

    def _init_model(self):
        import torch
        # Silero VAD model — load once, cached after first download
        model, utils = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False,
        )
        self._model = model
        (self._get_speech_ts, _, _, _, _) = utils

    def is_speech(self, audio: np.ndarray) -> float:
        """Returns probability 0-1 that this chunk contains speech."""
        import torch
        with torch.no_grad():
            tensor = torch.from_numpy(audio).float()
            prob = self._model(tensor, self.SAMPLE_RATE).item()
            return prob

    def reset(self):
        """Reset VAD state (call after each utterance)."""
        if self._model:
            self._model.reset_states()


# ═══════════════════════════════════════════════════════════════════
# Audio capture + VAD loop
# ═══════════════════════════════════════════════════════════════════

@dataclass
class SpeechSegment:
    """A detected speech utterance."""
    audio: np.ndarray          # (N,) float32, 16kHz mono
    timestamp: float           # when captured
    duration: float            # seconds

class AudioCapture:
    """
    Continuous audio capture with VAD-based speech detection.

    Streams audio from mic, runs VAD, accumulates speech segments.
    Pushes complete utterances to a thread-safe queue.
    """

    SAMPLE_RATE = 16000        # target rate for ASR
    SILENCE_TIMEOUT = 1.0      # seconds of silence to end utterance
    MAX_UTTERANCE = 15.0       # max seconds before forced cut
    PRE_SPEECH_BUFFER = 0.3    # seconds to keep before first speech detection

    def __init__(self, device_name: str, device_sample_rate: int = 48000,
                 vad_threshold: float = 0.5):
        self.device_name = device_name
        self.device_rate = device_sample_rate
        self.vad = SileroVAD(threshold=vad_threshold)
        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._thread = None

        # Resample ratio: device → 16k
        from scipy import signal as sp_sig
        self._resample_ratio = self.SAMPLE_RATE / self.device_rate

        # Pre-allocated ring buffer for pre-speech audio (at 16kHz)
        self._buffer_samples = int(self.PRE_SPEECH_BUFFER * self.SAMPLE_RATE)
        self._ring = None

    def start(self):
        """Start background capture thread."""
        if self._running:
            return
        self._running = True
        self._ring = deque(maxlen=self._buffer_samples)
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        print(f"[audio] Capture started: {self.device_name}")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def get_utterance(self, timeout: float = None) -> Optional[SpeechSegment]:
        """Block until next utterance, or return None on timeout."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _capture_loop(self):
        import sounddevice as sd
        from scipy import signal as sp_sig

        # Use device's native rate, resample in callback
        chunk_size = int(SileroVAD.WINDOW_SAMPLES * self.device_rate / self.SAMPLE_RATE)

        def callback(indata, frames, time_info, status):
            if status:
                print(f"[audio] stream error: {status}", file=sys.stderr)
            # Resample device rate → 16kHz
            audio = indata[:, 0].copy()
            audio_16k = sp_sig.resample(audio, SileroVAD.WINDOW_SAMPLES)
            self._process_chunk(audio_16k.astype(np.float32))

        try:
            with sd.InputStream(
                device=self.device_name,
                samplerate=self.device_rate,
                channels=1,
                blocksize=chunk_size,
                callback=callback,
                dtype='float32',
            ):
                while self._running:
                    time.sleep(0.05)
        except Exception as e:
            print(f"[audio] capture error: {e}", file=sys.stderr)

    def _process_chunk(self, chunk: np.ndarray):
        """Process one audio chunk: VAD → accumulate → emit utterance."""
        self._ring.append(chunk.copy())

        prob = self.vad.is_speech(chunk)

        # State machine
        if not hasattr(self, '_speaking'):
            self._speaking = False
            self._frames = []
            self._silence_frames = 0
            self._last_speech_time = time.time()

        now = time.time()

        if prob > self.vad.threshold:
            if not self._speaking:
                # Speech started — flush pre-speech buffer
                self._speaking = True
                self._frames = list(self._ring)
                print(f"  🎤 [VAD] speech started")
            self._frames.append(chunk)
            self._silence_frames = 0
            self._last_speech_time = now
        elif self._speaking:
            self._frames.append(chunk)
            self._silence_frames += 1

            silence_sec = self._silence_frames * (SileroVAD.WINDOW_SAMPLES / self.SAMPLE_RATE)
            utterance_sec = len(self._frames) * (SileroVAD.WINDOW_SAMPLES / self.SAMPLE_RATE)

            # End condition: silence timeout OR max utterance length
            if silence_sec >= self.SILENCE_TIMEOUT or utterance_sec >= self.MAX_UTTERANCE:
                self._speaking = False
                audio = np.concatenate(self._frames)
                duration = len(audio) / self.SAMPLE_RATE

                # Skip if too short
                if duration >= 0.5:
                    seg = SpeechSegment(
                        audio=audio,
                        timestamp=now,
                        duration=duration,
                    )
                    self._queue.put(seg)
                    print(f"  🔇 [VAD] speech ended: {duration:.1f}s, "
                          f"queue size={self._queue.qsize()}")
                else:
                    print(f"  🔇 [VAD] speech too short ({duration:.1f}s), discarded")

                self.vad.reset()
                self._frames = []
                self._silence_frames = 0


# ═══════════════════════════════════════════════════════════════════
# ASR: faster-whisper
# ═══════════════════════════════════════════════════════════════════

class WhisperASR:
    """
    Speech-to-text using faster-whisper, bilingual EN/ZH.
    Uses CTranslate2 backend → GPU auto-detect (CUDA if available, else CPU).

    Models: tiny, base, small, medium, large-v3
    """

    def __init__(self, model_size: str = "small", language: str = None,
                 device: str = "auto", compute_type: str = "auto"):
        self.model_size = model_size
        self.language = language  # None = auto-detect (best for bilingual)
        self._model = None

        # Detect best compute type
        if compute_type == "auto":
            try:
                import ctranslate2
                if ctranslate2.get_cuda_device_count() > 0:
                    compute_type = "float16"
                    device = "cuda"
                else:
                    compute_type = "int8"
                    device = "cpu"
            except Exception:
                compute_type = "int8"
                device = "cpu"

        self.device = device
        self.compute_type = compute_type
        lang_display = language or "auto (EN/ZH bilingual)"
        print(f"[asr] faster-whisper: model={model_size}, device={device}, "
              f"compute={compute_type}, language={lang_display}")

    def load(self):
        """Lazy-load the model (called on first use)."""
        if self._model is not None:
            return
        from faster_whisper import WhisperModel
        print(f"[asr] Loading model '{self.model_size}' ...")
        self._model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
        )
        print(f"[asr] Model loaded.")

    def transcribe(self, audio: np.ndarray) -> Dict:
        """
        Transcribe audio → text (auto-detect EN/ZH).

        Args:
            audio: (N,) float32 array, 16kHz mono

        Returns:
            dict with 'text', 'segments', 'language', 'duration'
        """
        self.load()
        segments, info = self._model.transcribe(
            audio,
            language=self.language,   # None → auto-detect
            beam_size=5,
            vad_filter=False,         # we already do VAD
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        text = " ".join(seg.text.strip() for seg in segments)
        result = {
            'text': text,
            'language': info.language,
            'duration': info.duration,
            'language_prob': info.language_probability,
        }
        lang_label = 'EN' if info.language == 'en' else (info.language.upper())
        print(f"  📝 [ASR] [{lang_label}] \"{text}\" "
              f"({(audio.shape[0]/16000):.1f}s audio)")
        return result


# ═══════════════════════════════════════════════════════════════════
# TTS: Text-to-Speech output
# ═══════════════════════════════════════════════════════════════════

class TTSEngine:
    """
    Bilingual text-to-speech using Microsoft Edge TTS (free).
    Auto-selects EN or ZH voice based on text content.
    """

    VOICES = {"en": "en-US-JennyNeural", "zh": "zh-CN-XiaoxiaoNeural"}

    def __init__(self, output_device: str = None, voice: str = None,
                 device_rate: int = 48000):
        self.output_device = output_device
        self._voice_override = voice  # if set, always use this voice
        self._tts_rate = 24000    # edge-tts output rate
        self._device_rate = device_rate  # headset rate

    def _pick_voice(self, text: str) -> str:
        """Pick EN or ZH voice based on text content."""
        if self._voice_override:
            return self._voice_override
        # Simple heuristic: if >50% CJK chars, use Chinese voice
        cjk = sum(1 for c in text if '一' <= c <= '鿿')
        return self.VOICES["zh"] if cjk > len(text) * 0.3 else self.VOICES["en"]

    def say(self, text: str):
        """Speak text through the output device (async, non-blocking)."""
        if not text.strip():
            return

        print(f"  🔊 [TTS] \"{text[:80]}{'...' if len(text) > 80 else ''}\"")

        def _speak():
            try:
                audio = self._synthesize(text)
                if audio is not None:
                    self._play(audio)
            except Exception as e:
                print(f"  [TTS] error: {e}", file=sys.stderr)

        t = threading.Thread(target=_speak, daemon=True)
        t.start()

    def say_blocking(self, text: str):
        """Speak and wait for completion."""
        import sounddevice as sd
        try:
            audio = self._synthesize(text)
            if audio is not None and len(audio) > 0:
                self._play(audio)
                sd.wait()  # ← wait for playback to finish
        except Exception as e:
            print(f"  [TTS] error: {e}", file=sys.stderr)

    def _synthesize(self, text: str) -> Optional[np.ndarray]:
        """Synthesize text → audio samples (float32, mono)."""
        import tempfile, subprocess

        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            mp3_path = f.name

        try:
            subprocess.run(
                [
                    'edge-tts',
                    '--voice', self._pick_voice(text),
                    '--text', text,
                    '--write-media', mp3_path,
                ],
                capture_output=True,
                timeout=15,
                check=True,
            )

            # Decode MP3 → numpy array
            import soundfile as sf
            audio, sr = sf.read(mp3_path, dtype='float32')
            if audio.ndim > 1:
                audio = audio.mean(axis=1)  # stereo → mono
            return audio

        except subprocess.TimeoutExpired:
            print(f"  [TTS] timeout", file=sys.stderr)
            return None
        except Exception as e:
            print(f"  [TTS] synthesis error: {e}", file=sys.stderr)
            return None
        finally:
            try:
                os.unlink(mp3_path)
            except OSError:
                pass

    def _play(self, audio: np.ndarray):
        """Play audio through selected output device, resampling if needed."""
        import sounddevice as sd
        from scipy import signal as sp_sig
        try:
            if self._device_rate != self._tts_rate:
                new_len = int(len(audio) * self._device_rate / self._tts_rate)
                audio = sp_sig.resample(audio, new_len)
                audio = audio.astype(np.float32)
            sd.play(audio, samplerate=self._device_rate,
                    device=self.output_device, blocking=False)
        except Exception as e:
            print(f"  [TTS] playback error: {e}", file=sys.stderr)


# ═══════════════════════════════════════════════════════════════════
# Claude API integration (LLM tool_use)
# ═══════════════════════════════════════════════════════════════════

DIRECTIONAL_LANGUAGE_EXAMPLES = {
    "turn.left": (
        "向左一点", "整个机械臂向左转", "底座往左转",
        "turn left", "rotate the whole arm left",
    ),
    "turn.right": (
        "向右一点", "整个机械臂向右转", "底座往右转",
        "turn right", "rotate the whole arm right",
    ),
    "lift.up": (
        "抬高一点", "把夹爪往上抬一下", "升高一点",
        "raise the gripper", "lift it up",
    ),
    "lift.down": (
        "降低一点", "放低一点", "把夹爪往下放",
        "lower the gripper", "move it down",
    ),
    "wrist.pitch.up": (
        "抬头", "抬头看看", "镜头朝上",
        "tilt the camera up", "look up",
    ),
    "wrist.pitch.down": (
        "低头", "低头一点", "镜头朝下",
        "tilt the camera down", "look down",
    ),
    "wrist.yaw.left": (
        "镜头看左边", "帮我看看左边", "夹爪朝左",
        "pan the camera left", "look to the left",
    ),
    "wrist.yaw.right": (
        "镜头看右边", "帮我看看右边", "夹爪朝右",
        "pan the camera right", "look to the right",
    ),
    "wrist.roll.clockwise": (
        "顺时针转一下", "手腕顺时针转", "夹爪顺时针旋转",
        "roll the wrist clockwise", "rotate clockwise",
    ),
    "wrist.roll.counterclockwise": (
        "逆时针转一下", "手腕逆时针转", "夹爪逆时针旋转",
        "roll the wrist counterclockwise", "rotate counterclockwise",
    ),
}


def _format_directional_language_examples() -> str:
    return "\n".join(
        f"- {action}: {', '.join(examples)}"
        for action, examples in DIRECTIONAL_LANGUAGE_EXAMPLES.items()
    )


DIRECTIONAL_LANGUAGE_GUIDE = _format_directional_language_examples()


ROBOT_TOOLS = [
    {
        "name": "set_joint_angle",
        "description": "Create a confirmation-gated candidate to set exactly one robot joint to an absolute angle in degrees.",
        "input_schema": {
            "type": "object",
            "properties": {
                "joint": {"type": "integer", "minimum": 1, "maximum": 6},
                "target_deg": {"type": "number"},
            },
            "required": ["joint", "target_deg"],
            "additionalProperties": False,
        },
    },
    {
        "name": "adjust_joint_angle",
        "description": "Create a confirmation-gated candidate to adjust exactly one robot joint by a delta in degrees. The execution service enforces that joint's mechanical limits.",
        "input_schema": {
            "type": "object",
            "properties": {
                "joint": {"type": "integer", "minimum": 1, "maximum": 6},
                "delta_deg": {"type": "number"},
            },
            "required": ["joint", "delta_deg"],
            "additionalProperties": False,
        },
    },
    {
        "name": "move_multiple_joints",
        "description": "Create one confirmation-gated candidate for 2 to 6 explicitly named robot joints. Each item gives either a relative delta in degrees or an absolute target in degrees. The execution service computes one six-joint target and enforces mechanical limits; never invent unspecified joints or a trajectory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "moves": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 6,
                    "items": {
                        "type": "object",
                        "properties": {
                            "joint": {"type": "integer", "minimum": 1, "maximum": 6},
                            "delta_deg": {"type": "number"},
                            "target_deg": {"type": "number"},
                        },
                        "oneOf": [
                            {"required": ["joint", "delta_deg"], "not": {"required": ["target_deg"]}},
                            {"required": ["joint", "target_deg"], "not": {"required": ["delta_deg"]}},
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["moves"],
            "additionalProperties": False,
        },
    },
    {
        "name": "directional_joint_control",
        "description": (
            "Create a confirmation-gated relative directional candidate from the camera/gripper first-person view. "
            "Chinese and English direction phrases select the same actions. Use action/delta_deg for one direction or "
            "moves for two to five non-conflicting directions that must execute atomically. Use delta_deg=20 for each "
            "action when the user gives no number; preserve explicit degree magnitudes. The execution service owns joint "
            "mapping, limits, speed, and lift-direction verification. Never provide joint arrays, speed, Cartesian "
            "distance, or trajectories."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "turn.left", "turn.right", "lift.up", "lift.down",
                        "wrist.pitch.up", "wrist.pitch.down",
                        "wrist.yaw.left", "wrist.yaw.right",
                        "wrist.roll.clockwise", "wrist.roll.counterclockwise",
                    ],
                },
                "delta_deg": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "default": 20,
                    "description": "Positive relative magnitude in degrees; default 20 when no degree is stated.",
                },
                "moves": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": [
                                    "turn.left", "turn.right", "lift.up", "lift.down",
                                    "wrist.pitch.up", "wrist.pitch.down",
                                    "wrist.yaw.left", "wrist.yaw.right",
                                    "wrist.roll.clockwise", "wrist.roll.counterclockwise",
                                ],
                            },
                            "delta_deg": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "default": 20,
                            },
                        },
                        "required": ["action"],
                        "additionalProperties": False,
                    },
                },
            },
            "oneOf": [
                {"required": ["action"], "not": {"required": ["moves"]}},
                {
                    "required": ["moves"],
                    "not": {"anyOf": [
                        {"required": ["action"]},
                        {"required": ["delta_deg"]},
                    ]},
                },
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "open_gripper",
        "description": "Create a confirmation-gated candidate to open the gripper.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "close_gripper",
        "description": "Create a confirmation-gated candidate to close the gripper.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_robot_status",
        "description": "Create a confirmation-gated candidate to read current robot status without motion.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "go_home",
        "description": "Create a confirmation-gated candidate to return to the existing Home preset used by the right-side manual control. Never generate joint angles for this action.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "software_stop",
        "description": "Immediately request software stop without waiting for confirmation. This is not a physical emergency stop.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "pick_and_place_bottle",
        "description": "Select the predefined pick_and_place_bottle@1 Skill for one Coke bottle to configured drop_zone_b. This tool selects a Skill only and never creates robot motion.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "say",
        "description": "用语音回复用户 (TTS 播报)",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要播报的中文文本"},
            },
            "required": ["text"],
        },
    },
]

VISION_INSPECT_TOOL = {
    "name": "vision_inspect_scene",
    "description": (
        "Read one fresh frame from the existing XVisio stream and return a read-only "
        "scene observation. Use this when the answer depends on what the camera can see. "
        "This tool cannot move the robot or select a grasp target."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The current visual question to answer from a fresh frame.",
            },
        },
        "required": ["question"],
        "additionalProperties": False,
    },
}

AGENT_TOOLS = [*ROBOT_TOOLS, VISION_INSPECT_TOOL]

SYSTEM_PROMPT = f"""You are a bilingual (EN/ZH) voice assistant for a desktop robot arm. The user speaks English or Chinese; you understand both and reply in the same language they used.

Robot capabilities:
- set_joint_angle(joint, target_deg): Set one joint to an absolute degree target
- adjust_joint_angle(joint, delta_deg): Change exactly one joint by a relative angle; the execution service enforces mechanical joint limits
- move_multiple_joints(moves): Move 2-6 explicitly named joints in one confirmed command; each joint uses delta_deg or target_deg, never both. The execution service enforces every mechanical joint limit.
- directional_joint_control(action, delta_deg=20) or directional_joint_control(moves=[...]): Camera/gripper-view relative directions. Map Chinese or English requests to the allowed actions. A compound request uses two to five non-conflicting moves; Node owns the joint mapping and sends one atomic bounded command.
- open_gripper(): Open the gripper
- close_gripper(): Close the gripper
- get_robot_status(): Read status without motion
- go_home(): Select the existing right-side Home preset; never generate or modify its six joint targets
- software_stop(): Immediately request SDK cleanup and motor disable; not a physical E-stop
- pick_and_place_bottle(): Select the predefined Coke bottle pipeline; an external adapter owns all motion
- vision_inspect_scene(question): Inspect one fresh camera frame without moving the robot
- say(text): Speak a response to the user

Approved Directional vocabulary examples. Match meaning and ordinary paraphrases, not only exact strings:
{DIRECTIONAL_LANGUAGE_GUIDE}

Other approved command examples:
- open_gripper(): 松开夹爪, 打开夹爪, 张开夹爪, open the gripper
- close_gripper(): 把夹爪合上, 关闭夹爪, 夹紧夹爪, close the gripper
- go_home(): 回到home, 归位, 回零, 回到初始姿态, go home

Rules:
1. Tools create structured candidates only. Never claim a candidate has executed.
2. For any request that plausibly maps to at least one supported action, create a candidate. Choose exactly one most likely supported interpretation (a single action or one non-conflicting compound moves list). Do not ask a follow-up clarification when at least one supported action is plausible. Use subject words such as 整个机械臂/底座 versus 看/镜头/摄像头/夹爪朝向 to disambiguate base turn from wrist yaw. Use `say` without a motion candidate only when no supported action is plausible, the request is contradictory, or it requests an unsupported capability. The words 点, 一点, 一下, and "a little" mean the approved default of 20 degrees.
3. Refuse XYZ, Cartesian, unspecified joint targets, high-speed and ACT motion generation. A directional compound may combine only the allowed action list through directional_joint_control(moves); never generate its joints yourself. Use at most one action from each opposing family: turn, lift, wrist pitch, wrist yaw, and wrist roll. For an explicit Home request, use go_home so the execution service reuses the existing preset. For a clear request to pick one Coke bottle and place it in configured drop_zone_b, select pick_and_place_bottle without inventing any motion.
4. A direct command naming one joint uses set_joint_angle or adjust_joint_angle. If the user explicitly names 2-6 distinct joints and their degree targets or signed changes (for example J1 +10 and J2 -10), use move_multiple_joints once; preserve each value exactly and do not invent any unspecified joint motion. A directional request may select one allowed action or two to five non-conflicting moves. If an action has no degree number, use 20 for that action. Examples: "抬高点，向左点" means lift.up 20 and turn.left 20. "抬高并向左 10 度" means lift.up 10 and turn.left 10 because one trailing magnitude applies to the coordinated group. "抬高 10 度，向左 15 度" means lift.up 10 and turn.left 15 because the values are named separately. Treat 再, 再来一点, 再多一点, again, and a little more as a new request that repeats the most recent supported action in the conversation, using the approved default of 20 degrees unless the user states a new magnitude. The repeated action still creates a new candidate and requires a new confirmation; never append it to a pending candidate or auto-execute it. Never invent joint limits; the execution service validates the resulting targets against configured mechanical limits.
5. Use software_stop immediately for an explicit stop request. Explain that it is not the physical E-stop.
6. Keep replies concise (1-2 sentences) and use the same language as the user.
7. When the answer depends on the current camera view, call vision_inspect_scene. Decide semantically rather than by a fixed keyword list. Explicit requests such as "重新看一下" or "use the camera" require a fresh visual call. If the user explicitly says not to use the camera or to answer only from the previous result, do not call it and make clear that prior context may not describe the current scene.
8. A visual observation is evidence only. Never turn it into coordinates, a grasp target, a trajectory, or an executed action. Preserve uncertainty from the visual result.
9. Never rewrite or invent hardware execution results."""


class ThirdHandController:
    """Natural language → robot actions via Anthropic API (with optional CC-Switch proxy).

    Supports:
      - Direct Anthropic API (needs sk-ant-... key)
      - CC-Switch proxy at 127.0.0.1:15721
      - DeepSeek Anthropic-compatible endpoint (fallback)
    """

    CC_SWITCH_DB = os.path.expanduser(
        os.environ.get("CC_SWITCH_DB", "~/.cc-switch/cc-switch.db")
    )
    CC_SWITCH_PROXY = "http://127.0.0.1:15721"

    def __init__(
        self,
        api_key: str = None,
        model: str = "auto",
        provider: str = "auto",
        *,
        client=None,
        vision_skill=None,
    ):
        self.provider = provider
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._base_url = None

        if client is None:
            self._try_ccswitch()

        has_ccswitch = bool(self._base_url)
        if client is None and not self._api_key and not has_ccswitch:
            print("[llm] WARNING: No API key. Set ANTHROPIC_API_KEY or configure CC-Switch.")

        self.provider = "anthropic"
        if model == "auto":
            model = os.environ.get("TEXT_LLM_MODEL", "deepseek-v4-pro")
        self.model = model
        self.vision_model = os.environ.get("VISION_LLM_MODEL", "deepseek-flash")

        self._client = client
        self._vision_skill = vision_skill
        self._history = []
        self._visual_summary: str | None = None
        info = f"provider={self.provider}, model={self.model}"
        if self._base_url:
            info += f", base_url={self._base_url}"
        key_src = "CC-Switch" if self._base_url else ("env" if self._api_key else "none")
        info += f", key={key_src}"
        print(f"[llm] {info}")

    def _try_ccswitch(self):
        """Try to use CC-Switch proxy or its configured endpoint."""
        # 1. Check if CC-Switch proxy is running locally
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        if s.connect_ex(('127.0.0.1', 15721)) == 0:
            s.close()
            self._base_url = self.CC_SWITCH_PROXY
            if not self._api_key:
                self._api_key = "cc-switch"  # proxy handles auth
            print("[llm] CC-Switch proxy detected on port 15721")
            return

        # 2. Read CC-Switch config for Anthropic endpoint
        try:
            import sqlite3, json
            db = sqlite3.connect(self.CC_SWITCH_DB)
            rows = db.execute(
                "SELECT p.settings_config FROM providers p "
                "JOIN provider_endpoints pe ON pe.provider_id = p.id "
                "WHERE p.app_type='claude' AND p.settings_config LIKE '%ANTHROPIC_BASE_URL%' LIMIT 1"
            ).fetchall()
            db.close()

            if rows and rows[0][0]:
                config = json.loads(rows[0][0])
                env = config.get('env', {})
                url = env.get('ANTHROPIC_BASE_URL', '')
                key = env.get('ANTHROPIC_AUTH_TOKEN', '')
                if url:
                    self._base_url = url.rstrip('/')
                    if key:
                        self._api_key = key  # CC-Switch key always wins
                    print(f"[llm] CC-Switch: {url}")
        except Exception:
            pass

    def _init_client(self):
        if self._client is not None:
            return
        import anthropic
        kwargs = dict(api_key=self._api_key)
        if self._base_url:
            kwargs["base_url"] = self._base_url
        self._client = anthropic.Anthropic(**kwargs)

    def _get_vision_skill(self):
        if self._vision_skill is not None:
            return self._vision_skill
        self._init_client()
        worker_path = (
            Path(__file__).resolve().parents[3]
            / "skills" / "vision" / "inspect-scene" / "src" / "worker.py"
        )
        if not worker_path.is_file():
            raise RuntimeError("视觉 Skill 尚未安装。")
        spec = importlib.util.spec_from_file_location("thirdhand_inspect_scene", worker_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("视觉 Skill 无法加载。")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stream_url = os.environ.get(
            "VISION_STREAM_URL",
            "http://127.0.0.1:3100/camera/xvisio/raw",
        )
        try:
            max_age_ms = int(os.environ.get("VISION_QA_MAX_FRAME_AGE_MS", "2000"))
        except ValueError:
            max_age_ms = 2000
        skill_root = worker_path.parents[1]
        self._vision_skill = module.InspectSceneSkill(
            client=self._client,
            frame_source=module.MjpegFrameSource(
                stream_url,
                timeout_seconds=max(0.1, max_age_ms / 1000),
            ),
            retention=module.ImageRetention(skill_root / "test_pics"),
            model=self.vision_model,
            max_frame_age_ms=max_age_ms,
        )
        return self._vision_skill

    @staticmethod
    def _language(text: str) -> str:
        return "zh" if any("\u4e00" <= char <= "\u9fff" for char in text) else "en"

    def _history_window(self, max_entries: int = 12) -> list[dict[str, Any]]:
        """Trim only at a real user-turn boundary, never inside a tool pair."""
        if len(self._history) <= max_entries:
            return list(self._history)
        target = len(self._history) - max_entries
        starts = [
            index
            for index, message in enumerate(self._history)
            if message.get("role") == "user"
            and isinstance(message.get("content"), str)
        ]
        if not starts:
            return list(self._history)
        start = next((index for index in starts if index >= target), starts[-1])
        return list(self._history[start:])

    def _create_message(self):
        return self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=AGENT_TOOLS,
            messages=self._history_window(),
        )

    @staticmethod
    def _parts(response) -> tuple[list[str], list[Any]]:
        text_parts = []
        tools = []
        for block in getattr(response, "content", []):
            if getattr(block, "type", None) == "text":
                value = str(getattr(block, "text", "")).strip()
                if value:
                    text_parts.append(value)
            elif getattr(block, "type", None) == "tool_use":
                tools.append(block)
        return text_parts, tools

    @staticmethod
    def _candidate_reply(actions: list[dict[str, Any]]) -> str:
        for action in actions:
            if action.get("tool") == "say":
                value = str(action.get("input", {}).get("text", "")).strip()
                if value:
                    return value
        return f"已生成 {len(actions)} 个待确认操作，请在页面确认后再执行。"

    def chat(self, user_text: str) -> Dict:
        """Run one controller turn, including at most one visual Skill call."""
        self._init_client()
        if self._client is None:
            return {
                "text": f"[LLM not available] 收到: {user_text}",
                "actions": [],
                "trace": [],
            }

        self._history.append({"role": "user", "content": user_text})
        try:
            response = self._create_message()
        except Exception:
            return {
                "text": "语言模型暂时不可用，请稍后重试。",
                "actions": [],
                "trace": [{
                    "stage": "controller.text",
                    "status": "failed",
                    "code": "llm_unavailable",
                }],
            }

        trace: list[dict[str, Any]] = []
        vision_used = False

        while True:
            reply_parts, tool_blocks = self._parts(response)
            vision_blocks = [
                block for block in tool_blocks
                if getattr(block, "name", "") == "vision_inspect_scene"
            ]

            if vision_blocks:
                if vision_used:
                    return {
                        "text": "本轮视觉检查次数已达到上限，请发起新的请求后再看。",
                        "actions": [],
                        "trace": trace,
                    }
                if len(tool_blocks) != 1:
                    trace.append({
                        "stage": "controller.policy",
                        "status": "failed",
                        "code": "vision_motion_separation",
                    })
                    return {
                        "text": "视觉检查与机械臂动作需要分开请求；本轮不会生成动作候选。",
                        "actions": [],
                        "trace": trace,
                    }
                vision_used = True
                block = vision_blocks[0]
                payload = getattr(block, "input", {}) or {}
                question = str(payload.get("question") or user_text).strip()

                try:
                    result = self._get_vision_skill().invoke(
                        question,
                        prior_visual_summary=self._visual_summary,
                        language=self._language(user_text),
                    )
                except Exception as exc:
                    code = str(getattr(exc, "code", "vision_failed"))
                    trace.append({
                        "stage": "vision.inspect_scene",
                        "status": "failed",
                        "code": code,
                    })
                    safe_codes = {
                        "stream_unavailable", "invalid_stream", "invalid_frame",
                        "frame_too_large", "frozen_frame", "stale_frame",
                        "vision_auth_failed", "vision_model_unavailable",
                        "vision_empty_response", "invalid_question",
                    }
                    message = (
                        str(exc).strip()
                        if code in safe_codes
                        else "当前无法完成视觉检查。"
                    )
                    return {"text": message, "actions": [], "trace": trace}

                summary = str(result.get("summary", "")).strip()
                if summary:
                    self._visual_summary = summary
                for item in result.get("trace", []):
                    if isinstance(item, dict):
                        trace.append(item)

                self._history.append({
                    "role": "assistant",
                    "content": list(getattr(response, "content", [])),
                })
                self._history.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": getattr(block, "id", "vision-inspect-scene"),
                        "content": json.dumps(result, ensure_ascii=False),
                    }],
                })
                try:
                    response = self._create_message()
                except Exception:
                    trace.append({
                        "stage": "controller.text",
                        "status": "failed",
                        "code": "llm_unavailable",
                    })
                    return {
                        "text": "视觉结果已取得，但语言模型暂时无法继续回答。",
                        "actions": [],
                        "trace": trace,
                    }
                continue

            if vision_used and tool_blocks:
                if all(getattr(block, "name", "") == "say" for block in tool_blocks):
                    say_actions = [{
                        "tool": "say",
                        "input": getattr(block, "input", {}) or {},
                    } for block in tool_blocks]
                    reply = " ".join(reply_parts).strip() or self._candidate_reply(say_actions)
                    self._history.append({
                        "role": "assistant",
                        "content": list(getattr(response, "content", [])),
                    })
                    self._history.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": getattr(block, "id", "say"),
                            "content": "Natural-language response accepted.",
                        } for block in tool_blocks],
                    })
                    return {"text": reply, "actions": [], "trace": trace}
                trace.append({
                    "stage": "controller.policy",
                    "status": "failed",
                    "code": "vision_motion_separation",
                })
                return {
                    "text": "视觉检查仅用于描述；请在下一条指令中单独下达机械臂动作。",
                    "actions": [],
                    "trace": trace,
                }

            actions = [
                {
                    "tool": str(getattr(block, "name", "")),
                    "input": getattr(block, "input", {}) or {},
                }
                for block in tool_blocks
            ]
            reply = " ".join(reply_parts).strip()
            if not reply and actions:
                reply = self._candidate_reply(actions)

            self._history.append({
                "role": "assistant",
                "content": list(getattr(response, "content", [])) if tool_blocks else reply,
            })
            if tool_blocks:
                self._history.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": getattr(block, "id", "robot-candidate"),
                        "content": f"候选操作已生成，等待用户确认: {getattr(block, 'name', '')}",
                    } for block in tool_blocks],
                })
            return {"text": reply, "actions": actions, "trace": trace}

    def _legacy_chat(self, user_text: str) -> Dict:
        """Send user text → Anthropic (via CC-Switch) → execute tool calls."""
        self._init_client()
        if self._client is None:
            return {'text': f'[LLM not available] 收到: {user_text}', 'actions': []}

        self._history.append({"role": "user", "content": user_text})

        try:
            response = self._client.messages.create(
                model=self.model, max_tokens=1024,
                system=SYSTEM_PROMPT, tools=ROBOT_TOOLS,
                messages=self._history[-10:],
            )
        except Exception as e:
            return {'text': f'API 错误: {e}', 'actions': []}

        reply_parts, actions = [], []
        for block in response.content:
            if block.type == "text":
                reply_parts.append(block.text)
            elif block.type == "tool_use":
                actions.append({'tool': block.name, 'input': block.input})
                self._history.append({"role": "assistant", "content": [block]})
                self._history.append({"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": block.id,
                    "content": f"候选操作已生成，等待用户确认: {block.name}"}]})

        reply = " ".join(reply_parts) if reply_parts else ""

        # FUTURE: 真机上机验证时，根据 RobotExecutor 执行结果改写回复
        # - 成功：直接返回 LLM 自然语言回复或 "已执行: <动作描述>"
        # - 失败：返回具体失败原因，例如 "夹爪打开失败: CAN 总线无响应"
        # 当前仅生成占位摘要，不反映实际执行结果。
        if not reply and actions:
            # Prefer the say tool's text as the visible reply.
            for action in actions:
                if action.get("tool") == "say":
                    say_text = str(action.get("input", {}).get("text", "")).strip()
                    if say_text:
                        reply = say_text
                        break
            if not reply:
                reply = (
                    f"已生成 {len(actions)} 个待确认操作，"
                    "请在页面确认后再进行本地模拟。"
                )
        self._history.append({"role": "assistant", "content": reply})
        return {'text': reply, 'actions': actions}


# ═══════════════════════════════════════════════════════════════════
# Robot command executor (bridge to ThirdHand)
# ═══════════════════════════════════════════════════════════════════

ClaudeAgent = ThirdHandController


class RobotExecutor:
    """
    Execute robot actions from Claude tool calls.
    Uses TTSEngine for voice responses, WebSocket for robot control.

    FUTURE: 真机上机验证时，execute() 应返回 (success: bool, message: str)
    - 成功 → (True, "已执行: 夹爪打开至 0.05m")，由上层改写 ClaudeAgent 回复
    - 失败 → (False, "夹爪打开失败: CAN 总线超时")，同样反馈到用户界面
    当前各工具方法均 return True，未连接硬件验证实际执行结果。
    """

    def __init__(self, proxy_url: str = "ws://localhost:3000/ws",
                 tts: Optional[TTSEngine] = None):
        self.proxy_url = proxy_url
        self.tts = tts
        self._ws = None

    def execute(self, action: Dict) -> bool:
        """
        Execute one tool action. Returns True on success.

        Supports: move_to, grasp, release, go_home, emergency_stop, say
        """
        tool = action.get('tool', '')
        params = action.get('input', {})

        if tool == 'say':
            text = params.get('text', '')
            if self.tts:
                self.tts.say(text)  # async, non-blocking
            else:
                print(f"  🔊 [TTS] {text}")
            return True

        elif tool == 'move_to':
            x, y, z = params.get('x', 0), params.get('y', 0), params.get('z', 0)
            print(f"  🦾 [Robot] MOVETO x={x:.3f} y={y:.3f} z={z:.3f}")
            self._send_to_proxy({
                'cmd': 'servo',
                'joints': self._ik_approx(x, y, z),
            })
            return True

        elif tool == 'grasp':
            width = params.get('width', 0.05)
            print(f"  ✋ [Robot] GRASP width={width:.3f}m")
            # TODO: gripper control
            return True

        elif tool == 'release':
            print(f"  🖐 [Robot] RELEASE")
            # TODO: gripper control
            return True

        elif tool == 'go_home':
            print(f"  🏠 [Robot] GO HOME")
            self._send_to_proxy({
                'cmd': 'preset',
                'name': 'home',
            })
            return True

        elif tool == 'emergency_stop':
            print(f"  🛑 [Robot] EMERGENCY STOP!")
            self._send_to_proxy({'cmd': 'estop'})
            return True

        else:
            print(f"  ⚠ [Robot] Unknown tool: {tool}")
            return False

    def _send_to_proxy(self, msg: Dict):
        """Send command to ThirdHand Node.js proxy."""
        try:
            import websocket
            ws = websocket.create_connection(self.proxy_url, timeout=2)
            ws.send(json.dumps(msg))
            ws.close()
        except Exception as e:
            print(f"  [Robot] proxy send failed: {e}", file=sys.stderr)

    def _ik_approx(self, x, y, z):
        """Approximate IK — placeholder. Replace with real IK later."""
        return [0, 0, 0, 0, 0, 0]


# ═══════════════════════════════════════════════════════════════════
# Main orchestrator
# ═══════════════════════════════════════════════════════════════════

class VoiceAgent:
    """
    End-to-end voice control agent.

    Pipeline:
      Mic → VAD → faster-whisper → Claude → Robot

    Modes:
      - full: VAD → ASR → Claude → Robot
      - asr-only: just transcribe (no LLM), for testing
      - llm-only: text input → Claude → Robot (no mic)
    """

    def __init__(
        self,
        device: str = "auto",
        whisper_model: str = "small",
        claude_model: str = "auto",
        mode: str = "full",
        proxy_url: str = "ws://localhost:3000/ws",
        tts_voice: str = None,  # None = auto-detect EN/ZH
    ):
        self.mode = mode
        self.device_name = None
        self.device_type = None
        self.speaker_name = None
        self.speaker_type = None

        # Select audio I/O devices
        if mode != "llm-only":
            self.device_name, self.device_type, self.device_rate = select_mic(prefer=device)
            self.speaker_name, self.speaker_type, self.speaker_rate = select_speaker(prefer=device)

        # TTS engine
        spk_rate_int = int(self.speaker_rate) if hasattr(self, 'speaker_rate') else 48000
        self.tts = TTSEngine(output_device=self.speaker_name, voice=tts_voice,
                              device_rate=spk_rate_int)

        # Components
        self.capture = None
        self.asr = WhisperASR(model_size=whisper_model) if mode != "llm-only" else None
        self.llm = ClaudeAgent(model=claude_model) if mode != "asr-only" else None
        self.robot = RobotExecutor(proxy_url=proxy_url, tts=self.tts)

        print(f"\n{'='*60}")
        print(f"  Voice Agent Ready")
        print(f"  Mode:     {mode}")
        print(f"  🎤 Input:  {self.device_name or 'N/A (text-only)'}")
        print(f"  🔊 Output: {self.speaker_name or 'N/A (text-only)'}")
        print(f"  ASR:      {whisper_model} (CPU)")
        print(f"  LLM:      {claude_model}")
        print(f"  TTS:      edge-tts (EN+ZH bilingual)")
        print(f"{'='*60}\n")

        # Welcome audio confirmation
        if mode != "llm-only":
            self.tts.say_blocking("语音助手已就绪")

    def run(self):
        """Main loop."""
        if self.mode == "llm-only":
            self._run_text_mode()
        else:
            self._run_voice_mode()

    def _run_voice_mode(self):
        """Microphone → VAD → ASR → (optional) Claude → Robot."""
        self.capture = AudioCapture(self.device_name,
                                     device_sample_rate=int(self.device_rate) if hasattr(self, 'device_rate') else 48000)
        self.capture.start()
        print("Listening... (speak now)\n")

        try:
            while True:
                seg = self.capture.get_utterance(timeout=0.5)
                if seg is None:
                    continue

                # 1. ASR
                print(f"\n--- Utterance {seg.duration:.1f}s ---")
                result = self.asr.transcribe(seg.audio)
                text = result['text'].strip()
                if not text:
                    print("  ⚠ [ASR] empty result, skipping")
                    continue

                # 2. Claude (if not asr-only mode)
                if self.mode == "asr-only":
                    print(f"  📝 [Result] \"{text}\"")
                    continue

                if self.llm:
                    llm_result = self.llm.chat(text)
                    print(f"  💬 [Claude] {llm_result['text']}")

                    # 3. Execute robot actions
                    for action in llm_result['actions']:
                        self.robot.execute(action)

        except KeyboardInterrupt:
            print("\n[voice] Shutting down...")
        finally:
            self.capture.stop()

    def _run_text_mode(self):
        """Text input → Claude → Robot (no mic/ASR)."""
        print("Text mode — type commands, Ctrl+C to exit\n")
        try:
            while True:
                text = input("You > ").strip()
                if not text:
                    continue
                if text.lower() in ('q', 'quit', 'exit'):
                    break

                llm_result = self.llm.chat(text)
                print(f"Claude > {llm_result['text']}")

                for action in llm_result['actions']:
                    self.robot.execute(action)

        except (KeyboardInterrupt, EOFError):
            print("\nDone.")


# ═══════════════════════════════════════════════════════════════════
# Quick test (no API key needed for ASR-only mode)
# ═══════════════════════════════════════════════════════════════════

def _record_pw(duration: float, sample_rate: int = 48000) -> np.ndarray:
    """Record audio via PipeWire (pw-record) — bypasses PortAudio bugs."""
    import subprocess, tempfile
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        wav_path = f.name
    try:
        subprocess.run(
            ['timeout', str(int(duration) + 2), 'pw-record',
             '--rate', str(sample_rate), '--channels', '1',
             '--format', 's16', wav_path],
            timeout=int(duration) + 5,
            capture_output=True,
        )
        import soundfile as sf
        audio, sr = sf.read(wav_path, dtype='float32')
        return audio
    finally:
        try: os.unlink(wav_path)
        except OSError: pass


def quick_test():
    """Test audio capture + VAD + ASR + TTS with a short recording."""
    print("=== Voice Agent Quick Test (I/O Loop) ===\n")

    spk_name, spk_type, spk_rate = select_speaker()

    # 1. Record via PipeWire (bypasses PortAudio)
    rec_secs = 5
    print(f"\n🎤 Recording {rec_secs}s via PipeWire (HECATE mic)...")
    print("Speak now!\n")
    audio_16k = _record_pw(rec_secs, sample_rate=16000)
    audio_16k = audio_16k.astype(np.float32)

    # 2. Transcribe
    print("📝 Transcribing...")
    asr = WhisperASR(model_size="small")
    result = asr.transcribe(audio_16k)
    print(f"   → \"{result['text']}\"")

    # 3. Play back response
    tts = TTSEngine(output_device=spk_name, device_rate=int(spk_rate))
    reply = f"你说的是：{result['text']}" if result['text'].strip() else '没有听到语音'
    print(f"🔊 Playing: \"{reply}\"")
    tts.say_blocking(reply)
    print("Done.")


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ubuntu PC Voice Agent")
    parser.add_argument('--tts-voice', default='zh-CN-XiaoxiaoNeural',
                        help='Edge TTS voice name')
    parser.add_argument('--list-devices', action='store_true',
                        help='List audio input devices and exit')
    parser.add_argument('--device', default='auto',
                        help='Audio device name or "auto"')
    parser.add_argument('--whisper-model', default='small',
                        choices=['tiny', 'base', 'small', 'medium'],
                        help='Whisper model size')
    parser.add_argument('--claude-model', default='auto',
                        help='Claude model ID')
    parser.add_argument('--mode', default='full',
                        choices=['full', 'asr-only', 'llm-only'],
                        help='Pipeline mode')
    parser.add_argument('--proxy', default='ws://localhost:3000/ws',
                        help='ThirdHand proxy WebSocket URL')
    parser.add_argument('--test', action='store_true',
                        help='Quick 5s test: record + transcribe')

    args = parser.parse_args()

    if args.list_devices:
        list_input_devices()
        sys.exit(0)

    if args.test:
        quick_test()
        sys.exit(0)

    agent = VoiceAgent(
        device=args.device,
        whisper_model=args.whisper_model,
        claude_model=args.claude_model,
        mode=args.mode,
        proxy_url=args.proxy,
        tts_voice=args.tts_voice,
    )
    agent.run()
