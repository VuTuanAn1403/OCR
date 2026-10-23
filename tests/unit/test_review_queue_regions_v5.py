import json
import pytest
from pathlib import Path
from benchmark.baselines.legacy_cli.batch_runner import BatchOCRRunner


def test_review_queue_captures_region_risks_including_numeric(tmp_path):
    output_dir = tmp_path / "output"
    doc_id = "test_doc_risk"
    doc_dir = output_dir / doc_id
    pages_dir = doc_dir / "pages"
    pages_dir.mkdir(parents=True)

    # 1. Page JSON with 3 distinct risk regions:
    # - Region 1: Numeric text disagreement
    # - Region 2: Orientation disagreement
    # - Region 3: Rejected evidence block
    page_data = {
        "page_num": 1,
        "width": 800.0,
        "height": 1000.0,
        "page_type": "MIXED",
        "regions": [
            {
                "region_id": "R_NUM_001",
                "content_type": "IMAGE",
                "needs_fallback": True,
                "failure_reason": "High-DPI OCR disagrees on numeric text; manual review required",
            },
            {
                "region_id": "R_ORI_002",
                "content_type": "IMAGE",
                "needs_fallback": True,
                "failure_reason": "OCR orientations disagree; manual review required",
            },
        ],
        "evidence_blocks": [
            {
                "block_id": "EB_001",
                "region_id": "R_EVD_003",
                "page": 1,
                "status": "REJECTED_LOW_CONFIDENCE",
                "failure_reason": "OCR confidence 0.42 below rejection threshold",
                "text": "123,456 VND",
            }
        ],
    }
    (pages_dir / "page-0001.json").write_text(json.dumps(page_data), encoding="utf-8")

    # Quality JSON
    (doc_dir / "quality.json").write_text(json.dumps({
        "document_id": doc_id,
        "total_pages": 1,
        "page_reports": [
            {
                "page": 1,
                "review_required_count": 3,
                "stage_seconds": {"primary_ocr": 0.5},
            }
        ]
    }), encoding="utf-8")

    manifest = [{
        "file_name": "test_risk.pdf",
        "document_id": doc_id,
        "status": "COMPLETED",
        "total_pages": 1,
        "wall_clock_seconds": 0.5,
        "seconds_per_page": 0.5,
    }]

    runner = BatchOCRRunner(
        input_dir=str(tmp_path / "input"),
        output_dir=str(output_dir),
        excel_path=str(output_dir / "test.xlsx"),
    )

    runner.generate_reports(manifest, batch_duration=1.0)

    # Verify review_queue.json
    rq_file = output_dir / "review_queue.json"
    assert rq_file.is_file()
    queue = json.loads(rq_file.read_text(encoding="utf-8"))

    # Must contain all 3 risk regions with their specific region_id
    region_ids = {item["region_id"] for item in queue}
    assert "R_NUM_001" in region_ids
    assert "R_ORI_002" in region_ids
    assert "R_EVD_003" in region_ids

    # Find numeric disagreement item specifically
    num_item = next(item for item in queue if item["region_id"] == "R_NUM_001")
    assert num_item["page"] == 1
    assert num_item["file"] == "test_risk.pdf"
    assert "numeric text" in num_item["reason"].lower()

    # Manifest review_required_count must reflect the items
    assert manifest[0]["review_required_count"] >= 3
