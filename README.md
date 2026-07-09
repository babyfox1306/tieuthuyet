# KDP Sub-niche Recon + Story Factory

Repo gồm **hai hệ thống độc lập** dùng chung môi trường Python:

| Vùng | Mục đích | Entry point |
|------|----------|-------------|
| **`recon/`** | Quét thị trường đa nền tảng (KDP, Vella, Webnovel, GoodNovel, Royal Road) → DB + CSV quyết định sub-niche | `.\run.ps1` |
| **`factory/`** | Sản xuất truyện theo chương (narrative → bible → plan → write → QC → catalog) | `.\factory\run_factory.ps1` hoặc **UI** `factory/ui/server.py` |
| **`catalog/`** | Bản giao hàng sạch — chỉ chương đã promote, export KDP/serial | đọc / upload tay |

Triết lý: **recon tìm ngách** → **Narrative OS hiểu truyện** → **factory viết trong khung** → **catalog publish**.

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
- Tab **Chương**: đọc prose, xem **hộp lý do** khi `needs_fix` / `needs_review`, duyệt vào catalog
- **Hủy lock batch** (`🔓`): khi batch treo sau crash/restart server (lock `running: true` còn sót)
- Batch log hiện lý do từng chương fail (vd. `needs_fix — quá ngắn (1347 từ)`)

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
│   │       ├── plan_qc.py              # Plan QC + NC-01..NC-07
│   │       ├── plan_normalize.py       # Unwrap plan, flatten must_happen
│   │       ├── write_guards.py         # State gate, prior excerpt
│   │       ├── qc_eval.py              # QC hard-fail continuity/voice
│   │       ├── chapter_reasons.py      # Lý do needs_fix / needs_review (UI + batch log)
│   │       ├── master_plan.py, prompt_builder.py, call_9router.py, …
│   └── workspaces/
│       ├── ceo-contract/     # EN thriller — plan 50ch, pipeline legacy
│       └── glass-meridian/   # EN clean run (default_workspace)
│           ├── direction.yaml    # narrative_profile, publish_strategy, gates
│           ├── concept.yaml
│           ├── bible/
│           │   ├── series.json
│           │   └── narrative/    # kernel, ledger, threads, knowledge_matrix
│           └── books/01/
│               ├── master_plan.json
│               ├── prompts/ch_NNN.txt
│               ├── state.json
│               └── pipeline/{draft,needs_fix,needs_review,ready}/
│
├── catalog/ceo-contract/       # Delivery zone
│   ├── series.yaml
│   ├── spot_check/             # Bản đọc nhanh khi review
│   └── books/01-hop-dong-co-gia/
│       ├── book.yaml
│       ├── chapters/           # Markdown đã promote
│       └── exports/            # vella | kdp | epub
│
├── archive/                    # Backup catalog, scripts cũ, story_factory cũ
├── scripts/                    # DEPRECATED — prompt tay thời đầu (tham chiếu)
├── start omni.bat              # Khởi động OmniRoute (port 20128)
├── run.ps1                     # Recon CLI
└── requirements.txt
```

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
  approve-plan
```

### Pha 2: Viết từng chương

```
prompts/ch_NNN.txt + state.json + excerpt chương trước (ready)
       │
       ▼
  write (Writer) — chặn nếu ch N-1 chưa ready
       │
       ├── machine_qc → needs_fix
       ├── LLM qc (hard-fail continuity/voice_drift) → needs_review
       └── PASS → ready/ → state_updater → auto-promote → catalog/
```

Batch UI: chỉ skip `ready`; rewrite `needs_fix` / `needs_review`; dừng khi fail (tuỳ chọn). Mỗi chương kẹt hiện **lý do rõ** (quá ngắn, đứt mạch continuity, v.v.) — tab Chương, batch log, `MORNING.md`.

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
| **`target_language`** | **`vi`** hoặc **`en`** — đổi 1 dòng, cả pipeline nhảy ngôn ngữ (prompt, roles, QC ký tự lạ) |
| `total_chapters` | Số chương book (vd: 50) |
| `canon_through` | Chương đã chốt canon — Outliner không plan lại từ đầu |
| `plan_status` | `draft` \| `approved` |
| `narrative_profile` | `romance_thriller`, `sweet_romance`, … |
| `narrative_status` | `draft` \| `approved` — compiler OFF cho đến khi approved |
| `publish_strategy` | `kdp_ku_exclusive` \| `wide_serial` |
| `workspace_mode` | `archive` trong direction → tắt compiler (legacy workspace) |
| `spice_default` | Mức 1 (sweet) cho chương thường |
| `spice_explicit_chapters` | Danh sách chương spice 3 (18+) |
| `spice_steamy_chapters` | Danh sách chương spice 2 |
| `arc` | act1_setup … act4_resolution — range chương |
| `book1_ending` | Kết book 1 — Outliner phải hướng tới |
| `audience`, `goal`, `blurb`, `tropes` | Đưa vào prompt Writer |

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

**Kỹ thuật:** opens_with mở cảnh, must_happen < 3, spice mismatch, signature generic, thiếu `[ROMANCE]`, legacy VN trên EN workspace.

**Narrative (NC-01..NC-07)** — khi compiler bật:

| Rule | Nội dung |
|------|----------|
| NC-01 | Clue plant theo ledger |
| NC-02 | Clue payoff đúng ch |
| NC-03 | Payoff không trước plant |
| NC-04/05 | Major reveal đủ clue trước |
| NC-06 | Knowledge gate — không leak fact sớm |
| NC-07 | Clue phải xuất hiện trong beats |

**Locked plans:** `bible/locked_chapter_plans.json` (`locked: true`).

**Normalize:** `plan_normalize.py` — unwrap `{chapter_plan: {...}}`, flatten list lồng trong `must_happen` (LLM hay trả nested list).

---

## Machine QC khi viết

`factory/engine/config.json`:

| Key | Mặc định | Ý nghĩa |
|-----|----------|---------|
| `min_word_count` | 1500 | Dưới ngưỡng → `needs_fix` |
| `max_word_count` | 2200 | Gợi ý trần |
| `banned_phrases` | list | Cụm sáo, lặp |
| `throttle_seconds` | 4 | Nghỉ giữa call 9router |
| `model_routing` | flexible | OmniRoute auto |
| `model_priority_groups` | auto variants | Xem § Vai AI |
| `default_workspace` | glass-meridian | Workspace mặc định CLI/UI |

---

## Catalog & promote

Khi chương **PASS** QC:

1. Lưu `pipeline/ready/ch_NNN.txt`
2. Cập nhật `state.json`
3. **Auto-promote** → `catalog/<series>/books/<slug>/chapters/NN-slug.md`
4. Copy `spot_check/` để đọc nhanh
5. Export EPUB/DOCX/serial

### Title chain (hệ thống — không phụ thuộc cuốn sách)

Nguồn title theo thứ tự ưu tiên:

```
# heading trong prose  →  master_plan.json (chapter_plans)  →  title catalog (nếu không generic)  →  fallback
```

- **Promote** (`text_to_catalog_md`) và **repair-catalog** ghi title đúng vào frontmatter
- **Export** (`resolve_chapter_display`) — TOC/H1 không bao giờ hiện bare `Chapter N` khi plan có tên thật
- **Export gate EG-09** — chặn generic title khi `master_plan` có title canonical

```powershell
.\factory\run_factory.ps1 repair-catalog --workspace glass-meridian   # normalize catalog in-place (có backup)
.\factory\run_factory.ps1 qc-export-gate --workspace glass-meridian  # EG-01..09, không export
.\factory\run_factory.ps1 promote --workspace glass-meridian --book 1
.\factory\run_factory.ps1 export --target epub
```

UI: nút **Repair catalog** + **Export gate** trên tab Export (`factory/ui/server.py`).

`pen_name` trong `manifest.yaml` để trống — điền tay trước khi publish.

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

### `glass-meridian` (khuyến nghị — clean run)

- **EN** international thriller-romance, Singapore hub
- Leads: Lin Wei × Adrian Vale, Glass Meridian conspiracy
- `narrative_profile: romance_thriller`, narrative files đầy đủ
- `default_workspace` trong `config.json`
- Chạy full pipeline từ narrative → plan → write

### `ceo-contract` (legacy / archive data)

- EN plan 50 ch, narrative approved, compiler ON
- Pipeline ch1–13 có prose cũ (trước pipeline guards) — cần reset hoặc rewrite tuần tự
- Dùng tham chiếu hoặc `workspace_mode: archive` nếu chỉ export catalog cũ

Bible: `factory/workspaces/<id>/bible/series.json`

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

- `plan_raw_XXX_YYY.txt` — raw Outliner
- `normalize-plan` — sửa wrapper lồng + must_happen nested
- `knowledge_matrix`: `must_not_know_before` hỗ trợ **dict** hoặc **int + hidden_truth**
- Lỗi `sequence item N: expected str` → chạy `normalize-plan` hoặc `fix-plans`

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

**Recon** tìm sub-niche → **Narrative OS** (ledger/compiler) → **Factory** plan (NC rules) → prompt → viết (guards + QC) → **Catalog** KDP/serial.
