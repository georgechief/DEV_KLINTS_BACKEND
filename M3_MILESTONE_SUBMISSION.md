# Klints MVP1 — Milestone 3 (Demo, Security & DP1) Submission

**Document type:** Client milestone handoff / acceptance package  
**Milestone:** **M3 — Demo, Security & DP1** (Schedule 1, Part A)  
**Payment gate:** **Tranche T3 — USD 3,000** (Schedule 1, Part B — released on Client acceptance of M3)  
**Contract reference:** *Klints × Astrapse Labs · MVP 1 Services Agreement v1.2 (8 July 2026)*  
**Submission date:** 5 October 2026  
**Repositories:**  
- Backend: [`georgechief/DEV_KLINTS_BACKEND`](https://github.com/georgechief/DEV_KLINTS_BACKEND)  
- Frontend: [`georgechief/DEV_KLINTS_FRONTEND`](https://github.com/georgechief/DEV_KLINTS_FRONTEND)  

**Prior claims:** M1 Foundation (accepted) · M2 Activation & Blueprint — [`M2_MILESTONE_SUBMISSION.md`](./M2_MILESTONE_SUBMISSION.md)  

**Staging backend:** `https://apis.klints.io` — tag-based CD ([`RELEASES.md`](./RELEASES.md)). Health: `GET /health/` → `{"status":"ok"}`.  
**Code deposit:** product sync on Client `main` via deposit PR [#12](https://github.com/georgechief/DEV_KLINTS_BACKEND/pull/12) / FE [#7](https://github.com/georgechief/DEV_KLINTS_FRONTEND/pull/7) (2026-09-30) — includes M3 SEC/OBS/DEMO docs + writeback wave through WB-21.  
**Live deploy tag:** still **`v1.0.2`** unless Client cuts a newer semver after this claim; `main` may be ahead of the running droplet until a new tag is published.

### Staging access (Client review)

| Surface | URL | Notes |
|---------|-----|--------|
| API health | https://apis.klints.io/health/ | Public |
| Grafana (ops only) | https://apis.klints.io/grafana/ | Credentials = Client `DEV_ENV_FILE` / existing M2 staging note — **not repeated in this file** |
| Frontend | Client Vercel / configured origin → `apis.klints.io` | — |
| Shopify demo shop | [klints-dev · Simple Sample Data](https://admin.shopify.com/store/klints-dev/apps/simple-sample-data) | Live sample path for DEMO-01 |

> This file is identical in both Client repositories so reviewers have one authoritative M3 writeup.  
> **M3 claim SoT:** this document. Specs live under `docs/sahil/` (SEC / OBS / DEMO PRDs) and `docs/security/` (SEC packet).

---

## 1. Executive summary

Milestone 3 required **Demo, Security & DP1**: security + observability hardened (RBAC, audit tamper detection, Grafana); security review / tenant isolation; demo environment with substantial contacts and a credible connect→score→fix path; Design Partner 1 **readiness** (live partner cutover remains Gate B).

**This deposit delivers the M3 engineering bundle on Client-controlled repos**, with an honest reading of each Schedule 1 row:

| Contract M3 item | Delivery status | Notes |
|------------------|-----------------|-------|
| Security + observability hardened (**RBAC**, **audit tamper detection**, **Grafana**) | **Met (with disclosed residual)** | SEC-01 packet + suites; OBS stack on staging since `v1.0.2`; **OBS-01B live alert email / induce §11 still open** — §3.2 |
| **AC — Security review passed; tenant isolation verified** | **Met as internal packet** | Automated RBAC + cross-tenant suites + review packet — **not** external pen-test / SOC2 — §3.1 |
| Demo env + live Shopify demo path | **Met (with disclosed caveats)** | klints-dev + Simple Sample Data → Klints import (DCS-10); documented contact counts; **staging OAuth/import residual** — §3.3 |
| Design Partner 1 live on production | **Not claimed** | **Readiness** only; partner PII / Gate B cutover open — §3.4 |
| External pen-test attestation | **Not claimed** | Scoped ask with Client (CZ/EU firms); separate from SEC-01 — §3.5 |

**Recommended Client posture for T3:** accept M3 **engineering delivery** (SEC-01 + OBS stack + DEMO path + code deposit) with written recognition that (a) **OBS-01B live alert closeout** and (b) **staging DEMO residual** may complete as short ops follow-ups, and that (c) **DP1 production live** and (d) **independent pen-test letter** are Gate B / follow-on — not silent omissions inside this claim.

---

## 2. Contract map — Schedule 1 M3

### 2.1 Deliverable bundle

| # | Contract deliverable (M3) | Status | Evidence |
|---|---------------------------|--------|----------|
| **M3-S1** | Security + observability hardened (**RBAC**, **audit tamper detection**, Grafana) | **S1a/S1b Met · S1c Met (stack) / closeout residual** | **RBAC + audit:** `docs/security/M3_SEC_01_*`, `docs/sahil/PRD_M3_SEC_01_*`, tests `test_m3_sec01_*`, `scripts/verify_m3_sec01_backend.py`. **Grafana:** compose Loki/Alloy/Grafana since `v1.0.2`; `docs/sahil/PRD_M3_OBS_01_*`, runbook `docs/sahil/M3_OBS_01_RUNBOOK.md`. Alert closeout: `PRD_M3_OBS_01B_*` — §3.2 |
| **M3-S2** | Security review passed; tenant isolation verified | **Met (internal)** | Packet §11 language: *Internal M3-SEC-01 security review packet complete; RBAC matrix and automated cross-tenant / role-negative tests green; audit tamper-detection controls evidenced.* See §3.1 |
| **M3-O1** | Grafana observability | **Met (stack) · closeout residual** | Staging `/grafana/`; five per-service ERROR alert rules as code; mailer bridge. Live induce → Explore → email proof = OBS-01B — §3.2 |
| **M3-D1** | Demo env with substantial contact volume | **Met (documented counts)** | Live Shopify path — **not** `seed_demo_tenant` as M3 AC. Evidence: ~189 Shopify / ~2k+ Manago (not literal 5k) — §3.3 |
| **M3-D2** | Demo path connect → score → fix → … | **Met (local/Sahil) · staging residual** | Runbook `docs/sahil/M3_DEMO_01_SHOPIFY_PATH.md`; verify `scripts/verify_m3_demo01_backend.py` |
| **M3-D3** | Design Partner 1 live | **Readiness only — not claimed live** | Same connect/import pattern; partner cutover = Gate B — §3.4 |

### 2.2 Acceptance criteria reading

| Theme | Status | How to verify |
|-------|--------|----------------|
| Security review + tenant isolation | **Internal packet Met** | Open `docs/security/M3_SEC_01_SECURITY_REVIEW_PACKET.md`; run `verify_m3_sec01_backend.py` + isolation/RBAC tests |
| Observability / Grafana | **Stack Met**; live alert proof **Open** | Login `/grafana/`; Explore by `service=`; OBS-01B A5/A7 still ops — §3.2 |
| Demo on live Shopify | **Path Met**; exact 5k **not claimed** | Follow DEMO Shopify path; counts in WORKING_GAPS |
| DP1 production live | **Not Met / not claimed** | Requires Gate B + partner |

---

## 3. Clarifications vs Schedule 1 wording (honesty register)

### 3.1 Security review = internal SEC-01 packet (not external pen-test)

Schedule 1 names *security review passed; tenant isolation verified*.

**Delivered:**

- RBAC matrix (Admin / Analyst / Viewer)  
- Automated cross-tenant isolation + RBAC-negative suites  
- Audit hash-chain + DB immutability evidence  
- Static verify script  
- Written packet with residual risks and allowed claim language  

**Not delivered / not claimed under T3 engineering:**

- External penetration-test firm attestation  
- SOC2 / ISO 27001  
- “Gate B closed” / “GDPR certified”  

Client is separately scoping a **CZ/EU grey-box web+API pen test** (tenant IDOR, RBAC, connectors, writeback gates, SQL injection, etc.) for Gate B evidence. That letter is **follow-on**, not a substitute for — or contradiction of — SEC-01.

### 3.2 Grafana / OBS — stack vs alert closeout

| Topic | Reality |
|-------|---------|
| Grafana + Loki + Alloy on staging | **Live** since tag `v1.0.2` |
| Per-service ERROR alert rules (web, celery_worker, celery_beat, nginx, redis) | **In repo** as Grafana provisioning |
| OBS-01B: induce ERROR → Explore marker → alert email → disable | **Ops residual** — Sahil prep done; live A5/A7/§11 open (`docs/sahil/M3_OBS_01B_WORKING_GAPS.md`) |
| Prometheus / RED metrics | **Out of M3 v1** (optional OBS-02) |

**Honest claim:** *Staging Grafana with Docker log aggregation and per-service alerts provisioned.*  
**Not yet:** *Live alert email closeout video/email proven* until OBS-01B ops completes.

### 3.3 Demo env — live Shopify, not seed; counts honesty

| Topic | Reality |
|-------|---------|
| M3 demo SoT | **klints-dev** + Simple Sample Data → OAuth → DCS-10 fresh import |
| `seed_demo_tenant` | Local smoke only — **not** M3 AC |
| Contact volume | Documented **~189 Shopify / ~2k+ Manago** — **not** silent claim of exact 5k |
| Staging A2/A3/A10 | **Residual** post–Sahil ship (local path accepted) — `docs/sahil/M3_DEMO_01_WORKING_GAPS.md` |
| Handoff Send | Remains **human Manago UI** (HO-02); no MCP required for M3 demo |

### 3.4 DP1 live = Gate B (not this claim)

**Delivered:** readiness pattern (connect Shopify/Manago → import → score → Fix → Studio → QA → Handoff) on demo/staging tooling.

**Not claimed:** production Design Partner with partner PII, legal DPAs complete, or Gate B closed.

### 3.5 Items explicitly out of T3 claim

| Item | Notes |
|------|--------|
| M2 AC-A live Manago MCP E2E | Remains M2 Client dependency / waiver — not re-opened as M3 AC |
| Writeback Phase B (CI-03/CC-01/CC-02 execute; PT-03 PRODUCT.IMPORT Loom) | Product follow-on; Phase A plan-only / Preview shipped |
| External pen-test certificate | Client-procured; §3.1 |
| New deploy tag beyond `v1.0.2` | Recommended so droplet matches 2026-09-30 deposit; not required to *read* the claim on GitHub |

---

## 4. M3 functional walkthrough (recommended acceptance path)

1. **Health** — `https://apis.klints.io/health/` → ok.  
2. **Security packet** — skim `docs/security/M3_SEC_01_SECURITY_REVIEW_PACKET.md` + RBAC matrix; optionally run verify scripts on a checkout.  
3. **Grafana** — open `/grafana/` (ops credentials via Client secret store); Explore logs by `service=web`.  
4. **Demo path** — Shopify Simple Sample Data on klints-dev → Connect → Run DCS (fresh import) → contacts visible → Fix / Studio / QA / Handoff as product allows.  
5. **Writebacks (supporting, not sole M3 AC)** — Settings Allow writebacks OFF by default; allowlisted Approve path for shipped checks (see writeback surface matrix).  
6. **Honesty check** — no claim of external pen-test, DP1 partner-live, or exact 5k contacts.

**Optional Loom / video evidence (ops follow-up):** OBS-01B induce → Explore → alert email (~1–2 min) when closeout is run.

---

## 5. What shipped for M3 (highlights)

| Area | Summary | Key references |
|------|---------|----------------|
| **M3-SEC-01** | RBAC matrix, isolation suites, audit evidence, review packet | `docs/security/M3_SEC_01_*`, `docs/sahil/PRD_M3_SEC_01_*`, `scripts/verify_m3_sec01_backend.py` |
| **M3-OBS-01** | Grafana + Loki + Alloy, dashboards/alerts as code, mailer bridge | `docs/sahil/PRD_M3_OBS_01_*`, `deploy/grafana/`, `M3_OBS_01_RUNBOOK.md` |
| **M3-OBS-01B** | Induce path + closeout prep | `docs/sahil/PRD_M3_OBS_01B_*`, `M3_OBS_01B_WORKING_GAPS.md` |
| **M3-DEMO-01** | Live Shopify demo path + verify | `docs/sahil/PRD_M3_DEMO_01_*`, `M3_DEMO_01_SHOPIFY_PATH.md`, `scripts/verify_m3_demo01_backend.py` |
| **Writeback catalogue (supporting)** | LE/CI/CC/SP/PT waves through WB-21 sandbox contract | `docs/maheep/PRD_WB_*`, `WRITEBACK_SURFACE_MATRIX.md` |
| **Code deposit** | Client `main` refreshed 2026-09-30 | BE PR #12 · FE PR #7 |

---

## 6. Repository pointers

### Backend (`DEV_KLINTS_BACKEND`)

```
docs/sahil/           M3 SEC / OBS / DEMO PRDs + phase notes + WORKING_GAPS
docs/security/        M3_SEC_01 packet, RBAC matrix, audit evidence
docs/maheep/          Writeback PRDs (WB-01…WB-21), surface matrix
dataruns/tests/       test_m3_sec01_*, writeback_wb*, sandbox_contract
scripts/              verify_m3_sec01_backend.py, verify_m3_demo01_backend.py, verify_m3_obs01_backend.py
deploy/grafana/       Alerting / datasources / dashboards provisioning
RELEASES.md           Tag-based staging deploy SoT
M2_MILESTONE_SUBMISSION.md
M3_MILESTONE_SUBMISSION.md   ← this claim
```

### Frontend (`DEV_KLINTS_FRONTEND`)

```
src/routes/           DCS, Fix, Studio, QA, Handoff, …
src/lib/writebacks.ts Allowlist + honesty (mapping-only, fail-closed eligibility)
scripts/              verify-wb02-frontend.mjs and related gates
M3_MILESTONE_SUBMISSION.md   ← identical claim copy
```

Secrets (`.env`, Grafana password, API tokens) are **excluded** from git.

---

## 7. Acceptance request (for T3 release)

Per Agreement clauses **4.2–4.3** and Schedule 1 Part B:

1. Provider hereby gives **written notice of M3 completion** (subject to honesty register §3) via this document and the Source Code deposit in Client-controlled `DEV_KLINTS_*` repositories.  
2. Client is requested to either:  
   - **(A)** Accept M3 engineering delivery as scoped in §1–§2, with OBS-01B live closeout and DEMO staging residual as **short disclosed ops follow-ups**, and DP1 live + external pen-test as **Gate B / follow-on**; **or**  
   - **(B)** Reject in writing within five (5) business days with specific unmet criteria (clause 4.3).  
3. If Client does not respond within five (5) business days, the Milestone is **deemed accepted** (clause 4.3) for the accepted scope.  
4. Upon acceptance (or deemed acceptance), Provider will invoice **Tranche T3 — USD 3,000**, payable within ten (10) business days (clause 5.4).  
5. Milestone source-code deposit obligations (Schedule 2 / clause 9) are satisfied by the pushes to Client GitHub repositories listed above (including 2026-09-30 deposit PRs).

### Suggested Client acceptance checklist

- [ ] Staging API healthy (`/health/` → ok)  
- [ ] Review SEC-01 packet + RBAC matrix (`docs/security/`)  
- [ ] Grafana reachable (ops credentials via Client secret store)  
- [ ] DEMO path understood (Shopify klints-dev → import → score); counts honesty noted  
- [ ] No expectation of external pen-test letter inside this T3 engineering claim  
- [ ] No expectation of DP1 partner-PII production live inside this claim  
- [ ] Written note on OBS-01B closeout timeline (ops) if Client wants email proof before invoice  
- [ ] Optional: cut new semver tag so droplet matches latest `main` deposit  
- [x] Source present in Client GitHub repos  

---

## 8. Closing statement

**Milestone M3 (Demo, Security & DP1) is submitted for Client acceptance** with:

- **Internal security review packet** + tenant isolation / RBAC evidence (M3-S2 / M3-S1 RBAC+audit)  
- **Grafana observability stack** on staging (M3-O1), with **OBS-01B live alert closeout** disclosed as residual  
- **Live Shopify demo path** (M3-D1/D2) with honest contact counts and staging residual disclosed  
- **DP1 readiness** without claiming partner production live (M3-D3)  

Disclosed residuals (§3) are intentional honesty, not silent omissions. M2 Track B MCP (AC-A) remains under the M2 waiver/dependency track and is **not** re-claimed here.

---

*Submitted by Astrapse Labs LLP / Named Lead Developer for Client milestone review under the MVP 1 Services Agreement.*
