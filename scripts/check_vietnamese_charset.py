#!/usr/bin/env python3
"""Check that a model can emit every Vietnamese letter before trusting it (V8-065, V8-090).

PP-OCRv6 recognition is documented as multilingual, yet its character dictionary
lacks most tone-marked vowels (PaddleOCR issue #18254), so it cannot write them.
This check reads a recognizer dictionary (one symbol per line, PaddleOCR style)
a VietOCR config (`vocab`) or a Hugging Face `tokenizer.json` and reports which of the 146 Vietnamese
letters (12 vowel bases x 6 tones, both cases, plus đ/Đ) it can produce.

A byte-level BPE tokenizer can spell any Unicode text from bytes, so it is
reported as BYTE_FALLBACK: the alphabet is reachable, but whether the model
writes the marks correctly is only answered by measuring it (V8-010 stress set).

  python scripts/check_vietnamese_charset.py path/to/ppocrv6_dict.txt --report scratch/<new>.json
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Dict, Iterable, List, Set

VOWELS = ("a", "ă", "â", "e", "ê", "i", "o", "ô", "ơ", "u", "ư", "y")
TONES = ("", chr(0x301), chr(0x300), chr(0x309), chr(0x303), chr(0x323))
# GPT-2 style byte-level BPE marks bytes 0x00-0xFF with these code points.
_BYTE_LEVEL_HINTS = ("Ġ", "Ċ", "ĉ")


def vietnamese_letters() -> List[str]:
    lower = [unicodedata.normalize("NFC", vowel + tone) for vowel in VOWELS for tone in TONES] + ["đ"]
    return lower + [letter.upper() for letter in lower]


def symbols_from_dictionary(text: str) -> Set[str]:
    symbols: Set[str] = set()
    for line in text.splitlines():
        symbols.update(unicodedata.normalize("NFC", line.strip(chr(13))))
    return symbols


def symbols_from_tokenizer(data: Dict) -> tuple[Set[str], bool]:
    model = data.get("model") or {}
    vocab = model.get("vocab") or {}
    tokens: Iterable[str] = vocab.keys() if isinstance(vocab, dict) else (item[0] for item in vocab)
    tokens = list(tokens) + [item.get("content", "") for item in data.get("added_tokens") or []]
    symbols: Set[str] = set()
    for token in tokens:
        symbols.update(unicodedata.normalize("NFC", token))
    pre = json.dumps(data.get("pre_tokenizer") or {}) + json.dumps(data.get("decoder") or {})
    byte_level = "ByteLevel" in pre or (model.get("byte_fallback") is True) or \
        all(hint in symbols for hint in _BYTE_LEVEL_HINTS)
    return symbols, byte_level


def check(path: Path) -> Dict:
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    byte_level = False
    if path.suffix.lower() == ".json":
        symbols, byte_level = symbols_from_tokenizer(json.loads(text))
        kind = "tokenizer_json"
    elif path.suffix.lower() in (".yml", ".yaml"):
        import yaml  # VietOCR config: the recognizer alphabet is the `vocab` string
        vocab = (yaml.safe_load(text) or {}).get("vocab")
        if not isinstance(vocab, str):
            raise ValueError(f"{path} has no `vocab` string")
        symbols, kind = set(unicodedata.normalize("NFC", vocab)), "vietocr_vocab"
    else:
        symbols, kind = symbols_from_dictionary(text), "dictionary_txt"
    letters = vietnamese_letters()
    missing = [letter for letter in letters if letter not in symbols]
    combining = [hex(code) for code in (0x300, 0x301, 0x303, 0x309, 0x323) if chr(code) in symbols]
    if not missing:
        status = "PASS"
    elif byte_level:
        status = "BYTE_FALLBACK"
    else:
        status = "FAIL"
    return {"schema_version": "vietnamese-charset-check-v1", "path": str(path), "kind": kind, "status": status,
            "letters": len(letters), "covered": len(letters) - len(missing), "missing": missing,
            "combining_marks_present": combining, "byte_level": byte_level,
            "note": "Coverage shows which letters a model can emit, not whether it reads them correctly."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", type=Path, help="Recognizer dictionaries (.txt) or tokenizer.json files")
    parser.add_argument("--report", type=Path, help="New JSON report path (never overwritten)")
    args = parser.parse_args(argv)
    if args.report and args.report.exists():
        parser.error(f"{args.report} exists")
    results = [check(path) for path in args.paths]
    for result in results:
        print(f"{result['status']}: {result['covered']}/{result['letters']} Vietnamese letters, "
              f"{len(result['missing'])} missing -> {result['path']}")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(results, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    return 0 if all(result["status"] == "PASS" for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
