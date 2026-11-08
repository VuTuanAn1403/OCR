# Taxonomy và đặc tả Error Registry

Ngày 07/11/2026. Đặc tả QA offline; phần audit ban đầu là DRAFT. Đã triển khai lát cắt registry v1 với schema, adapter operator review, validate và append CLI ngoài pipeline: [cách dùng và giới hạn](../../benchmark/qa/README.md). Các adapter khác và lifecycle nghiệm thu chất lượng chưa triển khai. Nền hiện hữu và bằng chứng ở [CURRENT_ARCHITECTURE](CURRENT_ARCHITECTURE.md); tiêu chí đo ở [BENCHMARK_PLAN](BENCHMARK_PLAN.md).

Taxonomy có 10 họ E01–E10, chia thành 14 mã cụ thể để bao phủ cả dấu tiếng Việt, layout, công thức và export. Mỗi mã là một khả năng cần kiểm, không phải khẳng định đã có lỗi thật. Một sự cố có thể có nhiều mã liên quan, nhưng chỉ một hồ sơ gốc và liên kết nhân quả đã được xác minh; không cộng các mã thành số lỗi độc lập.

## Quy ước mức độ và bằng chứng

- `CRITICAL`: tác động đã xác minh tới số/đơn vị/địa chỉ ô quan trọng, mất bằng chứng nguồn, hoặc công bố kết quả sai identity. Áp dụng theo impact và phạm vi đã khóa, không chỉ vì confidence thấp.
- `HIGH`: mất/thêm nội dung hay occurrence, sai order/cấu trúc ảnh hưởng kết quả; chưa đủ căn cứ xếp critical.
- `MEDIUM`: sai định dạng/cảnh báo/hiệu năng trong phạm vi không làm đổi dữ liệu nghiệp vụ đã kiểm.
- `UNASSESSED`: chưa đủ expected/actual để quyết định mức độ. Không tự nâng hoặc hạ theo engine score.

Các mức dưới là impact dự kiến khi lỗi được xác nhận. `root_cause` mặc định null. Module nghi ngờ là `HYPOTHESIS`, chỉ xác nhận khi trace và counterexample cô lập được biên gây lỗi. Chữ trong ảnh không rõ phải giữ unresolved; không suy expected từ nội dung kinh doanh.

## E01-PDF — Phân loại và đánh giá text layer

- **Mức:** HIGH; CRITICAL nếu dẫn tới bỏ nội dung hoặc dùng sai nguồn mà công bố thành dữ liệu đúng.
- **Nguồn:** PDF/hash, trang vật lý, text layer/raw spans, image coverage/visibility, inspector/routing metadata và ảnh render cùng view. Mã: [PDFInspector](../../src/ocr_pdf_io/pdf_inspector.py), [RoutingPolicy](../../src/ocr_recognition/routing_policy.py), [layer agreement](../../src/ocr_recognition/ocr_layer_agreement.py).
- **Tái hiện:** dùng cùng PDF/view, inspect và route trang rồi đối chiếu nhãn loại trang và nội dung từ ảnh. Kiểm hidden layer, text đúng bảng mã nhưng sai chữ, mixed page. Trong sản phẩm hiện tại phân loại không được bỏ OCR.
- **Nguyên nhân nghi ngờ:** heuristic density/visibility/Unicode hoặc transform; bất đồng hai prediction chỉ là tín hiệu.
- **Metric/sửa:** confusion theo loại trang và lỗi nội dung trên GT; chỉ điều chỉnh heuristic/gate sau khi có nhãn. Không bật native-first để “sửa” một ca phân loại.
- **Regression:** [test_native_quality](../../tests/unit/test_native_quality.py), [test_routing](../../tests/unit/test_routing.py), [test_unified_pipeline](../../tests/unit/test_unified_pipeline.py); bổ sung counterexample riêng nếu chưa có ca tương đương.

## E02-IMAGE — Render, crop và tiền xử lý

- **Mức:** HIGH khi mất dấu/chữ hoặc bbox sai; UNASSESSED nếu chỉ có blur/skew score.
- **Nguồn:** ảnh gốc và ảnh candidate, pixel hash, DPI, page rect/CropBox/Rotate, coordinate chain và crop frame. Mã: [PDFRenderer](../../src/ocr_pdf_io/pdf_renderer.py), [scan_image](../../src/ocr_pdf_io/scan_image.py), [fallback_engine](../../src/ocr_recognition/fallback_engine.py).
- **Tái hiện:** cùng crop/GT chạy nhánh giữ ảnh và nhánh candidate, map bbox trở lại frame nguồn; tách tác động render khỏi recognition. Không mặc định CLAHE/dewarp luôn cải thiện.
- **Nguyên nhân nghi ngờ:** scaling, transform, resampling hoặc bộ lọc làm mất nét/dấu.
- **Metric/sửa:** CER/DER và fix/harm paired theo điều kiện biến dạng, cộng tính đúng transform; chọn sửa nhỏ nhất, giữ ảnh trước/sau. Tái dùng [degradation_metric](../../benchmark/scientific_evaluation/degradation_metric.py).
- **Regression:** [test_degradation_metric](../../tests/scientific/test_degradation_metric.py), [test_degradation_corpus](../../tests/scientific/test_degradation_corpus.py), [test_region_cropper](../../tests/unit/test_region_cropper.py); không lấy điểm blur làm accuracy.

## E03-DETECTION — Bỏ sót hoặc thêm vùng chữ

- **Mức:** HIGH; tăng theo impact số/keyword bị mất khi đã xác minh.
- **Nguồn:** primary detector snapshot trước retry, hash ảnh, polygon/bbox/score/transform, GT vùng và ignore regions. Mã: [ONNXTextDetector](../../src/ocr_recognition/text_detector.py), [text_detection_metric](../../benchmark/scientific_evaluation/text_detection_metric.py).
- **Tái hiện:** đối chiếu GT region với mọi detection theo matching protocol đã khóa. Dòng không có trong Markdown chưa đủ để kết luận detector bỏ sót; kiểm nó có detection nhưng recognition rỗng hay bị downstream ẩn.
- **Nguyên nhân nghi ngờ:** resize/threshold/box decode/model; chưa loại trừ ảnh/transform thì chưa xác nhận cause.
- **Metric/sửa:** TP/FP/FN, recall/precision/F1 ở đúng detector scope; giữ vùng không có chữ nhận dạng. Chỉnh tham số trên development, không chọn theo holdout.
- **Regression:** [test_text_detection_metric](../../tests/scientific/test_text_detection_metric.py), caller [text_page](../../src/ocr_workers/text_page.py); thêm fixture ảnh/snapshot đúng identity cho lỗi thuật toán.

## E04-TEXT — Nhận dạng nội dung dòng

- **Mức:** HIGH; CRITICAL khi số/đơn vị quan trọng sai trên ảnh.
- **Nguồn:** detection và crop đúng, text_raw, transcription, confidence, model/runtime receipt, ứng viên hướng/repetition. Mã: [VietnameseSeq2SeqEngine](../../src/ocr_recognition/vietnamese_seq2seq_engine.py).
- **Tái hiện:** giữ bbox/ảnh đã phát hiện, so chữ dòng với GT độc lập; phân biệt đọc sai với mất detection hoặc ownership. Lưu raw ngay cả khi quality filter từ chối dòng.
- **Nguyên nhân nghi ngờ:** recognizer/crop orientation/tokenization/repetition; engine score không xác nhận chữ đúng.
- **Metric/sửa:** CER/WER_ws, numeric exact và nội dung target riêng; retry hoặc thay model chỉ sau paired fix/harm, không tự đoán token/số.
- **Regression:** [test_repetition_evidence](../../tests/unit/recognition/test_repetition_evidence.py), [test_retry_effects](../../tests/scientific/test_retry_effects.py), [test_fallback_numeric_guard](../../tests/unit/recognition/test_fallback_numeric_guard.py). Test numeric guard có thay đổi người dùng từ trước phải giữ nguyên trong audit.

## E04-VI — Dấu tiếng Việt

- **Mức:** HIGH khi đổi nghĩa/keyword; UNASSESSED nếu ảnh không đủ rõ để gán nhãn.
- **Nguồn:** crop/hash, raw và NFC text, slot dấu/ứng viên retry, quyết định áp dụng/bác và lý do. Mã: [diacritic_retry](../../src/ocr_recognition/diacritic_retry.py), [UnicodeNormalizer](../../src/ocr_text/unicode_normalizer.py).
- **Tái hiện:** so cả dòng và dấu trên ảnh; tách NFC hợp lệ khỏi thay nội dung. Giữ độc lập các gate hướng/ownership/protected.
- **Nguyên nhân nghi ngờ:** nhận dạng dấu, nét nhỏ hoặc retry; không kết luận normalize có lỗi chỉ vì byte raw khác NFC.
- **Metric/sửa:** DER_VN_v1 cùng CER và occurrence keyword; nhãn mark chưa phân xử không cho nghiệm thu. Không thêm/bỏ dấu chỉ dựa từ điển kinh doanh.
- **Regression:** [test_vietnamese_diacritics](../../tests/unit/text/test_vietnamese_diacritics.py), [test_diacritic_acceptance](../../tests/scientific/test_diacritic_acceptance.py), [test_vietnamese_diacritic_review](../../tests/unit/test_vietnamese_diacritic_review.py).

## E05-ORDER — Thứ tự đọc và nối cột

- **Mức:** HIGH khi đảo/nối nội dung làm sai ngữ nghĩa hoặc keyword.
- **Nguồn:** GT block IDs/precedence, prediction IDs/spans, graph edges/dispositions, column/article, source bbox và alignment đã rà. Mã: [resolve_document_layout](../../src/ocr_document/resolve_document_layout.py), [column_continuity](../../src/ocr_document/column_continuity.py).
- **Tái hiện:** giữ chữ và node nguồn, so đúng cặp thứ tự; thử trích dẫn giữa cột, bảng chắn cột, câu dang dở và node bị split/merge. Không dùng chỉ CER toàn trang.
- **Nguyên nhân nghi ngờ:** region partition, graph ordering hoặc continuation; phải xác định bước đầu tiên làm lệch order.
- **Metric/sửa:** precedence đúng trên GT pairs, penalize missing/duplicate nodes theo evaluator; sửa rule có trace và guard cấu trúc nguyên tử.
- **Regression:** [test_v62_reading_order_protocol](../../tests/scientific/test_v62_reading_order_protocol.py), [test_column_continuity](../../tests/unit/document/test_column_continuity.py), [test_pull_quote_flow](../../tests/unit/document/test_pull_quote_flow.py).

## E05-LAYOUT — Loại vùng, header/footer và binding

- **Mức:** HIGH khi ẩn nội dung thật hoặc ghép sai section/caption; MEDIUM nếu chỉ trình bày.
- **Nguồn:** vùng model/heuristic, GT class/bbox, role_initial/final, furniture support liên trang, caption/section IDs. Mã: [document_furniture](../../src/ocr_document/document_furniture.py), [canonical_layout](../../benchmark/scientific_evaluation/canonical_layout.py).
- **Tái hiện:** đối chiếu block role với ảnh/GT, kiểm header/footer lặp và caption gần bảng/hình; raw nguồn bị ẩn vẫn phải có evidence.
- **Nguyên nhân nghi ngờ:** model layout, furniture heuristic hoặc section/caption binding.
- **Metric/sửa:** layout TP/FP/FN theo class và lỗi loại vùng quan trọng; không đổi layout recall thành detector recall.
- **Regression:** [test_canonical_layout](../../tests/scientific/test_canonical_layout.py), [test_table_caption_binding](../../tests/unit/document/test_table_caption_binding.py), [test_content_flow_contract](../../tests/unit/document/test_content_flow_contract.py).

## E06-TABLE — Nội dung và cấu trúc bảng

- **Mức:** CRITICAL nếu sai số/đơn vị/năm/cột quan trọng; HIGH với span/header/continuation sai đã xác nhận.
- **Nguồn:** GT cell text/address/span, table bbox, physical cells, bridge/source mapping và logical projection. Mã: [Docling bridge](../../src/ocr_structure/ocr_bridge.py), [auto_table_stitch](../../src/ocr_document/auto_table_stitch.py), [structured_scoreboard](../../benchmark/scientific_evaluation/structured_scoreboard.py).
- **Tái hiện:** dùng extraction/response đã xác minh nếu đủ, phát lại downstream ở output mới; kiểm tách nội dung ô, vị trí hàng/cột, span và nối trang. Không dùng text giống nhau làm bằng chứng ô đúng.
- **Nguyên nhân nghi ngờ:** bridge/model/ownership/stitch; AGR/ASM là đầu mối development lịch sử, không tự kết luận hiện còn đúng cùng lỗi.
- **Metric/sửa:** TEDS content/structure, numeric cell exact tại địa chỉ và FP/FN, continuation/L5. Sửa biên có phản ví dụ, giữ ô vật lý/raw; không ngoại lệ theo công ty.
- **Regression:** [test_cross_cell_token_ownership](../../tests/unit/document/test_cross_cell_token_ownership.py), [test_source_glyph_ownership](../../tests/unit/document/test_source_glyph_ownership.py), [test_table_boundary_annotations](../../tests/scientific/test_table_boundary_annotations.py).

## E06-FORMULA — Công thức và ký hiệu quan trọng

- **Mức:** HIGH/CRITICAL theo tác động ký hiệu/nội dung đã xác minh; scope công thức hiện bắt buộc theo hồ sơ dự án.
- **Nguồn:** crop, GT độc lập, formula source/locator, renderer identity và critical-symbol adjudication. Mã: [formula_alignment](../../benchmark/scientific_evaluation/formula_alignment.py), [formula_content](../../benchmark/scientific_evaluation/formula_content.py), [formula_policy](../../benchmark/scientific_evaluation/formula_policy.py).
- **Tái hiện:** căn source/GT rồi so nội dung và render theo policy đã khóa; không dùng bbox đúng hoặc CDM đơn lẻ thay chứng minh nội dung.
- **Nguyên nhân nghi ngờ:** phát hiện/căn vùng, model nội dung, renderer hoặc alignment.
- **Metric/sửa:** metric công thức theo policy gồm nội dung/critical/CDM đúng scope; thiếu renderer/GT giữ NOT_EVALUATED, không tự duyệt dung sai mới.
- **Regression:** [test_formula_alignment](../../tests/scientific/test_formula_alignment.py), [test_formula_content](../../tests/scientific/test_formula_content.py), [test_formula_scorecard](../../tests/scientific/test_formula_scorecard.py).

## E07-OWNERSHIP — Truy nguồn, placement và lặp occurrence

- **Mức:** CRITICAL nếu mất/raw đổi nguồn hoặc công bố sai chủ sở hữu số; HIGH khi còn ambiguity đã được giữ review.
- **Nguồn:** source ID/hash/text_raw/bbox/frame, frozen/visible disposition, bridge line/token proof và cell owner. Mã: [ocr_bridge](../../src/ocr_structure/ocr_bridge.py), [resolve_document_layout](../../src/ocr_document/resolve_document_layout.py), [geometry contract](../../src/ocr_contracts/geometry.py).
- **Tái hiện:** replay mapping từ bằng chứng gốc; kiểm occurrence chỉ tiêu thụ đúng số lần, không dùng lại source hoặc suy token bbox bằng độ dài chữ. Bằng chứng glyph chỉ xác nhận placement theo hợp đồng, không chứng minh chữ trên ảnh đúng.
- **Nguyên nhân nghi ngờ:** source pool thiếu/trùng, coordinate transform, reconciliation hoặc exporter disposition.
- **Metric/sửa:** coverage source/disposition và số mapping thiếu/trùng/ambiguity trên scope đã kê; semantic ownership accuracy cần GT. Giữ null khi chưa biết owner, không gán “đúng” từ heuristic.
- **Regression:** hai test ownership của E06-TABLE, [test_content_flow_contract](../../tests/unit/document/test_content_flow_contract.py), [test_review_packet](../../tests/unit/test_review_packet.py).

## E08-POSTPROCESS — Thay đổi nội dung sau nhận dạng

- **Mức:** CRITICAL nếu đổi số/tiền tệ/đơn vị hoặc mất raw; HIGH khi đổi chữ/keyword chưa đủ bằng chứng.
- **Nguồn:** raw, normalized, candidate, disposition/applied, numeric spans và correction source. Mã: [numeric_guard](../../src/ocr_text/numeric_guard.py), [fallback_engine](../../src/ocr_recognition/fallback_engine.py).
- **Tái hiện:** cùng dòng trước/sau, replay guard và caller; kiểm dấu âm, ngoặc kế toán, %, ‰, currency, suffix và repetition. So NFC hợp lệ riêng với sửa nội dung.
- **Nguyên nhân nghi ngờ:** normalize/retry scoring/caller bỏ qua guard hoặc cleanup; không đổ mọi số sai cho hậu xử lý khi raw đã sai.
- **Metric/sửa:** exact protected spans, whole-line fix/harm và số ứng viên bị bác/áp dụng; giữ chữ bị loại và không sửa số bằng kiểm tài chính.
- **Regression:** [test_financial_numeric_guard](../../tests/unit/text/test_financial_numeric_guard.py), [test_fallback_numeric_guard](../../tests/unit/recognition/test_fallback_numeric_guard.py), [test_repetition_evidence](../../tests/unit/recognition/test_repetition_evidence.py).

## E09-KEYWORD — Đếm và ánh xạ occurrence

- **Mức:** HIGH khi sai kết quả nghiên cứu; mức critical chỉ khi impact được protocol xác định.
- **Nguồn:** result.md/hash, dictionary/policy snapshot, offsets NFC/casefold, GT unit/occurrence và alignment/source locator. Mã: [keyword_acceptance](../../benchmark/scientific_evaluation/keyword_acceptance.py), [alias_finalization](../../src/ocr_pipeline/alias_finalization.py).
- **Tái hiện:** kê từng match thiếu/thừa/không quy nguồn; trường hợp cùng tổng nhưng sai vị trí phải thất bại. Tách OCR miss khỏi đếm sai và literal khỏi alias. `literal_v1` đếm toàn Markdown là hợp đồng hiện hành, không tự đổi thành word-boundary.
- **Nguyên nhân nghi ngờ:** detection/recognition/order/ownership hoặc matcher/offset/publication; cần trace ngược để chọn module.
- **Metric/sửa:** precision/recall occurrence, missing/extra/unattributed/unannotated và coverage; dùng evaluator hiện có, không điều chỉnh workbook để ép khớp tổng.
- **Regression:** [test_keyword_acceptance](../../tests/scientific/test_keyword_acceptance.py), [test_keyword_counter](../../tests/unit/test_keyword_counter.py), [test_review_packet](../../tests/unit/test_review_packet.py).

## E10-EXPORT — Artifact và publication

- **Mức:** CRITICAL khi công bố thiếu/sai identity hoặc mất số/source; MEDIUM nếu chỉ layout workbook.
- **Nguồn:** expected artifact inventory, completion/receipt, hashes trên đĩa, validation, workbook readback, SQLite revision/ack. Mã: [export](../../src/ocr_document/export.py), [publication](../../src/ocr_pipeline/publication.py), [audit_batch_outputs](../../scripts/audit_batch_outputs.py).
- **Tái hiện:** bản sao output/snapshot riêng hoặc fixture; so expected set/hash/nội dung, từ chối thiếu/trùng/path thoát phạm vi, mô phỏng fail trước/sau acknowledge. Không chỉnh receipt gốc.
- **Nguyên nhân nghi ngờ:** exporter/projection/write/readback/ledger; API hỗ trợ thiếu TXT ở publication lịch sử không tự là lỗi.
- **Metric/sửa:** completeness trên mẫu số artifact/trang dự kiến, lỗi semantic readback riêng; validation PASS không là OCR accuracy.
- **Regression:** [test_document_review_gate_exports](../../tests/unit/test_document_review_gate_exports.py), [test_v63_pipeline](../../tests/unit/test_v63_pipeline.py), [test_migration_v63_export_baseline](../../tests/unit/test_migration_v63_export_baseline.py).

## E10-RUNTIME — Scheduler, resume và tài nguyên

- **Mức:** CRITICAL khi tái dùng sai stage/công bố số cũ; HIGH khi timeout/OOM/mất trang; MEDIUM khi vi phạm SLO đã duyệt mà dữ liệu vẫn đúng.
- **Nguồn:** input/config/code/model/runtime identity, stage keys, done/exited receipts, process tree, attempt/phase logs, resource traces và publication revision. Mã: [scheduler](../../src/ocr_pipeline/scheduler.py), [batch_store](../../src/ocr_pipeline/batch_store.py).
- **Tái hiện:** fixture hoặc fault plan trong output mới, giữ các điểm crash/timeout/OOM/cache/resume đã định trước. Không xóa lock hoặc dừng batch người dùng để tạo lỗi.
- **Nguyên nhân nghi ngờ:** supervision/cache/identity/ledger; process “đã trả response” chưa đủ chứng minh cả cây thoát.
- **Metric/sửa:** fail/timeout/retry/OOM theo workload, latency/resource và recovery consistency; giữ tài liệu failed/pending là unknown, không 0 count.
- **Regression:** [test_stage_cache](../../tests/unit/test_stage_cache.py), [test_v63_pipeline](../../tests/unit/test_v63_pipeline.py), [test_release_gate](../../tests/scientific/test_release_gate.py). Soak thật cần kế hoạch/evidence riêng.

## Hồ sơ registry đề nghị

Đây là **đặc tả metadata**, không thêm field vào extraction/receipt. Wire schema v1 ở [error_registry.py](../../benchmark/qa/error_registry.py), tham chiếu record hiện có qua adapter. V1 chỉ kiểm metadata/hash và lifecycle kỹ thuật; `QUALITY_ACCEPTED` chưa được hỗ trợ, vẫn dùng release workflow độc lập hiện hữu. Không coi việc kiểm hash là xác minh nội dung chứng cứ điều tra.

- **Identity:** `error_id`, `taxonomy_version`, `error_codes`, `related_issue_ids`, `record_revision`, thời điểm có timezone và nguồn người/công cụ tạo. ID không được gán lại cho lỗi khác; nhiều detector signal cùng sự cố không tạo nhiều lỗi độc lập.
- **Nguồn:** document ID/PDF SHA, physical page 1-based, region/source/table/cell locator, bbox cùng tên coordinate space/transform, source crop path/hash hoặc lý do crop chưa có. Lỗi batch/runtime có thể không áp page/bbox; dùng null và scope, không đặt trang 0 hay bbox giả.
- **Run:** baseline/candidate IDs, code HEAD **và dirty diff**, config/model/lock/interpreter/hardware references, extraction/publication/receipt hashes. Dẫn tới artifact bất biến; path tương đối phải ở trong evidence root được phép, chống path traversal và hash mismatch.
- **Expected/actual:** raw, normalized, prediction; `expected_kind` tách `CONTRACT_ORACLE`, `INDEPENDENT_GT`, `UNRESOLVED`. GT có annotation/alignment/custody hash và eligibility; contract fixture không thành GT accuracy. Thiếu expected giữ null.
- **Điều tra:** symptom, reproduction command/config/input, expected/actual tối thiểu, suspected modules và căn cứ; `root_cause: null` cho tới khi có cause evidence. Mỗi kết luận phải có locator và bước cô lập.
- **Sửa/kiểm:** proposed fix hoặc null, patch identity, counterexample-before, regression-after, source preservation proof, paired metric report, fix/harm scope/mẫu số và benchmark/release decision liên quan.
- **Trạng thái đề nghị:** `OPEN`, `NEEDS_REVIEW`, `REPRODUCED`, `CAUSE_VERIFIED`, `FIX_VERIFIED_TECHNICAL`, `QUALITY_ACCEPTED`. Đây là lifecycle offline dự thảo, không thay enum runtime. Trạng thái chất lượng luôn tách riêng: `NOT_EVALUATED`, measured report hoặc gate decision theo schema sẵn có.

Không tự chép các dòng backlog cũ thành lỗi hiện tại đã tái hiện. Import phải giữ original issue ID, ngày, artifact identity và nhãn historical; không di chuyển/xóa/sửa hồ sơ cũ để làm registry đẹp hơn. Các test được dẫn là điểm mở đầu đối chiếu; audit không tuyên bố chúng bao phủ hết 14 loại hoặc đã tái hiện mọi lỗi PDF.
