# M3-OBS-01 — Phase 2 notes (labels + Explore)

**Date:** 2026-09-08  
**Branch:** `feature/m3-obs-01-grafana-loki-alloy`  
**Depends on:** Phase 1

## What landed

### 2.1 Service labels (required five)

| Compose service | `klints.obs.service` |
|-----------------|----------------------|
| `web` | `web` |
| `celery_worker` | `celery_worker` |
| `celery_beat` | `celery_beat` |
| `nginx` | `nginx` |
| `redis` | `redis` |

Also labeled: `loki`, `alloy`, `grafana` (self-logs optional).

Alloy maps labels in order:
1. `klints.obs.service` → `service`
2. else Compose `com.docker.compose.service`
3. else container name

### 2.2 Loki datasource

- Provisioned at `deploy/grafana/provisioning/datasources/loki.yml`
- `uid: loki`, `isDefault: true`, URL `http://loki:3100`

### 2.3 Explore / filter proof (in-repo)

Grafana **Explore** (after login):

1. Datasource: **Loki**
2. Label browser → `service`
3. Queries to paste:

```logql
{service="web"}
{service="celery_worker"}
{service="celery_beat"}
{service="nginx"}
{service="redis"}
```

Helper dashboard (Phase 2, not full Phase 4 Errors board):
- **Staging Docker Logs** (`m3-obs-staging-docker-logs`)
- Dropdown variable **service** from `label_values(service)`
- Panel: `{service=~"$service"}`

Live UI screenshot still required on staging after Phase 3 (or local port-forward). In-repo: labels + datasource + dashboard + verify gate.

## Deep check fixes (2026-09-08)

| Issue | Fix |
|-------|-----|
| Service labels might stay on discovery targets only | Alloy now uses `relabel_rules = discovery.relabel.containers.rules` on `loki.source.docker` so `service` attaches to log lines for Explore |
| Grafana 11 variable query format | Dashboard service variable uses Loki `type: 1` / `label: service` query object |
| Overclaim on live Explore | PRD 2.3 notes config ready; screenshot remains Phase 3 / staging PR proof |

## Validate

```bash
python scripts/verify_m3_obs01_backend.py
docker compose config --quiet
```

## PR body note (for screenshots later)

```text
Explore: filter service=web|celery_worker|celery_beat|nginx|redis
Dashboard: Staging Docker Logs · service dropdown
```

## Next

Phase 3 — nginx `/grafana/` + auth + `GF_SERVER_ROOT_URL`.
