# M3-OBS-01 — Phase 6 notes (staging acceptance demo)

**Date:** 2026-09-08  
**Branch:** `feature/m3-obs-01-grafana-loki-alloy`  
**Depends on:** Phase 0–5  
**Live SoT:** GitHub Actions `deploy-development.yml` after merge to `main` (Sahil does **not** push `main`)

## What this phase is

Prove OBS-01 on **staging** with a controlled `web` ERROR, then paste the employer checklist in the PR.

| # | Task | In-repo prep | Live (after merge) |
|---|------|--------------|--------------------|
| 6.1 | Deploy via workflow | Workflow + smoke ready (Phase 5) | Merge PR → Actions green |
| 6.2 | Induce ERROR `service=web` | Gated HTTP + `m3_obs_induce_error` | Enable token → induce → Explore |
| 6.3 | Other services do not false-fire | Documented checks below | Confirm redis/nginx rules stay OK |
| 6.4 | Employer checklist §11 | Template below | Sign off in PR comment |

## Critical: why HTTP (not bare `docker exec` log)

Alloy scrapes the **running** `web` container Docker json-file logs.  
`docker compose exec … logger.error(...)` often prints only to the exec session and **never appears in Loki**.

Induce therefore **POSTs** `http://127.0.0.1:8000/ops/m3-obs-01/induce-error/` inside the web container so **gunicorn** emits the ERROR line.

## Induce (non-destructive)

Marker: **`M3-OBS-01-INDUCE-WEB`**

### 1) Enable briefly in staging `DEV_ENV_FILE` / `.env`

```bash
M3_OBS_INDUCE_ENABLED=true
M3_OBS_INDUCE_TOKEN=<long-random-secret>
```

Redeploy (or rewrite `.env` + `docker compose up -d web`) so web picks up env.

### 2) Run induce on the droplet

```bash
cd /opt/klints_backend   # or DEV_APP_DIR
bash deploy/scripts/m3-obs-induce-web-error.sh
# equivalent:
docker compose exec -T web python manage.py m3_obs_induce_error --yes
```

### 3) Explore

```logql
{service="web"} |= "M3-OBS-01-INDUCE-WEB"
```

**Expect:** line under `service=web` only.  
**Alert:** `staging-logs-error-web` may go pending/firing after ~2m.  
**Must not:** `staging-logs-error-redis` (and ideally other services) fire for this same marker.

### 4) Disable induce again

Set `M3_OBS_INDUCE_ENABLED=false` (or remove token) in `DEV_ENV_FILE` and redeploy.

Optional silence before induce if you only want Explore proof: Alerting → Silences → `m3_obs=01` for 30m.

## Email

If alert fires → inbox `noreplyklints@gmail.com` via mailer bridge.  
If mailer fails → **stop-and-flag** with bridge logs; Explore still counts.

## Deep-check fix (2026-09-08)

- Replaced exec-only logging with gated **POST** `/ops/m3-obs-01/induce-error/` (token + flag)
- Command POSTs to live gunicorn; view also `print`s ERROR to stderr for Docker logs
- Default **disabled** (`M3_OBS_INDUCE_ENABLED=false`)

## Employer checklist (paste into PR after live proof)

```markdown
### M3-OBS-01 employer acceptance (§11)

**Staging only · free OSS · Alloy not Promtail · no product UI link · alerts → noreplyklints@gmail.com · workflow is deploy SoT**

- [ ] **A1** — loki / alloy / grafana in compose (pinned tags + volumes)
- [ ] **A2** — deploy-development.yml deploy left https://apis.klints.io/health/ green
- [ ] **A3** — https://apis.klints.io/grafana/ reachable; login required
- [ ] **A4** — Explore filters service= web / celery_worker / celery_beat / nginx / redis
- [ ] **A5** — Induced ERROR `M3-OBS-01-INDUCE-WEB` appears under service=web
- [ ] **A6** — Five separate alert rules (not one combined rule)
- [ ] **A7** — Alert email → noreplyklints@gmail.com (send proven **or** stop-and-flag note)
- [ ] **A8** — Dashboards + Loki datasource provisioned as code
- [ ] **A9** — Workflow OBS smoke green; `python scripts/verify_m3_obs01_backend.py` PASS
- [ ] **A10** — Runbook merged; no Klints product UI link; no Promtail; no Prometheus required

**Induce evidence:** Explore screenshot or LogQL result for `M3-OBS-01-INDUCE-WEB`  
**False-fire check:** redis (and other) rules did not fire for that event  
**Actions URL:** _paste workflow run_

Signed off: _name / date_
```

## Validate (static)

```bash
python scripts/verify_m3_obs01_backend.py
python manage.py test core.tests.M3ObsInduceErrorTests
```

## Ops before merge

1. Set strong `GF_SECURITY_ADMIN_PASSWORD` in GitHub `DEV_ENV_FILE`
2. Confirm `MAILER_API_*` present in `DEV_ENV_FILE`
3. Optionally pre-stage `M3_OBS_INDUCE_TOKEN` (keep `M3_OBS_INDUCE_ENABLED=false` until induce)
4. Open PR from `feature/m3-obs-01-grafana-loki-alloy` (do not push `main`)
5. After merge: watch Actions → enable induce → run script → Explore → disable induce → fill checklist
