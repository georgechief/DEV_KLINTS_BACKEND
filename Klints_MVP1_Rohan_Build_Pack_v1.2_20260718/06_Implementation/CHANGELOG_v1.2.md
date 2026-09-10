# Changelog — Build Pack v1.2

- Restored end-to-end implementation traceability for the downloadable Assessment Report.
- Added REPORT and EXPORT orchestration tasks, a dedicated workbook contract sheet, report schema, OpenAPI contract and golden fixtures.
- Restored the canonical v1.3 priority formula and removed the conflicting 0–100 formula.
- Corrected wave scheduling so dependencies can execute in deterministic order inside one wave.
- Repaired blank Lumera worked-example rows caused by inherited merged cells.
- Added 12 on-demand pilot preflight gates missing from the 42-check headline scope.
- Added machine schemas for DCS run, capability record, approval token, QA result and handoff package.
- Replaced Check IDs incorrectly stored as blueprint required fields with canonical data-field names.
- Split specification validation from backend execution status; no unexecuted backend test is labelled PASS.
- Added Requirements Traceability Matrix and corrective defect log.
