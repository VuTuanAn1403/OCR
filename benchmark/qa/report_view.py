"""Self-contained local QA dashboard; the browser never reads holdout artifacts."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from urllib.parse import quote

from .evidence import EvidenceStore


def render(report, output, evidence_root):
    output = Path(output).resolve()
    store = EvidenceStore(evidence_root)
    data = deepcopy(report)
    # File paths in holdout manifests are not browser data. Expose the hash only.
    data["sources"] = {key: {"sha256": ref["sha256"]} for key, ref in data["sources"].items()}
    for finding in (data["registry"] or {}).get("findings", []):
        assets = finding["crop"]["assets"]
        for name, ref in assets.items():
            path = store.verify(ref)
            relative = Path(os.path.relpath(path, output.parent)).as_posix()
            assets[name] = {"href": quote(relative, safe="/"), "sha256": ref["sha256"]}
    encoded = json.dumps(data, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    # Escape script delimiters even in a non-executable JSON script element.
    encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return _PAGE.replace("@@REPORT_DATA@@", encoded)


def write_html(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content.encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


_PAGE = r'''<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src file: data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>OCR PDF · Bàn QA</title>
<style>
:root{color-scheme:light;--ink:#17232d;--muted:#566675;--surface:#fff;--bg:#f5f7f9;--line:#d5dfe6;--accent:#28547b;--wash:#e9f0f6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,sans-serif}
main{max-width:1180px;margin:auto;padding:36px clamp(16px,4vw,48px) 64px}header{border-top:4px solid var(--accent);padding:19px 0 13px}
h1{font-size:26px;line-height:1.2;margin:6px 0 12px}h2{font-size:19px;margin:0 0 12px}h3{font-size:16px;margin:16px 0 8px}
p{margin:0 0 10px}.eyebrow{font-size:12px;letter-spacing:.13em;text-transform:uppercase;color:var(--accent);font-weight:650}
.muted,small{color:var(--muted)}.summary{display:flex;gap:25px;flex-wrap:wrap;padding:15px 0 18px;border-bottom:1px solid var(--line)}
.summary strong{display:block;font-size:22px;font-variant-numeric:tabular-nums}.summary span{font-size:13px;color:var(--muted)}
nav{display:flex;gap:5px;flex-wrap:wrap;margin:20px 0 18px;border-bottom:1px solid var(--line)}
button,input{font:inherit;color:inherit}button{background:transparent;border:0;border-bottom:3px solid transparent;padding:9px 13px;cursor:pointer}
button[aria-pressed="true"]{border-color:var(--accent);color:var(--accent);font-weight:650}button:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.scroll{overflow-x:auto;border:1px solid var(--line);background:var(--surface);border-radius:5px}
table{border-collapse:collapse;width:100%;min-width:770px;font-variant-numeric:tabular-nums}th,td{text-align:left;vertical-align:top;padding:10px 12px;border-bottom:1px solid var(--line)}
thead th{background:var(--wash);font-size:13px}tbody tr:last-child>*{border-bottom:0}.pill{font-size:12px;line-height:1.4;display:inline-block;border:1px solid var(--line);border-radius:4px;padding:2px 6px;white-space:nowrap}
.measured{color:#1d5d47;border-color:#9ebfaf}.partial{color:#735318;border-color:#cfbd91}.field{display:block;margin:4px 0;color:var(--muted);font-size:12px;overflow-wrap:anywhere}
.search{width:min(100%,520px);border:1px solid var(--line);padding:8px 10px;border-radius:4px;background:var(--surface);margin:4px 0 14px}
.finding{background:var(--surface);border-bottom:1px solid var(--line);padding:10px 12px}.finding summary{cursor:pointer;overflow-wrap:anywhere}
.finding p{margin:8px 0}.finding pre{max-height:220px;overflow:auto}.finding img{display:block;width:auto;max-width:100%;max-height:240px;border:1px solid var(--line);margin:6px 0}
pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:6px 0;padding:9px;background:var(--bg);border:1px solid var(--line);border-radius:4px;font-size:13px}
code{overflow-wrap:anywhere;font-size:12px}a{color:var(--accent)}.split{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.source{padding:8px 0;border-bottom:1px solid var(--line);overflow-wrap:anywhere}[hidden]{display:none!important}
@media(max-width:620px){main{padding-top:19px}.split{grid-template-columns:1fr}.summary{gap:12px 20px}h1{font-size:23px}}
</style></head><body><main>
<header><p class="eyebrow">OCR PDF / Quality assurance</p><h1>Báo cáo QA offline</h1>
<p id="quality"></p><p class="muted" id="summary-note"></p><div class="summary" id="summary"></div></header>
<nav aria-label="Mục báo cáo"><button data-tab="metrics" aria-pressed="true">Chỉ số</button><button data-tab="review" aria-pressed="false">Review</button><button data-tab="evidence" aria-pressed="false">Bằng chứng</button></nav>
<section id="metrics"><h2>Chỉ số theo phạm vi đo</h2><p class="muted">Baseline, candidate và detector diagnostic được giữ riêng. Tử/mẫu số lấy từ count của evaluator.</p>
<div class="scroll"><table aria-label="Chỉ số QA"><thead><tr><th>Chỉ số</th><th>Trạng thái và phạm vi</th><th>Baseline</th><th>Candidate / diagnostic</th><th>Fix / harm</th></tr></thead><tbody id="metric-rows"></tbody></table></div></section>
<section id="review" hidden><h2>Mục review và truy nguồn</h2><p class="muted" id="review-note"></p><div id="review-content"></div></section>
<section id="evidence" hidden><h2>Nguồn và phạm vi</h2><p class="muted">Mỗi nguồn giữ hash riêng. Dashboard không mở nội dung hoặc định danh từng unit holdout.</p><div id="source-content"></div></section>
<noscript>Bật JavaScript để xem bộ lọc và mục chi tiết trong báo cáo offline này.</noscript>
</main><script type="application/json" id="report-data">@@REPORT_DATA@@</script>
<script>
"use strict";
const report = JSON.parse(document.getElementById("report-data").textContent);
const $ = id => document.getElementById(id);
function add(parent, tag, value, css) {
  const node = document.createElement(tag);
  if (value !== undefined && value !== null) node.textContent = String(value);
  if (css) node.className = css;
  parent.appendChild(node); return node;
}
const labels = {cer:"CER · lỗi ký tự",wer:"WER · lỗi từ",der:"DER · lỗi dấu tiếng Việt",teds_content:"TEDS · nội dung bảng",teds_structure:"TEDS · cấu trúc bảng",
 numeric_cell_exact:"Ô số đúng giá trị và vị trí",reading_order:"Thứ tự đọc",keyword_recall:"Recall từ khóa",layout_recall:"Recall vùng layout",
 layout_errors_per_gt:"Lỗi layout trên vùng GT",text_detection_recall:"Recall detector chữ",text_detection_precision:"Precision detector chữ",text_detection_hmean:"Hmean detector chữ",
 formula_detection_recall:"Recall phát hiện công thức",formula_detection_errors_per_gt:"Lỗi phát hiện công thức / GT",formula_text_cer:"CER công thức TEXT",
 formula_text_exact:"Công thức TEXT khớp",formula_cdm_mean:"CDM · điểm render công thức",formula_critical_error_rate:"Tỷ lệ lỗi công thức nghiêm trọng",
 review_precision:"Precision review",review_recall:"Recall review",review_miss_rate:"Tỷ lệ lỗi lọt review",review_seconds:"Thời gian review",review_cost:"Chi phí review",
 runtime_throughput:"Thông lượng",runtime_latency_p95:"Độ trễ p95",runtime_peak_rss:"Đỉnh RAM",runtime_peak_vram:"Đỉnh VRAM",export_completeness:"Độ đầy đủ đầu ra"};
const reasons = {NO_PAIRED_REPORT:"Chưa có báo cáo trước/sau",PREFLIGHT_NOT_READY:"Preflight chưa đủ điều kiện",METRIC_NOT_IN_FROZEN_SAMPLE:"Ngoài mẫu đã khóa",
 NO_PRIMARY_DETECTOR_REPORT:"Chưa có báo cáo detector pha A",NO_VERIFIED_ADAPTER_INPUT:"Chưa có nguồn đã xác minh",
 INCOMPLETE_SCOPE:"Phạm vi chưa chấm đủ",ZERO_REFERENCE_DENOMINATOR:"Mẫu số của chỉ số bằng 0",PAIR_HAS_UNSCORED_OR_ZERO_REFERENCE_SCOPE:"Thiếu đơn vị chấm hoặc mẫu số",
 PARTIAL_OR_EMPTY_SCOPE:"Phạm vi chưa đủ",NO_BASELINE_WRONG_UNITS:"Không có đơn vị sai trước sửa",NO_BASELINE_CORRECT_UNITS:"Không có đơn vị đúng trước sửa",EMPTY_REFERENCE:"Không có vùng GT thường"};
const number = new Intl.NumberFormat("vi-VN", {maximumFractionDigits:6});
const percent = new Intl.NumberFormat("vi-VN", {style:"percent", maximumFractionDigits:4});
const fmt = x => x == null ? "—" : number.format(x);
const rate = x => x == null ? "—" : percent.format(x);
const reason = code => reasons[code] || code || "";
function badge(parent, status) { add(parent,"span",status,"pill " + (status === "MEASURED" ? "measured" : status === "PARTIAL" ? "partial" : "")); }
function fact(value, title) {const d=add($("summary"),"div");add(d,"strong",fmt(value));add(d,"span",title);}
$("quality").textContent = "Chất lượng OCR: " + report.quality_status;
$("summary-note").textContent = "Số liệu chỉ mô tả từng nguồn và đơn vị đã chấm; không có điểm độ chính xác tổng hợp.";
if (report.registry) {
  fact(report.registry.distinct_findings,"Hồ sơ từ registry");
  fact(report.registry.source_documents_with_findings,"Tài liệu có hồ sơ");
  fact(report.registry.source_pages_with_findings,"Trang có hồ sơ");
}
fact(report.metric_states.MEASURED || 0,"Chỉ số có số đo theo phạm vi");
function measure(cell, value) {
  if (!value) { add(cell,"span","—","muted"); return; }
  add(cell,"strong",rate(value.value));
  if (value.numerator != null) add(cell,"span",fmt(value.numerator)+" / "+fmt(value.denominator),"field");
  add(cell,"span",fmt(value.scored_units)+" / "+fmt(value.declared_units)+" đơn vị có count","field");
  if (value.missing_output_units) add(cell,"span",fmt(value.missing_output_units)+" thiếu đầu ra","field");
  if (value.reason) add(cell,"span",reason(value.reason),"field");
}
for (const [key, metric] of Object.entries(report.metrics)) {
  const tr=add($("metric-rows"),"tr");const name=add(tr,"th",labels[key]||key);name.scope="row";
  const state=add(tr,"td");badge(state,metric.status);
  if (metric.reason) add(state,"span",reason(metric.reason),"field");
  if (metric.scope) add(state,"span",[metric.scope.partition||"partition chưa khai báo",metric.scope.kind,metric.scope.definition].join(" · "),"field");
  measure(add(tr,"td"),metric.values?.baseline);measure(add(tr,"td"),metric.values?.candidate||metric.values?.diagnostic);
  const pair=add(tr,"td");const effect=metric.paired_effects;
  if (!effect) add(pair,"span","—","muted"); else {
    add(pair,"span","Fix "+rate(effect.fix_rate)+" · "+fmt(effect.fixed)+"/"+fmt(effect.baseline_wrong));
    add(pair,"span","Harm "+rate(effect.harm_rate)+" · "+fmt(effect.harmed)+"/"+fmt(effect.baseline_correct),"field");
    add(pair,"span",fmt(effect.paired_units)+"/"+fmt(effect.declared_units)+" cặp chấm được","field");
    if(effect.fix_rate_reason) add(pair,"span",reason(effect.fix_rate_reason),"field");
    if(effect.harm_rate_reason && effect.harm_rate_reason!==effect.fix_rate_reason) add(pair,"span",reason(effect.harm_rate_reason),"field");
  }
}
const registry=report.registry;
$("review-note").textContent=registry?"Các mục dưới là hồ sơ truy vết. Tín hiệu review hoặc phát hiện lịch sử chưa xác nhận lỗi hiện tại.":"Chưa nạp Error Registry.";
if(registry){
  const content=$("review-content");
  for(const [key,count] of Object.entries(registry.finding_kinds)) add(content,"p",key+": "+fmt(count),"muted");
  if(registry.findings.length){
    const input=add(content,"input",null,"search");input.type="search";input.placeholder="Lọc mã, tài liệu, trang hoặc lý do";input.setAttribute("aria-label","Lọc hồ sơ review");
    const matches=add(content,"p",null,"muted");const list=add(content,"div");const indexed=[];
    for(const item of registry.findings){
      const source=item.source;const row=add(list,"details",null,"finding");row.dataset.errorId=item.error_id;
      const title=[source.document_id,source.page==null?null:"trang "+source.page,item.error_codes.join(", ")||"chưa phân loại",item.lifecycle].filter(Boolean).join(" · ");
      add(row,"summary",title);add(row,"span",item.error_id,"field");
      add(row,"p",item.review_reasons.join(" · "));
      add(row,"span","Nguồn: "+(source.source_id||"chưa có ID")+" · "+JSON.stringify(source.locator),"field");
      add(row,"span","Khung: "+(source.coordinate_space||"chưa có")+" · bbox "+(source.bbox?JSON.stringify(source.bbox):"chưa đặt được"),"field");
      add(row,"span","Nguyên nhân: "+(item.root_cause_status==="UNVERIFIED"?"chưa xác minh":"có khai báo và bằng chứng trong registry"),"field");
      const split=add(row,"div",null,"split");for(const [label,text] of [["Chữ thô",item.actual.text_raw],["Chữ xuất",item.actual.prediction]]){
        const block=add(split,"div");add(block,"h3",label);add(block,"pre",text==null?"Chưa có":text);
      }
      if(item.crop.reason) add(row,"p","Crop chưa có: "+item.crop.reason,"muted");
      for(const [name,asset] of Object.entries(item.crop.assets)){
        const link=add(row,"a","Mở crop "+name);link.href=asset.href;
        const img=add(link,"img");img.loading="lazy";img.alt="Ảnh nguồn "+name;img.src=asset.href;
        add(row,"span","SHA-256 "+asset.sha256,"field");
      }
      indexed.push([row,[title,item.error_id,source.source_id,...item.review_reasons].join(" ").toLocaleLowerCase("vi")]);
    }
    function filter(){const q=input.value.trim().toLocaleLowerCase("vi");let n=0;for(const [row,words] of indexed){row.hidden=!words.includes(q);if(!row.hidden)n++;}matches.textContent=fmt(n)+" mục phù hợp";}
    input.addEventListener("input",filter);filter();
  }else add(content,"p","Chưa bật chi tiết development, hoặc nguồn không có mục được phép hiển thị.","muted");
}
const evidence=$("source-content");
for(const [name,source] of Object.entries(report.sources)){
  const section=add(evidence,"div",null,"source");add(section,"strong",name);add(section,"p","SHA-256 "+source.sha256,"field");
}
if(report.paired){add(evidence,"p","Preflight: "+report.paired.preflight_status+" · "+fmt(report.paired.readiness_issue_count)+" mục cần xử lý.");
 add(evidence,"p","Protocol SHA-256 "+report.paired.protocol_sha256,"field");
 add(evidence,"p","Holdout chỉ hiển thị thống kê tổng hợp.","muted");
 const locked=Object.entries(report.paired.verified_artifact_hashes);
 if(locked.length){const details=add(evidence,"details");add(details,"summary","Hash artifact đã khóa");for(const [name,sha] of locked)add(details,"p",name+" · "+sha,"field");}
}
for(const button of document.querySelectorAll("button[data-tab]"))button.addEventListener("click",()=>{
  for(const b of document.querySelectorAll("button[data-tab]")){const active=b===button;b.setAttribute("aria-pressed",String(active));$(b.dataset.tab).hidden=!active;}
});
</script></body></html>
'''
