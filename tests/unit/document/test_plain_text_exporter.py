import unicodedata

from ocr_document.plain_text_exporter import markdown_plain_text


def test_visible_content_keeps_financial_literals_accents_and_cell_boundaries():
    original = """# Báo cáo
*Tổng số trang*: 2 | **Profile**: v7.0

| Chỉ tiêu | Năm 2025 |
| :--- | ---: |
| A\\|B | (020) |
| Tỷ lệ | − 3,5% |
| Tiền | USD 1.234,50 |

> **Ghi chú**: chuyển đổi số &amp; đổi mới.
- [Nguồn ảnh](images/a.png)
![Đồ thị](images/b.png)

---
"""
    text = markdown_plain_text(original)
    assert text == """Báo cáo
Tổng số trang: 2 | Profile: v7.0

Chỉ tiêu\tNăm 2025
A|B\t(020)
Tỷ lệ\t− 3,5%
Tiền\tUSD 1.234,50

Ghi chú: chuyển đổi số & đổi mới.
Nguồn ảnh
Đồ thị
"""
    assert original.startswith("# Báo cáo")


def test_source_symbols_and_unicode_are_not_dictionary_rewritten():
    text = unicodedata.normalize("NFD", "1. O2O 020 mã_ABC_020 a*b 2 < 3 [020] \\#nguyên văn")
    assert markdown_plain_text(text) == text.replace(r"\#", "#") + "\n"


def test_code_and_formula_bodies_stay_literal_and_only_fences_are_removed():
    source = "```text\na*b_020 <b>raw</b> [x](y)\n```\n\n$$\n\\frac{020}{2} = 10\n$$\n"
    assert markdown_plain_text(source) == "a*b_020 <b>raw</b> [x](y)\n\n\\frac{020}{2} = 10\n"


def test_br_and_escaped_pipes_do_not_create_extra_columns():
    assert markdown_plain_text("| đầu<br>cuối | a\\|b |\n|---|---|\n") == "đầu\ncuối\ta|b\n"


def test_display_formula_symbols_are_never_parsed_as_markdown_emphasis():
    formula = r"\{a\}_{x} * y * \{b\}_{z}"
    assert markdown_plain_text("$$\n"+formula+"\n$$") == formula+"\n"
