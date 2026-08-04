# ThirdHand VLA

ThirdHand VLA is a desktop robotic-arm platform for the Lumos Touch R1 and
Lumos Ego camera. It combines local perception, guarded robot control, optional
cloud VLA reasoning, and browser-based operator tools.

Chinese documentation: [README_CN.md](README_CN.md)

## Repository layout

| Path | Responsibility |
| --- | --- |
| `src/uiea_thirdhand_vla/` | Installable Python VLA application and FastAPI console |
| `web-control/` | Standalone Startouch SDK bridge, camera services, and operator UI |
| `configs/` | Portable robot, camera, task, and vision configuration |
| `scripts/` | Calibration, deployment, demo, and validation entry points |
| `tests/` | Offline application and workflow tests |
| `docs/` | Architecture, setup, API, safety, and research records |

See [docs/architecture.md](docs/architecture.md) for component boundaries and
data flow.

## Quick start

Python 3.10 or newer is required.

```bash
git clone https://github.com/Oliveirah007/UIEAclub_ThirdHand_VLA.git
cd UIEAclub_ThirdHand_VLA
python -m venv .venv
. .venv/bin/activate
pip install -e ".[core]"
cp .env.example .env
python -m uiea_thirdhand_vla
```

Open `http://localhost:8000` for the packaged FastAPI console.

## Startouch hardware web control

The independently deployable `web-control/` service controls the robot through
the Startouch SDK and `can0`. Read
[web-control/README.md](web-control/README.md) and verify the hardware stop
before enabling motion.

```bash
cp web-control/.env.example web-control/.env
web-control/scripts/setup_ubuntu.sh
web-control/scripts/start_ubuntu.sh
```

Open `http://<robot-host>:3000`. The UI proxies the Startouch bridge and D435
stream; the Lumos HTTP stream listens on port `3001` when enabled.

## Fixed A/B pick-and-place demo

The fixed-point demo has an independent loopback-only control page. It checks
the branch, `can0`, point validity, joint limits, speed, logs, and competing
control processes before motion.

```bash
bash scripts/demo_fixed_pick_place.sh
# Or open the loopback dashboard:
bash scripts/open_fixed_pick_place_control.sh
```

Open `http://127.0.0.1:8766`. Do not run it alongside another CAN controller.
Detailed operating and safety instructions are in
[web-control/FIXED_PICK_PLACE.md](web-control/FIXED_PICK_PLACE.md).

## Service ports

| Port | Bind/default | Service |
| --- | --- | --- |
| `8000` | `0.0.0.0` | Packaged VLA FastAPI console |
| `3000` | `0.0.0.0` | Startouch proxy and browser UI |
| `3001` | `0.0.0.0` | Lumos camera HTTP/MJPEG service |
| `8766` | `127.0.0.1` | Fixed-point demo control page |

Override ports through the corresponding YAML or environment configuration.

## Models and runtime data

Downloaded `*.pt` and `*.onnx` weights, logs, PID files, captured frames, and
operator point backups are local runtime artifacts and are not committed. See
[docs/model_assets.md](docs/model_assets.md) for model setup and configuration.

## Development verification

```bash
pip install -e ".[core,dev]"
ruff check src/ tests/
mypy src/
STARTOUCH_CAN_INTERFACE=thirdhand-test pytest tests/ -q --ignore=tests/e2e/
pytest web-control/server/tests/ -q
```

The test interface name prevents offline lock tests from competing with a live
`can0` controller.

## License

MIT — see [LICENSE](LICENSE).
