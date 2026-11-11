#!/usr/bin/env python3
"""Serve the offline review sheets and save every decision to disk as the reviewer works.

The sheets (screening, blind adjudication, table-number review, structured GT labeller)
keep their state in the browser's localStorage. That is not durable: a browser pane that
keeps storage in memory loses it on restart, and Chromium caps localStorage near 5 MB, which
a 9,733-item adjudication sheet can exceed. On 10/11/2026 half an adjudication sheet was lost
that way.

This server serves a sheet folder over 127.0.0.1 and adds one script at the top of every
HTML page it sends (the sheet files on disk, and the templates pinned by the measurement
lock, are not changed). The script

* sends each state the sheet writes under a known key (``screening:``, ``adjudication:``,
  ``table-number-review:``, ``structured-gt:``) to ``POST /__autosave``, at most every 1.5 s;
* on load, hands the sheet the saved state when it holds more decisions than localStorage
  (``GET /__autosave?page=``), so a wiped or capped browser store no longer loses work.

The server writes ``<sheet folder>/autosave/<key>.json`` (the latest state, atomically),
``<key>.decisions.jsonl`` (one decision record per line, the same records the sheet's
"Xuất JSONL" button exports, ready for ``seal``) and a dated copy under ``autosave/backups/``
at most every five minutes. Decisions are only ever written by the reviewer's own clicks;
nothing here creates or edits one.

  python scripts/serve_review_sheets.py --directory scratch/v8/adjudication --port 8767
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

PREFIXES = ("screening:", "adjudication:", "table-number-review:", "structured-gt:")
MAX_BODY = 64 * 1024 * 1024
BACKUP_EVERY_SECONDS = 300
BACKUPS_KEPT = 50
MARKER = "<!-- review-sheet-autosave v1 -->"
_LOCK = threading.Lock()
_LAST_BACKUP: Dict[Path, float] = {}

AUTOSAVE_SCRIPT = MARKER + """
<script>
(() => {
  "use strict";
  const PREFIXES = %(prefixes)s;
  const tracked = key => typeof key === "string" && PREFIXES.some(p => key.startsWith(p));
  const page = location.pathname;
  let saved = {};
  try {
    const request = new XMLHttpRequest();
    request.open("GET", "/__autosave?page=" + encodeURIComponent(page), false);
    request.send();
    if (request.status === 200) saved = JSON.parse(request.responseText).states || {};
  } catch (e) {}
  const score = value => {
    try { const s = JSON.parse(value); const d = s.decisions || s.labels || {};
          return Object.keys(d).length * 1e6 + Object.values(s.revisions || {}).reduce((a, b) => a + Number(b || 0), 0); }
    catch (e) { return -1; }
  };
  const proto = Storage.prototype, getItem = proto.getItem, setItem = proto.setItem;
  proto.getItem = function (key) {
    const local = getItem.call(this, key);
    if (this === window.localStorage && tracked(key) && key in saved && score(saved[key]) > score(local)) return saved[key];
    return local;
  };
  const pending = {};
  let timer = null, failures = 0;
  const flush = () => {
    timer = null;
    for (const [key, value] of Object.entries(pending)) {
      delete pending[key];
      fetch("/__autosave", {method: "POST", headers: {"Content-Type": "application/json"},
                            body: JSON.stringify({page, key, value})})
        .then(r => { if (!r.ok) throw new Error(r.status); saved[key] = value; failures = 0; })
        .catch(() => { failures++; pending[key] = pending[key] || value; if (!timer) timer = setTimeout(flush, 5000); });
    }
  };
  proto.setItem = function (key, value) {
    if (this === window.localStorage && tracked(key)) { pending[key] = String(value); if (!timer) timer = setTimeout(flush, 1500); }
    try { return setItem.call(this, key, value); } catch (e) { /* storage full or gone: the server copy still holds it */ }
  };
  addEventListener("pagehide", flush);
  window.__autosave = {flush, status: () => ({pending: Object.keys(pending), saved: Object.keys(saved), failures})};
})();
</script>
"""


def safe_name(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", key)


def sheet_folder(root: Path, page: str) -> Optional[Path]:
    """The folder of the sheet page, or None when the page lies outside the served root."""
    relative = unquote(urlparse(page).path).lstrip("/")
    target = (root / relative).resolve()
    folder = target if target.is_dir() else target.parent
    try:
        folder.relative_to(root.resolve())
    except ValueError:
        return None
    return folder if folder.is_dir() else None


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def save_state(folder: Path, key: str, value: str) -> Dict:
    state = json.loads(value)
    name = safe_name(key)
    out = folder / "autosave"
    data = value.encode("utf-8")
    decisions = state.get("decisions") if isinstance(state, dict) else None
    with _LOCK:
        write_atomic(out / f"{name}.json", data)
        if isinstance(decisions, dict):
            lines = "".join(json.dumps(decisions[item], ensure_ascii=False) + "\n" for item in sorted(decisions))
            write_atomic(out / f"{name}.decisions.jsonl", lines.encode("utf-8"))
        now = time.monotonic()
        state_file = out / f"{name}.json"
        if now - _LAST_BACKUP.get(state_file, -BACKUP_EVERY_SECONDS) >= BACKUP_EVERY_SECONDS:
            _LAST_BACKUP[state_file] = now
            stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).strftime("%Y%m%dT%H%M%S")
            write_atomic(out / "backups" / f"{name}-{stamp}.json", data)
            backups = sorted((out / "backups").glob(f"{name}-*.json"))
            for old in backups[:-BACKUPS_KEPT]:
                old.unlink()
    return {"key": key, "decisions": len(decisions) if isinstance(decisions, dict) else None}


def saved_states(folder: Path) -> Dict[str, str]:
    states = {}
    out = folder / "autosave"
    for path in sorted(out.glob("*.json")) if out.is_dir() else ():
        if path.name.endswith(".decisions.jsonl"):
            continue
        text = path.read_text(encoding="utf-8")
        for prefix in PREFIXES:
            if path.stem.startswith(safe_name(prefix)):
                states[prefix + path.stem[len(safe_name(prefix)):]] = text
    return states


def inject(html: str) -> str:
    if MARKER in html:
        return html
    script = AUTOSAVE_SCRIPT % {"prefixes": json.dumps(list(PREFIXES))}
    match = re.search(r"<head[^>]*>", html, flags=re.IGNORECASE)
    if match:
        return html[:match.end()] + "\n" + script + html[match.end():]
    return script + html


class Handler(SimpleHTTPRequestHandler):
    root: Path

    def log_request(self, code="-", size="-"):
        # Page and image requests are quiet; saves are logged by do_POST, failures here.
        if str(code)[:1] in "45":
            super().log_request(code, size)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, status: int, payload: Dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server naming
        parsed = urlparse(self.path)
        if parsed.path == "/__autosave":
            folder = sheet_folder(self.root, parse_qs(parsed.query).get("page", [""])[0])
            if folder is None:
                return self._json(400, {"error": "page outside the served folder"})
            return self._json(200, {"states": saved_states(folder)})
        target = Path(self.translate_path(self.path))
        if target.is_dir() and parsed.path.endswith("/") and (target / "index.html").is_file():
            target = target / "index.html"
        if target.suffix.lower() == ".html" and target.is_file():
            body = inject(target.read_text(encoding="utf-8")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        return super().do_GET()

    def do_POST(self):  # noqa: N802 - http.server naming
        if urlparse(self.path).path != "/__autosave":
            return self._json(404, {"error": "unknown endpoint"})
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._json(413, {"error": f"body must be 1..{MAX_BODY} bytes"})
        try:
            payload = json.loads(self.rfile.read(length))
            key, value, page = payload["key"], payload["value"], payload["page"]
            if not (isinstance(key, str) and key.startswith(PREFIXES) and isinstance(value, str) and isinstance(page, str)):
                raise ValueError("key, value and page must be strings and the key a known sheet key")
            json.loads(value)
        except (ValueError, KeyError, TypeError) as error:
            return self._json(400, {"error": str(error)})
        folder = sheet_folder(self.root, page)
        if folder is None:
            return self._json(400, {"error": "page outside the served folder"})
        result = save_state(folder, key, value)
        self.log_message("autosave %s: %s decisions -> %s", key, result["decisions"], folder / "autosave")
        return self._json(200, {"saved": result})


def make_server(directory: Path, port: int, bind: str = "127.0.0.1") -> ThreadingHTTPServer:
    if bind not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("the review server only binds to the loopback interface")
    root = directory.resolve()
    handler = type("BoundHandler", (Handler,), {"root": root})
    return ThreadingHTTPServer((bind, port), partial(handler, directory=str(root)))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--directory", type=Path, required=True, help="Folder holding the sheet folders")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--bind", default="127.0.0.1")
    args = parser.parse_args(argv)
    if not args.directory.is_dir():
        parser.error(f"{args.directory} is not a folder")
    server = make_server(args.directory, args.port, args.bind)
    print(f"Serving {args.directory.resolve()} on http://{args.bind}:{args.port}/ with autosave", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
