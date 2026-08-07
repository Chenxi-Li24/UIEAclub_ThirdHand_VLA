# ruff: noqa: E501
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

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
    "docs/research/REUSE_FIRST_ENGINEERING_POLICY.md",
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
HTML_ANCHOR_RE = re.compile(
    r'<a\s+[^>]*?(?:id|name)=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE
)
ATX_HEADING_RE = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$")
SETEXT_HEADING_RE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
INLINE_LINK_RE = re.compile(r"!?\[([^\]]+)\]\([^)]+\)")
HTML_TAG_RE = re.compile(r"<[^>]+>")


def section_anchors(text: str) -> list[str]:
    return ANCHOR_RE.findall(text)


def local_markdown_links(text: str) -> list[str]:
    links: list[str] = []
    for target in LINK_RE.findall(text):
        if not target:
            continue
        parsed = urlsplit(target)
        if parsed.scheme or target.startswith("//"):
            continue
        links.append(target)
    return links


def github_heading_slug(heading: str) -> str:
    visible = INLINE_LINK_RE.sub(r"\1", heading)
    visible = HTML_TAG_RE.sub("", visible)
    visible = visible.replace("`", "").replace("*", "")
    normalized: list[str] = []
    for character in visible.strip().lower():
        category = unicodedata.category(character)
        if character in {"-", "_"} or category[0] not in {"P", "S", "C"}:
            normalized.append(character)
    return re.sub(r"\s", "-", "".join(normalized))


def markdown_anchor_targets(text: str) -> set[str]:
    anchors = set(HTML_ANCHOR_RE.findall(text))
    allocated = set(anchors)
    next_suffix: dict[str, int] = {}
    lines = text.splitlines()
    in_fence = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.match(r"^ {0,3}(```|~~~)", line):
            in_fence = not in_fence
            index += 1
            continue
        heading: str | None = None
        if not in_fence:
            match = ATX_HEADING_RE.match(line)
            if match:
                heading = match.group(1)
            elif index + 1 < len(lines) and line.strip() and SETEXT_HEADING_RE.match(
                lines[index + 1]
            ):
                heading = line.strip()
                index += 1
        if heading is not None:
            base = github_heading_slug(heading)
            candidate = base
            suffix = next_suffix.get(base, 0)
            while candidate in allocated:
                suffix += 1
                candidate = f"{base}-{suffix}"
            next_suffix[base] = suffix
            allocated.add(candidate)
            anchors.add(candidate)
        index += 1
    return anchors


def local_markdown_link_failures(source: Path, targets: list[str]) -> list[str]:
    root = ROOT.resolve()
    source_is_document = source.is_file()
    base = source.parent if source_is_document else source
    failures: list[str] = []
    for target in targets:
        path_part, separator, fragment = target.partition("#")
        decoded_path = unquote(path_part)
        if decoded_path and Path(decoded_path).is_absolute():
            failures.append(f"absolute local link: {target}")
            continue
        if decoded_path:
            resolved = (base / decoded_path).resolve()
        elif source_is_document:
            resolved = source.resolve()
        else:
            failures.append(f"missing local link: {target}")
            continue
        if not resolved.is_relative_to(root):
            failures.append(f"outside repository: {target}")
        elif not resolved.exists():
            failures.append(f"missing local link: {target}")
        elif separator:
            try:
                anchors = markdown_anchor_targets(resolved.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError):
                failures.append(f"unreadable fragment target: {target}")
                continue
            if unquote(fragment) not in anchors:
                failures.append(f"missing fragment: {target}")
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


def test_local_markdown_links_preserve_local_fragments_and_ignore_external_urls() -> None:
    text = "\n".join(
        (
            "[deep link](README_CN.md#tutorial-07-hands-on)",
            "[same document](#tutorial-01-system)",
            "[external](https://example.com/guide#section)",
            "[external non-HTTP](ftp://example.com/archive#item)",
        )
    )

    assert local_markdown_links(text) == [
        "README_CN.md#tutorial-07-hands-on",
        "#tutorial-01-system",
    ]


@pytest.mark.parametrize(
    "target",
    [
        "README_CN.md#tutorial-07-hands-on",
        "README_EN.md#learning-outcomes",
        "README_EN.md#problem",
        "README_EN.md#problem-1",
    ],
    ids=("explicit-html", "markdown-heading", "first-heading", "duplicate-heading"),
)
def test_local_markdown_link_validation_accepts_existing_fragments(target: str) -> None:
    assert local_markdown_link_failures(ROOT / "README.md", [target]) == []


def test_local_markdown_link_validation_accepts_same_document_fragment() -> None:
    assert local_markdown_link_failures(
        ROOT / "README_CN.md", ["#tutorial-01-system"]
    ) == []


@pytest.mark.parametrize(
    "target",
    [
        "README_EN.md#fragment-that-does-not-exist",
        "README_EN.md#problem-6",
    ],
    ids=("missing", "duplicate-heading-out-of-range"),
)
def test_local_markdown_link_validation_rejects_missing_fragments(target: str) -> None:
    assert local_markdown_link_failures(ROOT / "README.md", [target]) == [
        f"missing fragment: {target}"
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
        source_path = ROOT / source
        for failure in local_markdown_link_failures(
            source_path, local_markdown_links(read_doc(source))
        ):
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
PREVIEW_CONTRACT_KEYS = {
    "V1": {
        "intended_content": "content:v1:mask-depth-base3d",
        "source_data": "source:v1:rgb-depth-calibration-mask-points",
        "generation_command": "generator:v1:manifest-calibrated-panel",
        "release_gate": "gate:v1:reproducible-no-manual-edit",
    },
    "V2": {
        "intended_content": "content:v2:occlusion-reacquisition-identity",
        "source_data": "source:v2:replay-tracks-memory-annotations",
        "generation_command": "generator:v2:declared-clips-three-states",
        "release_gate": "gate:v2:heldout-identity-selection",
    },
    "V3": {
        "intended_content": "content:v3:registration-residual-uncertainty",
        "source_data": "source:v3:calibration-correspondence-covariance",
        "generation_command": "generator:v3:aggregate-residual-error-uncertainty",
        "release_gate": "gate:v3:units-aggregation-calibration-exclusions",
    },
    "L1": {
        "intended_content": "content:l1:instruction-candidate-preview-refusal",
        "source_data": "source:l1:scenario-context-candidate-validator-log",
        "generation_command": "generator:l1:auditable-decision-trace",
        "release_gate": "gate:l1:no-secrets-or-actuator-success-claim",
    },
    "E1": {
        "intended_content": "content:e1:baseline-confidence-intervals",
        "source_data": "source:e1:preregistered-results-intervals-slices",
        "generation_command": "generator:e1:aggregate-confidence-interval-plot",
        "release_gate": "gate:e1:baseline-split-interval-exclusions",
    },
    "E2": {
        "intended_content": "content:e2:ablation-table-curve",
        "source_data": "source:e2:controlled-variants-seeds-results",
        "generation_command": "generator:e2:grouped-variant-table-curve",
        "release_gate": "gate:e2:one-delta-controls",
    },
    "E3": {
        "intended_content": "content:e3:accuracy-latency-resource",
        "source_data": "source:e3:metrics-environment-manifest",
        "generation_command": "generator:e3:experiment-metric-tradeoff",
        "release_gate": "gate:e3:comparable-hardware-window",
    },
    "F1": {
        "intended_content": "content:f1:representative-success-failure",
        "source_data": "source:f1:selection-traces-failure-taxonomy",
        "generation_command": "generator:f1:selection-rule-paired-cases",
        "release_gate": "gate:f1:no-cherry-pick-limitations-visible",
    },
}
PREVIEW_CN_VISIBLE_FIELDS = {
    "V1": {
        "intended_content": "Lumos 实例 mask、D435 depth 和机器人基座坐标系 3D 视图",
        "source_data": "带时间戳的 Lumos RGB、D435 depth、calibration ID/hash、实例 masks、registered 3D points、experiment manifest",
        "generation_command": "版本化 script/command 按 manifest 对齐帧、应用记录的 calibration 并渲染已选样本",
        "release_gate": "manifest 和命令无需手工改图即可复现 panel",
    },
    "V2": {
        "intended_content": "遮挡前、遮挡中和重捕获后的身份",
        "source_data": "有序 replay frames、detections/masks、track IDs、association scores、memory state、occlusion annotations、experiment manifest",
        "generation_command": "版本化 script/command 选择声明的 clips，并从 result records 渲染三个状态",
        "release_gate": "clip split 为 held-out，且 identity labels/selection rule 已记录",
    },
    "V3": {
        "intended_content": "深度注册误差、径向标定残差和不确定度视图",
        "source_data": "calibration targets、correspondence/residual records、radial-bin metadata、registration errors、covariance/uncertainty records、manifest",
        "generation_command": "版本化 script/command 将 source JSON/CSV 聚合为残差、误差和不确定度 panels",
        "release_gate": "单位、聚合、calibration ID 和排除样本均已报告",
    },
    "L1": {
        "intended_content": "VLA instruction、visual context、candidate、preview、confirmation 和 refusal reason",
        "source_data": "去标识 scenario input、visual-context reference、structured candidate、preview output、confirmation event、validator/refusal log、manifest",
        "generation_command": "版本化 script/command 从 logs 渲染完整可审计 decision trace",
        "release_gate": "trace 不含 secret、个人信息或误导性的 actuator-success claim",
    },
    "E1": {
        "intended_content": "baseline comparison 和 confidence intervals",
        "source_data": "所有预注册 baselines 的 result records、sample counts、intervals、slices、source CSV/JSON、manifests",
        "generation_command": "版本化 script/command 读取 result records 并计算/绘制声明的 aggregate 和 confidence intervals",
        "release_gate": "baselines、split、interval method 和 exclusions 与矩阵一致",
    },
    "E2": {
        "intended_content": "ablation table/curve",
        "source_data": "controlled-variant result records、variant configuration、seeds、slices、source CSV/JSON、manifests",
        "generation_command": "版本化 script/command 按 variants 分组，生成声明的 table 或 curve",
        "release_gate": "one-delta ablation rule 和所有 controls 均有文档记录",
    },
    "E3": {
        "intended_content": "accuracy-latency-resource trade-off",
        "source_data": "accuracy、P50/P95 latency、FPS、CPU/GPU/VRAM records、hardware/environment manifests、source CSV/JSON",
        "generation_command": "版本化 script/command 按 experiment ID 连接 metrics 并渲染 trade-off points/error bars",
        "release_gate": "hardware、batch/input settings 和 aggregation window 可比较",
    },
    "F1": {
        "intended_content": "representative success/failure cases",
        "source_data": "声明的 case-selection rule、scenario/clip IDs、input/output traces、failure taxonomy、manifests",
        "generation_command": "版本化 script/command 应用 selection rule 并渲染成对 success/failure cases",
        "release_gate": "不可 cherry-pick；limitations 和 refusal/failure context 必须可见",
    },
}
PREVIEW_CONTRACT_KEY_RE = re.compile(
    r"<code>((content|source|generator|gate):([a-z0-9]+):([a-z0-9-]+))</code>"
)
PREVIEW_CODE_TAG_RE = re.compile(r"<code>.*?</code>")
PREVIEW_FIELD_KEY_PREFIXES = {
    "intended_content": "content",
    "source_data": "source",
    "generation_command": "generator",
    "release_gate": "gate",
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
    assert set(registry) == set(PREVIEW_IDS)
    for row in registry.values():
        assert row["status"] == "Planned Evidence"
    return registry


def preview_contract_key(figure_id: str, field: str, value: str) -> str:
    matches = PREVIEW_CONTRACT_KEY_RE.findall(value)
    assert len(matches) == 1
    key, prefix, key_figure_id, slug = matches[0]
    assert prefix == PREVIEW_FIELD_KEY_PREFIXES[field]
    assert key_figure_id == figure_id.lower()
    assert slug
    assert PREVIEW_CODE_TAG_RE.findall(value) == [f"<code>{key}</code>"]
    assert value.count("<code>") == value.count("</code>") == 1
    return key


def normalized_visible_preview_field(figure_id: str, field: str, value: str) -> str:
    preview_contract_key(figure_id, field, value)
    return " ".join(PREVIEW_CODE_TAG_RE.sub("", value).split())


def assert_preview_contract_keys_align(documents: dict[str, str]) -> None:
    assert set(documents) == set(PREVIEW_REGISTRY_PATHS)
    registries = {path: parse_preview_registry(text) for path, text in documents.items()}
    canonical = registries["docs/research/figure_manifest.md"]

    for figure_id in PREVIEW_IDS:
        for field in PREVIEW_FIELD_KEY_PREFIXES:
            canonical_key = preview_contract_key(figure_id, field, canonical[figure_id][field])
            assert canonical_key == PREVIEW_CONTRACT_KEYS[figure_id][field]
            for path in DOCS:
                readme_key = preview_contract_key(
                    figure_id, field, registries[path][figure_id][field]
                )
                assert readme_key == canonical_key


def assert_preview_registry_alignment(documents: dict[str, str]) -> None:
    assert_preview_contract_keys_align(documents)


def assert_preview_visible_semantics(documents: dict[str, str]) -> None:
    assert_preview_contract_keys_align(documents)
    registries = {path: parse_preview_registry(text) for path, text in documents.items()}
    canonical = registries["docs/research/figure_manifest.md"]

    for figure_id in PREVIEW_IDS:
        for field in PREVIEW_FIELD_KEY_PREFIXES:
            canonical_text = normalized_visible_preview_field(
                figure_id, field, canonical[figure_id][field]
            )
            for path in ("README.md", "README_EN.md"):
                assert normalized_visible_preview_field(
                    figure_id, field, registries[path][figure_id][field]
                ) == canonical_text
            assert normalized_visible_preview_field(
                figure_id, field, registries["README_CN.md"][figure_id][field]
            ) == PREVIEW_CN_VISIBLE_FIELDS[figure_id][field]


def preview_registry_documents() -> dict[str, str]:
    return {path: read_doc(path) for path in PREVIEW_REGISTRY_PATHS}


def replace_preview_row_cell(text: str, figure_id: str, column: int, value: str) -> str:
    line = next(line for line in text.splitlines() if line.startswith(f"| {figure_id} |"))
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    cells[column] = value
    replacement = "| " + " | ".join(cells) + " |"
    return text.replace(line, replacement, 1)


def replace_preview_contract_key(text: str, figure_id: str, field: str, replacement: str) -> str:
    column = PREVIEW_FIELDS.index(field)
    old_key = PREVIEW_CONTRACT_KEYS[figure_id][field]
    line = next(line for line in text.splitlines() if line.startswith(f"| {figure_id} |"))
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    cells[column] = cells[column].replace(
        f"<code>{old_key}</code>", f"<code>{replacement}</code>", 1
    )
    replacement_line = "| " + " | ".join(cells) + " |"
    return text.replace(line, replacement_line, 1)


def replace_preview_visible_text(
    text: str, figure_id: str, field: str, removed: str, replacement: str
) -> str:
    column = PREVIEW_FIELDS.index(field)
    line = next(line for line in text.splitlines() if line.startswith(f"| {figure_id} |"))
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    assert removed in cells[column]
    cells[column] = cells[column].replace(removed, replacement, 1)
    replacement_line = "| " + " | ".join(cells) + " |"
    return text.replace(line, replacement_line, 1)


def test_preview_registry_rows_match_the_canonical_evidence_contract() -> None:
    assert_preview_registry_alignment(preview_registry_documents())


def test_preview_registry_machine_keys_match_canonical_fields() -> None:
    assert_preview_contract_keys_align(preview_registry_documents())


def test_preview_registry_visible_fields_match_canonical_contract() -> None:
    assert_preview_visible_semantics(preview_registry_documents())


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


@pytest.mark.parametrize(
    ("figure_id", "field", "replacement"),
    [
        ("V1", "intended_content", "content:v1:incorrect-content"),
        ("V1", "source_data", "source:v1:incorrect-source"),
        ("V1", "generation_command", "generator:v1:incorrect-generator"),
        ("V1", "release_gate", "gate:v1:incorrect-gate"),
    ],
    ids=("intended-key", "source-key", "generator-key", "gate-key"),
)
def test_preview_registry_contract_rejects_readme_key_drift(
    figure_id: str, field: str, replacement: str
) -> None:
    documents = preview_registry_documents()
    documents["README.md"] = replace_preview_contract_key(
        documents["README.md"], figure_id, field, replacement
    )

    with pytest.raises(AssertionError):
        assert_preview_contract_keys_align(documents)


@pytest.mark.parametrize(
    "replacement",
    [
        "",
        "content:v1:mask-depth-base3d</code> <code>content:v1:mask-depth-base3d",
        "source:v1:mask-depth-base3d",
        "content:v2:mask-depth-base3d",
    ],
    ids=("missing", "duplicate", "wrong-field-prefix", "wrong-figure-id"),
)
def test_preview_registry_contract_rejects_malformed_machine_keys(replacement: str) -> None:
    documents = preview_registry_documents()
    documents["README.md"] = replace_preview_contract_key(
        documents["README.md"], "V1", "intended_content", replacement
    )

    with pytest.raises(AssertionError):
        assert_preview_contract_keys_align(documents)


def test_preview_registry_contract_rejects_extra_code_token() -> None:
    documents = preview_registry_documents()
    documents["README.md"] = replace_preview_visible_text(
        documents["README.md"],
        "V1",
        "intended_content",
        "view.",
        "view. <code>not-a-contract-key</code>",
    )

    with pytest.raises(AssertionError):
        assert_preview_contract_keys_align(documents)


def test_preview_registry_key_comparison_rejects_negated_natural_text() -> None:
    documents = preview_registry_documents()
    documents["README_EN.md"] = replace_preview_contract_key(
        documents["README_EN.md"], "V1", "generation_command", "generator:v1:negated"
    ).replace(
        "Versioned script/command joins frames by manifest, applies recorded calibration, "
        "and renders selected samples",
        "No versioned script/command joins frames by manifest, applies recorded calibration, "
        "or renders selected samples",
    )

    with pytest.raises(AssertionError):
        assert_preview_contract_keys_align(documents)


@pytest.mark.parametrize(
    ("path", "figure_id", "field", "removed", "replacement"),
    [
        ("README.md", "V1", "release_gate", "reproduce", "do not reproduce"),
        ("README.md", "V1", "intended_content", "instance mask, ", ""),
        ("README_EN.md", "L1", "intended_content", "confirmation, ", ""),
        ("README.md", "V2", "source_data", "association scores, ", ""),
        ("README_CN.md", "E2", "source_data", "、slices", ""),
        ("README_CN.md", "E3", "release_gate", "batch/input settings 和", ""),
    ],
    ids=("negated-gate", "v1-instance-mask", "l1-confirmation", "v2-scores", "e2-slices", "e3-batch"),
)
def test_preview_registry_contract_rejects_prose_only_drift(
    path: str, figure_id: str, field: str, removed: str, replacement: str
) -> None:
    documents = preview_registry_documents()
    documents[path] = replace_preview_visible_text(
        documents[path], figure_id, field, removed, replacement
    )

    with pytest.raises(AssertionError):
        assert_preview_visible_semantics(documents)


def test_research_schemas_are_valid_json_schema_documents() -> None:
    for path in RESEARCH_FILES[-2:]:
        payload = json.loads(read_doc(path))
        assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert payload["type"] == "object"
        assert payload["additionalProperties"] is False
        assert payload["required"]


def marked_section(text: str, name: str) -> str:
    begin = f"<!-- {name}:BEGIN -->"
    end = f"<!-- {name}:END -->"
    assert text.count(begin) == 1, f"expected one {begin} marker"
    assert text.count(end) == 1, f"expected one {end} marker"
    before, remainder = text.split(begin, 1)
    section, after = remainder.split(end, 1)
    assert end not in before
    assert begin not in after
    return section.strip()


def bash_fenced_blocks(text: str) -> list[str]:
    return [block.strip() for block in re.findall(r"```(?:bash|sh)\n(.*?)\n```", text, re.DOTALL)]


def markdown_tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    lines = text.splitlines()
    tables: list[tuple[list[str], list[list[str]]]] = []
    for index, line in enumerate(lines[:-1]):
        if not (line.startswith("|") and line.endswith("|")):
            continue
        header = markdown_table_cells(line)
        divider = markdown_table_cells(lines[index + 1]) if lines[index + 1].startswith("|") else []
        if len(divider) != len(header) or not is_markdown_table_divider(divider):
            continue
        rows: list[list[str]] = []
        for row_line in lines[index + 2 :]:
            if not (row_line.startswith("|") and row_line.endswith("|")):
                break
            row = markdown_table_cells(row_line)
            assert len(row) == len(header)
            rows.append(row)
        tables.append((header, rows))
    return tables


def marked_contract_rows(text: str, marker: str) -> dict[str, list[str]]:
    tables = markdown_tables(marked_section(text, marker))
    assert len(tables) == 1
    _, rows = tables[0]
    result: dict[str, list[str]] = {}
    for row in rows:
        key = row[0].strip("`")
        assert key not in result
        result[key] = row
    return result


def test_fixed_manual_wrapper_is_the_only_executable_l4_recommendation() -> None:
    wrapper = "bash scripts/demo_fixed_pick_place.sh"
    forbidden_in_executable_blocks = (
        "open_fixed_pick_place_control.sh",
        "/api/start-auto",
        "--real",
    )
    prohibition_tokens = (
        "bash scripts/open_fixed_pick_place_control.sh",
        "<code>prohibited:open-fixed-ui</code>",
        "<code>prohibited:start-auto</code>",
        "<code>prohibited:raw-real-runner</code>",
    )

    for path in DOCS:
        text = read_doc(path)
        recommendation = marked_section(text, "L4-EXECUTABLE-RECOMMENDATION")
        assert bash_fenced_blocks(recommendation) == [wrapper]
        assert [block for block in bash_fenced_blocks(text) if wrapper in block] == [wrapper]
        assert all(
            forbidden not in block
            for block in bash_fenced_blocks(text)
            for forbidden in forbidden_in_executable_blocks
        )
        prohibition = marked_section(text, "L4-PROHIBITIONS")
        assert all(token in prohibition for token in prohibition_tokens)


def test_each_readme_separates_grasp_and_active_view_motion_authority() -> None:
    for path in DOCS:
        rows = marked_contract_rows(read_doc(path), "ACTIVE-VIEW-SAFETY")
        assert set(rows) == {"grasp-lock", "active-view-motion"}

        grasp = " ".join(rows["grasp-lock"])
        assert "<code>visionSafety.robotExecutionEnabled=false</code>" in grasp
        assert "<code>robot_execution_enabled:false</code>" in grasp
        assert "<code>maturity:Planned</code>" in grasp

        active_view = " ".join(rows["active-view-motion"])
        assert "<code>maturity:Implemented/Experimental</code>" in active_view
        assert "<code>ACTIVE_VIEW_EXECUTION_ENABLED=0</code>" in active_view
        assert "<code>authority:approval+catalog+evidence+confirmation</code>" in active_view
        assert "<code>real-hardware-accepted:false</code>" in active_view


def test_each_readme_lists_exact_id_only_active_view_websocket_commands() -> None:
    expected_keys = {
        "start_active_view": "<code>keys:cmd+identityId</code>",
        "confirm_active_view_step": "<code>keys:cmd+sessionId+proposalId</code>",
        "cancel_active_view": "<code>keys:cmd+sessionId</code>",
    }
    for path in DOCS:
        section = marked_section(read_doc(path), "ACTIVE-VIEW-WS-COMMANDS")
        tables = markdown_tables(section)
        assert len(tables) == 1
        _, rows = tables[0]
        commands = {row[0].strip("`"): " ".join(row) for row in rows}
        assert set(commands) == set(expected_keys)
        for command, key_contract in expected_keys.items():
            assert key_contract in commands[command]
        assert "<code>authentication:none</code>" in section
        assert "<code>per-client-ownership:none</code>" in section
        assert "<code>session-scope:shared</code>" in section


def test_each_readme_classifies_active_view_demo_as_l2_only() -> None:
    for path in DOCS:
        section = marked_section(read_doc(path), "ACTIVE-VIEW-L2-DEMO")
        assert bash_fenced_blocks(section) == ["bash scripts/vision/start_active_view_demo.sh"]
        assert "<code>authority:L2-only</code>" in section
        assert "<code>actuator-transport:none</code>" in section


def test_landing_mermaid_separates_runtimes_and_active_view_authority() -> None:
    text = read_doc("README.md")
    mermaid_blocks = re.findall(r"```mermaid\n(.*?)\n```", text, re.DOTALL)
    assert len(mermaid_blocks) == 1
    diagram = mermaid_blocks[0]
    assert 'subgraph PYTHON_RUNTIME["Packaged Python runtime' in diagram
    assert 'subgraph STARTOUCH_RUNTIME["Startouch Web / guarded control runtime' in diagram
    assert "ACTIVE_VIEW_EXECUTION_ENABLED" in diagram
    assert "visionSafety.robotExecutionEnabled" in diagram
    assert "<br/>" in diagram
    assert r"\n" not in diagram


def test_landing_page_dated_measurements_have_incomplete_evidence_status() -> None:
    tables = [
        table
        for table in markdown_tables(read_doc("README.md"))
        if table[0] and table[0][0] == "Date"
    ]
    assert len(tables) == 1
    header, rows = tables[0]
    assert header == ["Date", "Measured record", "Evidence Status", "Source"]
    assert len(rows) == 3
    assert all(row[2] == "Evidence Incomplete / 待补充证据" for row in rows)


def test_active_view_deployment_numbers_have_explicit_incomplete_status() -> None:
    text = read_doc("docs/vision_research/REMIND3D_DEPLOYMENT_RESULTS.md")
    for marker in ("ACTIVE-VIEW-DRY-RUN-EVIDENCE", "ACTIVE-VIEW-CONTROL-EVIDENCE"):
        section = marked_section(text, marker)
        assert "Evidence Incomplete / 待补充证据" in section
        assert "<code>preregistration-readiness:incomplete</code>" in section
        assert "confidence interval" in section
        assert "statistical method" in section


def test_contribution_and_reuse_policy_are_indexed() -> None:
    for path in ("README_CN.md", "README_EN.md"):
        links = local_markdown_links(read_doc(path))
        assert "CONTRIBUTING.md" in links
        assert "docs/research/REUSE_FIRST_ENGINEERING_POLICY.md" in links

    assert "REUSE_FIRST_ENGINEERING_POLICY.md" in local_markdown_links(
        read_doc("docs/research/README.md")
    )
