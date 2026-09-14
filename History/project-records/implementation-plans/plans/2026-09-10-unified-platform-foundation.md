# Unified Platform Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the canonical repository layout, local asset boundary, versioned contracts, native process supervisor, Skill discovery, and one-command simulated lifecycle that every later robot, vision, speech, orchestration, and policy migration will build upon.

**Architecture:** Keep Node.js 24 as the control-plane runtime for lifecycle and Skill discovery, Python 3.10+ for asset verification and later hardware/model services, and JSON Schema as the cross-language contract. This phase does not move live hardware implementations or replace the accepted services; it creates a testable foundation and a simulation profile while all current Ubuntu entry points remain available.

**Tech Stack:** Bash, Node.js 24, npm, Python 3.10+, pytest, Node `node:test`, JSON Schema Draft 2020-12, Ajv 8

**Spec:** `docs/superpowers/specs/2026-09-10-unified-platform-skills-design.md`

**Ubuntu Target:** `/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA`, an independent clone of the user's GitHub fork. Existing projects are read-only migration sources and are never modified in place.

## Global Constraints

- `Oliveirah007/UIEAclub_ThirdHand_VLA` is the only future canonical repository.
- Create the unified project only at `/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA` as an independent clone, with `origin` set to `Oliveirah007/UIEAclub_ThirdHand_VLA` and `upstream` set to `Chenxi-Li24/UIEAclub_ThirdHand_VLA`.
- Treat every existing Ubuntu project as read-only. Copy required files into the new checkout; do not move, edit, delete, clean, or replace source files, and do not create symlinks from the new project back to old directories.
- Copy required SDK, model, vendor, and runtime payloads into the new checkout's ignored `local/` tree. Record provenance, size, license status, and SHA-256 before considering the copy complete.
- Keep all currently running services untouched. Foundation and migration validation use non-conflicting alternate ports until the user separately approves production cutover.
- Ubuntu 20.04 is the current real-hardware environment; Ubuntu 22.04 is a compatibility target until matching SDK binaries pass hardware acceptance.
- Do not use systemd or start services at Ubuntu boot; `./thirdhand start` is the only normal startup path.
- Port 9983 is the user-facing gateway; ports 3000, 3100, and 3004 listen on `127.0.0.1` by default.
- Starting Robot Service must never home, jog, enable motion, or issue a gripper target automatically.
- Physical motion always requires a version-bound plan and one-task user authorization.
- Supervisor failure locks automated motion; interrupted tasks are never recovered automatically.
- Startouch SDK, model weights, FunASR checkout, Python/Node runtimes, logs, captures, and task results live under `local/` or `runtime/` and are not tracked by public Git.
- Public Git tracks asset provenance, versions, license state, sizes, hashes, schemas, and import/verification tools.
- Formal source must not contain `/home/nieqingcao/...` runtime paths or import from `archive/`.
- Do not delete or edit the accepted Ubuntu source directories during this phase.
- Hardware tests remain skipped unless the user gives explicit live-hardware approval for that run.

## Scope Decomposition

The approved specification spans independent subsystems and must not be executed as one unreviewable patch. This is the first self-contained plan. After it passes, write and execute separate plans in this order:

1. Startouch Robot Service and retained 3000 maintenance console migration.
2. XVisio Vision Service, stable target registry, and Supervisor migration.
3. `Thirdhand_language` 9983 Web and 3004 Speech migration.
4. LLM Orchestrator, Task Engine, plan authorization, and gateway integration.
5. Vision and pick-and-place Skill packaging.
6. VLA/ACT/DP policy boundaries, archive cutover, Ubuntu 20.04 acceptance, and Ubuntu 22.04 compatibility validation.

Each later plan must consume the contracts and lifecycle interfaces produced here without redefining them.

## File Structure For This Phase

```text
thirdhand                                      # POSIX entry point
package.json                                   # private Node control-plane workspace
.gitignore                                     # local/runtime/archive data boundaries
apps/launcher/
  package.json                                 # launcher package metadata
  src/cli.js                                   # start/stop/status/doctor command dispatch
  src/service-supervisor.js                    # process ownership and shutdown order
  src/state-store.js                           # atomic runtime/run/state.json access
platform/contracts/
  package.json                                 # Ajv contract package
  src/validator.js                             # schema loading and validation API
  schemas/service-health.schema.json
  schemas/skill-manifest.schema.json
  schemas/target-ref.schema.json
  schemas/task-plan.schema.json
  schemas/task-authorization.schema.json
  schemas/skill-result.schema.json
platform/skill_registry/
  package.json
  src/registry.js                              # discover, validate, and resolve Skills
  src/resource-status.js                       # dependency availability evaluation
configs/runtime/default.json                   # final port ownership, initially disabled
configs/runtime/simulation.json                # safe fake workers for lifecycle tests
configs/assets/manifest.example.json           # non-secret asset declaration example
skills/.../manifest.yaml                       # formal Skill metadata, unavailable until migrated
tools/assets/verify_assets.py                  # size/hash/platform verification
tools/assets/import_assets.py                  # explicit local asset copy tool
tools/fixtures/fake_service.js                 # deterministic process fixture
tests/unit/platform/                           # Python layout and asset tests
tests/node/contracts/                          # JSON contract tests
tests/node/launcher/                           # lifecycle tests
tests/node/skill_registry/                     # discovery and availability tests
tests/integration/test_simulated_lifecycle.py  # `thirdhand` end-to-end smoke test
docs/DIRECTORY_MAP.md                          # detailed ownership and tracked-data rules
docs/OPERATIONS.md                             # setup-assets/start/status/stop behavior
docs/migration/FOUNDATION_BASELINE.md           # source and rollback checkpoint
```

---

### Task 1: Freeze The Migration Baseline And Add Repository Boundaries

**Files:**
- Create: `docs/migration/FOUNDATION_BASELINE.md`
- Create: `docs/DIRECTORY_MAP.md`
- Create: `tests/unit/platform/test_repository_layout.py`
- Modify: `.gitignore`
- Create: `apps/.gitkeep`
- Create: `platform/.gitkeep`
- Create: `services/.gitkeep`
- Create: `skills/.gitkeep`
- Create: `drivers/.gitkeep`
- Create: `local/README.md`
- Create: `runtime/README.md`
- Create: `archive/README.md`

**Interfaces:**
- Consumes: Approved directory names and Git tracking rules from the design specification.
- Produces: `REQUIRED_TOP_LEVEL_DIRS`, a repository layout enforced by tests; ignored `local/**`, `runtime/**`, and archive runtime data; documented rollback baseline.

- [ ] **Step 1: Create the isolated Ubuntu checkout and record every source state**

On Ubuntu, first verify that the exact destination does not already contain unrelated data. Then create the parent directory, clone the user's fork into the approved destination, add the upstream remote, and create the implementation branch:

```bash
test ! -e /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA
mkdir -p /home/nieqingcao/ThirdHand
git clone https://github.com/Oliveirah007/UIEAclub_ThirdHand_VLA.git /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA
cd /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA
git remote add upstream https://github.com/Chenxi-Li24/UIEAclub_ThirdHand_VLA.git
git switch -c refactor/unified-platform-foundation
git status --short --branch
git rev-parse HEAD
git remote -v
```

Expected: the new independent checkout is on `refactor/unified-platform-foundation`; `origin` is the user's fork and `upstream` is the source repository. Record the status, current commit, and relevant inventory of every old source directory in the baseline document without changing those directories. If the destination already exists, stop and inspect it instead of deleting, overwriting, or recloning it.

- [ ] **Step 2: Write the failing repository-layout test**

Create `tests/unit/platform/test_repository_layout.py`:

```python
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]
REQUIRED_TOP_LEVEL_DIRS = {
    "apps", "platform", "services", "skills", "drivers",
    "configs", "assets", "local", "runtime", "tools", "tests",
    "archive", "docs",
}


def test_required_top_level_directories_exist():
    missing = sorted(name for name in REQUIRED_TOP_LEVEL_DIRS if not (ROOT / name).is_dir())
    assert missing == []


def test_local_and_runtime_payloads_are_ignored():
    probes = ["local/sdk/startouch/libstartouch.so", "runtime/logs/service.log"]
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=ROOT,
        input="\n".join(probes) + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert set(result.stdout.splitlines()) == set(probes)
```

- [ ] **Step 3: Run the test and confirm the missing directories fail**

Run:

```bash
python -m pytest tests/unit/platform/test_repository_layout.py -v
```

Expected: `test_required_top_level_directories_exist` fails and names the new top-level directories that do not yet exist.

- [ ] **Step 4: Add the directory markers, detailed boundary documentation, and ignore rules**

Append these rules to `.gitignore`:

```gitignore
# Unified local delivery assets: present on Ubuntu, never tracked publicly
/local/**
!/local/README.md

# Unified mutable runtime state
/runtime/**
!/runtime/README.md

# Archive may keep reviewed first-party source, but not copied runtime payloads
/archive/**/node_modules/
/archive/**/.venv/
/archive/**/build/
/archive/**/dist/
/archive/**/models/
/archive/**/logs/
```

Create every listed directory and marker. `local/README.md` must state that SDK, models, vendor sources, and runtimes are imported locally and verified through manifests. `runtime/README.md` must enumerate `run/`, `logs/`, `captures/`, `artifacts/`, and `cache/`. `archive/README.md` must prohibit formal imports and define the required provenance file for each archived component.

Write `docs/migration/FOUNDATION_BASELINE.md` with the branch, source commit, Windows checkout status, Ubuntu canonical paths, accepted live entry points, and the rule that this phase does not modify them. Write `docs/DIRECTORY_MAP.md` from Section 5 of the specification, adding columns for owner, inputs, outputs, lifecycle, Git tracking, and migration source.

- [ ] **Step 5: Run layout tests and Git whitespace checks**

Run:

```bash
python -m pytest tests/unit/platform/test_repository_layout.py -v
git diff --check
```

Expected: both layout tests pass and `git diff --check` produces no output.

- [ ] **Step 6: Commit the repository boundary**

```bash
git add .gitignore apps platform services skills drivers local runtime archive docs tests/unit/platform
git commit -m "chore: establish unified repository boundaries"
```

---

### Task 2: Add Explicit Local Asset Manifests And Verification

**Files:**
- Create: `configs/assets/manifest.example.json`
- Create: `tools/assets/__init__.py`
- Create: `tools/assets/verify_assets.py`
- Create: `tools/assets/import_assets.py`
- Create: `tests/unit/platform/test_asset_verifier.py`
- Modify: `local/README.md`

**Interfaces:**
- Consumes: Project root and a JSON manifest containing `id`, `relativePath`, `kind`, `required`, `sha256`, `sizeBytes`, `licenseStatus`, and optional compatibility constraints.
- Produces: `verify_manifest(project_root: Path, manifest_path: Path) -> dict`; CLI exit 0 only when all required assets pass; explicit import that never downloads implicitly.

- [ ] **Step 1: Write failing verifier tests**

Create `tests/unit/platform/test_asset_verifier.py`:

```python
import hashlib
import json
from pathlib import Path

from tools.assets.verify_assets import verify_manifest


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_verify_manifest_accepts_matching_local_asset(tmp_path: Path):
    payload = b"verified-model"
    asset = tmp_path / "local/models/asr/medium/model.bin"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(payload)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"assets": [{
        "id": "asr.medium", "kind": "model", "required": True,
        "relativePath": "local/models/asr/medium/model.bin",
        "sha256": _sha(payload), "sizeBytes": len(payload),
        "licenseStatus": "recorded",
    }]}), encoding="utf-8")

    report = verify_manifest(tmp_path, manifest)

    assert report["ok"] is True
    assert report["assets"][0]["status"] == "ready"


def test_verify_manifest_rejects_hash_mismatch(tmp_path: Path):
    asset = tmp_path / "local/sdk/startouch/libstartouch.so"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"unexpected")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"assets": [{
        "id": "startouch.sdk", "kind": "sdk", "required": True,
        "relativePath": "local/sdk/startouch/libstartouch.so",
        "sha256": "0" * 64, "sizeBytes": 10,
        "licenseStatus": "unknown",
    }]}), encoding="utf-8")

    report = verify_manifest(tmp_path, manifest)

    assert report["ok"] is False
    assert report["assets"][0]["status"] == "hash_mismatch"
```

- [ ] **Step 2: Run the tests and verify import failure**

Run:

```bash
python -m pytest tests/unit/platform/test_asset_verifier.py -v
```

Expected: collection fails because `tools.assets.verify_assets` does not exist.

- [ ] **Step 3: Implement the manifest verifier**

Implement this public API in `tools/assets/verify_assets.py`:

```python
def verify_manifest(project_root: Path, manifest_path: Path) -> dict:
    """Return {ok, platform, assets}; never modify or download assets."""
```

For each asset, resolve `relativePath` under `project_root` and reject path traversal. Return one of `ready`, `missing`, `size_mismatch`, `hash_mismatch`, `license_unrecorded`, or `incompatible_platform`. Include actual size/hash when available. The CLI accepts `--project-root`, `--manifest`, and `--json`; non-JSON mode prints one concise line per asset.

Create `configs/assets/manifest.example.json` with entries for `startouch.sdk`, `xvisio.sdk`, the three ASR models, `funasr.source`, `runtime.python`, `runtime.node`, and optional `policy.vla`, `policy.act`, `policy.dp`. Use empty hashes only for optional unavailable policy assets and mark them `required: false`; do not invent hashes for real Ubuntu files.

- [ ] **Step 4: Implement explicit local import with collision protection**

In `tools/assets/import_assets.py`, provide:

```python
def import_asset(source: Path, destination: Path, *, expected_sha256: str) -> dict:
    """Copy one file/tree into local/ after validation; never overwrite a differing destination."""
```

Require the destination to resolve under `<project_root>/local`. Copy into a temporary sibling, verify the result, then rename atomically. If a destination already exists with another hash, return `destination_conflict` without deleting it. Do not implement network downloads.

- [ ] **Step 5: Run focused and existing Python tests**

Run:

```bash
python -m pytest tests/unit/platform/test_asset_verifier.py -v
python -m pytest tests/test_build_backend.py -v
git diff --check
```

Expected: all tests pass; no whitespace errors.

- [ ] **Step 6: Commit asset management**

```bash
git add configs/assets local/README.md tools/assets tests/unit/platform/test_asset_verifier.py
git commit -m "feat: add local asset verification boundary"
```

---

### Task 3: Define Versioned Cross-Language Contracts

**Files:**
- Create: `package.json`
- Create: `package-lock.json`
- Create: `platform/contracts/package.json`
- Create: `platform/contracts/src/validator.js`
- Create: `platform/contracts/schemas/service-health.schema.json`
- Create: `platform/contracts/schemas/skill-manifest.schema.json`
- Create: `platform/contracts/schemas/target-ref.schema.json`
- Create: `platform/contracts/schemas/task-plan.schema.json`
- Create: `platform/contracts/schemas/task-authorization.schema.json`
- Create: `platform/contracts/schemas/skill-result.schema.json`
- Create: `tests/node/contracts/contracts.test.js`

**Interfaces:**
- Consumes: Plain JSON values and schema IDs.
- Produces: `createContractValidator() -> { validate(schemaId, value), schemas }`; validation returns `{ ok: boolean, errors: array }` and never mutates input.

- [ ] **Step 1: Add the private workspace manifest and install Ajv**

Create root `package.json`:

```json
{
  "name": "thirdhand-platform",
  "private": true,
  "engines": {"node": ">=24 <25"},
  "workspaces": ["apps/*", "platform/*", "services/robot", "skills/*/*"],
  "scripts": {
    "test:contracts": "node --test tests/node/contracts/*.test.js"
  },
  "devDependencies": {"ajv": "8.17.1", "ajv-formats": "3.0.1", "yaml": "2.8.1"}
}
```

Run `npm install --package-lock-only` and commit the generated lockfile. Do not copy a `node_modules` directory into Git.

- [ ] **Step 2: Write the failing contract test**

Create `tests/node/contracts/contracts.test.js`:

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');
const { createContractValidator } = require('../../../platform/contracts/src/validator');

test('task authorization is bound to plan revision and target', () => {
  const contracts = createContractValidator();
  const result = contracts.validate('thirdhand.task-authorization.v1', {
    schema: 'thirdhand.task-authorization.v1',
    authorizationId: 'auth-1', taskId: 'task-1', planId: 'plan-1',
    planRevision: 2, targetRef: 'target-7', expiresAt: '2026-09-10T13:00:00+08:00',
  });
  assert.equal(result.ok, true, JSON.stringify(result.errors));
});

test('physical plan without risks is rejected', () => {
  const contracts = createContractValidator();
  const result = contracts.validate('thirdhand.task-plan.v1', {
    schema: 'thirdhand.task-plan.v1', taskId: 'task-1', planId: 'plan-1',
    revision: 1, targetRef: 'target-7', risk: 'physical-motion', steps: [], risks: [],
  });
  assert.equal(result.ok, false);
});
```

- [ ] **Step 3: Run the test and confirm the missing validator failure**

Run:

```bash
npm run test:contracts
```

Expected: FAIL with `Cannot find module .../platform/contracts/src/validator`.

- [ ] **Step 4: Create strict schemas and the validator**

All schemas use Draft 2020-12, set `additionalProperties: false`, and carry stable `$id` values matching their `schema` constant. Define these minimum invariants:

- `target-ref`: stable ID, class, confidence 0..1, last-seen timestamp, positive pose revision.
- `task-plan`: non-empty steps; `physical-motion` requires at least one risk; plan ID/revision/target binding.
- `task-authorization`: authorization ID, task ID, plan ID/revision, target, expiry.
- `skill-result`: task/trace/skill IDs, `completed|interrupted|failed`, structured reason.
- `service-health`: service ID, `ready|degraded|unavailable`, version, dependencies, timestamp.
- `skill-manifest`: ID/version/summary/risk/lifecycle/runtime/operations/requirements/schemas/entrypoint/healthcheck.

Implement `platform/contracts/src/validator.js` to load only files in `schemas/`, register formats, and return normalized Ajv error objects `{path, keyword, message}`.

- [ ] **Step 5: Run contract tests and validate schema files parse**

Run:

```bash
npm run test:contracts
node -e "const fs=require('node:fs');for(const f of fs.readdirSync('platform/contracts/schemas'))JSON.parse(fs.readFileSync('platform/contracts/schemas/'+f));console.log('schemas ok')"
git diff --check
```

Expected: contract tests pass and output includes `schemas ok`.

- [ ] **Step 6: Commit contracts**

```bash
git add package.json package-lock.json platform/contracts tests/node/contracts
git commit -m "feat: define platform contracts"
```

---

### Task 4: Implement The Native Service Supervisor

**Files:**
- Create: `apps/launcher/package.json`
- Create: `apps/launcher/src/service-config.js`
- Create: `apps/launcher/src/state-store.js`
- Create: `apps/launcher/src/service-supervisor.js`
- Create: `tools/fixtures/fake_service.js`
- Create: `configs/runtime/default.json`
- Create: `configs/runtime/simulation.json`
- Create: `tests/node/launcher/service-supervisor.test.js`
- Modify: `package.json`

**Interfaces:**
- Consumes: `loadServiceConfig(path) -> ServiceDefinition[]`, where each definition has `id`, `command`, `args`, `cwd`, `env`, `healthUrl`, `shutdownOrder`, and `enabled`.
- Produces: `ServiceSupervisor.startAll()`, `.status()`, `.stopAll()`; atomic state at `runtime/run/state.json`; no systemd interaction.

- [ ] **Step 1: Write the failing lifecycle test**

Create `tests/node/launcher/service-supervisor.test.js` using a temporary runtime directory:

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { ServiceSupervisor } = require('../../../apps/launcher/src/service-supervisor');

test('starts once and stops in descending shutdown order', async () => {
  const events = [];
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-launcher-'));
  const supervisor = new ServiceSupervisor({
    runtimeDir,
    services: [
      { id: 'robot', command: process.execPath, args: [path.resolve('tools/fixtures/fake_service.js')], shutdownOrder: 100, enabled: true },
      { id: 'vision', command: process.execPath, args: [path.resolve('tools/fixtures/fake_service.js')], shutdownOrder: 50, enabled: true },
    ],
    onEvent: event => events.push(event),
  });
  await supervisor.startAll();
  await supervisor.startAll();
  assert.deepEqual((await supervisor.status()).map(x => x.state), ['ready', 'ready']);
  await supervisor.stopAll();
  assert.deepEqual(events.filter(x => x.type === 'stopped').map(x => x.serviceId), ['robot', 'vision']);
  fs.rmSync(runtimeDir, { recursive: true, force: true });
});
```

- [ ] **Step 2: Run the lifecycle test and confirm the missing module failure**

Run:

```bash
node --test tests/node/launcher/service-supervisor.test.js
```

Expected: FAIL because `service-supervisor.js` does not exist.

- [ ] **Step 3: Implement config validation and atomic state storage**

`service-config.js` must reject duplicate IDs, non-array args, relative command ambiguity, ports outside 1..65535, and non-loopback bindings for 3000/3100/3004 unless an explicit `allowLan` flag is true.

`state-store.js` exports:

```javascript
function readState(statePath) {}
function writeStateAtomic(statePath, state) {}
function removeState(statePath) {}
```

Write to a sibling temporary file, `fsync`, then rename. State records service ID, PID, process start marker, command hash, status, startedAt, and lastError. Do not trust a PID without comparing the recorded process marker.

- [ ] **Step 4: Implement idempotent process lifecycle**

`ServiceSupervisor.startAll()` must start enabled services in declaration order, create per-service stdout/stderr logs, wait for the declared health endpoint or process-ready JSON line, and never launch a second live instance. `stopAll()` sends the configured graceful signal in descending `shutdownOrder`, waits for timeout, then reports `stop_timeout`; it must not silently claim success.

Set Robot Service to the highest shutdown order so task authorization is revoked before robot ownership is released. This fixture phase sends no CAN or SDK commands.

- [ ] **Step 5: Add safe runtime profiles**

`configs/runtime/simulation.json` launches deterministic fake `robot`, `vision`, `speech`, `model`, and `supervisor` workers on loopback test ports selected by environment overrides. `configs/runtime/default.json` declares 3000/3100/3004 and 9983 ownership but sets unmigrated live services `enabled: false` with `unavailableReason: "service_not_migrated"`.

- [ ] **Step 6: Run launcher tests and existing Node smoke tests**

Run:

```bash
node --test tests/node/launcher/service-supervisor.test.js
npm --prefix web-control/server test
git diff --check
```

Expected: new lifecycle test passes; existing web-control smoke suite remains green.

- [ ] **Step 7: Commit the supervisor**

```bash
git add apps/launcher configs/runtime tools/fixtures tests/node/launcher package.json package-lock.json
git commit -m "feat: add native service supervisor"
```

---

### Task 5: Implement Skill Discovery And Availability

**Files:**
- Create: `platform/skill_registry/package.json`
- Create: `platform/skill_registry/src/resource-status.js`
- Create: `platform/skill_registry/src/registry.js`
- Create: `skills/vision/describe-scene/manifest.yaml`
- Create: `skills/vision/detect-objects/manifest.yaml`
- Create: `skills/vision/supervise-execution/manifest.yaml`
- Create: `skills/manipulation/pick-and-place/manifest.yaml`
- Create: `skills/policies/vla/manifest.yaml`
- Create: `skills/policies/act/manifest.yaml`
- Create: `skills/policies/diffusion-policy/manifest.yaml`
- Create: `tests/node/skill_registry/registry.test.js`
- Modify: `package.json`

**Interfaces:**
- Consumes: Validated Skill manifests, `serviceHealthById`, `deviceHealthById`, and `assetHealthById`.
- Produces: `discoverSkills({skillsRoot, resources}) -> SkillDescriptor[]`; each descriptor has `id`, `version`, `risk`, `operations`, `status`, and `unavailableReasons`.

- [ ] **Step 1: Write failing discovery and fail-closed tests**

Create `tests/node/skill_registry/registry.test.js`:

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { discoverSkills } = require('../../../platform/skill_registry/src/registry');

test('discovers manifests without loading worker code', async () => {
  const skills = await discoverSkills({
    skillsRoot: path.resolve('skills'),
    resources: { services: {}, devices: {}, models: {} },
  });
  assert.ok(skills.some(skill => skill.id === 'vision.describe-scene'));
  assert.ok(skills.some(skill => skill.id === 'manipulation.pick-and-place'));
});

test('ACT remains unavailable without checkpoint and services', async () => {
  const skills = await discoverSkills({
    skillsRoot: path.resolve('skills'),
    resources: { services: {}, devices: {}, models: {} },
  });
  const act = skills.find(skill => skill.id === 'policy.act');
  assert.equal(act.status, 'unavailable');
  assert.ok(act.unavailableReasons.includes('model:policy.act'));
});
```

- [ ] **Step 2: Run the test and confirm discovery is missing**

Run:

```bash
node --test tests/node/skill_registry/registry.test.js
```

Expected: FAIL because the registry module does not exist.

- [ ] **Step 3: Create all approved Skill manifests**

Use the exact IDs:

```text
vision.describe-scene
vision.detect-objects
vision.supervise-execution
manipulation.pick-and-place
policy.vla
policy.act
policy.diffusion-policy
```

Read-only vision Skills use `risk: read-only`; manipulation and policy Skills use `risk: physical-motion`. Every physical Skill declares `operations: [plan, execute, status, cancel]` and requires `robot`, `vision`, and `supervisor`. Policy manifests additionally require their matching model resource. Do not add worker entry files in this foundation phase; manifests must therefore report `implementation_not_migrated` even if dependencies appear healthy.

- [ ] **Step 4: Implement deterministic discovery**

`discoverSkills` recursively finds only `skills/*/*/manifest.yaml`, sorts by ID, validates each manifest with `thirdhand.skill-manifest.v1`, rejects duplicate IDs, and evaluates all declared service/device/model requirements. Invalid manifests throw a startup configuration error; valid but incomplete Skills return `status: unavailable` with sorted reasons.

Do not `require()` or import Skill entrypoints during discovery. Worker loading belongs to a later plan after authorization and sandbox boundaries exist.

- [ ] **Step 5: Run registry and contract tests**

Run:

```bash
node --test tests/node/skill_registry/registry.test.js
npm run test:contracts
git diff --check
```

Expected: both suites pass; ACT, DP, VLA, and all not-yet-migrated Skills are truthfully unavailable.

- [ ] **Step 6: Commit Skill discovery**

```bash
git add platform/skill_registry skills tests/node/skill_registry package.json package-lock.json
git commit -m "feat: add fail-closed skill discovery"
```

---

### Task 6: Add The `thirdhand` CLI And Simulated One-Command Lifecycle

**Files:**
- Create: `thirdhand`
- Create: `apps/launcher/src/cli.js`
- Create: `tests/integration/test_simulated_lifecycle.py`
- Create: `docs/OPERATIONS.md`
- Modify: `package.json`
- Modify: `runtime/README.md`

**Interfaces:**
- Consumes: Runtime profile path, asset manifest, `ServiceSupervisor`, and Skill registry.
- Produces: `./thirdhand start|stop|status|doctor|verify-assets`; JSON mode for automation; human-readable mode for operators.

- [ ] **Step 1: Write the failing CLI integration test**

Create `tests/integration/test_simulated_lifecycle.py`:

```python
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def _run(*args: str):
    env = {**os.environ, "THIRDHAND_PROFILE": "simulation"}
    return subprocess.run(
        [str(ROOT / "thirdhand"), *args, "--json"],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False,
    )


def test_simulated_start_status_stop_cycle():
    started = _run("start")
    assert started.returncode == 0, started.stderr
    assert json.loads(started.stdout)["overall"] == "ready"

    status = _run("status")
    assert status.returncode == 0
    assert json.loads(status.stdout)["services"]["robot"]["state"] == "ready"

    stopped = _run("stop")
    assert stopped.returncode == 0
    assert json.loads(stopped.stdout)["overall"] == "stopped"
```

- [ ] **Step 2: Run the test and confirm the missing executable failure**

Run:

```bash
python -m pytest tests/integration/test_simulated_lifecycle.py -v
```

Expected: FAIL because `thirdhand` does not exist.

- [ ] **Step 3: Implement the POSIX wrapper and command dispatch**

`thirdhand` is a small Bash wrapper that resolves its own repository root, selects `local/runtimes/node/bin/node` when verified and otherwise uses a compatible system Node 24, then executes `apps/launcher/src/cli.js`. It must never run `npm install`, download assets, use sudo, or invoke systemd.

`cli.js` supports:

```text
start          verify required assets, start enabled services, discover Skills
stop           revoke runtime state and stop owned services in safe order
status         report process, service, Skill, and asset state
doctor         run read-only platform, port, ABI, GPU, USB, and CAN diagnostics
verify-assets  delegate to tools/assets/verify_assets.py
```

Every command accepts `--json`. `start` is idempotent. `status` distinguishes `ready`, `degraded`, `unavailable`, and `stopped`; missing optional policy models produce degraded availability, not a false overall failure. Missing Robot/Supervisor assets prevent motion capability but the later gateway may still start.

- [ ] **Step 4: Make state ownership safe**

Before `stop`, compare each recorded process start marker and command hash. Never signal a reused PID. Emit `not_owned` for mismatches. `stop` first writes `authorizationState: revoked`, then stops services by shutdown order. This foundation profile contains only fake workers and must not open CAN.

- [ ] **Step 5: Run lifecycle, launcher, registry, and contract tests**

Run:

```bash
python -m pytest tests/integration/test_simulated_lifecycle.py -v
node --test tests/node/launcher/*.test.js
node --test tests/node/skill_registry/*.test.js
npm run test:contracts
```

Expected: all tests pass; a second `start` reports the same owned PIDs; `stop` leaves no fake worker processes.

- [ ] **Step 6: Document exact operator behavior**

`docs/OPERATIONS.md` must document prerequisites, every command, simulation versus default profile, asset failure messages, PID ownership, log paths, port ownership, degraded startup, shutdown order, and the explicit statement that software stop is not a hardware emergency stop.

- [ ] **Step 7: Commit the CLI lifecycle**

```bash
git add thirdhand apps/launcher/src/cli.js tests/integration/test_simulated_lifecycle.py docs/OPERATIONS.md runtime/README.md package.json package-lock.json
git commit -m "feat: add one-command simulated lifecycle"
```

---

### Task 7: Add Boundary Audits And Complete Foundation Verification

**Files:**
- Create: `tools/diagnostics/audit_boundaries.py`
- Create: `tests/unit/platform/test_source_boundaries.py`
- Modify: `docs/DIRECTORY_MAP.md`
- Modify: `docs/migration/FOUNDATION_BASELINE.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Repository root and formal source roots.
- Produces: `audit_repository(root: Path) -> list[Violation]`; zero violations required before later migrations start.

- [ ] **Step 1: Write failing source-boundary tests**

Create `tests/unit/platform/test_source_boundaries.py`:

```python
from pathlib import Path

from tools.diagnostics.audit_boundaries import audit_repository


ROOT = Path(__file__).resolve().parents[3]


def test_unified_foundation_has_no_machine_specific_runtime_paths():
    violations = audit_repository(ROOT)
    relevant = [v for v in violations if v.code == "absolute_home_path"]
    assert relevant == []


def test_formal_source_does_not_import_archive():
    violations = audit_repository(ROOT)
    relevant = [v for v in violations if v.code == "archive_runtime_dependency"]
    assert relevant == []
```

The audit scope is only new formal roots (`apps`, `platform`, `services`, `skills`, `drivers`, `tools`) in this phase. Existing legacy paths are migration inputs and are not falsely declared clean yet.

- [ ] **Step 2: Run the test and confirm the missing audit module failure**

Run:

```bash
python -m pytest tests/unit/platform/test_source_boundaries.py -v
```

Expected: collection fails because `tools.diagnostics.audit_boundaries` does not exist.

- [ ] **Step 3: Implement the read-only boundary auditor**

Define:

```python
@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    line: int
    detail: str


def audit_repository(root: Path) -> list[Violation]:
    """Scan text source only; never follow symlinks or enter ignored payload directories."""
```

Report `/home/nieqingcao/`, imports or executable references containing `archive/`, tracked files under `local/` other than `README.md`, tracked mutable files under `runtime/` other than `README.md`, and symlinks escaping the repository. Exclude the design, plans, migration documentation, and archive provenance because they intentionally mention old absolute paths.

- [ ] **Step 4: Run the full foundation verification matrix**

Run:

```bash
python -m pytest tests/unit/platform tests/integration/test_simulated_lifecycle.py -v
npm run test:contracts
node --test tests/node/launcher/*.test.js tests/node/skill_registry/*.test.js
npm --prefix web-control/server test
python -m pytest tests/test_build_backend.py tests/docs -v
python tools/diagnostics/audit_boundaries.py --root . --json
git diff --check
git status --short
```

Expected: all tests pass; the boundary report has `violations: []`; only intended foundation files are modified. Do not run hardware tests.

- [ ] **Step 5: Perform a manual simulation acceptance**

Run:

```bash
THIRDHAND_PROFILE=simulation ./thirdhand doctor
THIRDHAND_PROFILE=simulation ./thirdhand start
THIRDHAND_PROFILE=simulation ./thirdhand status
THIRDHAND_PROFILE=simulation ./thirdhand start
THIRDHAND_PROFILE=simulation ./thirdhand stop
THIRDHAND_PROFILE=simulation ./thirdhand status
```

Expected: doctor is read-only; the first start reports five ready fake services; the second start is idempotent; stop reports owned processes stopped in safe order; final status is `stopped`.

- [ ] **Step 6: Update foundation documentation and migration checkpoint**

Add the verified commands and results to `FOUNDATION_BASELINE.md`. Update the root README with only the simulation foundation entry point and clearly state that accepted real services have not yet moved. Do not advertise live unified startup until the later service migration plans pass hardware acceptance.

- [ ] **Step 7: Commit the verified foundation**

```bash
git add tools/diagnostics tests/unit/platform docs/DIRECTORY_MAP.md docs/migration/FOUNDATION_BASELINE.md README.md
git commit -m "test: enforce unified platform boundaries"
```

- [ ] **Step 8: Review the branch before requesting integration**

Run:

```bash
git log --oneline --decorate --reverse HEAD~7..HEAD
git diff --stat HEAD~7..HEAD
git status --short --branch
```

Expected: the worktree is clean; commits are limited to repository foundation, contracts, asset tooling, launcher, Skill discovery, tests, and documentation. No accepted Ubuntu live source directory was modified or deleted.
