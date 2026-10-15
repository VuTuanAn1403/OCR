import copy

import pytest

from benchmark.scientific_evaluation.cluster_statistics import company_cluster_bootstrap, holm_adjust
from benchmark.scientific_evaluation.coco_layout import evaluate_layout_scoreboards


def records():
    base = [dict(company_id="A", document_id="A1", page=1, numerator=90, denominator=900),
            dict(company_id="A", document_id="A1", page=2, numerator=10, denominator=100),
            dict(company_id="B", document_id="B1", page=1, numerator=1, denominator=10)]
    candidate = copy.deepcopy(base)
    for record, numerator in zip(candidate, [45, 5, 2]):
        record["numerator"] = numerator
    return base, candidate


def test_bootstrap_is_paired_by_company_and_micro_not_mean_of_page_rates():
    base, candidate = records()
    result = company_cluster_bootstrap(base, candidate, metric="cer", resamples=200, seed=7)
    assert result["company_count"] == 2
    assert result["difference"] == pytest.approx((52-101)/1010)
    assert result == company_cluster_bootstrap(base[::-1], candidate[::-1], metric="cer", resamples=200, seed=7)
    assert result["ci_unadjusted"]["lower"] == pytest.approx(-.05)
    assert result["ci_unadjusted"]["upper"] == pytest.approx(.1)


def test_missing_output_is_error_and_missing_pair_cannot_disappear():
    base, candidate = records()
    candidate[0].update(status="MISSING_OUTPUT", numerator=0)
    result = company_cluster_bootstrap(base, candidate, metric="cer", resamples=100)
    assert result["candidate"] == pytest.approx(907/1010)
    with pytest.raises(ValueError, match="same paired units"):
        company_cluster_bootstrap(base, candidate[1:], metric="cer")


def test_unknown_company_different_gt_and_degenerate_ci_are_not_accepted():
    base, candidate = records()
    candidate[0]["denominator"] += 1
    with pytest.raises(ValueError, match="denominators differ"):
        company_cluster_bootstrap(base, candidate, metric="cer")
    base[0]["company_id"] = "unknown"
    with pytest.raises(ValueError, match="verified company_id"):
        company_cluster_bootstrap(base, candidate, metric="cer")
    base, _ = records()
    result = company_cluster_bootstrap(base, base, metric="cer", margin=.005, margin_approved=True)
    assert result["status"] == "DEGENERATE"
    assert result["noninferiority"]["status"] == "NOT_EVALUATED"
    assert not result["eligible_for_quality_acceptance"]


def test_holm_preserves_names_and_uses_all_hypotheses():
    assert holm_adjust({"b": .02, "a": .01, "c": .5}) == {"b": .04, "a": .03, "c": .5}
    with pytest.raises(ValueError):
        holm_adjust({"invalid": float("nan")})


def gt(category="Text", box=None, image="doc_p1", **kw):
    return dict(category=category, bbox=box or [0, 0, 10, 10], image_id=image, **kw)


def test_two_coco_boards_missing_class_unknown_and_no_gt_coverage():
    pytest.importorskip("pycocotools")
    result = evaluate_layout_scoreboards([gt(), gt("Table", [20, 20, 40, 40])],
        [gt(score=.9), gt("UNKNOWN", [20, 20, 40, 40], score=.9)],
        common_classes=["Text"], supported_classes=["Text"])
    assert result["comparison"]["mAP@50"] == pytest.approx(1)
    table = result["acceptance"]["per_class"]["Table"]
    assert table["AP50"] == 0 and table["FN"] == 1 and table["supported"] is False
    assert result["acceptance"]["per_class"]["Formula"]["AP50"] is None
    assert result["unknown_predictions"] == 1
    assert not result["mandatory_coverage_complete"]


def test_ignore_regions_do_not_erase_valid_gt_objects():
    pytest.importorskip("pycocotools")
    result = evaluate_layout_scoreboards([gt(), gt("decoration", [0, 0, 100, 100], ignore=True)],
        [gt(score=.8), gt(box=[30, 30, 40, 40], score=.99)])
    assert result["ignored_predictions"] == 1
    assert result["acceptance"]["per_class"]["Text"]["TP"] == 1
    assert result["mAP@50"] == pytest.approx(1)


def test_coco_duplicate_wrong_page_and_no_predictions_count_errors():
    pytest.importorskip("pycocotools")
    result = evaluate_layout_scoreboards([gt()], [gt(score=.9), gt(score=.8), gt(image="other_p1", score=.99)])
    text = result["acceptance"]["per_class"]["Text"]
    assert (text["TP"], text["FP"], text["FN"]) == (1, 2, 0)
    assert text["AP50"] == pytest.approx(.5)
    assert evaluate_layout_scoreboards([gt()], [])["acceptance"]["per_class"]["Text"]["FN"] == 1
