# ThirdHand one-click start

## Purpose

The one-click start is a developer-triggered, one-shot CAN and service check
for the Ubuntu ThirdHand host. It prepares `can0`, keeps expected services that
are already listening, starts only missing services in profile order, prints
the results, and then exits.

It is not a background monitor, boot service, automatic restart policy, robot
connection action, or one-click stop command. After the web page opens, the
operator still connects the robot manually.

## Locations

| Item | Location |
|---|---|
| Ubuntu repository | `/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA` |
| Backend command | `./thirdhand ensure --profile manual-control` |
| Launcher CLI | `apps/launcher/src/cli.js` |
| Ensure implementation | `apps/launcher/src/service-supervisor.js` |
| CAN preparation | `apps/launcher/src/can-interface.js` |
| Two-level recovery orchestration | `apps/launcher/src/runtime-ensure.js` |
| Service profile | `configs/runtime/manual-control.json` |
| Windows installer | `tools/launcher/windows/install-thirdhand-shortcut.ps1` |
| Ubuntu installer | `tools/launcher/ubuntu/install-ubuntu-shortcut.sh` |
| Ubuntu launcher script | `tools/launcher/ubuntu/start-thirdhand.sh` |
| English guide | `docs/ONE_CLICK_START.md` |
| Chinese guide | `docs/ONE_CLICK_START_CN.md` |

After installation on Windows:

- desktop shortcut: `Start ThirdHand.lnk`;
- local runner: `%LOCALAPPDATA%\ThirdHand\Start-ThirdHand.cmd`;
- last-run diagnostic log: `%LOCALAPPDATA%\ThirdHand\last-run.log`.

The current Windows launcher is `2026.09.18-3`. The desktop shortcut points
directly to the CMD runner. The earlier PowerShell runner
`Start-ThirdHand.ps1` is retired and should not be used.

After installation on the current Ubuntu host:

- desktop shortcut: `/home/nieqingcao/桌面/Start ThirdHand.desktop`.

## CAN preparation and recovery

Before checking the five services, `manual-control` checks `can0` for `UP`,
bitrate `1000000`, and `restart-ms 100`.

- A correctly configured interface is kept unchanged.
- A fresh DOWN or incorrectly configured interface is reconfigured with
  `down -> type can bitrate 1000000 restart-ms 100 -> up`.
- If Robot Service was already running while CAN was unhealthy, or existing
  counters show transmitted packets with zero received packets, the launcher
  uses the full recovery proven during the 2026-09-20 incident: stop the
  `manual-control` profile, rebuild `can0`, and restore the profile.
- A missing adapter, sudo failure, or failed verification is reported as a CAN
  failure. The other five service checks still run.

CAN preparation never sends the Robot Service `{ "cmd": "connect" }` command.
The operator still decides whether to connect or disconnect Startouch SDK from
the 9983 page.

## Services checked

The current `manual-control` profile checks these five explicitly configured
services in order:

| Service | Address | One-click behavior |
|---|---|---|
| Robot Service | `127.0.0.1:3000` | Keep when listening; otherwise start it. Restart the profile only during level-two CAN recovery. Never connect Startouch SDK automatically. |
| Speech Service | `127.0.0.1:3004` | Keep when listening; otherwise start it. |
| Vision Service | `127.0.0.1:3100` | Keep when listening; otherwise start it. |
| Bottle-pick runtime | `127.0.0.1:8766` | Keep when listening; otherwise start it. |
| Web Gateway | `192.168.58.68:9983` | Keep when listening; otherwise start it. |

Port `3200` is retired and is not part of this workflow. The tool checks CAN,
service ports, and lightweight service identity. It does not repair models,
cameras, dependencies, or application-level debugging failures.

## New Windows user setup

The Windows PC must be on a network that can reach `192.168.58.68`, have the
Windows OpenSSH client, and use its own SSH key. No Ubuntu password is stored by
the shortcut.

### 1. Create a key if this PC does not already have one

Open PowerShell:

```powershell
ssh-keygen -t ed25519
Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub"
```

Send only the displayed public key (`.pub`) to the Ubuntu administrator. Never
send `id_ed25519`, which is the private key. The administrator adds the public
key to the `nieqingcao` account.

### 2. Verify key-based access

```powershell
ssh -o BatchMode=yes nieqingcao@192.168.58.68 true
```

The command should finish without requesting a password. If it fails, fix SSH
access before installing the shortcut.

### 3. Download and run the installer

```powershell
scp nieqingcao@192.168.58.68:/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA/tools/launcher/windows/install-thirdhand-shortcut.ps1 "$env:USERPROFILE\Downloads\"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\install-thirdhand-shortcut.ps1"
```

This creates `Start ThirdHand` on the Windows desktop.

### 4. Daily use

Double-click `Start ThirdHand`:

1. the shortcut connects to Ubuntu using this PC's SSH key;
2. `can0` is kept, prepared, or recovered as described above;
3. existing healthy services are kept and missing services are started sequentially;
4. when all five are ready, the result stays visible until the developer presses
   Enter; Windows then asks Explorer to open `http://192.168.58.68:9983/` and
   closes the terminal window;
5. if any service fails, the window stays open with the reason and log paths;
6. connect the robot manually from the 9983 web page when robot control is
   required.

## New Ubuntu user setup

From the repository root:

```bash
cd /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA
tools/launcher/ubuntu/install-ubuntu-shortcut.sh
```

This creates `Start ThirdHand` on the Ubuntu desktop. Double-clicking it opens a
terminal, runs the one-shot check, and displays the result. The Ubuntu shortcut
does not open a browser and waits for Enter before closing.

The same operation can always be run directly:

```bash
cd /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA
./thirdhand ensure --profile manual-control
```

## Result meanings

- `can: ready (kept)`: `can0` was already UP with the configured bitrate and
  restart policy; no CAN or service reset occurred.
- `can: ready (reconfigured)`: level-one recovery configured and started
  `can0` without restarting an already healthy profile.
- `can: ready (full_recovery)`: the stale/one-way condition selected level-two
  recovery; the profile was stopped, CAN rebuilt, and services restored.
- `can: failed`: CAN could not be prepared. Read the printed `reason` and
  `detail`; the five service checks still continue.
- `ready (kept)`: the expected service was already listening and was not
  restarted.
- `ready (started)`: the port was missing and this invocation started it.
- `blocked_external`: the port responded but did not match the configured
  lightweight service identity; no process was killed.
- `failed (start_failed)`: this invocation started the service but it did not
  listen before its timeout or exited. Only that newly started failed process is
  cleaned up; other successful services stay running.

Logs are stored in `runtime/logs/<service>.stdout.log` and
`runtime/logs/<service>.stderr.log`.

## Windows shortcut troubleshooting

If the Windows window closes before reaching the Enter prompt:

1. do not delete the shortcut immediately;
2. inspect `%LOCALAPPDATA%\ThirdHand\last-run.log` to see whether the CMD runner
   started and which stage it reached;
3. confirm that the window title or first line shows
   `ThirdHand One-Click Launcher 2026.09.18-3`;
4. reinstall the current shortcut from the Ubuntu repository if the version is
   older:

```powershell
scp nieqingcao@192.168.58.68:/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA/tools/launcher/windows/install-thirdhand-shortcut.ps1 "$env:USERPROFILE\Downloads\"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\install-thirdhand-shortcut.ps1"
```

On success, the CMD window waits at `Press Enter to open ...`. Pressing Enter
opens the 9983 page and closes only the one-click window; the Ubuntu services
continue running.

## Deliberate boundaries

The one-click start does not:

- restart an already listening expected service while CAN is healthy;
- run continuously or start at Ubuntu boot;
- restart a service that a developer stops later;
- connect the robot, enable motors, home, or move the arm;
- stop or kill an unknown process occupying a configured port;
- repair ASR models, Vision models, cameras, dependencies, or internal state;
- provide a one-click stop-all operation.

Future backend services must be added explicitly to the runtime profile with a
command, address, timeout, and lightweight probe. Desktop launchers do not scan
for ports or create frontend service entries automatically.
