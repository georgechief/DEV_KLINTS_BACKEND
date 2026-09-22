# PRD-M3-DEMO-01 — Live Shopify Demo Contacts (klints-dev)

**Status:** **Sahil ship DONE** (2026-09-15) — **P0 (M3)** · staging A2/A10 residual · **Separate from Grafana**  
**Owner track:** Sahil (`docs/sahil/`) — **live Shopify connect + import + demo path evidence**  
**Surfaces:** Shopify OAuth · DCS fresh import (DCS-10) · Integrations UI · demo walkthrough  
**Milestone:** **M3 Demo & DP1** — contacts come from **real Shopify**, not `seed_demo_tenant` script  
**Shopify demo shop:** [klints-dev · Simple Sample Data](https://admin.shopify.com/store/klints-dev/apps/simple-sample-data)  
**SoT layers:**  
1. Contract M3 demo / DP1  
2. **This PRD**  
3. DCS-10 fresh import · connector auth · HO-02 human Send  
4. Code truth after merge  

**Locked product decisions (employer · 2026-09-14):**

| # | Decision |
|---|----------|
| D1 | **Contacts are filled from Shopify** — use **klints-dev** store + **Simple Sample Data** app to generate sample customers/orders in Shopify, then **Klints import** pulls them |
| D2 | **`seed_demo_tenant` is NOT the M3 demo AC** — offline script may remain for local smoke only; do **not** claim M3 demo via script corpus |
| D3 | **Grafana is a separate PRD** — [M3-OBS-01B](./PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md); do not mix alert work here |
| D4 | Demo tenant/company on staging connects to **klints-dev** via normal Shopify OAuth (scopes as configured) |
| D5 | After sample data exists in Shopify → **Run score / DCS** must **fresh-import** (DCS-10) so contacts appear in Klints |
| D6 | Manago: connect if required for score gates; if Manago blocked, **stop-and-flag** (do not fake Manago via seed) |
| D7 | Handoff Send stays **human** (HO-02) — no MCP |
| D8 | Honest claim: *demo path uses live Shopify klints-dev sample data + Klints import* — **not** “production DP1 live with partner PII” unless Gate B + partner agree |

**Out of scope:** Grafana alerts · SEC-01 rebuild · offline 5k script as primary demo · inventing MCP · Gate B legal · pen-test  

**Progress:** [WORKING_GAPS](./M3_DEMO_01_WORKING_GAPS.md) · [PHASE_0](./M3_DEMO_01_PHASE_0.md)–[PHASE_6](./M3_DEMO_01_PHASE_6.md) · [SHOPIFY_PATH](./M3_DEMO_01_SHOPIFY_PATH.md) · **Sahil ship ready for PR** · staging residual → Rohan

---

## 0. Cursor agent brief

```text
Implement PRD-M3-DEMO-01 — Live Shopify Demo Contacts (klints-dev).

Read:
- docs/sahil/PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md
- docs/sahil/M3_DEMO_01_WORKING_GAPS.md
- docs/sahil/PRD_DCS_10_FRESH_IMPORT_BEFORE_SCORE.md
- docs/sahil/GAP_01F_DEMO_PATH.md (legacy offline — cite as non-AC)
- Shopify shop: klints-dev + Simple Sample Data app
  https://admin.shopify.com/store/klints-dev/apps/simple-sample-data

Ship:
1. Runbook: generate sample data in Shopify Simple Sample Data → connect klints-dev to staging Klints → fresh import / DCS → contacts visible
2. Docs: M3_DEMO_01_SHOPIFY_PATH.md (step-by-step)
3. Fix any BE/FE holes that block live import from this shop (flag Rohan for app credentials / scopes)
4. verify_m3_demo01_backend.py — docs + no “seed script is M3 AC” claim; theater register
5. Optional: assert contact count / import metadata after a staging smoke (evidence in Phase 6)
6. Do NOT make seed_demo_tenant the primary demo path
7. Do NOT work Grafana alerts here (OBS-01B)

Acceptance: §11.
```

---

## 1. Why this PRD exists (simple)

We need a **real demo**: open Shopify, generate sample customers with **Simple Sample Data**, connect that shop to Klints, import, score — so contacts in Klints match Shopify.

We are **not** filling contacts with a Python seed script for the M3 claim.

Grafana alerts are **another** PRD (OBS-01B).

---

## 2. Happy path (operator)

1. Open [Shopify Admin → klints-dev → Simple Sample Data](https://admin.shopify.com/store/klints-dev/apps/simple-sample-data)  
2. Generate **sample customers / orders** (enough volume for a credible demo; target order-of-magnitude **~5k contacts** if the app supports it — if cap is lower, document actual count and stop-and-flag if contract needs exact 5k)  
3. On Klints staging: create/use demo workspace → **Connect Shopify** to **klints-dev** (OAuth)  
4. **Run Data Consistency Score** (triggers **fresh import** per DCS-10)  
5. Confirm contacts/orders visible in Klints and score is honest  
6. Walk Fix → Studio → QA → Handoff as product allows (human Send)  
7. Capture checklist / Loom evidence  

---

## 3. Contract point-to-point

| # | Need | This PRD |
|---|------|----------|
| M3-D1 | Demo env with substantial contact volume | **YES** — via Shopify sample data + import (document achieved count) |
| M3-D2 | Demo path connect→score→fix→… | **YES** — live Shopify path |
| M3-D3 | DP1 live | **Readiness** using same connect/import pattern; partner cutover still Gate B |
| M3-O1 | Grafana | **NO** — OBS-01B |

---

## 4. Reuse (do not rebuild)

| Asset | Role |
|-------|------|
| Shopify connector + OAuth | Live connect |
| DCS-10 fresh import | Pull contacts into Klints |
| Integrations / DCS / Fix UI | Demo path |
| HO-02 | Human Send |
| `seed_demo_tenant` | **Local smoke only** — not M3 AC |
| GAP_01F path doc | Legacy offline reference |

---

## 5. Gaps

| Gap | Status |
|-----|--------|
| G1 Runbook for Simple Sample Data → Klints import | **Done** — [M3_DEMO_01_SHOPIFY_PATH.md](./M3_DEMO_01_SHOPIFY_PATH.md) |
| G2 Staging OAuth to klints-dev works | **Residual ops** / Rohan (local reconnect works) |
| G3 Fresh import brings sample customers into Klints | **Local done** (189) · A3 local-only accept · staging residual |
| G4 Documented contact count vs ~5k target | **Done** (189 Shopify / ~2k Manago; not 5k) |
| G5 Manago dependency for score | **Connected** ~2k+ · documented |
| G6 `verify_m3_demo01_backend.py` | **Done** — [PHASE_5](./M3_DEMO_01_PHASE_5.md) |
| G7 Full path + DP1 readiness | **Done** — [PHASE_4](./M3_DEMO_01_PHASE_4.md) |
| G8 FE honesty if import/score copy wrong | Optional |
| G9 §11 Sahil ship | **Done** — [PHASE_6](./M3_DEMO_01_PHASE_6.md) local-only A3 |
| G9b staging A2 + A10 | Residual post-merge |

---

## 6. Phases

| Phase | Work |
|-------|------|
| 0 | Lock shop URL, app, scopes, staging callback URLs with Rohan |
| 1 | Runbook + credential checklist |
| 2 | Fix connect/import holes if any |
| 3 | Staging smoke: sample data → import → contacts + score evidence |
| 4 | Full path notes (Fix/Studio/QA/Handoff) + DP1 readiness paragraph |
| 5 | Verify script + theater register |
| 6 | Employer §11 + Loom/checklist |

---

## 7. Employer acceptance (§11)

- [x] **A1** — Runbook uses [Simple Sample Data on klints-dev](https://admin.shopify.com/store/klints-dev/apps/simple-sample-data)  
- [ ] **A2** — Staging Klints connected to klints-dev via OAuth — **residual ops** (local proven)  
- [x] **A3** — Fresh import / DCS pulls Shopify sample contacts — **local-only accept** (189/250 · [PHASE_3](./M3_DEMO_01_PHASE_3.md)); staging residual  
- [x] **A4** — Demo path documented without claiming script seed as AC  
- [x] **A5** — `verify_m3_demo01_backend.py` PASS  
- [x] **A6** — Grafana work not mixed in; points to OBS-01B  
- [x] **A7** — No MCP / Gate B closed / pen-test claims  
- [x] **A8** — Manago status honest (connected)  
- [x] **A9** — Phase notes + WORKING_GAPS updated  
- [ ] **A10** — Rohan review — **residual**  

Full paste block: [PHASE_6](./M3_DEMO_01_PHASE_6.md).

**Allowed claim:**  
> M3 demo path uses live Shopify shop **klints-dev** with Simple Sample Data; Klints imports contacts via normal connect + fresh import.

---

## 8. Theater register

| Do not claim | Why |
|--------------|-----|
| Contacts filled by `seed_demo_tenant` for M3 | Wrong SoT |
| Grafana alerts done in this PR | OBS-01B |
| DP1 production partner PII live | Gate B |
| MCP publish | Client-blocked |
| Exact 5k if sample app cannot reach 5k | Document actual count |

---

## 9. Relationship

| PRD | Topic |
|-----|--------|
| **This** | Live Shopify demo contacts |
| [OBS-01B](./PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md) | Grafana alert email closeout |
| SEC-01 | Already merged |
| Optional later | True partner DP1 cutover after Gate B |
