#!/usr/bin/env python3
"""Build and export a human occurrence-alignment sheet against frozen keyword GT."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from ocr_artifacts.hashing import sha256_file
from ocr_artifacts.completion import verify_completed
from ocr_pipeline.analysis_run import verify_source
from benchmark.scientific_evaluation import keyword_acceptance as acceptance

SCHEMA = "ocr-keyword-occurrence-review-v1"
PENDING_SCHEMA = "ocr-keyword-pending-review-v1"
TEMPLATE = ROOT / "benchmark/ground_truth_tools/keyword_occurrence_sheet.html"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def new_output(output, protected):
    require(not output.exists() and all(not output.is_relative_to(p) and not p.is_relative_to(output)
                                       for p in protected)
            and not any((p / marker).exists() for p in output.parents
                        for marker in ("COMPLETED.json", "batch_input_manifest.json")),
            "Use a new output outside publication and source paths")


def occurrence_context(markdown, observed):
    raw = markdown.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == observed["identity"]["result_md_sha256"],
            "Markdown changed while preparing occurrence context")
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text).casefold()
    rows = []
    for index, occurrence in enumerate(observed["occurrences"]):
        start, end = occurrence["start"], occurrence["end"]
        before, match, after = text[max(0, start - 90):start], text[start:end], text[end:end + 90]
        rows.append({**occurrence, "id": f"occ-{index:06d}", "context": before + match + after,
                     "context_before": before, "context_after": after, "observed_text": match,
                     "offset_space": "nfc_casefold"})
    return rows


def literal_inventory(document, snapshot):
    citation_source = None
    if (document / "source.json").is_file():
        citation_source = Path(verify_source(document)["source_dir"])
    return acceptance.inventory(document, snapshot, citation_source_dir=citation_source)


def pending_inventory(document, observed):
    """Read a sealed publication's review-only occurrences with source locations."""
    require(verify_completed(document), "Review-only candidates require a verified publication")
    tier_path = document / "keyword_two_tier.json"
    digest_before = sha256_file(tier_path)
    tier = read(tier_path)
    identity = observed["identity"]
    require(tier.get("document_id") == identity["document_id"] and tier.get("pdf_sha256") == identity["pdf_sha256"]
            and tier.get("result_md_sha256") == identity["result_md_sha256"]
            and tier.get("dictionary_snapshot_hash") == identity["dictionary_sha256"],
            "Review-only candidate artifact differs from the literal publication")
    if tier.get("schema_version") == "keyword-two-tier-v3":
        aliases = [row for row in tier["resolutions"] if row["review_status"] == "NOT_EVALUATED"]
    else:
        decided = {(row["keyword_id"], row["match_start"], row["match_end"], row["observed_text"])
                   for row in tier["decisions"]}
        aliases = [row for row in tier["candidates"]
                   if (row["keyword_id"], row["match_start"], row["match_end"], row["observed_text"]) not in decided]
    require("confusable_candidates" in tier and tier.get("retained_line_status") == "EVALUATED",
            "Run the analysis with the Q6/Q7 keyword integration before reviewing pending candidates")
    raw = (document / "result.md").read_bytes()
    require(hashlib.sha256(raw).hexdigest() == identity["result_md_sha256"], "Pending Markdown source changed")
    markdown = (document / "result.md").read_text(encoding="utf-8")
    require(sha256_file(document / "result.md") == identity["result_md_sha256"], "Pending Markdown source changed")
    markdown = unicodedata.normalize("NFC", markdown)
    keyword_ids = {row["id"] for row in observed["keywords"]}
    rows = []
    for stream, records in (("alias", aliases), ("confusable", tier["confusable_candidates"]),
                            ("retained_line", tier["retained_line_occurrences"])):
        for value in records:
            start, end = value["match_start"], value["match_end"]
            text = value["line_text"].casefold() if stream == "retained_line" else markdown
            require(value["keyword_id"] in keyword_ids and type(start) is int and type(end) is int
                    and 0 <= start < end <= len(text), "Invalid review-only candidate location")
            match = text[start:end]
            if stream == "retained_line":
                require(value.get("source_id") and value.get("bbox") and value.get("page") in observed["selected_pages"],
                        "Retained-line candidate lacks a physical source location")
            else:
                require(match == value["observed_text"], "Review-only candidate text differs from its offsets")
            rows.append({**value, "id": f"pending-{len(rows):06d}", "stream": stream,
                         "start": start, "end": end, "observed_text": match,
                         "context_before": text[max(0, start - 90):start], "context_after": text[end:end + 90]})
    require(sha256_file(tier_path) == digest_before, "Review-only candidate artifact changed during inventory")
    return rows, digest_before


def pending_score(observed, ground_truth, sheet, pending_attributions):
    """Measure coverage added by source-linked pending candidates without changing counts."""
    units, references, unannotated = acceptance._reference_units(ground_truth, observed)
    covered = {}
    extras, excluded, unscored = [], [], []
    for prediction, review in zip(sheet["occurrences"], pending_attributions, strict=True):
        row = {"id": prediction["id"], "stream": prediction["stream"], "keyword_id": prediction["keyword_id"], **review}
        unit_id, ref_id = review["unit_id"], review["reference_id"]
        if unit_id is None:
            acceptance._text(review["outside_scope_reason"], "outside_scope_reason")
            excluded.append(row)
        elif unit_id in unannotated:
            unscored.append(row)
        elif ref_id is not None and ref_id not in covered:
            covered[ref_id] = row
        else:
            extras.append(row)
    literal_links = sheet["literal_covered_reference_ids"]
    literal_covered = set(literal_links or ())
    complete_reference = literal_links is not None and not unannotated and not unscored
    remaining = sorted(set(references) - literal_covered - covered.keys()) if complete_reference else None
    return {"method": PENDING_SCHEMA, "status": "SCORED_DEVELOPMENT", "quality_acceptance": "NOT_EVALUATED",
            "eligible_for_quality_acceptance": False, "identity": observed["identity"],
            "units": len(units), "reference_occurrences": len(references), "literal_covered": literal_links,
            "pending_covered": covered, "added_reference_ids": sorted(covered.keys() - literal_covered) if complete_reference else None,
            "remaining_reference_ids": remaining, "duplicate_or_unlinked_candidates": extras,
            "outside_scope": excluded, "unscored": unscored, "unannotated_unit_ids": unannotated}


def prepare(document, dictionary, ground_truth, pdf, output, *, pending=False, literal_alignment=None):
    import pymupdf

    document, dictionary, ground_truth, pdf, output = (
        Path(p).resolve() for p in (document, dictionary, ground_truth, pdf, output))
    if literal_alignment is not None:
        require(pending, "A literal alignment is only used with --pending")
        literal_alignment = Path(literal_alignment).resolve()
    new_output(output, [document, dictionary, ground_truth, pdf, *([literal_alignment] if literal_alignment else [])])
    paths = {"dictionary": dictionary, "ground_truth": ground_truth, "pdf": pdf}
    if literal_alignment:
        paths["literal_alignment"] = literal_alignment
    hashes = {k: sha256_file(p) for k, p in paths.items()}
    snapshot, gt = read(dictionary), read(ground_truth)
    observed = literal_inventory(document, snapshot)
    require(hashes["pdf"] == observed["identity"]["pdf_sha256"], "Source PDF differs from publication")
    empty = {"schema_version": acceptance.METHOD, "identity": observed["identity"],
             "reviewed_by": "PREPARATION_ONLY_NOT_A_REVIEW", "attributions": []}
    acceptance.evaluate(observed, gt, empty)
    # The sheet is downstream of source-only annotation. Never prefill or alter GT.
    units, _, _ = acceptance._reference_units(gt, observed)
    covered, tier_hash = None, None
    if pending:
        occurrences, tier_hash = pending_inventory(document, observed)
        if literal_alignment:
            alignment = read(literal_alignment)
            require(alignment.get("ground_truth_sha256") == hashes["ground_truth"], "Literal review GT changed")
            literal_score = acceptance.evaluate(observed, gt, alignment)
            require(not literal_score["unattributed"] and not literal_score["unannotated_unit_ids"],
                    "Literal review must cover every occurrence and reference unit")
            covered = sorted(row["reference"]["id"] for row in literal_score["correct"])
    else:
        occurrences = occurrence_context(document / "result.md", observed)
    pages = {}
    with pymupdf.open(pdf) as source:
        for unit in units.values():
            require(unit["coordinate_space"] == "pdf_points_top_left", "Only unrotated PDF source coordinates are supported")
            number = unit["physical_page"]
            require(1 <= number <= len(source), "GT page outside source PDF")
            page = source[number - 1]
            require(page.rotation == 0, "Rotated PDF requires an explicit source-view adapter")
            x0, y0, x1, y1 = unit["bbox"]
            require(0 <= x0 < x1 <= page.rect.width and 0 <= y0 < y1 <= page.rect.height,
                    "GT box outside source page")
            pages[str(number)] = {"image": f"pages/{number}.png", "width": page.rect.width, "height": page.rect.height}
        output.mkdir(parents=True)
        (output / "pages").mkdir()
        for number, page in pages.items():
            source[int(number) - 1].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(output / page["image"])
            page["sha256"] = sha256_file(output / page["image"])
    require(all(sha256_file(paths[k]) == h for k, h in hashes.items()), "Source changed during preparation")
    require(literal_inventory(document, snapshot) == observed, "Publication changed during preparation")
    if pending:
        require(sha256_file(document / "keyword_two_tier.json") == tier_hash, "Pending publication changed during preparation")
    sheet = {"schema_version": PENDING_SCHEMA if pending else SCHEMA,
             "document": str(document), "source_paths": {k: str(p) for k, p in paths.items()},
             "source_hashes": hashes, "observed": observed, "units": list(units.values()),
             "occurrences": occurrences, "pages": pages, "ground_truth_origin": gt.get("annotation_origin"),
             "quality_acceptance": "NOT_EVALUATED", "template_sha256": sha256_file(TEMPLATE),
             "builder_sha256": sha256_file(Path(__file__))}
    if pending:
        sheet.update(tiered_report_sha256=tier_hash, literal_covered_reference_ids=covered)
    sheet["sheet_id"] = digest(sheet)
    write(output / "sheet.json", sheet)
    payload = json.dumps(sheet, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__SHEET__*/null", payload)
    with (output / "index.html").open("x", encoding="utf-8") as stream:
        stream.write(html)
    return sheet


def export(sheet_dir, decisions, output):
    sheet_dir, decisions, output = (Path(p).resolve() for p in (sheet_dir, decisions, output))
    sheet = read(sheet_dir / "sheet.json")
    claimed = sheet.pop("sheet_id")
    require(sheet.get("schema_version") in (SCHEMA, PENDING_SCHEMA) and digest(sheet) == claimed,
            "Review sheet identity differs")
    pending = sheet["schema_version"] == PENDING_SCHEMA
    paths = {k: Path(v) for k, v in sheet["source_paths"].items()}
    new_output(output, [sheet_dir, decisions, Path(sheet["document"]), *paths.values()])
    require(all(sha256_file(paths[k]) == h for k, h in sheet["source_hashes"].items()), "Review source changed")
    require(all(sha256_file(sheet_dir / p["image"]) == p["sha256"] for p in sheet["pages"].values()),
            "Review source image changed")
    decision_hash = sha256_file(decisions)
    state = read(decisions)
    require(state.get("sheet_id") == claimed, "Decisions belong to another sheet")
    reviewer = state.get("reviewer")
    require(isinstance(reviewer, str) and bool(reviewer.strip()), "Reviewer is required")
    rows = state.get("decisions")
    require(isinstance(rows, dict) and rows.keys() == {r["id"] for r in sheet["occurrences"]},
            "Review every observed occurrence explicitly before export")
    document = Path(sheet["document"])
    observed = literal_inventory(document, read(paths["dictionary"]))
    require(observed == sheet["observed"], "Published keyword inventory changed since sheet preparation")
    if pending:
        current, tier_hash = pending_inventory(document, observed)
        require(tier_hash == sheet["tiered_report_sha256"] and current == sheet["occurrences"],
                "Review-only candidate artifact changed since sheet preparation")
    gt = read(paths["ground_truth"])
    units, references, _ = acceptance._reference_units(gt, observed)
    attributions = []
    for occurrence in sheet["occurrences"]:
        row = rows[occurrence["id"]]
        require(isinstance(row, dict) and row.get("occurrence_id") == occurrence["id"], "Invalid occurrence decision")
        unit_id, ref_id = row.get("unit_id"), row.get("reference_id")
        if pending and unit_id is not None and occurrence["stream"] == "retained_line":
            require(unit_id in units and units[unit_id]["physical_page"] == occurrence["page"],
                    "A retained-line candidate must link to a unit on its source page")
        if ref_id is not None:
            require(ref_id in references and references[ref_id]["unit_id"] == unit_id
                    and references[ref_id]["keyword_id"] == occurrence["keyword_id"], "Reference link is inconsistent")
        elif unit_id is not None:
            require(unit_id in units, "Unknown source unit")
        attribution = {"unit_id": unit_id, "reference_id": ref_id, "outside_scope_reason": row.get("outside_scope_reason")}
        if pending:
            attribution.update(occurrence_id=occurrence["id"])
        else:
            attribution.update({k: occurrence[k] for k in ("keyword_id", "start", "end")})
        attributions.append(attribution)
    alignment = {"schema_version": PENDING_SCHEMA if pending else acceptance.METHOD,
                 "identity": observed["identity"], "reviewed_by": reviewer.strip(),
                 "ground_truth_sha256": sheet["source_hashes"]["ground_truth"], "attributions": attributions,
                 "review_sheet_id": claimed, "decisions_sha256": decision_hash}
    if pending:
        alignment["tiered_report_sha256"] = sheet["tiered_report_sha256"]
        report = pending_score(observed, gt, sheet, attributions)
    else:
        report = acceptance.evaluate(observed, gt, alignment)
    require(sha256_file(decisions) == decision_hash
            and all(sha256_file(paths[k]) == h for k, h in sheet["source_hashes"].items()),
            "Review inputs changed during export")
    output.mkdir(parents=True)
    write(output / "alignment.json", alignment)
    write(output / "score.json", {**report, "ground_truth_sha256": alignment["ground_truth_sha256"],
                                 "alignment_sha256": sha256_file(output / "alignment.json")})
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("prepare", allow_abbrev=False)
    for name in ("document", "dictionary", "ground-truth", "pdf", "output"):
        build.add_argument("--" + name, type=Path, required=True)
    build.add_argument("--pending", action="store_true", help="Review unresolved alias, confusable and retained-line candidates")
    build.add_argument("--literal-alignment", type=Path, help="An exported literal alignment on the same GT for added coverage")
    finish = commands.add_parser("export", allow_abbrev=False)
    for name in ("sheet", "decisions", "output"):
        finish.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args.document, args.dictionary, args.ground_truth, args.pdf, args.output,
                             pending=args.pending, literal_alignment=args.literal_alignment)
            print(f"Prepared {len(result['occurrences'])} occurrences for review.")
        else:
            result = export(args.sheet, args.decisions, args.output)
            print(json.dumps({k: result[k] for k in ("status", "eligible_for_quality_acceptance")}))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
