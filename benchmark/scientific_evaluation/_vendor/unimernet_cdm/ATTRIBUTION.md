# Nguồn mã CDM

Các file trong `PROVENANCE.json` giữ nguyên byte từ [UniMERNet, revision 5a2c80d](https://github.com/opendatalab/UniMERNet/tree/5a2c80d96b1d2dba447ff18d873e5fb73ba03c35/cdm). Bản quyền OpenDataLab 2024. Điều khoản Apache 2.0 nằm trong `LICENSE`. Ba giấy phép MIT đi kèm giữ ghi công KaTeX, match-at và im2markup. Thư mục tokenizer upstream lấy từ [im2markup](https://github.com/harvardnlp/im2markup).

Adapter `formula_cdm.py` thay cách điều phối tiến trình, raster hóa và ghi kết quả. Các entry point dùng shell của upstream không được đóng gói. `PROVENANCE.json` phân biệt file giữ nguyên với mã tích hợp của dự án.
