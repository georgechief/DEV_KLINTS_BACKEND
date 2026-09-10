# M3-OBS-01 runbook — Staging Grafana + Loki + Alloy

**PRD:** [PRD_M3_OBS_01_STAGING_GRAFANA_LOKI_ALLOY.md](./PRD_M3_OBS_01_STAGING_GRAFANA_LOKI_ALLOY.md)  
**Scope:** Staging DigitalOcean only · free OSS · ops URL · **no** Klints product UI link  

---

## 1. URL + login

| Item | Value |
|------|--------|
| URL | https://apis.klints.io/grafana/ |
| Admin user | `noreplyklints@gmail.com` (from `GF_SECURITY_ADMIN_USER` in `DEV_ENV_FILE`) |
| Password | `GF_SECURITY_ADMIN_PASSWORD` in GitHub Secret `DEV_ENV_FILE` only — never commit |
| Auth | Grafana native login; anonymous **off**; no public host `:3000` |

Open `/grafana/` → login page → sign in. Merchants / tenants have **no** access.

---

## 2. Explore — filter by service + find errors

1. Grafana → **Explore** (Loki is default datasource).
2. LogQL examples:

```logql
{service="web"}
{service="celery_worker"} |~ "(?i)error|exception|traceback"
```

3. Or open dashboards (folder **M3 OBS-01**):
   - **Staging Docker Logs** — service dropdown
   - **Errors only** — ERROR-like lines + service filter

Required app services: `web`, `celery_worker`, `celery_beat`, `nginx`, `redis`.

---

## 3. Alert rules + silence during deploy

**Rules (as code):** `deploy/grafana/provisioning/alerting/rules.yml`

| Rule UID | Service |
|----------|---------|
| `staging-logs-error-web` | web |
| `staging-logs-error-celery_worker` | celery_worker |
| `staging-logs-error-celery_beat` | celery_beat |
| `staging-logs-error-nginx` | nginx |
| `staging-logs-error-redis` | redis |

**Email path:** Grafana webhook → `obs_alert_mailer` → `MAILER_API_*` → `ALERT_EMAIL_TO` (default `noreplyklints@gmail.com`).

**Silence for a deploy:**

1. Alerting → **Silences**
2. Match label `m3_obs=01` (all five) **or** one `service=…`
3. Duration covering the deploy window; comment `deploy silence YYYY-MM-DD`
4. Expire when `/health/` + OBS smoke are green

Do **not** delete/disable the five rules permanently.

---

## 4. How deploy rolls this out

| Path | Detail |
|------|--------|
| Workflow | `.github/workflows/deploy-development.yml` |
| Trigger | Push to `main` **or** `workflow_dispatch` |
| Flow | rsync → write `.env` from `DEV_ENV_FILE` → bootstrap → `deploy.sh` → HTTPS `/health/` → **Grafana `/grafana/api/health` + login + Loki `/ready`** |
| Branch discipline | Feature branch + PR; do **not** push straight to `main` |

Static gate before merge:

```bash
python scripts/verify_m3_obs01_backend.py
```

---

## 5. Common failures

| Symptom | Likely cause | What to check |
|---------|--------------|---------------|
| Disk full / containers crash | Droplet out of space | `df -h /`; shorten Loki retention if needed |
| No logs in Explore | Alloy cannot read docker.sock | `docker compose logs alloy`; socket mounted `:ro` (`/var/run/docker.sock`); labels `klints.obs.service` |
| Grafana subpath 404 / asset errors | Root URL / nginx mismatch | `GF_SERVER_ROOT_URL=https://apis.klints.io/grafana/` + `SERVE_FROM_SUB_PATH`; nginx `location /grafana/` |
| Login works but alerts never email | Mailer / SMTP path unset or rejecting | `MAILER_API_*` in `.env`; `docker compose logs obs_alert_mailer`; bridge `/health`; **stop-and-flag** if blocked (no second mail product) |
| Workflow OBS smoke fails | grafana/loki not up | Actions log; `docker compose ps grafana loki alloy`; nginx `/grafana/` |
| `/health/` broken after OBS | nginx mis-edit | Keep `location /health/` on :80 and :443 |

---

## 6. What this is **not**

- **Not** M3-SEC-01 (RBAC / security review packet)
- **Not** DP1 / demo-env live acceptance
- **Not** Prometheus / metrics dashboards (M3-OBS-02)
- **Not** Grafana Cloud paid / Promtail / Kubernetes
- **Not** a Klints app nav “Open Grafana” link

Honest claim: *Staging Grafana with Docker log aggregation and per-service alerts.*

---

## Related notes

| Doc | Role |
|-----|------|
| [M3_OBS_01_PHASE_0.md](./M3_OBS_01_PHASE_0.md) … [PHASE_5.md](./M3_OBS_01_PHASE_5.md) | Phase lock notes |
| [M3_OBS_01_PHASE_6.md](./M3_OBS_01_PHASE_6.md) | Staging induce + employer checklist |
| [M3_OBS_01_PHASE_5.md](./M3_OBS_01_PHASE_5.md) | Workflow + verify + this runbook |

---

## 7. Phase 6 acceptance (after merge)

1. Confirm Actions deploy + OBS smoke green.
2. Set `M3_OBS_INDUCE_ENABLED=true` + `M3_OBS_INDUCE_TOKEN` in staging `.env`, restart `web`.
3. On droplet: `bash deploy/scripts/m3-obs-induce-web-error.sh`  
   (POSTs to live gunicorn — **not** bare exec logging; Alloy needs container json-file logs)
4. Explore: `{service="web"} |= "M3-OBS-01-INDUCE-WEB"`
5. Confirm **web** alert pending/firing; **redis** (and other services) do **not** false-fire for that marker.
6. Disable induce (`M3_OBS_INDUCE_ENABLED=false`) and redeploy.
7. Paste employer checklist from [M3_OBS_01_PHASE_6.md](./M3_OBS_01_PHASE_6.md) into the PR comment.
