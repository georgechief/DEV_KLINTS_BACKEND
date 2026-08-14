#!/usr/bin/env bash
# Issue or renew Let's Encrypt cert for the API domain (idempotent).
# Uses the official certbot/certbot Docker image — no host certbot package needed.
# First issue: standalone (needs port 80 free). Renewals: webroot via nginx.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/klints_backend}"
API_DOMAIN="${API_DOMAIN:-apis.klints.io}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-ops@klints.io}"
CERTBOT_IMAGE="${CERTBOT_IMAGE:-certbot/certbot:v2.11.0}"
# Docker Hub from some DO regions is flaky — retry then fall back to a local image.
CERTBOT_PULL_ATTEMPTS="${CERTBOT_PULL_ATTEMPTS:-5}"
CERTBOT_PULL_SLEEP_SEC="${CERTBOT_PULL_SLEEP_SEC:-8}"
WEBROOT="${APP_DIR}/deploy/certbot/www"
LIVE_DIR="/etc/letsencrypt/live/${API_DOMAIN}"
FULLCHAIN="${LIVE_DIR}/fullchain.pem"

cd "${APP_DIR}"

run() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

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

certbot_image_present() {
  docker_cmd image inspect "${CERTBOT_IMAGE}" >/dev/null 2>&1
}

ensure_certbot_image() {
  local attempt
  echo "==> Ensuring Docker image ${CERTBOT_IMAGE}"
  for attempt in $(seq 1 "${CERTBOT_PULL_ATTEMPTS}"); do
    if docker_cmd pull "${CERTBOT_IMAGE}"; then
      echo "==> Pulled ${CERTBOT_IMAGE}"
      return 0
    fi
    echo "==> docker pull failed (attempt ${attempt}/${CERTBOT_PULL_ATTEMPTS})" >&2
    if [[ "${attempt}" -lt "${CERTBOT_PULL_ATTEMPTS}" ]]; then
      sleep "${CERTBOT_PULL_SLEEP_SEC}"
    fi
  done

  if certbot_image_present; then
    echo "==> WARNING: Docker Hub pull failed; using cached local image ${CERTBOT_IMAGE}" >&2
    return 0
  fi

  # Cert already on disk: renew can wait; do not fail the whole deploy for Hub outages.
  if [[ -f "${FULLCHAIN}" ]]; then
    echo "==> WARNING: ${CERTBOT_IMAGE} unavailable and not cached — skipping renew; existing cert kept" >&2
    return 1
  fi

  echo "==> ERROR: cannot pull or find ${CERTBOT_IMAGE}, and no cert exists for ${API_DOMAIN}." >&2
  echo "    Docker Hub timed out from this host. Retry deploy later, or pre-pull on the droplet:" >&2
  echo "      docker pull ${CERTBOT_IMAGE}" >&2
  exit 1
}

certbot_docker() {
  # Shared mounts for issue/renew
  docker_cmd run --rm \
    -v /etc/letsencrypt:/etc/letsencrypt \
    -v /var/lib/letsencrypt:/var/lib/letsencrypt \
    -v "${WEBROOT}:/var/www/certbot" \
    "$@"
}

reload_nginx() {
  if dc ps --status running nginx 2>/dev/null | grep -q nginx; then
    dc exec -T nginx nginx -s reload 2>/dev/null || dc restart nginx || true
  fi
}

run mkdir -p "${WEBROOT}/.well-known/acme-challenge"
run mkdir -p /etc/letsencrypt /var/lib/letsencrypt
run chmod -R a+rX "${APP_DIR}/deploy/certbot" 2>/dev/null || true

HAVE_CERTBOT_IMAGE=1
if ! ensure_certbot_image; then
  HAVE_CERTBOT_IMAGE=0
fi

if [[ ! -f "${FULLCHAIN}" ]]; then
  echo "==> No cert for ${API_DOMAIN} — issuing via standalone (port 80 must be free)"
  dc stop nginx 2>/dev/null || true
  sleep 2

  # Bind host :80 for HTTP-01
  certbot_docker \
    -p 80:80 \
    "${CERTBOT_IMAGE}" certonly \
    --standalone \
    --non-interactive \
    --agree-tos \
    --email "${CERTBOT_EMAIL}" \
    --preferred-challenges http \
    -d "${API_DOMAIN}" \
    --keep-until-expiring

  echo "==> Certificate issued: ${FULLCHAIN}"
elif [[ "${HAVE_CERTBOT_IMAGE}" -eq 1 ]]; then
  echo "==> Cert present for ${API_DOMAIN} — renewing if due (webroot)"
  # Webroot works when nginx is serving /.well-known/acme-challenge/
  if certbot_docker \
    "${CERTBOT_IMAGE}" renew \
    --cert-name "${API_DOMAIN}" \
    --webroot \
    -w /var/www/certbot \
    --quiet; then
    reload_nginx
  else
    echo "==> Renew skipped or not due — OK"
  fi
else
  echo "==> Cert present — renew deferred (certbot image unavailable)"
fi

if [[ ! -f "${FULLCHAIN}" ]]; then
  echo "==> ERROR: ${FULLCHAIN} missing. Check DNS A/AAAA for ${API_DOMAIN} → this host, and that ports 80/443 are open." >&2
  exit 1
fi

# Let's Encrypt defaults to 700 on live/archive — nginx in Docker needs traverse
run chmod 755 /etc/letsencrypt /etc/letsencrypt/live /etc/letsencrypt/archive 2>/dev/null || true
if [[ -d "/etc/letsencrypt/live/${API_DOMAIN}" ]]; then
  run chmod 755 "/etc/letsencrypt/live/${API_DOMAIN}" 2>/dev/null || true
fi
if [[ -d "/etc/letsencrypt/archive/${API_DOMAIN}" ]]; then
  run chmod 755 "/etc/letsencrypt/archive/${API_DOMAIN}" 2>/dev/null || true
fi

echo "==> SSL ready for ${API_DOMAIN}"
