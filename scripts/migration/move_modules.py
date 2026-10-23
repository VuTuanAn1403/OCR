"""Move modules from the legacy `src.ocr` namespace into `ocr_*` packages.

Usage: python scripts/migration/move_modules.py STAGE OLD=NEW [OLD=NEW ...]

For each pair the module source moves to `src/<new path>.py` and the old file
becomes a `sys.modules` alias of the new module (same object, so imports,
`mock.patch` targets and isinstance checks keep working). Imports of moved
modules are rewritten to their new names inside `src/ocr_*`; legacy files keep
their old imports and resolve through the aliases. Every move is recorded in
config/module_map.json, which the alias tests read.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
MAP = ROOT / "config" / "module_map.json"

ALIAS = '''"""Compatibility alias: this module moved to `{new}` (migration {stage}).

The object registered under this name is `{new}` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import {new} as _module

sys.modules[__name__] = _module
'''

ALIAS_MAIN = '''"""Compatibility alias: this module moved to `{new}` (migration {stage}).

The object registered under this name is `{new}` itself. Running this path
with `python -m` runs the new module as the main program.
"""
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("{new}", run_name="__main__", alter_sys=True)
else:
    import {new} as _module

    sys.modules[__name__] = _module
'''


def module_file(name: str) -> Path:
    parts = name.split(".")
    if parts[0] == "src":
        return ROOT.joinpath(*parts).with_suffix(".py")
    return SRC.joinpath(*parts).with_suffix(".py")


def load_map() -> dict:
    return json.loads(MAP.read_text(encoding="utf-8")) if MAP.is_file() else {"moves": {}}


def rewrite_imports(text: str, moves: dict[str, str]) -> str:
    # Longest names first, so `a.b.c` is not rewritten through its prefix `a.b`.
    for old in sorted(moves, key=len, reverse=True):
        new = moves[old]
        text = re.sub(rf"(?<![\w.]){re.escape(old)}(?![\w])", new, text)
    return text


def ensure_package(path: Path) -> None:
    for parent in reversed(path.parents):
        if parent == SRC or not parent.is_relative_to(SRC) or parent == SRC.parent:
            continue
        init = parent / "__init__.py"
        if not init.exists():
            init.write_text(f'"""`{parent.name}` package. See README.md."""\n', encoding="utf-8")


def main(argv: list[str]) -> int:
    stage, pairs = argv[0], [arg.split("=", 1) for arg in argv[1:]]
    registry = load_map()
    moves = registry["moves"]
    for old, new in pairs:
        if old in moves:
            raise SystemExit(f"{old} already moved to {moves[old]['to']}")
        source, target = module_file(old), module_file(new)
        if not source.is_file() or target.exists():
            raise SystemExit(f"Cannot move {source} -> {target}")
    all_moves = {old: entry["to"] for old, entry in moves.items()} | dict(pairs)
    for old, new in pairs:
        source, target = module_file(old), module_file(new)
        text = source.read_text(encoding="utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        ensure_package(target)
        target.write_text(text, encoding="utf-8", newline="")
        template = ALIAS_MAIN if re.search(r"^if __name__ == ['\"]__main__['\"]", text, re.M) else ALIAS
        source.write_text(template.format(new=new, stage=stage), encoding="utf-8", newline="\n")
        moves[old] = {"to": new, "stage": stage}
    # Keep every new package free of the legacy namespace for moved modules.
    for path in SRC.glob("ocr_*/**/*.py"):
        text = path.read_text(encoding="utf-8")
        rewritten = rewrite_imports(text, all_moves)
        if rewritten != text:
            path.write_text(rewritten, encoding="utf-8", newline="")
    registry["moves"] = dict(sorted(moves.items()))
    MAP.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{stage}: moved {len(pairs)} module(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
