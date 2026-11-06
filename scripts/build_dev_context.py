"""Build a bounded development snapshot without loading OCR data or models.

Print JSON by default. --output creates a new file under this checkout's
scratch directory. File hashes cover the selected scope, not the pipeline.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MAX_FOCUS_FILES = 12
MAX_FILE_BYTES = 1024 * 1024
DOC_BUDGETS = {
    "AGENTS.md": 6500,
    "CLAUDE.md": 500,
    "docs/development/HANDOFF.md": 5500,
    "docs/development/PROJECT_MAP.md": 8000,
    "docs/development/README.md": 16000,
    "docs/development/templates/SESSION.md": 5000,
}
STARTUP_DOCS = ("AGENTS.md", "CLAUDE.md", "docs/development/HANDOFF.md")


def git(root: Path, *args: str) -> str:
    """Read Git without taking optional index locks or invoking a shell."""
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    result = subprocess.run(["git", *args], cwd=root, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return result.stdout.decode("utf-8")


def parse_status(raw: str) -> list[dict]:
    """Parse NUL-delimited porcelain, including both paths of renames/copies."""
    changes = []
    items = iter(raw.rstrip("\0").split("\0") if raw else [])
    for item in items:
        if len(item) < 4 or item[2] != " ":
            raise ValueError("Invalid Git porcelain record")
        change = {"status": item[:2], "path": item[3:]}
        if "R" in item[:2] or "C" in item[:2]:
            source = next(items, None)
            if not source:
                raise ValueError("Incomplete Git rename/copy record")
            change["source_path"] = source
        changes.append(change)
    return changes


def repo_path(root: Path, name: str) -> Path:
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root) or candidate == root:
        raise ValueError(f"Path must stay inside the checkout: {name}")
    if candidate.relative_to(root).parts[0] == ".git":
        raise ValueError("Git metadata is outside the focus scope")
    return candidate


def file_identity(root: Path, name: str) -> dict:
    path = repo_path(root, name)
    if not path.is_file():
        raise ValueError(f"Select an existing file, not a directory: {name}")
    before = path.stat()
    if before.st_size > MAX_FILE_BYTES:
        raise ValueError(f"File exceeds {MAX_FILE_BYTES} bytes; select a manifest instead: {name}")
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            count += len(chunk)
            if count > MAX_FILE_BYTES:
                raise ValueError(f"File grew beyond the focus limit: {name}")
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size, after.st_mtime_ns, after.st_ino) or count != before.st_size:
        raise ValueError(f"File changed while hashing; retry when stable: {name}")
    return {"path": path.relative_to(root).as_posix(), "bytes": count,
            "sha256": digest.hexdigest()}


def documentation(root: Path) -> dict:
    records = []
    for name, budget in DOC_BUDGETS.items():
        path = repo_path(root, name)
        exists = path.is_file()
        size = path.stat().st_size if exists else None
        record = {"path": name, "exists": exists, "bytes": size, "budget_bytes": budget,
                  "within_budget": exists and size <= budget}
        if exists and size <= MAX_FILE_BYTES:
            record.update(file_identity(root, name))
        records.append(record)
    startup = [item for item in records if item["path"] in STARTUP_DOCS]
    return {"files": records, "budget_pass": all(item["within_budget"] for item in records),
            "suggested_startup_bytes": sum(item["bytes"] for item in startup)
            if all(item["exists"] for item in startup) else None,
            "token_usage": "NOT_MEASURED",
            "scope": "Repository documents only; bytes are not tokens or full chat context."}


def build_context(root: Path, focus: list[str], max_changes: int = 30) -> dict:
    root = root.resolve()
    git_root = Path(git(root, "rev-parse", "--show-toplevel").strip()).resolve()
    if git_root != root:
        raise ValueError("Snapshot root must be the Git checkout root")
    if len(focus) > MAX_FOCUS_FILES:
        raise ValueError(f"Select at most {MAX_FOCUS_FILES} focus files")
    if not 1 <= max_changes <= 100:
        raise ValueError("--max-changes must be between 1 and 100")
    head = git(root, "rev-parse", "HEAD").strip()
    branch = git(root, "branch", "--show-current").strip() or None
    changes = parse_status(git(root, "status", "--porcelain=v1", "-z", "--untracked-files=normal"))
    selected = {}
    for name in focus:
        record = file_identity(root, name)
        selected[record["path"]] = record
    return {
        "schema_version": "development-context-v1",
        "captured_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "git": {"head": head, "branch": branch, "dirty": bool(changes),
                "changes": changes[:max_changes], "change_records_total": len(changes),
                "change_records_omitted": max(0, len(changes) - max_changes),
                "note": "Untracked directories may be grouped; HEAD does not identify uncommitted bytes."},
        "focus_files": list(selected.values()),
        "identity_scope": "Selected files and development documents only; not a full code/runtime fingerprint.",
        "documentation": documentation(root),
        "verification": "NOT_EVALUATED: no tests, inference or ground-truth evaluation executed by this tool.",
    }


def write_snapshot(root: Path, output: str, payload: str) -> Path:
    root = root.resolve()
    scratch = (root / "scratch").resolve()
    target = (root / output).resolve()
    if (not scratch.is_relative_to(root) or not target.is_relative_to(scratch)
            or target == scratch):
        raise ValueError("--output must be a new file inside this checkout's scratch directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--focus", action="append", default=[], metavar="FILE",
                        help="hash one explicit file, at most 12 files of at most 1 MiB each")
    parser.add_argument("--max-changes", type=int, default=30, help="Git change records to include (1..100)")
    parser.add_argument("--output", help="create a new JSON file under scratch; default: print JSON")
    args = parser.parse_args(argv)
    try:
        report = build_context(ROOT, args.focus, args.max_changes)
        payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            target = write_snapshot(ROOT, args.output, payload)
            print(f"Snapshot: {target}; documentation budget pass: {report['documentation']['budget_pass']}")
        else:
            print(payload, end="")
        return 0 if report["documentation"]["budget_pass"] else 1
    except (OSError, UnicodeError, ValueError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.decode("utf-8", "replace")[:1000].strip() if isinstance(
            exc, subprocess.CalledProcessError) else str(exc)
        print(f"Cannot build development context: {detail}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
