"""serve_review_sheets: review decisions survive a browser that forgets its localStorage."""
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from scripts import serve_review_sheets as serve


@pytest.fixture()
def server(tmp_path):
    sheet = tmp_path / "sheets" / "adj_v1"
    sheet.mkdir(parents=True)
    (sheet / "index.html").write_text("<!doctype html><html><head><title>x</title></head>"
                                      "<body><script>const SHEET = null;</script></body></html>", encoding="utf-8")
    (sheet / "pages").mkdir()
    (sheet / "pages" / "p.png").write_bytes(b"png")
    httpd = serve.make_server(tmp_path / "sheets", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", sheet
    httpd.shutdown()
    httpd.server_close()


def _get(url):
    with urllib.request.urlopen(url) as response:
        return response.status, response.read().decode("utf-8")


def _post(url, payload):
    request = urllib.request.Request(url + "/__autosave", data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_pages_get_the_autosave_script_before_the_sheet_script_and_files_stay_unchanged(server):
    base, sheet = server
    status, html = _get(base + "/adj_v1/")
    assert status == 200 and html.index(serve.MARKER) < html.index("const SHEET")
    assert html.count(serve.MARKER) == 1 and "/__autosave" in html
    assert serve.MARKER not in (sheet / "index.html").read_text(encoding="utf-8")
    assert _get(base + "/adj_v1/pages/p.png")[0] == 200


def test_a_saved_state_lands_on_disk_with_a_decisions_jsonl_and_comes_back(server):
    base, sheet = server
    decisions = {"i2": {"item_id": "i2", "choice": "B_CORRECT", "a": "tri"}, "i1": {"item_id": "i1", "choice": "A_CORRECT", "a": "trị"}}
    value = json.dumps({"decisions": decisions, "revisions": {"i1": 1, "i2": 1}, "cursor": 2, "reviewer": "r"}, ensure_ascii=False)
    status, body = _post(base, {"page": "/adj_v1/", "key": "adjudication:4e74b0e7955ff91d", "value": value})
    assert status == 200 and body["saved"]["decisions"] == 2
    out = sheet / "autosave"
    assert (out / "adjudication_4e74b0e7955ff91d.json").read_text(encoding="utf-8") == value
    lines = (out / "adjudication_4e74b0e7955ff91d.decisions.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["item_id"] for line in lines] == ["i1", "i2"]
    assert len(list((out / "backups").glob("adjudication_4e74b0e7955ff91d-*.json"))) == 1
    status, text = _get(base + "/__autosave?page=" + urllib.request.quote("/adj_v1/index.html"))
    assert json.loads(text)["states"] == {"adjudication:4e74b0e7955ff91d": value}


@pytest.mark.parametrize("payload,code", [
    ({"page": "/../../etc/", "key": "adjudication:x", "value": "{}"}, 400),   # outside the served folder
    ({"page": "/adj_v1/", "key": "cookie", "value": "{}"}, 400),              # not a sheet key
    ({"page": "/adj_v1/", "key": "adjudication:x", "value": "not json"}, 400)])
def test_unsafe_or_foreign_saves_are_refused(server, payload, code):
    base, sheet = server
    assert _post(base, payload)[0] == code
    assert not (sheet / "autosave").exists()


def test_the_server_only_binds_to_loopback(tmp_path):
    with pytest.raises(ValueError, match="loopback"):
        serve.make_server(tmp_path, 0, "0.0.0.0")
