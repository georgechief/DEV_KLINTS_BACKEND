# M3-OBS-01 — Phase 1 notes (compose stack)

**Date:** 2026-09-08  
**Branch:** `feature/m3-obs-01-grafana-loki-alloy`  
**Depends on:** Phase 0 (`M3_OBS_01_PHASE_0.md`)

## What landed

| Service | Image (pinned) | Role |
|---------|----------------|------|
| `loki` | `grafana/loki:3.5.1` | Log store · 7d retention · filesystem volume · listen `0.0.0.0:3100` (3.5.1+ avoids #17371 SM spam) |
| `alloy` | `grafana/alloy:v1.9.2` | Docker logs → Loki (`service` / `container` / `compose_project`); compose-project keep filter |
| `grafana` | `grafana/grafana:11.6.1` | UI · admin from env · subpath-ready · Loki datasource provisioned |

**Not in Phase 1:** nginx `/grafana/` route (Phase 3) · dashboards/alerts (Phase 4) · workflow smoke (Phase 5).

## Files

- `docker-compose.yml` — obs services; **no** host publish of `:3000` / `:3100` / Alloy UI
- `deploy/loki/loki-config.yml`
- `deploy/alloy/config.alloy`
- `deploy/grafana/provisioning/datasources/loki.yml`
- `.env.example` — `GF_SECURITY_ADMIN_*`, `GF_SERVER_ROOT_URL`
- `scripts/verify_m3_obs01_backend.py` — static gate

## Security notes (honest)

- Alloy mounts `/var/run/docker.sock:ro` as `user: root` (needed to read logs on typical DO hosts).
- Grafana anonymous auth **off**; change `GF_SECURITY_ADMIN_PASSWORD` in `DEV_ENV_FILE` before merge to staging.
- Default compose password is a placeholder only.
- Loki has **no** in-container wget healthcheck (slim image); readiness proven later via workflow smoke.

## Validate

```bash
# Static (any machine with venv)
python scripts/verify_m3_obs01_backend.py

# Compose parse (WSL or Docker Desktop) — prefer quiet (avoids dumping .env secrets)
docker compose config --quiet && docker compose config --services
```

Must list `loki`, `alloy`, `grafana` with pinned tags (no `:latest`).

## Deep check (2026-09-08)

| Check | Result |
|-------|--------|
| PRD 1.1–1.4 | **Pass** |
| 1.5 compose config | **Pass** (WSL `docker compose config`; volumes + pinned images present) |
| Static verify | **Pass** |
| No host `:3000` / Promtail / Prometheus | **Pass** |
| Loki healthcheck wget | **Removed** (unreliable on slim Loki images) |
| Loki bind all interfaces | **Fixed** (`http_listen_address: 0.0.0.0`) |
| Alloy compose-only scrape | **Added** keep-if-compose-project |

## Next

Phase 2 — prove Explore filters by `service` (after nginx or local port-forward for demo).
