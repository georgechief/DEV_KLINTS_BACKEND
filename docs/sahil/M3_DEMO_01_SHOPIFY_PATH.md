# M3-DEMO-01 — Shopify path (live klints-dev)

**PRD:** [PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md](./PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md)  
**Phase lock:** [M3_DEMO_01_PHASE_0.md](./M3_DEMO_01_PHASE_0.md) · [M3_DEMO_01_PHASE_1.md](./M3_DEMO_01_PHASE_1.md)  
**SoT:** Live Shopify **klints-dev** + Simple Sample Data → Klints OAuth → [DCS-10](./PRD_DCS_10_FRESH_IMPORT_BEFORE_SCORE.md) fresh import  

**Not this path:** [GAP_01F_DEMO_PATH.md](./GAP_01F_DEMO_PATH.md) / `seed_demo_tenant` — offline local smoke only, **not** M3 AC.  
**Not this PRD:** Grafana → [PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md](./PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md)

---

## 0. Credential checklist (ops)

Confirm before staging smoke (do **not** commit secrets):

| Key / item | Purpose / expected |
|------------|-------------------|
| `SHOPIFY_API_KEY` / `SHOPIFY_API_SECRET` | Partners app for klints-dev |
| `SHOPIFY_SCOPES` | `read_customers,write_customers,read_orders,read_products,read_inventory,read_locations,read_store_credit_account_transactions` |
| `SHOPIFY_OAUTH_REDIRECT_URI` | Local: ngrok callback · Staging: `https://apis.klints.io/api/v1/connectors/shopify/callback/` |
| `FRONTEND_SHOPIFY_REDIRECT_URL` | Local: `http://localhost:8080/integrations` · Staging: `https://klints-frontend.vercel.app/integrations` |
| Shopify Admin access | Operator can open [Simple Sample Data](https://admin.shopify.com/store/klints-dev/apps/simple-sample-data) |
| Manago connector | Connected **or** stop-and-flag (do not seed-fake Manago) |
| Celery worker | Running so DCS / bootstrap tasks complete |

After changing `SHOPIFY_SCOPES`: **reconnect Shopify** in Klints (token must re-grant).

---

## 1. Generate sample data in Shopify

1. Open [Shopify Admin → klints-dev → Simple Sample Data](https://admin.shopify.com/store/klints-dev/apps/simple-sample-data)  
2. Generate **customers** and **orders** (target ~5k contacts if the app allows; if capped lower, note the **actual** count)  
3. In Shopify Admin, spot-check that customers/orders exist  

Record:

| Field | Value |
|-------|--------|
| Customers (approx) | **189** (local 2026-09-15; growing via Simple Sample Data) |
| Orders (approx) | **250** (local 2026-09-15) |
| Date | 2026-09-15 |
| Staging | _pending — repeat on apis.klints.io_ |

---

## 2. Connect shop to Klints

1. Sign in to Klints (staging or local) on the **demo / target workspace** (live tenant — **not** `demo@example.com` seed login)  
2. Go to **Connected stack** → `/integrations`  
3. **Connect Shopify** → authorize **klints-dev**  
4. Expect status **connected** (or **degraded** only for real warns: empty window, explicit truncation notes, etc.)  
   - Exact order counts that are multiples of 250 are **not** treated as truncated (client paginates fully)  
5. Confirm **Manago.ai** connected (or document stop-and-flag)

---

## 3. Fresh import + DCS score

1. Go to **Data Consistency Score** → `/data-consistency`  
2. Click **Re-run checks** (triggers [DCS-10](./PRD_DCS_10_FRESH_IMPORT_BEFORE_SCORE.md) fresh import for connected Shopify ± Manago)  
3. Wait for Celery / UI to finish  
4. Confirm:  
   - Import succeeded for Shopify (and Manago if connected)  
   - Headline score appears (may be low / `INCOMPLETE` — honest)  
   - Contact/order volume moved with sample data  

Record:

| Field | Value |
|-------|--------|
| Headline score | **43.549** (local 2026-09-15) |
| run_state | **INCOMPLETE** |
| Shopify contacts imported (bootstrap/UI) | **189** |
| Shopify orders imported | **250** |
| Manago status | **connected** (~2k+ in Manago; mismatch vs Shopify expected) |
| Fresh import on DCS | Shopify OK · Manago OK (Celery) |
| Staging repeat | _pending_ |

### API evidence (local 2026-09-15)

`GET /api/v1/connectors/` → Shopify row:

| Field | Expected (local) |
|-------|------------------|
| `latest_bootstrap.contacts` | **189** |
| `latest_bootstrap.orders` | **250** |
| `latest_bootstrap.summary_status` | **ok** |
| `latest_bootstrap.issue_count` | **0** |
| `last_data_refresh.source` | `dcs_fresh_import` |
| `status` | **connected** |

Counts come from import metadata, not seed script. After Phase 2 deploy, display recomputes health from snapshot so exact page-size windows (250 orders) are not falsely degraded.

---

## 4. Where contacts show in Klints

| Surface | Route | Expect |
|---------|-------|--------|
| Integrations stats | `/integrations` | Shopify card shows recent run / counts when available |
| Data Consistency | `/data-consistency` | Score + worklist from imported data |
| Fix | `/fix` | FAIL/WARN from live checks (not seed corpus) |

Contacts come from **import**, not from `seed_demo_tenant`.

---

## 5. Rest of product path (honest)

Full detail: [M3_DEMO_01_PHASE_4.md](./M3_DEMO_01_PHASE_4.md)

| Step | Route | Expect on live klints-dev (local 2026-09-15) |
|------|-------|-----------------------------------------------|
| Connect / Score | `/integrations` · `/data-consistency` | Connected · **43.549** · 42 live checks |
| Fix | `/fix` | **15 FAIL** · **1 WARN** from live DCS (not seed) |
| Opportunities | `/opportunities` | **0 ready** · **16** `blocked_dcs_score` · **9** gap_suggested |
| Studio | `/workflow?uc=UC-02` | Blueprint loads · **Needs higher score** · Generate disabled |
| Lifecycle | `/lifecycle` | Architecture **INCOMPLETE** (12 gaps) |
| QA | `/qa` | Empty — **0** build packages |
| Handoff | `/handoff` | Empty until QA PASS |
| Handoff Send | `/handoff` | **Human** (HO-02) — no MCP |

DEMO-01 acceptance = **sample data → connect → import → contacts visible**. Green Studio is **not** required if score stays below 70.

**Not this path:** [GAP_01F_DEMO_PATH.md](./GAP_01F_DEMO_PATH.md) (`seed_demo_tenant` ~61 — offline, not M3 AC).

---

## 6. Troubleshooting

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| Refresh token inactive | Token expired / revoked | Reconnect Shopify on `/integrations` |
| `read_locations` 403 | Scope missing on token | Update `SHOPIFY_SCOPES`, reconnect |
| Degraded + PARTIAL_FETCH | Snapshot notes say truncated/partial | Retry bootstrap; check import logs |
| Degraded + EMPTY_*_WINDOW | No contacts/orders in window | Add sample data / widen window |
| DCS fails Shopify fresh import | Auth / scopes | Reconnect; check Celery error |
| Score low with Manago ~2k / Shopify thin | Cross-system mismatch | Expected; grow Shopify sample or document honesty |
| Using seed login / stub connectors | Wrong SoT | Stop — use live OAuth path for M3 |
| post_bootstrap DCS skipped `queue_unavailable` | Celery/queue hiccup | Re-run checks from `/data-consistency` with worker up |

---

## 7. Theater register (do not claim)

| Do not claim | Why |
|--------------|-----|
| Contacts filled by `seed_demo_tenant` for M3 | Wrong SoT |
| Exact 5k if app cannot | Document actual |
| Studio/QA/Handoff complete at score &lt; 70 | Gate honesty |
| Grafana done here | OBS-01B |
| MCP publish / Gate B partner PII | Out of scope |
