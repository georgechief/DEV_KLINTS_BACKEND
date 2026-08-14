#!/usr/bin/env bash
# Build, migrate (via container entrypoint), ensure TLS, and start the stack.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/klints_backend}"
API_DOMAIN="${API_DOMAIN:-apis.klints.io}"
cd "${APP_DIR}"

run() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

# Prefer direct docker; fall back to sudo (fresh docker group membership needs re-login)
docker_cmd() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
  else
    run docker "$@"
  fi
}

dc() {
  docker_cmd compose "$@"
}

upsert_env() {
  # upsert_env KEY VALUE — replace or append a line in .env
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" .env 2>/dev/null; then
    # portable in-place edit
    run sed -i.bak "s|^${key}=.*|${key}=${value}|" .env
    run rm -f .env.bak
  else
    printf '%s=%s\n' "$key" "$value" | run tee -a .env >/dev/null
  fi
}

ensure_domain_env() {
  echo "==> Ensuring Django hosts for ${API_DOMAIN}"
  local hosts csrf
  if grep -q '^ALLOWED_HOSTS=' .env; then
    hosts="$(grep '^ALLOWED_HOSTS=' .env | head -1 | cut -d= -f2-)"
  else
    hosts=""
  fi
  case ",${hosts}," in
    *",${API_DOMAIN},"*) ;;
    *)
      if [[ -n "${hosts}" ]]; then
        hosts="${API_DOMAIN},${hosts}"
      else
        hosts="${API_DOMAIN},localhost,127.0.0.1"
      fi
      upsert_env ALLOWED_HOSTS "${hosts}"
      ;;
  esac

  csrf="https://${API_DOMAIN}"
  if grep -q '^CSRF_TRUSTED_ORIGINS=' .env; then
    local origins
    origins="$(grep '^CSRF_TRUSTED_ORIGINS=' .env | head -1 | cut -d= -f2-)"
    case ",${origins}," in
      *",${csrf},"*) ;;
      *)
        if [[ -n "${origins}" ]]; then
          origins="${csrf},${origins}"
        else
          origins="${csrf}"
        fi
        upsert_env CSRF_TRUSTED_ORIGINS "${origins}"
        ;;
    esac
  else
    upsert_env CSRF_TRUSTED_ORIGINS "${csrf}"
  fi

  upsert_env API_DOMAIN "${API_DOMAIN}"
}

if [[ ! -f .env ]]; then
  echo "Missing ${APP_DIR}/.env — set GitHub secret DEV_ENV_FILE" >&2
  exit 1
fi

ensure_domain_env

echo "==> Applying Docker daemon log rotation (max-size 1g, rotating)"
run mkdir -p /etc/docker
run cp deploy/docker-daemon.json /etc/docker/daemon.json
run systemctl reload docker 2>/dev/null || run systemctl restart docker

echo "==> Ensuring TLS certificate for ${API_DOMAIN}"
APP_DIR="${APP_DIR}" API_DOMAIN="${API_DOMAIN}" \
  bash "${APP_DIR}/deploy/scripts/ensure-ssl.sh"

echo "==> Building and starting stack"
# --pull can fail when Docker Hub is unreachable from the droplet; fall back to local base layers.
if ! dc build --pull; then
  echo "==> WARNING: compose build --pull failed (often Docker Hub timeout) — retrying without --pull" >&2
  dc build
fi
dc up -d --remove-orphans --force-recreate

echo "==> Waiting for HTTPS health (${API_DOMAIN})"
health_url="https://${API_DOMAIN}/health/"
for i in $(seq 1 36); do
  code="$(curl -sS -o /tmp/klints-health.out -w '%{http_code}' --max-time 8 \
    --resolve "${API_DOMAIN}:443:127.0.0.1" \
    "${health_url}" 2>/tmp/klints-health.err || echo "000")"
  if [[ "${code}" == "200" ]]; then
    echo "==> Healthy (${health_url}) → $(cat /tmp/klints-health.out)"
    break
  fi
  if [[ "$i" -eq 36 ]]; then
    echo "==> Health check failed (HTTP ${code}) for ${health_url}" >&2
    echo "==> Body: $(head -c 500 /tmp/klints-health.out 2>/dev/null || true)" >&2
    echo "==> Curl: $(head -c 300 /tmp/klints-health.err 2>/dev/null || true)" >&2
    echo "==> ALLOWED_HOSTS in .env: $(grep '^ALLOWED_HOSTS=' .env || true)" >&2
    echo "==> Recent nginx/web logs:" >&2
    dc logs --tail=60 nginx >&2 || true
    dc logs --tail=80 web >&2 || true
    exit 1
  fi
  sleep 5
done

# Reload nginx after recreate so any mid-deploy renew is picked up
dc exec -T nginx nginx -s reload 2>/dev/null || true

echo "==> Pruning unused images"
docker_cmd image prune -f >/dev/null

dc ps
echo "==> Deploy complete — https://${API_DOMAIN}/"
