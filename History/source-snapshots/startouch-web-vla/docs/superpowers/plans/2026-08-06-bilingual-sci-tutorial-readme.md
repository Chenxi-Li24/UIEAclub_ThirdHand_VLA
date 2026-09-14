# Bilingual SCI Tutorial README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a bilingual, tutorial-style project documentation set that explains the complete ThirdHand VLA system and establishes a traceable evidence framework for future vision, VLA, and integrated SCI publications.

**Architecture:** Keep `README.md` as a compact bilingual landing page and maintain structurally aligned full tutorials in `README_CN.md` and `README_EN.md`. Add a focused `docs/research/` evidence layer with machine-readable schemas and human-readable templates; enforce links, section alignment, maturity labels, repository facts, and planned-evidence honesty through pytest documentation contracts.

**Tech Stack:** GitHub-Flavored Markdown, Mermaid, HTML anchors, Python 3.10+, pytest, JSON Schema documents, existing YAML/configuration and repository documentation.

## Global Constraints

- Primary research axis: robotic vision and 3D perception.
- Secondary research axis: verifiable VLA decision-making.
- Optional paper axis: integrated vision–VLA system.
- Robot control is the supervised experimental platform and safety boundary, not the principal claimed contribution.
- `README.md` is a concise bilingual landing page; `README_CN.md` and `README_EN.md` are complete aligned tutorials.
- Label capabilities only as **Implemented**, **Verified**, **Experimental**, or **Planned**, based on repository evidence.
- Use **Planned Evidence / 待补实验证据** for missing future figures or results; never invent screenshots, values, curves, or conclusions.
- Every scientific result must be traceable to machine-readable data, a manifest, a generation command, and the relevant code/model/calibration/data versions.
- Online dual-camera perception remains observational while `robot_execution_enabled: false`; do not imply validated vision-triggered robot motion.
- VLA and voice outputs are candidates or recommendations and cannot bypass deterministic local validation.
- Software stop does not replace the independent hardware emergency stop.
- Do not commit credentials, host-specific tokens, logs, PID files, runtime captures, model weights, or private absolute paths.
- Use the repository URL `https://github.com/Chenxi-Li24/UIEAclub_ThirdHand_VLA.git`.
- Commands must state their working directory and hardware authority level (L0–L4).
- Chinese and English section anchors, diagrams, tables, commands, links, maturity labels, and technical meaning must remain aligned.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `README.md` | Compact bilingual GitHub landing page, research focus, architecture summary, maturity matrix, safe quick start, and language navigation |
| `README_CN.md` | Canonical full Chinese tutorial from foundations through research reproducibility |
| `README_EN.md` | Complete English counterpart aligned by stable section anchors |
| `docs/research/README.md` | Research evidence hub and three publication-track navigation map |
| `docs/research/claim_evidence_matrix.md` | Claim-to-hypothesis-to-experiment-to-artifact mapping template |
| `docs/research/dataset_datasheet.md` | Dataset provenance, capture, split, privacy, licensing, and quality template |
| `docs/research/baseline_ablation_matrix.md` | Vision/VLA baselines and ablations with exact controlled variables |
| `docs/research/figure_manifest.md` | Figure/table IDs, source data, generation command, status, and caption contract |
| `docs/research/reproducibility_checklist.md` | Environment, seed, version, artifact, statistical, and release checklist |
| `docs/research/schemas/experiment-manifest.schema.json` | Machine-readable experiment provenance schema |
| `docs/research/schemas/result-record.schema.json` | Machine-readable metric/result schema |
| `tests/docs/test_readme_contract.py` | Automated bilingual alignment, link, fact, safety, and evidence-policy checks |

---

### Task 1: Documentation Contract Tests

**Files:**
- Create: `tests/docs/__init__.py`
- Create: `tests/docs/test_readme_contract.py`

**Interfaces:**
- Consumes: repository root, existing `configs/`, `docs/`, `web-control/`, and `pyproject.toml` paths.
- Produces: pytest contracts used by every later task; helper functions `read_doc(path: str) -> str`, `section_anchors(text: str) -> list[str]`, and `local_markdown_links(text: str) -> list[str]`.

- [ ] **Step 1: Create the documentation test package and failing file-presence test**

Create `tests/docs/__init__.py` empty and start `tests/docs/test_readme_contract.py` with:

```python
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ("README.md", "README_CN.md", "README_EN.md")
RESEARCH_FILES = (
    "docs/research/README.md",
    "docs/research/claim_evidence_matrix.md",
    "docs/research/dataset_datasheet.md",
    "docs/research/baseline_ablation_matrix.md",
    "docs/research/figure_manifest.md",
    "docs/research/reproducibility_checklist.md",
    "docs/research/schemas/experiment-manifest.schema.json",
    "docs/research/schemas/result-record.schema.json",
)


def read_doc(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def test_required_documentation_files_exist() -> None:
    missing = [path for path in (*DOCS, *RESEARCH_FILES) if not (ROOT / path).is_file()]
    assert missing == []
```

- [ ] **Step 2: Run the presence test and verify it fails**

Run: `.venv/bin/python -m pytest tests/docs/test_readme_contract.py::test_required_documentation_files_exist -v`

Expected: FAIL listing `README_EN.md` and the `docs/research/` files.

- [ ] **Step 3: Add failing structure, link, fact, and safety contracts**

Append tests that:

```python
ANCHOR_RE = re.compile(r'<a id="([a-z0-9-]+)"></a>')
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def section_anchors(text: str) -> list[str]:
    return ANCHOR_RE.findall(text)


def local_markdown_links(text: str) -> list[str]:
    return [
        target.split("#", 1)[0]
        for target in LINK_RE.findall(text)
        if target and not target.startswith(("http://", "https://", "mailto:", "#"))
    ]


def test_language_tutorials_have_aligned_section_anchors() -> None:
    cn = section_anchors(read_doc("README_CN.md"))
    en = section_anchors(read_doc("README_EN.md"))
    assert cn == en
    assert cn == [
        "tutorial-01-system",
        "tutorial-02-robotics-geometry",
        "tutorial-03-perception",
        "tutorial-04-vla-interaction",
        "tutorial-05-control-safety",
        "tutorial-06-code-map",
        "tutorial-07-hands-on",
        "tutorial-08-research-verification",
    ]


def test_all_local_markdown_links_resolve() -> None:
    failures: list[str] = []
    for source in (*DOCS, *RESEARCH_FILES[:-2]):
        base = (ROOT / source).parent
        for target in local_markdown_links(read_doc(source)):
            if not (base / target).resolve().exists():
                failures.append(f"{source}: {target}")
    assert failures == []


def test_repository_identity_and_runtime_boundaries_are_current() -> None:
    combined = "\n".join(read_doc(path) for path in DOCS)
    assert "Oliveirah007/UIEAclub_ThirdHand_VLA" not in combined
    assert "https://github.com/Chenxi-Li24/UIEAclub_ThirdHand_VLA.git" in combined
    for port in ("8000", "3000", "3001", "8766"):
        assert port in combined
    assert "robot_execution_enabled: false" in combined


def assert_tutorial_safety_and_maturity(path: str) -> None:
    text = read_doc(path)
    assert all(label in text for label in ("Implemented", "Verified", "Experimental", "Planned"))
    assert "Planned Evidence" in text
    assert "hardware emergency stop" in text.lower() or "硬件急停" in text


def test_chinese_tutorial_safety_and_maturity() -> None:
    assert_tutorial_safety_and_maturity("README_CN.md")


def test_english_tutorial_safety_and_maturity() -> None:
    assert_tutorial_safety_and_maturity("README_EN.md")


def test_landing_page_identity_and_safe_quick_start() -> None:
    text = read_doc("README.md")
    assert "Oliveirah007/UIEAclub_ThirdHand_VLA" not in text
    assert "https://github.com/Chenxi-Li24/UIEAclub_ThirdHand_VLA.git" in text
    assert "STARTOUCH_CAN_INTERFACE=thirdhand-test" in text
    assert "robot_execution_enabled: false" in text


def test_readmes_do_not_contain_unqualified_placeholders() -> None:
    forbidden = re.compile(r"\b(TBD|TODO|FIXME|PLACEHOLDER)\b", re.IGNORECASE)
    for path in DOCS:
        assert forbidden.search(read_doc(path)) is None


def test_research_schemas_are_valid_json_schema_documents() -> None:
    for path in RESEARCH_FILES[-2:]:
        payload = json.loads(read_doc(path))
        assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert payload["type"] == "object"
        assert payload["additionalProperties"] is False
        assert payload["required"]
```

- [ ] **Step 4: Run the full documentation contract and verify expected failures**

Run: `.venv/bin/python -m pytest tests/docs/test_readme_contract.py -v`

Expected: FAIL only because the new/rewritten documents and anchors do not exist yet; helper code must import and collect successfully.

- [ ] **Step 5: Commit the test contract**

```bash
git add tests/docs/__init__.py tests/docs/test_readme_contract.py
git commit -m "test(docs): define bilingual research readme contract"
```

---

### Task 2: Research Evidence Schemas and Templates

**Files:**
- Create: `docs/research/README.md`
- Create: `docs/research/claim_evidence_matrix.md`
- Create: `docs/research/dataset_datasheet.md`
- Create: `docs/research/baseline_ablation_matrix.md`
- Create: `docs/research/figure_manifest.md`
- Create: `docs/research/reproducibility_checklist.md`
- Create: `docs/research/schemas/experiment-manifest.schema.json`
- Create: `docs/research/schemas/result-record.schema.json`

**Interfaces:**
- Consumes: research direction and evidence policy from the approved design; existing metrics in `docs/vision_research/13_BENCHMARK_AND_ACCEPTANCE_PLAN.md`.
- Produces: stable research artifact paths linked by all README files and validated by Task 1.

- [ ] **Step 1: Write the experiment manifest JSON Schema**

Define a Draft 2020-12 object with `additionalProperties: false` and required fields:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://uiea.example/schemas/thirdhand-experiment-manifest-v1.json",
  "title": "ThirdHand Experiment Manifest",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version", "experiment_id", "research_track", "hypothesis_id",
    "git_commit", "command", "environment", "dataset", "models",
    "calibration_id", "seeds", "started_at", "artifacts"
  ],
  "properties": {
    "schema_version": {"const": 1},
    "experiment_id": {"type": "string", "minLength": 1},
    "research_track": {"enum": ["vision", "vla", "vision_vla"]},
    "hypothesis_id": {"type": "string", "minLength": 1},
    "git_commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
    "command": {"type": "array", "items": {"type": "string"}, "minItems": 1},
    "environment": {
      "type": "object", "additionalProperties": false,
      "required": ["python", "os", "hardware", "dependencies_lock_sha256"],
      "properties": {
        "python": {"type": "string"}, "os": {"type": "string"},
        "hardware": {"type": "object"},
        "dependencies_lock_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
      }
    },
    "dataset": {
      "type": "object", "additionalProperties": false,
      "required": ["manifest", "sha256", "split"],
      "properties": {
        "manifest": {"type": "string"},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "split": {"enum": ["train", "validation", "test", "replay", "live"]}
      }
    },
    "models": {"type": "array", "items": {"type": "object"}, "minItems": 1},
    "calibration_id": {"type": ["string", "null"]},
    "seeds": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
    "started_at": {"type": "string", "format": "date-time"},
    "artifacts": {"type": "array", "items": {"type": "object"}}
  }
}
```

- [ ] **Step 2: Write the result record JSON Schema**

Require `schema_version`, `experiment_id`, `metric`, `value`, `unit`, `aggregation`,
`sample_count`, `confidence_interval`, `slice`, and `source_artifact`. Allow `value`
to be number, integer, boolean, or null; define `aggregation` as `raw`, `mean`,
`median`, `p50`, `p95`, `max`, `rate`, or `count`; represent a confidence interval as
`null` or an object with `level`, `lower`, `upper`, and `method`.

- [ ] **Step 3: Write the research hub with three publication tracks**

Document Track A (vision/3D, primary), Track B (verifiable VLA, secondary), and Track C
(integrated vision–VLA). For each track include scope, candidate contribution, required
evidence, metrics, current repository evidence, missing gates, and links to the templates.
State that robot control is an experimental platform rather than the main contribution.

- [ ] **Step 4: Write the claim/evidence and dataset templates**

Use concrete field tables rather than blank prose prompts. The claim matrix columns are:
`Claim ID`, `Track`, `Falsifiable hypothesis`, `Method/config`, `Dataset/split`,
`Baselines`, `Metric and threshold`, `Experiment IDs`, `Figures/tables`, `Status`,
`Threats to validity`. The dataset datasheet must cover capture hardware, logical camera
roles, timestamps, calibration, scenes, object categories, annotation policy, splits,
leakage prevention, privacy, consent, licensing, checksums, known biases, and retention.

- [ ] **Step 5: Write baseline, figure, and reproducibility templates**

Include these exact baseline families:

- detection/segmentation: YOLOv8n detect, YOLO nano segmentation, RTMDet-tiny-ins,
  Mask R-CNN R50-FPN;
- identity: IoU-only tracker, appearance-only, appearance+3D gate, work bank only,
  work+stable memory, ambiguity rejection on/off;
- VLA: free-form direct output (offline unsafe baseline only), structured candidate,
  candidate+preview, candidate+preview+human confirmation+local safety validation.

The figure manifest must define V1, V2, V3, L1, E1, E2, E3, and F1 from the approved
design, with `Planned Evidence` status and required source-data/generation-command fields.

- [ ] **Step 6: Run the schema and file-presence contracts**

Run:

```bash
.venv/bin/python -m pytest \
  tests/docs/test_readme_contract.py::test_required_documentation_files_exist \
  tests/docs/test_readme_contract.py::test_research_schemas_are_valid_json_schema_documents -v
```

Expected: schema test PASS; presence test still FAIL only for `README_EN.md` until Task 5.

- [ ] **Step 7: Commit the research evidence layer**

```bash
git add docs/research
git commit -m "docs(research): add SCI evidence contracts"
```

---

### Task 3: Bilingual Landing Page

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: research hub and evidence files from Task 2; current service/config facts.
- Produces: GitHub landing page and language navigation consumed by readers.

- [ ] **Step 1: Replace the obsolete landing page structure**

Write a compact bilingual page containing:

1. centered project title and bilingual one-sentence description;
2. badges for Python 3.10+, MIT, research alpha, and CI without claiming CI success;
3. prominent links to `README_CN.md` and `README_EN.md`;
4. cards/table for Vision & 3D, Verifiable VLA, Safe Execution Platform, and Reproducible Evidence;
5. a four-level maturity legend;
6. a concise capability status matrix backed by repository evidence.

- [ ] **Step 2: Add the high-level Mermaid architecture**

The diagram must visually separate:

- packaged Python VLA application on port 8000;
- Startouch Web stack on port 3000;
- Lumos RGB service on port 3001;
- fixed-point control on loopback port 8766;
- observational vision data from robot command authority;
- the local safety/state-machine boundary between VLA/voice candidates and execution.

- [ ] **Step 3: Add the shortest safe quick start**

Use the correct clone URL and L0/L1 commands:

```bash
git clone https://github.com/Chenxi-Li24/UIEAclub_ThirdHand_VLA.git
cd UIEAclub_ThirdHand_VLA
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[core,dev]"
ruff check src/ tests/
mypy src/
STARTOUCH_CAN_INTERFACE=thirdhand-test pytest tests/ -q --ignore=tests/e2e/
```

State explicitly that these commands do not authorize hardware motion.

- [ ] **Step 4: Add research previews without fabricated results**

Show a table for V1/V2/V3/L1/E1/E2/E3/F1 with status `Planned Evidence`, intended
visual, required source artifact, and link to `docs/research/figure_manifest.md`.
Include only dated, linked measured evidence already present in
`docs/vision_research/REMIND3D_DEPLOYMENT_RESULTS.md`.

- [ ] **Step 5: Run landing-page-specific contracts**

Run:

```bash
.venv/bin/python -m pytest \
  tests/docs/test_readme_contract.py::test_landing_page_identity_and_safe_quick_start -v
git diff --check -- README.md
rg -n '\b(TBD|TODO|FIXME|PLACEHOLDER)\b|Oliveirah007/UIEAclub_ThirdHand_VLA' README.md || true
```

Expected: landing-page contract and whitespace check PASS; `rg` prints no matches.

- [ ] **Step 6: Commit the landing page**

```bash
git add README.md
git commit -m "docs: build bilingual ThirdHand research landing page"
```

---

### Task 4: Complete Chinese Tutorial

**Files:**
- Modify: `README_CN.md`

**Interfaces:**
- Consumes: stable anchors, research templates, source/config facts, existing architecture,
  setup, module, API, model, fixed-point, voice, and vision research documentation.
- Produces: canonical complete tutorial whose structure Task 5 translates.

- [ ] **Step 1: Build the eight anchored chapters and navigation**

Insert exactly these anchors in order:

```html
<a id="tutorial-01-system"></a>
<a id="tutorial-02-robotics-geometry"></a>
<a id="tutorial-03-perception"></a>
<a id="tutorial-04-vla-interaction"></a>
<a id="tutorial-05-control-safety"></a>
<a id="tutorial-06-code-map"></a>
<a id="tutorial-07-hands-on"></a>
<a id="tutorial-08-research-verification"></a>
```

Add a top-level learning-outcomes block and separate reading paths for a new developer,
vision researcher, VLA researcher, reproducer, and supervised hardware operator.

- [ ] **Step 2: Write Chapters 1–2: system and foundations**

Cover hardware topology, the two runtime boundaries, feature maturity, 6-DoF joints,
joint/Cartesian motion, coordinate frames, RPY convention `Rz*Ry*Rx`, homogeneous SE(3),
intrinsics/extrinsics, hand-eye calibration, joint/workspace/speed constraints, watchdog,
software stop, and hardware emergency stop. Link each concept to its implementation/config.

- [ ] **Step 3: Write Chapter 3: perception and primary SCI direction**

Explain canonical Lumos RGB, D435 metric depth/debug RGB, SEUCM and pinhole models,
timestamp alignment, depth registration and z-buffering, RTMDet masks, DINOv2 descriptors,
tracking, work/stable object memory, occlusion/reacquisition, masked 3D pose, covariance,
and actionability gates. For every method include Problem, Method, Protocol, Metrics,
Evidence, and Limits subsections with links to the research evidence templates.

- [ ] **Step 4: Write Chapters 4–5: VLA, voice, orchestration, and safety**

Explain VLA recommendations, ASR/NLU/TTS, voice bridge, text path, structured candidates,
preview, confirmation, unsupported-intent rejection, deterministic state machine, control
adapters, Startouch bridge, CAN ownership, resource locks, fail-closed gates, and why robot
control is experimental infrastructure rather than the SCI novelty.

- [ ] **Step 5: Write Chapter 6: complete curated code map**

Include the repository tree and responsibility/interface/dependency/safety/deep-link tables
for `src/uiea_thirdhand_vla`, `web-control`, `configs`, `scripts`, `tests`, and `docs`.
Include current ports, bind defaults, configuration files, major environment variables,
model-asset policy, runtime-artifact policy, REST/WebSocket links, and all supported entry points.

- [ ] **Step 6: Write Chapter 7: L0–L4 hands-on tutorial**

For each level state prerequisites, exact commands, expected observations, prohibited
actions, stop conditions, and evidence to retain. Cover installation, offline verification,
deterministic replay, simulation/dry-run Web UI, voice mock, read-only dual-camera service,
fixed A/B demo, and supervised hardware gates. Do not include an unsupervised motion recipe.

- [ ] **Step 7: Write Chapter 8: SCI verification and troubleshooting**

Document the three research tracks, claim/evidence workflow, dataset/experiment/result
manifests, baseline and ablation plan, metrics, statistical reporting, figure previews,
failure cases, threats to validity, reproducibility checklist, and paper-writing path.
Add symptom→diagnosis→safe decision→recovery→evidence tables for CAN ownership,
camera role loss, frame staleness, invalid calibration/depth, ambiguous identity, port and
WebSocket failures, missing weights, GPU capacity, and latency limits.

- [ ] **Step 8: Run Chinese tutorial checks**

Run:

```bash
.venv/bin/python -m pytest \
  tests/docs/test_readme_contract.py::test_chinese_tutorial_safety_and_maturity -v
git diff --check -- README_CN.md
rg -n '\b(TBD|TODO|FIXME|PLACEHOLDER)\b|Oliveirah007/UIEAclub_ThirdHand_VLA' README_CN.md || true
```

Expected: safety, maturity, identity, placeholder, and whitespace checks PASS; bilingual
anchor test remains blocked only because English tutorial is not yet created.

- [ ] **Step 9: Commit the Chinese tutorial**

```bash
git add README_CN.md
git commit -m "docs: write complete Chinese vision VLA tutorial"
```

---

### Task 5: Aligned English Tutorial

**Files:**
- Create: `README_EN.md`

**Interfaces:**
- Consumes: canonical section order, commands, diagrams, tables, links, maturity labels,
  and technical meaning from `README_CN.md`.
- Produces: complete English tutorial with identical stable anchors and evidence references.

- [ ] **Step 1: Reproduce the exact eight-anchor structure**

Use the same anchor list and order from Task 4. Translate headings and explanatory prose,
but preserve path names, commands, configuration keys, diagram topology, figure IDs,
status labels, equations, symbols, and metric definitions exactly.

- [ ] **Step 2: Translate Chapters 1–5 with technical consistency**

Use standard terms: joint space, Cartesian space, end-effector, homogeneous transform,
SE(3), hand–eye calibration, canonical RGB, metric depth, cross-camera registration,
persistent instance identity, object memory, reacquisition, ambiguity rejection,
structured candidate, deterministic validation, and fail closed.

- [ ] **Step 3: Translate Chapters 6–8 and reference material**

Keep every command byte-for-byte identical to the Chinese version. Keep all maturity,
research-track, experiment-level, figure-ID, metric, troubleshooting, and evidence links aligned.

- [ ] **Step 4: Run bilingual alignment and link contracts**

Run:

```bash
.venv/bin/python -m pytest \
  tests/docs/test_readme_contract.py::test_language_tutorials_have_aligned_section_anchors \
  tests/docs/test_readme_contract.py::test_all_local_markdown_links_resolve \
  tests/docs/test_readme_contract.py::test_chinese_tutorial_safety_and_maturity \
  tests/docs/test_readme_contract.py::test_english_tutorial_safety_and_maturity \
  tests/docs/test_readme_contract.py::test_repository_identity_and_runtime_boundaries_are_current -v
git diff --check -- README_EN.md
```

Expected: all listed checks PASS.

- [ ] **Step 5: Commit the English tutorial**

```bash
git add README_EN.md
git commit -m "docs: add aligned English vision VLA tutorial"
```

---

### Task 6: Evidence Previews and Cross-Document Consistency

**Files:**
- Modify: `README.md`
- Modify: `README_CN.md`
- Modify: `README_EN.md`
- Modify: `docs/research/figure_manifest.md`
- Modify: `tests/docs/test_readme_contract.py`

**Interfaces:**
- Consumes: completed bilingual docs and research evidence layer.
- Produces: synchronized preview registry and stronger anti-fabrication/consistency tests.

- [ ] **Step 1: Add a failing preview-registry test**

Add:

```python
def test_planned_preview_registry_is_complete_and_honest() -> None:
    required_ids = {"V1", "V2", "V3", "L1", "E1", "E2", "E3", "F1"}
    for path in DOCS:
        text = read_doc(path)
        assert required_ids <= set(re.findall(r"\b(?:V[123]|L1|E[123]|F1)\b", text))
    manifest = read_doc("docs/research/figure_manifest.md")
    for figure_id in required_ids:
        assert f"| {figure_id} |" in manifest
    assert manifest.count("Planned Evidence") >= len(required_ids)
```

- [ ] **Step 2: Run the preview test and verify it fails if any ID is missing**

Run: `.venv/bin/python -m pytest tests/docs/test_readme_contract.py::test_planned_preview_registry_is_complete_and_honest -v`

Expected: FAIL with the first missing preview ID or insufficient planned-evidence labels.

- [ ] **Step 3: Synchronize all preview registries**

Ensure every README and the figure manifest contains V1, V2, V3, L1, E1, E2, E3,
and F1 with the same intended content, evidence status, source data requirements, and
generation-command requirement. Use Mermaid only for conceptual diagrams; do not create
synthetic bitmap results that could be mistaken for measured output.

- [ ] **Step 4: Run the complete documentation contract**

Run: `.venv/bin/python -m pytest tests/docs/test_readme_contract.py -v`

Expected: all documentation tests PASS.

- [ ] **Step 5: Commit consistency updates**

```bash
git add README.md README_CN.md README_EN.md docs/research/figure_manifest.md tests/docs/test_readme_contract.py
git commit -m "docs(research): synchronize evidence previews"
```

---

### Task 7: Final Repository Verification and Handoff

**Files:**
- Verify: `README.md`
- Verify: `README_CN.md`
- Verify: `README_EN.md`
- Verify: `docs/research/`
- Verify: `tests/docs/test_readme_contract.py`

**Interfaces:**
- Consumes: all deliverables from Tasks 1–6.
- Produces: verified documentation set ready for review and later remote push.

- [ ] **Step 1: Run Markdown and repository-diff checks**

Run:

```bash
git diff --check
git status --short
rg -n 'Oliveirah007/UIEAclub_ThirdHand_VLA|\b(TBD|TODO|FIXME|PLACEHOLDER)\b' \
  README.md README_CN.md README_EN.md docs/research tests/docs || true
```

Expected: no whitespace errors; no obsolete URL or unqualified placeholder output;
only intended files appear in Git status.

- [ ] **Step 2: Run documentation and core static checks**

Run:

```bash
.venv/bin/python -m pytest tests/docs/test_readme_contract.py -v
.venv/bin/ruff check src/ tests/
.venv/bin/mypy src/
```

Expected: all documentation tests PASS, Ruff reports all checks passed, and MyPy reports
no issues. If Python 3.10 and 3.11 environments are available, run MyPy in both because
the GitHub Actions matrix covers both versions.

- [ ] **Step 3: Run offline application and service regression tests**

Run:

```bash
STARTOUCH_CAN_INTERFACE=thirdhand-test \
  .venv/bin/python -m pytest tests/ -q --ignore=tests/e2e/
.venv/bin/python -m pytest web-control/server/tests/ -q
```

Expected: all tests PASS; the fake CAN interface prevents ownership of live `can0`.

- [ ] **Step 4: Validate JSON schemas and all local links independently**

Run:

```bash
.venv/bin/python -m json.tool docs/research/schemas/experiment-manifest.schema.json >/dev/null
.venv/bin/python -m json.tool docs/research/schemas/result-record.schema.json >/dev/null
.venv/bin/python -m pytest tests/docs/test_readme_contract.py::test_all_local_markdown_links_resolve -v
```

Expected: both schemas parse and all relative links resolve.

- [ ] **Step 5: Review the rendered GitHub presentation**

Inspect all Mermaid diagrams, tables, details blocks, language links, anchors, and preview
labels in a GitHub-compatible renderer. Confirm that planned evidence cannot be confused
with measured results and that dated evidence links show their dates.

- [ ] **Step 6: Commit only if verification required final corrections**

```bash
git add README.md README_CN.md README_EN.md docs/research tests/docs
git commit -m "docs: finalize bilingual SCI tutorial"
```

Skip this commit when the working tree has no final corrections.
