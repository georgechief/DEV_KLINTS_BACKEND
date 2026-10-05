# M3-OBS-01B — Phase 3 notes (alert email / stop-and-flag)

**Date:** 2026-09-14  
**Branch:** `feature/m3-obs-01b-grafana-alert-closeout`  
**PRD:** [PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md](./PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md)  
**SoT:** [M3_OBS_01_PHASE_6.md](./M3_OBS_01_PHASE_6.md) (email) · parent Phase 4 mailer path · [M3_OBS_01_RUNBOOK.md](./M3_OBS_01_RUNBOOK.md)  
**Depends on:** Phase 2 live induce (ops) so `staging-logs-error-web` can fire  

| Slice | Status |
|-------|--------|
| **Sahil (repo / prep)** | **DONE** (2026-09-14) |
| **Ops live (Rohan)** | **PENDING** — mailer env + inbox proof or stop-and-flag |
| **PRD Phase 3 / A7 full close** | **NOT done** until email proven or flagged with evidence |

## Goal

Prove alert path: Grafana rule fires → webhook → `obs_alert_mailer` → `MAILER_API_*` → inbox **`noreplyklints@gmail.com`**.  
If mailer fails: **stop-and-flag** with bridge logs (Explore still counts from Phase 2).

## Ownership split

| Owner | Scope |
|-------|--------|
| **Sahil** | Contact/rules/bridge on `main`, verify PASS, runbook path documented, Phase 3 checklist + evidence blanks |
| **Rohan / ops** | `MAILER_API_*` + `ALERT_EMAIL_TO` in `DEV_ENV_FILE`, inbox access, bridge logs on failure |
| **Either** | Confirm email received (or file stop-and-flag) after Phase 2 induce |

**Depends on ops Phase 2:** without induce → alert fire, Phase 3 cannot prove send.

## Path (repo — already shipped)

```text
staging-logs-error-web (pending/firing ~2m)
  → contact m3-obs-noreplyklints
  → http://obs_alert_mailer:8080/alert
  → MAILER_API_URL + Bearer MAILER_API_TOKEN
  → ALERT_EMAIL_TO (default noreplyklints@gmail.com)
```

| Piece | Path |
|-------|------|
| Rules | `deploy/grafana/provisioning/alerting/rules.yml` |
| Contact | `deploy/grafana/provisioning/alerting/contact-points.yml` |
| Bridge | `deploy/grafana/alert-mailer-bridge/server.py` |
| Compose | `obs_alert_mailer` |

## Sahil checklist (prep)

| # | Task | Done |
|---|------|------|
| S1 | Contact → `obs_alert_mailer:8080/alert` inventoried | [x] |
| S2 | Bridge → `MAILER_API_*` / `ALERT_EMAIL_TO` documented | [x] |
| S3 | Stop-and-flag path documented (runbook + parent Phase 4) | [x] |
| S4 | Verify script covers contact/mailer static checks | [x] PASS |
| S5 | Evidence blanks + ops checklist in this file | [x] |

## Ops / live checklist (Rohan)

| # | Task | Done |
|---|------|------|
| 3.1 | Confirm `MAILER_API_*` + `ALERT_EMAIL_TO=noreplyklints@gmail.com` | [ ] |
| 3.2 | After Phase 2 induce: `staging-logs-error-web` fires | [ ] |
| 3.3a | Email arrives at `noreplyklints@gmail.com` | [ ] **or** |
| 3.3b | Stop-and-flag: `docker compose logs obs_alert_mailer` + bridge `/health` | [ ] |
| 3.4 | Paste evidence below (or send Sahil) | [ ] |
| 3.5 | WORKING_GAPS → Phase 3 full `[x]` when A7 met | [ ] |

### Stop-and-flag (if mailer blocked)

```bash
docker compose logs --tail=100 obs_alert_mailer
# bridge /health should show mailer_configured true/false
```

Document: unset/rejecting mailer, HTTP status from bridge, no second mail product invented.

## Evidence (fill after live)

| Item | Value |
|------|--------|
| Alert rule state | _TBD_ (`staging-logs-error-web`) |
| Email received UTC | _TBD_ **or** N/A stop-and-flag |
| Inbox / subject screenshot | _TBD_ |
| Bridge logs excerpt | _TBD_ (required if stop-and-flag) |
| `mailer_configured` /health | _TBD_ |

## Exit criteria

| Exit | When |
|------|------|
| Sahil Phase 3 prep | **Met** — path + docs ready; waiting on ops |
| PRD Phase 3 / A7 | Email proven **or** stop-and-flag with evidence |

**Next after full Phase 3:** Phase 4 — disable induce + §11 + PR notes.

## Do not

Claim A7 without inbox or stop-and-flag · invent a second mail product · demo/SEC · leave induce on forever
