#!/usr/bin/env bash
# M3-OBS-01 Phase 6 — induce one benign web ERROR via the *running* web worker.
# Alloy scrapes Docker json-file logs; docker-exec stdout alone will NOT hit Loki.
# Requires M3_OBS_INDUCE_ENABLED=true and M3_OBS_INDUCE_TOKEN in the web .env.
set -euo pipefail
cd "$(dirname "$0")/../.."
docker compose exec -T web python manage.py m3_obs_induce_error --yes
echo "Next: Grafana Explore {service=\"web\"} |= \"M3-OBS-01-INDUCE-WEB\""
echo "Then disable M3_OBS_INDUCE_ENABLED (or remove token) in DEV_ENV_FILE and redeploy."
