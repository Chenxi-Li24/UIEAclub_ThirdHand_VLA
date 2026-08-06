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


def test_research_schemas_are_valid_json_schema_documents() -> None:
    for path in RESEARCH_FILES[-2:]:
        payload = json.loads(read_doc(path))
        assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert payload["type"] == "object"
        assert payload["additionalProperties"] is False
        assert payload["required"]
