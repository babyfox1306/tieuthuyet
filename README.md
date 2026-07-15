# KDP Sub-niche Recon + Story Factory

Repo gồm **hai hệ thống độc lập** dùng chung môi trường Python:

| Vùng | Mục đích | Entry point |
|------|----------|-------------|
| **`recon/`** | Quét thị trường đa nền tảng (KDP, Vella, Webnovel, GoodNovel, Royal Road) → DB + CSV quyết định sub-niche | `.\run.ps1` |
| **`factory/`** | Sản xuất truyện theo chương (narrative → bible → plan → write → QC → catalog) | `.\factory\run_factory.ps1` hoặc **UI** `factory/ui/server.py` |
| **`catalog/`** | Bản giao hàng sạch — chỉ chương đã promote, export KDP/serial | đọc / upload tay |

Triết lý: **recon tìm ngách** → **Narrative OS hiểu truyện** → **Canon registry khóa tên/cast** → **factory viết trong khung** → **catalog + export gate** → KDP.

**Dòng dark đang chạy (KDP):** bút danh **Reynard Frost** — `Docs/pen_names_data.txt`. Workspaces: `the-paper-oracle`, `the-salt-room-1`, `the-black-arteries`, `ink-and-venom` (gothic/horror). Romance CEO vẫn `glass-meridian` / `ceo-contract` (tách pen name khi publish).

---

## Bản vá gần đây (patch log)

> Ghi các sửa engine / vận hành như **bản vá**, kèm ngày giờ (UTC+7) và lý do. Chi tiết kiến trúc: `spec_kdp_subniche_recon.md`.

### 2026-07-14 ~20:20–20:40 — Canon registry + outliner tên lead

| | |
|--|--|
| **Files** | `factory/engine/lib/canon_registry.py`, `master_plan.py`, `roles/outliner.txt`, `tests/test_scaffold_canon_registry.py` |
| **Lý do** | `Male lead: Dr. Alistair Finch (29)` bị scaffold thành `Dr. Alistair` (regex max 2 token + `Dr.` thành alias). Outliner chỉ đọc bible → re-plan lệch registry → `approve-plan` báo `male_lead_cross_source_mismatch` / `forbidden_lead_name_in_plan`. |
| **Vá** | Parser bắt honorific + 1–4 token, dừng trước `(age)`; alias không còn `Dr.`; inject `locked_canon_names` vào outliner; `sync_bible_leads_from_registry` trước plan/replan. |
| **Operator** | Workspace đã lệch: sửa `canon_registry.yaml` hoặc `init-canon-registry --force`, rồi duyệt plan lại. |

### 2026-07-14 ~20:30 — ink-and-venom registry + ch9 plan

| | |
|--|--|
| **Files** | `factory/workspaces/ink-and-venom/canon_registry.yaml`, `books/01/master_plan.json` (ch9) |
| **Lý do** | Registry cũ cắt tên; ch9 `must_happen` chỉ còn `["["]` (JSON outliner/fixer bị truncate nhưng parse/`json_repair` vẫn lưu) → `plan_qc_fail` `must_happen_lt3` / `missing:must_not`. |
| **Vá** | Canonical `Dr. Alistair Finch` + alias Finch/Alistair; viết lại `must_happen`/`must_not`/carries ch9 từ beat còn lại. |
| **Ghi chú** | `plan_raw_007_009.txt` thường còn bản đủ — so raw trước khi re-plan đè master. |

### 2026-07-14 (trước đó trong phiên) — Dialogue quotes / isolation

| | |
|--|--|
| **Files** | `factory/engine/lib/machine_qc.py`, `tests/test_machine_qc_classify.py` (+ wire `chapter`/`plan` từ `run_factory` / `catalog`) |
| **Lý do** | Heuristic đếm dấu ngoặc kép → FAIL chương isolation (1 dòng thoại opener, còn lại nội tâm/catalogue). |
| **Vá** | Không FAIL vì sparse quotes; chỉ bắt dialogue-tag ngoài ngoặc; plan/direction có `[ISOLATION]` / isolation → tắt cảnh báo quotes. |

---

## Cài đặt

```powershell
cd "d:\duan\KDP Sub-niche Recon"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

**Factory cần LLM gateway** (OpenAI-compatible) chạy local — **OmniRoute** (khuyến nghị) hoặc 9router:

- URL mặc định: `http://localhost:20128/v1` (`factory/engine/config.json`)
- Khởi động OmniRoute: double-click **`start omni.bat`** (repo root) hoặc `npm run dev` trong `D:\OmniRoute\OmniRoute`
- **Tắt 9router** trước nếu cùng port 20128
- Routing: `model_routing: flexible` — gửi `auto` / `auto/fast`, OmniRoute tự chọn provider theo quota
- Kiểm tra: `.\factory\run_factory.ps1 probe-models`
- Test máy (không LLM): `.\factory\run_checks.ps1` → **64 tests**

Luôn activate `.venv` trước khi chạy Python.

### UI local (khuyến nghị)

```powershell
.\.venv\Scripts\python.exe factory\ui\server.py
# Mở http://localhost:8765 — concept, chuẩn bị sách, viết batch, export
```

**Dashboard — viết hàng loạt:**
- Tab **Pipeline**: Chuẩn bị sách → Viết hàng loạt / Tiếp tục / Chạy hết
- **Chế độ viết:** `supervised` (để lỗi cho operator) | `auto` (content/length retry tới `writer_auto_max_retries`, mặc định **10**; **format-only** `*` / quotes → `needs_fix`, không rewrite cả chương)
- Tab **Chương**: đọc prose, hộp lý do `needs_fix` / `needs_review`, **Duyệt → catalog** (promote trước, không treo LLM `state_updater`)
- **Hủy lock batch** (`🔓`): khi batch treo sau crash/restart server
- Batch log phân biệt: `FORMAT_FIX` · `SHORT/LENGTH` · `CONTENT_CAP`

---

## Cấu trúc thư mục

```
KDP Sub-niche Recon/
├── recon/                    # Market scanner
│   ├── main.py               # CLI: init | search | detail | ...
│   ├── scrapers/             # Từng nền tảng
│   ├── pipeline/             # Tropes, decision matrix
│   └── core/                 # DB, browser, cache HTML
│
├── factory/
│   ├── run_factory.ps1       # Wrapper PowerShell
│   ├── run_checks.ps1        # Zone tests (64 tests, no LLM)
│   ├── ui/                   # Dashboard local (server.py)
│   ├── engine/
│   │   ├── run_factory.py    # CLI chính
│   │   ├── config.json       # OmniRoute URL, model_routing, word count
│   │   ├── roles/            # System prompt từng vai AI
│   │   ├── tests/run_zones.py
│   │   └── lib/
│   │       ├── narrative_compiler.py   # Story Brain → constraints/chương
│   │       ├── canon_registry.py       # SSOT tên lead + cast allowlist + approve-plan
│   │       ├── canon_guard.py          # Forbidden lead aliases lúc promote
│   │       ├── plan_qc.py              # Plan QC + NC-01..NC-07 + absent-ML romance
│   │       ├── machine_qc.py           # format_fix / content_fail / length buckets
│   │       ├── export_gate.py          # EG-01..EG-13 trước promote/export
│   │       ├── plan_normalize.py       # Unwrap plan, flatten must_happen
│   │       ├── write_guards.py         # State gate, prior excerpt
│   │       ├── qc_eval.py              # QC hard-fail continuity/voice
│   │       ├── chapter_reasons.py      # Lý do needs_fix / needs_review (UI + batch log)
│   │       ├── master_plan.py, prompt_builder.py (LOCKED CANON), call_9router.py, …
│   └── workspaces/
│       ├── the-paper-oracle/   # EN gothic — Reynard Frost (KDP ready)
│       ├── the-salt-room-1/    # EN gothic — Reynard Frost
│       ├── glass-meridian/     # EN thriller-romance (default_workspace)
│       └── ceo-contract/       # EN thriller — legacy pipeline
│
├── catalog/<series>/           # Delivery — chapters + cover.png + exports/epub/
├── Docs/pen_names_data.txt     # Bút danh theo thể loại (Reynard Frost = dark)
├── archive/                    # Backup catalog khi export/promote
├── start omni.bat
├── run.ps1
└── requirements.txt
```

> Cấu trúc chi tiết cũ (ceo-contract nested tree) vẫn đúng về mặt ý tưởng; ưu tiên workspace dark/KDP ở trên.

---

## Story Factory — quy trình đầy đủ

### Pha 0: Narrative OS (trước plan)

```
concept.yaml + direction.yaml (narrative_profile, publish_strategy)
       │
       ▼
  develop-narrative → validate-narrative → approve-narrative
       │
       ▼
  bible/narrative/*.json  (kernel, mystery_ledger, threads, knowledge_matrix)
```

Compiler (`narrative_compiler.py`) bật khi: `romance_thriller` / `conspiracy_thriller` + `narrative_status: approved` + đủ ledger/matrix.

### Pha 1: Bible + Plan + Prompt

```
architect → validate-bible → approve-bible
       │
       ▼
  plan (Outliner, chunk 3 ch) ──► master_plan.json
       │     merge narrative constraints (compiler)
       ▼
  fix-plans (plan_qc + NC-01..07 + plan_fixer)
       │
       ▼
  normalize-plan (unwrap nested chapter_plan, flatten must_happen)
       │
       ▼
  render-prompts ──► prompts/ch_NNN.txt
       │
       ▼
  approve-plan   ← validate_plan_against_canon_registry (cast allowlist, spice, lead names)
```

`canon_registry.yaml` (operator SSOT) + `LOCKED CANON` trong mọi writer prompt: lead names, absent-ML, supporting cast phone-only (vd. Dr. Ovid), content boundaries từ concept.

### Pha 2: Viết từng chương

```
prompts/ch_NNN.txt + state.json (+ excerpt khi sequential)
       │
       ▼
  write (Writer)
       │
       ├── machine_qc classify:
       │     length   → expand rồi full rewrite (auto: tới writer_auto_max_retries)
       │     format   → needs_fix, KHÔNG rewrite (* / quotes) — sửa tay
       │     content  → retry capped → needs_review
       ├── LLM qc → needs_review
       └── PASS → ready/ → Duyệt/promote → catalog/ (+ cover.png khi export)
```

Batch UI: `supervised` vs `auto`. Auto **không** infinite-rewrite `needs_fix` format-only.

### Plan vs Prompt — ép kỹ thuật ở đâu?

| Tầng | Ai sinh | File | Ghi chú |
|------|---------|------|---------|
| **Plan** | Outliner (`roles/outliner.txt`) | `master_plan.json` | **Ép kỹ thuật** — `plan_qc.py`, NC-01..07, `locked_chapter_plans.json` |
| **Prompt** | `prompt_builder.py` + **compiler inject** | `prompts/ch_NNN.txt` | NARRATIVE CONSTRAINTS từ compiler, **không** từ `plan.narrative` |
| **Chương** | Writer | `pipeline/*/` | Đọc prompt + prior excerpt; QC hard-fail continuity |

**Không sửa tay `prompts/ch_NNN.txt`** nếu sẽ chạy lại `render-prompts` — sửa `master_plan.json` hoặc narrative ledger.

Format prompt mẫu (tham chiếu tay): `archive/scripts/prompt_chapter3_ceo_explicit.txt`

---

## Vai AI (roles) & routing

**Không gán cứng model** — `config.json` dùng **OmniRoute auto-routing**:

| Key | Giá trị | Ý nghĩa |
|-----|---------|---------|
| `model_routing` | `flexible` | Gửi `auto` / `auto/fast` cho OmniRoute; provider tự chọn theo quota/sức khỏe |
| `phase1_plan` | `auto`, `auto/best-fast`, `auto/fast` | architect, outliner, narrative_developer |
| `phase2_write` | **`auto/fast`**, `auto`, `auto/best-fast` | writer — ưu tiên nhanh |
| `phase_light` | `auto/fast`, `auto` | qc, state_updater, plan_fixer |
| `model_preferences` | `[]` | Dự phòng cuối (chỉ khi mọi auto variant fail) |

**Không dùng** `moi` (Omni không route được) hay `gh/gpt-4o` (cần GitHub credential trong Omni dashboard) trừ khi đã cấu hình xong provider.

Muốn list cứng: đặt `model_routing: fixed` và điền `model_priority_groups` (vd. `openrouter/...`). Chỉ thêm `gh/gpt-4o` làm fallback cuối sau khi reconnect GitHub trong Omni.

Gặp 402/403/404/429 → tụt xuống model kế trong chain. Lỗi `All models failed` hiện **lỗi model cuối** — chạy `probe-models` để xem model nào fail thật. Log: `factory/engine/factory_log.json`.

```powershell
.\factory\run_factory.ps1 probe-models
.\factory\run_factory.ps1 probe-models --role writer
```

| Role | File | Chain group |
|------|------|-------------|
| narrative_developer | `roles/narrative_developer.txt` | phase1_plan |
| architect | `roles/architect.txt` | phase1_plan |
| outliner | `roles/outliner.txt` | phase1_plan |
| writer | `roles/writer.txt` | phase2_write |
| qc | `roles/qc.txt` | phase_light |
| plan_fixer | `roles/plan_fixer.txt` | phase_light |
| state_updater | `roles/state_updater.txt` | phase_light |

Outliner plan theo **chunk 3 chương**. Sau `plan` tự chạy `qc_and_fix_plans` + render prompts.

---

## Factory CLI — toàn bộ lệnh

Chạy qua:

```powershell
.\factory\run_factory.ps1 <lệnh> [--workspace ceo-contract] [options]
```

| Lệnh | Mô tả |
|------|--------|
| `setup` / `init-workspace` | Tạo workspace từ template |
| `concept` | Kiểm tra / chỉnh concept.yaml |
| **`develop-narrative`** | LLM sinh/bổ sung `bible/narrative/` (`--pass kernel\|mystery\|threads\|all`) |
| **`validate-narrative`** | Schema + clue/thread rules |
| **`approve-narrative`** | `narrative_status: approved` — bật compiler |
| `architect` | Sinh `bible/series.json` |
| `validate-bible` / `approve-bible` | Gate bible |
| **`plan`** | Outliner → `master_plan.json` + merge narrative + render prompts |
| **`fix-plans`** | plan_qc + plan_fixer. `--no-llm` = không API |
| **`normalize-plan`** | Unwrap `chapter_plan` lồng, flatten `must_happen` |
| `render-prompts` | Render lại `prompts/` từ plan |
| **`approve-plan`** | Bắt buộc trước `write` |
| **`write`** | `--from-chapter N --to-chapter M`. `--force` bỏ gate |
| `status` | Pipeline + `MORNING.md` |
| `promote` / `export` | `--target kdp\|vella\|epub` (vella = serial txt legacy) |
| `probe-models` / `list-models` | Test OmniRoute |
| `reset` | Archive catalog, wipe plan/pipeline |

### Workflow — series mới (glass-meridian)

```powershell
# 1. OmniRoute
.\start omni.bat

# 2. UI hoặc CLI
.\.venv\Scripts\python.exe factory\ui\server.py
# Hoặc từng bước:
.\factory\run_factory.ps1 develop-narrative --workspace glass-meridian --pass all
.\factory\run_factory.ps1 validate-narrative --workspace glass-meridian
.\factory\run_factory.ps1 approve-narrative --workspace glass-meridian
.\factory\run_factory.ps1 architect --workspace glass-meridian
.\factory\run_factory.ps1 approve-bible --workspace glass-meridian
.\factory\run_factory.ps1 plan --workspace glass-meridian --book 1
.\factory\run_factory.ps1 approve-plan --workspace glass-meridian
.\factory\run_factory.ps1 write --workspace glass-meridian --from-chapter 1 --to-chapter 1
```

### Workflow — bắt đầu sạch (sau reset)

```powershell
.\factory\run_factory.ps1 plan --book 1
.\factory\run_factory.ps1 fix-plans --book 1 --no-llm   # khóa canon ch1-3
# Đọc: factory/workspaces/ceo-contract/books/01/prompts/ch_001.txt
.\factory\run_factory.ps1 fix-plans --book 1              # sửa ch4+ bằng LLM (tùy chọn)
.\factory\run_factory.ps1 approve-plan
.\factory\run_factory.ps1 write --from-chapter 1 --to-chapter 1
.\factory\run_factory.ps1 status
```

### Workflow — viết hàng ngày

```powershell
.\factory\run_factory.ps1 write --from-chapter 2 --to-chapter 5
.\factory\run_factory.ps1 status
.\factory\run_factory.ps1 export --target vella
```

### Workflow — chỉ xóa plan/prompt (giữ catalog)

Xóa tay hoặc dùng `reset` (reset còn archive + wipe catalog chapters).

Sau khi xóa plan/prompt + pipeline:

- `direction.yaml` → `plan_status: draft`
- `state.json` → `current_chapter: 0`

---

## `direction.yaml` — khóa sáng tạo

File: `factory/workspaces/<workspace>/direction.yaml` (vd. `glass-meridian`)

| Field | Ý nghĩa |
|-------|---------|
| **`pen_name`** | Bút danh KDP — **bắt buộc trước export**. Dark: `Reynard Frost` (`Docs/pen_names_data.txt`) |
| **`target_language`** | **`vi`** hoặc **`en`** — đổi 1 dòng, cả pipeline nhảy ngôn ngữ |
| `total_chapters` | Số chương book |
| `canon_through` | Chương đã chốt canon — Outliner không plan lại từ đầu |
| `plan_status` | `draft` \| `approved` |
| `narrative_profile` | `romance_thriller`, `sweet_romance`, gothic/no-ML, … |
| `narrative_status` | `draft` \| `approved` — compiler OFF cho đến khi approved |
| `publish_strategy` | `kdp_ku_exclusive` \| `wide_serial` |
| `workspace_mode` | `archive` → tắt compiler (legacy) |
| `spice_default` / `spice_*_chapters` | Mức spice theo chương |
| `arc`, `book1_ending`, `audience`, `goal`, `blurb` | Prompt Writer / Outliner |

Chỉnh direction → chạy lại `plan` (hoặc `plan --acts 13-30` cho một act).

### `target_language` — đổi ngôn ngữ cả pipeline

```yaml
# direction.yaml
target_language: vi   # test tiếng Việt (mặc định)
# target_language: en # chuyển sang English
```

Fallback mặc định: `config.json` → `default_target_language: vi`.

| Thành phần | Theo `target_language` |
|------------|------------------------|
| `prompt_builder` | Header, tech rules, spice blocks, section labels |
| `roles/writer.txt`, `roles/qc.txt` | Placeholder `<<language_*>>` render lúc gọi API |
| `roles/outliner.txt` | Plan JSON viết bằng ngôn ngữ đích |
| `machine_qc` | **vi**: cấm CJK/Hangul — **en**: cấm CJK + chữ có dấu tiếng Việt |
| Profiles | `factory/engine/lib/language.py` (`vi`, `en`) |

Sau khi đổi `target_language`: `render-prompts` (hoặc `fix-plans`) rồi `write` lại.

---

## Plan QC (`plan_qc.py`)

**Kỹ thuật:** opens_with, must_happen < 3, spice mismatch, signature generic, cliffhanger yếu.

**Romance / absent male lead:**
- Có ML thật → thiếu `[ROMANCE]` = fail
- `Unassigned (no male lead)` / M.I.A. → **cấm** invent love interest / bác sĩ hiện diện; dùng `[ISOLATION]` / absence beat
- Cast allowlist: `Dr. X` trong plan/state phải khớp concept/bible (vd. chỉ **Dr. Ovid**, phone-only)

**Narrative (NC-01..NC-07)** — khi compiler bật: clue plant/payoff, knowledge gate, beats.

**Locked plans:** `bible/locked_chapter_plans.json` (`locked: true`).

**Normalize:** `plan_normalize.py` — unwrap `{chapter_plan: {...}}`, flatten list lồng trong `must_happen` (LLM hay trả nested list).

---

## Machine QC khi viết

`factory/engine/config.json`:

| Key | Mặc định | Ý nghĩa |
|-----|----------|---------|
| `min_word_count` | **1250** | Dưới ngưỡng → length fail (không cho qua ready) |
| `min_publish_words` | **1250** | EG-08 export/promote |
| `max_word_count` | 2200 | Gợi ý trần |
| `writer_short_retries` | 2 | Expand patch khi short |
| `writer_length_max_retries` | 3 | Full rewrite khi expand chưa đủ (supervised) |
| `writer_content_max_retries` | 2 | POV / name drift / bible (supervised) |
| `writer_auto_max_retries` | **10** | Auto mode: content + length full rewrite |
| `write_mode` | `parallel` | Parallel chapters vs sequential state gate |
| `banned_phrases` | list | Cụm sáo |
| `throttle_seconds` | 4 | Nghỉ giữa call |
| `default_workspace` | glass-meridian | CLI/UI mặc định |

**Buckets `machine_qc.classify_machine_issues`:**

| Bucket | Ví dụ | Hành vi auto |
|--------|-------|----------------|
| `format_fix` | `*italic*`, missing quotes | `needs_fix` — **STOP**, sửa tay |
| `length` | short < min | expand → full rewrite → mới `needs_fix` |
| `content_fail` | POV I/my, name drift | retry tới cap → `needs_review` |

---

## Catalog & promote

Khi chương **PASS** QC (hoặc operator **Duyệt**):

1. `pipeline/ready/ch_NNN.txt`
2. `promote_chapter` — export-gate subset (EG-01/02/03/06/08/10/11/12) + canon_guard
3. `catalog/<series>/books/<slug>/chapters/` + `spot_check/`
4. Export EPUB: gate full EG-01..12 → `dc:creator` = `pen_name` → optional `--cover cover.png`

### Pen name + cover (KDP)

```yaml
# direction.yaml + manifest.yaml + series.yaml
pen_name: Reynard Frost   # dark fiction — xem Docs/pen_names_data.txt
```

```
catalog/<series>/books/<slug>/cover.png   # hoặc cover.jpg
.\factory\run_factory.ps1 export --workspace the-paper-oracle --target epub --cover catalog/the-paper-oracle/books/01-the-paper-oracle/cover.png
```

**Không mở `archive/.../exports/epub/`** — đó là backup trước export; bản mới nằm dưới `catalog/.../exports/epub/`.

### Title chain

```
# heading prose → master_plan title → catalog title → fallback
```

```powershell
.\factory\run_factory.ps1 repair-catalog --workspace the-paper-oracle
.\factory\run_factory.ps1 qc-export-gate --workspace the-paper-oracle
.\factory\run_factory.ps1 export --workspace the-paper-oracle --target epub --cover path\to\cover.png
```

---

## Recon — quét thị trường

```powershell
.\run.ps1 init
.\run.ps1 search --platforms royalroad --subniches 1
.\run.ps1 detail --platforms royalroad
.\run.ps1 reparse --platforms royalroad    # parse lại HTML cache, không mạng
.\run.ps1 tropes
.\run.ps1 matrix
.\run.ps1 full --platforms royalroad --subniches 1
```

| Command | Mô tả |
|---------|--------|
| `init` | Khởi tạo SQLite DB |
| `search` | Tìm theo sub-niche trên từng platform |
| `detail` | Scrape chi tiết + export CSV |
| `reparse` | Sửa parser, đọc cache |
| `tropes` | Trích trope từ mô tả |
| `matrix` | Decision matrix |
| `full` | Chạy cả pipeline |

Platform: `amazon`, `vella`, `webnovel`, `goodnovel`, `royalroad` hoặc `all`.

DB và CSV nằm trong `recon/` (xem `recon/config.py`).

---

## Workspaces

### `the-paper-oracle` / `the-salt-room-1` (KDP dark — Reynard Frost)

- EN gothic / psychological dread, spice 1, **no male lead**
- `pen_name: Reynard Frost`, cover + EPUB đã gắn author
- Cast cứng: concept/bible only (vd. Dr. Ovid = phone-only)

### `glass-meridian` (default_workspace — thriller-romance)

- EN international thriller-romance
- `narrative_profile: romance_thriller`
- Tách bút danh romance khi publish (không dùng Reynard Frost)

### `ceo-contract` (legacy)

- EN plan 50 ch — tham chiếu / archive data

---

## Archive & scripts cũ

| Path | Ghi chú |
|------|---------|
| `archive/story_factory/` | Factory phiên bản cũ (đã migrate) |
| `archive/scripts/` | Prompt + output chương viết tay |
| `archive/catalog_*` | Backup catalog khi `reset` |
| `scripts/DEPRECATED.txt` | Không dùng trong pipeline — chỉ tham chiếu format |

---

## Xử lý sự cố

### OmniRoute / model

```powershell
.\start omni.bat                    # khởi động gateway
.\factory\run_factory.ps1 probe-models
.\factory\run_factory.ps1 probe-models --role writer
```

- Log OmniRoute dài (guardrails, auto selection) — **bình thường** nếu HTTP 200
- `invalid bearer` + `REQUIRE_API_KEY=false` — factory dùng `api_key: local`, vẫn chạy
- Chậm ~10–15s/call với prompt 5k+ token — bình thường
- Tinh chỉnh provider: OmniRoute dashboard → Settings → Connections (reconnect GitHub nếu bị ban)
- **`All models failed (... gh/gpt-4o ... No active credentials for provider: github)`** — toàn chain fail; lỗi cuối thường là GitHub. Sửa: reconnect credential trong Omni **hoặc** bỏ `gh/*` khỏi `model_priority_groups` (config hiện chỉ dùng `auto/fast`, `auto`, `auto/best-fast`)
- **`moi` — Unable to determine provider** — không dùng alias này; Omni không nhận
- Token usage: `factory/engine/factory_log.json` (`prompt_tokens`, `completion_tokens` mỗi call)

### Duyệt treo / “bấm Duyệt không qua”

- Cũ: `chapter_approve` gọi `state_updater` (LLM) **trước** promote → treo OmniRoute
- Hiện: **promote trước**, chỉ bump `current_chapter` local — không chờ LLM
- Restart UI sau khi pull code; nếu vẫn fail → đọc toast `export gate chặn promote: EG-…`

### Chương cụt / EG-01 / KDP spelling

- EG-01: body kết giữa câu → sửa catalog md rồi export lại
- KDP Quality: sửa từ bịa (vd. `hypoxiate` → `go hypoxic`) trong `catalog/.../chapters/` rồi `export --cover`

### Batch treo / `batch dang chay`

- Refresh trang — server tự xóa lock cũ nếu không còn thread batch thật
- Bấm **Hủy lock batch** trên dashboard hoặc `POST /api/pipeline/<ws>/batch/reset`
- Đừng chạy nhiều batch chồng nhau — dễ đốt token Omni vô ích

### Chương `needs_fix` / `needs_review` — đọc lý do

| Nguồn | File / UI |
|-------|-----------|
| Machine QC | `pipeline/needs_fix/ch_NNN_issues.json` |
| LLM QC | `pipeline/needs_review/ch_NNN_qc.json` |
| UI | Tab Chương — hộp vàng + tóm tắt trên card |
| Sáng | `catalog/<ws>/MORNING.md` — chi tiết từng ch kẹt |

Ví dụ: `quá ngắn (1347 từ)` · `đứt mạch (continuity): ...`

### Plan JSON / normalize

- `plan_raw_XXX_YYY.txt` — raw Outliner (đối chiếu khi master bị lệch)
- `normalize-plan` — sửa wrapper lồng + must_happen nested
- `knowledge_matrix`: `must_not_know_before` hỗ trợ **dict** hoặc **int + hidden_truth**
- Lỗi `sequence item N: expected str` → chạy `normalize-plan` hoặc `fix-plans`
- **`must_happen: ["["]` / thiếu `must_not` sau re-plan** — JSON bị cắt nhưng vẫn lưu; xem **Bản vá 2026-07-14** (ink-and-venom ch9). Sửa tay field từ `beat_summary`/`plan_raw_*` rồi `approve-plan`
- **`male_lead_cross_source_mismatch` / tên `Dr. X` bị cắt** — xem **Bản vá 2026-07-14** (parser + `locked_canon_names`); không re-plan mang tính “may mắn”

### Chương quá ngắn (`needs_fix`)

- Kiểm tra prompt có `1600-1900 chữ` trong phần kỹ thuật
- Writer hay under-deliver — cân nhắc chỉnh `roles/writer.txt` hoặc expand pass (roadmap)
- Sửa tay trong `pipeline/needs_fix/` rồi promote thủ công nếu cần

### `write` bị chặn

```
plan chưa approved
```

→ `approve-plan` hoặc `write --force` (không khuyến khích)

### Unicode / PowerShell

Factory dùng `safe_print` cho log tiếng Việt. File luôn UTF-8.

### Test máy (không LLM)

```powershell
.\factory\run_checks.ps1
.\factory\run_checks.ps1 -Zone guards
```

---

## Tóm tắt một dòng

**Recon** tìm sub-niche → **Narrative OS** → **Canon registry / LOCKED CANON** → **Factory** (format≠length≠content retries) → **Catalog + EG-01..12 + pen_name/cover** → KDP.
