"""The Word export must keep Vietnamese text, structure and links intact."""
import io
import json
import unicodedata
import zipfile
from xml.etree import ElementTree

from scripts import export_v8_docx as export

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
META = {"verified_head": "08f7602ea8bd7fa4db0775924f47ac9960306e58", "last_verified": "2026-11-08",
        "pipeline_version": "7.0.0"}
SAMPLE = """# Bảo toàn dấu tiếng Việt

<a id="ct-01"></a>Đoạn có **đậm**, `mã`, [nguồn](https://example.invalid/a?b=1&c=2) và [nội bộ](04.md).

## Bảng

<!-- v8-status:gaps:begin -->
| Tầng | Trạng thái |
| --- | --- |
| L3 nhận dạng | PARTIAL \\| còn thiếu |
<!-- v8-status:gaps:end -->

1. Bước một
2. Bước hai
   - ý phụ

- gạch đầu dòng

```text
mã giữ nguyên  khoảng trắng
```

> Trích dẫn
"""


def parts(data):
    archive = zipfile.ZipFile(io.BytesIO(data))
    return archive, ElementTree.fromstring(archive.read("word/document.xml"))


def test_indent_and_numbered_list_restart():
    data = export.render(["1. a\n2. b\n\nĐoạn thường.\n\n1. c\n\n  thụt hai dấu cách\n"], META)
    document = parts(data)[1]
    nums = [node.get(W + "val") for node in document.iter(W + "numId")]
    assert nums[0] == nums[1] and nums[2] != nums[0]
    indents = [node.get(W + "left") for node in document.iter(W + "ind")]
    assert "720" in indents and "1440" not in indents


def test_registry_only_records_the_canonical_export(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(export, "ROOT", tmp_path)
    assert export.main(["--output", "scratch/other.docx", "--update-registry"]) == 2
    assert export.main(["--output", "../outside.docx"]) == 2
    assert "Cannot export DOCX" in capsys.readouterr().err


def test_markdown_structure_and_text_survive():
    data = export.render([SAMPLE], META)
    archive, document = parts(data)
    names = archive.namelist()
    assert not [name for name in names if name.endswith("/")]
    assert {"[Content_Types].xml", "word/document.xml", "word/styles.xml", "word/numbering.xml"} <= set(names)
    for name in names:
        if name.endswith((".xml", ".rels")):
            ElementTree.fromstring(archive.read(name))
    styles = [node.get(W + "val") for node in document.iter(W + "pStyle")]
    assert styles.count("Heading1") == 1 and styles.count("Heading2") == 1
    assert styles.count("ListParagraph") == 4 and "Code" in styles and "Quote" in styles
    assert len(list(document.iter(W + "tbl"))) == 1
    text = "".join(node.text or "" for node in document.iter(W + "t"))
    assert text == unicodedata.normalize("NFC", text)
    for expected in ("Bảo toàn dấu tiếng Việt", "đậm", "mã giữ nguyên  khoảng trắng", "PARTIAL | còn thiếu", "nội bộ"):
        assert expected in text
    assert "v8-status" not in text and "<a id" not in text and "](" not in text
    rels = archive.read("word/_rels/document.xml.rels").decode("utf-8")
    assert "https://example.invalid/a?b=1&amp;c=2" in rels and 'TargetMode="External"' in rels


def test_export_is_deterministic_and_registry_update_touches_only_exports(tmp_path, monkeypatch):
    assert export.render([SAMPLE], META) == export.render([SAMPLE], META)
    root = tmp_path / "repo"
    folder = root / export.V8_DIR
    folder.mkdir(parents=True)
    for name in export.DOCUMENTS:
        (folder / name).write_text(f"# {name}\n\nNội dung.\n", encoding="utf-8")
    (root / export.BACKLOG).write_bytes(
        "id,title_vi,priority,status,blocked_by\nV8-001,Khóa baseline,P0,TODO,\n".encode("utf-8-sig"))
    registry = {"schema_version": "x", "layers": [{"id": "L0"}], **META, "exports": []}
    (root / export.REGISTRY).write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setattr(export, "ROOT", root)
    assert export.main(["--update-registry"]) == 0
    data = (root / export.OUTPUT).read_bytes()
    updated = json.loads((root / export.REGISTRY).read_text(encoding="utf-8"))
    assert {k: v for k, v in updated.items() if k != "exports"} == {k: v for k, v in registry.items() if k != "exports"}
    entry = updated["exports"][0]
    assert entry["path"] == export.OUTPUT and len(entry["sources"]) == len(export.DOCUMENTS) + 1
    assert entry["sha256"] == __import__("hashlib").sha256(data).hexdigest()
    text = "".join(node.text or "" for node in parts(data)[1].iter(W + "t"))
    assert "Khóa baseline" in text and "Phụ lục: Backlog V8" in text
