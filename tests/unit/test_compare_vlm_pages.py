"""compare_vlm_pages.classify: empty pages and paraphrased prompt echoes are counted apart (V8-090)."""
import pytest

from scripts.compare_vlm_pages import classify


@pytest.mark.parametrize("text,kind", [
    ("", "EMPTY"), ("   \n ", "EMPTY"),
    ("Chép lại văn bản trang báo cáo này theo từng dòng, giữ đúng dấu tiếng Việt. Không dịch, không tóm tắt.", "PROMPT_ECHO"),
    ("BÁO CÁO THƯỜNG NIÊN 2020\nTĂNG TRƯỞNG XANH", "TEXT"),
    ("Công ty không dịch chuyển trụ sở trong năm", "TEXT"),  # one marker alone is ordinary text
])
def test_classify(text, kind):
    assert classify(text) == kind
