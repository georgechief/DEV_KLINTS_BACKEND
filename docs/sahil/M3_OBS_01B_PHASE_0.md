# M3-OBS-01B — Phase 0 notes (lock / inventory)

**Date:** 2026-09-14  
**Branch:** `feature/m3-obs-01b-grafana-alert-closeout` (from `origin/main` @ `72bdb41`)  
**PRD:** [PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md](./PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md)  
**Parent:** OBS-01 Phases 0–5 shipped; Phase 6 **live** proof still open  

## Goal

Inventory induce / alert / mailer paths on current `main`. Confirm static gate green. List staging env keys for Rohan. **No live induce in Phase 0.**

## Checklist

| # | Task | Done |
|---|------|------|
| 0.1 | Branch from latest `main` | [x] |
| 0.2 | Read OBS-01B + parent PHASE_6 + runbook | [x] |
| 0.3 | Inventory induce HTTP + command + droplet script | [x] |
| 0.4 | Inventory alert rules + contact point + mailer bridge | [x] |
| 0.5 | `python scripts/verify_m3_obs01_backend.py` | [x] **PASS** |
| 0.6 | `manage.py test core.tests.M3ObsInduceErrorTests` | [x] **3 OK** |
| 0.7 | Staging env checklist for Rohan (below) | [x] drafted — needs ops confirm |
| 0.8 | Update WORKING_GAPS | [x] |

## Inventory (repo — present on main)

| Piece | Path / detail | Status |
|-------|---------------|--------|
| Marker | `core/m3_obs.py` → `INDUCE_MARKER = "M3-OBS-01-INDUCE-WEB"` | OK |
| Induce view | `POST /ops/m3-obs-01/induce-error/` · `M3ObsInduceErrorView` · gated by `M3_OBS_INDUCE_ENABLED` + `X-M3-Obs-Induce-Token` · 404 if off | OK |
| Induce command | `manage.py m3_obs_induce_error --yes` POSTs to `http://127.0.0.1:8000/ops/...` (gunicorn path for Alloy) | OK |
| Droplet script | `deploy/scripts/m3-obs-induce-web-error.sh` → `docker compose exec -T web … --yes` | OK |
| Settings | `M3_OBS_INDUCE_ENABLED` default **False**; `M3_OBS_INDUCE_TOKEN` | OK |
| `.env.example` | Documents induce + `ALERT_EMAIL_TO` | OK |
| Alert rules | Five UIDs in `deploy/grafana/provisioning/alerting/rules.yml` (web / celery_worker / celery_beat / nginx / redis) | OK |
| Contact point | webhook → `http://obs_alert_mailer:8080/alert` | OK |
| Mailer bridge | `deploy/grafana/alert-mailer-bridge/server.py` → `MAILER_API_*` → `ALERT_EMAIL_TO` (default `noreplyklints@gmail.com`) | OK |
| Compose | `obs_alert_mailer` + loki / alloy / grafana | OK |
| Runbook / PHASE_6 | Induce steps + §11 A1–A10 template | OK |
| Verify script | Phase 1–6 static checks | **PASS** |

### Drift check (runbook vs code)

No blocking drift found. Induce is correctly **HTTP into live web** (not bare `docker exec` logger). Marker string matches Explore LogQL in PHASE_6 / runbook.

## Staging env checklist (Rohan / ops)

Confirm in GitHub Secret **`DEV_ENV_FILE`** / droplet `.env` (do **not** commit secrets):

| Key | Expected for closeout | Notes |
|-----|----------------------|--------|
| `GF_SECURITY_ADMIN_USER` | set (often `noreplyklints@gmail.com`) | Grafana login |
| `GF_SECURITY_ADMIN_PASSWORD` | strong secret | never commit |
| `GF_SERVER_ROOT_URL` | `https://apis.klints.io/grafana/` | subpath |
| `MAILER_API_*` | present + working | alert email path |
| `ALERT_EMAIL_TO` | `noreplyklints@gmail.com` | default OK |
| `M3_OBS_INDUCE_TOKEN` | long random (can pre-stage) | keep secret |
| `M3_OBS_INDUCE_ENABLED` | **`false` until Phase 2** | enable only for proof window |

**Sahil cannot verify staging secret values from this machine.** Phase 0 exit for env = checklist sent; Rohan confirms before Phase 2.

## What is still open (live — not Phase 0)

| Gap | Owner |
|-----|--------|
| Staging induce enabled briefly | Rohan/ops + Sahil |
| Explore shows `M3-OBS-01-INDUCE-WEB` under `service=web` | Live Phase 2 |
| Alert email to noreplyklints@gmail.com | Live Phase 3 |
| Induce disabled again | Live Phase 4 |
| Phase 6 §11 signed | Live Phase 4 |

## Static evidence (2026-09-14)

```text
python scripts/verify_m3_obs01_backend.py
→ M3-OBS-01 Phase 1-6 static checks: PASS

python manage.py test core.tests.M3ObsInduceErrorTests --keepdb
→ Ran 3 tests … OK
```

## Exit

Phase 0 **done** for repo inventory + static gate.  
**Next:** Phase 1 closed as N/A (see [M3_OBS_01B_PHASE_1.md](./M3_OBS_01B_PHASE_1.md)). Proceed to Phase 2 live induce when Rohan enables staging flags.

## Do not

Demo seed · Shopify · SEC packet · enable induce on staging from this phase · claim alert email proven
