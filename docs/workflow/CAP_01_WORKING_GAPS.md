# CAP-01 Working / Gaps (PRD-CAP-01)

**PRD:** `PRD_CAP_01_CAPABILITY_MATRIX_RESOLVER.md`  
**Branch intent:** `feature/cap-01-capability-matrix-resolver`  
**Scope:** Capability Matrix registry + package route resolver (MCP vs `HUMAN_FALLBACK`); GET capabilities; Studio/Handoff honesty. **No MCP Send** (HO-02).

---

## Step progress

| Step | Status | Notes |
|------|--------|-------|
| 0 Preconditions | **Done** | Restarted again: folder inventory (xlsx+json) + adjacent schemas; must-seed re-verified |
| 1 Contract lock | **Done** | `dataruns/capabilities/contract.py` + step1 tests |
| 2 Matrix seed file | **Done** | `matrix_seed.json` (40 rows) + gen script + step2 tests |
| 3 Registry loader | **Done** | `registry.py` — get_capability / list_capabilities + step3 tests |
| 4 Resolver | **Done** | `resolver.py` — deps + route; stock HUMAN_FALLBACK; fake MCP path tested |
| 5 Wire build package | **Done** | `build_package` uses `resolve_blueprint_capabilities`; step5 tests |
| 6 GET APIs | **Done** | `GET /api/v1/capabilities/` + by id; Admin/Analyst/Viewer; no POST/PATCH |
| 7 BE tests | **Done** | PRD §8 BE matrix sign-off (`test_capability_matrix_step7`) |
| 8 FE Studio (+ QA) | **Done** | Route chip + resolution line on Studio + QA from live package |
| 9 FE Handoff honesty | **Done** | CAP-01 route chip + resolution on `/handoff`; Send stays locked |
| 10 Writeback safety | **Done** | Option B locked; CI-01/CC-03/WB-SHOP-01 mapping + execute caps green |
| 11 Acceptance + verify | **Done** | §9 checklist + `verify_cap01_backend.py` + FE `verify:cap01` |
| 12 PR | **Ready** | Manual commit/PR — see §Step 12 below (split BE/FE repos) |

---

## Step 1 — locked contract

**Code:** `dataruns/capabilities/contract.py`  
**Pack SoT:** `capability_record.schema.json` (`schema_version` = `1.0.0`)  
**Tests:** `dataruns.tests.test_capability_matrix_step1`

### 1.1 Matrix status enum (seed `status`)

| Value | Meaning for CAP-01 |
|-------|-------------------|
| `CONFIRMED_LIVE` | Execute-eligible (MCP WRITE still needs non-empty `evidence`) |
| `CONFIRMED_LIMITED` | Same eligibility band as LIVE for route unlock |
| `DISCOVERY_REQUIRED` | Not execute-eligible → fallback / NOT_CONFIRMED |
| `REQUIRED_BUILD` | Not execute-eligible |
| `NOT_SUPPORTED` | Not execute-eligible |

**Stock seed lock:** all `MCP.*` stay `DISCOVERY_REQUIRED` (no fabricated CONFIRMED).

### 1.2 Mode enum

`READ` · `WRITE` · `WRITE_ARTIFACT` · `READ_ARTIFACT`

### 1.3 Seed row shape

Align pack schema (`additionalProperties: false` on records).

| Field | Lock |
|-------|------|
| `schema_version` | Always `1.0.0` |
| `capability_id` | Pack id string |
| `channel` | e.g. `MANAGO_MCP`, `HUMAN_OPERATOR`, `REST_V2` |
| `mode` | Pack mode enum |
| `status` | Pack status enum — exact from Matrix sheet 02 |
| `input_contract` / `output_contract` | Strings (may be short) |
| `fallback` | String or `null` (Matrix prose OK in seed; resolver prefers blueprint `fallback` id) |
| `evidence` | Array — `[]` for MCP until discovery; human may cite Matrix |
| `verified_at` | Optional; `null` unless evidence recorded |

**Must-seed statuses (Step 2 must assert):**

| capability_id | status |
|---------------|--------|
| `HUMAN.WORKFLOW.BUILD` | `CONFIRMED_LIVE` |
| `MCP.WORKFLOW.UPSERT` | `DISCOVERY_REQUIRED` |
| `MCP.WORKFLOW.PUBLISH` | `DISCOVERY_REQUIRED` |
| `RESTV2.WORKFLOW.LIST` | `CONFIRMED_LIVE` (READ — **does not** unlock `route=MCP`) |

**Seed path:** `dataruns/capabilities/matrix_seed.json`  
**Envelope (intent for Step 2):** `{ "schema_version", "source": "pack:Capability Matrix v1.1", "count", "capabilities": [ …records ] }`

### 1.4 Package `route`

```text
route = "MCP"  iff  MCP.WORKFLOW.UPSERT is execute-eligible
else route = "HUMAN_FALLBACK"
```

**Execute-eligible UPSERT** (`upsert_is_execute_eligible`):

1. `status ∈ {CONFIRMED_LIVE, CONFIRMED_LIMITED}`  
2. If channel is `MANAGO_MCP` and mode is WRITE/WRITE_ARTIFACT → `evidence` non-empty  
3. Else fail closed  

**M2 stock seed:** `route` always **`HUMAN_FALLBACK`**. Unit test may fake CONFIRMED + evidence in-memory to prove `route=MCP`.

### 1.5 `capability_resolution[]` row

| Field | Required | Notes |
|-------|----------|-------|
| `capability_id` | yes | From blueprint dep |
| `required_status` | yes | From blueprint (pass-through) |
| `resolved_status` | yes | See §1.6 |
| `fallback_used` | yes | Capability id string or `null` |
| `matrix_status` | optional | Registry `status` when known |
| `channel` | optional | Registry channel when known |

### 1.6 `resolved_status` rules (per blueprint dep)

| Case | `resolved_status` | `fallback_used` |
|------|-------------------|-----------------|
| Cap missing from registry | `NOT_CONFIRMED` if no dep fallback; else `HUMAN_FALLBACK` | dep `fallback` or null |
| Cap `DISCOVERY_REQUIRED` / `REQUIRED_BUILD` / `NOT_SUPPORTED` | `HUMAN_FALLBACK` if fallback available; else `NOT_CONFIRMED` | dep `fallback` → else Matrix fallback id if mappable → else null |
| Cap CONFIRMED_* + (human channel **or** MCP WRITE with evidence) | Matrix status; **UPSERT** uses alias `MCP` when execute-eligible | null (or Matrix fallback unused) |
| Cap CONFIRMED_* but MCP WRITE with **empty** evidence | Treat as not execute-eligible → same as discovery path | as above |
| **`MCP.WORKFLOW.UPSERT` not execute-eligible** | Always `HUMAN_FALLBACK` | **`HUMAN.WORKFLOW.BUILD`** (dep fallback or default) |

Unknown id → fail closed for MCP route (never invent `route=MCP`).

### 1.7 Blueprint `required_status`

| Value | Meaning |
|-------|---------|
| `CONFIRMED_LIVE` | Prefer live Matrix status; else fallback / NOT_CONFIRMED |
| `CONFIRMED_LIVE_OR_APPROVED_FALLBACK` | Live **or** approved human fallback satisfies dep (package still buildable) |

Do **not** invent new blueprint fields. UC-02 UPSERT uses `CONFIRMED_LIVE_OR_APPROVED_FALLBACK` + `fallback: HUMAN.WORKFLOW.BUILD`.

### 1.8 Explicit non-goals (still)

| Item | Owner |
|------|-------|
| Handoff Send / `ACTIVATED` / publish | HO-02 |
| Flipping seed MCP → CONFIRMED | CAP-01B + evidence |
| Writeback registry unify | Option B locked — defer |

### 1.9 Helpers locked in code

| Helper | Behavior |
|--------|----------|
| `status_allows_mcp_write(status)` | `status ∈ {CONFIRMED_LIVE, CONFIRMED_LIMITED}` |
| `upsert_is_execute_eligible(...)` | CONFIRMED_* + MCP WRITE evidence (or human channel) |

---

## Step 2 — Matrix seed file

**Runtime SoT:** `dataruns/capabilities/matrix_seed.json`  
**Regen (optional):** `python scripts/gen_capability_matrix_seed.py` (needs xlsx + openpyxl; not used at runtime)  
**Tests:** `dataruns.tests.test_capability_matrix_step2`

| Lock | Value |
|------|--------|
| Envelope | `schema_version=1.0.0`, `source=pack:Capability Matrix v1.1`, `count`, `capabilities[]` |
| Row count | **40** (full sheet 02) |
| MCP.* | `status=DISCOVERY_REQUIRED`, `evidence=[]`, `verified_at=null` |
| UPSERT `fallback` | **`HUMAN.WORKFLOW.BUILD`** (sheet 05 id override; not Matrix prose) |
| Must-seed | HUMAN BUILD / REST LIST = CONFIRMED_LIVE; UPSERT / PUBLISH = DISCOVERY_REQUIRED |
| Docker | Seed JSON only — **no xlsx** required |

**Recheck:** No fabricated MCP CONFIRMED in committed seed; unique `capability_id`s; pack status/mode enums only

---

## Step 3 — Registry loader

**Module:** `dataruns/capabilities/registry.py`  
**Tests:** `dataruns.tests.test_capability_matrix_step3`

| API | Behavior |
|-----|----------|
| `get_capability(capability_id)` | Deep-copied seed row or `None` (unknown / empty → fail closed); **case-insensitive** id |
| `list_capabilities(channel=, status=, q=)` | Envelope `{ schema_version, source, count, results }` — filters for GET §6 |
| `get_matrix_source()` / `get_matrix_schema_version()` | Seed envelope metadata |
| `clear_matrix_registry_cache()` | Test / regen helper |
| `matrix_seed_path()` | Package-local `matrix_seed.json` (Docker-safe) |

**Locks:** File-only (no DB); does **not** touch writeback execute map (option B + TODO in `writebacks/capabilities.py`); list filters are case-insensitive exact for channel/status, substring for `q` on `capability_id`; load validates status/mode enums, evidence list, and envelope `count`.

### Deep-check (Steps 0–3)

| Check | Result |
|-------|--------|
| Pack folder docs (xlsx + discovery JSON) | OK |
| Seed 40 rows / must-seed / all MCP DISCOVERY + empty evidence | OK |
| UC-02 AGENT.* present as CONFIRMED_LIVE in seed | OK |
| Registry get/list + fail-closed unknown | OK |
| Option B TODO on writebacks | OK |
| `upsert_is_execute_eligible` requires real evidence list | OK |
| Docker: seed under `dataruns/` (not `docs/`) | OK |

---

## Step 4 — Resolver

**Module:** `dataruns/capabilities/resolver.py`  
**Tests:** `dataruns.tests.test_capability_matrix_step4`

| API | Behavior |
|-----|----------|
| `resolve_dependency(dep, default_fallback=, overrides=)` | One `capability_resolution` row (+ optional `matrix_status` / `channel`) |
| `resolve_capabilities(deps, …)` | List of rows |
| `resolve_package_route(rows)` | `MCP` iff UPSERT `resolved_status=MCP`; else `HUMAN_FALLBACK` |
| `resolve_blueprint_capabilities(body, …)` | `{ capability_resolution, route }` |

**Locks**

| Case | Result |
|------|--------|
| Stock seed + UC-02 deps | `route=HUMAN_FALLBACK`; UPSERT → `HUMAN_FALLBACK` + `fallback_used=HUMAN.WORKFLOW.BUILD` |
| AGENT.* CONFIRMED in seed | `resolved_status=CONFIRMED_LIVE` |
| Missing id, no fallback | `NOT_CONFIRMED` |
| UPSERT always | Fallback forced to human build id when not execute-eligible |
| In-memory override UPSERT CONFIRMED + evidence | `route=MCP` (unit only; seed unchanged) |
| Matrix prose fallback | Not used as `fallback_used` (must look like capability id) |

**Non-goal:** does not enable Send / publish (HO-02).

### Deep-check (Step 4)

| Check | Result |
|-------|--------|
| Stock UC-02 → `route=HUMAN_FALLBACK` + UPSERT human fallback | OK |
| AGENT CONFIRMED pass-through | OK |
| Fake UPSERT CONFIRMED(+LIMITED)+evidence → `route=MCP` | OK |
| REST LIST CONFIRMED does **not** unlock MCP route | OK |
| PUBLISH discovery + prose fallback → `NOT_CONFIRMED` | OK |
| Empty / bad UPSERT override → still HUMAN_FALLBACK | OK |
| Empty capability_id / empty body | OK |
| Wire into `build_package` | **Done** (Step 5) |

---

## Step 5 — Wire build package

**Module:** `dataruns/use_cases/build_package.py`  
**Tests:** `dataruns.tests.test_capability_matrix_step5`

| Lock | Behavior |
|------|----------|
| `assemble_build_package_payload` | Calls `resolve_blueprint_capabilities` for `route` + `capability_resolution[]` |
| `_resolve_capabilities` | Thin wrapper → resolver (no hardcode) |
| Stock UC-02 generate | `route=HUMAN_FALLBACK`; UPSERT → human fallback + `matrix_status`/`channel` |
| AGENT.* | `CONFIRMED_LIVE` (not pre-CAP `NOT_CONFIRMED`) |
| Existing packages | Immutable stored JSON — only **new** generates use resolver |

**Handoff:** unchanged — still reads package `route` (HO-01); HUMAN_FALLBACK copy stays Manago-human.

---

## Step 6 — GET capabilities APIs

**Module:** `dataruns/capabilities/views.py` · `dataruns/capabilities_urls.py`  
**Mount:** `GET /api/v1/capabilities/` (+ `{capability_id}/`) via `core/urls.py`  
**Tests:** `dataruns.tests.test_capability_matrix_step6`

| Lock | Behavior |
|------|----------|
| List | Envelope `{ schema_version, source, count, results }` from `list_capabilities` |
| Filters | `?channel=` · `?status=` · `?q=` (registry exact / substring rules) |
| Detail | Seed row or **404** unknown; id lookup **case-insensitive** |
| Roles | Admin / Analyst / Viewer (read-only); non-reader role → **403** (`test_non_reader_role_gets_403`) |
| Writes | **No** POST/PATCH/PUT/DELETE in v1 (405) |
| Audit | None for GET |
| Storage | File seed only — no DB |

---

## Step 7 — BE case matrix (PRD §8 backend)

Authoritative BE sign-off before FE. FE §8 rows (Studio / Handoff) → Steps 8–9. Deep writeback execute → Step 10.

| §8 / gate | Expect | Status |
|-----------|--------|--------|
| Seed `HUMAN.WORKFLOW.BUILD` | `CONFIRMED_LIVE` | Pass |
| Stock `MCP.WORKFLOW.UPSERT` | `DISCOVERY_REQUIRED` + empty evidence | Pass |
| Stock `MCP.WORKFLOW.PUBLISH` | `DISCOVERY_REQUIRED` | Pass |
| `RESTV2.WORKFLOW.LIST` CONFIRMED READ | Does **not** unlock `route=MCP` | Pass |
| No fabricated MCP CONFIRMED in seed | All `MCP.*` discovery | Pass |
| Generate UC-02 package | `route=HUMAN_FALLBACK`; UPSERT → human fallback + Matrix fields | Pass |
| In-memory UPSERT CONFIRMED + evidence | `route=MCP` | Pass |
| GET `/capabilities/` | 200; MCP + HUMAN rows | Pass |
| GET unknown id | 404 | Pass |
| Writeback CI-01 capability | Mapping still `RESTV2.CONTACT.UPSERT` + execute-eligible; option B TODO intact | Pass |

**Tests:** `dataruns.tests.test_capability_matrix_step7`

---

## Step 8 — FE Studio (+ QA) route honesty

**Surfaces:** `/workflow` (`WorkflowStudio`) · `/qa`  
**Helpers:** `klints_frontend/src/lib/capability-route.ts`

| Lock | Behavior |
|------|----------|
| Studio **Build route** row | Live package `route` only; `—` until package exists (never pilot fallback id) |
| Studio **Build package** card | Route chip + PRD copy + `MCP.WORKFLOW.UPSERT → HUMAN.WORKFLOW.BUILD` when resolution present |
| QA eyebrow | Same chip + copy + resolution line from live package |
| Copy `HUMAN_FALLBACK` | “Human build guide — MCP upsert not confirmed” |
| Copy `MCP` | “MCP upsert confirmed — Send still not live (HO-02)” |
| Toast / touchpoints | No “sent via MCP”; route not used as a touchpoint pill |
| Helpers | `lib/capability-route.ts` + shared `PackageRouteHonesty` |
| Empty route on package | “Route not set on this package” (not a generate hint) |
| Handoff | See Step 9 |

**Verify:** `npm run verify:cap01` (frontend)

---

## Step 9 — FE Handoff route honesty

**Surface:** `/handoff` (`LiveHandoffBody` · Route / capability)  
**Helpers:** `handoffRouteSummary` → `packageRouteSummary` · shared `PackageRouteHonesty`

| Lock | Behavior |
|------|----------|
| Route source | Live handoff `route` (trimmed) else build package `route` |
| Chip + copy | CAP-01 §7 (`HUMAN_FALLBACK` / `MCP` / empty) |
| Resolution line | From build package `capability_resolution` when loaded |
| Send / Send all | Still `HandoffSendLockedButton` only — **no** MCP Send (HO-02) |
| Toast | No “sent via MCP” / fake Sent |
| Whitespace-only live route | Falls through to package `route` (does not blank the chip) |

**Verify:** `npm run verify:cap01` (+ `npm run verify:ho01` Send lock non-regression)

---

## Step 10 — Writeback safety (option B)

**Goal:** CAP-01 Matrix registry must **not** break Engineering writeback execute for allowlisted checks.  
**Tests:** `dataruns.tests.test_capability_matrix_step10`

| Lock | Expect | Status |
|------|--------|--------|
| Option B comment + `TODO(CAP-unify)` | Present on `writebacks/capabilities.py` | Pass |
| Seed paths | `matrix_seed.json` ≠ `writebacks/capabilities.json` | Pass |
| Adapters | `manago` / `shopify` / writeback caps **do not** import Matrix registry | Pass |
| CI-01 | Mapping → `RESTV2.CONTACT.UPSERT` · execute-eligible · registry enabled | Pass |
| CC-03 | Mapping → `RESTV2.CONTACT.UPSERT` · execute-eligible · registry enabled | Pass |
| WB-SHOP-01 | Mapping → `SHOPIFY.CUSTOMER.UPDATE` · execute-eligible · registry enabled | Pass |
| Matrix vs writeback | Same id may exist in Matrix; writeback gate still uses writeback JSON | Pass |
| Shopify independence | `SHOPIFY.CUSTOMER.UPDATE` absent from Matrix, still execute-eligible in writeback | Pass |

**Non-goal:** Unify Matrix + writeback loaders (CAP-unify later).

---

## Step 11 — §9 Acceptance

| §9 item | Evidence |
|---------|----------|
| Matrix seed committed; no xlsx at runtime | `dataruns/capabilities/matrix_seed.json` (40) · registry file-only |
| `_resolve_capabilities` uses registry | `build_package` → `resolve_blueprint_capabilities` |
| Stock packages `route=HUMAN_FALLBACK` | Step 5/7 UC-02 generate tests |
| `capability_resolution[]` Matrix-backed | Step 5/7 UPSERT + AGENT asserts |
| `GET /api/v1/capabilities/` tenant-auth | Step 6 API tests |
| Studio + Handoff honest; no MCP Send | Steps 8–9 · `npm run verify:cap01` · `verify:ho01` |
| Writebacks allowlisted checks | Step 10 · CI-01/CC-03/WB-SHOP-01 |
| No fabricated MCP CONFIRMED in seed | Step 2/7/10 · verify script |

**Verify**

```bash
# Backend (from klints_backend)
python scripts/verify_cap01_backend.py
python scripts/verify_cap01_backend.py --run-tests

# Frontend (from klints_frontend)
npm run verify:cap01
npm run verify:ho01   # Send lock non-regression
```

**PRD:** §9 checklist marked `[x]` in `PRD_CAP_01_CAPABILITY_MATRIX_RESOLVER.md`.

---

## Step 0 — Preconditions (locked · restarted)

**Exit criteria:** Needed pack docs found · Matrix/discovery/schema readable · discovery not inventable as CONFIRMED · code gap confirmed · writeback option chosen · product locks written. **Met.**

### 0.0 Needed docs inventory

#### A — In `02_Execution_Capabilities/` (this folder)

| File | Role for CAP-01 | Status |
|------|-----------------|--------|
| `Klints_Manago_ExecutionCapabilityMatrix_v1.1_20260718.xlsx` | Pack SoT — sheets **02** (seed rows) + **05** (fallback / route rules). Also 01 Overview, 03 Discovery Plan, 04 Evidence Log. | **Found** (16 648 bytes) · 40 matrix rows · all must-seed IDs present |
| `manago_mcp_discovery_results.json` | Proof MCP is not live — top `PENDING_EXECUTION`; 15 tests PENDING / PENDING_APPROVAL; `evidence: null`. Do **not** invent CONFIRMED. | **Found** (3 229 bytes) |

**Only these two files** live in that folder (no other JSON/XLS).

#### B — Adjacent pack docs (PRD §0 brief — required)

| File | Folder | Role for CAP-01 | Status |
|------|--------|-----------------|--------|
| `capability_record.schema.json` | `03_Machine_Contracts/` | Seed row shape / status enum SoT | **Found** |
| `workflow_blueprint.schema.json` | `03_Machine_Contracts/` | Blueprints may declare `capability_dependencies[]` (loose object items) | **Found** (reference only; do not change blueprints) |
| `UC-02_blueprint.json` (+ 15 peers) | `04_MVP1_Pilot_Blueprints/` | Sample deps for resolve tests; **do not edit** | **Found** |
| `pilot_manifest.json` | `04_MVP1_Pilot_Blueprints/` | Pilot `fallback` defaults | **Found** |
| `handoff_package.schema.json` | `03_Machine_Contracts/` | HO-01 already shipped — CAP-01 must not enable Send | Present (out of CAP write scope) |

#### C — Repo code / docs (not in pack folder)

| Path | Role |
|------|------|
| `docs/engineering/PRD_CAP_01_CAPABILITY_MATRIX_RESOLVER.md` | This PRD |
| `dataruns/use_cases/build_package.py` (`_resolve_capabilities`) | Replaced in Step 5 — Matrix resolver |
| `dataruns/writebacks/capabilities.json` + `capabilities.py` | Engineering — **do not break** (option B) |

### 0.1 Dependencies

| Dep | Status | Evidence |
|-----|--------|----------|
| **WF-01** | Present | `build_package.py` emits `route` + `capability_resolution[]` via Matrix resolver (Step 5) |
| **HO-01** | Product-ready | Live `/handoff` + `handoffRouteSummary` + Send locked (`HANDOFF_SEND_DISABLED_TITLE`); WORKING_GAPS Step 12 Ready |
| **Pack Matrix v1.1** | **Present** | §0.0 A — xlsx + discovery JSON |
| **Blueprints** | Present | Do **not** edit 16 blueprint JSONs (PRD out of scope) |

### 0.2 Pack artifacts reviewed

| Artifact | Path | Finding |
|----------|------|---------|
| `capability_record.schema.json` | `Klints_MVP1_…/03_Machine_Contracts/` | Row SoT. Required: `schema_version`=`1.0.0`, `capability_id`, `channel`, `mode`, `status`, `input_contract`, `output_contract`, `fallback`, `evidence`. Status enum: `CONFIRMED_LIVE` \| `CONFIRMED_LIMITED` \| `DISCOVERY_REQUIRED` \| `REQUIRED_BUILD` \| `NOT_SUPPORTED`. Mode: `READ` \| `WRITE` \| `WRITE_ARTIFACT` \| `READ_ARTIFACT`. `additionalProperties: false`. Optional `verified_at`. |
| Matrix xlsx | `…/02_Execution_Capabilities/Klints_Manago_ExecutionCapabilityMatrix_v1.1_20260718.xlsx` | **On disk**. Sheets: `01 Overview`, **`02 Capability Matrix`**, `03 MCP Discovery Plan`, `04 Evidence Log`, **`05 Fallback Rules`**. |
| `manago_mcp_discovery_results.json` | same folder | Top-level **`PENDING_EXECUTION`** · **15** tests · all PENDING / PENDING_APPROVAL · `evidence: null`. **Do not invent CONFIRMED.** |
| Discovery UPSERT | MCP-D-12 / MCP-D-13 | `MCP.WORKFLOW.UPSERT` → `PENDING_APPROVAL`, no evidence |
| Discovery PUBLISH | — | Not a discovery test row; Matrix still has `MCP.WORKFLOW.PUBLISH` = `DISCOVERY_REQUIRED` |

#### Sheet 02 — Capability Matrix (read)

| Metric | Value |
|--------|-------|
| Data rows | **40** |
| Status mix | CONFIRMED_LIVE 16 · CONFIRMED_LIMITED 4 · DISCOVERY_REQUIRED 15 · REQUIRED_BUILD 4 · NOT_SUPPORTED 1 |
| All `MCP.*` | **DISCOVERY_REQUIRED** (15 ops), including UPSERT + PUBLISH |
| Headers | Capability ID · Object · Operation · Channel · Mode · Status · Input/Output Contract · Side Effect · Fallback · Evidence Source |

**PRD §3.2 must-seed — verified in sheet 02:**

| capability_id | channel | mode | status | Matrix fallback (human text) |
|---------------|---------|------|--------|------------------------------|
| `HUMAN.WORKFLOW.BUILD` | HUMAN_OPERATOR | WRITE | **CONFIRMED_LIVE** | Required MVP1 fallback |
| `MCP.WORKFLOW.UPSERT` | MANAGO_MCP | WRITE | **DISCOVERY_REQUIRED** | Human-operated build guide |
| `MCP.WORKFLOW.PUBLISH` | MANAGO_MCP | WRITE | **DISCOVERY_REQUIRED** | Human activation in UI |
| `RESTV2.WORKFLOW.LIST` | REST_V2 | READ | **CONFIRMED_LIVE** | MCP discovery for richer graph — **does not unlock `route=MCP`** |

#### Sheet 05 — Fallback Rules (read · workflow-relevant)

| Operation class | Preferred | Fallback | MVP1 rule |
|-----------------|-----------|----------|-----------|
| **Workflow build** | `MCP.WORKFLOW.UPSERT` | **`HUMAN.WORKFLOW.BUILD`** | All 16 pilots remain buildable through human fallback |
| **Workflow publish** | Human activation | `MCP.WORKFLOW.PUBLISH` after confirmation | **No autonomous activation in MVP1** |

Overview principle (sheet 01): MCP starts DISCOVERY_REQUIRED; never inferred live; DISCOVERY_REQUIRED cannot execute without fallback.

**Seed strategy (locked for Step 2):** Generate `dataruns/capabilities/matrix_seed.json` from sheet **02** (all 40 rows preferred). Map UPSERT fallback → `HUMAN.WORKFLOW.BUILD` for resolver (sheet 05). `evidence: []` for MCP until discovery. Runtime reads **JSON only** (no xlsx in Docker). Optional `scripts/` regenerator OK.

### 0.3 Code gap confirmed (today)

| Surface | Behavior |
|---------|----------|
| `build_package._resolve_capabilities` | **CAP-01 Step 5:** Matrix resolver (was hardcoded HUMAN / NOT_CONFIRMED) |
| Package `route` | Becomes `MCP` only if UPSERT row `resolved_status == "MCP"` — **never** with hardcode |
| Engineering writebacks | `writebacks/capabilities.json` + `capabilities.py` — REST/Shopify execute gate; **≠** Matrix |
| FE Handoff | **CAP-01 Step 9:** route chip + resolution from live handoff/package; Send locked |
| FE Studio | **CAP-01 Step 8:** route chip + resolution line from live package |

### 0.4 UC-02 blueprint sample (do not edit)

| capability_id | required_status | fallback |
|---------------|-----------------|----------|
| `AGENT.SEGMENT.CREATE` | `CONFIRMED_LIVE` | null |
| `AGENT.EMAIL.DRAFT` | `CONFIRMED_LIVE` | null |
| `MCP.WORKFLOW.UPSERT` | `CONFIRMED_LIVE_OR_APPROVED_FALLBACK` | `HUMAN.WORKFLOW.BUILD` |

**Expected after CAP-01 stock seed:** `route=HUMAN_FALLBACK`; UPSERT → `resolved_status=HUMAN_FALLBACK`; `fallback_used` contains `HUMAN.WORKFLOW.BUILD`.

### 0.5 Writeback option (locked)

**Choice: B** for CAP-01 v1.

| Option | Decision |
|--------|----------|
| **A** Shared loader | Deferred — Engineering / CAP unify later |
| **B** Leave writeback JSON as-is | **Locked** — CAP registry is Studio/package only; TODO to unify |

**Why B:** Different shape (`batch_max`, no channel/evidence). Unifying now risks CI-01 / CC-03 / WB-SHOP-01. PRD allows B.

### 0.6 Product locks (carry into Step 1)

| Lock | Value |
|------|--------|
| Stock seed → package `route` | Always **`HUMAN_FALLBACK`** |
| MCP CONFIRMED in committed seed | **Forbidden** (discovery PENDING; sheet 02 MCP.* = DISCOVERY_REQUIRED) |
| Handoff Send / ACTIVATED | **Out of scope** (HO-02 / sheet 05 publish rule) |
| GET capabilities | Read-only; **no POST/PATCH** in v1 |
| Registry storage v1 | **File-only** seed (no DB model) |
| Seed path | `dataruns/capabilities/matrix_seed.json` |
| Branch / PR title | Per PRD §11 |

### 0.7 Explicitly not this PRD (§10)

| Later | Why |
|-------|-----|
| E2E-01 | Loom / M2 submission after CAP honesty |
| HO-02 | Live MCP Send + ACTIVATED |
| CAP-01B | Discovery plan + evidence + status flips with audit |
| Unify writeback + Matrix | Follow-up (option B) |

### 0.8 Gaps / risks noted

| Gap | Impact | Mitigation |
|-----|--------|------------|
| `02_Execution_Capabilities/` has only xlsx + discovery JSON | No pre-built matrix seed JSON in pack | Step 2 generates `matrix_seed.json` into `dataruns/capabilities/` |
| xlsx may be gitignored / missed by some indexers | Easy to think file missing | Path locked in §0.0 A |
| Matrix fallback column is prose, not always a capability_id | Resolver needs ID fallback | Prefer blueprint `fallback` + map UPSERT → `HUMAN.WORKFLOW.BUILD` (sheet 05) |
| UC-02 AGENT.* may be REQUIRED_BUILD / missing in Matrix | Resolves NOT_CONFIRMED if no fallback | Acceptable for M2 if UPSERT→HUMAN path is honest; expand seed from full sheet 02 |
| Discovery has no PUBLISH test | N/A for CAP-01 | Matrix still seeds PUBLISH as DISCOVERY_REQUIRED |

---

## Step 12 — PR (manual)

CAP-01 spans **two git repos** (`klints_backend`, `klints_frontend`). Do not commit from the parent `Klints/` folder (no commits there).

### Pre-flight

```bash
# Backend (klints_backend)
python scripts/verify_cap01_backend.py
# Optional when Django env ready:
python scripts/verify_cap01_backend.py --run-tests

# Frontend (klints_frontend)
npm run verify:cap01
```

### Branch (both repos)

`feature/cap-01-capability-matrix-resolver` → base `main`

If CAP-01 work currently sits on another local branch (e.g. WF-02), create the CAP branch from `main` and bring only CAP-01 paths across (or rename/cherry-pick). Do not mix unrelated WF-02 commits into the CAP-01 PR.

### What to commit

| Repo | Paths (CAP-01) |
|------|----------------|
| **klints_backend** | `dataruns/capabilities/` · `dataruns/capabilities_urls.py` · `dataruns/use_cases/build_package.py` · `dataruns/writebacks/capabilities.py` (CAP-unify TODO) · `core/urls.py` · `dataruns/tests/test_capability_matrix_step*.py` · `scripts/verify_cap01_backend.py` · `scripts/gen_capability_matrix_seed.py` · `docs/engineering/CAP_01_WORKING_GAPS.md` · `docs/engineering/PRD_CAP_01_CAPABILITY_MATRIX_RESOLVER.md` · `docs/engineering/README.md` |
| **klints_frontend** | `src/lib/capability-route.ts` · `src/components/workflow/PackageRouteHonesty.tsx` · `src/components/workflow/WorkflowStudio.tsx` · `src/routes/qa.tsx` · `src/routes/handoff.tsx` · `src/lib/handoff.ts` · `src/lib/use-cases.ts` · `scripts/verify-cap01-frontend.mjs` · `package.json` (`verify:cap01`) |

### Suggested PR titles

| Repo | Title |
|------|-------|
| Backend | `feat(CAP-01): Capability Matrix registry + package route resolver (human default)` |
| Frontend | `feat(CAP-01): Studio/QA/Handoff route honesty (no MCP Send)` |

PRD §11 default title covers the **backend** deliverable; frontend PR is the honesty UI + verify script.

### BE PR body (copy)

- Seed Capability Matrix (`matrix_seed.json`, 40 rows); file registry + resolver
- `build_package` uses Matrix-backed `capability_resolution`; stock route = `HUMAN_FALLBACK`
- `GET /api/v1/capabilities/` (+ by id); read-only
- Writebacks stay on option B (separate JSON); CI-01 / CC-03 / WB-SHOP-01 execute unchanged
- Test: `python scripts/verify_cap01_backend.py` · `--run-tests`

### FE PR body (copy)

- Shared `PackageRouteHonesty` + `packageRouteSummary` / `packageResolutionLine` (CAP-01 copy locks)
- Studio + QA + Handoff show live package route; never imply MCP Send
- Send stays locked (`HandoffSendLockedButton`)
- Test: `npm run verify:cap01`

---

## Gaps / defer (running)

| Item | Status |
|------|--------|
| MCP Send / ACTIVATED | HO-02 |
| MCP discovery evidence flips | CAP-01B |
| Writeback ↔ Matrix unify | Deferred (option B) |
| Sheet 02 → committed seed | **Done** (Step 2) |

---

## PR note (draft)

**Right:** CAP-01 complete for M2 route honesty — Matrix seed + registry + resolver; packages resolve `HUMAN_FALLBACK` until UPSERT is confirmed with evidence; GET capabilities read-only; Studio/QA/Handoff show route + resolution from live package; writebacks unchanged (option B). Verify: BE `verify_cap01_backend.py` · FE `verify:cap01`.

**Gap:** MCP Send / `ACTIVATED` = HO-02. Discovery evidence flips = CAP-01B. Writeback ↔ Matrix unify deferred. Step 12 PRs are manual (see WORKING_GAPS §Step 12).
