# Ubuntu Speech Service

This is the formal speech runtime for the unified ThirdHand project. It listens
only on `127.0.0.1:3004`; browsers access it through the Web Gateway's same-origin
`/voice` WebSocket.

## Components

- `src/voice_bridge.py`: `thirdhand.voice.v1` WebSocket service.
- `src/asr_model_manager.py`: Medium, Real-time, and High model lifecycle.
- `src/whisper_backend.py`: Medium Whisper backend.
- `src/funasr_backends.py`: Real-time Paraformer and High Fun-ASR backends.
- `src/voice_agent.py`: text/voice dialogue and candidate action generation.
- `src/tts_bridge.py`: speech response bridge.
- `src/model_paths.py`: project-local ASR model resolution.

Candidate actions are previews. This service cannot control the robot and cannot
send CAN frames. Robot execution requires the separate confirmation and Robot
Service path, which is not yet fully adapted.

## Start

Use the unified launcher:

```bash
./thirdhand start --profile manual-control
./thirdhand status --profile manual-control
```

For isolated diagnostics only:

```bash
local/runtimes/python/bin/python services/speech/src/voice_bridge.py \
  --host 127.0.0.1 --port 3004
```

Models must exist below `local/models/asr/{medium,realtime,high}`. The launcher
uses `medium` by default. Historical Jetson and 3001/3002 instructions are kept
under `History/legacy-platform/docs/` and are not supported runtime entrypoints.

## Test

```bash
python -m pytest tests/python/speech_service services/speech/src/test_*.py -q
```
