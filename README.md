# Klints Backend

Django API backend for Klints. Project root is this repository; settings live under `core`.

## Layout

```
klints_backend/
├── manage.py
├── core/                 # project package + shared settings
│   ├── celery.py         # Celery app
│   ├── tasks.py          # setup / health tasks
│   ├── settings/
│   │   ├── base.py
│   │   ├── local.py
│   │   └── production.py
│   ├── urls.py
│   ├── views.py
│   ├── wsgi.py
│   └── asgi.py
├── tenants/              # + tenants/tasks.py
├── dataruns/             # + dataruns/tasks.py
├── .env.example
└── requirements.txt
```

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set SECRET_KEY
python manage.py migrate
python manage.py runserver
```

- Health: `GET /health/`
- Admin: `/admin/`
- Tenants API: `/api/v1/tenants/`
- Data runs API: `/api/v1/dataruns/`

## Celery + Redis

### 1. Install & run Redis

**macOS (Homebrew):**
```bash
brew install redis
brew services start redis
# or foreground: redis-server
```

**Docker:**
```bash
docker run -d --name klints-redis -p 6379:6379 redis:7-alpine
```

Verify:
```bash
redis-cli ping   # → PONG
```

### 2. Env (already in `.env.example`)

```
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=django-db
REDIS_URL=redis://127.0.0.1:6379/1
CELERY_TASK_ALWAYS_EAGER=False
```

### 3. Migrate Celery tables

```bash
source .venv/bin/activate
python manage.py migrate
```

### 4. Start processes (3 terminals)

```bash
# Terminal 1 — Django
python manage.py runserver

# Terminal 2 — Celery worker
celery -A core worker -l info

# Terminal 3 — Celery beat (periodic tasks)
celery -A core beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

Optional flower monitor:
```bash
pip install flower
celery -A core flower
# → http://127.0.0.1:5555
```

### 5. Smoke-test a task

```bash
python manage.py shell
```

```python
from core.tasks import ping, health_check
from dataruns.tasks import process_data_run

ping.delay().get(timeout=5)
health_check.delay().get(timeout=5)
```

### Built-in tasks

| Task | Module | Purpose |
|------|--------|---------|
| `core.ping` | `core.tasks` | Broker smoke test (also scheduled every 5 min) |
| `core.health_check` | `core.tasks` | Cache + broker health |
| `tenants.deactivate_inactive` | `tenants.tasks` | Example maintenance job |
| `dataruns.process_data_run` | `dataruns.tasks` | Process a `DataRun` by id |
| `dataruns.dispatch_daily_dcs_scores` | `dataruns.tasks` | Daily Beat dispatcher (15:00 IST) |
| `dataruns.run_dcs_score` | `dataruns.tasks` | DCS score worker per company |

**Daily DCS schedule:** Celery Beat runs `dataruns.dispatch_daily_dcs_scores` every day at **15:00 Asia/Kolkata (IST)** via `TzAwareCrontab` in `CELERY_BEAT_SCHEDULE`. `DatabaseScheduler` syncs the same entry into django-celery-beat Admin (same pattern as `core-ping`).

```bash
celery -A core beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

The dispatcher enqueues one `run_dcs_score` task per company with a connected or degraded Shopify and/or Manago connector.

**On-connect DCS:** after a connector **bootstrap** succeeds, if the company has **both** Shopify and Manago `connected|degraded` with succeeded bootstraps, the worker also enqueues `run_dcs_score` (`triggered_by=post_bootstrap`). Connecting only one connector does not start DCS.

**DCS master data:** score runs load check/dimension/root-cause definitions from DB tables (`check_masters`, `dimension_masters`, `root_cause_masters`). Seed before first score:

```bash
python manage.py seed_dcs_master
```

Restart Celery workers after re-seeding so cached master lookups refresh.

Enqueue a data run:
```python
from dataruns.tasks import process_data_run
process_data_run.delay(data_run_id)
```

## Settings

| Module | Use |
|--------|-----|
| `core.settings.local` | Local development (default for `manage.py`) |
| `core.settings.production` | Deploy / gunicorn / ASGI |

```bash
DJANGO_SETTINGS_MODULE=core.settings.production gunicorn core.wsgi:application
```

Set `DATABASE_URL` for Postgres (falls back to SQLite when unset):

```
DATABASE_URL=postgres://user:password@localhost:5432/klints
```

## Tests

```bash
python manage.py test
```

Celery tests run with `CELERY_TASK_ALWAYS_EAGER` so Redis is not required for `manage.py test`.
