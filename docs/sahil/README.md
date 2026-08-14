# Sahil PRD series

Implementation contracts owned on the Sahil track (foundation checks, scrapers, executors, DCS money impact, architecture assessment, use-case library / pilots, orchestration priority, full assessment report PDF).

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

## Corrected check IDs (employer)

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
