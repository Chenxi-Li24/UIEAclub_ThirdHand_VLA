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
- `../../skills/vision/inspect-scene`: read-only visual question answering from
  the existing XVisio MJPEG stream.

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

## Text controller and visual Skill

The default controller model is `deepseek-v4-pro`. It decides semantically
whether the current request needs the `vision_inspect_scene` tool. Only that
tool sends an image to `deepseek-flash`; Pro never receives image input. Both
requests reuse the same resolved Anthropic-compatible DeepSeek credential from
`start-with-user-auth.sh`. There is no separate vision key by default.

The visual Skill reads one new JPEG from
`http://127.0.0.1:3100/camera/xvisio/raw`. It never opens `/dev/video*`, starts
or restarts the camera service, changes calibration, or moves the robot. If the
stream is unavailable, stale, or Flash rejects the request, the turn fails
explicitly after at most one transient retry. It never falls back to Pro.

Recent raw frames are retained under
`skills/vision/inspect-scene/test_pics/` for debugging: at most 20 JPEG files
and no longer than 24 hours. The files are ignored by Git. The 9983 assistant
panel receives only the natural-language answer; the communication log may
show the sanitized stage, model, frame ID/age, retry count, or error code.

For live acceptance, first confirm that the existing 3004, 3100, and 9983
processes own their expected ports. Read a frame through the running 3100 HTTP
stream and invoke the Skill without restarting any service. If the existing
credential is specifically rejected for `deepseek-flash`, obtain a compatible
key instead of changing models or silently degrading the request.

## Test

```bash
python -m pytest tests/python/speech_service services/speech/src/test_*.py -q
```
