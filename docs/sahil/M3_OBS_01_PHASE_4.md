# M3-OBS-01 — Phase 4 notes (dashboards + alerts + email)

**Date:** 2026-09-08  
**Branch:** `feature/m3-obs-01-grafana-loki-alloy`  
**Depends on:** Phase 0–3  
**Alert inbox:** `noreplyklints@gmail.com`

## What landed

### 4.1 Dashboards (as code)
| Dashboard | UID | Path |
|-----------|-----|------|
| Staging Docker Logs | `m3-obs-staging-docker-logs` | `deploy/grafana/provisioning/dashboards/json/staging-docker-logs.json` |
| Staging Errors (**Errors only**) | `m3-obs-staging-errors` | `deploy/grafana/provisioning/dashboards/json/staging-errors.json` |

Folder: **M3 OBS-01**. Errors panel filters ERROR-like lines (`error|exception|traceback|critical|fatal`) with service dropdown.

### 4.2 Contact point → email
Grafana cannot call the Klints Mailer JSON API directly. Path:

```text
Grafana alert → webhook → obs_alert_mailer:8080/alert
                         → MAILER_API_URL + Bearer MAILER_API_TOKEN
                         → ALERT_EMAIL_TO (noreplyklints@gmail.com)
```

| Piece | Location |
|-------|----------|
| Contact point `m3-obs-noreplyklints` | `deploy/grafana/provisioning/alerting/contact-points.yml` |
| Policy group_by `service` | `deploy/grafana/provisioning/alerting/policies.yml` |
| Bridge | `deploy/grafana/alert-mailer-bridge/server.py` + compose `obs_alert_mailer` |

**Not a second mail product** — reuses existing `MAILER_API_*` from `DEV_ENV_FILE` / `.env` via compose `env_file` (avoids `${}` mangling tokens with `&` / `*`).

**Stop-and-flag:** If staging mailer rejects / is unset, Explore + dashboards + rules still ship; bridge `/health` reports `mailer_configured: false` and webhook returns 502. Prove one real alert email after Phase 6 induce (or flag with evidence).

### Deep-check fixes (2026-09-08)
- Alert reduce expressions use `replaceNN` + `replaceWithValue: 0` (cleaner zero windows)
- nginx LogQL no longer required spaced ` emerg ` tokens
- Bridge: `urlparse` path match, `ThreadingHTTPServer`, better Grafana webhook titles
- `obs_alert_mailer` uses `env_file: .env` for `MAILER_API_*`
- Dashboard title aligned to PRD **Errors only**

### 4.3 Five separate ERROR rules
Provisioned under group `staging-docker-log-errors` (folder M3 OBS-01):

| UID / title | Filter |
|-------------|--------|
| `staging-logs-error-web` | `service="web"` |
| `staging-logs-error-celery_worker` | `service="celery_worker"` |
| `staging-logs-error-celery_beat` | `service="celery_beat"` |
| `staging-logs-error-nginx` | `service="nginx"` |
| `staging-logs-error-redis` | `service="redis"` |

Each: LogQL `count_over_time` 5m · threshold `> 0` · `for: 2m` · label `service=<name>` · routes to `m3-obs-noreplyklints`.

### 4.4 Silence / mute during deploy

**During a staging deploy** (avoid alert noise):

1. Open Grafana → **Alerting → Silences**.
2. Create a silence matching label `m3_obs=01` (covers all five OBS-01 rules) **or** match one `service=web` etc.
3. Set duration covering the deploy window (e.g. 30–60 min).
4. Comment: `deploy silence YYYY-MM-DD`.
5. After smoke is green, expire/delete the silence.

**Mute timings (optional):** Alerting → Notification policies → time intervals — use for recurring maintenance windows. Prefer **Silences** for one-off deploys.

**Do not** disable the five rules permanently; silence instead.

## Validate

```bash
python scripts/verify_m3_obs01_backend.py
docker compose config --quiet
```

Live email proof waits for staging deploy + controlled ERROR (Phase 6).

## Next

Phase 5 — workflow Grafana/Loki smoke + runbook + README row.
