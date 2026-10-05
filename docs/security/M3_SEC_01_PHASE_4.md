# M3-SEC-01 — Phase 4 notes (RBAC negatives + audit evidence)

**Date:** 2026-09-11  
**Branch:** `feature/m3-sec-01-rbac-isolation-packet`  
**Depends on:** Phase 3 complete  

## Goal

Wrong-role / unauth negatives on mutating surfaces + packable audit evidence (PRD §5.3 / Phase 4 exit).

## Checklist

| # | Task | Done |
|---|------|------|
| 4.1 | `make_sec01_role_clients` helper | [x] |
| 4.2 | `dataruns/tests/test_m3_sec01_rbac_negatives.py` | [x] |
| 4.3 | Audit evidence doc (`M3_SEC_01_AUDIT_EVIDENCE.md`) | [x] |
| 4.4 | Verify script: require RBAC module + audit helpers / `0030` / command | [x] |
| 4.5 | Cite existing role tests (do not duplicate) | [x] |
| 4.6 | Suites green | [x] |
| 4.7 | Deep recheck: `/writebacks/run/` role-before-keys; fill matrix mutate gaps | [x] |

## Deep-recheck fixes

| Gap | Fix |
|-----|-----|
| `WritebackRunView` validated required keys **before** role → wrong role got **400** | Role gate after parsing `action` (Phase 4) |
| Viewer missing/invalid `action` still got **400** (action-name leak) | **2026-09-12:** Viewer denied **before** action validation |
| Missing team member patch / invite resend-revoke | Added to SEC-01 RBAC suite |
| Missing writeback `/run/`, approval approve/reject, handoff reject | Added |
| Missing manago create/fetch, connector disconnect, handoff create | Added |
| Missing bootstrap / Manago owners / api-v3-key / Analyst tenant create-destroy in SEC-01 suite | **2026-09-12:** added to `test_m3_sec01_rbac_negatives` |
| Cite inventory incomplete; wrong doc cross-ref | Fixed below + audit hygiene cites |

## New coverage (`test_m3_sec01_rbac_negatives`)

Viewer → **403**, unauth → **401** (Analyst → **403** where Admin-only):

| Family | Surfaces |
|--------|----------|
| DCS | `POST /dcs/runs/`, pilot-gates evaluate |
| Writebacks | preview / execute / rollback / **run** (all actions + missing/invalid action) / approvals request / approve / reject |
| Architecture | `POST /assessments/` |
| Orchestration | create task / transition |
| Reports | compose / PDF |
| Use-cases / handoffs | build-package; package handoff create; approve / reject / confirm-activated |
| Auth workspace | `PATCH /auth/workspace/` |
| Team | member patch; invite create / resend / revoke |
| Connectors | create Manago; shopify start; shopify+manago fetch; disconnect; **bootstrap**; **Manago owners PUT**; **api-v3-key PUT/DELETE** |
| Tenants ViewSet | patch / create / destroy (Viewer + Analyst) |

## Cite inventory (reuse — do not rebuild)

| Gate | Evidence |
|------|----------|
| Orch Viewer mutate + Analyst Admin-only transitions | `test_orch_sm_phase2.py`, `test_orch_sm_phase3.py` |
| Writeback Analyst execute via `/run/` | `test_writeback_wb02.py`, `test_writeback_01c.py` |
| Handoff create / activate roles | `test_handoff_package_step4/6.py`, `test_handoff_ho02_phase2/3.py` |
| QA Viewer allowed (intentional) | `test_qa_api_step5.py` |
| Build-package Viewer blocked | `test_use_case_build_package.py` |
| Report compose / PDF Viewer blocked | `test_report_compose.py`, `test_report_pdf_download_audit.py` |
| Connector Manago owners / API key / disconnect / fetch | `test_manago_owners.py`, `test_manago_api_v3_key.py`, `test_connector_disconnect.py`, `test_connector_fetch.py` |
| Shopify start Viewer | `test_shopify_oauth.py` |
| Workspace Admin-only | `test_workspace.py` |
| Team invite non-admin | `test_team_invites.py` |
| Pilot-gates Viewer write | `test_pilot_gates_step7.py` |
| DCS runs Viewer | `test_dcs_runs_api.py` |
| Secret config masking | `test_manago_api_v3_key.py`, `tenants/crypto.py` `SECRET_CONFIG_FIELDS` |
| Audit chain + `0030` | [M3_SEC_01_AUDIT_EVIDENCE.md](../security/M3_SEC_01_AUDIT_EVIDENCE.md) |

## Audit evidence

- Doc: `docs/security/M3_SEC_01_AUDIT_EVIDENCE.md`
- Command: `manage.py verify_audit_chain --company-id …`
- Migration: `0030_audit_logs_immutability_triggers`
- Helper: `verify_audit_chain_for_company`

## Explicit non-goals this phase

- Full security review packet → **Phase 5**
- Harden `POST /connectors/verify/` (F3 — documented residual)
- Theater claims (pen-test / SOC2 / DP1)

## Exit

Phase 4 done when RBAC negatives green + audit evidence packable → start Phase 5 (packet + full verify).
