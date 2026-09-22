# M3-OBS-01 — Phase 0 lock notes

**Date:** 2026-09-08  
**Branch:** `feature/m3-obs-01-grafana-loki-alloy` (from `main`; Sahil does **not** push to `main`)  
**PRD:** `PRD_M3_OBS_01_STAGING_GRAFANA_LOKI_ALLOY.md`

## 0.1 Deploy path read-through — done

| File | Role today | OBS-01 impact |
|------|------------|---------------|
| `.github/workflows/deploy-development.yml` | `main` push / `workflow_dispatch` → rsync → `.env` → bootstrap → `deploy.sh` → HTTPS `/health/` smoke | Phase 5: add Grafana/Loki health smoke after `/health/` |
| `deploy/scripts/bootstrap-host.sh` | Docker Engine + log rotation daemon.json + firewall 80/443 | No change expected in v1 (Alloy needs docker.sock in compose) |
| `deploy/scripts/deploy.sh` | TLS → `compose build/up` → health → pilot verify | Obs services start with same `dc up`; no second deploy system |
| `docker-compose.yml` | `redis`, `web`, `celery_worker`, `celery_beat`, `nginx` · **json-file** logging (1g × 3) | Phase 1: add `loki`, `alloy`, `grafana` + volumes |
| `deploy/nginx/klints.conf` | `apis.klints.io` → `web:8000`; TLS on 443 | Phase 3: `location /grafana/` → `grafana:3000` (subpath) |
| `.env` / `DEV_ENV_FILE` | Staging secrets via GitHub Secret | Phase 1+: `GF_*`, SMTP vars — never commit passwords |

**Compose today:** no Grafana / Loki / Alloy / Promtail. Logging already json-file — Alloy can scrape Docker logs.

## 0.2 Staging disk / RAM + SSH

**SSH / deploy access:** Already live on **`main`** via `.github/workflows/deploy-development.yml` (`DEV_HOST` + `DEV_SSH_PRIVATE_KEY`). Sahil does **not** push `main`; after PR merge, that workflow is the SoT for putting OBS on the droplet.

**Disk / RAM numbers:** Still useful once (paste into PR). Anyone with droplet shell can run:

```bash
df -h /
free -h
nproc
docker system df
```

| Guardrail (PRD) | Action if breached |
|-----------------|--------------------|
| Free disk &lt; ~5 GB | Stop — propose shorter Loki retention / slim config before Cloud |
| Cannot add ~512 MB–1 GB RAM for obs | Stop — propose slim config or tiny sibling droplet |

**PR body placeholder:** `Disk free: _optional paste_ · Mem: _optional paste_ · Deploy SSH: main workflow OK`

Phase 1 compose-in-repo may proceed; staging fit confirmed after merge smoke (or earlier paste).

## 0.3 Admin / alert email — **confirmed**

| Use | Value |
|-----|-------|
| Grafana admin + alert target | `noreplyklints@gmail.com` (locked D6) |
| Outbound mail SoT | Existing **Klints mailer API** (`MAILER_API_URL` / `MAILER_API_TOKEN` in `.env` / `DEV_ENV_FILE`) — Sahil has this in local env |

**Phase 4 note:** Grafana alert contact points are usually SMTP or webhook. Plan: wire alerts to email `noreplyklints@gmail.com` using **staging mailer** (SMTP if present, or webhook → mailer API). Do **not** invent a second mail product. If Grafana cannot call the mailer cleanly, stop-and-flag with evidence — still ship Explore.

**Sahil checklist:**
- [x] Mailer API available in own env (matches `.env.example` pattern)
- [ ] Phase 4: prove one alert email lands (or stop-and-flag)

## 0.4 URL mode — **LOCKED**

| Choice | Decision |
|--------|----------|
| **Mode** | **Path:** `https://apis.klints.io/grafana/` |
| Why | Reuses existing `apis.klints.io` TLS; no new DNS/A record; matches PRD preference |
| Not chosen | `grafana.apis.klints.io` subdomain (extra DNS + cert unless covered by wildcard) |
| Auth | Grafana native admin password via `DEV_ENV_FILE` / GitHub Secrets (minimum v1) |
| Product UI | **No** Klints nav link (D7) |
| Public `:3000` | **Forbidden** |

`GF_SERVER_ROOT_URL` must match path mode (Phase 3), e.g. `https://apis.klints.io/grafana/`.

## 0.5 Branch — ready

```text
feature/m3-obs-01-grafana-loki-alloy
```

Cut from current `main` (includes OBS-01 PRD doc). Push feature branch only; merge via PR.

## Phase 0 exit

| Item | Status |
|------|--------|
| Deploy path understood | **Done** |
| URL mode locked | **Done** → `/grafana/` |
| Branch ready | **Done** |
| Droplet disk/RAM numbers | **Optional paste** — deploy SSH already on `main` workflow |
| Alert email / mailer | **Confirmed** — use existing `MAILER_API_*`; Phase 4 wires Grafana → that path |

**Next:** Phase 1 — add `loki` + `alloy` + `grafana` to compose (pinned tags) + config dirs under `deploy/`.
