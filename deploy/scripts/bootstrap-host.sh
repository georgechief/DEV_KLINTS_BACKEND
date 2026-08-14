#!/usr/bin/env bash
# Idempotent CentOS / Rocky / Alma host prep for Klints Docker deploys.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/klints_backend}"

run() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

echo "==> Preparing host for Klints (APP_DIR=${APP_DIR})"

if command -v dnf >/dev/null 2>&1; then
  PKG=dnf
elif command -v yum >/dev/null 2>&1; then
  PKG=yum
else
  echo "Unsupported OS: need dnf/yum (CentOS/Rocky/Alma)" >&2
  exit 1
fi

run $PKG -y install curl ca-certificates gnupg2 yum-utils

if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker Engine"
  run $PKG -y install dnf-plugins-core 2>/dev/null || true
  run $PKG config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
  run $PKG -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

run mkdir -p /etc/docker
run cp "${APP_DIR}/deploy/docker-daemon.json" /etc/docker/daemon.json

run systemctl enable docker
run systemctl restart docker

# Allow non-root deploy user to run docker without sudo after bootstrap
if [[ "$(id -u)" -ne 0 ]]; then
  run usermod -aG docker "$(whoami)" || true
fi

run mkdir -p "${APP_DIR}"
run mkdir -p "${APP_DIR}/deploy/certbot/www/.well-known/acme-challenge"
run mkdir -p /etc/letsencrypt /var/lib/letsencrypt
run chmod 755 "${APP_DIR}"

if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  run firewall-cmd --permanent --add-service=http || true
  run firewall-cmd --permanent --add-service=https || true
  run firewall-cmd --reload || true
fi

# Weekly renew via Docker certbot (ensure-ssl.sh) — no host certbot package
CRON_LINE="15 3 * * * APP_DIR=${APP_DIR} API_DOMAIN=apis.klints.io /bin/bash ${APP_DIR}/deploy/scripts/ensure-ssl.sh >> /var/log/klints-ssl-renew.log 2>&1"
if command -v crontab >/dev/null 2>&1; then
  existing="$(crontab -l 2>/dev/null || true)"
  if ! printf '%s\n' "$existing" | grep -qF "deploy/scripts/ensure-ssl.sh"; then
    echo "==> Installing cert renew cron"
    printf '%s\n%s\n' "$existing" "$CRON_LINE" | run crontab - || \
      printf '%s\n%s\n' "$existing" "$CRON_LINE" | crontab - || true
  fi
fi

docker --version
docker compose version
echo "==> Host bootstrap complete (TLS via certbot Docker image on deploy)"
