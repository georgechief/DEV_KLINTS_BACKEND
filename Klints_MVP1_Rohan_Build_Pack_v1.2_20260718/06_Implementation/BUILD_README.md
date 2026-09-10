# Klints MVP1 — Rohan Build Pack

Release: 1.2 / 18 July 2026
Specification version: v1.4.1

## Read this first

This package is a corrected implementation contract. It supersedes Build Pack v1.1 but does not overwrite it. The package has passed specification-level traceability and structural QA with the verdict **PASS WITH RESIDUAL EXTERNAL RISKS**. This is not a claim that the backend or live Manago/MCP integration has passed; those statuses are explicitly NOT_RUN or BLOCKED_EXTERNAL in the acceptance matrix.

## Authoritative order

1. JSON Schemas and the report OpenAPI contract define machine structure.
2. DCS v1.4.1 defines the 42-check headline score plus 12 on-demand pilot preflight gates.
3. Architecture v1.4.1 defines evidence, dependencies and verdicts.
4. Use Case Library v1.4.1 and pilot_manifest.json define the exact 16 pilots.
5. Individual blueprint JSON files are authoritative for workflow builds.
6. Capability Matrix v1.1 resolves Manago MCP, Agent, REST, SDK, callback, Klints backend and human fallbacks.
7. Orchestration v1.4.1 defines canonical priority, task order, REPORT/EXPORT, approvals, waves and handoff.
8. Requirements Traceability Matrix proves the chain from source requirement to acceptance test.

## Corrected reporting contract

REPORT composes a governed payload from immutable DCS and architecture snapshots. EXPORT renders PDF/JSON from that same payload. Free, paid and living variants, content locking, incomplete-state behavior, versioning, hashing, tenant isolation, PII minimization, storage/retention, API behavior and retry/idempotency are defined in Orchestration sheet 10, assessment_report.schema.json and assessment_report_api.openapi.json.

## DCS scope clarification

The headline score remains exactly 42 checks: 28 RULE_BASED + 14 DRIFT/FRESHNESS. Twelve additional checks required by the 16 pilots run only as workflow-specific preflight gates. They do not change the headline score; a failure blocks only the dependent pilot.

## Important MCP rule

Manago MCP was newly launched but absent from the supplied Manago documentation. MCP operations remain DISCOVERY_REQUIRED until Rohan stores executed evidence. Read-only discovery precedes any sandbox write test. Every core pilot retains a human fallback; no MCP capability is inferred from the workbooks.

## Build sequence

Follow implementation_backlog_v1.2.xlsx: contracts → headline and supplemental DCS checks → connectors/capability resolver → architecture → pilot registry → canonical orchestrator → report composition/export/security → build guides/approvals/QA → Lumera end to end → signed release.

## Stop-and-flag rule

If code, the tenant, Manago, MCP or the source workbooks disagree with this package, stop before implementing the disputed behavior. Record the exact artifact, ID, expected/observed behavior, proposed resolution and affected tests. George/Klints decides the contract change; do not silently choose an interpretation.
