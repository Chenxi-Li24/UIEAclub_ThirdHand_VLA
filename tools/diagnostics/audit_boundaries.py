#!/usr/bin/env python3
"""Audit source and Git boundaries without modifying repository state."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import subprocess


FORMAL_ROOTS = ("apps", "platform", "services", "skills", "drivers", "tools")
HOME_PATH = re.compile(r"/home/[A-Za-z_][A-Za-z0-9_-]*/")
ARCHIVE_DIRECTORY = "archive" + "/"
ARCHIVE_EXECUTABLE_REFERENCE = re.compile(
    r"\b(import|from|require|spawn|exec|command)\b[^\n]*" + re.escape(ARCHIVE_DIRECTORY),
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    line: int
    detail: str


def _tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.splitlines()


def _text_lines(path: Path) -> list[str]:
    try:
        payload = path.read_bytes()
    except OSError:
        return []
    if b"\0" in payload[:8192]:
        return []
    try:
        return payload.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return []


def _inside(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def audit_repository(root: Path) -> list[Violation]:
    """Scan formal text source and repository boundaries without following symlinks."""
    root = root.resolve()
    violations: list[Violation] = []

    for root_name in FORMAL_ROOTS:
        formal_root = root / root_name
        if not formal_root.exists():
            continue
        for candidate in formal_root.rglob("*"):
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                resolved = candidate.resolve(strict=False)
                if not _inside(root, resolved):
                    violations.append(Violation("external_symlink", relative, 0, str(resolved)))
                continue
            if not candidate.is_file():
                continue
            for line_number, line in enumerate(_text_lines(candidate), 1):
                if HOME_PATH.search(line):
                    violations.append(
                        Violation("absolute_home_path", relative, line_number, line.strip())
                    )
                if ARCHIVE_EXECUTABLE_REFERENCE.search(line):
                    violations.append(
                        Violation("archive_runtime_dependency", relative, line_number, line.strip())
                    )

    for tracked in _tracked_files(root):
        if tracked.startswith("local/") and tracked != "local/README.md":
            violations.append(Violation("tracked_local_payload", tracked, 0, "local payload tracked"))
        if tracked.startswith("runtime/") and tracked != "runtime/README.md":
            violations.append(
                Violation("tracked_runtime_payload", tracked, 0, "runtime payload tracked")
            )

    return sorted(violations, key=lambda item: (item.path, item.line, item.code))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    violations = audit_repository(args.root)
    report = {"ok": not violations, "violations": [asdict(item) for item in violations]}
    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        for item in violations:
            print(f"{item.code}: {item.path}:{item.line}: {item.detail}")
        if not violations:
            print("repository boundaries: ready")
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
