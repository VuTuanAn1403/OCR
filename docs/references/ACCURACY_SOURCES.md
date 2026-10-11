# Nguồn khoa học và evaluator tham chiếu cho bộ đo accuracy

**Đối chiếu ngày 09/10/2026.** Đây là danh mục nguồn phục vụ triển khai, không phải danh sách kết quả thực nghiệm của OCR_pdf. Link `main/master` dưới đây để tìm mã; Anti phải chọn và lưu commit/version cụ thể trước nghiệm thu. Không ghi “đã pin” khi chưa có hash.

## 1. Công trình nghiên cứu

| ID | Công trình và nguồn chính | Cách dùng trong dự án |
|---|---|---|
| **S1** | Morris, Maier, Green (2004), *From WER and RIL to MER and WIL: improved evaluation measures for connected speech recognition*, Interspeech. [ISCA](https://www.isca-archive.org/interspeech_2004/morris04_interspeech.html), DOI [10.21437/Interspeech.2004-668](https://doi.org/10.21437/Interspeech.2004-668) | Định nghĩa WER theo căn chỉnh S/D/I. Bài thuộc nhận dạng tiếng nói; dự án thích nghi cách đo edit-based cho chuỗi OCR, không gọi đây là benchmark PDF. |
| **S2** | Zhong, ShafieiBavani, Jimeno Yepes (2020), *Image-based table recognition: data, model, and evaluation*, ECCV. [ECVA](https://www.ecva.net/papers/eccv_2020/papers_ECCV/html/3802_ECCV_2020_paper.php), [PDF](https://www.ecva.net/papers/eccv_2020/papers_ECCV/papers/123660562.pdf) | Nguồn TEDS và biểu diễn bảng. Dùng evaluator chính thức để đối chiếu cấu trúc và nội dung ô. Không lấy score của EDD/PubTabNet làm score của pipeline tiếng Việt. |
| **S3** | Lin và cộng sự (2014), *Microsoft COCO: Common Objects in Context*. [Bản tác giả trên arXiv](https://arxiv.org/abs/1405.0312) | Bối cảnh dataset/evaluation detection. Quy tắc chạy AP hiện dùng mã và parameters evaluator COCO ở T3; ảnh COCO không phải GT layout cho PDF hiện tại. |
| **S4** | Ouyang và cộng sự (2025), *OmniDocBench: Benchmarking Diverse PDF Document Parsing with Comprehensive Annotations*, được chấp nhận CVPR 2025. [Bản tác giả](https://arxiv.org/abs/2412.07626), [mã/dataset chính thức](https://github.com/opendatalab/OmniDocBench) | Tham khảo thiết kế đánh giá parsing end-to-end và theo thành phần/thuộc tính. Bộ tiếng Việt riêng phải công bố adaptation; kết quả trên nó không được gọi là score leaderboard OmniDocBench. |
| **S5** | Pfitzmann, Auer, Dolfi, Nassar, Staar (2022), *DocLayNet: A Large Human-Annotated Dataset for Document-Layout Analysis*, bản tác giả của công trình được chấp nhận SIGKDD 2022. [arXiv](https://arxiv.org/abs/2206.01062), [DOI xuất bản liên quan](https://doi.org/10.1145/3534678.3539043) | Tham khảo thiết kế đa nguồn, nhãn layout và kiểm tra đồng thuận gán nhãn. Khi trích bản xuất bản, dùng metadata của nhà xuất bản vì tên công trình có thể khác bản arXiv. |
| **S6** | Koehn (2004), *Statistical Significance Tests for Machine Translation Evaluation*, EMNLP, 388–395. [ACL Anthology](https://aclanthology.org/W04-3250/), [PDF](https://aclanthology.org/W04-3250.pdf) | Tham khảo bootstrap để đánh giá chênh lệch hệ thống. Cluster theo tài liệu cho OCR_pdf là lựa chọn thích nghi của dự án, cần mô tả riêng; không khẳng định bài gốc quy định document bootstrap cho OCR. |

## 2. Mã và tài liệu kỹ thuật chính thức

| ID | Nguồn | Yêu cầu triển khai |
|---|---|---|
| **T1** | [JiWER usage](https://jitsi.github.io/jiwer/usage/), [repository chính thức](https://github.com/jitsi/jiwer) | Dùng làm đối chiếu CER/WER độc lập, lưu version và transformations. Nó là thư viện tham chiếu, không được ghi thành bài báo peer-reviewed. Quy ước denominator=0 trong protocol dự án phải có adapter rõ ràng. |
| **T2** | [PubTabNet metric.py](https://github.com/ibm-aur-nlp/PubTabNet/blob/master/src/metric.py), [repository](https://github.com/ibm-aur-nlp/PubTabNet) | Pin commit và license. So parser/tree/content/denominator trên golden cases. Nếu wrapper canonicalize HTML, ghi scope adapted. |
| **T3** | [COCO evaluation documentation](https://cocodataset.org/dataset/detection-eval.htm), [COCOeval chính thức](https://github.com/cocodataset/cocoapi/blob/master/PythonAPI/pycocotools/cocoeval.py) | Dùng pycocotools và lưu params/version, box format/class/image mappings. Thực thi chính thức ưu tiên hơn tự viết approximation rồi đặt nhãn COCO. |
| **T4** | [OmniDocBench chính thức](https://github.com/opendatalab/OmniDocBench) | Pin dataset và evaluator commit nếu thực sự chạy benchmark đó. Tách track đối chiếu công khai và bộ tiếng Việt riêng. |

CER chia cho số ký tự GT; một số normalized edit distance khác dùng mẫu số khác. Không đổi tên NED thành CER hoặc trộn các công thức vào cùng cột. TEDS đơn bảng không đo detection bảng dư; cần detection precision/recall riêng. DER_VN_v1, NumericExact và custom precedence trong protocol là chỉ số do dự án định nghĩa/thích nghi, không được gán nguồn chính thức nếu công thức không trùng nguồn.

## 3. Bằng chứng cần lưu cho mỗi dependency tham chiếu

Trong `reference_implementations.json`, ghi: ID; paper/technical URL; repository; tag/commit/package version; hash source đang chạy; license; adapter path/hash; policy; lệnh tạo golden outputs; fixture hashes; so sánh parity/tolerance; ngày đối chiếu; trạng thái `PENDING` hoặc `VERIFIED` và phạm vi xác minh.

Không download toàn bộ dataset/model chỉ để gắn thêm citation. Chọn nguồn phù hợp câu hỏi, tuân thủ license và kiểm tra số đo trên data thật của dự án. Chưa có parity thì `PENDING`, chưa có GT thật thì `NO_GROUND_TRUTH`, chưa có actual run thì không có số liệu empirical.

## 4. Trích dẫn trong bài

Dùng [accuracy_metrics.bib](C:/kk_2/OCR_pdf/docs/references/accuracy_metrics.bib) như thư mục trích dẫn ban đầu. Entry arXiv ghi rõ bản tác giả và venue acceptance đã xác minh; khi nộp bài, thay metadata bằng bản xuất bản đúng edition nếu venue yêu cầu. Không thêm DOI/page range hoặc tên tác giả bằng suy đoán.

Mẫu mô tả phương pháp: “Chúng tôi đánh giá văn bản bằng edit-based CER và WER_ws; đánh giá bảng bằng adapter TEDS của PubTabNet; bố cục bằng COCOeval. Các metric bổ sung cho dấu và số được định nghĩa trong protocol. Phiên bản evaluator, normalization, matching và dataset manifests được lưu cùng mỗi run.” Đây là phương pháp dự kiến; chỉ chuyển sang thì đã thực hiện sau khi có implementation và evidence.
