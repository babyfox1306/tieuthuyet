# Audit: Concept → Plan → Prompt

> Read-only architecture report. Evidence from engine code plus live workspace `the-ninth-bell`. No code was changed.

## Kết luận cứng

Hệ thống hiện tại **không phải compiler fidelity**. Nó là chuỗi LLM rewrite (develop → bible → outliner → writer) với gate phần lớn chỉ kiểm schema / digest / heuristic. Vì vậy concept hay cũng có thể thành plan / prompt sai — và approve vẫn qua. Writer "ngu" không phải gốc bệnh; gốc bệnh là tầng trước prompt không chứng minh bám concept.

| Chỉ số | Giá trị |
|--------|---------|
| Tầng trong chuỗi | 8 |
| Lỗ critical | 8 |
| Lỗ high | 8 |
| Gate fidelity thật | 0 |

---

## Chúng ta đang cần gì

Mục tiêu đúng cho dây chuyền: **concept khóa → narrative/plan là executable spec → prompt chN là phép chiếu deterministic của plan đã duyệt**. Writer chỉ thực thi. Nếu kết quả dở, lỗi thuộc concept hoặc thuộc compiler/plan — không đổ cho "AI viết chưa hay".

Điều đó đòi hỏi mỗi bước sau concept phải chứng minh coverage / entailment / non-contradiction, không chỉ "field không rỗng" hay "digest chưa stale".

---

## Luồng thật hiện nay

| Tầng | Máy làm gì | Có chứng minh bám concept? |
|------|------------|----------------------------|
| 1. Concept ready | SAT cấu trúc + độ dài directive blob + status=ready | ⚠️ Không — không khóa chapter map / POV schema / must_include coverage |
| 2. develop-narrative | 6 pass LLM rewrite concept → kernel/ledger/threads/matrix | ❌ Không — validate chỉ file + field nonempty + ID graph |
| 3. architect bible | LLM sinh series.json; cắt author_directive 4k; bỏ surface/true_plot | ❌ Không — role romance-biased; schema validate |
| 4. Story Contract | Compile optional; semantic candidates cần review | ⚠️ Mặc định OFF — không bảo vệ production path |
| 5. plan / outliner | LLM sinh chapter_plans theo act; không nhận concept.yaml | ❌ Không — không so chapter map concept ↔ plan |
| 6. approve-plan | Digest + plan QC + phrase/canon heuristics (+ contract nếu enforced) | ❌ Không chứng minh semantic fidelity / ending / causality |
| 7. render prompt | Deterministic compile từ plan + bible + concept boundaries | ⚠️ Một phần — preflight bắt placeholder/POV; không bắt chapter-map drift |
| 8. writer | Thực thi prompt + LLM QC loop | Phụ thuộc prompt; nếu prompt đã sai thì viết đúng cái sai |

---

## Phát hiện nghiêm trọng (xếp hạng)

### 🔴 C1 — Không có gate fidelity concept → narrative / plan
approve-narrative / approve-plan không so `kernel.true_case` với `concept.true_plot`, không so chapter progression trong author_directive với chapter_plans, không bắt buộc must_include xuất hiện đúng chương. Digests chỉ chứng minh bytes chưa đổi, không chứng minh nghĩa còn đúng.
**Evidence:** `narrative_schema.validate_narrative_assets`; `master_plan.approve_plan`; `concept_canon.artifact_stale_errors`

### 🔴 C2 — Outliner không nhận concept / book_arc / chapter map
`build_outliner_payload` chỉ gửi bible, direction, prior_plans, locked names, chapter_canon_rules, narrative_constraints (clue IDs), optional Story Contract. `concept.yaml` và book_arc descriptions không vào payload. Chapter map chi tiết trong author_directive chỉ sống nếu LLM trước đó tình cờ giữ lại.
**Evidence:** `master_plan.py build_outliner_payload`; `roles/outliner.txt`

### 🔴 C3 — Bằng chứng sống: the-ninth-bell — plan duyệt đã lệch concept
Concept khóa: ch3 future confession; ch4 micro-splices; ch8 vào chamber + Elin tape; ch9 reconstruct + stop Thomas; ch10 public confess + coda. Plan approved: ch3 còn phân tích edit; ch4 gộp confession+splices; ch8 chỉ cửa thép; ch9 chìa khóa; ch10 dồn chamber+tape+reconstruct+confess+coda. Approve vẫn pass.
**Evidence:** `concept.yaml:109-161`; `master_plan.json` ch3/4/8/9/10

### 🔴 C4 — iris_knows bị poison bằng god-knowledge của mọi nhân vật
Compiler gộp may_know của Clara + Gabriel + Mara + Thomas + Elin thành iris_knows. Prompt ch1 vừa REDACT đáp án mystery, vừa cho writer đọc "Thomas Vale: Knows everything… fabricated Clara's confession… froze instead of saving Elin". Đây là mâu thuẫn authority ngay trong prompt.
**Evidence:** `narrative_compiler._knowledge_for_chapter / _split_iris_knows_and_truth`; `prompts/ch_001.txt` Knowledge gates

### 🔴 C5 — Prompt ch1 tự spoil world rules trước reveal
LOCKED CANON World rules ở ch1 đã viết: hệ thống do Thomas tạo; ninth bell fabricated; legend là cover. Đồng thời central mystery answer bị REDACT. Writer bị kéo về romance role header dù concept cấm romance. must_include của cả cuốn bị dump vào mọi chương.
**Evidence:** `prompt_builder.render_locked_canon_block` + world_rules từ series.json; language_profile romance header

### 🔴 C6 — merge_narrative_into_plans tự bơm clue ID → QC xanh giả
Compiler ghi đè narrative, append `[CLUE]` vào must_happen. NC-01..07 chủ yếu kiểm ID do chính compiler gắn; NC-07 chấp nhận chính ID đó như bằng chứng beat đã viết. Plan có thể không dramatize clue mà vẫn pass.
**Evidence:** `narrative_compiler.merge`; `plan_qc` NC-01..07; Audit narrative to plan

### 🔴 C7 — must_not_know_before dạng prose bị bỏ silent
Parser chỉ nhận int+hidden_truth hoặc dict fact→chapter. Matrix Ninth Bell lưu chuỗi prose → compile ra `must_not_know:[]`. Cấm biết sớm biến mất trước khi NC-06 kịp quét.
**Evidence:** `narrative_compiler.iter_must_not_know_before`; `knowledge_matrix.json`

### 🔴 C8 — Live false-green: the-bell-names-the-dead
Concept có Elena Voss / Edmund Rusk. Registry+bible+plan+prompts khóa Female Lead / Male Lead. Digests FRESH, plan approved. Writer/catalog đã đoán tên Elena — promote qua dù prompt hỏng. Parser lead chỉ khớp nhãn 'Female lead: Name'.
**Evidence:** Audit tests; `canon_registry._parse_lead_from_concept_text`

### 🟡 H1 — Lead placeholders / sync hỏng schema
Plan dùng Female Lead / Male Lead. Registry có thể canonicalize placeholder. book_arc dùng `lead_internal_arc[].name` nhưng sync tìm `.character` → không heal. Preflight bắt placeholder nếu còn trong prompt text, nhưng plan đã duyệt vẫn có thể mang placeholder nếu render/substitution tạm che.
**Evidence:** `canon_registry resolve/sync`; ninth-bell master_plan; prompt_preflight

### 🟡 H2 — Story Contract mặc định off; dict surface_order không compile
Contract là lớp đúng hướng để khóa must_include/ending/binding, nhưng mode default off. `compile_deterministic_from_concept` chỉ nhận surface_order dạng list; production dùng dict → bị drop. Semantic extract từ free text cần review thủ công.
**Evidence:** `story_contract/modes.py`; `compile.py` surface_order branch

### 🟡 H3 — Architect / profile defaults làm lệch genre
`architect.txt` mở đầu thiết kế series ngôn tình; payload bỏ surface_plot/true_plot; planned_books hardcode 5. `infer_narrative_profile` keyword-only; fallback validate có thể kéo romance_thriller asset set / romance thread.
**Evidence:** `roles/architect.txt`; `bible_architect.build_architect_payload`; `workspace_metadata.infer_narrative_profile`

### 🟡 H4 — NC plan QC bắt schedule clue, không bắt drama đúng chương concept
NC-01..07 chứng minh clues_plant/payoff khớp ledger và có trong beats. Ledger chính là output LLM từ concept đã bị paraphrase. Nếu ledger dời chamber từ ch8→ch10, QC vẫn xanh vì plan khớp ledger sai.
**Evidence:** `plan_qc.validate_narrative_plan`; mystery_ledger C009 plant 8 / payoff 10 vs concept ch8 entry

### 🟡 H5 — Approve ≠ prompt immutable; write rebuild prompt live
`plan_book` có render_all_prompts, nhưng write path `build_writer_payload` gọi lại `build_chapter_prompt` từ master_plan hiện tại. File `prompts/*.txt` không phải sole source-of-truth lúc viết. Approve-plan CLI không bắt buộc render; UI có thể khác CLI.
**Evidence:** `run_factory.build_writer_payload`; `master_plan.approve_plan`; `render_all_prompts`

### 🟡 H6 — Không có gate prose bám plan; check_must_happen_anchors chết
Hàm `check_must_happen_anchors` đã viết nhưng không được gọi. LLM QC không có dimension beat_coverage. Chương bỏ must_happen vẫn có thể READY. File `prompts/*.txt` chỉ decorative — write rebuild prompt live từ plan+bible+registry.
**Evidence:** `plan_compliance.py`; `run_factory.build_writer_payload`; Audit plan to prompts

### 🟡 H7 — Auto-prep tự approve narrative/bible; UI approve-plan lệch preflight
Batch prep: develop→validate→approve-narrative→architect→approve-bible→plan→approve-plan. Không cửa người. UI: `approve_plan()` chạy trước; PromptPreflightError trả `ok:false` nhưng `plan_approved:true`. CLI approve-plan không render.
**Evidence:** `factory_workflow._prep_steps / approve path`; Audit tests

### 🟡 H8 — Bible/registry drift sau approve không bị chặn
Narrative snapshot được pin; `bible/series.json` và `canon_registry` đọc live lúc write. Sửa bible sau approve đổi prompt im lặng trong khi plan vẫn 'approved & fresh'. Snapshot có ghi digest bible/canon nhưng không so tại write.
**Evidence:** `prompt_builder` live load; narrative_snapshot manifest digests

### ⚪ M1 — must_include dump toàn cuốn vào mọi prompt
Content requirements liệt kê cả ending conditions ở ch1. Writer bị nhiễu bởi obligation tương lai; preflight không phân chương hóa must_include.
**Evidence:** `prompt_builder._content_boundaries_for_prompt`; `ch_001.txt` MUST INCLUDE block

### ⚪ M2 — Ending / sequel contradiction không hard-fail
Ninth Bell concept: `hook_book2 = No sequel hook`. Plan ch10 carries_to_next nói sang 'next book'. Approve không bắt mâu thuẫn standalone vs sequel handoff.
**Evidence:** `concept.yaml hook_book2`; `master_plan.json ch10 carries_to_next`

---

## Vì sao concept → plan/prompt sai?

### Chuỗi mất mát (lossy chain)

| Bước | Mất gì | Hệ quả |
|------|--------|--------|
| Concept → narrative LLM | Chapter map chi tiết trở thành paraphrase tự do | Ledger/threads có thể dời beat sang chương khác |
| Narrative → bible LLM | surface/true_plot không feed đủ; romance bias | World rules / leads / mystery shape lệch |
| Narrative → outliner | Concept không vào payload | Plan chỉ bám ledger/bible đã lệch |
| Approve gates | Chỉ schema/digest/heuristic | Plan sai vẫn approved |
| Prompt compile | Dump world rules + full must_include + iris_knows bẩn | Prompt tự mâu thuẫn / spoil / nhiễu genre |
| Writer | Thực thi prompt sai | 10 giờ viết vẫn dở vì đang tối ưu sai spec |

---

## Bằng chứng Ninth Bell (tóm tắt)

| Concept khóa | Plan/prompt thực tế | Ý nghĩa |
|--------------|---------------------|---------|
| Ch8: Gabriel đưa key; Clara vào chamber; tìm tape + editing gear | Ch8: mở cửa thép, chamber vẫn khóa; tape dời ch10 | Mất beat bắt buộc của concept |
| Ch9: reconstruct tape; nghe Thomas freeze; chặn phá tape | Ch9: Gabriel mới đưa key; lock quay từ trong | Climax bị đẩy / cắt |
| Ch10: public confess + coda siêu nhiên | Ch10 gánh luôn chamber + reconstruct + confess + coda | Nén quá tải; cấu trúc gãy |
| Ch1: chưa biết Thomas là thủ phạm | Prompt ch1 world rules + iris_knows Thomas full truth | Spoil / authority conflict |
| No romance | Prompt role: paid-chapter romance writer | Genre header sai |

---

## Gate giả-pass (nhìn như máy chặt, thực ra hở)

| Gate | Tưởng chứng minh | Thực tế |
|------|------------------|---------|
| concept --ready | Concept đủ chất lượng | Chỉ length/placeholder/SAT cấu trúc |
| approve-narrative | Narrative đúng concept | File tồn tại + field nonempty + clue IDs |
| approve-bible | Bible đúng truyện | Schema + một số canon heuristic |
| NC-01..07 | Plan đúng mystery design | Plan khớp ledger LLM (có thể đã lệch concept) |
| approve-plan | Plan executable trung thành | Fresh digest + QC hình thức; không chapter-map entailment |
| prompt preflight | Prompt sạch mâu thuẫn | Bắt placeholder/POV/title; không bắt spoil world-rules sớm hay must_include theo chương |

---

## Kiến trúc cần chuyển sang

> **Nguyên tắc:** Concept là source of truth bất biến. Mọi tầng sau là compiler artifacts. LLM chỉ được đề xuất candidate; máy phải chứng minh candidate trước khi approve. Writer không được bù cho spec kém.

### Intent lock (trước mọi LLM)

Compile concept → `IntentManifest` typed: POV, cast, chapter_count, chapter_map[1..N], must_include@chapter, must_avoid, surface_order, binding_condition, ending_book1, genre/profile (operator chọn, không keyword đoán), language.

### Các gate bắt buộc

| Gate | Chặn gì | Pass khi |
|------|---------|----------|
| G0 Concept lock | Directive rỗng / thiếu chapter_map / thiếu POV | Manifest complete + SAT |
| G1 Narrative fidelity | approve-narrative | surface/true/ending entailment + must_include coverage + cast ⊆ concept |
| G2 Ledger vs chapter_map | approve-narrative / plan | Mỗi beat khóa trong concept có plant/payoff/reveal đúng chương ±0 |
| G3 Plan fidelity | approve-plan | chapter_plans[n] covers IntentManifest.chapter_map[n]; no placeholder leads; ending obligations ở ch cuối |
| G4 Prompt projection | render / write | Prompt = deterministic view(plan[n], manifest[n]); no full-book must_include dump; iris_knows = POV only |
| G5 Contract on | plan/write/promote | Story Contract plan_enforced mặc định; dict surface_order compile được |

### Thay đổi máy cụ thể (ưu tiên)

| # | Việc | Lý do |
|---|------|-------|
| 1 | Outliner payload phải nhận IntentManifest / concept chapter_map | Hết phụ thuộc LLM nhớ gián tiếp |
| 2 | Sửa iris_knows = chỉ POV character | Chặn spoil god-knowledge trong prompt sớm |
| 3 | World rules / bible answer theo reveal ladder từng chương | Ch1 không được thấy Thomas-built-system nếu chưa unlock |
| 4 | must_include theo chương, không dump cả cuốn | Giảm nhiễu writer |
| 5 | Role/header theo profile concept, không hardcode romance | Genre fidelity |
| 6 | approve-plan atomic với prompt preflight + chapter-map check | Không còn approved-but-wrong |
| 7 | Cấm auto-approve narrative/bible trong batch prep | Operator mới được khóa intent |
| 8 | Acceptance tests I-NAME / I-MAP / I-COV không gọi LLM | Chặn tái phát bằng CI |

---

## Trả lời thẳng câu hỏi của bạn

**Từ concept đến plan/prompt sai vì đâu?**
Vì concept bị LLM viết lại nhiều lần, rồi plan được sinh từ bản viết lại đó, trong khi approve không đo "còn giống concept không".

**Writer ngu có phải gốc?**
Không. Writer chỉ theo prompt chN. Prompt chN đang mang spec lệch + spoil + genre sai thì viết "hay" cũng sai cấu trúc.

**Cần gì?**
Khóa concept thành manifest, bắt narrative/plan chứng minh coverage từng chương, prompt chỉ là projection deterministic. Lúc đó dở = concept dở; hay = concept hay.

---

## Phạm vi đã kiểm (nguồn audit)

Engine + live samples: the-ninth-bell, the-bell-names-the-dead, the-language-of-the-dead. Sub-audits: concept→narrative, narrative→plan, plan→prompts, tests/ops parity — all complete.
