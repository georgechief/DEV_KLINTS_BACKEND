# M3-OBS-01B — Phase 2 notes (live induce + Explore)

**Date:** 2026-09-14  
**Branch:** `feature/m3-obs-01b-grafana-alert-closeout`  
**PRD:** [PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md](./PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md)  
**SoT steps:** [M3_OBS_01_PHASE_6.md](./M3_OBS_01_PHASE_6.md) · [M3_OBS_01_RUNBOOK.md](./M3_OBS_01_RUNBOOK.md) §7  

| Slice | Status |
|-------|--------|
| **Sahil (repo / prep)** | **DONE** (2026-09-14) |
| **Ops live (Rohan)** | **PENDING** — enable induce + run script + Explore marker |
| **PRD Phase 2 full close** | **NOT done** until A5 marker evidence exists |

## Goal

Prove controlled ERROR on staging: enable induce → fire marker → see it in Grafana Explore under `service=web` → note web alert pending/firing (no redis false-fire). **Email proof = Phase 3.**

## Ownership split

| Owner | Scope |
|-------|--------|
| **Sahil** | Induce path on `main`, verify/tests green, runbook accurate, Phase 2 checklist docs, Rohan handoff note |
| **Rohan / ops** | `DEV_ENV_FILE` / droplet `.env`, SSH on server, enable/disable induce, run droplet script (or hand Sahil evidence) |
| **Either** | Grafana Explore confirm of `M3-OBS-01-INDUCE-WEB` + paste evidence here |

**Note:** SSH already exists on the server — that is **ops**, not Sahil. Sahil does not own droplet write / induce flag flip.

**Partial staging fact (not A5):** Grafana already works and shows service logs. That supports stack health; it does **not** replace the controlled induce marker proof.

## Sahil checklist (prep)

| # | Task | Done |
|---|------|------|
| S1 | Induce HTTP + command + droplet script inventoried | [x] |
| S2 | Runbook / PHASE_6 steps match code (Phase 1) | [x] |
| S3 | `verify_m3_obs01_backend.py` PASS | [x] |
| S4 | `M3ObsInduceErrorTests` 3 OK | [x] |
| S5 | Live runbook + evidence blanks in this file | [x] |
| S6 | Rohan handoff message drafted | [x] |

## Ops / live checklist (Rohan)

| # | Task | Done |
|---|------|------|
| 2.1 | Confirm `GF_*` / `MAILER_*` / induce token in `DEV_ENV_FILE` | [ ] |
| 2.2 | Set `M3_OBS_INDUCE_ENABLED=true`, restart/redeploy `web` | [ ] |
| 2.3 | Droplet: `bash deploy/scripts/m3-obs-induce-web-error.sh` | [ ] |
| 2.4 | Explore: `{service="web"} \|= "M3-OBS-01-INDUCE-WEB"` | [ ] |
| 2.5 | `staging-logs-error-web` pending/firing; redis (etc.) no false-fire | [ ] |
| 2.6 | Capture evidence below (or send Sahil screenshot) | [ ] |
| 2.7 | WORKING_GAPS → Phase 2 full `[x]` when Explore proven | [ ] |

## Live runbook (ops on staging)

```bash
# 1) Enable briefly in DEV_ENV_FILE / droplet .env
M3_OBS_INDUCE_ENABLED=true
M3_OBS_INDUCE_TOKEN=<already-set-or-new-long-random>
# then: rewrite .env + docker compose up -d web  (or full redeploy)

# 2) On droplet
cd /opt/klints_backend   # or DEV_APP_DIR
bash deploy/scripts/m3-obs-induce-web-error.sh

# 3) Grafana Explore (Loki)
{service="web"} |= "M3-OBS-01-INDUCE-WEB"
```

**Expect:** one ERROR line under `service=web` only.  
**Alert:** `staging-logs-error-web` may go pending/firing after ~2m.  
**Must not:** `staging-logs-error-redis` (and ideally other services) fire for this marker.

## Evidence (fill after live ops)

| Item | Value |
|------|--------|
| Induce UTC time | _TBD_ |
| Explore URL / screenshot | _TBD_ |
| LogQL result summary | _TBD_ |
| `staging-logs-error-web` state | _TBD_ |
| False-fire (redis/other) | _TBD_ |
| Actions / deploy run (if used) | _TBD_ |

## Exit criteria

| Exit | When |
|------|------|
| Sahil Phase 2 prep | **Met** — docs + path ready; waiting on ops |
| PRD Phase 2 full | Explore shows `M3-OBS-01-INDUCE-WEB` under `service=web` + evidence pasted |

**Next after full Phase 2:** Phase 3 — alert email to `noreplyklints@gmail.com` (or stop-and-flag).

## Do not

Claim PRD Phase 2 / A5 closed without marker evidence · leave induce enabled after proof · claim email proven here · demo/SEC · bare `docker exec` logger
