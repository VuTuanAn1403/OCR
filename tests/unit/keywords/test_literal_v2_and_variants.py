"""V8-031 single-word diacritic variants and the V8-032 literal_v2 challenger.

literal_v1 stays the product policy; these tests pin what v2 changes and that the
single-word list is review evidence only. Imports only ocr_* packages and pydantic.
"""
import unicodedata

import pytest

from ocr_keywords.alias_map import find_alias_candidates, find_single_word_variants
from ocr_keywords.counter import COUNTING_POLICIES, KeywordCounter, resolve_literal_v2
from ocr_keywords.tiered import build_tiered_report


def counts(text, keywords, policy):
    report = KeywordCounter.count_keywords(text, keywords, policy=policy)
    return {item.keyword: item.count for item in report.keywords}


def test_literal_v1_remains_the_default_policy():
    text = "Internet di độngx và phát triển bền vững"
    keywords = ["internet di động", "phát triển", "phát triển bền vững"]
    assert counts(text, keywords, "literal_v1") == {k: c.count for k, c in zip(
        keywords, KeywordCounter.count_keywords(text, keywords).keywords)}
    assert COUNTING_POLICIES[0] == "literal_v1"


@pytest.mark.parametrize("text,keyword,v1,v2", [
    ("Internet di động, Internet di độngx", "internet di động", 2, 1),   # trailing word character
    ("tái cơ cấu và cơ cấu", "cơ cấu", 2, 2),                            # space is a boundary
    ("xcơ cấu", "cơ cấu", 1, 0),                                         # leading word character
    ("AI, (AI) và AIoT", "ai", 3, 2),                                    # embedded in a longer word
    ("C++ và C++x", "c++", 2, 2),                                        # no boundary after '+'
    ("số 4.0, số 4.05", "số 4.0", 2, 1),                                 # digits continue a word
    (unicodedata.normalize("NFD", "Dữ liệu lớn"), "dữ liệu lớn", 1, 1),  # NFC first
])
def test_literal_v2_requires_word_boundaries(text, keyword, v1, v2):
    assert counts(text, [keyword], "literal_v1")[keyword] == v1
    assert counts(text, [keyword], "literal_v2")[keyword] == v2


def test_literal_v2_counts_a_nested_phrase_once_and_reports_the_suppression():
    text = "Phát triển bền vững là mục tiêu; phát triển nhanh"
    keywords = ["phát triển", "phát triển bền vững"]
    assert counts(text, keywords, "literal_v1") == {"phát triển": 2, "phát triển bền vững": 1}
    assert counts(text, keywords, "literal_v2") == {"phát triển": 1, "phát triển bền vững": 1}
    kept, suppressed = resolve_literal_v2(text, keywords)
    assert [row[0] for row in kept] == ["phát triển bền vững", "phát triển"]
    assert suppressed == [{"keyword": "phát triển", "match_start": 0, "match_end": 10,
                           "kept_keyword": "phát triển bền vững", "kept_start": 0, "kept_end": 19}]


def test_literal_v2_resolves_partial_overlaps_leftmost():
    kept, suppressed = resolve_literal_v2("kinh tế số hóa", ["kinh tế số", "số hóa"])
    assert [row[0] for row in kept] == ["kinh tế số"]
    assert suppressed[0]["keyword"] == "số hóa" and suppressed[0]["kept_keyword"] == "kinh tế số"


def test_iter_occurrences_follows_the_policy_and_rejects_unknown_ones():
    text = "phát triển bền vững"
    v2 = list(KeywordCounter.iter_occurrences(text, ["phát triển", "phát triển bền vững"], policy="literal_v2"))
    assert v2 == [("phát triển bền vững", 0, 19)]
    with pytest.raises(ValueError):
        list(KeywordCounter.iter_occurrences(text, ["x"], policy="fuzzy"))
    with pytest.raises(ValueError):
        KeywordCounter.count_keywords(text, ["x"], policy="fuzzy")


def test_single_word_keyword_with_another_accent_is_listed_not_counted():
    text = "Doanh nghiệp đầu tư số hóa. Tư vấn đâu tu và đầu tu."
    variants = find_single_word_variants(text, ["tư", "đầu tư"])
    assert [(row["keyword"], row["observed_variant"], row["occurrences"]) for row in variants] == [("tư", "tu", 2)]
    row = variants[0]
    assert row["counted"] is False and row["review_status"] == "NOT_EVALUATED"
    assert text[row["examples"][0]["match_start"]:row["examples"][0]["match_end"]] == "tu"
    # The two-word keyword still goes through alias candidates, not this list.
    assert {c.observed_text for c in find_alias_candidates(text, ["đầu tư"])} == {"đâu tu", "đầu tu"}


def test_single_word_variants_skip_exact_case_variants_and_multiword_keywords():
    assert find_single_word_variants("ESG esg Esg", ["ESG"]) == []
    assert find_single_word_variants("chuyen doi so", ["chuyển đổi số"]) == []
    assert find_single_word_variants("số 4.0", ["4.0"]) == []


def test_tiered_report_carries_the_review_list_without_changing_counts():
    snapshot = {"snapshot_sha256": "a" * 64,
                "canonical_keywords": [{"id": "kw-tu", "keyword": "tư"}, {"id": "kw-dt", "keyword": "đầu tư"}]}
    text = "đầu tư và tu"
    report = {"document_id": "d", "pdf_sha256": "b" * 64, "canonical_counts": {"kw-tu": 1, "kw-dt": 1},
              "total_canonical_matches": 2, "identity": {"counting_policy": "literal_v1"}}
    result = build_tiered_report(report, snapshot, text)
    assert result["tier1_literal_counts"] == {"kw-tu": 1, "kw-dt": 1}
    assert result["single_word_variant_policy"] == "single-word-variant-review-v1"
    assert result["single_word_variant_occurrences"] == 1
    assert result["single_word_variants"][0]["observed_variant"] == "tu"
