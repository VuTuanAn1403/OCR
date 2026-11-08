"""Strict JSON and evidence-root-bound file references for offline QA."""
from __future__ import annotations

import hashlib
import json
import ntpath
import os
from pathlib import Path, PurePosixPath


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Nonfinite JSON number: {value}")


def decode_json(raw):
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                      parse_constant=_reject_constant)


def digest(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def is_sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def file_digest(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


class EvidenceStore:
    """Resolve references once, verify bytes on every read; never mutate sources."""

    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        require(self.root.is_dir(), "Evidence root must be a directory")
        self.references = {}
        self._json_cache = {}

    def path(self, relative):
        require(isinstance(relative, str) and relative and "\\" not in relative
                and not ntpath.splitdrive(relative)[0] and ":" not in relative,
                "Evidence path must be relative POSIX, without a drive")
        parts = relative.split("/")
        require(all(part not in ("", ".", "..") for part in parts)
                and not PurePosixPath(relative).is_absolute(), "Unsafe evidence path")
        resolved = (self.root / relative).resolve(strict=True)
        require(resolved.is_relative_to(self.root) and resolved.is_file(),
                "Evidence path escapes root or is not a file")
        return resolved

    def ref(self, path, expected_sha256=None):
        resolved = Path(path).resolve(strict=True)
        require(resolved.is_relative_to(self.root) and resolved.is_file(),
                "Evidence path escapes root or is not a file")
        relative = resolved.relative_to(self.root).as_posix()
        checksum = file_digest(resolved)
        require(expected_sha256 is None or checksum == expected_sha256, f"Evidence hash mismatch: {relative}")
        reference = {"path": relative, "sha256": checksum}
        self.verify(reference)
        return reference

    def verify(self, reference, *, force=False):
        require(isinstance(reference, dict) and reference.keys() == {"path", "sha256"}
                and is_sha(reference["sha256"]), "Invalid evidence reference")
        path = self.path(reference["path"])
        previous = self.references.get(reference["path"])
        require(previous is None or previous == reference["sha256"], "Conflicting hashes for one evidence path")
        if previous is None or force:
            require(file_digest(path) == reference["sha256"],
                    f"Evidence hash mismatch: {reference['path']}")
            self.references[reference["path"]] = reference["sha256"]
        return path

    def read(self, reference):
        path = self.verify(reference)
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == reference["sha256"], "Evidence changed during read")
        return raw

    def json(self, reference):
        key = (reference["path"], reference["sha256"])
        if key not in self._json_cache:
            self._json_cache[key] = decode_json(self.read(reference))
        return self._json_cache[key]

    def verify_all(self):
        for path, checksum in list(self.references.items()):
            self.verify({"path": path, "sha256": checksum}, force=True)


def write_new_json(path, value):
    """Exclusive output creation. An interrupted file is not a validated snapshot."""
    raw = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
