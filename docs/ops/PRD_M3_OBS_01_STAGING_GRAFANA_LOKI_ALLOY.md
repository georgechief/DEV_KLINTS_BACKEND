# PRD-M3-OBS-01 — Staging Grafana + Loki + Alloy (Docker logs & alerts)

**Status:** Ready for Sahil — **P0 (M3 observability · first M3 engineering slice)**  
**Owner track:** Sahil (`docs/ops/`) — **BE / deploy / ops** (no Klints product FE)  
**Surfaces:** DigitalOcean **staging** Docker stack · GitHub Actions deploy · Grafana Explore + Alerting  
**Milestone:** **M3 Demo, Security & DP1 (T3)** — contract deliverable *Security + observability hardened (… Grafana)*  
**SoT layers (priority when they conflict):**  
1. **Contract** Schedule 1 M3 (Astrapse v1.2) — Grafana named under security + observability  
2. **This PRD** (implementation SoT for OBS-01)  
3. **Existing deploy path** — `.github/workflows/deploy-development.yml` · `docker-compose.yml` · `deploy/scripts/deploy.sh` · `deploy/nginx/klints.conf`  
4. **Code / droplet truth** after merge  

**Locked product decisions (employer · 2026-09-08):**

| # | Decision |
|---|----------|
| D1 | **Staging only** — no requirement to run this stack on every laptop |
| D2 | **Free OSS only** — Grafana OSS + Loki OSS + **Grafana Alloy** (not paid Grafana Cloud; not Prometheus for v1) |
| D3 | **Docker Compose only** — no Kubernetes |
| D4 | **Deploy / test via GitHub workflow** — Sahil learns from and extends `deploy-development.yml` + deploy scripts |
| D5 | **Per-container logs** in Grafana with service filter / dropdown; **ERROR** (and equivalent) visible and attributed correctly |
| D6 | **Separate alerts per Docker service** → email **`noreplyklints@gmail.com`** (sheet / LangSmith account) |
| D7 | **Ops URL only** — **no** Klints app nav / merchant-facing “Open Grafana” link in v1 |
| D8 | **Promtail is EOL** (2026-03-02) — use **Alloy** as the log shipper |

**Out of scope:** Grafana Cloud paid tiers · Prometheus / metrics dashboards (defer M3-OBS-02) · Kubernetes · Klints FE product link · M3-SEC-01 RBAC security review packet · DP1 onboarding · inventing MCP / Matrix flips · local-dev mandatory mirror · multi-region HA Loki  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-M3-OBS-01 — Staging Grafana + Loki + Alloy (Docker logs & alerts).

Read:
- docs/ops/PRD_M3_OBS_01_STAGING_GRAFANA_LOKI_ALLOY.md (this file)
- .github/workflows/deploy-development.yml
- docker-compose.yml
- deploy/scripts/deploy.sh
- deploy/scripts/bootstrap-host.sh
- deploy/nginx/klints.conf

Ship (staging only, free OSS, workflow-deployed):
1. Compose services: loki, alloy, grafana (+ volumes).
2. Alloy scrapes Docker container logs for: web, celery_worker, celery_beat, nginx, redis
   (and obs services themselves if useful).
3. Grafana: Loki datasource, Explore with service/container label dropdown,
   folders/dashboards-as-code for log views, alert rules per service → email
   noreplyklints@gmail.com.
4. Nginx path (or subdomain) for Grafana behind auth — NOT public anonymous.
5. Extend deploy-development.yml smoke to prove Grafana/Loki healthy after deploy.
6. Runbook + verify script. Admin via noreplyklints@gmail.com.

Do NOT: add Klints product UI link · Prometheus · Grafana Cloud billing · Promtail · K8s.
Stop-and-flag if droplet RAM/disk cannot fit the stack — propose slim config before inventing cloud.
Acceptance: §11.
```

---

## 1. Why this PRD exists

| Problem | Effect |
|---------|--------|
| Contract M3 names **Grafana** under hardened observability | Nothing in compose/workflow today is Grafana |
| Staging failures require SSH + `docker compose logs` | Slow, no shared team view, no alerts |
| Employer wants **per-Docker logs + separated alerts** | Needs log aggregation (Loki), not empty Grafana |
| Promtail is EOL | New work must use **Alloy** |
| Must stay **$0 software** and **Docker-only** | Self-host OSS on existing DigitalOcean droplet |

This PRD is the **first M3 engineering slice** for Sahil after GAP-01 (Track B MCP remains parked / client-blocked).

---

## 2. Contract M3 — point to point (OBS slice only)

| # | Contract wording (M3) | Today | This PRD closes |
|---|----------------------|-------|-----------------|
| M3-O1 | Security + observability hardened (**… Grafana**) | No Grafana | **YES** — Grafana live on staging |
| M3-O2 | (Implied) ops can observe staging health | SSH logs only | **YES** — Explore + alerts |
| M3-S1 | RBAC, audit tamper detection | Partial (audit chain exists; RBAC review separate) | **NO** — **M3-SEC-01** |
| M3-D1 | Demo env / DP1 live | Seed exists; DP1 client | **NO** — demo/DP PRDs |

**Honest claim after OBS-01:** “Staging Grafana with Docker log aggregation and per-service alerts” — **not** “full M3 security review passed” and **not** “DP1 live.”

---

## 3. Architecture (staging · Docker Compose)

```text
┌─────────────────────────────────────────────────────────────┐
│ DigitalOcean droplet · docker compose                        │
│                                                              │
│  redis · web · celery_worker · celery_beat · nginx           │
│       │                                                      │
│       │  Docker logs (json-file already configured)          │
│       ▼                                                      │
│  alloy  ──ship──►  loki  ◄──query──  grafana                 │
│                                                              │
│  nginx :443 ──/grafana/──► grafana:3000  (auth required)     │
└─────────────────────────────────────────────────────────────┘
         ▲
         │  GitHub Actions: deploy-development.yml
         │  (push main / workflow_dispatch)
```

### 3.1 Component roles

| Service | Image (pin versions in PR) | Role |
|---------|----------------------------|------|
| **loki** | `grafana/loki` (OSS) | Store + query logs |
| **alloy** | `grafana/alloy` (OSS) | Discover containers / read Docker logs / push to Loki |
| **grafana** | `grafana/grafana` (OSS) | Explore UI, dashboards-as-code, alerting + email |

**Explicitly not in v1:** Prometheus, Tempo, Pyroscope, Grafana Cloud Agent billing, Promtail.

### 3.2 Labels / filters (must work in Explore dropdown)

Every log line shipped to Loki **must** carry stable labels so Grafana Explore can filter:

| Label | Example values | Purpose |
|-------|----------------|---------|
| `service` | `web`, `celery_worker`, `celery_beat`, `nginx`, `redis`, `loki`, `alloy`, `grafana` | Primary dropdown / alert split |
| `container` | Docker container name | Debug |
| `compose_project` | project name | Isolation if multiple stacks |

**Required app services (alerts + Explore):**  
`web` · `celery_worker` · `celery_beat` · `nginx` · `redis`

### 3.3 Log level / ERROR visibility

- Prefer parsing common patterns (`ERROR`, `Error`, `CRITICAL`, `Traceback`, gunicorn/celery fail lines).  
- If structured level is unavailable, still ship **raw lines**; Explore must show them filtered by `service`.  
- Alert rules (§7) use LogQL that matches ERROR-like lines **per service** (separate rules — not one mega-alert).

### 3.4 Retention & resource guardrails (staging)

| Knob | Default for v1 | Notes |
|------|----------------|-------|
| Loki retention | **7–14 days** | Enough for staging; protect disk |
| Loki storage | Local volume on droplet | No S3 required for v1 |
| Alloy | Single instance | Docker socket read (document security note) |
| Grafana users | Admin = `noreplyklints@gmail.com` | Invite Rohan / Sahil as editors/viewers |

**Stop-and-flag** if droplet free disk &lt; ~5 GB or RAM cannot add ~512 MB–1 GB for obs services — propose: shorter retention, single-binary Loki monorepo config, or move Grafana-only to a tiny sibling droplet **before** inventing Cloud.

---

## 4. Access model (D7)

| Item | v1 decision |
|------|-------------|
| Public anonymous Grafana | **Forbidden** |
| Klints product UI link | **Out of scope** |
| URL | Prefer `https://apis.klints.io/grafana/` (nginx path) **or** `grafana.apis.klints.io` if DNS/TLS easy — pick one in Phase 1 and document |
| Auth | Grafana native admin + password **or** Google OAuth if cheap to wire with `noreplyklints@gmail.com`; minimum = strong admin password in GitHub Secret / `.env` |
| Who | Ops / engineering team only (Rohan, Sahil, employer) |
| Merchants / tenants | **No access** |

Nginx must **not** expose Grafana without auth. Do not publish `:3000` on the public host firewall.

---

## 5. Email / identity (D6)

| Use | Value |
|-----|-------|
| Grafana admin identity / recovery | **`noreplyklints@gmail.com`** |
| Alert notification email | **`noreplyklints@gmail.com`** |
| SMTP | Use existing transactional mail path **or** Gmail SMTP app password / SES — document chosen path in runbook; store secrets in `DEV_ENV_FILE` / GitHub Secrets only |

**Stop-and-flag** if SMTP cannot send from staging — still ship Explore + dashboards; mark alert email as blocked with evidence, do not fake “alerts working.”

---

## 6. Deploy / workflow integration (D4) — primary delivery path

Sahil must treat **GitHub Actions as the SoT for “it works on staging.”**

### 6.1 Existing path (do not break)

| File | Role today |
|------|------------|
| `.github/workflows/deploy-development.yml` | On `main` push / `workflow_dispatch`: rsync → `.env` → bootstrap → `deploy.sh` → HTTPS `/health/` smoke |
| `deploy/scripts/deploy.sh` | `docker compose` build/up + TLS |
| `docker-compose.yml` | `redis`, `web`, `celery_worker`, `celery_beat`, `nginx` |
| `deploy/nginx/klints.conf` | Proxy to `web:8000` |

### 6.2 Required changes

| Change | Detail |
|--------|--------|
| `docker-compose.yml` | Add `loki`, `alloy`, `grafana` + volumes; logging stays json-file |
| `deploy/grafana/` (new) | Provisioning: datasources, dashboards, alerting contact points / policies (as code) |
| `deploy/loki/` (new) | `loki-config.yml` (filesystem store, retention) |
| `deploy/alloy/` (new) | Alloy config: Docker discovery → Loki push |
| `deploy/nginx/klints.conf` | Location `/grafana/` (or dedicated server block) → `grafana:3000` with correct subpath headers |
| `.env.example` | Document `GF_SECURITY_ADMIN_USER`, `GF_SECURITY_ADMIN_PASSWORD`, `GF_SERVER_ROOT_URL`, SMTP vars, Loki URL |
| `deploy-development.yml` | After health smoke: curl Grafana login or `/api/health` **through nginx**; fail job if obs stack down |
| `scripts/verify_m3_obs01_backend.py` (or `.sh`) | Static asserts: compose services present, config files exist, nginx path, workflow smoke step present, no Promtail |

### 6.3 Workflow test discipline

| Gate | How |
|------|-----|
| PR | Static verify script green; compose config validated (`docker compose config`) where CI can run Docker |
| Merge to `main` | Deploy workflow runs; Sahil watches Actions |
| Manual | `workflow_dispatch` redeploy after secret/config tweaks |
| Proof | Screenshot or export: Explore filtered by `service=web` + one alert rule list |

**Do not** invent a second deploy system (Portainer-only, manual `scp` of Grafana zip, etc.) as the primary path.

---

## 7. Alerting requirements (D5 + D6)

### 7.1 Separate alerts per service (mandatory)

Create **one alert rule (or rule group) per service** below — not a single “any error anywhere” rule:

| Alert name (example) | Filter | Intent |
|----------------------|--------|--------|
| `staging-logs-error-web` | `service="web"` + ERROR-like | API / Django failures |
| `staging-logs-error-celery_worker` | `service="celery_worker"` | Import / writeback / tasks |
| `staging-logs-error-celery_beat` | `service="celery_beat"` | Scheduler failures |
| `staging-logs-error-nginx` | `service="nginx"` | Proxy / TLS / 5xx noise (tune threshold) |
| `staging-logs-error-redis` | `service="redis"` | Broker instability |

Optional (nice): `loki` / `alloy` / `grafana` self-health alerts.

### 7.2 Alert behavior

| Knob | v1 |
|------|-----|
| Destination | Email → `noreplyklints@gmail.com` |
| Pending period | Short for staging (e.g. 2–5 min) — avoid flapping on one-line Tracebacks if needed |
| Dedup / grouping | Group by `service` label |
| Silence | Document how to silence during deploys |

### 7.3 Proof of “errors recorded correctly”

Acceptance needs a **controlled induce** (staging only):

1. Trigger a benign ERROR in `web` (e.g. hit a debug path or temporary log line in a verify job — **prefer non-destructive**; do not corrupt tenant data).  
2. Confirm line appears in Explore under `service=web`.  
3. Confirm **web** alert can fire (or evaluate pending) without firing **redis** alert for the same event.

---

## 8. Grafana UX minimum (Explore + dashboards)

| Item | Requirement |
|------|-------------|
| Explore | Loki datasource default; filter by `service` (dropdown / label browser) |
| Dashboard “Staging Docker Logs” | Rows or repeating panels per service **or** one panel with service variable |
| Dashboard “Errors only” | LogQL restricted to ERROR-like across services with `service` legend |
| Time range | Default last 1h; support last 24h |
| Provisioning | Dashboards + datasource **as code** under `deploy/grafana/` so redeploy does not wipe them |

---

## 9. Security notes (honest · not M3-SEC-01)

| Topic | Requirement |
|-------|-------------|
| Docker socket to Alloy | Document risk; Alloy container read-only socket where possible; no public Alloy port |
| Grafana secrets | Admin password only in secrets / `.env`; never commit |
| Log PII | Staging may contain emails / tokens in logs — restrict Grafana access; do not paste prod secrets into chat |
| Audit chain | Unchanged; this PRD does **not** replace audit tamper detection |

---

## 10. Build order (phases)

Do **not** skip ahead. One branch: `feature/m3-obs-01-grafana-loki-alloy`.

```text
Phase 0  Pre-flight (droplet disk/RAM, workflow read-through)
  ↓
Phase 1  Loki + Alloy + Grafana in compose (local compose config validate OK)
  ↓
Phase 2  Labels + Explore proof (service dropdown works)
  ↓
Phase 3  Nginx path + auth + GF_SERVER_ROOT_URL
  ↓
Phase 4  Dashboards-as-code + per-service alert rules + email
  ↓
Phase 5  Workflow smoke + verify script + runbook
  ↓
Phase 6  Staging induce ERROR + employer demo checklist
```

### Phase 0 — Pre-flight

| # | Task | Done |
|---|------|------|
| 0.1 | Read this PRD + `deploy-development.yml` + `deploy.sh` + current `docker-compose.yml` | [x] |
| 0.2 | SSH or ask Rohan: free disk / RAM on staging droplet; note numbers in PR | [x] **Deploy SSH on `main` workflow**; disk/RAM paste optional |
| 0.3 | Confirm admin email **`noreplyklints@gmail.com`** access for password reset / inbox alerts | [x] Target locked; **mailer API** in Sahil env (`MAILER_API_*`) — Phase 4 wires Grafana |
| 0.4 | Choose URL mode: path `/grafana/` **vs** subdomain (document choice) | [x] **LOCKED:** `https://apis.klints.io/grafana/` |
| 0.5 | Branch `feature/m3-obs-01-grafana-loki-alloy` | [x] |

**Exit:** Resource note + URL mode locked; branch ready.  
**Phase 0 notes:** `docs/ops/M3_OBS_01_PHASE_0.md` — URL locked `/grafana/`; deploy SSH via `main` workflow; mailer API confirmed for Phase 4 alerts. **Phase 0 complete** → Phase 1 compose.

### Phase 1 — Compose stack

| # | Task | Done |
|---|------|------|
| 1.1 | Add `loki` service + config + volume | [x] |
| 1.2 | Add `alloy` service + Docker log pipeline → Loki | [x] |
| 1.3 | Add `grafana` service + admin env from `.env` | [x] |
| 1.4 | Pin image tags (no `:latest` in final PR) | [x] `loki:3.5.1` · `alloy:v1.9.2` · `grafana:11.6.1` |
| 1.5 | `docker compose config` validates | [x] Static verify PASS · WSL `docker compose config --quiet` → CONFIG_OK (services include loki/alloy/grafana) |

**Exit:** Stack defined; configs in repo.  
**Phase 1 notes:** `docs/ops/M3_OBS_01_PHASE_1.md`

### Phase 2 — Labels + Explore

| # | Task | Done |
|---|------|------|
| 2.1 | Confirm `service` label on all five app services | [x] `klints.obs.service` on web/celery_worker/celery_beat/nginx/redis + Alloy map |
| 2.2 | Grafana Loki datasource provisioned | [x] `uid: loki` · default · `http://loki:3100` |
| 2.3 | Explore can filter each service | [x] Config: LogQL + service dropdown dashboard · **Live screenshot** after Phase 3 / staging (PR exit) |

**Exit:** Screenshot/notes in PR for Explore filters.  
**Phase 2 notes:** `docs/ops/M3_OBS_01_PHASE_2.md` — in-repo filters ready; attach Explore screenshot when Grafana URL is live.

### Phase 3 — Edge access

| # | Task | Done |
|---|------|------|
| 3.1 | Nginx proxies Grafana with correct subpath/headers | [x] `/grafana/` → `klints_grafana` + Forwarded/Upgrade |
| 3.2 | No anonymous access; login required | [x] anonymous off · no host `:3000` |
| 3.3 | TLS via existing Let’s Encrypt path still green for `/health/` | [x] `/health/` locations kept (HTTP+HTTPS) |

**Exit:** HTTPS Grafana URL works after deploy.  
**Phase 3 notes:** `docs/ops/M3_OBS_01_PHASE_3.md` — config ready; live login proof after PR merge / workflow deploy.

### Phase 4 — Dashboards + alerts

| # | Task | Done |
|---|------|------|
| 4.1 | Provision “Staging Docker Logs” + “Errors” dashboards | [x] Logs + `m3-obs-staging-errors` |
| 4.2 | Contact point email → `noreplyklints@gmail.com` | [x] webhook → `obs_alert_mailer` → `MAILER_API_*` |
| 4.3 | Five separate service ERROR alert rules | [x] `staging-logs-error-{web,celery_worker,celery_beat,nginx,redis}` |
| 4.4 | Document silence / mute during deploy | [x] `M3_OBS_01_PHASE_4.md` §4.4 |

**Exit:** Alerts configured; email path proven or stop-and-flagged.  
**Phase 4 notes:** `docs/ops/M3_OBS_01_PHASE_4.md` — config ready; live mail proof after staging induce (Phase 6) or stop-and-flag.

### Phase 5 — Workflow + verify

| # | Task | Done |
|---|------|------|
| 5.1 | Extend `deploy-development.yml` smoke for Grafana/Loki health | [x] health JSON + login/Explore auth gate + Loki `/ready` via web Python |
| 5.2 | Add `scripts/verify_m3_obs01_*.py` (or shell) static gate | [x] `scripts/verify_m3_obs01_backend.py` Phase 1–5 |
| 5.3 | Runbook: `docs/ops/M3_OBS_01_RUNBOOK.md` (login, Explore, alerts, redeploy) | [x] |
| 5.4 | Update `docs/ops/README.md` build-order row | [x] |

**Exit:** Merge-ready; workflow is the test/deploy proof.  
**Phase 5 notes:** `docs/ops/M3_OBS_01_PHASE_5.md` — config ready; live Actions green after merge (Phase 6).

### Phase 6 — Staging acceptance demo

| # | Task | Done |
|---|------|------|
| 6.1 | Deploy via workflow (`main` or `workflow_dispatch`) | [ ] After PR merge — Actions SoT |
| 6.2 | Induce / observe ERROR under `service=web` | [x] prep: gated POST `/ops/m3-obs-01/induce-error/` + command · **live observe after deploy** |
| 6.3 | Confirm other service alerts do not false-fire for that event | [ ] Live confirm after induce |
| 6.4 | Employer checklist (§11) signed off in PR comment | [x] template in `M3_OBS_01_PHASE_6.md` · **sign-off after live** |

**Exit:** Staging demo evidence + checklist in PR.  
**Phase 6 notes:** `docs/ops/M3_OBS_01_PHASE_6.md` — induce marker `M3-OBS-01-INDUCE-WEB`; employer §11 paste block.

---

## 11. Acceptance criteria

### 11.1 Must pass

- [ ] **A1** — `loki`, `alloy`, `grafana` defined in `docker-compose.yml` with pinned tags and volumes  
- [ ] **A2** — Staging deploy via **`deploy-development.yml`** brings obs stack up without breaking `https://apis.klints.io/health/`  
- [ ] **A3** — Grafana reachable on chosen HTTPS ops URL; **login required**  
- [ ] **A4** — Explore: filter logs by **`service`** for `web`, `celery_worker`, `celery_beat`, `nginx`, `redis`  
- [ ] **A5** — ERROR-like lines for a service appear under **that** service filter  
- [ ] **A6** — **Separate** alert rules exist per those five services  
- [ ] **A7** — Alert email target configured to **`noreplyklints@gmail.com`** (send proven **or** SMTP blocked with stop-and-flag note)  
- [ ] **A8** — Dashboards + datasource **provisioned as code** (survive redeploy)  
- [ ] **A9** — Workflow smoke checks obs health; verify script green  
- [ ] **A10** — Runbook merged; **no** Klints product UI link; **no** Promtail; **no** Prometheus required  

### 11.2 Explicit non-acceptance

- Grafana Cloud free-tier-only demo with no staging Docker ship  
- Opening `:3000` on the public internet without auth  
- One combined alert for all services  
- Claiming M3 security review / DP1 / full observability platform  
- Using EOL Promtail as the shipper  

---

## 12. PR / branch hygiene

| Item | Value |
|------|-------|
| Branch | `feature/m3-obs-01-grafana-loki-alloy` |
| PR title | `feat(M3-OBS-01): Staging Grafana + Loki + Alloy log alerts` |
| PR body must state | Staging only · free OSS · Alloy not Promtail · no product UI link · alerts → `noreplyklints@gmail.com` · workflow is deploy SoT |
| Review | Rohan — check workflow smoke + Explore filters + alert separation |
| Merge order | Single BE PR preferred (compose + nginx + workflow + docs). No FE PR. |

---

## 13. Runbook outline (ship as `M3_OBS_01_RUNBOOK.md`)

Must include:

1. URL + how to log in (`noreplyklints@gmail.com` admin)  
2. Explore: pick `service` → find errors  
3. Where alert rules live / how to silence  
4. How deploy workflow rolls this out  
5. Common failures: disk full, Alloy cannot read docker.sock, Grafana subpath 404, SMTP fail  
6. What this is **not** (SEC-01, DP1, Prometheus)  

---

## 14. Follow-ons (do not expand this PRD)

| ID | Topic |
|----|--------|
| **M3-OBS-02** | Prometheus metrics / RED dashboards (optional) |
| **M3-SEC-01** | RBAC + tenant isolation evidence + security review packet |
| **M3-DEMO-01** | Oct demo path / DP1 live support |
| GAP-01 Slice B | Track B MCP (still client-blocked) |

---

## 15. Traceability

| Field | Value |
|-------|--------|
| Contract | Schedule 1 **M3** — Security + observability hardened (RBAC, audit tamper detection, **Grafana**) |
| Milestone payment | T3 USD 3,000 (M3 acceptance — OBS-01 is **necessary but not sufficient** alone) |
| Parent | M2 GAP-01 mostly closed; MCP parked |
| Owner | Sahil |
| Gmail SoT | `noreplyklints@gmail.com` (AI-01 / sheet) |
| Deploy SoT | `.github/workflows/deploy-development.yml` |

---

## 16. Theater / overclaim register

| Do not claim | Actual after OBS-01 |
|--------------|---------------------|
| “Full M3 done” | Only Grafana/log observability slice |
| “Security review passed” | SEC-01 later |
| “Prometheus monitoring” | Not in v1 |
| “Merchant can open Grafana in Klints” | Ops URL only |
| “Promtail pipeline” | Alloy |

---

**YOU BUILD NEXT:** Phase 0 → Phase 1 compose → workflow-deployed staging proof → alerts email.  
**SKIP:** Prometheus · K8s · product UI link · Promtail · Grafana Cloud paid · SEC/DP1 scope creep.
