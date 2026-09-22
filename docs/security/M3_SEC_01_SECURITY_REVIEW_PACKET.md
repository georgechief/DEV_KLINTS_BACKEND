# M3-SEC-01 — Security review packet

**PRD:** [PRD_M3_SEC_01_RBAC_ISOLATION_SECURITY_PACKET.md](../sahil/PRD_M3_SEC_01_RBAC_ISOLATION_SECURITY_PACKET.md)  
**Date:** 2026-09-11  
**Branch:** `feature/m3-sec-01-rbac-isolation-packet`  
**Scope:** Internal evidence pack + targeted harden for product RBAC, tenant isolation, and audit tamper-detection packaging.

---

## 1. Executive summary

This packet documents an **internal** M3-SEC-01 security review of the Klints backend product API:

- Product roles remain `User.Role` = Admin / Analyst / Viewer (no new role system).
- Cross-tenant isolation is evidenced by automated A-vs-B suites.
- Mutating surfaces are evidenced by Viewer / wrong-role → 403 and unauth → 401 negatives.
- `TenantViewSet` / `DataRunViewSet` global list leaks were closed.
- Audit hash-chain + DB immutability (`0030`) are packaged as evidence (runtime already existed).

**Honest claim language (allowed after §11):**

> Internal M3-SEC-01 security review packet complete; RBAC matrix and automated cross-tenant / role-negative tests green; audit tamper-detection controls evidenced (hash chain + DB immutability).

This is **not** an external pen-test, **not** SOC2 / ISO certification, **not** DP1 demo readiness, and **not** a claim that Grafana/Loki equals security review.

---

## 2. Control inventory

| Control | Location | Evidenced by |
|---------|----------|--------------|
| Product roles Admin / Analyst / Viewer | `tenants/models.py` `User.Role` | [RBAC matrix](./M3_SEC_01_RBAC_MATRIX.md) |
| Default API auth `IsAuthenticated` | `core/settings/base.py` | Matrix + RBAC negatives (401) |
| Product admin = `user.role == ADMIN` (not Django `IsAdminUser`) | views across apps | Matrix notes + RBAC suite |
| Per-module role allowlists | writebacks, orch, DCS, connectors, team, workspace, … | Matrix + `test_m3_sec01_rbac_negatives.py` + cited module tests |
| `User.tenant` FK + invites | `tenants/models.py` | Isolation suites |
| `get_user_company(user)` | `tenants/auth/services.py` | Verify script + residual risks |
| Company filters on product APIs | `dataruns/**`, `tenants/**` | Isolation suites + cited tests |
| Connector cross-tenant uniqueness | `tenants/connector_uniqueness.py` | Existing connector tests (cited) |
| Audit hash chain | `dataruns/audit.py` `verify_audit_chain_for_company` | [Audit evidence](./M3_SEC_01_AUDIT_EVIDENCE.md) |
| `manage.py verify_audit_chain` | `dataruns/management/commands/verify_audit_chain.py` | Audit evidence + verify script |
| DB immutability triggers | migration `0030_audit_logs_immutability_triggers` | `test_audit_immutability.py` |
| Secret config masking | `tenants/crypto.py` `SECRET_CONFIG_FIELDS` | Audit evidence § hygiene + `test_manago_api_v3_key.py` |
| Audit metadata sanitization | `dataruns/audit.py` | `test_audit.py::test_sanitize_metadata_strips_secrets` |
| Static gate | `scripts/verify_m3_sec01_backend.py` | Exit 0 = PASS |

---

## 3. RBAC summary

Full Admin / Analyst / Viewer × surface matrix:

→ **[M3_SEC_01_RBAC_MATRIX.md](./M3_SEC_01_RBAC_MATRIX.md)**

Phase notes: [M3_SEC_01_PHASE_1.md](../sahil/M3_SEC_01_PHASE_1.md), [M3_SEC_01_PHASE_4.md](../sahil/M3_SEC_01_PHASE_4.md).

**Negatives command:**

```bash
python manage.py test dataruns.tests.test_m3_sec01_rbac_negatives --keepdb
```

---

## 4. Isolation summary

Cross-company (Company A vs Company B) suites:

| Module | Focus |
|--------|-------|
| `dataruns/tests/test_m3_sec01_tenant_isolation.py` | Writebacks, DCS, architecture, AI |
| `tenants/tests/test_m3_sec01_tenant_isolation.py` | Team, connectors, Tenant/DataRun ViewSets |

Additional families cited (not rebuilt): orch, handoff, QA/build-packages, audit, reports, search, pilot-gates — see [WORKING_GAPS](../sahil/M3_SEC_01_WORKING_GAPS.md) “Covered elsewhere”.

**Isolation command:**

```bash
python manage.py test dataruns.tests.test_m3_sec01_tenant_isolation tenants.tests.test_m3_sec01_tenant_isolation --keepdb
```

**Combined SEC-01 suite:**

```bash
python manage.py test dataruns.tests.test_m3_sec01_tenant_isolation dataruns.tests.test_m3_sec01_rbac_negatives tenants.tests.test_m3_sec01_tenant_isolation --keepdb
```

---

## 5. Audit tamper detection

Packaged detail: **[M3_SEC_01_AUDIT_EVIDENCE.md](./M3_SEC_01_AUDIT_EVIDENCE.md)**

```bash
python manage.py verify_audit_chain --company-id <COMPANY_UUID>
```

| Piece | Path |
|-------|------|
| Hash helper | `dataruns/audit.py` → `verify_audit_chain_for_company` |
| Management command | `dataruns/management/commands/verify_audit_chain.py` |
| Immutability triggers | `dataruns/migrations/0030_audit_logs_immutability_triggers.py` |
| Tests | `dataruns/tests/test_audit.py`, `dataruns/tests/test_audit_immutability.py` |

`audit_read` remains mutable (mark-read); hash / business columns are protected.

---

## 6. Findings fixed in this PR

| ID | Finding | Fix |
|----|---------|-----|
| F1 | `TenantViewSet` listed all tenants | Scoped to caller `tenant_id`; create/destroy 403; update Admin-only; `slug`/`is_active` read-only |
| F2 | `DataRunViewSet` foreign `?tenant=` leak | Always filter caller tenant; ignore `?tenant=`; force tenant on create/update; `tenant_slug` read-only |
| F-run | `WritebackRunView` taught payload/action shape before role | **Viewer denied first** (before action-name validation); then wrong-role gates before `_missing_run_keys` (→ 403, not 400) |

Evidence: Phase 3–4 notes + isolation / RBAC suites + verify source checks (Viewer-before-action + Viewer-before-keys).

**2026-09-12 deep recheck (Steps 1–6):** ViewSet isolation OK; DataRun UUID/`PUT`/status probes locked; RBAC suite extended (bootstrap, Manago owners, api-v3-key, Analyst tenant create/destroy); writeback Viewer-before-action; execute isolation assert = 400/403/404 only; SEC-01 combined suites **83 OK**; verify **PASS**.

---

## 7. Residual risks

Must remain visible (not “fixed away” by documentation):

1. **`get_user_company`** returns the first company for the user’s tenant ordered by `created_at`. Multi-company-per-tenant is **not** productized — do not claim per-company RBAC beyond that helper.
2. **Grafana / Loki (M3-OBS-01)** is ops observability. Grafana ops admin ≠ product `User.Role` RBAC. Observability does **not** prove isolation or RBAC.
3. **Django `/admin/`** is a staff/superuser path, separate from product Admin / Analyst / Viewer.
4. **Track B MCP** remains Client-blocked — do not claim MCP live.
5. **`POST /connectors/verify/`** has no product role gate (matrix F3) — authenticated users can call verify; document as residual / optional harden.
6. **Intentional Viewer writes** (QA run, AI suggest POSTs, audit mark-read) match product PRDs — not treated as RBAC holes.
7. **Audit verify command** is ops/manual — not continuous SIEM monitoring.

---

## 8. Theater register (do not claim)

Out of scope for this packet / PR / M3 claim language. Do **not** claim:

| Forbidden claim | Why |
|-----------------|-----|
| Pen-test passed / external pen-test | No external firm engagement in this PRD |
| SOC2 / ISO certified | Out of scope |
| “Security review passed” without linking this packet + green verify | Hollow |
| “Tenant isolation verified” without citing isolation suite | Hollow |
| Grafana proves RBAC / isolation | OBS ≠ SEC |
| MCP / Track B live | Client-blocked |
| DP1 live | Belongs to M3-DEMO-01 |

**Allowed** (only after employer §11): the executive-summary sentence in §1.

---

## 9. Employer checklist (PR paste — §11)

### M3-SEC-01 employer acceptance (§11)

Evidence captured in [M3_SEC_01_PHASE_6.md](../sahil/M3_SEC_01_PHASE_6.md): verify **PASS**; SEC-01 suites **83 OK** (2026-09-12 deep recheck). A2 = new isolation suites + cited orch/handoff/audit modules (see PHASE_6 A2 map).

- [x] **A1** — `M3_SEC_01_RBAC_MATRIX.md` covers every `/api/v1/*` family from `core/urls.py`
- [x] **A2** — Cross-tenant suite green (writebacks + DCS + connectors + team + audit + orch + handoff minimum)
- [x] **A3** — RBAC negatives green on mutating surfaces (Viewer/wrong-role → 403; unauth → 401)
- [x] **A4** — `TenantViewSet` / `DataRunViewSet` no longer leak other tenants’ data (tests prove)
- [x] **A5** — `python scripts/verify_m3_sec01_backend.py` → PASS
- [x] **A6** — Audit evidence section documents `verify_audit_chain` + `0030` + immutability tests
- [x] **A7** — Security review packet includes residual risks + theater register
- [x] **A8** — Secret masking / audit sanitization cited or tested
- [x] **A9** — PR paste does **not** claim pen-test / SOC2 / DP1 / Grafana-as-security *(confirm on open)*
- [x] **A10** — WORKING_GAPS + phase notes updated; Rohan review requested *(docs [x]; Rohan [ ] after push)*

**Test evidence:** paste commands + PASS lines

```bash
python scripts/verify_m3_sec01_backend.py
python manage.py test dataruns.tests.test_m3_sec01_tenant_isolation dataruns.tests.test_m3_sec01_rbac_negatives tenants.tests.test_m3_sec01_tenant_isolation --keepdb
```

**Packet paths:**

- `docs/security/M3_SEC_01_RBAC_MATRIX.md`
- `docs/security/M3_SEC_01_SECURITY_REVIEW_PACKET.md`
- `docs/security/M3_SEC_01_AUDIT_EVIDENCE.md`
