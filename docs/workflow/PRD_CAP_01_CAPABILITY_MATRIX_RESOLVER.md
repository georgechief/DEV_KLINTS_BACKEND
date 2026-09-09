# PRD-CAP-01 — Capability Matrix resolver (MCP vs human route)

**Status:** Steps 0–11 done; Step 12 PR ready (manual commit) — **P0 (M2)** · see [CAP_01_WORKING_GAPS.md](./CAP_01_WORKING_GAPS.md) §Step 12  
**Owner track:** Engineering  — **BE + FE**  
**Surfaces:** Build package `route` · Studio · QA eyebrow · Handoff capability summary · `GET` capabilities API  
**Depends on:** WF-01 (package `route` / `capability_resolution`) · HO-01 (handoff shows route honestly) · pack Capability Matrix v1.1  
**Out of scope:** Live MCP tool calls / discovery runs against Manago (**ops evidence later**) · **HO-02** MCP Send / `ACTIVATED` · autonomous publish · Engineering writeback execute mappings · inventing `CONFIRMED_LIVE` without pack/evidence · BL-017 ORCH SM · changing the 16 blueprint JSON files  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-CAP-01 — Capability Matrix resolver for package route MCP vs HUMAN_FALLBACK.

Read:
- docs/engineering/PRD_CAP_01_CAPABILITY_MATRIX_RESOLVER.md
- Pack: 02_Execution_Capabilities/Klints_Manago_ExecutionCapabilityMatrix_v1.1_20260718.xlsx
  (sheets 02 Capability Matrix, 05 Fallback Rules) + capability_record.schema.json
- Pack: manago_mcp_discovery_results.json (all PENDING — do not invent CONFIRMED)
- Code: dataruns/use_cases/build_package.py (_resolve_capabilities — currently hardcodes HUMAN)
- Engineering (do not break): dataruns/writebacks/capabilities.json + capabilities.py

Ship:
1. Seed/load Matrix rows into a capability registry (JSON under dataruns/ + optional model) (§3).
2. Resolver: status lookup + package route resolution per Fallback Rules (§4).
3. Replace hardcoded _resolve_capabilities; packages get honest capability_resolution + route (§5).
4. GET /api/v1/capabilities/ (+ optional by id) for Studio/Handoff/ops (§6).
5. FE: Studio + Handoff show route + resolution from live package — never claim MCP Send (§7).
6. Default remains HUMAN_FALLBACK until MCP.WORKFLOW.UPSERT is CONFIRMED_* with evidence (§4.2).

Acceptance: §9. Do not implement HO-02 Send.
```

---

## 1. Why (pack + code gap)

### Pack (SoT)

From **Build Pack v1.2** / Capability Matrix **v1.1**:

| Rule | Pack lock |
|------|-----------|
| MCP ops | All `MCP.*` are **`DISCOVERY_REQUIRED`** until executed evidence exists (`manago_mcp_discovery_results.json` = `PENDING_EXECUTION`) |
| Workflow build | Preferred `MCP.WORKFLOW.UPSERT` → fallback **`HUMAN.WORKFLOW.BUILD`** (`CONFIRMED_LIVE`) — all 16 pilots stay buildable via human |
| Workflow publish | Prefer **human activation**; `MCP.WORKFLOW.PUBLISH` only after confirmation — **no autonomous activation in MVP1** |
| Machine shape | `capability_record.schema.json` — status enum: `CONFIRMED_LIVE` \| `CONFIRMED_LIMITED` \| `DISCOVERY_REQUIRED` \| `REQUIRED_BUILD` \| `NOT_SUPPORTED` |
| Stop-and-flag | Do not silently mark MCP live without evidence |

### Code today

| Surface | Behavior |
|---------|----------|
| `build_package._resolve_capabilities` | **Hardcodes** `MCP.WORKFLOW.UPSERT` → `resolved_status: HUMAN_FALLBACK`; other deps → `NOT_CONFIRMED` |
| Package `route` | Always **`HUMAN_FALLBACK`** in practice (MCP branch never sets `resolved_status == "MCP"`) |
| Engineering writebacks | Separate tiny `writebacks/capabilities.json` (REST/Shopify WRITE) — **not** the Matrix registry |
| Studio / Handoff | Show package `route` when present; no Matrix-backed resolver |

**CAP-01** makes route + resolution **Matrix-backed and honest**, without flipping MCP to live or implementing Send.

---

## 2. Product outcome (M2)

1. Every build package’s `capability_resolution[]` comes from the **registry** (pack Matrix seed), not a hardcode.  
2. Package `route`:
   - **`HUMAN_FALLBACK`** when `MCP.WORKFLOW.UPSERT` is not execute-eligible (today’s reality), **or**
   - **`MCP`** only when registry says `MCP.WORKFLOW.UPSERT` ∈ `{CONFIRMED_LIVE, CONFIRMED_LIMITED}` **and** evidence refs exist.  
3. Studio + Handoff copy explain the route (human build guide vs MCP-ready) — **Send still disabled** (HO-01 / HO-02).  
4. Ops can inspect Matrix status via API without opening the xlsx.

---

## 3. Capability registry (BE)

### 3.1 Source of truth order

1. **Seed file** checked into repo (required for Docker; same pattern as writeback possible sheet):  
   `dataruns/capabilities/matrix_seed.json` (or `dataruns/use_cases/capability_matrix_seed.json`)  
2. Generated once from pack xlsx sheet **02 Capability Matrix** (script OK in `scripts/`; do **not** require xlsx at runtime).  
3. Optional later: DB table overlay for evidence updates — **v1 may be file-only** if GET + resolver read the seed.

### 3.2 Seed row shape (align `capability_record.schema.json`)

Minimum fields per row:

| Field | Notes |
|-------|--------|
| `capability_id` | e.g. `MCP.WORKFLOW.UPSERT`, `HUMAN.WORKFLOW.BUILD` |
| `channel` | `MANAGO_MCP`, `HUMAN_OPERATOR`, `REST_V2`, … |
| `mode` | `READ` \| `WRITE` \| … |
| `status` | Pack enum — seed **exactly** from Matrix (MCP.* stay `DISCOVERY_REQUIRED`) |
| `fallback` | From Matrix column (string or null) |
| `input_contract` / `output_contract` | From Matrix (may be short strings) |
| `evidence` | Array — empty `[]` for MCP until discovery; human row may cite pack Matrix as source |
| `verified_at` | null unless evidence recorded |

Also seed:

| `capability_id` | Expected seed status |
|-----------------|----------------------|
| `HUMAN.WORKFLOW.BUILD` | `CONFIRMED_LIVE` |
| `MCP.WORKFLOW.UPSERT` | `DISCOVERY_REQUIRED` |
| `MCP.WORKFLOW.PUBLISH` | `DISCOVERY_REQUIRED` |
| `RESTV2.WORKFLOW.LIST` | `CONFIRMED_LIVE` (read — does **not** unlock package `route=MCP`) |

### 3.3 Engineering writebacks

**Do not break** `dataruns/writebacks/capabilities.py`.  

**v1 options (pick one in PR, document):**

- **A (preferred):** Shared loader module used by both; writeback file remains a **subset overlay** or migrates REST/Shopify ids into the same seed.  
- **B:** Leave writeback JSON as-is; CAP-01 registry is Studio/package only; add a code comment + TODO to unify later.

Either way: CI-01 / CC-03 / WB-SHOP-01 execute must keep working.

---

## 4. Resolver (core)

### 4.1 Status lookup

```text
get_capability(capability_id) -> record | None
status_allows_mcp_write(status) -> status in {CONFIRMED_LIVE, CONFIRMED_LIMITED}
```

Unknown id → treat as **not confirmed** (fail closed for MCP route).

### 4.2 Package route resolution (Fallback Rules · Workflow build)

For each blueprint `capability_dependencies[]` row:

| Case | `resolved_status` | `fallback_used` |
|------|-------------------|-----------------|
| Cap `CONFIRMED_LIVE` or `CONFIRMED_LIMITED` and (if WRITE MCP) evidence non-empty **or** human channel | pass through Matrix status (or `MCP` alias for UPSERT — see below) | null / Matrix fallback |
| Cap `DISCOVERY_REQUIRED` / `REQUIRED_BUILD` / `NOT_SUPPORTED` / missing | `HUMAN_FALLBACK` when dep defines `fallback` (e.g. `HUMAN.WORKFLOW.BUILD`); else `NOT_CONFIRMED` | `fallback` from dep or Matrix |
| `MCP.WORKFLOW.UPSERT` specifically | If not execute-eligible → `HUMAN_FALLBACK` + `fallback_used=HUMAN.WORKFLOW.BUILD` | required |

**Package `route`:**

```text
route = "MCP"  iff  MCP.WORKFLOW.UPSERT resolves to execute-eligible (CONFIRMED_LIVE|LIMITED + evidence)
else route = "HUMAN_FALLBACK"
```

**Locked for M2 ship with current pack seed:** `route` remains **`HUMAN_FALLBACK`**. Tests must assert that with stock seed. A unit test may flip seed status + fake evidence in-memory to prove `route=MCP` path exists.

### 4.3 Publish / Send (explicit non-goal)

Fallback Rules: prefer human activation; no autonomous publish.  
**CAP-01 does not enable Handoff Send.** HO-02 owns `MCP.WORKFLOW.PUBLISH` / activation.

### 4.4 `required_status` on blueprints

Blueprints use values like `CONFIRMED_LIVE` and `CONFIRMED_LIVE_OR_APPROVED_FALLBACK`.  

Resolver interpretation:

| `required_status` | Meaning |
|-------------------|---------|
| `CONFIRMED_LIVE` | Prefer live capability; if missing → fallback / NOT_CONFIRMED |
| `CONFIRMED_LIVE_OR_APPROVED_FALLBACK` | Live **or** approved human fallback satisfies the dep (package still buildable) |

Do not invent new blueprint fields.

---

## 5. Wire build package (replace hardcode)

### 5.1 Change `dataruns/use_cases/build_package.py`

Replace `_resolve_capabilities` body with calls to the resolver (§4).  

Keep package payload fields from WF-01:

- `route`
- `capability_resolution[]` — each row: `capability_id`, `required_status`, `resolved_status`, `fallback_used`, optional `matrix_status`, `channel`

### 5.2 Existing packages

Already-generated packages keep stored JSON (immutable).  
**New** generates use the resolver. Optional: document that old packages may show pre-CAP resolution until regenerated.

### 5.3 Handoff

HO-01 already surfaces package route / approval_ref.  
Ensure handoff UI/API siblings still read `route` from package; when `HUMAN_FALLBACK`, copy stays “activation / build human in Manago”.

---

## 6. HTTP API

```http
GET /api/v1/capabilities/
Authorization: Bearer …
```

**200:** `{ "schema_version": "1.0.0", "source": "pack:Capability Matrix v1.1", "count": N, "results": [ …records ] }`  

Optional filters: `?channel=MANAGO_MCP` · `?status=DISCOVERY_REQUIRED` · `?q=WORKFLOW`

```http
GET /api/v1/capabilities/{capability_id}/
```

**200** record · **404** unknown  

**Roles:** Admin / Analyst / Viewer (read-only).  

**No POST/PATCH in v1** that sets `CONFIRMED_LIVE` from the app (avoids silent Matrix drift). Evidence updates = seed PR or future admin PRD.

Audit: none required for GET. If a future write lands, audit `capability.status_updated`.

---

## 7. Frontend

| Surface | Bind |
|---------|------|
| Workflow Studio | Show package `route` chip + short resolution line (“MCP.WORKFLOW.UPSERT → HUMAN.WORKFLOW.BUILD”) from live package / detail |
| QA | Eyebrow already can show route — use live package field |
| Handoff | Capability / route summary from live handoff + package; Send remains locked |
| Optional ops | Simple read-only Capabilities list page **not required** if Studio+Handoff show enough — prefer minimal |

Copy rules:

- Never toast “sent via MCP”  
- If `route=HUMAN_FALLBACK`: “Human build guide — MCP upsert not confirmed”  
- If `route=MCP` (future evidence): “MCP upsert confirmed — Send still not live (HO-02)”  

---

## 8. Tests + verify

### BE

| Case | Expect |
|------|--------|
| Seed loads; `HUMAN.WORKFLOW.BUILD` = CONFIRMED_LIVE | Pass |
| Stock seed: `MCP.WORKFLOW.UPSERT` = DISCOVERY_REQUIRED | Pass |
| Generate UC-02 package | `route=HUMAN_FALLBACK`; UPSERT row `resolved_status=HUMAN_FALLBACK`; `fallback_used` contains `HUMAN.WORKFLOW.BUILD` |
| In-memory override UPSERT → CONFIRMED_LIVE + evidence | `route=MCP` |
| GET `/capabilities/` | 200, includes MCP + HUMAN rows |
| GET unknown id | 404 |
| Writeback execute CI-01 still green | No regression |

### FE

| Case | Expect |
|------|--------|
| Studio package shows HUMAN_FALLBACK + honest line | Pass |
| Handoff STAGED still Send disabled | Pass |

### Script (optional)

`scripts/verify_cap01_backend.py` — load seed counts + assert UPSERT not CONFIRMED in committed seed.

---

## 9. Acceptance

- [x] Matrix seed committed; runtime does not need the xlsx  
- [x] `_resolve_capabilities` no longer hardcodes blindly — uses registry  
- [x] Stock seed → all new packages `route=HUMAN_FALLBACK`  
- [x] `capability_resolution[]` lists blueprint deps with Matrix-backed statuses / fallbacks  
- [x] `GET /api/v1/capabilities/` works tenant-auth  
- [x] Studio + Handoff honest about route; **no MCP Send**  
- [x] Engineering writebacks still execute for allowlisted checks  
- [x] Pack rule respected: no fabricated MCP CONFIRMED in seed  

---

## 10. Explicitly next (not this PRD)

| Later | Why |
|-------|-----|
| **E2E-01** | Lumera path Loom + M2 submission (after CAP honesty) |
| **HO-02** | Live MCP/A2A Send + `ACTIVATED` when UPSERT/PUBLISH confirmed |
| **CAP-01B** | Run MCP discovery plan (MCP-D-01…); attach evidence; flip statuses with audit |
| **Unify** writeback + Matrix registry | Engineering follow-up if option B chosen |

---

## 11. PR title / branch

- Branch: `feature/cap-01-capability-matrix-resolver`  
- Title: `feat(CAP-01): Capability Matrix registry + package route resolver (human default)`  
- Manual checklist: [CAP_01_WORKING_GAPS.md](./CAP_01_WORKING_GAPS.md) §Step 12  

---

## 12. Traceability

| Item | Note |
|------|------|
| Milestone | M2 — honest MCP vs human before T2 E2E claim |
| Pack | Capability Matrix v1.1 · Fallback Rules · `capability_record.schema.json` · MCP discovery PENDING |
| Parents | WF-01 §7.1–7.2 · HO-01 §10 |
| Independent of | HO-02 Send · Engineering POLISH-01 (already shipped) |
| BUILD_README | “Capability Matrix resolves Manago MCP, Agent, REST, … and human fallbacks” |
