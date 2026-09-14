# Setup Guide -- Ubuntu 20.04 / 22.04

## Prerequisites

- Ubuntu 20.04 or 22.04
- Python 3.10+
- Node.js 18+ and npm
- CAN interface, Lumos Touch R1, Lumos Ego camera

Ubuntu 20.04 is the currently tested hardware environment. Ubuntu 22.04 is
supported by the repository layout and scripts, but must be regression-tested
with the actual Startouch SDK binary and robot before production use.

## 1. System Dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-dev can-utils v4l-utils
```

Install Node.js 18 or newer using your preferred Ubuntu package source, then
verify:

```bash
node --version
npm --version
```

## 2. CAN Bus

```bash
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
ip -details -statistics link show can0
```

`candump can0` may remain quiet when the motors only reply to requests. The
hardware web controller performs an active CAN preflight before constructing
the SDK object.

## 3. Python VLA Environment

```bash
cd UIEAclub_ThirdHand_VLA
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[core]"
```

## 4. Robot SDK

Keep the vendor SDK outside this repository. The default hardware web-control
path is `~/arm/startouch_sdk`, and it can be overridden with
`STARTOUCH_SDK_PATH`.

The SDK's native extension must be built for the active Python version and
Ubuntu ABI. Rebuild or obtain a compatible SDK package before moving from
Ubuntu 20.04 to 22.04.

## 5. Startouch Hardware Web Control

```bash
cd UIEAclub_ThirdHand_VLA
cp web-control/.env.example web-control/.env
# Edit web-control/.env if the SDK or Python paths differ.
web-control/scripts/setup_ubuntu.sh
web-control/scripts/start_ubuntu.sh
# Open http://<Ubuntu-IP>:3000
```

The service talks directly to the robot through the SDK and `can0`; no
intermediate development board is required. See
[`../web-control/README.md`](../web-control/README.md) before enabling motors.

## 6. Camera SDK

See: https://github.com/lumos-open/FastUMI_Hardware_SDK

## 7. VLA Configuration

```bash
cp .env.example .env
# Edit .env with API keys.
# Edit configs/*.yaml for your hardware.
```

## 8. Verify the VLA Console

```bash
python -c "import uiea_thirdhand_vla; print(uiea_thirdhand_vla.__version__)"
python -m uiea_thirdhand_vla
# Open http://localhost:8000
```
