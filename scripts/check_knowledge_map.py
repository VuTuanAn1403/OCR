"""Check the v8 knowledge map: registry, backlog, documents, skill and budgets.

`cai tien v2/10_TRANG_THAI_V8.json` is the single source of project status.
This tool never measures OCR quality. It verifies that every status claim
points at existing evidence, that generated tables match the registry and
that documents stay within their byte budgets.

Exit codes: 0 = no errors, 1 = errors (or STALE with --require-fresh),
2 = the check could not run (missing/invalid registry, Git failure).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

try:
    from scripts import build_dev_context as dev_context
except ImportError:  # executed as `python scripts/check_knowledge_map.py`
    import build_dev_context as dev_context


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "ocr-v8-knowledge-map-v1"
V8_DIR = "cai tien v2"
REGISTRY = f"{V8_DIR}/10_TRANG_THAI_V8.json"
BACKLOG = f"{V8_DIR}/06_BACKLOG_V8.csv"
ARCHIVE_DOC = f"{V8_DIR}/09_LUU_TRU_CAI_TIEN_V7.md"
SKILL_DIR = ".claude/skills/ocr-pdf-knowledge-map"
VERSION_FILE = "src/ocr_runtime/version.py"
RENDER_TARGETS = {"gaps": f"{V8_DIR}/02_KIEM_TOAN_KHOANG_TRONG.md",
                  "phases": f"{V8_DIR}/03_LO_TRINH_V8_THEO_TANG.md"}
# Pointer documents edited for v8; missing link targets fail unless Git ignores them.
POINTER_DOCS = ("AGENTS.md", "docs/development/PROJECT_MAP.md",
                "docs/development/README.md", "docs/development/HANDOFF.md")
# Historical records may still name the deleted folder.
LEGACY_EXEMPT = ("CLEANUP_REPORT.md", "docs/development/HUONG_DAN_COMMIT_VA_PUSH_GITHUB.md",
                 ARCHIVE_DOC)
LEGACY_PREFIX = "Cai Tien/"

CAPABILITY = {"IMPLEMENTED", "PARTIAL", "MISSING", "BROKEN"}
LABELS = {"VERIFIED", "HYPOTHESIS", "NOT_EVALUATED", "STALE"}
WORK_STATUS = {"TODO", "IN_PROGRESS", "BLOCKED", "DONE", "REJECTED"}
PRIORITIES = {"P0", "P1", "P2", "P3"}
QUALITY = {"NOT_EVALUATED", "PASS", "FAIL", "INCONCLUSIVE"}
GT_KINDS = {"HUMAN_ADJUDICATED", "SYNTHETIC_BY_CONSTRUCTION", "BORN_DIGITAL_VERIFIED"}
BACKLOG_HEADER = ["id", "title_vi", "layer", "gap_group", "qa_ref", "legacy_ref", "type",
                  "priority", "status", "blocked_by", "files", "tests", "exit_gate", "evidence"]
BACKLOG_ID = re.compile(r"^V8-\d{3}$")
LINK = re.compile(r"\[[^\]]*\]\((<[^>]+>|[^)\s]+)(?:\s+\"[^\"]*\")?\)")
LINE_REF = re.compile(r"\.py:\d+")
TOKEN_CLAIM = re.compile(r"\d[\d.,]*\s*[kK]?\s*tokens?\b|tiết kiệm[^\n]{0,40}?\d+(?:[.,]\d+)?\s*%",
                         re.IGNORECASE)
ARCHIVE_CMD = re.compile(r'git show ([0-9a-f]{7,40}):"([^"]+)"')
HEX40 = re.compile(r"^[0-9a-f]{40}$")
URL = re.compile(r"^(?:[a-z][a-z0-9+.-]*://|mailto:|tel:|data:)", re.IGNORECASE)
TEXT_SUFFIXES = {".md", ".csv", ".json", ".txt", ".py", ".yaml", ".yml"}


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    not_evaluated: list[str] = field(default_factory=list)
    freshness: str = "NOT_EVALUATED"

    def exit_code(self, require_fresh: bool = False) -> int:
        return 1 if self.errors or (require_fresh and (self.stale or self.not_evaluated)) else 0


def run_git(root: Path, *args: str, data: bytes | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    return subprocess.run(["git", *args], cwd=root, env=env, input=data,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def exact_exists(root: Path, rel: str) -> bool:
    """Case-exact existence, so Windows results match Linux CI."""
    current = root
    for part in PurePosixPath(rel).parts:
        if part in ("", "."):
            continue
        if part == ".." or not current.is_dir() or part not in os.listdir(current):
            return False
        current = current / part
    return True


def ignored_paths(root: Path, paths) -> set[str]:
    paths = sorted({p for p in paths if p})
    if not paths:
        return set()
    result = run_git(root, "check-ignore", "-z", "--stdin", data="\0".join(paths).encode("utf-8"))
    if result.returncode not in (0, 1):
        raise ValueError("git check-ignore failed: " + result.stderr.decode("utf-8", "replace"))
    return {item for item in result.stdout.decode("utf-8").split("\0") if item}


def sha256_file(path: Path) -> str:
    """Hash text with LF line endings so Windows (autocrlf) and Linux agree."""
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def is_shallow(root: Path) -> bool:
    result = run_git(root, "rev-parse", "--is-shallow-repository")
    return result.returncode == 0 and result.stdout.decode().strip() == "true"


def sha256_git_blob(root: Path, commit: str, rel: str) -> str | None:
    """Hash a file as stored in a commit, LF-normalized like sha256_file; None if absent."""
    result = run_git(root, "cat-file", "blob", f"{commit}:{rel}")
    if result.returncode != 0:
        return None
    data = result.stdout
    if PurePosixPath(rel).suffix.lower() in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def symbol_defined(path: Path, symbol: str) -> bool:
    text = read_text(path)
    if path.suffix != ".py":
        return symbol in text
    name = re.escape(symbol.split(".")[-1])
    pattern = rf"^\s*(?:async\s+def|def|class)\s+{name}\b|^\s*{name}\s*(?::[^=\n]+)?="
    return re.search(pattern, text, re.MULTILINE) is not None


def pipeline_version(root: Path) -> str | None:
    match = re.search(r'^PIPELINE_VERSION\s*=\s*"([^"]+)"', read_text(root / VERSION_FILE), re.MULTILINE)
    return match.group(1) if match else None


def load_registry(root: Path) -> dict:
    path = root / REGISTRY
    if not path.is_file():
        raise ValueError(f"Registry not found: {REGISTRY}")
    registry = json.loads(read_text(path))
    if not isinstance(registry, dict) or registry.get("schema_version") != SCHEMA:
        raise ValueError(f"Registry schema must be {SCHEMA}")
    check_shape(registry)
    return registry


def check_shape(registry: dict) -> None:
    """Reject wrong JSON types early so they are usage errors (exit 2), not tracebacks."""
    def need(condition: bool, where: str) -> None:
        if not condition:
            raise ValueError(f"Registry field has the wrong type: {where}")

    for key in ("program_label", "pipeline_version", "verified_head", "last_verified", "verified_scope"):
        need(isinstance(registry.get(key), str), key)
    for key in ("sources", "layers", "gaps", "phases", "exports"):
        need(isinstance(registry.get(key), list) and all(isinstance(x, dict) for x in registry[key]), key)
    gate = registry.get("diacritic_gate")
    need(isinstance(gate, dict), "diacritic_gate")
    owners = [*registry["layers"], *registry["gaps"], gate]
    for entry in [*owners, *registry["phases"]]:
        for key in ("id", "name", "title", "status", "capability", "quality"):
            need(entry.get(key) is None or isinstance(entry.get(key), str), key)
        need(isinstance(entry.get("backlog", []), list)
             and all(isinstance(x, str) for x in entry.get("backlog", [])), "backlog")
    for entry in owners:
        evidence = entry.get("evidence", [])
        need(isinstance(evidence, list) and all(isinstance(x, dict) for x in evidence), "evidence")
        need(isinstance(entry.get("gt_evidence") or [], list), "gt_evidence")


def load_backlog(root: Path, report: Report) -> list[dict]:
    path = root / BACKLOG
    if not path.is_file():
        report.errors.append(f"Backlog not found: {BACKLOG}")
        return []
    reader = csv.reader(io.StringIO(path.read_bytes().decode("utf-8-sig")))
    rows = list(reader)
    if not rows or rows[0] != BACKLOG_HEADER:
        report.errors.append("Backlog header must be: " + ",".join(BACKLOG_HEADER))
        return []
    return [dict(zip(BACKLOG_HEADER, row)) for row in rows[1:] if any(cell.strip() for cell in row)]


def split_list(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(";") if item.strip()]


def check_backlog(root: Path, rows: list[dict], report: Report) -> set[str]:
    ids: set[str] = set()
    for row in rows:
        item = row.get("id", "")
        if not BACKLOG_ID.match(item):
            report.errors.append(f"Backlog id must match V8-NNN: {item!r}")
        elif item in ids:
            report.errors.append(f"Duplicate backlog id: {item}")
        ids.add(item)
        if row.get("priority") not in PRIORITIES:
            report.errors.append(f"{item}: priority must be one of {sorted(PRIORITIES)}")
        if row.get("status") not in WORK_STATUS:
            report.errors.append(f"{item}: status must be one of {sorted(WORK_STATUS)}")
        if row.get("status") == "DONE" and not row.get("evidence", "").strip():
            report.errors.append(f"{item}: DONE needs evidence")
        for column in ("files", "tests"):
            for rel in split_list(row.get(column, "")):
                if not rel.startswith("planned:") and not exact_exists(root, rel.split("::")[0]):
                    report.errors.append(f"{item}: {column} path does not exist: {rel}")
    for row in rows:
        for ref in split_list(row.get("blocked_by", "")):
            if ref not in ids:
                report.errors.append(f"{row.get('id')}: blocked_by unknown id {ref}")
    return ids


def evidence_paths(registry: dict) -> list[str]:
    paths = []
    for group in ("layers", "gaps"):
        for entry in registry.get(group, []):
            paths += [item.get("path", "") for item in entry.get("evidence", [])]
    paths += [item.get("path", "") for item in registry.get("diacritic_gate", {}).get("evidence", [])]
    return paths


def check_evidence(root: Path, owner: str, items: list, ignored: set[str], report: Report) -> int:
    """Return the number of tracked, existing evidence entries."""
    usable = 0
    for item in items:
        rel, label = item.get("path"), item.get("label")
        if label not in LABELS:
            report.errors.append(f"{owner}: evidence label must be one of {sorted(LABELS)}")
        if not rel:
            report.errors.append(f"{owner}: evidence without path")
            continue
        if item.get("local_only"):
            if not exact_exists(root, rel):
                report.warnings.append(f"{owner}: local-only evidence absent here: {rel}")
            continue
        if rel in ignored:
            report.errors.append(f"{owner}: evidence is Git-ignored; mark local_only: {rel}")
            continue
        if not exact_exists(root, rel):
            report.errors.append(f"{owner}: evidence path does not exist: {rel}")
            continue
        symbol = item.get("symbol")
        if symbol and not symbol_defined(root / rel, symbol):
            report.errors.append(f"{owner}: symbol {symbol} not defined in {rel}")
            continue
        usable += 1
    return usable


def check_quality(root: Path, owner: str, entry: dict, key: str, report: Report) -> None:
    quality = entry.get(key, "NOT_EVALUATED")
    if quality not in QUALITY:
        report.errors.append(f"{owner}: {key} must be one of {sorted(QUALITY)}")
    elif quality != "NOT_EVALUATED":
        gt = entry.get("gt_evidence") or []
        if not gt or not all(exact_exists(root, rel) for rel in gt):
            report.errors.append(f"{owner}: {key}={quality} needs existing gt_evidence")
        if entry.get("gt_source_kind") not in GT_KINDS:
            report.errors.append(f"{owner}: gt_source_kind must be one of {sorted(GT_KINDS)}")


def check_registry(root: Path, registry: dict, backlog_ids: set[str], report: Report) -> None:
    version = pipeline_version(root)
    if registry.get("pipeline_version") != version:
        report.errors.append(f"pipeline_version {registry.get('pipeline_version')!r} != {VERSION_FILE} {version!r}")
    ignored = ignored_paths(root, evidence_paths(registry))
    for source in registry.get("sources", []):
        rel = source.get("path", "")
        preserved = source.get("git_preserved")
        if not exact_exists(root, rel) and isinstance(preserved, dict):
            # Removed from the working tree by the user; the mapped bytes must still be
            # readable from the named commit (`git show <commit>:<path>`).
            commit = str(preserved.get("commit", ""))
            if run_git(root, "cat-file", "-e", f"{commit}^{{commit}}").returncode and is_shallow(root):
                # A shallow clone (CI checkout depth 1) lacks the commit: unverifiable, not missing.
                report.not_evaluated.append(f"Preserved source commit {commit[:7]} is not in this shallow clone: {rel}")
                continue
            stored = sha256_git_blob(root, commit, rel)
            if stored is None:
                report.errors.append(f"Source document missing and not in commit {commit}: {rel}")
            elif stored != source.get("sha256"):
                report.errors.append(f"Preserved source differs from its mapped sha256: {rel}")
        elif not exact_exists(root, rel):
            report.errors.append(f"Source document missing: {rel}")
        elif sha256_file(root / rel) != source.get("sha256"):
            report.stale.append(f"Source document changed since mapping: {rel}")
    for group, status_key in (("layers", "capability"), ("gaps", "status")):
        for entry in registry.get(group, []):
            owner = f"{group}:{entry.get('id')}"
            status = entry.get(status_key)
            if status not in CAPABILITY:
                report.errors.append(f"{owner}: {status_key} must be one of {sorted(CAPABILITY)}")
            usable = check_evidence(root, owner, entry.get("evidence", []), ignored, report)
            if status in {"IMPLEMENTED", "PARTIAL", "BROKEN"} and not usable:
                report.errors.append(f"{owner}: {status} needs tracked evidence")
            if status == "MISSING" and not entry.get("searched"):
                report.errors.append(f"{owner}: MISSING needs the search that was run")
            check_quality(root, owner, entry, "quality", report)
    gate = registry.get("diacritic_gate", {})
    check_evidence(root, "diacritic_gate", gate.get("evidence", []), ignored, report)
    check_quality(root, "diacritic_gate", gate, "status", report)
    for phase in registry.get("phases", []):
        if phase.get("status") not in WORK_STATUS:
            report.errors.append(f"phases:{phase.get('id')}: status must be one of {sorted(WORK_STATUS)}")
    for group in ("layers", "gaps", "phases"):
        for entry in registry.get(group, []):
            for ref in entry.get("backlog", []):
                if ref not in backlog_ids:
                    report.errors.append(f"{group}:{entry.get('id')}: unknown backlog id {ref}")
    for export in registry.get("exports", []):
        rel = export.get("path", "")
        if not exact_exists(root, rel):
            report.errors.append(f"Export missing: {rel}")
            continue
        if sha256_file(root / rel) != export.get("sha256"):
            report.stale.append(f"Export bytes differ from the registry: {rel}")
        for source in export.get("sources", []):
            src = source.get("path", "")
            if not exact_exists(root, src) or sha256_file(root / src) != source.get("sha256"):
                report.stale.append(f"Export {rel} is older than its source {src}")


def check_freshness(root: Path, registry: dict, report: Report) -> str:
    head = run_git(root, "rev-parse", "HEAD")
    if head.returncode:
        raise ValueError("Cannot read Git HEAD")
    head_sha = head.stdout.decode().strip()
    verified = registry.get("verified_head", "")
    if not HEX40.match(verified):
        report.errors.append("verified_head must be a 40-character commit id")
        return head_sha
    if verified == head_sha:
        report.freshness = "FRESH"
        return head_sha
    if run_git(root, "cat-file", "-e", f"{verified}^{{commit}}").returncode:
        report.not_evaluated.append(f"verified_head {verified[:7]} is not in this clone")
        return head_sha
    tracked = sorted({p for p in evidence_paths(registry) if p})
    diff = run_git(root, "diff", "--name-only", verified, head_sha, "--", *tracked)
    if diff.returncode:
        raise ValueError("git diff failed: " + diff.stderr.decode("utf-8", "replace"))
    changed = [line for line in diff.stdout.decode("utf-8").splitlines() if line]
    if changed:
        # A commit cannot contain its own id, so only changed evidence makes the map stale.
        report.freshness = "STALE"
        report.stale.append(f"verified_head {verified[:7]} != HEAD {head_sha[:7]}; "
                            f"evidence changed: {', '.join(changed[:10])}")
    else:
        report.freshness = "FRESH_EVIDENCE_UNCHANGED"
    return head_sha


def link_targets(text: str):
    for match in LINK.finditer(text):
        target = match.group(1).strip("<>")
        if URL.match(target):
            continue  # web, mail and data links are not checkout paths
        yield target


def heading_anchors(text: str) -> set[str]:
    anchors = set(re.findall(r'<a id="([^"]+)"', text))
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*$", text, re.MULTILINE):
        anchors.add(re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-"))
    return anchors


def resolve_link(doc: str, target: str) -> tuple[str, str]:
    path_part, _, anchor = target.partition("#")
    path_part = urllib.parse.unquote(path_part)
    path_part = re.sub(r":\d+(?::\d+)?$", "", path_part)
    if not path_part:
        return doc, anchor
    resolved = os.path.normpath(str(PurePosixPath(doc).parent / path_part)).replace("\\", "/")
    return resolved, anchor


def is_legacy(resolved: str) -> bool:
    return resolved == LEGACY_PREFIX.rstrip("/") or resolved.startswith(LEGACY_PREFIX)


def outside(resolved: str) -> bool:
    return resolved == ".." or resolved.startswith(("../", "/")) or bool(re.match(r"^[A-Za-z]:", resolved))


def check_links(root: Path, docs: list[str], report: Report) -> None:
    pending = []
    for doc in docs:
        text = read_text(root / doc)
        for target in link_targets(text):
            resolved, anchor = resolve_link(doc, target)
            pending.append((doc, target, resolved, anchor))
    ignored = ignored_paths(root, [item[2] for item in pending if not outside(item[2])])
    for doc, target, resolved, anchor in pending:
        if is_legacy(resolved):
            report.errors.append(f"{doc}: link into deleted folder: {target}")
        elif outside(resolved):
            report.errors.append(f"{doc}: link leaves the checkout: {target}")
        elif not exact_exists(root, resolved):
            (report.warnings if resolved in ignored else report.errors).append(
                f"{doc}: link target not found: {target}")
        elif anchor and resolved.endswith(".md") and resolved in docs:
            if anchor not in heading_anchors(read_text(root / resolved)):
                report.errors.append(f"{doc}: anchor #{anchor} not found in {resolved}")


def legacy_link_docs(root: Path) -> list[str]:
    listed = run_git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.md")
    if listed.returncode:
        raise ValueError("git ls-files failed")
    names = {item for item in listed.stdout.decode("utf-8").split("\0") if item}
    return sorted(name for name in names if name not in LEGACY_EXEMPT and exact_exists(root, name))


def check_legacy_links(root: Path, report: Report, checked: set[str]) -> None:
    for doc in legacy_link_docs(root):
        if doc in checked:
            continue
        for target in link_targets(read_text(root / doc)):
            if is_legacy(resolve_link(doc, target)[0]):
                report.errors.append(f"{doc}: link into deleted folder: {target}")


def map_documents(root: Path, registry: dict) -> list[str]:
    sources = {item.get("path") for item in registry.get("sources", [])}
    names = []
    for base in (V8_DIR, SKILL_DIR):
        folder = root / base
        if folder.is_dir():
            for path in sorted(folder.rglob("*")):
                rel = path.relative_to(root).as_posix()
                if path.is_file() and path.suffix in {".md", ".csv", ".json"} and rel not in sources:
                    names.append(rel)
    return names


def check_text_rules(root: Path, names: list[str], report: Report) -> None:
    for rel in names:
        lines = read_text(root / rel).splitlines()
        strict = rel == REGISTRY or rel.startswith(SKILL_DIR + "/")
        for number, line in enumerate(lines, 1):
            if TOKEN_CLAIM.search(line) and "NOT_MEASURED" not in line:
                report.errors.append(f"{rel}:{number}: unmeasured token claim")
            if strict and LINE_REF.search(line):
                report.errors.append(f"{rel}:{number}: use path::symbol, not .py line numbers")


def check_skill(root: Path, report: Report) -> None:
    path = root / SKILL_DIR / "SKILL.md"
    if not path.is_file():
        report.errors.append(f"Skill missing: {SKILL_DIR}/SKILL.md")
        return
    match = re.match(r"^---\n(.*?)\n---\n", read_text(path), re.DOTALL)
    if not match:
        report.errors.append("SKILL.md needs YAML frontmatter")
        return
    meta = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith(" "):
            meta[key.strip()] = value.strip().strip('"').strip("'")
    expected = PurePosixPath(SKILL_DIR).name
    if meta.get("name") != expected or not re.fullmatch(r"[a-z0-9-]{1,64}", meta.get("name", "")):
        report.errors.append(f"SKILL.md name must be {expected}")
    description = meta.get("description", "")
    if not description or len(description) > 1024:
        report.errors.append("SKILL.md description must have 1..1024 characters")


def check_archive(root: Path, report: Report) -> None:
    path = root / ARCHIVE_DOC
    if not path.is_file():
        report.errors.append(f"Archive index missing: {ARCHIVE_DOC}")
        return
    commands = ARCHIVE_CMD.findall(read_text(path))
    if not commands:
        report.errors.append("Archive index lists no git show commands")
    for rev, rel in commands:
        if run_git(root, "cat-file", "-e", f"{rev}:{rel}").returncode == 0:
            continue
        if run_git(root, "cat-file", "-e", f"{rev}^{{commit}}").returncode:
            report.not_evaluated.append(f"Archive commit {rev} is not in this clone")
            return
        report.errors.append(f"Archive path not in {rev}: {rel}")


def check_budgets(root: Path, names: list[str], report: Report) -> None:
    docs = dev_context.documentation(root)
    for record in docs["files"]:
        if not record["exists"]:
            report.errors.append(f"Budgeted document missing: {record['path']}")
        elif not record["within_budget"]:
            report.errors.append(f"{record['path']}: {record['bytes']} B over budget {record['budget_bytes']} B")
    for rel in names:
        if rel not in dev_context.DOC_BUDGETS:
            report.errors.append(f"No DOC_BUDGETS entry: {rel}")


# ---- generated tables -------------------------------------------------------

def _cell(text) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def _evidence_cell(items: list) -> str:
    shown = [f"`{item['path']}{'::' + item['symbol'] if item.get('symbol') else ''}`"
             for item in items[:2] if item.get("path")]
    return "; ".join(shown) or "—"


def render_block(registry: dict, name: str) -> str:
    if name == "gaps":
        lines = ["| Nhóm | Năng lực | Chất lượng | Bằng chứng chính | QA | Backlog |",
                 "| --- | --- | --- | --- | --- | --- |"]
        for gap in registry.get("gaps", []):
            lines.append(f"| {gap.get('id')} {_cell(gap.get('title'))} | {gap.get('status')} | "
                         f"{gap.get('quality', 'NOT_EVALUATED')} | {_evidence_cell(gap.get('evidence', []))} | "
                         f"{_cell(', '.join(gap.get('qa_ref', [])) or '—')} | "
                         f"{_cell(', '.join(gap.get('backlog', [])) or '—')} |")
    else:
        lines = ["| Pha | Tên | Trạng thái | Cổng ra | Backlog |", "| --- | --- | --- | --- | --- |"]
        for phase in registry.get("phases", []):
            lines.append(f"| {phase.get('id')} | {_cell(phase.get('title'))} | {phase.get('status')} | "
                         f"{_cell(phase.get('exit_gate'))} | {_cell(', '.join(phase.get('backlog', [])) or '—')} |")
    return "\n".join(lines)


def _markers(name: str) -> tuple[str, str]:
    return f"<!-- v8-status:{name}:begin -->", f"<!-- v8-status:{name}:end -->"


def replace_block(text: str, name: str, body: str) -> str | None:
    begin, end = _markers(name)
    start, stop = text.find(begin), text.find(end)
    if start < 0 or stop < start:
        return None
    return text[:start + len(begin)] + "\n" + body + "\n" + text[stop:]


def check_rendered(root: Path, registry: dict, report: Report) -> None:
    for name, rel in RENDER_TARGETS.items():
        if not (root / rel).is_file():
            report.errors.append(f"Rendered document missing: {rel}")
            continue
        text = read_text(root / rel)
        expected = replace_block(text, name, render_block(registry, name))
        if expected is None:
            report.errors.append(f"{rel}: markers for {name} block are missing")
        elif expected != text:
            report.errors.append(f"{rel}: {name} table differs from registry; run --render")


def render(root: Path, registry: dict) -> list[str]:
    written = []
    for name, rel in RENDER_TARGETS.items():
        path = root / rel
        text = read_text(path)
        updated = replace_block(text, name, render_block(registry, name))
        if updated is None:
            raise ValueError(f"{rel}: markers for {name} block are missing")
        if updated != text:
            path.write_text(updated, encoding="utf-8", newline="\n")
            written.append(rel)
    return written


# ---- entry points -----------------------------------------------------------

def check(root: Path) -> tuple[Report, dict, list[dict], str]:
    root = root.resolve()
    report = Report()
    registry = load_registry(root)
    head = check_freshness(root, registry, report)
    backlog = load_backlog(root, report)
    ids = check_backlog(root, backlog, report)
    check_registry(root, registry, ids, report)
    names = map_documents(root, registry)
    check_text_rules(root, names, report)
    link_docs = [rel for rel in names if rel.endswith(".md")]
    link_docs += [rel for rel in POINTER_DOCS if exact_exists(root, rel)]
    check_links(root, link_docs, report)
    check_legacy_links(root, report, set(link_docs))
    check_skill(root, report)
    check_archive(root, report)
    check_rendered(root, registry, report)
    check_budgets(root, names, report)
    return report, registry, backlog, head


def summary(registry: dict, backlog: list[dict], report: Report, head: str) -> str:
    def cell(value, width: int = 0) -> str:
        return f"{'' if value is None else value!s:<{width}}"

    verified = registry.get("verified_head", "")
    lines = [f"{registry.get('program_label')} | schema {SCHEMA}",
             f"PIPELINE_VERSION {registry.get('pipeline_version')} | HEAD {head[:7]} | "
             f"verified_head {verified[:7]} ({report.freshness}) | last_verified {registry.get('last_verified')}",
             f"Phạm vi xác minh: {registry.get('verified_scope')}", "", "Khoảng trống (năng lực / chất lượng):"]
    for gap in registry.get("gaps", []):
        lines.append(f"  {cell(gap.get('id'), 4)} {cell(gap.get('status'), 12)} "
                     f"{cell(gap.get('quality', 'NOT_EVALUATED'), 14)} {cell(gap.get('title'))}")
    lines += ["", "Tầng pipeline (năng lực / chất lượng):"]
    for layer in registry.get("layers", []):
        lines.append(f"  {cell(layer.get('id'), 4)} {cell(layer.get('capability'), 12)} "
                     f"{cell(layer.get('quality', 'NOT_EVALUATED'), 14)} {cell(layer.get('name'))}")
    gate = registry.get("diacritic_gate", {})
    lines += ["", f"Cổng dấu {gate.get('target')}: {gate.get('status')} — {gate.get('blocker', '')}", "",
              "Lộ trình:"]
    for phase in registry.get("phases", []):
        lines.append(f"  {cell(phase.get('id'), 4)} {cell(phase.get('status'), 12)} {cell(phase.get('title'))}")
    counts: dict[str, int] = {}
    for row in backlog:
        counts[row.get("status", "?")] = counts.get(row.get("status", "?"), 0) + 1
    next_items = [f"{row['id']} {row['title_vi']}" for row in backlog
                  if row.get("status") in {"TODO", "IN_PROGRESS"} and row.get("priority") == "P0"][:5]
    lines += ["", "Backlog: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
              "P0 đang mở: " + ("; ".join(next_items) or "—"), "",
              f"Kiểm tra: {len(report.errors)} lỗi, {len(report.warnings)} cảnh báo, "
              f"{len(report.stale)} STALE, {len(report.not_evaluated)} NOT_EVALUATED"]
    for label, items in (("LỖI", report.errors), ("STALE", report.stale),
                         ("NOT_EVALUATED", report.not_evaluated), ("CẢNH BÁO", report.warnings)):
        lines += [f"  {label}: {item}" for item in items[:20]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate only (default)")
    mode.add_argument("--summary", action="store_true", help="print the project status from the registry")
    mode.add_argument("--render", action="store_true", help="rewrite generated tables, then validate")
    parser.add_argument("--require-fresh", action="store_true", help="fail when the map is STALE")
    parser.add_argument("--output", help="also write a JSON report as a new file under scratch")
    args = parser.parse_args(argv)
    try:
        if args.render:
            for rel in render(ROOT, load_registry(ROOT)):
                print(f"Rendered: {rel}")
        report, registry, backlog, head = check(ROOT)
        if args.output:
            payload = {"schema_version": "knowledge-map-check-v1", "head": head,
                       "verified_head": registry.get("verified_head"), **asdict(report),
                       "quality_claims": "NOT_EVALUATED: this tool checks references, not OCR accuracy."}
            dev_context.write_snapshot(ROOT, args.output, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        if args.summary:
            print(summary(registry, backlog, report, head))
        else:
            for label, items in (("ERROR", report.errors), ("STALE", report.stale),
                                 ("NOT_EVALUATED", report.not_evaluated), ("WARNING", report.warnings)):
                for item in items:
                    print(f"{label}: {item}")
            print(f"Knowledge map: {len(report.errors)} errors, {len(report.warnings)} warnings, "
                  f"{len(report.stale)} stale, {len(report.not_evaluated)} not evaluated")
        return report.exit_code(args.require_fresh)
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError) as exc:
        print(f"Cannot check knowledge map: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
