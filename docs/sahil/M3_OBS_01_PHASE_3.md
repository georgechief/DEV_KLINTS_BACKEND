# M3-OBS-01 — Phase 3 notes (edge access)

**Date:** 2026-09-08  
**Branch:** `feature/m3-obs-01-grafana-loki-alloy`  
**Depends on:** Phase 0–2  
**URL (locked):** `https://apis.klints.io/grafana/`

## What landed

### 3.1 Nginx → Grafana subpath
- `upstream klints_grafana` → `grafana:3000`
- `location = /grafana` → 301 `/grafana/`
- `location /grafana/` → proxy with `Host`, `X-Forwarded-*`, WebSocket `Upgrade`
- Matches `GF_SERVER_ROOT_URL` + `GF_SERVER_SERVE_FROM_SUB_PATH=true`
- `nginx` `depends_on: grafana`

### 3.2 Auth
- `GF_AUTH_ANONYMOUS_ENABLED=false` (compose)
- No host publish of `:3000`
- Login = Grafana native admin (`GF_SECURITY_ADMIN_*` from `DEV_ENV_FILE`)

### 3.3 `/health/` preserved
- HTTP + HTTPS `location /health/` still proxy to `web` (deploy smoke unchanged)

## Validate

```bash
python scripts/verify_m3_obs01_backend.py
docker compose config --quiet
```

Live proof after merge to `main` + deploy workflow:
- `https://apis.klints.io/health/` → 200
- `https://apis.klints.io/grafana/` → login page (not anonymous Explore)

## Next

Phase 4 — Errors dashboard + per-service alert rules + email to `noreplyklints@gmail.com`.
