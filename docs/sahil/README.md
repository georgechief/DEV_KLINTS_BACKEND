# Sahil PRD series

Implementation contracts owned on the Sahil track (foundation through M2 GAP-01, M3-OBS-01 Grafana stack, M3-SEC-01 security packet, **M3-OBS-01B Grafana alert closeout**, **M3-DEMO-01 live Shopify klints-dev sample data**).

## Build order

| # | File | Delivers |
|---|------|----------|
| 1 | [PRD_FD_03_COMPANY_WEBSITE_MANAGO_TRACKER.md](./PRD_FD_03_COMPANY_WEBSITE_MANAGO_TRACKER.md) | **Website scrape content → implement as FD-07** (filename kept; check ID corrected by employer). FD-03 stays ERP + `isOptional`. |
| 2 | [PRD_DCS_08_REVENUE_IMPACT.md](./PRD_DCS_08_REVENUE_IMPACT.md) | Per-check `revenue_impact` for LE-05/09/04, PT-04 (+ LE-02 alias); deduped run rollup; clear formulas |
| 3 | [PRD_AF_01_ARCHITECTURE_ASSESSMENT.md](./PRD_AF_01_ARCHITECTURE_ASSESSMENT.md) | **BL-008 + BL-009** — Manago asset inventory, dependency graph, Keep/Improve/Fix-first/Consolidate/Retire + AUGMENT/REBUILD; auto after DCS; Lifecycle Q/Y = impact display only |
| 4 | [PRD_UC_01_USE_CASE_LIBRARY_AND_PILOTS.md](./PRD_UC_01_USE_CASE_LIBRARY_AND_PILOTS.md) | **BL-010 BE** — Seed 16 MVP1 pilots + blueprints; recommend via DCS gates + AF mode/WF-12 gaps |
| 5 | [PRD_UC_01B_OPPORTUNITIES_ORIGINAL_DESIGNS_RECONNECT.md](./PRD_UC_01B_OPPORTUNITIES_ORIGINAL_DESIGNS_RECONNECT.md) | **BL-010 FE correction** — Restore `original-designs` Opportunity **tracker** as primary; pilots secondary; AF gaps on `/lifecycle` |
| 6 | [PRD_ORCH_01_CANONICAL_PRIORITY.md](./PRD_ORCH_01_CANONICAL_PRIORITY.md) | **BL-011** — Four-factor priority + plan API **and FE bind** (Overview NBA, Data Center Plan sort, Opportunity Plan queue → Fix) |
| 7 | [PRD_RPT_01_FULL_ASSESSMENT_REPORT_PDF.md](./PRD_RPT_01_FULL_ASSESSMENT_REPORT_PDF.md) | **BL-013/014/015 (full)** — On-demand Assessment PDF (score, all checks, fix, AF, plan); stream only; payload retained; download audit **email · time · IP** |
| 8 | [PRD_RPT_01B_ASSESSMENT_PDF_POLISH.md](./PRD_RPT_01B_ASSESSMENT_PDF_POLISH.md) | Follow-up: populate What to fix; humanize copy; incomplete callout; richer tables; ReportLab visual polish |
| 9 | [PRD_AI_01_MISTRAL_NARRATIVE_AND_FIX_SUGGESTIONS.md](./PRD_AI_01_MISTRAL_NARRATIVE_AND_FIX_SUGGESTIONS.md) | **AI-01** — PrivacyGate + Mistral Small 4 JSON narratives; Fix AI suggestion box; persist all suggestions; LangSmith traces |
| 10 | [PRD_WF_01_WORKFLOW_BLUEPRINT_STUDIO.md](./PRD_WF_01_WORKFLOW_BLUEPRINT_STUDIO.md) | **BL-016 / WF-01** — Workflow Blueprint Studio: gates → ready pilot → build package (human fallback); UC-02 first; Data Consistency Build vs Fix rules |
| 11 | [PRD_WF_02_FIX_FLOW_STAGES_AND_CHECK_ROUTING.md](./PRD_WF_02_FIX_FLOW_STAGES_AND_CHECK_ROUTING.md) | **WF-02** — Journey stages + redirects; Fix Proceed only if check gates a UC; hide Studio CTA for CI-01/WB-SHOP-01; honest DCS Fix vs Build |
| 12 | [PRD_QA_01_WORKFLOW_QA_GATE_ENGINE.md](./PRD_QA_01_WORKFLOW_QA_GATE_ENGINE.md) | **BL-018 / QA-01** — Live `/qa` against build package; 7 pack hard_tests; score 0–100; PASS only if all hard PASS **and** ≥80; unlocks Handoff CTA (Send = next PRD) |
| 13 | [PRD_OPS_UC_01_SEED_MVP1_PILOTS_ON_DEPLOY.md](./PRD_OPS_UC_01_SEED_MVP1_PILOTS_ON_DEPLOY.md) | **OPS-UC-01 (P0)** ✅ — `ensure_runtime_catalogue` on deploy (DCS master if empty + pilots upsert); verify pilots + CheckMaster |
| 14 | [PRD_HO_01_HANDOFF_PACKAGE_BIND.md](./PRD_HO_01_HANDOFF_PACKAGE_BIND.md) | **HO-01 (P0)** — Persist staged `handoff_package` after QA PASS; live `/handoff` bind; Send stays disabled · progress: [HO_01_WORKING_GAPS.md](./HO_01_WORKING_GAPS.md) |
| 15 | [PRD_CAP_01_CAPABILITY_MATRIX_RESOLVER.md](./PRD_CAP_01_CAPABILITY_MATRIX_RESOLVER.md) | **CAP-01 (P0)** — Seed Capability Matrix registry; resolve package `route` MCP vs `HUMAN_FALLBACK`; GET capabilities; Studio/Handoff honesty (no Send) · Steps 0–11 done; Step 12 Ready · [CAP_01_WORKING_GAPS.md](./CAP_01_WORKING_GAPS.md) |
| 16 | [PRD_DCS_09_PILOT_SUPPLEMENTAL_GATES.md](./PRD_DCS_09_PILOT_SUPPLEMENTAL_GATES.md) | **DCS-09 (P0 M2)** — Evaluate 12 pack supplemental gates; merge into recommend so UC-02 can be **ready** (not forever provisional); never touch headline 42 · Steps 0–12 done; Step 13 Ready · [DCS_09_WORKING_GAPS.md](./DCS_09_WORKING_GAPS.md) |
| 17 | [PRD_DCS_10_FRESH_IMPORT_BEFORE_SCORE.md](./PRD_DCS_10_FRESH_IMPORT_BEFORE_SCORE.md) | **DCS-10 (P0 gap)** — Mandatory fresh Shopify/Manago import before every successful DCS score; fail closed · BE v1 Steps 0–4 · Slice D (FE) done · `verify_dcs10_fresh_import_backend.py` · `npm run verify:dcs10-fresh-import` · [DCS_10_WORKING_GAPS.md](./DCS_10_WORKING_GAPS.md) |
| 18 | [PRD_HO_02_HANDOFF_SEND_HUMAN_ACTIVATION.md](./PRD_HO_02_HANDOFF_SEND_HUMAN_ACTIVATION.md) | **HO-02 (P0 M2)** — Unlock Handoff Send with approval → `APPROVED_FOR_ACTIVATION` → confirm `ACTIVATED`; human Manago UI path (no MCP publish) |
| 19 | [PRD_GAP_01_M2_CODE_GAPS_WEEKS_5_9.md](./PRD_GAP_01_M2_CODE_GAPS_WEEKS_5_9.md) | **GAP-01 (P0 M2)** — Point-to-point code gaps Weeks 5–9 vs contract/pack/sheet; Slices A–F (8-state · Track B · CDUC honesty · MCP object · demo seed) |
| — | [GAP_01F_DEMO_PATH.md](./GAP_01F_DEMO_PATH.md) | **GAP-01F W9-04** — Offline demo seed + reset + UI path (connect→score→fix→studio→qa→handoff) |
| 20 | [PRD_M3_OBS_01_STAGING_GRAFANA_LOKI_ALLOY.md](./PRD_M3_OBS_01_STAGING_GRAFANA_LOKI_ALLOY.md) | **M3-OBS-01 (P0 M3)** — Staging-only free OSS Grafana + Loki + Alloy; per-Docker logs + separated alerts; deploy/test via `deploy-development.yml`; ops URL only · [RUNBOOK](./M3_OBS_01_RUNBOOK.md) · Phase 0–6: [PHASE_0](./M3_OBS_01_PHASE_0.md) · [PHASE_1](./M3_OBS_01_PHASE_1.md) · [PHASE_2](./M3_OBS_01_PHASE_2.md) · [PHASE_3](./M3_OBS_01_PHASE_3.md) · [PHASE_4](./M3_OBS_01_PHASE_4.md) · [PHASE_5](./M3_OBS_01_PHASE_5.md) · [PHASE_6](./M3_OBS_01_PHASE_6.md) |
| 21 | [PRD_M3_SEC_01_RBAC_ISOLATION_SECURITY_PACKET.md](./PRD_M3_SEC_01_RBAC_ISOLATION_SECURITY_PACKET.md) | **M3-SEC-01 (P0 M3)** ✅ — RBAC matrix + isolation packet (merged) |
| 22 | [PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md](./PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md) | **M3-OBS-01B (P0 M3)** — Grafana Phase 6: induce ERROR + alert email closeout · Sahil prep Phase 0–4 done; live A5/A7 ops pending · [WORKING_GAPS](./M3_OBS_01B_WORKING_GAPS.md) · [PHASE_0](./M3_OBS_01B_PHASE_0.md) · [PHASE_1](./M3_OBS_01B_PHASE_1.md) · [PHASE_2](./M3_OBS_01B_PHASE_2.md) · [PHASE_3](./M3_OBS_01B_PHASE_3.md) · [PHASE_4](./M3_OBS_01B_PHASE_4.md) · separate from demo |
| 23 | [PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md](./PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md) | **M3-DEMO-01 (P0 M3)** — Live Shopify **klints-dev** + Simple Sample Data → Klints import · **Sahil ship DONE** · staging A2/A10 residual · `verify_m3_demo01_backend.py` · [WORKING_GAPS](./M3_DEMO_01_WORKING_GAPS.md) · [PHASE_0](./M3_DEMO_01_PHASE_0.md)–[PHASE_6](./M3_DEMO_01_PHASE_6.md) · [SHOPIFY_PATH](./M3_DEMO_01_SHOPIFY_PATH.md) |

## Cross-track testing

- **[../CROSS_TRACK_TEST_LAST_5_PRDS.md](../CROSS_TRACK_TEST_LAST_5_PRDS.md)** — Sahil↔Maheep polish: last 5 PRDs each (common TCs TC-M* / TC-S*)

## Related

| Check | Work |
|-------|------|
| **FD-03** | ERP feed (Excel). Mark `isOptional=true` only. |
| **FD-07** | Manago tracking: Excel VISIT/smclient **and** website SalesManago scrape from this PRD. |

## Related

- Check master: `docs/dcs_scoring/CHECK_MASTER_42.md`
- Company website on signup: `docs/maheep/PRD_AUTH_01_SIGNUP_COMPANY_WEBSITE.md` (`Company.domain` / `company_domain`)
- Optional gate + app lock: `docs/maheep/PRD_FE_03_DCS_APP_LOCK.md` (`isOptional` on FD-03)
- Foundation gates overview: `docs/dcs_scoring/PRD_DCS_02_FOUNDATION_GATES.md`
- RULE checks (lifecycle/product joins this PRD consumes): `docs/dcs_scoring/PRD_DCS_04_RULE_BASED_CHECKS.md`
- Pack root: `Klints_MVP1_Rohan_Build_Pack_v1.2_20260718/` (in this repo)
- Architecture workbook: `…/01_Specifications/Klints_Spec_ArchitectureAssessmentFramework_v1.4.1_20260718.xlsx` (sheets **01–08**)
- Schemas: `…/03_Machine_Contracts/architecture_asset.schema.json`, `architecture_verdict.schema.json`
- Pilot gates (deferred): `docs/dcs_scoring/PRD_DCS_09_PILOT_SUPPLEMENTAL_GATES-FUTURE-PRD.md`
- AI patterns (reference only): `docs/AI_AGENT_ORCHESTRATION_BLUEPRINT.md`
- AI security boundary: `docs/security/KLINTS_AI_SECURITY_AND_DATA_PROCESSING_RESPONSE.md` §7
- Use Case Library pack: `…/01_Specifications/Klints_Spec_DefaultUseCaseLibrary_v1.4.1_20260718.xlsx`
- Pilots: `…/04_MVP1_Pilot_Blueprints/pilot_manifest.json` + `UC-*_blueprint.json`
- Blueprint schema: `…/03_Machine_Contracts/workflow_blueprint.schema.json`
- Orchestration: `…/01_Specifications/Klints_Spec_OnboardingOrchestrationBlueprint_v1.4.1_20260718.xlsx` · `orchestration_task.schema.json`
