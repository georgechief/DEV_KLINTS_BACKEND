# Releases & deploy (DEV_KLINTS_BACKEND)

Staging deploy is **tag-driven**. Pushing or merging to `main` does **not** deploy.

| Rule | Detail |
|------|--------|
| Trigger | Push of a semver tag `vMAJOR.MINOR.PATCH`, publish of a GitHub Release from that tag, or manual **workflow_dispatch** with a tag |
| Not a trigger | Commits / PRs on `main` alone |
| Workflow | `.github/workflows/deploy-development.yml` — name: **Deploy release (tag)** |
| Target | Client DigitalOcean droplet → stack under `/opt/klints_backend` |
| Public API | `https://apis.klints.io` (TLS via Let’s Encrypt / nginx) |

## Version format

```text
vMAJOR.MINOR.PATCH
```

Examples: `v1.0.0`, `v1.2.3`, `v2.0.0`  
Not accepted: `1.0.0` (missing `v`), `v1.0`, `v1.2.3-rc.1`

## How to ship a release

```bash
# 1. Ensure main has the code you want
git checkout main
git pull origin main

# 2. Tag (annotated)
git tag -a v1.2.3 -m "v1.2.3"

# 3. Push tag → triggers Actions "Deploy release (tag)"
git push origin v1.2.3
```

Optional: GitHub → **Releases** → create release from the tag and publish (also triggers deploy).

Manual: Actions → **Deploy release (tag)** → Run workflow → enter `v1.2.3`.

## On the server

After a successful deploy, the droplet has:

```text
/opt/klints_backend/DEPLOY_VERSION   # e.g. v1.0.1
```

Smoke: `GET https://apis.klints.io/health/` → `{"status":"ok"}`.

## Release history (this deposit)

| Tag | Published | Result | Notes |
|-----|-----------|--------|-------|
| [`v1.0.0`](https://github.com/georgechief/DEV_KLINTS_BACKEND/releases/tag/v1.0.0) | 10 Sep 2026 | **Failed health** | First tag-based deploy of the M2 deposit. `web` crash-looped: MVP1 Build Pack was missing from the deposit, so `load_use_case_pilots` failed before gunicorn → nginx **502**. |
| [`v1.0.1`](https://github.com/georgechief/DEV_KLINTS_BACKEND/releases/tag/v1.0.1) | 10 Sep 2026 | **Live** (superseded by next tag) | Build Pack restored ([PR #1](https://github.com/georgechief/DEV_KLINTS_BACKEND/pull/1)); `/health/` **200**. |
| [`v1.0.2`](https://github.com/georgechief/DEV_KLINTS_BACKEND/releases/tag/v1.0.2) | 10 Sep 2026 | **Cutting** | Latest M2 claim amend + M3 OBS (Grafana/Loki/Alloy) deposit; enables `/grafana/` when `DEV_ENV_FILE` includes `GF_*`. |

GitHub Releases: https://github.com/georgechief/DEV_KLINTS_BACKEND/releases  

Do **not** retag an existing version for new code — always bump.
