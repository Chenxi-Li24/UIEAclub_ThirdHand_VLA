from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SPEECH_SRC = ROOT / "services/speech/src"
EXPECTED_RUNTIME_FILES = {
    "asr_model_manager.py",
    "funasr_backends.py",
    "tts_bridge.py",
    "voice_agent.py",
    "voice_bridge.py",
    "whisper_backend.py",
}
FORBIDDEN_REFERENCES = (
    "History/",
    "/home/nieqingcao/Thirdhand_language",
    "/home/nieqingcao/th0814",
)


def test_formal_speech_runtime_is_complete() -> None:
    assert SPEECH_SRC.is_dir(), "formal speech service is missing"
    actual = {path.name for path in SPEECH_SRC.glob("*.py")}
    assert EXPECTED_RUNTIME_FILES <= actual


def test_formal_speech_runtime_has_no_old_project_dependency() -> None:
    assert SPEECH_SRC.is_dir(), "formal speech service is missing"
    for path in SPEECH_SRC.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_REFERENCES:
            assert forbidden not in text, f"{path} references {forbidden}"
