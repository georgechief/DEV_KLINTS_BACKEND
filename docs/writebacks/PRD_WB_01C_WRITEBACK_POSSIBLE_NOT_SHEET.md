# PRD-WB-01C — Writeback possible/not sheet + common write API contract

**Status:** Backend implemented  
**Owner track:** Engineering   
**Depends on:** WB-01 + WB-01B ([BE #39](https://github.com/georgechief/klints_backend/pull/39) / [FE #27](https://github.com/georgechief/klints_frontend/pull/27)) — merge first or land on same branch  
**Pack sources (read-only — do not rewrite pack history):**  
- `Klints_MVP1_Rohan_Build_Pack_v1.2_20260718/01_Specifications/Klints_Spec_InitialDataConsistencyCheck_v1.4.1_20260718.xlsx` → sheet **02 Check Catalogue** (Suggested Fix · Fix Type · Fix Owner · Rollback Note · surfaces)  
- same workbook → sheet **06 Field Mapping Reference**  
- `…/02_Execution_Capabilities/Klints_Manago_ExecutionCapabilityMatrix_v1.1_20260718.xlsx` → sheet **02 Capability Matrix**  
**Out of scope:** Enabling prod `WRITEBACKS_ENABLED=True` · FE Approve live · inventing fields not in Suggested Fix / `map.json` · Shopify order/transaction writers · changing DCS check pass/fail

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-01C — honest writeback possible/not sheet + common API keys.

Read:
- docs/engineering/PRD_WB_01C_WRITEBACK_POSSIBLE_NOT_SHEET.md
- docs/engineering/PRD_WB_01B_SANDBOX_PROOF_AND_LE04_FIX.md (§3 matrix)
- Pack: DCS “02 Check Catalogue” + Manago Capability Matrix

Must ship:
1. New sheet (CSV + optional xlsx) listing per MVP1 check / write surface:
   what is possible vs not (op_kind, fields, native vs klints_, update existing?,
   rollback?, status). Ground every YES in pack Suggested Fix + our mapping.
2. GET API that returns that sheet as JSON (same truth as the file).
3. Common writeback request contract: preview / execute / rollback share one
   envelope shape; only keys change by action (document + thin adapter if needed).
4. Keep sandbox/prod gates from WB-01/01B. Do not enable FE Approve.

Acceptance: §8.
```

---

## 1. Why

WB-01B shipped an **object-level** honesty matrix (contacts / orders / transactions). Reviewers still ask:

- For **this check**, can we write?  
- **Which fields** — new `klints_*` only, or **update pre-existing** native values?  
- Can we **rollback**?  
- Is the API the same for write vs rollback?

This PRD answers with a **check/field sheet** (evidence, like the Check Catalogue) and a **common write API contract** so Postman / FE / ops use one mental model.

---

## 2. Deliverable A — Writeback Possible/Not sheet

### 2.1 Files to commit

| File | Role |
|------|------|
| `dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv` | **Authoritative** machine-readable sheet (required; Docker-safe runtime path) |
| `docs/engineering/WRITEBACK_POSSIBLE_NOT_SHEET.csv` | Human mirror / editorial copy (optional in prod) |
| `docs/engineering/WRITEBACK_POSSIBLE_NOT_SHEET.xlsx` | Optional Excel for humans (same columns) |
| Keep `WRITEBACK_SURFACE_MATRIX.md` | Object-level summary (already from 01B) — link from sheet README row 0 / header comment |

Do **not** edit the pack Excel in place. Our sheet is a **Klints implementation view** of the pack.

### 2.2 Columns (locked)

| Column | Meaning |
|--------|---------|
| `check_id` | e.g. `CC-03`, `CI-01`, `LE-04`, `WB-SHOP-01` |
| `check_name` | From CheckMaster / Catalogue |
| `pack_fix_type` | From Catalogue (Automated writeback / Integration build / Configuration / …) |
| `pack_fix_owner` | From Catalogue |
| `pack_suggested_fix_summary` | Short paraphrase of Catalogue Suggested Fix (no PII) |
| `platform` | `manago` \| `shopify` \| `both` \| `none` |
| `op_kind` | e.g. `detail_set`, `contact_upsert`, `shopify_customer_update`, `—` |
| `entity` | `contact` \| `customer` \| `event` \| `order` \| … |
| `field_or_key` | Concrete write target: `klints_consent_evidence`, `email`, `note`, `tag:klints:…`, `—` |
| `namespace` | `klints_` \| `klints:` \| `native` \| `n/a` |
| `creates_new` | `yes` \| `no` \| `n/a` — can create a new detail/tag/metafield |
| `updates_existing` | `yes` \| `no` \| `n/a` — can overwrite a **pre-existing** value on that entity |
| `write_possible_today` | `yes` \| `no` \| `sandbox_only` \| `preview_only` \| `disabled` |
| `rollback_possible_today` | `yes` \| `no` \| `partial` \| `n/a` |
| `mapping_file` | e.g. `CC-03.consent_provenance.v1.json` or `—` |
| `registry_enabled` | `true` \| `false` |
| `blocker` | Why not / why limited (e.g. `pack_fix_type=Integration+Manual`, `no_adapter`, `orders_not_supported`) |
| `evidence_note` | How we know (Catalogue row + mapping op + Loom/check) |
| `last_verified` | ISO date or empty |

### 2.3 Row coverage (minimum)

1. **Every enabled registry mapping** (CI-01, CC-03, WB-SHOP-01, …) — one row per **field/key** written.  
2. **Every disabled / stub mapping** we keep in repo (LE-04, CI-03, SP-01, LE-01, …) — at least one row with `write_possible_today=disabled` + honest `blocker`.  
3. **Explicit NO rows** for high-confusion surfaces (even without a mapping file):

| check_id / topic | Expected |
|------------------|----------|
| Shopify Order | `write_possible_today=no` |
| Shopify Transaction / payment | `no` |
| Manago “Order CRUD” | `no` (events ≠ order updater) |
| LE-04 | `disabled` — pack Integration build + Manual (T6) |

4. Optional stretch: top FAIL/WARN MVP1 checks from Catalogue with Fix Type = Automated writeback that we have **not** mapped yet → `write_possible_today=no`, `blocker=mapping_not_built`.

### 2.4 Rules for filling YES

A cell may be `yes` / `sandbox_only` only if **all** hold:

1. Pack **Fix Type** allows automated writeback **or** row is explicitly marked sandbox proof (`WB-SHOP-01`).  
2. Field appears in Catalogue Suggested Fix **or** is a documented `klints_*` / `klints:` marker / sandbox proof field.  
3. Field is reverse-mappable via `map.json` **or** declared in mapping `from_evidence` / `extras` / `detail_set` key.  
4. Adapter `op_kind` is **implemented** + capability `CONFIRMED_LIVE` (or sandbox allowlisted path).  
5. `updates_existing=yes` only when execute path can overwrite an already-present value (upsert / detail overwrite / note replace) — not invent a fake “update.”

If unsure → `no` or `preview_only` + `STOP_AND_FLAG` in `blocker`. Prefer under-claiming.

### 2.5 Optional Google Sheet

Ops may mirror the CSV into a private Google Sheet for review. **Repo CSV remains SoT.** Link the Sheet URL in the PR description (not secrets).

---

## 3. Deliverable B — API that serves the sheet

### 3.1 Read API (required)

```http
GET /api/v1/writebacks/possible/
Authorization: Bearer …
```

**Auth:** same as mappings — Authenticated + Admin/Analyst/Viewer.  
**Company:** not required for static sheet (implementation truth is global). Optional later: overlay per-company sandbox eligibility flags.

**Response 200:**

```json
{
  "schema_version": 1,
  "source": "dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv",
  "generated_from": [
    "pack:02 Check Catalogue",
    "pack:Manago Capability Matrix",
    "dataruns/writebacks/mappings/"
  ],
  "count": 42,
  "rows": [
    {
      "check_id": "CC-03",
      "platform": "manago",
      "op_kind": "detail_set",
      "field_or_key": "klints_consent_evidence",
      "namespace": "klints_",
      "creates_new": "yes",
      "updates_existing": "yes",
      "write_possible_today": "sandbox_only",
      "rollback_possible_today": "yes",
      "registry_enabled": true,
      "blocker": "",
      "evidence_note": "Catalogue Suggested Fix + CC-03 mapping + WB-01B Loom"
    }
  ]
}
```

Load from committed CSV (or regenerate from registry + Catalogue seed in a management command — CSV must stay in sync; prefer **CSV as SoT**, API reads CSV).

### 3.2 FE (optional thin)

Settings or Fix “Write surfaces” disclosure: table from `GET …/possible/` — not required for v1 if Postman + CSV in PR is enough. If shipped: read-only, no execute.

---

## 4. Deliverable C — Common writeback / rollback API contract

Today we already have three paths under `/api/v1/writebacks/`. Keep them for compatibility, but **norm the shared envelope** so “keys change by action” is explicit.

### 4.1 Common principles (normative)

| Principle | Rule |
|-----------|------|
| Auth | JWT Bearer; company = `get_user_company(user)` only — never pass foreign `company_id` |
| Roles | Preview: Admin/Analyst · Execute/Rollback: **Admin** |
| One check at a time | `check_id` required for preview/execute |
| Freshness | Execute requires `diff_hash` from latest preview |
| Rollback | Uses `job_id` from **execute** (not preview) |
| Gates | Unchanged: allowlist + sandbox ids / `WRITEBACKS_ENABLED` + approval |

### 4.2 Shared request keys

| Key | preview | execute | rollback |
|-----|---------|---------|----------|
| `action` | optional if using dedicated URL; required if using unified URL | same | same |
| `check_id` | **required** | **required** | omit |
| `diff_hash` | omit (returned) | **required** (64-char) | omit |
| `job_id` | omit | omit (returned) | **required** |
| `max_rows` | optional | optional | omit |
| `batch_size` | optional | optional | omit |
| `approval_id` | omit | required only when non-sandbox + prod enabled | omit |

### 4.3 Unified endpoint (implement)

Add **one** action-discriminated endpoint; keep existing three as thin aliases.

```http
POST /api/v1/writebacks/run/
Authorization: Bearer …
Content-Type: application/json
```

**Preview**

```json
{ "action": "preview", "check_id": "CC-03", "max_rows": 1 }
```

**Execute**

```json
{ "action": "execute", "check_id": "CC-03", "diff_hash": "<64 hex>", "max_rows": 1 }
```

**Rollback**

```json
{ "action": "rollback", "job_id": "<uuid>" }
```

Invalid / missing keys for the chosen `action` → **400** with `{ "detail", "required_keys": […] }`.

Aliases (unchanged behaviour):

- `POST …/preview/` → `action=preview`  
- `POST …/execute/` → `action=execute` (mode still `sandbox_execute` when company is sandbox)  
- `POST …/rollback/` → `action=rollback`  

### 4.4 Shared response keys (minimum)

Every run response should include when applicable:

| Key | Notes |
|-----|--------|
| `action` | echo |
| `check_id` | when known |
| `job_id` | preview + execute jobs |
| `diff_hash` | preview / execute |
| `summary` | counts: ready / executed / errors |
| `intents` or `results` | before/after, op_kind, field keys |
| `rollback` | `{ "supported": bool }` on execute when known |
| `blocked_reason` | when gated |

Update Postman collection (`writebacks_sandbox.postman_collection.json`) to show **the same three actions** via `/run/` plus aliases.

---

## 5. Relationship to pack sheets

```text
Pack 02 Check Catalogue  ──► what SHOULD be fixable (Suggested Fix / Fix Type)
Pack Capability Matrix   ──► which WRITE APIs exist
Our map.json + mappings  ──► what we CAN implement
WRITEBACK_POSSIBLE_NOT_SHEET.csv  ──► honest intersection (this PRD)
GET /writebacks/possible/         ──► same data over API
POST /writebacks/run/             ──► common keys for preview|execute|rollback
```

---

## 6. Suggested code layout

```text
dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv   # NEW runtime SoT (Docker-safe)
docs/engineering/PRD_WB_01C_…md
dataruns/writebacks/possible_sheet.py          # load/validate CSV
dataruns/writebacks/views.py                   # PossibleView + RunView
dataruns/writebacks_urls.py                    # routes
docs/engineering/writebacks_sandbox.postman_collection.json  # add /run/
dataruns/tests/test_writeback_01c.py
scripts/verify_wb01c_backend.py
```

---

## 7. Non-goals / still blocked

- FE “Approve writeback” still **Coming soon**  
- Prod execute still off unless env explicitly enables + approval  
- No claim that Catalogue “Automated writeback” rows are live until mapping + sheet say so  
- No Shopify order / payment writers  

---

## 8. Acceptance

- [ ] CSV sheet committed with columns in §2.2  
- [ ] Enabled mappings have field-level YES/sandbox_only rows with `updates_existing` filled honestly  
- [ ] LE-04 + Shopify Order/Transaction + Manago Order CRUD called out as **not** possible  
- [ ] `GET /api/v1/writebacks/possible/` returns CSV rows  
- [ ] `POST /api/v1/writebacks/run/` accepts `action` ∈ `preview|execute|rollback` with key rules in §4.2  
- [ ] Existing preview/execute/rollback URLs still work (aliases)  
- [ ] Postman collection updated; unit/verify script green  
- [ ] PR description links CSV (and optional Google Sheet mirror)

---

## 9. Definition of done

A reviewer can open the sheet (or `GET …/possible/`) and answer for any listed check: **write? update existing? rollback?** — and run Postman with **one URL** changing only `action` + keys.
