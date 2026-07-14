# SPEC — KDP Sub-niche Recon + Story Factory

> **Tài liệu này** = spec kiến trúc & quy tắc nghiệp vụ (source of truth).  
> **README.md** = hướng dẫn vận hành hàng ngày (lệnh, workflow, troubleshooting).  
> Hai file phải khớp nhau; khi đổi máy → cập nhật spec trước, README sau.

**Repo:** `tieuthuyet` / GitHub `babyfox1306/tieuthuyet_v2`  
**Cập nhật:** 2026-07-12

---

## 1. Tổng quan hệ thống

Ba vùng code + **hai tầng điều phối** (Publish Strategy, Narrative OS), một `.venv`:

```
RECON
  ↓ chọn sub-niche
PUBLISH STRATEGY GATE     ← sách này bán ở đâu? KU exclusive hay wide serial?
  ↓
NARRATIVE OS              ← hiểu truyện trước khi plan (kernel, ledger, threads…)
  ↓
FACTORY WRITE ENGINE      ← plan → prompt → write → QC (per-chapter)
  ↓ promote
CATALOG                   ← chỉ chương đã promote
  ↓ export gate (deterministic) + EPUBCheck
EXPORT                    ← EPUB/DOCX (KDP) | serial txt (Webnovel/RR…)
```

| Vùng | Mục đích | Entry |
|------|----------|-------|
| **`recon/`** | Quét thị trường đa nền tảng → DB + CSV + decision matrix | `.\run.ps1` |
| **`factory/`** | Sản xuất series theo chương (narrative → bible → plan → write → QC) | `.\factory\run_factory.ps1` hoặc `factory/ui/server.py` |
| **`catalog/`** | Bản giao hàng sạch — chỉ chương đã promote | đọc / export / upload |

**Triết lý:** recon tìm ngách → **chốt publish strategy** → **Story Brain** + **canon registry** → factory viết trong khung (format≠length≠content) → catalog + EG-01..12 + pen_name/cover → KDP.

**Factory hiện tại** = Narrative OS compiler + **canon registry** (approve-plan cast allowlist, LOCKED CANON) + plan QC (NC + absent-ML) + **machine_qc buckets** (format / length / content) + export gate **EG-01..EG-12** + EPUB `dc:creator` từ `pen_name` + cover.  
**LLM gateway:** OmniRoute (`start omni.bat`, port 20128), `model_routing: flexible`.  
**Pen names:** `Docs/pen_names_data.txt` — dark primary **Reynard Frost** (The Paper Oracle, The Salt Room).  
**Test máy:** `.\factory\run_checks.ps1`.

> **Không tạo máy viết truyện. Tạo máy hiểu truyện + khóa canon trước, rồi mới cho viết.** Invented cast phải chết ở plan/state — không phát hiện ở ch3 sau 10 lần rewrite.

---

## 2. Constraint cứng (charter)

1. **KDP account MỚI**, pen name MỚI — không link account cũ (Focus Math Press, email/phone/bank đã dùng).
2. **Validate trước build:** recon free trước. Không mua tool trả phí cho tới khi decision matrix chọn xong sub-niche.
3. **Passive / KU:** ưu tiên series 3+ book + KU enrolled. Skip standalone không binge.
4. **Signal > vanity:** BSR + review velocity > total review count.
5. **KDP content rule (hard line):**
   - Không nhân vật dưới 18 trong cảnh tình dục
   - Không incest, bestiality, non-con không redemption
   - Không real person (idol/celeb thật)
   - Erotica → category Erotica; spicy romance → Romance
6. **Publish exclusivity:** không đăng cùng nội dung digital lên nhiều kênh nếu đã enroll **KDP Select/KU** (xem §4.2).
7. **AI disclosure:** prose do AI generate → coi là **AI-generated** trên KDP (không chỉ AI-assisted); metadata bắt buộc trong `manifest.yaml` / `book.yaml` (xem §4.3).

---

## 3. RECON — Market scanner

### 3.1 Mục tiêu

Quét top listing đa nền tảng, lọc sub-niche thoả: demand cao + cung yếu + KU-friendly + AI-writable.  
Output = **decision matrix** → chọn series + **publish_strategy**.  
Workspaces KDP dark: **`the-paper-oracle`**, **`the-salt-room-1`** (`pen_name: Reynard Frost`).  
Thriller-romance: **`glass-meridian`** (`default_workspace`), **`ceo-contract`** (legacy).

### 3.2 Sub-niches quét (15)

**Group A — Asian aesthetic:** Xianxia, Wuxia, K-pop idol (fictional), K-drama CEO/contract, dark academia, romantasy Asian, VN mythology fantasy.

**Group B — Western tropes:** Mafia, dark romance/why choose, reverse harem, omegaverse, monster/alien, stepbrother (adult), bully (college+), billionaire × Asian twist.

### 3.3 Platforms (recon signal)

| Platform | Module | Ghi chú |
|----------|--------|---------|
| Amazon KDP | `scrapers/kdp_*.py` | BSR, KU, review velocity — **đầu ra publish chính** |
| Kindle Vella | `scrapers/vella.py` | Chỉ recon lịch sử; **Vella wind-down 26/02/2025** — không còn target publish |
| Webnovel | `scrapers/webnovel.py` | Wide serial |
| GoodNovel | `scrapers/goodnovel.py` | Wide serial |
| Royal Road | `scrapers/royalroad.py` | Wide serial / funnel |

### 3.4 Cấu trúc & CLI

```
recon/
├── main.py          # init | search | detail | reparse | tropes | matrix | full
├── scrapers/, pipeline/, core/, data/, output/
```

```powershell
.\run.ps1 init
.\run.ps1 search --platforms royalroad --subniches 1
.\run.ps1 matrix
.\run.ps1 full --platforms royalroad --subniches 1
```

### 3.5 Decision matrix

```
opportunity_score = (review_velocity × series_length × ku_rate)
                    / (supply_density × (1 + ai_suspicion_rate))
```

Output: `recon/output/subniche_decision_matrix.md` + CSV.

**Sau recon:** chọn sub-niche **và** `publish_strategy` trước khi `setup` workspace.

---

## 4. PUBLISH STRATEGY GATE

Tầng bắt buộc **trước Narrative OS và trước `plan`**. Trả lời: truyện này sinh ra để **KU exclusive** hay **wide serial**?

### 4.1 `publish_strategy` (trong `direction.yaml` hoặc `bible/narrative/publish_strategy.json`)

| Giá trị | Được | Không được (cùng nội dung digital) |
|---------|------|-------------------------------------|
| `kdp_ku_exclusive` | KDP eBook, paperback, KU, Amazon series page | Webnovel, GoodNovel, website public, Patreon public |
| `wide_serial` | Webnovel, GoodNovel, RoyalRoad, site riêng, EPUB bán ngoài KU | KDP Select / KU cho cùng nội dung digital |
| `draft_serial_then_kdp` | Test serial trước, sau đó KDP | Phải **gỡ / đổi** bản serial trước khi enroll KU — rule riêng, không làm bừa |

**KDP Select:** enrollment 90 ngày; eBook **exclusive Kindle Store** trong thời gian đó (print/audio có thể wide). Tham chiếu: [KDP Select](https://kdp.amazon.com/help/topic/G200798990), [enrollment](https://kdp.amazon.com/help/topic/GD9PMU58BV24QFZ7).

**Factory chặn `plan`** nếu `publish_strategy` chưa set hoặc xung đột với `target_platforms` trong `direction.yaml`.

### 4.2 Kindle Vella — không còn target publish

Amazon **wind down Kindle Vella** (effective 26 Feb 2025); episodes không còn mua trên Amazon — khuyến khích republish thành eBook. ([Vella FAQ](https://kdp.amazon.com/en_US/help/topic/GUJHP3574Z3DLPZD))

| Cũ (sai tư duy) | Mới (đúng) |
|-----------------|------------|
| `export --target vella` = đăng Kindle Vella | **`serial`** = per-chapter txt cho Webnovel/GoodNovel/RR |
| Platform chính: Vella + Webnovel | Platform chính: **KDP EPUB/DOCX** (+ KU nếu exclusive) hoặc **wide serial** |

**Code hiện tại:** CLI vẫn alias `vella` → `exports/vella/*.txt`. Spec coi đây là **legacy alias** của `serial`. Roadmap: thêm `--target serial`, giữ `vella` alias.

### 4.3 AI content metadata (bắt buộc)

Amazon yêu cầu disclose **AI-generated** content (text/images/translations do AI tạo, kể cả sau edit). AI-assisted không bắt buộc disclose nhưng publisher chịu trách nhiệm compliance. ([Content Guidelines](https://kdp.amazon.com/help/topic/G200672390))

Factory dùng AI viết outline + prose → coi là **ai_generated**, không chỉ assisted.

Thêm vào `manifest.yaml` hoặc `catalog/.../book.yaml`:

```yaml
ai_content:
  status: ai_generated          # ai_generated | ai_assisted | human_only
  human_review: required
  disclosure_required_for_kdp: true
  generated_components:
    - outline
    - prose
    - blurb
  human_components:
    - concept approval
    - narrative ledger approval
    - publish_strategy choice
    - final spot_check
```

`export` / promote cảnh báo nếu thiếu `ai_content.status`.

### 4.4 Pen name & cover (KDP delivery)

| Artefact | Rule |
|----------|------|
| `Docs/pen_names_data.txt` | SSOT bút danh theo thể loại |
| Dark (horror/gothic/thriller) | **Reynard Frost** — Primary |
| Romance / thiếu nhi / erotica | **Tách** tên — không dùng Frost |
| `direction.yaml` + `manifest.yaml` + `series.yaml` | `pen_name` bắt buộc trước export |
| EPUB | `dc:creator` = `resolve_pen_name()` |
| Cover | `catalog/<series>/books/<slug>/cover.png` (hoặc `.jpg`); `export --cover …` |
| Archive | `archive/catalog_*` = backup — **không** upload bản archive |

Checklist KDP: pen name đúng dòng · AI disclosure · title không số thừa · cover thumbnail đọc được · không dùng tên nhân vật làm bút danh.

---

## 5. NARRATIVE OS — Story Intelligence Layer

### 5.1 Vai trò

Trả lời **trước** khi Outliner đẻ 50 chương:

- Câu chuyện này thật ra nói về cái gì? (**surface plot** vs **true plot**)
- Ai biết gì ở chương nào?
- Manh mối plant/payoff ở đâu?
- Cuốn 1 đóng gì? Mở gì cho cuốn 2?
- Thread nào phải trả trong book 1?

**Không có tầng này:** AI viết hay từng chương nhưng **ngu toàn truyện** (clue rơi, twist không cài, knowledge leak).

### 5.2 `narrative_profile` + file bắt buộc

Không phải mọi genre cần cùng schema. `narrative_profile` trong `direction.yaml` quyết định file nào **bắt buộc** trong `bible/narrative/`:

| Profile | Dùng cho | Bắt buộc |
|---------|----------|----------|
| `sweet_romance` | Romance nhẹ | `kernel.json`, `book_arc.json`, emotional arc |
| `romance_thriller` | **glass-meridian**, ceo-contract | `kernel`, `mystery_ledger`, `threads`, `knowledge_matrix`, `book_arc` |
| `conspiracy_thriller` | John/Bangkok… | + `conspiracy.json`, knowledge_matrix đầy đủ |
| `progression_fantasy` | xianxia | `kernel`, `power_system`, `progression_ladder`, `enemy_ladder`, `book_arc` |
| `dark_romance` | mafia/dark | `kernel`, `consent_boundaries`, `danger_ladder`, `relationship_power_map`, `book_arc` |

### 5.3 Cấu trúc workspace (mở rộng)

```
factory/workspaces/<series-id>/
├── direction.yaml              # + narrative_profile, publish_strategy, narrative_status
├── manifest.yaml               # + ai_content block
├── bible/
│   ├── series.json             # nhân vật, bloodline, central_mystery (giữ)
│   ├── locked_chapter_plans.json
│   └── narrative/              # NEW — không phải file nào cũng có
│       ├── publish_strategy.json   # optional nếu đã gộp direction.yaml
│       ├── kernel.json
│       ├── book_arc.json
│       ├── mystery_ledger.json
│       ├── threads.json
│       ├── knowledge_matrix.json
│       ├── conspiracy.json         # chỉ conspiracy_thriller
│       └── power_system.json       # chỉ progression_fantasy
└── books/01/
    ├── master_plan.json        # chapter grid mở rộng (§5.6) — KHÔNG tách file riêng
    └── ...
```

### 5.4 `kernel.json` — hạt nhân (mọi profile)

```json
{
  "narrative_profile": "romance_thriller",
  "surface_case": "Thứ độc giả tưởng đang đọc (vd: hợp đồng hôn nhân đổi tiền).",
  "true_case": "Thứ thật diễn ra bên dưới (vd: lá chắn trong cuộc chiến gia tộc).",
  "core_question": "Câu hỏi plot",
  "emotional_question": "Câu hỏi cảm xúc",
  "book1_promise": "Reader được trả gì cuốn 1",
  "case_closed": "Vụ/case book 1 giải quyết",
  "series_door_opened": "Cửa mở sang book 2",
  "book2_hook": "Hook cụ thể"
}
```

**Rule:** mọi chapter plan phải phục vụ `surface_case` hoặc `hidden_function` hướng tới `true_case`.

### 5.5 Ledger files (thriller / mystery)

**`mystery_ledger.json`:** clues (plant_chapter, payoff_chapter, clue_id), red_herrings, major_reveals + required_clues.

**`threads.json`:** thread id, opened/closed, `open_to_book2`, book1_payoff, book2_promise.

**`knowledge_matrix.json`:** ai biết gì ở milestone (ch1, ch10, ch25, ch36, ch50). Hỗ trợ hai format `must_not_know_before`:
- **dict:** `fact → chapter` (glass-meridian)
- **int + `hidden_truth`:** scalar chapter ngưỡng (ceo-contract)

Runtime `state.json` cập nhật sau QC PASS; sync ngược knowledge_matrix vẫn roadmap.

### 5.6 `master_plan.json` — mở rộng chapter object

Không tạo `chapter_grid.json` riêng. Mở rộng mỗi `chapter_plan`:

```json
{
  "chapter": 17,
  "title": "...",
  "chapter_role": "midpoint clue escalation",
  "surface_event": "Sự kiện bề mặt reader thấy",
  "hidden_function": "Nhiệm vụ trong hệ thống truyện",
  "thread_ids": ["T1", "T5"],
  "clue_events": [
    { "type": "plant", "clue_id": "C006", "payoff_chapter": 28 },
    { "type": "payoff", "clue_id": "C003", "payoff_from_chapter": 3 }
  ],
  "reader_question_opened": "...",
  "reader_question_answered": "...",
  "knowledge_delta": { "Diệp Tâm": ["..."], "reader": ["..."] },
  "emotional_turn": "...",
  "next_click_hook": "...",
  "must_happen": ["[ROMANCE] ...", "..."],
  "opens_with": "...",
  "cliffhanger": "..."
}
```

Fields cũ (must_happen, spice, opens_with…) **giữ**; fields mới **bắt buộc theo profile** (romance_thriller: thread_ids + clue_events khi có ledger).

### 5.7 Cổng duyệt Narrative OS

```yaml
# direction.yaml
narrative_profile: romance_thriller
publish_strategy: kdp_ku_exclusive   # hoặc wide_serial
narrative_status: draft              # draft | approved
bible_status: approved
plan_status: draft
```

**Factory không được `plan` nếu** (UI / workflow gate):
- `narrative_profile` có mà `narrative_status` ≠ approved (romance_thriller)
- `bible_status` ≠ approved
- thiếu file narrative bắt buộc (`validate-narrative`)

**Compiler** (`narrative_compiler_enabled`) bật khi: profile thriller + `narrative_status: approved` + ledger/matrix tồn tại. `workspace_mode: archive` trong direction → tắt compiler.

### 5.8 CLI Narrative OS (**có**)

```powershell
.\factory\run_factory.ps1 develop-narrative --workspace glass-meridian --pass all
.\factory\run_factory.ps1 validate-narrative --workspace glass-meridian
.\factory\run_factory.ps1 approve-narrative --workspace glass-meridian
```

Passes: `kernel` | `mystery` | `threads` | `all`. Schema: `narrative_schema.py`, loader trong `narrative_developer.py`.

### 5.9 Plan narrative QC — **NC-01..NC-07** (`plan_qc.py`)

Đã implement trong `plan_qc.validate_narrative_plan` + compiler `narrative_compiler.py`:

| Rule | Nội dung |
|------|----------|
| NC-01 | Clue plant theo ledger tại ch này |
| NC-02 | Clue payoff scheduled |
| NC-03 | Payoff không trước plant |
| NC-04 | Major reveal có đủ clue plant trước |
| NC-05 | Số clue tối thiểu theo reveal_weight |
| NC-06 | Knowledge gate — fact forbidden chưa được leak trong plan prose |
| NC-07 | Clue plant/payoff phải xuất hiện trong beats |

Gọi từ `validate_plan` khi `narrative_compiler_enabled(ws)`. Locked plans skip NC.

**Roadmap** (`narrative_qc.py` riêng): validate kernel/ledger/threads độc lập, book-ending contract toàn cuốn, thread starvation cross-plan.

### 5.10 Compiler inject — **có**

| Thành phần | File | Vai trò |
|------------|------|---------|
| Compiler | `narrative_compiler.py` | Source of truth từ ledger + matrix → `compile_chapter_narrative` |
| Plan merge | `master_plan.merge_narrative_into_plans` | Ghi `plan.narrative` từ compiler (ghi đè LLM) |
| Outliner payload | `build_outliner_payload` | `narrative_constraints` per act |
| Writer prompt | `prompt_builder` | Block **NARRATIVE CONSTRAINTS** từ compiler — **không** đọc `plan.narrative` |
| Plan normalize | `plan_normalize.py` | Unwrap `{chapter_plan}`, flatten nested `must_happen` |

---

## 6. FACTORY — Write engine (hiện có + tích hợp)

### 6.1 Nguyên tắc

| Nguyên tắc | Ý nghĩa |
|------------|---------|
| **Publish-first** | Biết KU hay wide trước khi plan |
| **Story-before-chapters** | Narrative OS approved trước Outliner |
| **Canon-first** | `series.json` + narrative ledgers |
| **Code = luật, JSON = dữ liệu** | Không hardcode tên cuốn trong engine |
| **Ép kỹ thuật ở PLAN** | Writer chỉ thực thi prompt |
| **Catalog = sự thật publish** | Pipeline = WIP |

### 6.2 Pipeline đầy đủ (**chạy được**)

```
concept.yaml + direction.yaml (publish_strategy, narrative_profile)
→ develop-narrative → validate-narrative → approve-narrative
→ architect → validate-bible → approve-bible
→ plan (Outliner chunk=3, merge narrative, qc_and_fix_plans)
→ normalize-plan (optional repair) → render-prompts
→ approve-plan
→ write (state gate: ch N-1 ready; prior excerpt in payload)
→ machine_qc → LLM qc (qc_eval hard-fail continuity/voice_drift)
→ state_updater (PASS only) → promote → catalog → export
```

**UI batch** (`factory/ui/factory_workflow.py`): chỉ skip `ready`; rewrite `needs_fix`/`needs_review`; dừng khi fail (tuỳ chọn). Mỗi chương kẹt có **reason_summary** (machine QC + LLM QC) — UI tab Chương, batch log, `blocked_chapters` API, `MORNING.md`.

**Batch lock:** `batch_progress.json` + thread in-memory. Lock cũ (`running: true` sau crash/restart) tự xóa khi không còn thread; **Hủy lock batch** (`POST .../batch/reset`) hoặc refresh dashboard.

**Thứ tự khuyến nghị:** `develop-narrative` trước `architect` — bible bám Story Brain.

**Workspace sạch:** `glass-meridian` (`default_workspace` trong `config.json`).

### 6.3 Bible schema (`series.json`)

Giữ schema hiện tại: `leads`, `supporting_cast`, `central_mystery` (answer = 1 string), `bloodline`, `world_rules`, `series_arc`. Validator: `bible_schema.py`.

`central_mystery` trong bible **bổ sung** cho `mystery_ledger` — ledger chi tiết plant/payoff; bible giữ answer + reveal_chapter.

### 6.4 Plan layer

- Outliner chunk **3** chương; `json-repair`; split act nếu thiếu ch; `plan_raw_*.txt` debug
- `[ROMANCE]` micro-beat mọi chương (romance profiles)
- `locked_chapter_plans.json` — plans `locked: true` skip NC / plan_fixer
- `plan_qc.py`: kỹ thuật + canon (`bible_schema`) + **NC-01..07**
- `plan_normalize.py`: unwrap nested `chapter_plan`, `coerce_text_list` cho `must_happen`
- `master_plan.merge_narrative_into_plans`: compiler ghi đè `plan.narrative` (unlocked)

### 6.5 QC layers — ba tầng (không gộp)

**Nguyên tắc:** Lỗi cơ học (regex/script) và lỗi ngữ nghĩa (canon/judgment) **khác tầng, khác thời điểm bắt, khác chi phí fix**. Không dồn vào một “post-book QA”.

| Tầng | Tên | Khi chạy | Công cụ | Fail = chặn? |
|------|-----|----------|---------|--------------|
| **1** | **Export / promote gate** | Trước `promote` (catalog) và trước `export` | `export_gate.py` — deterministic | **Có** — không ghi EPUB/DOCX/serial |
| **2** | **Canon consistency guard** | `approve-plan` + write prompt + promote | `canon_registry.yaml`, bible cast, LOCKED CANON | **Có** — invented `Dr. X` / romance khi absent-ML |
| **3** | **Narrative health report** | Sau khi đủ chương / trước publish tay | LLM + compiler metrics | **Không** — báo cáo cho mắt người |

**Per-chapter pipeline (hiện có)** — nằm *trước* tầng 1, không thay thế tầng 1:

| Lớp | File | Nội dung |
|-----|------|----------|
| Plan tech | `plan_qc.py` | opens_with, spice, romance beat, legacy VN on EN |
| Plan narrative | `plan_qc.py` NC-* | Clue/knowledge khi compiler ON |
| Narrative assets | `narrative_schema.py` | validate-narrative (kernel, ledger, threads) |
| Machine | `machine_qc.py` | **Buckets:** `format_fix` (* / quotes) → needs_fix no rewrite; `length` → expand+rewrite; `content_fail` (POV/name) → capped retry → needs_review |
| Canon | `canon_registry.py` + `prompt_builder` LOCKED CANON | approve-plan cast allowlist; absent-ML; supporting phone-only constraints |
| Canon guard | `canon_guard.py` | Forbidden lead aliases lúc promote |
| LLM + hard-fail | `qc_eval.py` + `roles/qc.txt` | continuity / voice_drift → needs_review |
| Block reasons | `chapter_reasons.py` | UI/MORNING |
| Write guards | `write_guards.py` | parallel mặc định; sequential = prior ready |
| Approve | `factory_workflow.chapter_approve` | **Promote trước**; không treo `state_updater` |
| EPUB | `catalog.export_epub` | `dc:creator` = pen_name; `--cover` |
| EPUB structure | `epub_qc.py` | EPUBCheck |

> **EPUBCheck ≠ export gate.** EPUBCheck PASS không có nghĩa reader không thấy bản nháp (`# Chapter` lặp, marker leak, chương cụt). Tầng 1 bắt lỗi *đọc được*; EPUBCheck bắt lỗi *file hợp lệ*.

Chi tiết tầng 1: **§6.10** (EG-01..**EG-12**). Tầng 2: **§6.11** (canon registry **đã có**; narrative health report vẫn roadmap).

### 6.6 Model routing (OmniRoute)

`config.json`:

| Key | Giá trị mặc định (2026-07) |
|-----|------------------------------|
| `base_url` | `http://localhost:20128/v1` |
| `model_routing` | `flexible` |
| `phase1_plan` | `auto`, `auto/best-fast`, `auto/fast` |
| `phase2_write` | **`auto/fast`**, `auto`, `auto/best-fast` |
| `phase_light` | `auto/fast`, `auto` |
| `model_preferences` | `[]` — dự phòng cuối |

**Tránh trong chain mặc định:**
- `moi` — Omni trả 400 *Unable to determine provider*
- `gh/gpt-4o` — cần GitHub credential active trong Omni dashboard; nếu thiếu → 404 *No active credentials for provider: github*

`model_routing: fixed` + `model_priority_groups` = list model cứng.  
Wrapper: `call_9router.py` — walk chain on 402/403/404/429. Lỗi `All models failed` báo **exception model cuối** — dùng `probe-models` để kiểm từng bước. Log token: `factory_log.json`.

### 6.7 Export & publish

**Thứ tự bắt buộc khi export EPUB:**

```
load catalog chapters
  → export_gate (§6.10)     FAIL = dừng, không ghi file
  → build EPUB/DOCX/serial
  → validate_epub_structure (nếu epub)
  → epub_qc / EPUBCheck     WARN hoặc FAIL tuỳ config
```

| Target | Output | Dùng cho |
|--------|--------|----------|
| **epub** | `exports/epub/<slug>.epub` + `<slug>.qc.json` | **KDP primary** |
| **docx** | `exports/docx/<slug>.docx` | Word / KDP auto-ToC |
| **serial** (`vella` legacy) | `exports/vella/*.txt` | Webnovel, GoodNovel, RoyalRoad — **không phải Kindle Vella** |

Gate report: `exports/<target>/.export_gate.json` (hoặc cạnh slug epub).

```powershell
.\factory\run_factory.ps1 export --target epub --cover catalog/the-paper-oracle/books/01-the-paper-oracle/cover.png
.\factory\run_factory.ps1 export --target docx
.\factory\run_factory.ps1 export --target vella   # legacy alias → serial txt
.\factory\run_factory.ps1 qc-export-gate --workspace the-paper-oracle
.\factory\run_factory.ps1 qc-epub --workspace the-paper-oracle
```

Config: `epubcheck_jar`, `epub_qc_fail_on_warnings`, `min_publish_words: 1250`, `writer_auto_max_retries: 10`.

### 6.8 Factory CLI

| Lệnh | Trạng thái |
|------|------------|
| `setup`, `init-workspace`, `concept` | **Có** |
| `develop-narrative`, `validate-narrative`, `approve-narrative` | **Có** |
| `architect`, `validate-bible`, `approve-bible` | **Có** |
| `plan`, `fix-plans`, `normalize-plan`, `render-prompts`, `approve-plan` | **Có** |
| `write`, `status`, `promote`, `export`, `reset`, `migrate` | **Có** |
| `qc-epub`, `qc-export-gate`, `probe-models`, `list-models` | **Có** |
| UI `factory/ui/server.py` | **Có** — batch prep + write, chapter reasons, batch lock reset |

### 6.9 Test zones

`factory/engine/tests/run_zones.py` — **64 tests**, không LLM:

| Zone | Nội dung |
|------|----------|
| bible | relation_type schema |
| compiler | narrative_compiler deterministic |
| prompt | NARRATIVE CONSTRAINTS inject |
| plan | merge narrative into plans |
| plan_qc | NC-01..07 |
| guards | normalize, write_guards, qc_eval, model routing |
| export_gate | EG-01..**12** deterministic |
| canon | `is_absent_male_lead`, cast allowlist, invented doctor |
| machine_qc | format vs length vs content classify |
| epub_qc | EPUBCheck parse + integration |
| integration | compiler → plan → prompt E2E |

```powershell
.\factory\run_checks.ps1
.\factory\run_checks.ps1 -Zone compiler
```

---

### 6.10 Export gate (Tầng 1) — **spec implement**

> **Trạng thái:** **implemented** 2026-07 (`export_gate.py`, hooks, `qc-export-gate` CLI). Catalog glass-meridian chưa sạch — gate FAIL cho tới re-promote/fix.

#### 6.10.1 Mục đích

Chặn **lỗi cơ học** mà reader thấy ngay trên bản đọc — không cần LLM, chạy ~2 giây toàn cuốn. Đây là **cửa kiểm cuối deterministic** trước khi file rời catalog.

**Không hook vào `write`.** Chỉ `promote_chapter()` + `export_book()` — viết dở (ch1–15) vẫn chạy bình thường; EG-04 gap chỉ fail khi export cuốn chưa đủ chương.

**Không thay thế:** per-chapter `machine_qc` (word count, foreign) hay LLM QC — những cái đó bắt sớm hơn ở pipeline.

**Không bao gồm:** tên riêng mâu thuẫn canon, POV judgment, scene recycle, tease/payoff ratio → **§6.11**.

#### 6.10.2 Khi nào chạy

| Hook | Hành vi nếu FAIL |
|------|------------------|
| `promote_chapter()` | Không ghi `catalog/chapters/*.md` (hoặc ghi nhưng `export_gate: fail` trong meta — **khuyến nghị: không promote**) |
| `export_book()` | **Raise / exit 1** — không tạo EPUB/DOCX/serial |
| CLI `qc-export-gate` | Chỉ quét + in report — không export |
| UI tab Xuất sách | Nút «Export gate» — hiện checklist trước khi export |

**Input:** toàn bộ `catalog/<series>/books/<slug>/chapters/*.md` + `book.yaml` + `direction.yaml` (`target_language`, `chapter_count`).

**Output:** JSON report (schema bên dưới) + human summary cho CLI/UI.

#### 6.10.3 Module

```
factory/engine/lib/export_gate.py
factory/engine/tests/test_export_gate.py
```

Public API đề xuất:

```python
def run_export_gate(
    workspace_id: str,
    book_slug: str,
    *,
    cfg: dict | None = None,
) -> dict: ...

def export_gate_pass(report: dict) -> bool: ...

def format_export_gate_summary(report: dict) -> str: ...

def format_export_gate_reasons(report: dict) -> list[str]: ...
```

Hook trong `catalog.py`:

- `promote_chapter()` — subset **EG-01, EG-02, EG-03, EG-06, EG-08, EG-10, EG-11, EG-12**
- `export_book()` — **full book** EG-01..**12**
- **`write` — không hook**

#### 6.10.4 Rules (EG-01 .. EG-12)

Mỗi rule trả `CheckResult`: `{id, severity, passed, chapter?, detail, snippet?}`.

| ID | Severity | Mô tả | Thuật toán |
|----|----------|-------|------------|
| **EG-01** | error | Chương cụt giữa câu | Ký tự cuối body ∈ `. ! ? … ) ] » — –` / đóng dialogue. **FAIL:** `,`, ASCII `-`, chữ cái trailing |
| **EG-02** | error | Marker / template leak | `T001`, `**Cliffhanger:**`, `must_happen:`, … |
| **EG-03** | error | Header bẩn / lặp | `# Chapter` trong body; subtitle trùng; title VN trên EN |
| **EG-04** | error | Thiếu số chương | Expect `1..N` liên tục (`book.yaml` total_chapters) |
| **EG-05** | warn→error* | Trùng title | `export_gate_dup_title` |
| **EG-06** | error | Markdown trong prose | `*italic*`, `**bold**`, backtick |
| **EG-07** | warn | Near-dup chương | hash 500 từ đầu |
| **EG-08** | error | Body quá ngắn publish | `< min_publish_words` (**1250**) |
| **EG-09** | error | Generic catalog title vs plan title | bare `Chapter N` khi plan có tên |
| **EG-10** | error | CJK trên bản EN | fullwidth/CJK trong body |
| **EG-11** | error | Generic title (per-chapter promote) | tương tự EG-09, hook promote |
| **EG-12** | error/warn | Frontmatter `needs_fix` còn flags | kể cả khi body đã sạch — phải clear meta |

**Pass book:** mọi `severity=error` đều `passed=true`. `warn` không chặn trừ `export_gate_strict`.

#### 6.10.5 Report schema

File: `catalog/<series>/books/<slug>/exports/.export_gate.json`

```json
{
  "ok": true,
  "passed": false,
  "workspace_id": "glass-meridian",
  "book_slug": "01-the-glass-meridian",
  "checked_at": "2026-07-09T05:30:00Z",
  "chapter_count": 49,
  "expected_chapters": 50,
  "target_language": "en",
  "checks": [
    {
      "id": "EG-03",
      "severity": "error",
      "passed": false,
      "chapter": 40,
      "detail": "subtitle trùng body; title VN trên bản EN",
      "snippet": "# Chapter 40: The Meridian's Calculated Strike"
    },
    {
      "id": "EG-04",
      "severity": "error",
      "passed": false,
      "chapter": null,
      "detail": "missing chapters: [47]"
    }
  ],
  "summary": "FAIL — 2 errors, 1 warning (EG-06 ch40)"
}
```

#### 6.10.6 Sửa export renderer (đi kèm implement)

`catalog.py` `_chapter_xhtml()` / `export_docx` phải:

1. **Strip** dòng đầu body nếu match `^#\s*(Chapter|Chương)\s+\d+`.
2. **Subtitle:** bỏ prefix `# `; không render nếu trùng title hoặc trùng dòng đầu body sau strip.
3. **Title EN:** dùng phần sau `Chapter N:` làm `h1` khi `target_language=en` (hoặc `subtitle` sạch), không dùng `Chương N`.

Đây là **fix renderer**, không phải chỉ FAIL — nhưng EG-03 vẫn FAIL nếu catalog md chưa sạch (để biết cần re-promote).

#### 6.10.7 Config (`config.json`)

| Key | Default | Ý nghĩa |
|-----|---------|---------|
| `export_gate_enabled` | `true` | Tắt toàn bộ gate (chỉ debug) |
| `export_gate_strict` | `false` | WARN cũng chặn export |
| `export_gate_dup_title` | `warn` | `warn` \| `error` |
| `export_gate_near_dup` | `warn` | EG-07 |
| `min_publish_words` | `1250` | EG-08 |
| `export_gate_on_promote` | `true` | Subset per-chapter khi promote |
| `writer_auto_max_retries` | `10` | Auto write: content + length |

#### 6.10.8 CLI & UI

```powershell
.\factory\run_factory.ps1 qc-export-gate --workspace glass-meridian
.\factory\run_factory.ps1 qc-export-gate --workspace glass-meridian --strict
```

UI (roadmap):

- `POST /api/export/<ws>/export-gate` — JSON report
- Tab Xuất sách: nút «Export gate» + checklist EG-xx đỏ/xanh
- Export EPUB: nếu gate FAIL → message giống `chapter_reasons`, không tải file

#### 6.10.9 Test vectors (bắt buộc trong `test_export_gate.py`)

| Case | Input | Expect |
|------|-------|--------|
| cụt câu | body kết `"She turned and` | EG-01 fail |
| cliffhanger leak | `**Cliffhanger:**` trong body | EG-02 fail |
| header lặp | subtitle = `# Chapter 5: X`, body cùng dòng | EG-03 fail |
| gap | ch 1,2,4 trong catalog | EG-04 fail, missing [3] |
| glass-meridian live | catalog hiện tại | EG-03 fail nhiều ch; EG-04 missing 47 |
| sạch | chương fixture minimal | all pass |

#### 6.10.10 Ví dụ thực tế (glass-meridian, 2026-07)

Đọc EPUB ch40 — reader thấy:

- `h1`: Chương 40
- subtitle + paragraph: `# Chapter 40: The Meridian's Calculated Strike` (lặp 2 lần)

→ **EG-03** (header bẩn + lặp), **EG-06** (`*click-click-click*` markdown thô).  
→ EPUBCheck **PASS** — chứng minh tầng EPUB structure ≠ tầng 1.

---

### 6.11 Canon guard & narrative health — **canon DONE; health roadmap**

#### 6.11.1 Tầng 2 — Canon (**implemented**)

| Cơ chế | File | Hành vi |
|--------|------|---------|
| `canon_registry.yaml` | workspace root | Operator SSOT lead names, spice_max, pov |
| `is_absent_male_lead` | `canon_registry.py` | Nhận `Unassigned (no male lead)` / M.I.A. |
| Cast allowlist | `collect_allowed_cast_names` | Invented `Dr. X` trong plan / narrative / `state.json` → conflict |
| `approve-plan` | `validate_plan_against_canon_registry` | Chặn plan có bác sĩ bịa / spice vượt |
| LOCKED CANON | `prompt_builder.render_locked_canon_block` | Inject mọi writer prompt; supporting phone-only |
| `plan_fixer` / `outliner` | roles | Absent-ML → isolation, không invent romance doctor |
| `state_updater` | strip invented doctors | Không poison story_state |
| `canon_guard` | promote | Forbidden lead aliases |

**Nguyên tắc:** invented characters chết ở **plan/state**, không phát hiện ở chương 3 sau retry writer.

#### 6.11.2 Tầng 3 — Narrative health report (roadmap)

Báo cáo cho editor — **không** block export mặc định.

| Metric | Cách đo | Ghi chú |
|--------|---------|---------|
| Scene diversity | `scene_type` histogram | Cảnh báo khi lặp |
| Tease vs payoff | ledger clue mở không payoff | NC bổ sung |
| POV drift | Regex `I/my` + LLM | machine_qc đã một phần |
| Book promise | kernel vs ending | LLM summary |

**Output (roadmap):** `exports/narrative_health.json` + `qc-narrative-health` CLI.

---

## 7. Workspaces

### 7.1 `the-paper-oracle` / `the-salt-room-1` (**KDP dark — Reynard Frost**)

| Field | Giá trị |
|-------|--------|
| `target_language` | `en` |
| `pen_name` | **Reynard Frost** |
| Thể loại | Gothic / psychological dread, spice 1 |
| Male lead | `Unassigned (no male lead)` |
| Cast | Concept/bible only (Ovid = phone-only) |
| Delivery | `cover.png` + EPUB `dc:creator` |

### 7.2 `glass-meridian` (`default_workspace` — thriller-romance)

| Field | Giá trị |
|-------|--------|
| `target_language` | `en` |
| `narrative_profile` | `romance_thriller` |
| `publish_strategy` | `kdp_ku_exclusive` |
| Leads | Lin Wei × Adrian Vale |
| Pen name | **Tách** khỏi Reynard Frost khi publish romance |

### 7.3 `ceo-contract` (legacy)

EN plan 50 ch — tham chiếu / archive. Khuyến nghị không dùng làm clean KDP run.

---

## 8. KDP content & spice

| Spice | Plan | Writer |
|-------|------|--------|
| 0–1 | sweet / tension | không explicit; vẫn `[ROMANCE]` micro-beat |
| 2 | steamy | hôn, gần chạm |
| 3 | explicit 18+ | ~40% chương; spot-check + AI disclosure |

---

## 9. Implementation roadmap

### Phase 0 — spec & docs

- [x] Vella → serial export semantics
- [x] Publish Strategy Gate (direction.yaml)
- [x] Narrative OS + profile table
- [x] AI disclosure metadata
- [x] README + spec sync (2026-07-12)
- [x] Pen names SSOT (`Docs/pen_names_data.txt`) + EPUB `dc:creator`
- [x] Canon registry + cast allowlist + absent-ML
- [x] machine_qc format/length/content + auto retries (10)
- [x] Export gate EG-01..**12** + promote subset
- [x] Approve không treo state_updater
- [x] Dark KDP: Paper Oracle + Salt Room (+ cover)

### Phase 1 — Narrative data

- [x] `bible/narrative/*.json` ceo-contract
- [x] `glass-meridian` concept + narrative draft
- [ ] `glass-meridian`: approve narrative → full plan → write ch1 clean

### Phase 2 — Narrative OS code (**done**)

- [x] `narrative_schema.py`, `narrative_developer.py`, `narrative_compiler.py`
- [x] CLI: develop / validate / approve-narrative
- [x] Gate plan khi narrative chưa approved (UI + workflow)

### Phase 3 — Outliner + prompt inject (**done**)

- [x] `merge_narrative_into_plans`, `build_outliner_payload` constraints
- [x] `prompt_builder` NARRATIVE CONSTRAINTS từ compiler

### Phase 4 — Plan QC + pipeline guards (**done**)

- [x] NC-01..07 trong `plan_qc.py`
- [x] `plan_normalize.py`, `write_guards.py`, `qc_eval.py`
- [x] Batch: no skip on failed buckets; state catch-up
- [x] Chapter block reasons (`chapter_reasons.py`, UI + MORNING)
- [x] Batch stale-lock recovery + `batch/reset` API
- [x] Model chain: chỉ `auto/fast`, `auto`, `auto/best-fast` (bỏ `moi`, `gh/*`)
- [x] Zone tests
- [x] EPUBCheck integration (`epub_qc.py`, `qc-epub`, `.qc.json`)
- [x] **Export gate** EG-01..**12** — §6.10
- [x] Export renderer: strip `# Chapter`, title EN
- [x] Canon registry / LOCKED CANON / cast allowlist — §6.11.1
- [x] machine_qc buckets + writer_auto_max_retries
- [x] Pen name + cover → EPUB
- [x] Export gate UI (`Export gate` trên dashboard)
- [ ] Narrative health report — §6.11.2

### Phase 5 — Runtime sync (roadmap)

- [ ] `state_updater` ↔ knowledge_matrix / thread progress
- [ ] Machine check `carries_to_next` ↔ cliff
- [ ] `export --target serial` alias chính thức (giữ `vella` legacy)
- [ ] `narrative_qc.py` standalone (kernel/ledger/book-ending toàn cuốn)
- [ ] Recon: đủ 15 sub-niche × platforms

---

## 10. Rủi ro & giới hạn

| Rủi ro | Mitigation |
|--------|------------|
| Plan không có Story Brain | Compiler + NC-01..07 |
| Nested plan JSON / must_happen list | `plan_normalize.coerce_text_list` |
| Stale state / write out of order | `write_guards` state gate + prior excerpt |
| LLM QC pass despite continuity bug | `qc_eval` hard-fail |
| KU + Webnovel cùng lúc | publish_strategy gate |
| Vella target chết | serial export; KDP EPUB primary |
| AI disclosure thiếu | `ai_content` metadata bắt buộc |
| Clue/thread orphan | mystery_ledger + NC rules |
| Outliner JSON truncate | chunk=3, json-repair, act split |
| OmniRoute log noise | HTTP 200 = OK; tune routing on dashboard |
| Omni `All models failed` / GitHub 401/404 | `probe-models`; reconnect provider trong Omni; không thêm `gh/*` vào chain trừ khi credential OK |
| Batch lock treo sau crash | Auto-clear khi refresh; `POST /api/pipeline/<ws>/batch/reset` |
| User không biết vì sao chương kẹt | `reason_summary` + `issues.json` / `_qc.json` + UI reason box |
| Reader thấy bản nháp (header lặp, marker leak) | **Export gate** §6.10 — trước EPUBCheck |
| EPUBCheck PASS nhưng nội dung xấu | Tách tầng: `epub_qc` = structure; `export_gate` = readable prose |
| Tên/fact mâu thuẫn muộn | Canon registry + LOCKED CANON + cast allowlist §6.11.1 |
| Plan invent romance doctor (absent-ML) | `is_absent_male_lead` + plan_fixer isolation + invent QC |
| Approve treo OmniRoute | Promote trước; không LLM `state_updater` trước catalog |
| EPUB không có author/cover | `pen_name` + `cover.png` trước export |

---

## 11. Tài liệu liên quan

| File | Vai trò |
|------|---------|
| **spec_kdp_subniche_recon.md** (file này) | Kiến trúc, publish strategy, narrative OS, quy tắc |
| **README.md** | Cheat sheet vận hành |
| `factory/workspaces/<id>/direction.yaml` | publish_strategy, narrative_profile, spice, arc |
| `factory/workspaces/<id>/bible/narrative/` | Story Brain per series |
| `factory/workspaces/<id>/bible/series.json` | Character canon |
| `factory/engine/lib/export_gate.py` | Export gate EG-01..**12** |
| `factory/engine/lib/canon_registry.py` | Cast allowlist, absent-ML, approve-plan |
| `factory/engine/lib/epub_qc.py` | W3C EPUBCheck wrapper |
| `Docs/pen_names_data.txt` | Bút danh theo thể loại (Reynard Frost = dark) |
| `start omni.bat` | Khởi động OmniRoute gateway |
| `factory/run_checks.ps1` | Zone tests (64+) |
| `recon/output/subniche_decision_matrix.md` | Kết quả recon |

---

## 12. Tóm tắt một dòng

**Recon** → **Publish strategy** → **Narrative OS** → **Canon registry** → **Factory** (format≠length≠content) → **Catalog + EG-01..12 + pen_name/cover** → KDP (Reynard Frost = dark).

**Done:** compiler, NC rules, canon cast allowlist, auto/supervised write, export gate 12 rules, EPUB author+cover.  
**Next:** narrative health report; AI `ai_content` metadata enforce.
