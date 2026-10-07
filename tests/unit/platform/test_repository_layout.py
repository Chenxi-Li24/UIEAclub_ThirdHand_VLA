from pathlib import Path
import json
import re
import subprocess


ROOT = Path(__file__).resolve().parents[3]
REQUIRED_TOP_LEVEL_DIRS = {
    "apps",
    "platform",
    "services",
    "skills",
    "drivers",
    "configs",
    "assets",
    "local",
    "runtime",
    "tools",
    "tests",
    "History",
    "docs",
}
TOP_LEVEL_GUIDES = {
    "apps/README.md",
    "assets/README.md",
    "configs/README.md",
    "data/README.md",
    "drivers/README.md",
    "logs/README.md",
    "platform/README.md",
    "services/README.md",
    "skills/README.md",
    "tests/README.md",
    "tools/README.md",
}
PLANNED_MODULE_GUIDES = {
    "platform/authorization/README.md",
    "platform/task_engine/README.md",
    "services/model/README.md",
    "services/model/act/README.md",
    "services/model/diffusion_policy/README.md",
    "services/model/vla/README.md",
    "services/robot/src/policies/README.md",
    "services/supervisor/README.md",
    "skills/vision/active-view/README.md",
}
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def test_required_top_level_directories_exist():
    missing = sorted(name for name in REQUIRED_TOP_LEVEL_DIRS if not (ROOT / name).is_dir())
    assert missing == []


def test_top_level_directories_are_self_describing():
    missing = sorted(path for path in TOP_LEVEL_GUIDES if not (ROOT / path).is_file())
    assert missing == []


def test_planned_module_scaffolds_are_documented_but_not_activated():
    missing = sorted(path for path in PLANNED_MODULE_GUIDES if not (ROOT / path).is_file())
    assert missing == []
    assert (ROOT / "docs" / "MIGRATION_BACKLOG.md").is_file()
    assert not (ROOT / "skills" / "vision" / "active-view" / "manifest.yaml").exists()


def test_root_readmes_link_to_documentation_index():
    assert (ROOT / "docs" / "INDEX.md").is_file()
    for readme in ("README.md", "README_CN.md"):
        assert "docs/INDEX.md" in (ROOT / readme).read_text(encoding="utf-8")


def test_primary_documentation_links_resolve():
    documents = [
        ROOT / "README.md",
        ROOT / "README_CN.md",
        ROOT / "docs" / "DIRECTORY_MAP.md",
        ROOT / "docs" / "INDEX.md",
        *(ROOT / path for path in sorted(TOP_LEVEL_GUIDES)),
        *(ROOT / path for path in sorted(PLANNED_MODULE_GUIDES)),
    ]
    broken = []
    for document in documents:
        for link in MARKDOWN_LINK.findall(document.read_text(encoding="utf-8")):
            target = link.split("#", 1)[0]
            if not target or "://" in target:
                continue
            if not (document.parent / target).resolve().exists():
                broken.append(f"{document.relative_to(ROOT)} -> {link}")
    assert broken == []


def test_legacy_implementations_are_consolidated_under_history():
    forbidden_paths = {
        "archive": ROOT / "archive",
        "migration": ROOT / "migration",
        "web-control": ROOT / "web-control",
        "src/uiea_thirdhand_vla": ROOT / "src" / "uiea_thirdhand_vla",
    }
    remaining = sorted(name for name, path in forbidden_paths.items() if path.exists())
    assert remaining == []


def test_environments_temporary_payloads_and_runtime_state_are_ignored():
    probes = [
        "local/runtimes/python/bin/python",
        "local/scratch/temporary.so",
        "runtime/logs/service.log",
    ]
    result = subprocess.run(
        ["git", "check-ignore", "--", *probes],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert set(result.stdout.splitlines()) == set(probes)


def test_manifest_listed_sdk_library_is_trackable_and_tracked():
    library = "local/sdk/startouch/src/libstartouch.so.24"
    manifest = json.loads(
        (ROOT / "configs/assets/runtime-assets.json").read_text(encoding="utf-8")
    )
    assert library in {entry["path"] for entry in manifest["files"]}
    ignored = subprocess.run(
        ["git", "check-ignore", "--no-index", "--verbose", "--non-matching", "--stdin", "-z"],
        cwd=ROOT,
        input=library.encode("utf-8") + b"\0",
        capture_output=True,
        check=False,
    )
    assert ignored.returncode in (0, 1), ignored.stderr
    # Older Git reports negated matches as success; inspect the actual rule.
    fields = ignored.stdout.decode("utf-8").split("\0")
    assert len(fields) == 5
    assert fields[3] == library
    assert fields[2] == "" or fields[2].startswith("!"), fields[2]
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", library],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert tracked.returncode == 0, tracked.stderr
    assert tracked.stdout.splitlines() == [library]


def test_each_skill_manifest_has_protocol_document():
    missing = sorted(
        path.parent.relative_to(ROOT).as_posix()
        for path in (ROOT / "skills").glob("*/*/manifest.yaml")
        if not (path.parent / "SKILL.md").is_file()
    )
    assert missing == []
