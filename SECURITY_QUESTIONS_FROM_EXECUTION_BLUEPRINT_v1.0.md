# Klints · MVP1 Security, Privacy & AI Compliance — Questions & Disposition Pack

**Working companion to:** `Klints_MVP1_Security_Privacy_AI_Compliance_Execution_Blueprint_v1.0_20260810.pdf`  
**Prepared for:** Astrapse Labs (Rohan) — answer / disposition tracking  
**Date:** 11 September 2026  
**Classification:** Klints Confidential  
**Filled:** 11 Sep 2026 from Rohan answers + code evidence. Companion: `SECURITY_ANSWERS_KNOWN_VS_NEEDED.md`

**Authoritative baseline:** If this pack differs from blueprint **v1.3**, **v1.3 prevails**.

**How to read Status**
| Status | Plain meaning |
|--------|----------------|
| Accepted | We do this as the blueprint asks |
| Alternative proposed | We do something different — explained honestly |
| Comenius decision required | Product/client must choose |
| Legal/provider evidence required | Lawyer / Mistral / DO / GitHub paperwork — not engineering alone |
| Evidence pending | Built or partly built; proof packet not finished |
| Blocked | Cannot claim done yet |
| Complete | This row’s ask is answered |

### Plain English — where we stand (read this first)

| Topic | Simple answer |
|-------|----------------|
| Can we use **real customer data** yet? | **No.** Gate B is still open. Fake/staging data only (Gate A). |
| Can we **write back** into Shopify for live partners? | **No** (Gate C). Shopify has a write permission for **testing**; the app still blocks real execute unless a company opts in + approval. |
| Where does staging run? | DigitalOcean **Frankfurt**: one droplet + Managed Postgres (~2 GB). URL: `apis.klints.io`. Deploy from **`georgechief/DEV_KLINTS_BACKEND` tags**. |
| How are tenants separated today? | Same app for everyone; each user’s data is filtered by their **company** in code. Not database RLS. Later idea: one Docker stack per tenant (~7–10 days after phase 1). |
| How are connector secrets kept? | Encrypted with one server key (Fernet) from **GitHub Actions** secrets — rotatable, not in git. |
| Which AI? | **Mistral** in the **EU**, model id **`mistral-small-latest`**. Privacy filter before send. LangSmith tracing on (`noreplyklints@gmail.com`). |
| Reports | PDF is **generated on download** (not stored as a file). Only authorized people. |
| Backups | **Off** in development (fake data). Turn on for a live partner; restore aim **5–10 minutes**. Never restore-tested yet. |
| Who can operate? | **Rohan Girdhani** + **Sahil Kumar**. 24h critical. Sahil can deploy under guidance. |
| Gate B effort | **7–10 days outside phase 1** (reviewer ~3–4 days + fixes ~6 days). Independent pen test not booked yet. |
| Legal / DPAs | **Ask Comenius counsel** — we do not invent signed contracts from code. |

---

## 1 Quick Start

### CURRENT DECISION (from blueprint)

**CONDITIONAL GO.** Build with fake/staging data now. **Real** tenant data waits for Gate B. **Writes** into customer systems wait for Gate C.

**Astrapse (11 Sep 2026):** Gate A **OPEN**. Gate B and Gate C **BLOCKED**. Do not say “security review passed” or “live-data ready.” Closing Gate B engineering + review ≈ **7–10 days outside phase 1**.

### 1.1 What Rohan should do first

| # | Blueprint ask | Our answer / notes | Status |
|---|---------------|--------------------|--------|
| 1.1.1 | Confirm the baseline — marked response: accepted requirements, technical conflicts, proposed alternatives, decisions needed from Comenius | **This pack is the baseline response.** Honest differences vs blueprint: (1) company filtering in the app, not Postgres RLS; (2) one shared encryption key for connector secrets; (3) AI model `mistral-small-latest`, not pinned `2603`; (4) EU Mistral by ops practice, not hard-fail in code; (5) Shopify write permission for test, app execute still gated; (6) backups off in dev. Legal items → Comenius. Companion: `SECURITY_ANSWERS_KNOWN_VS_NEEDED.md`. | In progress |
| 1.1.2 | Confirm the implementation route — DigitalOcean product, GitHub plan & repository visibility, secrets/key-management approach, intended deployment flow | **Hosting:** Frankfurt droplet + Managed Postgres (~2 GB). No load balancer yet. **Deploy:** tags on `georgechief/DEV_KLINTS_BACKEND` → `apis.klints.io` (see RELEASES.md; live tag v1.0.2). **Secrets:** Fernet key in GitHub Actions, rotatable. **GitHub plan / who can approve prod:** Comenius to confirm. | Alternative proposed |
| 1.1.3 | Return a bottom-up estimate by work package — dependencies, critical path, external blockers, evidence work | **Gate B:** 7–10 days outside phase 1 (reviewer 3–4 days + our fixes ~6 days). Later extras: load balancer ~3 days; per-tenant Docker package ~7–10 days after phase 1. Waiting on: legal/DPA, pen-test booking. | Complete |
| 1.1.4 | Build with synthetic data — do not wait for Gate B legal/provider evidence where synthetic/stubs are safe | Yes — we keep building on **fake/staging data** under Gate A. Dev backups stay off on purpose. | Accepted |
| 1.1.5 | Produce evidence while building — control incomplete without evidence + acceptance result retained with requirement ID | Evidence will live in this **backend repo**. Full Gate B evidence pack + independent review **not done yet**. | Evidence pending |

### 1.2 Status at a glance

| Gate | Purpose | Blueprint status | What this means now | Our confirmation |
|------|---------|------------------|---------------------|------------------|
| **A** | Synthetic development | OPEN | Build with fake data and non-prod credentials | **OPEN** — we continue here |
| **B** | First live read-only tenant | **BLOCKED** | No real customer data until Gate B is proven | **Blocked** — not ready; ~7–10 days work outside phase 1 |
| **C** | Write connector or MCP | **BLOCKED** | No live writes into customer systems | **Blocked** — test write permission on Shopify exists; app execute stays off unless opted in + approved |
| **D** | First paying or public launch | FUTURE GATE | After Gate B (and more) | **Not now** |
| **E** | Cross-tenant benchmarks | POST-MVP | No shared benchmarks across tenants in MVP1 | **Not now** |

### 1.3 Working rule

**NO SILENT ASSUMPTIONS**

An open item must never be resolved informally in code. Record it as **Accepted**, **Alternative proposed**, **Comenius decision required**, **Legal/provider evidence required**, or **Not applicable** with reason.

| # | Question | Status |
|---|----------|--------|
| 1.3.1 | Is every open item dispositioned with one of the five statuses above (no silent code reinterpretation)? | In progress — this pack dispositions known items; legal/provider still open |

---

## 2 Locked MVP1 Direction

The following decisions are treated as fixed for estimation and implementation unless Comenius Agency formally changes the v1.3 baseline.

| # | Locked decision | Confirm Accept / Alternative | Status |
|---|-----------------|------------------------------|--------|
| 2.1 | **Deployment model** — Shared multi-tenant service with strong logical isolation is the MVP1 default. Dedicated single-tenant is not the baseline | **Yes, one shared product** for MVP1. Each company only sees its own data via app checks (`get_user_company`). Not Postgres RLS. Later idea: separate Docker per tenant (~7–10 days after phase 1). | Alternative proposed |
| 2.2 | **Hosting intent** — DigitalOcean Frankfurt is the intended primary region. Exact DigitalOcean product and service map remain open and must be decided | **Yes — Frankfurt.** Droplet + Managed Postgres (~2 GB). No load balancer / Spaces yet. Evidence: deploy workflow, RELEASES.md, `apis.klints.io`. | Accepted |
| 2.3 | **AI route** — One direct Mistral EU route using pinned model identifier `mistral-small-2603`. No OpenRouter, no automatic Scaleway fallback, no floating model alias | **Almost:** we call Mistral directly (no OpenRouter). Model we use: **`mistral-small-latest`** (not `2603`). EU region by ops today; app does not hard-fail if misconfigured. | Alternative proposed |
| 2.4 | **AI fallback** — Complete deterministic Klints report template is the only MVP1 fallback when the provider is unavailable or an AI response is rejected | **Yes** — assessment report still works without AI. AI text is optional. | Accepted |
| 2.5 | **Model egress** — AI Data Contract is allow-list based, fails closed on unknown fields, applies cohort and suppression rules. Provisional platform minimum: **50 distinct data subjects** | We strip/block unsafe fields before AI (PrivacyGate + allowlist). **50-person cohort rule is not built yet.** | Alternative proposed |
| 2.6 | **Tenant access** — First live phase is read-only. Write scopes and executable MCP tools are not activated before Gate C | **Honest Alternative:** Shopify app has `write_customers` so we can **test** updates. Klints still blocks execute by default (global flag off, company flag off, needs allowlist + human approval). We do **not** claim Gate C. | Alternative proposed |
| 2.7 | **Reports** — Canonical structured payload is authoritative. PDF is generated for delivery, hashed at issue, and is not permanently stored by default | JSON report is stored and hashed (`payload_hash`). PDF is **made on download**, not kept as a file. Authorized people only. We do **not** also store a separate hash of the PDF file bytes. | Alternative proposed |
| 2.8 | **Outcome data** — MVP1 records tenant-local issue, fix and outcome events. No cross-tenant contribution, aggregation or benchmark publication plane | **Yes** — keep outcomes inside each tenant. No cross-tenant benchmarks in MVP1. | Accepted |

### 2.1 Explicitly deferred

| # | Deferred item | Confirm: no dormant production path / unused write credentials / hidden cross-tenant flows? | Status |
|---|---------------|---------------------------------------------------------------------------------------------|--------|
| 2.1.1 | Write-capable connectors and executable MCP workflows | Writeback **code is in the product** (needed for tests). Execute is **off by default** and needs company opt-in + allowlist + approval. Shopify write permission is for **sandbox/test**, not “live writes open.” | Alternative proposed |
| 2.1.2 | A second external AI provider | Confirmed deferred — Mistral only; no OpenRouter / Scaleway fallback in code. | Accepted |
| 2.1.3 | Cross-tenant benchmark computation and publication | Confirmed deferred (Gate E POST-MVP). | Accepted |
| 2.1.4 | Dedicated single-tenant or customer-hosted deployment as the default product | Confirmed not MVP1 default. Future: per-tenant Docker package post phase 1 (Alternative proposal only). | Accepted |
| 2.1.5 | SSO and other enterprise identity extensions not required for the first MVP1 live gate | Confirmed deferred for first live gate. | Accepted |

**SCOPE CONTROL:** Deferred features must not create dormant production paths, unused write credentials or hidden cross-tenant data flows. If scaffolding is retained, it must remain unreachable and excluded from live configuration.

---

## 3 Critical Path and Next Best Steps

Gate B closes only when three parallel lanes converge. Engineering is one lane, not the whole programme.

| Lane | Immediate owner | Outputs required before Gate B | Started? (Y/N) | Status |
|------|-----------------|--------------------------------|----------------|--------|
| **A** Product, legal and contracts | Comenius + counsel | Processing and transfer instruments; report-audience and Article 50 decisions; retention; legal roles; design-partner jurisdiction; named owners | N | Legal/provider evidence required |
| **B** Architecture and implementation | Rohan / Astrapse Labs | As-built architecture; secure platform; test results; runbooks; deployment evidence; bottom-up estimate and critical path | Y (partial) | In progress |
| **C** Provider and independent evidence | Comenius + providers + reviewer | Mistral evidence; DigitalOcean service map; GitHub capability facts; independent isolation and credential-store reviews | N (pen test not booked) | Blocked |

### 3.1 Recommended sequence

| Step | Blueprint step | Our plan / ETA | Status |
|------|----------------|----------------|--------|
| 1 | **Baseline response** — Rohan returns requirement disposition, architecture questions and bottom-up estimate. Comenius resolves decisions that prevent design finalisation | This pack + answers companion. Gate B estimate 7–10d outside phase 1. | Complete |
| 2 | **Platform foundation** — Fix deployment product, environments, network boundaries, database roles, secrets architecture and CI/CD constraints | Frankfurt droplet + Managed Postgres; Fernet via Actions; tag deploy. LB/RLS/KMS deferred as Alternatives. | Alternative proposed |
| 3 | **Highest-risk controls** — Implement tenant isolation and connector credential protection first | App-level scoping live; no RLS. Fernet shared key. Future: per-tenant Docker. | Alternative proposed |
| 4 | **AI and report path** — AI Data Contract, Mistral EU route, validation/fallback, canonical report payload, report access and provenance | PrivacyGate+allowlist; mistral-small-latest; EU ops; payload_hash; PDF stream. Gaps: EU hard-pin, 2603, PDF byte hash, cohort. | In progress |
| 5 | **Operational readiness** — Logs, monitoring, backup restore, deletion replay, incident response, access control, deployment approval and secondary-operator runbooks | Grafana live; backups OFF; restore never tested; no formal tabletop. Sahil secondary under guidance. | Evidence pending |
| 6 | **Independent evidence and Gate B review** — Acceptance catalogue, independent review, disposition findings, customer security evidence pack | Pen test (e.g. pentest-tools.com) not booked; GB-25 pack not assembled. | Blocked |

### 3.2 What may run in parallel

| # | Parallel item | In progress? | Status |
|---|---------------|--------------|--------|
| 3.2.1 | Astrapse processing/transfer documentation, Mistral evidence and DigitalOcean service mapping start immediately (external lead time) | Legal = ask Comenius; DO map partial (Frankfurt droplet + Managed PG) | Legal/provider evidence required |
| 3.2.2 | Rohan implements synthetic-data controls while external items pending — **no live data or live credential** enters the environment | Yes — Gate A synthetic continue | Accepted |
| 3.2.3 | Article 50 and retention decisions may be pending while report pipeline is built to support either approved outcome without re-architecture | Yes — pipeline exists; legal decisions open | Comenius decision required |
| 3.2.4 | Independent reviewer selected **before** isolation and credential-store implementation finishes | Not selected/booked | Blocked |

---

## 4 Ownership and Immediate Handoff

### 4.1 Responsibility split

| Party | Accountable for now | Must not decide alone | Confirmed? |
|-------|---------------------|----------------------|------------|
| Rohan / Astrapse Labs | Architecture options; implementation; automated tests; as-built evidence; runbooks; estimate and dependencies | Legal roles; product audience; retention periods; acceptance of residual risk; authorisation of live data | Yes — Rohan Girdhani (Lead); Sahil Kumar (tester/secondary under guidance) |
| Comenius Agency | Product decisions; accounts; owner appointments; acceptance of risk; approval of gates; customer-facing claims | Technical feasibility or security evidence without Rohan and the independent reviewer | Ask Comenius |
| Counsel / privacy owner | Processing roles; transfers; Article 50 determination; DPIA screening; contract language | Engineering architecture or undocumented product-intent assumptions | Ask Comenius / counsel |
| Independent reviewer | Independent review of tenant isolation and credential handling; findings and dispositions | Implementation ownership or self-review of code they authored | Not booked (pentest-tools.com path) |
| Providers | Contractual and service evidence for Mistral, DigitalOcean and GitHub capabilities | Klints compliance claims or Gate B approval | Legal/provider evidence required |

### 4.2 First response required from Rohan

| # | Deliverable | Our answer / artefact link | Status |
|---|-------------|----------------------------|--------|
| 4.2.1 | **Disposition matrix** — for every requirement referenced by the work packages: Accepted; Alternative proposed; Comenius decision required; Legal/provider evidence required; or Not applicable with reason | This file + `SECURITY_ANSWERS_KNOWN_VS_NEEDED.md` | Complete |
| 4.2.2 | **Architecture pack** — current and target diagrams; complete service/region inventory; ingress/egress paths; data stores; secrets and key hierarchy; access paths; logging; monitoring; backups | Partial: inventory known (DO Frankfurt droplet + Managed PG ~2GB; apis.klints.io; Grafana/Loki/Alloy; Fernet env key; Mistral; LangSmith). Formal diagram pack incomplete. | Evidence pending |
| 4.2.3 | **Decision recommendations** — preferred DigitalOcean product, database topology, secrets/key-management product and GitHub protection mechanism, with trade-offs | DO: droplet + Managed Postgres Frankfurt. Secrets: stay env Fernet via Actions (Alternative vs per-tenant DEK/KMS). Future isolation: per-tenant Docker. GitHub: tag CD from DEV_KLINTS_BACKEND; plan/visibility → Comenius. | Complete |
| 4.2.4 | **Estimate** — bottom-up effort by work package, named dependencies, external blockers, critical path and the point at which independent review should occur | Gate B **7–10 days outside phase 1** (reviewer 3–4d + remediations ~6d). LB later ~3d; per-tenant package later 7–10d. Blockers: legal DPAs, pen-test booking, Comenius decisions. | Complete |
| 4.2.5 | **Deviation list** — any conflict with the current codebase or any control that would materially change cost, schedule or the product architecture | No RLS; shared Fernet; mistral-small-latest; EU ops not code-pin; write_customers for test; writeback routes gated; no PDF byte hash; backups off; no LiteLLM; no 50-subject cohort. | Complete |
| 4.2.6 | **Evidence plan** — where each test result, configuration export, review record and runbook will be stored and who will produce it | Evidence in **backend repository**. Named company + command transcripts still needed for Gate B packet. | Evidence pending |

**IMPORTANT:** A requirement should be challenged before build if it is technically unsound. It should not be reinterpreted silently to fit the existing implementation.

---

## 5 Engineering Work Packages

Track each WP as: `Not started` · `In progress` · `Evidence pending` · `Blocked` · `Ready for independent review` · `Complete`

Full normative wording and tests remain in **v1.3**.

### WP0 Baseline, Architecture and Estimate

**Outcome.** A reviewed and estimable build baseline with no hidden disagreement between the current system and v1.3.

| # | Rohan / Astrapse action (as question) | Answer / evidence | Status |
|---|---------------------------------------|-------------------|--------|
| WP0-1 | Return the marked requirement disposition and identify every technical conflict or assumption? | Yes — this pack + companion answers. | Complete |
| WP0-2 | Produce current-state and target-state architecture and data-flow diagrams? | Inventory described; formal diagram pack incomplete. | Evidence pending |
| WP0-3 | Provide the complete infrastructure, service, region, account and external-endpoint inventory? | Frankfurt droplet + Managed Postgres ~2GB; apis.klints.io; Mistral; LangSmith (noreplyklints@gmail.com); Grafana. No LB/Spaces. | In progress |
| WP0-4 | Provide a bottom-up estimate by WP1 to WP8, dependencies, critical path and external lead-time assumptions? | Gate B 7–10d outside phase 1; LB ~3d later; per-tenant Docker 7–10d post phase 1. | Complete |

| Inputs from Comenius | Notes | Status |
|----------------------|-------|--------|
| O-01, O-02, O-03 and initial answers on O-13 resolved jointly; Comenius supplies account and repository facts | O-01/O-13 Rohan recommendations given; O-02/O-03 GitHub plan/visibility still need Comenius | Comenius decision required |

| Evidence to retain | Have we retained it? | Status |
|--------------------|----------------------|--------|
| Disposition matrix; diagram pack; inventory; estimate; dependency map; deviation register | Disposition + estimate yes; diagrams/packet Partial | Evidence pending |

| Done when | Met? |
|-----------|------|
| Comenius and Rohan agree the implementation route and all material deviations are recorded for decision | **Partial** — Astrapse disposition recorded; Comenius acceptance pending |

**Authoritative references:** Sections 2.3, 3.4, 23.2 and 36.2; O-01 to O-03; GB-17 and GB-18.

---

### WP1 Hosting, Environments and Network Boundaries

**Outcome.** A reproducible DigitalOcean Frankfurt deployment with documented service geography, controlled ingress/egress and separated environments.

| # | Rohan / Astrapse action (as question) | Answer / evidence | Status |
|---|---------------------------------------|-------------------|--------|
| WP1-1 | Recommend and document the exact DigitalOcean deployment product and managed services used? | Droplet + Managed Postgres (~2 GB), Frankfurt. No LB/autoscaling yet (~3d later when design partner live). Evidence: `.github/workflows/deploy-development.yml`, `docker-compose.yml`, `deploy/`, RELEASES.md, v1.0.2. | Complete |
| WP1-2 | Define development, staging and production boundaries; production data and credentials must not exist outside production? | Client staging = tag deploy from `georgechief/DEV_KLINTS_BACKEND` to apis.klints.io; synthetic data. Formal prod boundary evidence incomplete. | In progress |
| WP1-3 | Hard-code approved external destinations and deny user-, tenant- or data-controlled provider endpoints? | Mistral direct; EU ops practice only — **no hard-pin fail-closed in code**. | Alternative proposed |
| WP1-4 | Document support, administrative and break-glass paths, including access expiry and audit events? | Access: Rohan Girdhani + Sahil Kumar; 24h critical. Formal break-glass runbook not named. | Evidence pending |
| WP1-5 | Produce an as-built service/region map and identify facts that remain provider claims or not established? | Partial map: Frankfurt droplet + Managed PG; Grafana `/grafana/`. DPA/subprocessor map → provider/Comenius. | Evidence pending |

| Gate A refs (exact tests in v1.3) | Disposition | Status |
|----------------------------------|-------------|--------|
| GA-01 … GA-04 | Synthetic/staging deploy exists; continue Gate A | In progress |
| AI-06 (cited under WP1 hosting/egress) | EU ops practice; not code hard-pin | Alternative proposed |

| Evidence to retain | Have we retained it? | Status |
|--------------------|----------------------|--------|
| Infrastructure definitions; network diagram; egress configuration; environment inventory; account ownership evidence; service/region map | Partial in repo (compose, nginx, workflows, RELEASES.md) | Evidence pending |

| Done when | Met? |
|-----------|------|
| Synthetic deployment is reproducible; no production secret exists outside production; unapproved egress is blocked and logged | **Partial** — reproducible staging yes; egress hard-deny / formal env proof incomplete |

**Authoritative references:** Sections 3.4, 5.4, 10.4-10.5 and 23; GA-01 to GA-04; GB-16 to GB-18; AI-06.

---

### WP2 Tenant Isolation, Identity and Production Access

**Outcome.** Tenant A cannot access any Tenant B object through HTTP, database, pooler, background jobs, scheduled jobs, reports, support tooling, credentials or AI metadata.

| # | Rohan / Astrapse action (as question) | Answer / evidence | Status |
|---|---------------------------------------|-------------------|--------|
| WP2-1 | Implement tenant identifiers on all tenant-controlled records and enumerate read-only global tables? | Tenant/Company model + `get_user_company` scoping. Evidence: `tenants/models.py`, `tenants/auth/services.py`. | In progress |
| WP2-2 | Enforce PostgreSQL RLS with FORCE ROW LEVEL SECURITY; application roles must not own tenant tables or hold BYPASSRLS? | **Not building database RLS now.** Today: app filters by company. **Proposed later:** one Docker stack per tenant (~7–10 days after phase 1). | Alternative proposed |
| WP2-3 | Use transaction-scoped tenant context and test connection-pool leakage and missing-context failure? | Not as blueprint RLS context — app filters only. | Alternative proposed |
| WP2-4 | Validate tenant membership server-side for every request and job; JWT claims are not the trust boundary? | Server-side company resolution via `get_user_company`; roles admin/analyst/viewer. Residual: multi-company-per-tenant not productized (M3-SEC-01). | In progress |
| WP2-5 | Define least-privilege roles, privileged MFA, session revocation, support role and break-glass access? | Roles exist; MFA/break-glass formalization incomplete. Ops: Rohan + Sahil; 24h critical. | Evidence pending |
| WP2-6 | Run the complete TEN negative-test family in CI and prepare the implementation for independent review? | Independent review not booked; TEN family evidence not complete. | Blocked |

| Comenius inputs | Notes | Status |
|-----------------|-------|--------|
| Named support/admin holders | Rohan Girdhani (Lead); Sahil Kumar (Astrapse) | Complete |
| Approves the revocation target | Need Comenius | Comenius decision required |
| Selects the independent reviewer | Path: pentest-tools.com; not booked | Blocked |

| Acceptance IDs | Pass? | Evidence | Status |
|----------------|-------|----------|--------|
| TEN-01 … TEN-09 (Done-when minimum) | No | App scoping only; no RLS; no independent review | Blocked |
| TEN-10 … TEN-12 (cited in WP2 refs — disposition via v1.3) | No | Not evidenced | Not started |
| IAM-01 … IAM-10 | Partial | Roles exist; MFA/break-glass incomplete | Evidence pending |

| Evidence to retain | Have we retained it? | Status |
|--------------------|----------------------|--------|
| Schema and role queries; RLS policies; pooler configuration; TEN test output; access matrix; break-glass test; independent review record | No RLS/review packet | Blocked |

| Done when | Met? |
|-----------|------|
| TEN-01 to TEN-09 pass; no unresolved Critical or High finding; Medium and Low findings meet the v1.3 disposition standard | **No** — Alternative proposed; review blocked |

**Authoritative references:** Sections 11-12 and 24; GB-13 and GB-15; TEN-01 to TEN-12; IAM-01 to IAM-10.

---

### WP3 Connector Credentials and Read-Only Ingestion

**Outcome.** Database compromise or restoration outside the approved trust boundary does not yield usable tenant connector credentials.

| # | Rohan / Astrapse action (as question) | Answer / evidence | Status |
|---|---------------------------------------|-------------------|--------|
| WP3-1 | Recommend the key/secrets product once WP1 fixes the deployment product? | **Use env Fernet key** from GitHub Actions (`CONNECTOR_FERNET_KEY`). Never put in git; can rotate anytime. One key for all tenants (honest Alternative vs per-tenant keys). Evidence: `tenants/crypto.py`. | Alternative proposed |
| WP3-2 | Keep the key-encryption key outside the application database and use per-tenant or finer data-encryption keys? | KEK outside DB (env) **yes**; per-tenant DEKs **no** — Alternative. | Alternative proposed |
| WP3-3 | Implement rotation, emergency rotation, revocation and auditable credential reads? | Rotatable via Actions; formal emergency/revocation procedure evidence incomplete. Secrets masked in API. | In progress |
| WP3-4 | Prove one tenant key cannot decrypt another tenant's credential and restored development backups cannot decrypt credentials? | N/A under shared key model — disclose. Backups off in dev. | Alternative proposed |
| WP3-5 | Define a read-only scope matrix and field allow-list for every connector; do not request write scopes? | **Scopes in use:** read customers/orders/products/inventory/store-credit tx **+ `write_customers`**. Why write? So sandbox/test can prove a customer update. **When does Klints actually write?** Only if company/global execute is ON **and** check is allowlisted **and** someone approved. Defaults = OFF. | Alternative proposed |
| WP3-6 | Treat all ingested tenant content as untrusted data, never as instructions? | Intent Accepted; formal CON evidence pending. | In progress |

| Acceptance IDs | Pass? | Evidence | Status |
|----------------|-------|----------|--------|
| CON-01 … CON-06 (Done-when minimum) | No / Partial | Fernet + masking; not per-tenant DEK; no independent review | Alternative proposed |
| CON-07 … CON-16 (cited in WP3 refs — disposition via v1.3) | No | Not fully evidenced | Evidence pending |

| Evidence to retain | Have we retained it? | Status |
|--------------------|----------------------|--------|
| Key hierarchy; access policy; scope matrix; field allow-lists; rotation/revocation procedures; CON tests; independent review record | Partial (crypto + docs); review missing | Evidence pending |

| Done when | Met? |
|-----------|------|
| CON-01 to CON-06 pass, credential handling is independently reviewed and production read scopes are the minimum required | **No** — Alternative proposed; review blocked; write_customers disclosed |

**Authoritative references:** Section 13 and 24; O-13; GB-14; CON-01 to CON-16.

---

### WP4 AI Gateway, Data Contract and Mistral Route

**Outcome.** Only approved, policy-compliant A1 payloads reach the pinned Mistral EU endpoint; every rejection uses the internal deterministic template.

| # | Rohan / Astrapse action (as question) | Answer / evidence | Status |
|---|---------------------------------------|-------------------|--------|
| WP4-1 | Implement a server-side Klints AI gateway with a hard-coded EU endpoint, pinned `mistral-small-2603` and returned-model verification? | We call **Mistral directly**. Model: **`mistral-small-latest`**. EU used in ops; **not** hard-coded fail-if-not-EU. Evidence: `dataruns/ai/providers/mistral.py`. | Alternative proposed |
| WP4-2 | Implement the allow-listed AI Data Contract, unknown-field fail-closed behaviour, canary corpus, redaction manifest, policy version/hash and input digest? | PrivacyGate + allowlist exist (fail closed). Full ADC canary/manifest suite incomplete. Evidence: `privacy_gate.py`, `allowlist.py`. | In progress |
| WP4-3 | Apply the provisional minimum of 50 distinct data subjects, rare-value suppression, dimensionality limits and tenant commercial-data flag defaulted off? | **50-subject cohort / suppression not implemented.** | Alternative proposed |
| WP4-4 | Prevent prompts and responses from entering logs, traces, telemetry or error reporting? | Intent: allowlisted I/O only. **LangSmith active** on `noreplyklints@gmail.com` — confirm only allowlisted I/O sent; evidence packet pending. | Evidence pending |
| WP4-5 | Reject malformed, ungrounded, unknown-ID, numeric-fabrication and substituted-model responses; never stream unvalidated output? | Partial controls; full AI-01…11 suite not Gate-B evidenced. | In progress |
| WP4-6 | Implement and test a complete deterministic fallback with Mistral unreachable? | Deterministic report without AI works; formal unreachable test evidence pending. | In progress |

| Acceptance IDs | Pass? | Evidence | Status |
|----------------|-------|----------|--------|
| ADC-01 … ADC-18 | Partial | PrivacyGate + allowlist; cohort missing | Alternative proposed |
| MPA-01 … MPA-07 (mandatory) | No | Provider/legal evidence | Legal/provider evidence required |
| MPA-08, 09, 11 (evidenced or formally dispositioned) | No | Ask Comenius / Mistral | Legal/provider evidence required |
| MPA-10 (requested / status recorded) | No | Ask Comenius | Legal/provider evidence required |
| MPA-12 (cost planning only) | N/A planning | Cost planning only | Not applicable |
| AI-01 … AI-11 | Partial | Code path exists; Gate B suite incomplete | Evidence pending |

| Evidence to retain | Have we retained it? | Status |
|--------------------|----------------------|--------|
| Configuration export; policy schema; canary output; manifests; log scan; adversarial corpus; AI-01 to AI-11 results; fallback sample | Partial in code/docs; packet incomplete | Evidence pending |

| Done when | Met? |
|-----------|------|
| Group 1 Mistral preconditions are complete; AI Data Contract tests pass; global endpoint and unknown destinations are unreachable; fallback report is complete | **No** — Alternatives + provider evidence open |

**Authoritative references:** Sections 14-18; GB-08 to GB-12; ADC-01 to ADC-18; MPA-01 to MPA-12; AI-01 to AI-11.

---

### WP5 Assessment Report, Access and Provenance

**Outcome.** Every issued report is tenant-scoped, traceable to an immutable canonical payload and auditable without relying on byte-identical regeneration.

| # | Rohan / Astrapse action (as question) | Answer / evidence | Status |
|---|---------------------------------------|-------------------|--------|
| WP5-1 | Implement the canonical payload fields and make the issued payload immutable; corrections create a superseding report? | Canonical JSON payload stored. Evidence: `dataruns/reports/payload.py`, AssessmentReport model. | In progress |
| WP5-2 | Compute and store the canonical payload hash and issued-PDF SHA-256 before the ephemeral PDF is discarded? | **`payload_hash` yes**; PDF streamed (zero PDF file retention); **no separate PDF byte hash** — Alternative. | Alternative proposed |
| WP5-3 | Render regeneration from stored narrative, never by re-running the model, and test semantic consistency? | Intent aligned; formal REP evidence pending. | Evidence pending |
| WP5-4 | Implement authenticated or explicitly accepted short-lived delivery, unguessable report identifiers and access audit records? | Download audited; only **authorized account personnel**. | In progress |
| WP5-5 | Carry document-level provenance through validation, human editing, composition and PDF rendering? | Payload hash in PDF footer; full Art. 50 provenance → Comenius. | Evidence pending |
| WP5-6 | Keep cryptographic signing optional until Comenius decides O-26; do not block the base hash/provenance work? | Signing deferred pending O-26. | Comenius decision required |

| Acceptance IDs | Pass? | Evidence | Status |
|----------------|-------|----------|--------|
| REP-01, REP-02, REP-04, REP-05 (Done-when) | Partial | Payload + stream + audit; PDF byte hash missing | Alternative proposed |
| REP-03 (clarify in v1.3 if applicable) | TBD | Clarify with v1.3 | Evidence pending |

| Evidence to retain | Have we retained it? | Status |
|--------------------|----------------------|--------|
| Canonical schema; payload and artefact hashes; access transcript; audit sample; semantic re-render result; provenance inspection record | Partial (code + PRD-RPT-01) | Evidence pending |

| Done when | Met? |
|-----------|------|
| REP-01, REP-02, REP-04 and REP-05 pass; report access is tenant-scoped; provenance survives into the issued artefact | **Partial** — core path yes; Gate B evidence incomplete |

**Authoritative references:** Sections 12.2, 19-20 and 35.5; O-09, O-10, O-26 and O-28; GB-05, GB-22 and GB-23.

---

### WP6 Logging, Retention, Backups and Incident Readiness

**Outcome.** Klints can reconstruct security-relevant actions, expire and delete approved data, restore safely and execute a named incident response.

| # | Rohan / Astrapse action (as question) | Answer / evidence | Status |
|---|---------------------------------------|-------------------|--------|
| WP6-1 | Define append-only audit events for access, credentials, reports, AI metadata, deployments and administrative actions without logging prohibited content? | Hash chain + migration `0030` immutability triggers + `verify_audit_chain`. Evidence: `dataruns/audit.py`, migrations, tests. | In progress |
| WP6-2 | Implement the retention matrix as configuration after approval; do not hard-code an invented default? | Reports label `tenant-default` only; **matrix not approved**. | Comenius decision required |
| WP6-3 | Implement expiry, deletion records, backup expiry and deletion replay after restore? | Not Gate-B evidenced. Backups **OFF** in dev. | Not started |
| WP6-4 | Define monitoring for isolation failures, credential access, authentication abuse, egress failures and provider or deployment anomalies? | **Grafana live** (+ Loki/Alloy). Five alert classes not all test-fired. | In progress |
| WP6-5 | Write incident, credential-compromise and cross-tenant-exposure runbooks and support a tabletop exercise? | 24h critical supported; formal tabletop **not done**. | Evidence pending |
| WP6-6 | Implement and time a clean-environment restore and document degraded operation when the model, a connector or renderer is unavailable? | Restore **never tested**. Target **5–10 min** when backups enabled for live partner. | Blocked |

| Five required alert classes (test-fire each) | Pass? | Evidence | Status |
|----------------------------------------------|-------|----------|--------|
| Isolation failures | No | Grafana live; class not evidenced | Evidence pending |
| Credential access | No | Not evidenced | Evidence pending |
| Authentication abuse | No | Not evidenced | Evidence pending |
| Egress failures | No | Not evidenced | Evidence pending |
| Provider or deployment anomalies | Partial | Grafana/LangSmith observability | In progress |

| Acceptance IDs | Pass? | Evidence | Status |
|----------------|-------|----------|--------|
| RET-01 … RET-04 | No | Retention matrix not approved; backups off | Comenius decision required |
| IR-01 | No | No tabletop packet | Evidence pending |
| BCP-02 | No | Never restore-tested | Blocked |
| LOG family (exact IDs in v1.3 §§21–22, 35.6) | Partial | Audit chain exists | In progress |

| Evidence to retain | Have we retained it? | Status |
|--------------------|----------------------|--------|
| Audit samples; retention configuration; deletion and restore transcripts; alert test fires; runbooks; tabletop and degraded-mode records | Audit code/tests yes; restore/tabletop no | Evidence pending |

| Done when | Met? |
|-----------|------|
| RET-01 to RET-04, IR-01 and BCP-02 pass; five required alert classes fire; named responders can execute the runbook | **No** |

**Authoritative references:** Sections 21-22 and 25-26; O-11, O-12, O-18 and O-19; GB-07 and GB-19 to GB-21.

---

### WP7 Secure CI/CD, Review and Continuity

**Outcome.** The production artefact is reviewed, immutable, reproducible from the pipeline and deployable or recoverable by someone other than its author.

| # | Rohan / Astrapse action (as question) | Answer / evidence | Status |
|---|---------------------------------------|-------------------|--------|
| WP7-1 | Establish repository visibility, organisation plan and the independent production approval mechanism? | Live SoT: `georgechief/DEV_KLINTS_BACKEND` tags. Auto tag deploy. Plan/visibility/approver → Comenius. Sahil secondary under guidance. | Comenius decision required |
| WP7-2 | Separate production credentials; restrict them to the production job and narrowest supported scopes? | Secrets via GitHub Actions into deploy; formal prod separation evidence pending. | In progress |
| WP7-3 | Protect the default branch; pin actions to commit hashes; run dependency, container and secret scans; retain the SBOM? | SBOM / pinned Action hashes / branch protection **not proven in-repo** as Gate B hard asks. | Evidence pending |
| WP7-4 | Build once and promote the same digest; separate migration credentials and approvals; test a documented rollback action? | Tag-based CD; digest promotion / rollback evidence incomplete. | Evidence pending |
| WP7-5 | Record digest, approver, migration status, timestamp and outcome for every deployment? | RELEASES.md / tag history partial; dual-control approval not shown. | Evidence pending |
| WP7-6 | Write deployment, patch, restore and credential-rotation runbooks and demonstrate deployment by a second person? | Deploy scripts exist; Sahil can operate under guidance; formal second-person demo evidence pending. | In progress |

| Acceptance IDs | Pass? | Evidence | Status |
|----------------|-------|----------|--------|
| CICD-01 … CICD-05 (Done-when minimum) | No | Auto deploy; author-alone control incomplete | Evidence pending |
| CICD-06 … CICD-13 (cited in WP7 refs — disposition via v1.3) | No | Not evidenced | Not started |
| BCP-03, BCP-07 | No | Continuity demos incomplete | Evidence pending |
| VUL family (v1.3) | No | Pen test not booked | Blocked |
| O-14 (cited with O-02/O-03 — pull definition from v1.3) | Pending | Sahil secondary recommended | Comenius decision required |

| Comenius inputs | Notes | Status |
|-----------------|-------|--------|
| Confirms GitHub facts | Plan + visibility needed | Comenius decision required |
| Names the independent approver | Not named | Comenius decision required |
| Identifies the secondary operator | Sahil Kumar under guidance | Complete |

| Evidence to retain | Have we retained it? | Status |
|--------------------|----------------------|--------|
| Workflow configuration; branch/environment protection; token scopes; scan/SBOM output; digest trace; rollback test; second-person deployment record | Workflows yes; protection/SBOM/demo Partial/No | Evidence pending |

| Done when | Met? |
|-----------|------|
| CICD-01 to CICD-05 pass; the author cannot deploy alone; production secrets are inaccessible from ordinary builds and forks | **No** |

**Authoritative references:** Sections 23, 24 and 26; O-02, O-03 and O-14; GB-18; CICD-01 to CICD-13; BCP-03 and BCP-07.

---

### WP8 Tenant-Local Outcome Instrumentation

**Outcome.** MVP1 records issue-to-fix-to-outcome sequences inside each tenant without creating any cross-tenant contribution or benchmark path.

| # | Rohan / Astrapse action (as question) | Answer / evidence | Status |
|---|---------------------------------------|-------------------|--------|
| WP8-1 | Implement tenant-scoped issue, proposed-fix, approved-fix, execution-status and outcome-observation events? | Tenant-local intent Accepted; full event-chain evidence pending. | In progress |
| WP8-2 | Record attribution windows, method/version, observation confidence and metric provenance? | Not fully Gate-B evidenced. | Evidence pending |
| WP8-3 | Ensure the subsystem has no contribution plane, no cross-tenant aggregation and no external benchmark egress? | Gate E deferred — no cross-tenant benchmark plane claimed. | Accepted |
| WP8-4 | Include the outcome objects in tenant-isolation tests, retention treatment and access logging? | Tied to TEN/retention — incomplete. | Evidence pending |

| Acceptance IDs | Pass? | Evidence | Status |
|----------------|-------|----------|--------|
| BEN-01 | Partial | Architecture intent: no cross-tenant benchmark | Evidence pending |
| GE-01 … GE-08 (Gate E — future; not implemented here) | N/A | POST-MVP | Not applicable |

| Evidence to retain | Have we retained it? | Status |
|--------------------|----------------------|--------|
| Schema; sample tenant-local event chain; data-flow inspection; BEN-01 test; isolation and retention evidence | Incomplete | Evidence pending |

| Done when | Met? |
|-----------|------|
| BEN-01 passes and the architecture contains no active cross-tenant benchmark path | **Partial** — no Gate E path claimed; BEN evidence incomplete |

**Authoritative references:** Section 28; GB-24; BEN-01. Gate E controls are future and are not implemented here.

---

## 6 Gate B Readiness Checklist

### GATE RULE

Gate B is cumulative and binary. No live tenant data is authorised until every blocker is complete, evidenced and approved by Comenius Agency. A working feature without evidence remains incomplete.

**Astrapse:** Gate B is **Blocked / not complete**. Do not claim live-data ready.

### 6.1 Contractual, product and legal

| ID | Required outcome | Primary owner | Blueprint baseline | Our answer / evidence | Status |
|----|------------------|---------------|--------------------|-----------------------|--------|
| GB-01 | Astrapse Labs Article 28 terms, SCCs where required and TIA executed or confirmed | Comenius + counsel | Not established | Engineering practice only — ask George / Comenius counsel | Legal/provider evidence required |
| GB-02 | Tenant agreement and Article 28/subprocessor terms ready and signed before ingestion | Comenius + counsel | Planned | Ask Comenius counsel | Legal/provider evidence required |
| GB-03 | Mistral DPA executed and subprocessor position obtained | Comenius | Not established | Ask Comenius (B13b agreed) | Legal/provider evidence required |
| GB-04 | Subprocessor register and ROPA complete, dated and available | Comenius | Planned | Ask Comenius | Legal/provider evidence required |
| GB-05 | Report audience decision and Article 50 legal determination held before external pilot | Comenius + counsel | Not established | Product intent: authorized account personnel only; Art. 50 = counsel | Legal/provider evidence required |
| GB-06 | DPIA screening signed; full DPIA completed if screening establishes likely high risk | Comenius + joint | Planned | Ask Comenius counsel | Legal/provider evidence required |
| GB-07 | Retention matrix covering all five artefacts, logs, audit and backups approved | Comenius | Planned | Not approved. PDF zero file retention; DB payload may exist; backups off in dev | Comenius decision required |

### 6.2 AI route and egress

| ID | Required outcome | Primary owner | Blueprint baseline | Our answer / evidence | Status |
|----|------------------|---------------|--------------------|-----------------------|--------|
| GB-08 | Mistral evidence handled under the four-group model; Group 1 cannot be dispositioned | Comenius | Not established | Provider packet not established — ask Comenius / Mistral | Legal/provider evidence required |
| GB-09 | AI Data Contract, allow-list, suppression, manifest and fail-closed behaviour implemented | Comenius + Astrapse | Planned | PrivacyGate + allowlist yes; 50-subject suppression **no** | Alternative proposed |
| GB-10 | EU region pinned; start-up fails if region is absent; global endpoint cannot be selected | Comenius + Astrapse | Planned | We **use EU Mistral in ops**. App does **not** yet refuse to start if a non-EU endpoint were set. Model id: `mistral-small-latest`. | Alternative proposed |
| GB-11 | No prompt or response content in logs, traces, telemetry or error reporting | Comenius + Astrapse | Planned | LangSmith on; must confirm allowlisted I/O only — evidence pending | Evidence pending |
| GB-12 | Complete report produced through deterministic fallback with provider unreachable | Comenius + Astrapse | Planned | Deterministic path exists; formal unreachable test evidence pending | In progress |

### 6.3 Isolation, credentials and access

| ID | Required outcome | Primary owner | Blueprint baseline | Our answer / evidence | Status |
|----|------------------|---------------|--------------------|-----------------------|--------|
| GB-13 | Tenant isolation implemented, all negative tests passed and independently reviewed | Astrapse + reviewer | Planned | App-level company scoping; **no RLS**; pen test not booked. Future per-tenant Docker. | Alternative proposed |
| GB-14 | Credential store implemented, backup-decryption test passed and independently reviewed | Astrapse + reviewer | Planned | Shared Fernet via Actions; rotatable; no per-tenant DEK; independent review not done | Alternative proposed |
| GB-15 | No standing production access; named access matrix and expiring break-glass tested and audited | Comenius + Astrapse | Planned | Named: Rohan Girdhani + Sahil Kumar; 24h critical; formal break-glass test missing | Evidence pending |
| GB-16 | DigitalOcean and production account ownership documented under Comenius Agency | Comenius | Planned | Service map partial (Astrapse); ownership docs → Comenius | Legal/provider evidence required |

### 6.4 Operations and evidence

| ID | Required outcome | Primary owner | Blueprint baseline | Our answer / evidence | Status |
|----|------------------|---------------|--------------------|-----------------------|--------|
| GB-17 | Service-by-service hosting map complete; every unavailable fact recorded, not converted into a claim | Comenius + Astrapse | In progress | Frankfurt droplet + Managed PG ~2GB; apis.klints.io; Grafana; no LB. Provider DPA gaps recorded. | In progress |
| GB-18 | Independent production deployment approval and CI/CD capability facts evidenced | Comenius + Astrapse | Conditional | Tag auto-deploy; dual-control / GitHub plan facts incomplete | Evidence pending |
| GB-19 | Clean restore and deletion replay tested; deleted records absent before restored environment is exposed | Comenius + Astrapse | Planned | Backups OFF; **never restore-tested**; target 5–10 min when enabled | Blocked |
| GB-20 | Incident runbook complete and one tabletop exercise performed | Comenius + joint | Planned | 24h critical; tabletop packet not done | Evidence pending |
| GB-21 | Security monitoring live and all five alert classes test successfully | Comenius + Astrapse | Planned | Grafana live; five alert classes not all test-fired | In progress |
| GB-22 | Canonical payload, both hashes, semantic re-render and issuance/access audit implemented | Comenius + Astrapse | Planned | payload + payload_hash; PDF stream; **no PDF byte hash**; download audited | Alternative proposed |
| GB-23 | Article 50-ready document provenance survives the full report pipeline | Comenius + Astrapse | Planned | Engineering provenance partial; Art. 50 legal determination → counsel | Legal/provider evidence required |
| GB-24 | Tenant-local outcome instrumentation active with no contribution plane | Comenius + Astrapse | Planned | No cross-tenant benchmark claimed; BEN evidence Partial | In progress |
| GB-25 | Versioned customer security evidence pack assembled; every answer has an evidence reference | Comenius | Planned | **Not assembled**; evidence to live in backend repo | Not started |

---

## 7 Minimum Acceptance Evidence

Use the full procedures in **Section 35 of v1.3**. The matrix below is the minimum execution index, not a replacement test specification.

| Family | What must be demonstrated | Evidence retained | Gate | Pass? | Our evidence link | Status |
|--------|---------------------------|-------------------|------|-------|-------------------|--------|
| TEN-01 to TEN-09 | No cross-tenant access through every defined access path, including DB role, pooler, jobs, reports, support, credentials and AI metadata | CI output, query transcripts, review record | B | No | App scoping only (`get_user_company`); no RLS; no independent review | Blocked |
| IAM | Server-validated identity, tenant membership, privileged MFA, revocation, offboarding and audited break-glass | Configuration, timing tests, access/audit samples | B | Partial | Roles exist; MFA/break-glass incomplete | Evidence pending |
| CON-01 to CON-06 | One tenant key cannot decrypt another; revoked tokens fail; logs are clean; restored development backup cannot decrypt credentials | Test output, log scan, restore transcript | B | No | Shared Fernet Alternative; backups off | Alternative proposed |
| AI-01 to AI-11 | Prohibited data blocked; unknown fields fail closed; regional endpoint enforced; invalid output rejected; fallback complete; substitution detected | Canary and adversarial runs, manifests, log scan | B | Partial | PrivacyGate/allowlist; no EU hard-pin; no 50-cohort | Alternative proposed |
| REP-01 to REP-05 | Report access is scoped; issued hash matches; values trace to payload; semantic re-render passes; provenance survives | HTTP transcript, hashes, comparison and inspection records | B | Partial | payload_hash + PDF stream; no PDF byte hash | Alternative proposed |
| RET-01 to RET-04 | Expiry, erasure, restore/deletion replay and backup expiry follow the approved policy | Job logs, store inspection, restore transcript | B | No | Matrix not approved; backups off | Comenius decision required |
| CICD-01 to CICD-05 | Author cannot deploy alone; secrets unavailable to branch/fork; same reviewed digest promoted; rollback works; logs contain no tenant data or secret | Pipeline transcripts, digest trace, timed rollback, scans | B | No | Tag auto-deploy; dual-control incomplete | Evidence pending |
| IR-01 / BCP-02 | Named responder can execute the incident runbook; clean restore meets approved objectives | Tabletop record, timed restore | B | No | Never restore-tested; no tabletop | Blocked |
| BEN-01 | No cross-tenant contribution, aggregation or egress exists in MVP1 outcome instrumentation | Architecture inspection and egress log | B | Partial | Gate E not built; BEN packet incomplete | Evidence pending |

### 7.1 Review finding standard

**SINGLE STANDARD**

| # | Rule | Confirmed? | Status |
|---|------|------------|--------|
| 7.1.1 | No unresolved Critical or High finding | N/A — independent review not started | Blocked |
| 7.1.2 | Every Medium finding closed, assigned a documented treatment plan with owner and deadline, or formally accepted by the accountable owner | N/A until review | Blocked |
| 7.1.3 | Every Low finding recorded and tracked | N/A until review | Blocked |
| 7.1.4 | Formal acceptance of a Medium finding belongs in the **Decision and Exception Register** | Process Accepted when findings exist | Accepted |

### 7.2 Evidence naming and storage

| # | Rule / question | Our practice | Status |
|---|-----------------|--------------|--------|
| 7.2.1 | Use the authoritative ID at the start of every evidence filename (e.g. `TEN-03_pooler_isolation.pdf`) | Will use when Gate B packet assembled; not yet | Evidence pending |
| 7.2.2 | Store raw test output and a short human-readable result summary; screenshots alone are not sufficient where machine output exists | Plan: backend repo | Evidence pending |
| 7.2.3 | Record environment, artefact/commit digest, tester, date, result and linked finding or exception | Plan yes; not systematically applied yet | Evidence pending |
| 7.2.4 | Redact secrets and tenant data from evidence; live design-partner data must not be copied into the evidence repository | Accepted practice | Accepted |
| 7.2.5 | Keep failed results and their remediation history; do not retain only the final passing screenshot | Accepted practice | Accepted |

---

## 8 Gate B Blocking Decisions and Evidence

These items require owner action outside normal implementation. Rohan should identify dependencies and recommendations, but must not select product, legal or risk outcomes on behalf of Comenius Agency.

### 8.1 Immediate Comenius decisions

| ID | Decision | Input required from Rohan | Owner | Our recommendation / notes | Status |
|----|----------|---------------------------|-------|----------------------------|--------|
| O-01 | Exact DigitalOcean product | Recommended option, trade-offs, deployment and credential implications | Comenius + Astrapse | **Recommend:** Droplet + Managed Postgres (~2 GB) Frankfurt now; add LB/autoscaling (~3d) when design partner goes live. No Spaces called out. | Accepted |
| O-02 / O-03 | GitHub plan, visibility and independent approver | Required protection mechanism and feasible fallback | Comenius | Live SoT: `georgechief/DEV_KLINTS_BACKEND` tags. Plan/visibility/approver = Comenius. | Comenius decision required |
| O-09 | Assessment Report intended audience | Confirm how access and download controls support each option | Comenius | **Recommend:** authorized account personnel only; stream PDF; no shareable file trail. | Alternative proposed |
| O-11 / O-12 | Retention periods and legal-hold policy | Inventory of stores, logs, backups and deletion capabilities | Comenius | PDF zero file retention; JSON payload may remain in DB; backups off in dev until live partner. Need approved matrix. | Comenius decision required |
| O-13 | Key/secrets implementation | Preferred technical option after O-01 | Astrapse | **Recommend:** stay env Fernet via GitHub Actions (rotatable). Disclose single shared key — not per-tenant DEK/KMS. | Alternative proposed |
| O-14 | *(Cited in WP7 with O-02/O-03 — definition in v1.3; likely continuity / secondary operator)* | Pull wording from v1.3; supply technical input | Comenius + Astrapse | **Recommend secondary:** Sahil Kumar under guidance; 24h critical with Rohan. | Comenius decision required |
| O-16 / O-17 | First design partner, jurisdiction and scale | Capacity/security constraints and maximum supported volumes | Comenius | Capacity: current ~2GB Managed PG; no LB yet. Partner choice = Comenius. | Comenius decision required |
| O-18 | RTO and RPO | Feasible targets and cost/architecture consequences | Comenius | **Recommend restore target 5–10 min** when DO backups enabled; never tested yet. | Comenius decision required |
| O-19 | Incident owners and contact routes | Runbook roles and technical escalation needs | Comenius | Technical: Rohan primary, Sahil secondary; formal IR owners = Comenius. | Comenius decision required |
| O-25 | Exact sanitised A1 payload retention | Implementability, storage and deletion implications of Options A/B | Comenius + privacy | Implementable either way; need decision. | Comenius decision required |
| O-26 | Cryptographic signing at P0 or enhanced control | Implementation cost and key-custody implications | Comenius | **Recommend:** keep optional; do not block base hash/provenance. | Comenius decision required |
| O-27 | Session revocation service level | Measured feasible target and technical dependency | Comenius | Need measured target; roles exist today. | Comenius decision required |

**Also check v1.3 for any O-05…O-08, O-15, O-20…O-22 not listed in this working edition.**

### 8.2 Legal and contractual determinations

| ID | Determination | Owner | Our notes | Status |
|----|---------------|-------|-----------|--------|
| O-04 | Astrapse Labs Article 28 terms, SCCs where required and transfer impact assessment | Counsel | Ask George / Comenius counsel — not signed in this repo | Legal/provider evidence required |
| O-10 and O-28 | Article 50 applicability, first external pilot status and any transition or R&D analysis | Counsel | Ask counsel; product audience = authorized personnel | Legal/provider evidence required |
| O-23 | NIS2 and Czech Act No. 264/2025 Coll. screening inputs and decision D-17 | Counsel | Ask counsel | Legal/provider evidence required |
| O-24 | Controller, processor or subprocessor position for the tenant relationship | Counsel | Ask counsel | Legal/provider evidence required |
| O-29 | Mistral GDPR role after the production payload, telemetry and terms are assessed | Counsel | Ask counsel + Mistral DPA (GB-03) | Legal/provider evidence required |

### 8.3 External provider evidence

| Source | Required now | Rohan's role | Our evidence / gaps | Status |
|--------|--------------|--------------|---------------------|--------|
| Mistral | MPA-01 to MPA-07 mandatory; MPA-08, 09 and 11 evidenced or formally dispositioned; MPA-10 requested/status recorded; MPA-12 cost planning only | Implement technical tests and supply exact endpoint/model/configuration evidence | Model `mistral-small-latest`; EU ops practice; PrivacyGate. DPA/Group-1 packet = Comenius. No LiteLLM. | Legal/provider evidence required |
| DigitalOcean | Service-by-service region, subprocessor, support, backup, deletion, logging and disaster-recovery map plus DPA | Supply exact service inventory and identify documentation gaps | Frankfurt droplet + Managed PG ~2GB; backups off; Grafana. DPA/subprocessor map gaps remain. | Evidence pending |
| GitHub | Plan, visibility and available production deployment protection for that combination | Supply workflow design and required capability facts | Tag CD from DEV_KLINTS_BACKEND; Actions secrets for Fernet. Plan/visibility = Comenius. | Comenius decision required |
| Independent reviewer | Isolation and credential-store review by someone other than the code author | Prepare reviewable evidence and resolve findings | Path: pentest-tools.com; **not booked**. Gate B window 7–10d outside phase 1. | Blocked |

---

## 9 Working Method and Control of Change

### 9.1 Suggested implementation board

| Field | Required content | Do we track this? | Status |
|-------|------------------|-------------------|--------|
| Requirement ID | Full blueprint ID or work-package ID | Yes — this pack | In progress |
| Status | Not started; In progress; Evidence pending; Blocked; Ready for independent review; Complete | Yes — this pack | In progress |
| Owner | Named individual, not only an organisation | Rohan / Sahil / Comenius as noted | In progress |
| Dependency | Open decision, provider evidence, another WP or external reviewer | Yes — legal + pen test called out | In progress |
| Implementation reference | Ticket, pull request, commit and deployed artefact digest | Partial (tags / RELEASES.md) | Evidence pending |
| Evidence | Test result, configuration export, review record, runbook or executed instrument | Backend repo plan; packet incomplete | Evidence pending |
| Exception | Decision Register entry, owner, expiry/review date and residual risk | Alternatives listed; formal register with Comenius pending | Comenius decision required |

### 9.2 Review cadence

| # | Cadence | Happening? | Status |
|---|---------|------------|--------|
| 9.2.1 | **Implementation review** — work-package status, new dependencies and architecture deviations at least weekly while Gate B work is active | Planned when Gate B window opens (outside phase 1) | Not started |
| 9.2.2 | **Evidence review** — do not wait until the end; review evidence as each control reaches Ready for independent review | Plan Accepted; not yet at Ready | Evidence pending |
| 9.2.3 | **Decision review** — escalate any item that blocks final architecture, creates material cost or schedule impact, or would change a customer-facing security claim | Yes — Alternatives + legal escalations in this pack | In progress |
| 9.2.4 | **Gate review** — Gate B closes only through an explicit Comenius approval based on the complete evidence register | Not started — Gate B Blocked | Blocked |

### 9.3 Change and exception protocol

When the current implementation cannot meet a requirement, Rohan should submit a short change note containing:

| # | Change-note field | Included in our notes? | Status |
|---|-------------------|------------------------|--------|
| 9.3.1 | The affected requirement and work package | Yes — this pack / companion | Complete |
| 9.3.2 | The technical reason and evidence | Yes | Complete |
| 9.3.3 | The proposed alternative | Yes (RLS→app/Docker; Fernet; model alias; write scope disposition A; PDF hash) | Complete |
| 9.3.4 | Security, privacy, product, cost and schedule impact | Yes — Gate B 7–10d; later LB/Docker estimates | Complete |
| 9.3.5 | The residual risk and compensating controls | Yes — disclose shared key, no RLS, gated writebacks, EU ops | Complete |
| 9.3.6 | The decision owner and date required | Comenius / counsel for acceptance | Comenius decision required |

**STOP CONDITION:** Do not implement a material alternative until Comenius records the decision. A code merge is not approval of a security exception.

---

## 10 Gate B Handover Package

Rohan's Gate B handover should be a compact evidence pack. It does not need to repeat the full blueprint.

### 10.1 Required handover contents

| Package | Minimum contents | Ready? | Link / location | Status |
|---------|------------------|--------|-----------------|--------|
| Architecture | Final as-built system/data-flow diagram, service and region inventory, ingress/egress design and environment boundaries | Partial | Inventory in answers companion; diagrams incomplete | Evidence pending |
| Isolation | Database roles and RLS evidence, pooler behaviour and full TEN negative-test output | No | App scoping Alternative; no RLS | Alternative proposed |
| Credentials | Key hierarchy, access policy, connector scopes, restore-decryption test and independent review | Partial | Fernet + Actions; review missing | Alternative proposed |
| AI route | Redacted Mistral configuration, AI Data Contract schema, manifests, egress/log tests and deterministic fallback output | Partial | Code path; EU hard-pin/cohort gaps | Alternative proposed |
| Reports | Canonical schema, hash records, report access tests, semantic re-render and provenance inspection | Partial | payload_hash; no PDF byte hash | Alternative proposed |
| Operations | Logging/monitoring configuration, alert tests, retention/deletion implementation, restore transcript, incident and degraded-mode runbooks | Partial | Grafana live; backups off; no restore/tabletop | Evidence pending |
| Delivery | CI/CD configuration, approval evidence, scan/SBOM outputs, digest promotion and rollback result | Partial | Tag workflows / RELEASES.md | Evidence pending |
| Continuity | Patch process, deployment/restore runbooks and second-person deployment demonstration | Partial | Sahil secondary; demos incomplete | Evidence pending |
| Status | Final requirement disposition, open findings, exceptions, dependencies and bottom-up estimate actuals/variance | Partial | This pack + companion; review findings N/A | In progress |

### 10.2 Final questions before Gate B

If any answer is **No**, live tenant processing remains blocked. Synthetic development may continue unless the issue also invalidates the synthetic environment boundary.

| # | Question | Y/N | Evidence |
|---|----------|-----|----------|
| 10.2.1 | Can Rohan demonstrate that no live data or production credential entered non-production? | Partial | Synthetic/fabricated data practice; formal proof packet not assembled |
| 10.2.2 | Can an independent reviewer reproduce the tenant-isolation and credential-store evidence? | No | Pen test not booked; no RLS; shared Fernet |
| 10.2.3 | Can Klints identify exactly what left the environment in every model call without exposing prohibited content in logs? | Partial | PrivacyGate/allowlist; LangSmith active — full proof pending |
| 10.2.4 | Can a report be traced to its canonical payload, model route, policy version, human edits and issued-file hash? | Partial | payload_hash yes; PDF byte hash no; Art. 50 open |
| 10.2.5 | Can a second person deploy, restore and initiate incident response using the written runbooks? | Partial | Sahil can deploy under guidance; restore never tested; no tabletop |
| 10.2.6 | Does every customer-facing security statement have an evidence reference or an explicit not-established qualification? | No | GB-25 pack not assembled |

### GATE B OUTCOME

If any answer in §10.2 is no, live tenant processing remains blocked.

**Current outcome:** Gate B remains **Blocked**. Gate A synthetic development may continue.

---

## Appendix A Where to Look in the Full Blueprint

Use this map only when implementation requires the exact normative wording, test procedure, legal analysis or evidence rule.

| Working topic | Authoritative v1.3 sections | Key IDs |
|---------------|----------------------------|---------|
| Scope, hosting and legal roles | Sections 2-10 | O-01, O-04, O-16, O-23, O-24 |
| Tenant isolation and identity | Sections 11-12, 24, 35.1-35.2 | TEN, IAM, GB-13, GB-15 |
| Connector credentials | Sections 13, 24, 35.3 | CON, O-13, GB-14 |
| AI gateway and provider | Sections 14-18, 35.4 | ADC, MPA, AI, GB-08 to GB-12 |
| Assessment Report and Article 50 | Sections 19-20, 35.5 | REP, A50, O-09, O-10, O-26, O-28 |
| Logs, retention and privacy operations | Sections 21-22, 35.6 | LOG, RET, O-11, O-12, O-25 |
| CI/CD, testing and incidents | Sections 23-26, 35.7 and 35.9 | CICD, VUL, IR, BCP |
| Write connectors and MCP | Section 27, Gate C, 35.8 | MCP, GC-01 to GC-10 |
| Outcome instrumentation and benchmarks | Section 28, Gate E, 35.9 | BEN, GB-24, GE-01 to GE-08 |
| Gates, risks, decisions and evidence | Sections 31-36 | GA, GB, GC, GD, GE, O, D, R |

---

## Appendix B Scope Boundary for This Working Edition

This working edition intentionally omits (per client PDF):

- full regulatory and legal reasoning;
- the complete five-artefact classification matrix;
- the detailed threat and risk registers;
- the full RACI and acceptance-test procedures;
- detailed explanations of deterministic DCS and narrative grounding;
- future Gate C and Gate E implementation specifications.

| # | Follow-up question | Status |
|---|--------------------|--------|
| B.1 | Do we have / will we obtain **v1.3** for exact test procedures (TEN/IAM/CON/ADC/MPA/AI/CICD/LOG/VUL)? | Comenius decision required — obtain v1.3 for Gate B test execution |
| B.2 | Who owns pulling the **five-artefact classification matrix** into GB-07 retention work? | Comenius decision required — Comenius owns retention matrix / GB-07 |
| B.3 | Gate C (GC-01…10) tracked separately — not answered as Gate B? | Accepted — Gate C Blocked; writebacks disposition A only (gated execute + test Shopify write scope) |
| B.4 | Gate E (GE-01…08) confirmed POST-MVP only? | Accepted / Not applicable — POST-MVP; no cross-tenant benchmarks |

Those omissions reduce reading time; they do not remove the underlying requirements. The authoritative content remains in v1.3.

### FINAL WORKING INSTRUCTION

Use the client Execution Blueprint to organise the build. Use **v1.3** to resolve exact wording, run the acceptance test and support any external security claim. Use **this pack** to record Astrapse answers, evidence links and dispositions in the same section order the client used.

---

*Source structure mirrored from Comenius Agency Execution Blueprint v1.0 (10 Aug 2026). Answer columns added for Astrapse Labs disposition work. Disposition filled 11 Sep 2026 from Rohan answers + code evidence; companion `SECURITY_ANSWERS_KNOWN_VS_NEEDED.md`.*
