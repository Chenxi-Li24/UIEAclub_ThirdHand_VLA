from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

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


def local_markdown_link_failures(base: Path, targets: list[str]) -> list[str]:
    root = ROOT.resolve()
    failures: list[str] = []
    for target in targets:
        if Path(target).is_absolute():
            failures.append(f"absolute local link: {target}")
            continue
        resolved = (base / target).resolve()
        if not resolved.is_relative_to(root):
            failures.append(f"outside repository: {target}")
        elif not resolved.exists():
            failures.append(f"missing local link: {target}")
    return failures


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("/etc/passwd", "absolute local link: /etc/passwd"),
        ("../escaping.md", "outside repository: ../escaping.md"),
    ],
)
def test_local_markdown_link_validation_rejects_absolute_and_escaping_targets(
    target: str, expected: str
) -> None:
    assert local_markdown_link_failures(ROOT, [target]) == [expected]


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
        for failure in local_markdown_link_failures(base, local_markdown_links(read_doc(source))):
            failures.append(f"{source}: {failure}")
    assert failures == []


def test_repository_identity_and_runtime_boundaries_are_current() -> None:
    for path in DOCS:
        text = read_doc(path)
        assert "Oliveirah007/UIEAclub_ThirdHand_VLA" not in text
        assert "https://github.com/Chenxi-Li24/UIEAclub_ThirdHand_VLA.git" in text
        for port in ("8000", "3000", "3001", "8766"):
            assert port in text
        assert "robot_execution_enabled: false" in text


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


def test_planned_preview_registry_is_complete_and_honest() -> None:
    required_ids = {"V1", "V2", "V3", "L1", "E1", "E2", "E3", "F1"}
    for path in DOCS:
        text = read_doc(path)
        assert required_ids <= set(re.findall(r"\b(?:V[123]|L1|E[123]|F1)\b", text))
    manifest = read_doc("docs/research/figure_manifest.md")
    for figure_id in required_ids:
        assert f"| {figure_id} |" in manifest
    assert manifest.count("Planned Evidence") >= len(required_ids)


PREVIEW_REGISTRY_PATHS = (*DOCS, "docs/research/figure_manifest.md")
PREVIEW_IDS = ("V1", "V2", "V3", "L1", "E1", "E2", "E3", "F1")
PREVIEW_FIELDS = (
    "id",
    "intended_content",
    "status",
    "source_data",
    "generation_command",
    "release_gate",
)
PREVIEW_HEADER_ALIASES = {
    "ID": "id",
    "Intended content": "intended_content",
    "Planned content": "intended_content",
    "计划内容": "intended_content",
    "Status": "status",
    "状态": "status",
    "Required source data": "source_data",
    "必需来源数据": "source_data",
    "Required generation command": "generation_command",
    "必需生成命令": "generation_command",
    "Release gate": "release_gate",
    "释放门禁": "release_gate",
}

# Stable semantic anchors shared by the canonical manifest and every translated row.
# They permit natural-language phrasing differences while keeping evidence requirements aligned.
PREVIEW_FIELD_TOKENS = {
    "V1": {
        "intended_content": ("Lumos", "D435", "3D"),
        "source_data": ("Lumos RGB", "D435", "calibration", "manifest"),
        "generation_command": ("script/command", "manifest", "calibration"),
        "release_gate": ("manifest", "manual"),
    },
    "V2": {
        "intended_content": ("Identity", "occlusion", "reacquisition"),
        "source_data": ("track IDs", "memory", "manifest"),
        "generation_command": ("script/command", "result records"),
        "release_gate": ("identity", "selection rule"),
    },
    "V3": {
        "intended_content": ("registration", "residual", "uncertainty"),
        "source_data": ("calibration", "covariance", "manifest"),
        "generation_command": ("script/command", "JSON/CSV"),
        "release_gate": ("calibration ID", "aggregation"),
    },
    "L1": {
        "intended_content": ("VLA", "candidate", "preview", "refusal"),
        "source_data": ("scenario", "candidate", "validator/refusal log", "manifest"),
        "generation_command": ("script/command", "logs"),
        "release_gate": ("secret", "actuator-success"),
    },
    "E1": {
        "intended_content": ("baseline", "confidence intervals"),
        "source_data": ("result records", "CSV/JSON", "manifests"),
        "generation_command": ("script/command", "result records", "confidence intervals"),
        "release_gate": ("baseline", "interval"),
    },
    "E2": {
        "intended_content": ("ablation", "table/curve"),
        "source_data": ("variant", "seeds", "CSV/JSON"),
        "generation_command": ("script/command", "variants"),
        "release_gate": ("one-delta", "controls"),
    },
    "E3": {
        "intended_content": ("accuracy", "latency", "resource"),
        "source_data": ("P50/P95", "CPU/GPU/VRAM", "JSON"),
        "generation_command": ("script/command", "experiment ID"),
        "release_gate": ("hardware", "aggregation window"),
    },
    "F1": {
        "intended_content": ("success", "failure", "cases"),
        "source_data": ("selection rule", "failure taxonomy", "manifests"),
        "generation_command": ("script/command", "selection rule"),
        "release_gate": ("cherry-pick", "limitations"),
    },
}
CHINESE_CONTENT_TOKENS = {
    "V2": ("遮挡", "重捕获", "身份"),
    "V3": ("注册", "残差", "不确定度"),
}
CHINESE_FIELD_TOKEN_OVERRIDES = {
    ("V1", "release_gate"): ("manifest", "手工"),
    ("V3", "release_gate"): ("calibration ID", "聚合"),
}


def markdown_table_cells(line: str) -> list[str]:
    assert line.startswith("|") and line.endswith("|")
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_markdown_table_divider(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def parse_preview_registry(text: str) -> dict[str, dict[str, str]]:
    lines = text.splitlines()
    matches: list[dict[str, dict[str, str]]] = []
    for index, line in enumerate(lines):
        if not (line.startswith("|") and line.endswith("|")):
            continue
        header_cells = markdown_table_cells(line)
        header = tuple(PREVIEW_HEADER_ALIASES.get(cell, "") for cell in header_cells)
        if header != PREVIEW_FIELDS:
            continue
        assert index + 1 < len(lines)
        divider_cells = markdown_table_cells(lines[index + 1])
        assert len(divider_cells) == len(PREVIEW_FIELDS)
        assert is_markdown_table_divider(divider_cells)

        rows: dict[str, dict[str, str]] = {}
        for row_line in lines[index + 2 :]:
            if not (row_line.startswith("|") and row_line.endswith("|")):
                break
            row_cells = markdown_table_cells(row_line)
            assert len(row_cells) == len(PREVIEW_FIELDS)
            row = dict(zip(PREVIEW_FIELDS, row_cells, strict=True))
            assert all(row[field] for field in PREVIEW_FIELDS)
            figure_id = row["id"]
            assert figure_id not in rows
            rows[figure_id] = row
        matches.append(rows)

    assert len(matches) == 1
    registry = matches[0]
    assert tuple(registry) == PREVIEW_IDS
    for row in registry.values():
        assert row["status"] == "Planned Evidence"
    return registry


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).casefold()


def preview_field_tokens(path: str, figure_id: str, field: str) -> tuple[str, ...]:
    if path == "README_CN.md":
        if field == "intended_content":
            return CHINESE_CONTENT_TOKENS.get(figure_id, PREVIEW_FIELD_TOKENS[figure_id][field])
        if (figure_id, field) in CHINESE_FIELD_TOKEN_OVERRIDES:
            return CHINESE_FIELD_TOKEN_OVERRIDES[figure_id, field]
    return PREVIEW_FIELD_TOKENS[figure_id][field]


def assert_preview_registry_alignment(documents: dict[str, str]) -> None:
    assert tuple(documents) == PREVIEW_REGISTRY_PATHS
    registries = {path: parse_preview_registry(text) for path, text in documents.items()}
    canonical = registries["docs/research/figure_manifest.md"]

    for figure_id in PREVIEW_IDS:
        for field in PREVIEW_FIELDS[1:]:
            if field == "status":
                continue
            for token in preview_field_tokens(
                "docs/research/figure_manifest.md", figure_id, field
            ):
                assert normalized_text(token) in normalized_text(canonical[figure_id][field])
            for path, registry in registries.items():
                for token in preview_field_tokens(path, figure_id, field):
                    assert normalized_text(token) in normalized_text(registry[figure_id][field])


def preview_registry_documents() -> dict[str, str]:
    return {path: read_doc(path) for path in PREVIEW_REGISTRY_PATHS}


def replace_preview_row_cell(text: str, figure_id: str, column: int, value: str) -> str:
    line = next(line for line in text.splitlines() if line.startswith(f"| {figure_id} |"))
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    cells[column] = value
    replacement = "| " + " | ".join(cells) + " |"
    return text.replace(line, replacement, 1)


def test_preview_registry_rows_match_the_canonical_evidence_contract() -> None:
    assert_preview_registry_alignment(preview_registry_documents())


def test_preview_registries_require_traceable_generation() -> None:
    registry_headers = {
        "README.md": (
            "| ID | Intended content | Status | Required source data | "
            "Required generation command | Release gate |",
            "not measurements",
        ),
        "README_EN.md": (
            "| ID | Planned content | Status | Required source data | "
            "Required generation command | Release gate |",
            "must never be populated with invented values",
        ),
        "README_CN.md": (
            "| ID | 计划内容 | 状态 | 必需来源数据 | 必需生成命令 | 释放门禁 |",
            "不是空白结果图",
        ),
    }
    for path, (header, no_result_notice) in registry_headers.items():
        text = read_doc(path)
        assert header in text
        assert no_result_notice in text


@pytest.mark.parametrize(
    ("path", "figure_id", "column", "value"),
    [
        ("README.md", "V1", 2, "Evidence Incomplete"),
        ("README_EN.md", "V2", 3, ""),
        ("README_CN.md", "E1", 4, ""),
        ("README.md", "V2", 0, "V1"),
        ("docs/research/figure_manifest.md", "V1", 3, "Timestamped camera RGB"),
    ],
    ids=("status", "source-data", "generation-command", "duplicate-id", "canonical-token"),
)
def test_preview_registry_contract_rejects_row_level_drift(
    path: str, figure_id: str, column: int, value: str
) -> None:
    documents = preview_registry_documents()
    documents[path] = replace_preview_row_cell(documents[path], figure_id, column, value)

    with pytest.raises(AssertionError):
        assert_preview_registry_alignment(documents)


def test_research_schemas_are_valid_json_schema_documents() -> None:
    for path in RESEARCH_FILES[-2:]:
        payload = json.loads(read_doc(path))
        assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert payload["type"] == "object"
        assert payload["additionalProperties"] is False
        assert payload["required"]
