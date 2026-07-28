# Setup Guide -- Ubuntu 20.04

## Prerequisites
- Ubuntu 20.04+, Python 3.10+, CAN interface, Lumos Touch R1, Lumos Ego camera

## 1. System Dependencies
```bash
sudo apt update && sudo apt install -y python3.10 python3.10-venv python3.10-dev can-utils v4l-utils
```

## 2. CAN Bus
```bash
sudo ip link set can0 type can bitrate 1000000
sudo ip link set up can0
candump can0
```

## 3. Python Environment
```bash
cd UIEAclub_ThirdHand_VLA
python3.10 -m venv .venv && source .venv/bin/activate
pip install -e ".[core]"
```

## 4. Robot SDK
```bash
git clone https://github.com/lumos-open/startouch_sdk
cd startouch_sdk && pip install -e .
```

## 5. Camera SDK
See: https://github.com/lumos-open/FastUMI_Hardware_SDK

## 6. Configuration
```bash
cp .env.example .env
# edit .env with API keys
# edit configs/*.yaml for your hardware
```

## 7. Verify
```bash
python -c "import uiea_thirdhand_vla; print(uiea_thirdhand_vla.__version__)"
python -m uiea_thirdhand_vla
# Open http://localhost:8000
```
