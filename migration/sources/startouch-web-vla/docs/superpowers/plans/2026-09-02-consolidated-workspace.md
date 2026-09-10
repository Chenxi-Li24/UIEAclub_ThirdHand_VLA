# ThirdHand VLA Consolidated Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Ubuntu 主机上停止当前 ThirdHand 项目服务，并创建一个保留原项目边界、排除解释器环境、包含复现资料且经过校验的统一收纳目录。

**Architecture:** 新目录是原项目的只复制快照，各 Git 仓库和源码树保持独立。运行态、环境、硬件和复制校验信息单独写入 `environment/` 与 `manifests/`，为后续规范化合并提供可靠输入。

**Tech Stack:** Ubuntu 20.04 shell、OpenSSH、systemd user services、rsync、Git、Conda、pip、Node.js/npm、SHA-256。

**Spec:** `docs/superpowers/specs/2026-09-02-consolidated-workspace-design.md`

## Global Constraints

- 目标路径固定为 `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902`。
- 原目录只读使用；不得移动、删除、清理、还原、切换分支或自动提交原项目。
- 保留 Git 历史和未提交文件；链接工作树的失效 `.git` 指针不得复制。
- 排除 Conda 环境、`.venv`、`venv`、`.conda-execution`、`node_modules` 和通用缓存。
- 保留模型、标定数据、SDK、本地动态库和必要构建产物。
- 不启动机械臂，不发送 CAN 控制命令，不重启已停止的项目服务。
- 私密 `.env` 仅保存在 Ubuntu 本地收纳目录中，权限设为 `0600`，统一目录不推送 GitHub。

---

### Task 1: Capture Runtime State and Stop Project Services

**Files:**
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/manifests/running-processes-before.txt`
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/manifests/running-processes-after.txt`
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/manifests/stopped-services.txt`

**Interfaces:**
- Consumes: Ubuntu process table, `/proc/<pid>/cwd`, TCP listeners and user service `thirdhand-voice-robot-3000-v2.service`.
- Produces: a stopped, documented project runtime with ports `3000`, `3003`, `3004`, `9983` and `8085` no longer listening.

- [ ] **Step 1: Recheck destination and storage**

Run:

```bash
test ! -e /home/nieqingcao/ThirdHand_VLA_consolidated_20260902
df -Pk /home/nieqingcao
```

Expected: the first command exits `0`; available space is comfortably above the source estimate.

- [ ] **Step 2: Create only the manifest staging directory**

Run:

```bash
install -d -m 0755 /home/nieqingcao/ThirdHand_VLA_consolidated_20260902/manifests
```

Expected: the directory exists and is owned by `nieqingcao`.

- [ ] **Step 3: Record listeners, commands, parents and working directories**

Run:

```bash
snapshot=/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/manifests/running-processes-before.txt
{
  date -Is
  ss -ltnp
  ps -eo pid,ppid,lstart,args
  systemctl --user --no-pager status thirdhand-voice-robot-3000-v2.service || true
  for port in 3000 3003 3004 9983 8085; do
    echo "=== port $port ==="
    line="$(ss -H -ltnp "sport = :$port" || true)"
    printf '%s\n' "$line"
    printf '%s\n' "$line" | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u |
      while read -r pid; do
        test -n "$pid" || continue
        printf 'PID=%s CWD=%s CMD=' "$pid" "$(readlink -f "/proc/$pid/cwd")"
        tr '\0' ' ' <"/proc/$pid/cmdline"
        echo
      done
  done
} >"$snapshot" 2>&1
```

Expected: records identify:

```text
3000  thirdhand-voice-robot-3000-v2.service, cwd /home/nieqingcao/TH_new_asr_0820/app/server
3003  voice_bridge.py, cwd below /home/nieqingcao/th0814
3004  voice_bridge.py, cwd /home/nieqingcao/TH_new_asr_0820/voice
9983  proxy.js, cwd /home/nieqingcao/TH_new_asr_0820/app/server
8085  ros2_depth_bridge.py, cwd /home/nieqingcao/ros2_ws
```

- [ ] **Step 4: Stop only validated project services**

Run:

```bash
systemctl --user stop thirdhand-voice-robot-3000-v2.service
kill -TERM 155743 1631375 2589928 2654759
```

Before sending `SIGTERM`, re-read each PID's command and cwd; if a PID changed or no longer matches the recorded project command, omit it and resolve the current listener PID instead. Wait up to 15 seconds. Do not kill interactive shells or unrelated processes.

Expected: the systemd unit is inactive and the four standalone processes exit normally.

- [ ] **Step 5: Verify shutdown**

Run:

```bash
systemctl --user is-active thirdhand-voice-robot-3000-v2.service || true
ss -ltnp | grep -E ':(3000|3003|3004|9983|8085)\b' || true
```

Expected: unit reports `inactive`; no matching project listener remains. Save the commands and output in `running-processes-after.txt` and the stopped identities in `stopped-services.txt`.

### Task 2: Copy Source Trees While Preserving Boundaries

**Files:**
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/projects/UIEAclub_ThirdHand_VLA/`
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/projects/th0814/`
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/projects/TH_new_asr_0820/`
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/projects/TH-Fanxy/`
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/projects/auxiliary/`
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/sdk/`
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/calibration/`

**Interfaces:**
- Consumes: the source mappings defined in the approved spec.
- Produces: independent copied source trees without runtime environments or cache directories.

- [ ] **Step 1: Create destination structure**

Run:

```bash
install -d -m 0755 \
  /home/nieqingcao/ThirdHand_VLA_consolidated_20260902/projects/auxiliary \
  /home/nieqingcao/ThirdHand_VLA_consolidated_20260902/sdk/camera \
  /home/nieqingcao/ThirdHand_VLA_consolidated_20260902/calibration \
  /home/nieqingcao/ThirdHand_VLA_consolidated_20260902/environment/{conda-environments,python-packages,system-packages,node-runtime} \
  /home/nieqingcao/ThirdHand_VLA_consolidated_20260902/manifests/git-status
```

- [ ] **Step 2: Define and test the common rsync exclusions**

Use these exact directory exclusions for every source:

```text
.venv/
venv/
.conda-execution/
node_modules/
.cache/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
```

Also exclude `*.pyc`, editor metadata, ordinary `*.log` files and the source path `ThirdHand-XVisio-handeye-web/.git`. Run one `rsync -aHn --stats` dry run per source and save the aggregate stats in `manifests/rsync-dry-run.txt`.

Expected: no target path escapes the new directory and excluded environment trees are absent from the dry-run file list.

- [ ] **Step 3: Copy core projects**

Run `rsync -aH --info=progress2` with the tested exclusions for these exact mappings:

```text
/home/nieqingcao/arm/UIEAclub_ThirdHand_VLA/ -> projects/UIEAclub_ThirdHand_VLA/
/home/nieqingcao/th0814/                    -> projects/th0814/
/home/nieqingcao/TH_new_asr_0820/           -> projects/TH_new_asr_0820/
/home/nieqingcao/TH-Fanxy/                  -> projects/TH-Fanxy/
```

Expected: all four targets exist; their source directories are unchanged.

- [ ] **Step 4: Copy auxiliary projects**

Run the same copy policy for:

```text
/home/nieqingcao/thirdhand-policy/                         -> projects/auxiliary/thirdhand-policy/
/home/nieqingcao/thirdhand-policy-integration-20260817-01/ -> projects/auxiliary/thirdhand-policy-integration-20260817-01/
/home/nieqingcao/TH-Fanxy-deliverables/                    -> projects/auxiliary/TH-Fanxy-deliverables/
```

Expected: all existing auxiliary roots have independent destination directories.

- [ ] **Step 5: Copy SDK, camera, ROS and calibration inputs**

Run the same copy policy for:

```text
/home/nieqingcao/arm/startouch_sdk/     -> sdk/startouch_sdk/
/home/nieqingcao/FastUMI_Hardware_SDK/  -> sdk/camera/FastUMI_Hardware_SDK/
/home/nieqingcao/FastUMI_Camera/        -> sdk/camera/FastUMI_Camera/
/home/nieqingcao/ros2_ws/               -> sdk/camera/ros2_ws/
/home/nieqingcao/calibration/           -> calibration/current/
```

Expected: Startouch control SDK, camera interfaces, ROS bridge and calibration results are all present.

- [ ] **Step 6: Protect copied private configuration**

Run:

```bash
find /home/nieqingcao/ThirdHand_VLA_consolidated_20260902 -type f \
  \( -name '.env' -o -name '.env.*' -o -name '*secret*' -o -name '*credential*' \) \
  -exec chmod 0600 {} +
```

Expected: matching files are owner-readable/writable only.

### Task 3: Export Reproducible Environment Metadata

**Files:**
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/environment/conda-environments/*.yml`
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/environment/conda-environments/*.explicit.txt`
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/environment/python-packages/*.pip-freeze.txt`
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/environment/system-packages/*.txt`
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/environment/node-runtime/versions.txt`
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/environment/hardware-and-ports.md`

**Interfaces:**
- Consumes: installed Conda environments, project `.venv` interpreters, OS tools and device state.
- Produces: portable and exact environment records without copying environment binaries.

- [ ] **Step 1: Export the three known Conda environments**

Run:

```bash
conda=/home/nieqingcao/miniconda3/bin/conda
out=/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/environment
for env_name in LumosTouch voice-bridge thirdhand-groundedsam2; do
  "$conda" env export -n "$env_name" --from-history >"$out/conda-environments/$env_name.yml"
  "$conda" list -n "$env_name" --explicit >"$out/conda-environments/$env_name.explicit.txt"
  "$conda" run -n "$env_name" python -m pip freeze >"$out/python-packages/$env_name.pip-freeze.txt"
done
```

Write each output to the corresponding environment file. If an environment is absent, record that fact in `manifests/environment-errors.txt` and continue.

- [ ] **Step 2: Export excluded project virtual environments**

Run:

```bash
out=/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/environment/python-packages
find /home/nieqingcao/th0814 /home/nieqingcao/TH_new_asr_0820 /home/nieqingcao/TH-Fanxy \
  -type f -path '*/.venv/bin/python' -print0 |
  while IFS= read -r -d '' python_bin; do
    name="$(printf '%s' "${python_bin#/home/nieqingcao/}" | tr '/ ' '__')"
    { "$python_bin" --version; "$python_bin" -m pip freeze; } >"$out/$name.pip-freeze.txt" 2>&1 || true
  done
```

Expected: the known `TH_new_asr_0820`, `VA/Reuse`, and hand-eye web virtual environments are represented when readable.

- [ ] **Step 3: Record OS and system packages**

Capture `lsb_release -a`, `uname -a`, `lscpu`, `dpkg-query -W`, `nvidia-smi` and CUDA compiler version when available. Commands not installed must be recorded as unavailable instead of aborting the export.

- [ ] **Step 4: Record Node.js/npm runtimes**

Capture the default `node --version`, `npm --version`, executable paths, and the explicitly used Node 24 runtime at `/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node`.

- [ ] **Step 5: Record hardware interfaces and ports**

Run the following commands and append their labeled output to `environment/hardware-and-ports.md`:

```bash
ip -details -statistics link show can0
lsusb
find /dev -maxdepth 1 \( -name 'video*' -o -name 'ttyUSB*' -o -name 'ttyACM*' \) -ls
ss -ltnp | grep -E ':(3000|3003|3004|9983|8085)\b' || true
```

The report must list `/home/nieqingcao/arm/startouch_sdk`, both FastUMI camera roots, the port-to-service map from Task 1, and this exact warning: `软件停止依赖软件与通信链路，不能替代独立硬件急停。`

### Task 4: Build Manifests and Operator Documentation

**Files:**
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/manifests/source-paths.md`
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/manifests/git-status/*.txt`
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/manifests/exclusions.md`
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/README.md`

**Interfaces:**
- Consumes: copied trees and exported runtime metadata.
- Produces: an operator-readable inventory and future normalization input.

- [ ] **Step 1: Write the source mapping manifest**

Write one table row for each of the twelve source mappings in Task 2. Populate source and destination sizes with `du -sh`, use `date -Is` for the copy timestamp, and set the Git column to `preserved`, `not-a-repository`, or `linked-worktree-snapshot`.

- [ ] **Step 2: Capture Git metadata from original sources**

Run this discovery against the original source roots, excluding environment and dependency trees:

```bash
find /home/nieqingcao/arm/UIEAclub_ThirdHand_VLA /home/nieqingcao/th0814 \
     /home/nieqingcao/TH_new_asr_0820 /home/nieqingcao/TH-Fanxy \
  \( -name .venv -o -name venv -o -name .conda-execution -o -name node_modules -o -name .cache \) -prune -o \
  -name .git -print
```

For each result, use the parent directory as `SOURCE` and record:

```bash
git -C SOURCE status --short --branch
git -C SOURCE rev-parse HEAD
git -C SOURCE branch --show-current
git -C SOURCE remote -v
```

Expected: `ThirdHand-XVisio-handeye-web` is documented as a linked-worktree snapshot and its copied directory has no `.git` pointer.

- [ ] **Step 3: Write exclusions and privacy notes**

List every rsync exclusion, explain why environments are represented by exports, and mark copied `.env` files as local-only private configuration.

- [ ] **Step 4: Write the top-level README**

Document the directory map, main project capabilities, runtime entry points, Ubuntu 20.04 source platform, Ubuntu 22.04 rebuild guidance, environment creation order, Node install requirements, CAN setup, camera/calibration locations, port map, current disabled safety gates, and the boundary between software stop and hardware emergency stop.

### Task 5: Verify the Consolidated Workspace

**Files:**
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/manifests/copied-files.sha256`
- Create: `/home/nieqingcao/ThirdHand_VLA_consolidated_20260902/manifests/verification.txt`

**Interfaces:**
- Consumes: completed consolidated directory.
- Produces: evidence that the copy is internally complete, respects exclusions and did not restart project services.

- [ ] **Step 1: Scan for excluded directories**

Run `find` for `.venv`, `venv`, `.conda-execution`, `node_modules`, `.cache`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, and `.ruff_cache` below the destination.

Expected: no result. Record output and exit interpretation in `verification.txt`.

- [ ] **Step 2: Check required files and trees**

Verify all mappings from Task 2 exist, the top-level README and environment exports are nonempty, copied Git repositories answer `git status`, and the hand-eye snapshot lacks an invalid `.git` pointer.

- [ ] **Step 3: Generate checksums**

From the destination root, run a null-safe sorted file traversal and `sha256sum` for every file except `manifests/copied-files.sha256`; save relative paths in `copied-files.sha256`.

- [ ] **Step 4: Recheck services and hardware non-interference**

Run:

```bash
ss -ltnp | grep -E ':(3000|3003|3004|9983|8085)\b' || true
systemctl --user is-active thirdhand-voice-robot-3000-v2.service || true
```

Expected: no project listeners and the unit remains inactive. Do not transmit on `can0`.

- [ ] **Step 5: Record final size and source integrity evidence**

Record destination `du -sh`, filesystem free space, final file count, checksum count, source root existence and Git status after copying. Compare the pre-copy and post-copy source Git summaries; differences require investigation but must not be automatically reverted.

- [ ] **Step 6: Commit the local execution plan only**

On Windows, commit this plan document to `UIEAclub_ThirdHand_VLA`. Do not initialize or commit the Ubuntu consolidated directory.

```bash
git add docs/superpowers/plans/2026-09-02-consolidated-workspace.md
git commit -m "docs: plan Ubuntu workspace consolidation"
```
