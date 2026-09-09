# QA-01 Working / Gaps (PRD §12)

**PRD:** `PRD_QA_01_WORKFLOW_QA_GATE_ENGINE.md`  
**Branch intent:** `feature/qa-01-workflow-qa-engine`  
**Scope:** Build-package QA engine + live `/qa` + FlowStepper Handoff gate (not live MCP/A2A).

---

## Demo path — UC-02 (happy)

1. Fix / Opportunities → Workflow Studio `?uc=UC-02` (optionally `&issue=CC-03`).
2. Generate build package → note `package_id`.
3. Studio CTA → `/qa?uc=UC-02&package_id=…` (issue preserved when present).
4. `/qa` loads package; if never run → auto `POST …/build-packages/{id}/qa/`.
5. Expect: 7 hard tests PASS · score 100 · status PASS · audit `workflow.qa_run_completed`.
6. Continue to Handoff stub with `qa_run_id` in search; FlowStepper Handoff unlocked.
7. Re-run QA → new persisted row (append history); GET latest returns newest.

**Optional UC-06B:** Same path with `?uc=UC-06B` after a staged package exists for that pilot.

---

## Rights (done)

| §12 item | Evidence |
|----------|----------|
| POST QA schema + persist | `test_qa_api_step5` · `qa_run.run_qa_for_package` |
| All 7 pack hard_tests | `HARD_TEST_IDS` · `test_uc02_golden_all_seven_pass` |
| PASS iff all hard PASS **and** score ≥ min | `compute_qa_score` · `test_compute_score_*` |
| Any hard FAIL ⇒ overall FAIL | `test_compute_score_one_fail_still_overall_fail_even_if_ge_80` |
| Live `/qa` (no fixture primary) | `src/routes/qa.tsx` · no `getQaRunForIssue` |
| Re-run appends + refreshes | BE append history · FE `setQueryData` / Re-run |
| Handoff CTA only on PASS | `qa.tsx` · `isQaPass` |
| Studio → QA deep-link | `WorkflowStudio.tsx` `package_id` (+ `uc` / `issue`) |
| FlowStepper Handoff on PASS | `resolveFlowStepperStage` · tooltip §8.7 |
| Audit on run | `AUDIT_ACTION_QA_RUN_COMPLETED` |

---

## Gaps / defer (honest)

| Item | Status |
|------|--------|
| Live MCP / A2A Send on Handoff | HO-02 — Send locked in HO-01 |
| Persist full `handoff_package` + activation | HO-01 staged bind done; MCP/ACTIVATED = HO-02 |
| Force-PASS override | Never in MVP1 |
| Soft AI narrative of QA | Optional later |
| Handoff page fixture UI | Superseded by HO-01 live bind — see `HO_01_WORKING_GAPS.md` |
| Optional BE `verify_qa01` in CI | Script provided; wire into CI when ready |
| Post-audit fixes (GPT-5.6 Sol) | `terminal_reachable` fails dangling branches; empty `hard_tests: []` → 0/FAIL; migration `0027` status choices |

---

## PR note (paste)

**Right:** Package QA is live end-to-end for UC-02 — POST/GET persist schema-shaped results, seven pack hard tests, ≥80 gate with fail-closed hard FAIL, `/qa` bound to package (not fixtures), Re-run appends history, Handoff CTA + FlowStepper unlock only on PASS, audit `workflow.qa_run_completed`.

**Gap:** Handoff delivery is still a stub (no MCP/A2A send). Activation / full handoff_package is Handoff-01. No human force-PASS.
