# PRD-M3-SEC-01 — RBAC Matrix, Tenant Isolation Evidence & Security Review Packet

**Status:** Implementation complete (Phases 0–6 evidence) — pending operator commit / PR / Rohan review  
**Owner track:** Sahil (`docs/sahil/`) — **BE / tests / verify / docs packet** (no Klints product FE required)  
**Surfaces:** Django/DRF API · pytest · `scripts/verify_m3_sec01_backend.py` · `docs/security/` packet  
**Milestone:** **M3 Demo, Security & DP1 (T3)** — contract AC *Security review passed; tenant isolation verified* + deliverable *Security + observability hardened (**RBAC**, **audit tamper detection**, Grafana)*  
**SoT layers (priority when they conflict):**  
1. **Contract** Schedule 1 M3 (Astrapse v1.2) — security review + tenant isolation AC; RBAC + audit tamper detection named with Grafana  
2. **This PRD** (implementation SoT for SEC-01)  
3. **Existing product controls** — roles, `get_user_company`, AUDIT-01 / migration `0030`, connector uniqueness  
4. **Code / CI truth** after merge  

**Locked product decisions (employer · 2026-09-11):**

| # | Decision |
|---|----------|
| D1 | **Evidence + targeted hardening** — do **not** rebuild RBAC engine, audit hash chain, or company resolvers |
| D2 | **Roles stay Admin / Analyst / Viewer** — no new role enums, no OPA, no fine-grained permission tables |
| D3 | **Cross-tenant fail closed** — other company’s object id → **404** preferred (or **403** if already established); list endpoints never leak foreign rows |
| D4 | **Executable evidence** — matrix + negative tests + `verify_m3_sec01_backend.py` + review packet with employer checklist |
| D5 | **Honest claim language** — after merge: *internal security review packet + automated isolation/RBAC evidence*; **not** pen-test / SOC2 / DP1 / Grafana = security |
| D6 | **BE-first** — FE UI RBAC polish is out of scope unless a hole is proven to be FE-only (flag Rohan) |
| D7 | **Grafana / OBS stays separate** — M3-OBS-01 Phase 6 closeout is ops/Rohan; do not expand this PRD into Loki/alerts |

**Out of scope:** Grafana / Loki / Alloy · Prometheus (M3-OBS-02) · DP1 / demo seed (M3-DEMO-01) · MCP / Capability Matrix flips · external pen-test firm · SOC2 · new roles · FE redesign · rewriting AUDIT-01 · multi-company-per-tenant product redesign · Celery periodic audit verify as hard AC  

**Progress tracker:** [M3_SEC_01_WORKING_GAPS.md](./M3_SEC_01_WORKING_GAPS.md) · Phase notes: [PHASE_0](./M3_SEC_01_PHASE_0.md) → fill PHASE_1…6 as you go (same pattern as OBS-01)

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-M3-SEC-01 — RBAC Matrix, Tenant Isolation Evidence & Security Review Packet.

Read:
- docs/sahil/PRD_M3_SEC_01_RBAC_ISOLATION_SECURITY_PACKET.md (this file)
- docs/sahil/M3_SEC_01_WORKING_GAPS.md
- docs/security/KLINTS_AI_SECURITY_AND_DATA_PROCESSING_RESPONSE.md (§3.1 / §10.6 isolation intent)
- tenants/models.py (User.Role)
- tenants/auth/services.py (get_user_company)
- dataruns/audit.py + management/commands/verify_audit_chain.py
- dataruns/migrations/0030_audit_logs_immutability_triggers.py
- tenants/views.py (TenantViewSet)
- dataruns/views.py (DataRunViewSet)
- scripts/verify_m3_obs01_backend.py (template for verify_m3_sec01_backend.py)
- core/urls.py (API family inventory)

Ship:
1. docs/security/M3_SEC_01_RBAC_MATRIX.md — Admin/Analyst/Viewer × every /api/v1/* family
2. Cross-tenant isolation tests (company A vs B) for allowlisted object-ID APIs
3. Role negative tests (viewer/wrong-role → 403; unauth → 401) on mutating surfaces
4. Harden or disable TenantViewSet + DataRunViewSet global list leaks + tests
5. scripts/verify_m3_sec01_backend.py — static gate (packet files, tests, audit artifacts, no scope creep)
6. docs/security/M3_SEC_01_SECURITY_REVIEW_PACKET.md — inventory, findings, residual risks, employer checklist §11
7. Phase notes under docs/sahil/M3_SEC_01_PHASE_*.md as you complete each phase

Do NOT: rebuild audit hash chain · add Grafana work · invent MCP live · claim pen-test · add new roles · FE redesign.
Stop-and-flag if a surface cannot be scoped without product decision (e.g. multi-company-per-tenant).
Acceptance: §11.
```

---

## 1. Why this PRD exists

| Problem | Effect |
|---------|--------|
| Contract M3 AC: **“Security review passed; tenant isolation verified”** | M2 claim correctly marks this **not started** |
| Contract deliverable names **RBAC + audit tamper detection** alongside Grafana | OBS-01 shipped Grafana only; M3-S1 still open |
| Controls exist but **evidence is scattered** | Reviewer cannot point to one packet + one verify script |
| Some ViewSets still list **all tenants / all data runs** | Real IDOR / review finding if left unfixed |
| Isolation tests exist for orch/handoff/audit but **holes** on writebacks / core DCS HTTP / team | Cannot honestly say “verified” |

**Honest claim after SEC-01:**  
“RBAC role gates and company-scoped API isolation verified with automated evidence; audit chain + DB immutability evidenced; internal security review packet complete.”  

**Not:** “Third-party pen-test passed” · “SOC2” · “DP1 live” · “Grafana proves security.”

---

## 2. Contract M3 — point to point (SEC slice only)

| # | Contract wording (M3) | Today | This PRD closes |
|---|----------------------|-------|-----------------|
| M3-S1 | Security + observability hardened (**RBAC**, **audit tamper detection**, Grafana) | Grafana = OBS-01; audit chain exists; RBAC gates scattered | **YES** — RBAC matrix + evidence; audit evidence packaged; **not** Grafana |
| M3-S2 | **Security review passed; tenant isolation verified** | No packet; incomplete isolation suite | **YES** — packet + automated isolation/RBAC suite |
| M3-O1 | Grafana | OBS-01 | **NO** — already separate |
| M3-D1 | Demo / DP1 live | Separate | **NO** — M3-DEMO-01 |

OBS-01 §2 / §14 already named this PRD as the security follow-on.

---

## 3. Reuse inventory (do not rebuild)

### 3.1 Roles & auth

| Control | Path |
|---------|------|
| `User.Role` = `admin` / `analyst` / `viewer` | `tenants/models.py` |
| Default API auth `IsAuthenticated` | `core/settings/base.py` |
| Product “admin” = `user.role == User.Role.ADMIN` (not Django `IsAdminUser`) | various views |
| Per-module role allowlists | writebacks, orch, audit, DCS, connectors, team, workspace |

### 3.2 Tenant / company scoping

| Control | Path |
|---------|------|
| `User.tenant` FK + invites | `tenants/models.py` |
| `get_user_company(user)` — first company for tenant by `created_at` | `tenants/auth/services.py` |
| Company filters on orch / handoff / audit / reports / search / … | `dataruns/**` |
| Connector cross-tenant uniqueness | `tenants/connector_uniqueness.py` + tests |

### 3.3 Audit tamper detection (DONE — package evidence only)

| Control | Path |
|---------|------|
| Hash chain + `verify_audit_chain_for_company` | `dataruns/audit.py` |
| `manage.py verify_audit_chain` | `dataruns/management/commands/verify_audit_chain.py` |
| DB immutability triggers | `dataruns/migrations/0030_audit_logs_immutability_triggers.py` |
| Tests | `dataruns/tests/test_audit.py`, `test_audit_immutability.py` |

### 3.4 Existing isolation / role tests (extend, don’t duplicate blindly)

| Area | Paths (examples) |
|------|------------------|
| Audit | `dataruns/tests/test_audit.py` |
| Orch SM | `test_orch_sm_phase2.py`, `test_orch_sm_phase3.py` |
| Handoff | `test_handoff_ho02_phase*`, `test_handoff_package_step*` |
| Search / pilots / reports / AI | respective `test_*.py` |
| Connectors | `tenants/tests/test_connector_*.py` |

**Known holes (must close):** writeback HTTP cross-company; core DCS status/worklist/history object APIs; team member cross-tenant negatives; global `TenantViewSet` / `DataRunViewSet`.

### 3.5 Known review findings to fix

| Finding | Path | Required fix |
|---------|------|--------------|
| Lists all tenants | `tenants/views.py` `TenantViewSet` → `Tenant.objects.all()` | Scope to caller’s tenant **or** remove from public API |
| Lists all data runs (optional `?tenant=` only) | `dataruns/views.py` `DataRunViewSet` | Force caller tenant/company scope; deny foreign |

---

## 4. Architecture of the evidence pack

```text
┌──────────────────────────────────────────────────────────────────┐
│ SEC-01 deliverables                                              │
│                                                                  │
│  docs/security/M3_SEC_01_RBAC_MATRIX.md                          │
│  docs/security/M3_SEC_01_SECURITY_REVIEW_PACKET.md               │
│                                                                  │
│  tests:                                                          │
│    dataruns/tests/test_m3_sec01_tenant_isolation.py              │
│    dataruns/tests/test_m3_sec01_rbac_negatives.py                │
│    tenants/tests/test_m3_sec01_*.py (team/connectors/views)      │
│    (+ extend existing modules where cleaner)                     │
│                                                                  │
│  scripts/verify_m3_sec01_backend.py  ──static gate──► CI / PR    │
│                                                                  │
│  Reused runtime controls (unchanged unless hole found):          │
│    User.Role · get_user_company · audit chain · 0030 triggers    │
└──────────────────────────────────────────────────────────────────┘
```

API families to inventory (from `core/urls.py`):

| Prefix | App |
|--------|-----|
| `/api/v1/auth/` | tenants auth |
| `/api/v1/tenants/` | tenants |
| `/api/v1/team/` | team |
| `/api/v1/connectors/` | connectors |
| `/api/v1/dataruns/` | data runs |
| `/api/v1/dcs/` | DCS |
| `/api/v1/writebacks/` | writebacks |
| `/api/v1/architecture/` | lifecycle / AF |
| `/api/v1/use-cases/` | pilots / UC |
| `/api/v1/build-packages/` | studio packages |
| `/api/v1/capabilities/` | CAP matrix |
| `/api/v1/qa-runs/` | QA |
| `/api/v1/handoffs/` | handoff |
| `/api/v1/orchestration/` | orch SM |
| `/api/v1/assessment-reports/` | reports |
| `/api/v1/ai/` | AI suggestions |
| `/api/v1/audit/` | audit |
| `/api/v1/search/` | search |
| `/health/` | public health (no tenant data) |
| `/ops/m3-obs-01/*` | ops induce (token-gated; document as ops surface) |

---

## 5. Deliverables (code-level)

### 5.1 RBAC matrix

**File:** `docs/security/M3_SEC_01_RBAC_MATRIX.md`

For **every** `/api/v1/*` family, a table:

| Surface / method | Admin | Analyst | Viewer | Notes / code gate |
|------------------|-------|---------|--------|-------------------|
| … | R/W / — | … | … | path to role check |

Rules:
- Match **existing** product behaviour unless a gate is missing (then add the gate + test).
- Mutating surfaces must not be Viewer-writable.
- Document Django `/admin/` as staff/superuser (separate from product `User.Role`).

### 5.2 Tenant isolation suite

**Primary file:** `dataruns/tests/test_m3_sec01_tenant_isolation.py`  
**Also:** `tenants/tests/test_m3_sec01_tenant_isolation.py` for team / connectors / tenant views.

Pattern (required):

1. Create **Company A** + Admin A; **Company B** + Admin B (separate tenants).  
2. Create object under A (writeback job, DCS run artifact, connector, team user, orch task, handoff, audit event, report, …).  
3. As B: `GET/PATCH/POST` with A’s id → **404** (preferred) or **403**.  
4. As B: list endpoints → **zero** A rows.

**Minimum allowlist** (must all be covered by new or existing tests cited in the packet):

| Family | Examples |
|--------|----------|
| Writebacks | job detail, approve/execute paths that take ids |
| DCS | status / history / worklist detail if id-scoped |
| Connectors | get/update/delete foreign connector |
| Team | list/patch foreign user id |
| Audit | list/mark-read foreign company events |
| Orchestration | task get/transition foreign id |
| Handoff | package / send status foreign id |
| QA / build-packages / use-cases | foreign package or run ids where applicable |
| Reports / AI / search | foreign ids or company bleed |
| Tenants / DataRuns ViewSets | after harden |

### 5.3 RBAC negatives

**File:** `dataruns/tests/test_m3_sec01_rbac_negatives.py` (+ tenants tests as needed)

For each **mutating** matrix row:
- Viewer (or wrong role) → **403**
- Unauthenticated → **401**

Reuse existing orch/writeback role tests where they already prove the gate; cite them in the packet instead of duplicating.

### 5.4 ViewSet harden

| ViewSet | Action |
|---------|--------|
| `TenantViewSet` | `get_queryset` → caller’s tenant only; detail of other tenant → 404; **or** unregister from router if unused by FE |
| `DataRunViewSet` | Always filter to caller’s tenant; ignore/forbid foreign `?tenant=` override |

Tests required for whichever option is chosen.

### 5.5 Verify script

**File:** `scripts/verify_m3_sec01_backend.py`  
**Template:** `scripts/verify_m3_obs01_backend.py`

Must assert (static / importable):

1. Packet + RBAC matrix files exist under `docs/security/`  
2. Isolation + RBAC test modules exist  
3. Critical helpers still present (`get_user_company`, `verify_audit_chain`, migration `0030`)  
4. `TenantViewSet` / `DataRunViewSet` no longer use unscoped `.all()` without tenant filter (AST or source grep)  
5. Theater register: packet must contain strings like `pen-test` / `SOC2` / `DP1` only in **out-of-scope / do-not-claim** sections  
6. Exit **0** on PASS

Wire into PR checklist; optional: mention in deploy docs (not required on every web boot).

### 5.6 Security review packet

**File:** `docs/security/M3_SEC_01_SECURITY_REVIEW_PACKET.md`

Sections (required):

1. **Executive summary** — what was reviewed; honest claim language  
2. **Control inventory** — reuse table from §3 with “evidenced by” links (tests / verify / commands)  
3. **RBAC summary** — pointer to matrix  
4. **Isolation summary** — pointer to suite + command to run tests  
5. **Audit tamper detection** — how to run `manage.py verify_audit_chain --company-id …`; immutability tests  
6. **Findings fixed in this PR** — ViewSets, any missing gates  
7. **Residual risks** (must include):  
   - `get_user_company` = first company by `created_at` (multi-company-per-tenant not productized)  
   - Grafana ops admin ≠ product RBAC  
   - Django `/admin/` is staff path  
   - Track B MCP still Client-blocked  
8. **Theater register** — do **not** claim pen-test, SOC2, DP1, “Grafana = security review”  
9. **Employer checklist** — copy of §11 with checkboxes for PR paste  

### 5.7 Secret / metadata hygiene spot-check

- Connector list/detail responses still mask `SECRET_CONFIG_FIELDS` (`tenants/crypto.py`) — test or cite existing.  
- Audit metadata sanitization still applied — cite `test_audit*`.

---

## 6. Phases (OBS-style)

| Phase | Focus | Exit |
|-------|--------|------|
| **0 — Lock** | Inventory APIs from `core/urls.py`; map existing role constants + isolation tests; branch; fill PHASE_0 | Gap list locked; no scope creep |
| **1 — RBAC matrix** | Author `M3_SEC_01_RBAC_MATRIX.md`; stub verify asserts for matrix file | Matrix complete for all families |
| **2 — Isolation suite** | Cross-company tests for allowlist; close writeback/DCS/team holes | Isolation tests green |
| **3 — ViewSet harden** | Fix `TenantViewSet` + `DataRunViewSet`; negatives | No global list leak |
| **4 — RBAC negatives + audit evidence** | Wrong-role 403s; packet audit section; verify_audit_chain cited | Role + audit evidence packable |
| **5 — Packet + verify complete** | Full `verify_m3_sec01_backend.py` + review packet + residual risks | Static gate PASS |
| **6 — Employer acceptance** | Run §11 checklist; paste evidence in PR; ready for Rohan review | PR mergeable |

Phase note files (create/update as you go):

- `docs/sahil/M3_SEC_01_PHASE_0.md` … `M3_SEC_01_PHASE_6.md`

---

## 7. Phase 0 detail (start here)

1. Branch: `feature/m3-sec-01-rbac-isolation-packet`  
2. Walk `core/urls.py` includes → list every router ViewSet / APIView.  
3. Spreadsheet or markdown draft of matrix rows (can live in PHASE_0 until Phase 1 file).  
4. Grep for existing isolation tests; mark **covered** vs **missing** in WORKING_GAPS.  
5. Confirm `TenantViewSet` / `DataRunViewSet` still unscoped (re-verify).  
6. Stop-and-flag if FE depends on listing all tenants/runs — do not silently break; propose scoped contract.

---

## 8. Phase 2–3 detail (highest risk code)

### Isolation fixture helper (recommended)

```python
# Sketch only — put under dataruns/tests/helpers or inline
# company_a, user_a_admin, client_a
# company_b, user_b_admin, client_b
```

Prefer **APIClient** authenticated as each user. Prefer **404** over 403 for foreign object ids (do not leak existence) unless an endpoint already returns 403 consistently — then document and keep consistent.

### ViewSet harden acceptance

```text
As authenticated user of tenant T1:
  GET /api/v1/tenants/          → only T1 (or 404/empty for others)
  GET /api/v1/tenants/{t2_id}/  → 404
  GET /api/v1/dataruns/         → only T1 runs
  GET /api/v1/dataruns/?tenant={t2_slug} → must NOT return T2 runs
```

---

## 9. Verify script outline

```text
OPS — verify M3-SEC-01

[ ] docs/security/M3_SEC_01_RBAC_MATRIX.md
[ ] docs/security/M3_SEC_01_SECURITY_REVIEW_PACKET.md
[ ] test_m3_sec01_tenant_isolation modules present
[ ] test_m3_sec01_rbac_negatives modules present
[ ] get_user_company importable
[ ] verify_audit_chain command module present
[ ] migration 0030 present
[ ] TenantViewSet / DataRunViewSet scoped (source check)
[ ] packet contains theater register (do-not-claim)

PASS / FAIL
```

Run:

```bash
python scripts/verify_m3_sec01_backend.py
python manage.py test dataruns.tests.test_m3_sec01_tenant_isolation dataruns.tests.test_m3_sec01_rbac_negatives tenants.tests.test_m3_sec01_tenant_isolation --keepdb
```

---

## 10. Theater register (forbidden claims)

Do **not** write in PR / packet / M3 claim:

| Forbidden | Why |
|-----------|-----|
| “Pen-test passed” | No external firm in this PRD |
| “SOC2 / ISO certified” | Out of scope |
| “Security review passed” **without** linking this packet + green verify | Hollow |
| “Tenant isolation verified” **without** citing isolation suite | Hollow |
| “Grafana proves RBAC / isolation” | OBS ≠ SEC |
| “MCP / Track B live” | Client-blocked |
| “DP1 live” | M3-DEMO-01 |

Allowed after §11:

> Internal M3-SEC-01 security review packet complete; RBAC matrix and automated cross-tenant / role-negative tests green; audit tamper-detection controls evidenced (hash chain + DB immutability).

---

## 11. Employer acceptance checklist (paste on PR)

### M3-SEC-01 employer acceptance (§11)

- [ ] **A1** — `M3_SEC_01_RBAC_MATRIX.md` covers every `/api/v1/*` family from `core/urls.py`  
- [ ] **A2** — Cross-tenant suite green (writebacks + DCS + connectors + team + audit + orch + handoff minimum)  
- [ ] **A3** — RBAC negatives green on mutating surfaces (Viewer/wrong-role → 403; unauth → 401)  
- [ ] **A4** — `TenantViewSet` / `DataRunViewSet` no longer leak other tenants’ data (tests prove)  
- [ ] **A5** — `python scripts/verify_m3_sec01_backend.py` → PASS  
- [ ] **A6** — Audit evidence section documents `verify_audit_chain` + `0030` + immutability tests  
- [ ] **A7** — Security review packet includes residual risks + theater register  
- [ ] **A8** — Secret masking / audit sanitization cited or tested  
- [ ] **A9** — PR does **not** claim pen-test / SOC2 / DP1 / Grafana-as-security  
- [ ] **A10** — WORKING_GAPS + phase notes updated; Rohan review requested  

**Test evidence:** paste commands + PASS lines  

**Packet paths:**  
- `docs/security/M3_SEC_01_RBAC_MATRIX.md`  
- `docs/security/M3_SEC_01_SECURITY_REVIEW_PACKET.md`  

---

## 12. PR / branch hygiene

| Item | Value |
|------|-------|
| Branch | `feature/m3-sec-01-rbac-isolation-packet` |
| PR title | `feat(M3-SEC-01): RBAC matrix, tenant isolation evidence, security packet` |
| PR body must state | Evidence + harden · reuse AUDIT-01 · no Grafana · no pen-test claim · verify script PASS |
| Review | Rohan — matrix honesty, ViewSet fix, isolation allowlist coverage, claim language |
| Merge | Single BE PR preferred. No FE PR unless a proven FE hole. |

---

## 13. Follow-ons (do not expand this PRD)

| ID | Topic |
|----|--------|
| **M3-OBS-01 Phase 6** | Staging induce / alert email / OBS §11 (ops/Rohan) |
| **M3-OBS-02** | Prometheus / RED (optional) |
| **M3-DEMO-01** | Demo env + DP1 readiness — [PRD](./PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md) |
| GAP-01 Slice B | Track B MCP (Client-blocked) |
| Optional | Celery Beat periodic `verify_audit_chain` (v1.1) |

---

## 14. Definition of done

SEC-01 is **done** when:

1. All Phase 0–5 exits met  
2. `verify_m3_sec01_backend.py` PASS  
3. Isolation + RBAC test suites green in CI / local  
4. §11 checklist pasteable with evidence  
5. Honest claim language (§1 / §10) used in PR — nothing from theater register  

---

## 15. Relationship to T3

| T3 need | Owner after this PRD |
|---------|----------------------|
| Grafana observability | M3-OBS-01 (live; Phase 6 closeout) |
| Security review + tenant isolation | **This PRD** |
| Oct demo / DP1 | M3-DEMO-01 (later) |
| SM MCP/A2A live | Client-blocked |

SEC-01 alone does **not** complete all of M3 — it closes the **security AC / M3-S1 evidence** gap so T3 is not blocked on “isolation unverified.”

---

*PRD-M3-SEC-01 · Employer SoT for Sahil M3 security slice · 2026-09-11*
