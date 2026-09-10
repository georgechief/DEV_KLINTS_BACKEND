# Releases & deploy (DEV_KLINTS_BACKEND)

Staging deploy is **tag-driven**. Pushing to `main` does **not** deploy.

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

Optional: GitHub → **Releases** → create release from `v1.2.3` and publish (also triggers deploy).

Manual: Actions → **Deploy release (tag)** → Run workflow → enter `v1.2.3`.

## On the server

After a successful deploy, the droplet has:

```text
/opt/klints_backend/DEPLOY_VERSION   # e.g. v1.2.3
```

## Workflow file

`.github/workflows/deploy-development.yml` — name: **Deploy release (tag)**
