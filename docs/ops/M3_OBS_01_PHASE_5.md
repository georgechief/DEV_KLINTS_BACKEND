# M3-OBS-01 — Phase 5 notes (workflow + verify + runbook)

**Date:** 2026-09-08  
**Branch:** `feature/m3-obs-01-grafana-loki-alloy`  
**Depends on:** Phase 0–4  

## What landed

### 5.1 Workflow smoke
After existing HTTPS `/health/` smoke, `deploy-development.yml` adds **M3-OBS-01 smoke**:

1. `https://$DOMAIN/grafana/api/health` → 200 **and** body contains `database` / `ok` (retry)
2. `https://$DOMAIN/grafana/login` → 200 **with** login markers; `/grafana/explore` must not be anonymously open
3. Loki `http://loki:3100/ready` via `web` Python `urllib` (grafana wget fallback)

Fails the job (with compose ps/logs) if obs stack is down.

### Deep-check fixes (2026-09-08)
- Health JSON validated (not status-only)
- Login + Explore auth-gate checks
- Loki probe uses `web` container Python (Grafana image toolset unreliable)
- Verify asserts `/health/` still present and ordered before OBS smoke
- Runbook common failures include SMTP/mailer wording (PRD §13)

### 5.2 Verify script
`scripts/verify_m3_obs01_backend.py` — Phase 1–5 static gate (workflow smoke strings, runbook, README row).

```bash
python scripts/verify_m3_obs01_backend.py
```

### 5.3 Runbook
`docs/ops/M3_OBS_01_RUNBOOK.md` — login, Explore, alerts/silence, deploy path, common failures, non-claims.

### 5.4 README
`docs/ops/README.md` build-order row 20 links Phase 0–5 + runbook.

## Validate

```bash
python scripts/verify_m3_obs01_backend.py
```

Live deploy proof = merge to `main` (or `workflow_dispatch`) and green Actions (Phase 6).

## Next

Phase 6 — staging induce ERROR under `service=web` + employer checklist.
