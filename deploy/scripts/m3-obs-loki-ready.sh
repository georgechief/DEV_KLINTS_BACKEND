#!/usr/bin/env bash
# M3-OBS-01 — probe Loki /ready from the compose network (web has Python).
# Exit 0 when ready; exit 1 when still 503 / unreachable (caller retries).
set -eu
cd "${APP_DIR:-/opt/klints_backend}"

docker compose exec -T web python -c '
import urllib.error, urllib.request, sys

for path in ("/ready", "/loki/ready"):
    try:
        r = urllib.request.urlopen("http://loki:3100" + path, timeout=10)
        body = r.read().decode()
        if r.status == 200 and "ready" in body.lower():
            print(path, body.strip())
            sys.exit(0)
    except urllib.error.HTTPError as exc:
        print(path, exc.code, flush=True)
    except Exception as exc:
        print(path, type(exc).__name__, exc, flush=True)

sys.exit(1)
'
