# Security answers — what we know vs what we need from you

**For:** Rohan (Astrapse) · Gate B disposition  
**Based on:** Client Execution Blueprint v1.0 + current `klints_backend` / staging deposit  
**Date:** 11 September 2026  

**How to read this**
- **We know** = verified from code, deploy docs, or staging config we can see  
- **Need from you** = only you / Comenius / counsel can confirm  
- Be honest with the client: do **not** claim Gate B closed where evidence is missing  

---

## Bottom line (1 minute)

| Topic | Reality today |
|-------|----------------|
| Live tenant data (Gate B) | Still **blocked** by the blueprint — we should **not** claim live-data ready |
| Synthetic / staging engineering | **OK to continue** (Gate A open) |
| Shared multi-tenant product | **Yes** — matches locked direction |
| Postgres RLS | **Not implemented** — isolation is application-level today |
| Connector secrets | **Fernet** with **one global env key** — not per-tenant DEKs |
| AI | Direct **Mistral**, default model **`mistral-small-latest`** (not pinned `2603`); PrivacyGate + allowlist exist; **ops says EU-region Mistral for now** — still **no hard EU pin in app code** |
| Hosting (Rohan confirmed 11 Sep 2026) | Droplet **+ Managed Postgres (~2 GB)** in **Frankfurt**; **no LB/autoscaling** yet; live SoT = **`georgechief/DEV_KLINTS_BACKEND` tags** |
| Access | **Rohan Girdhani** + **Sahil Kumar**; 24h critical; pen test via commercial tooling (not booked) |
| Secrets trust (Rohan) | Env Fernet via **GitHub Actions**; rotatable; never committed — still **one shared key** |
| Shopify scopes (Rohan) | Includes **`write_customers`** + reads (inventory/orders/products/store credit tx) — **not read-only** |
| Gate B effort (Rohan) | **7–10 days outside phase 1**: reviewer ~3–4d + remediations ~6d |
| Reports / backups | PDF **streamed**, no retained PDF file; DB backups **off** in dev; restore target **5–10 min** when enabled |
| Writebacks | **Code exists** (defaults OFF) — this **conflicts** with Gate C “no write path until Gate C” unless we disposition it honestly |
| Grafana | **Shipped on staging stack** (`/grafana/`) — observability, not security review |
| Legal / DPAs / retention / Art. 50 | **Almost all need Comenius + counsel** |

---

# Part A — What we already know

Answers are short. Evidence is the proof.

---

### A1. Hosting & deploy

**Answer:** Staging API runs on a **DigitalOcean droplet** via Docker Compose + nginx TLS, public host **`apis.klints.io`**. Deploy is GitHub Actions → SSH/rsync → `/opt/klints_backend`. There is **no** Postgres container in compose; the app uses **`DATABASE_URL`** from env.

**Evidence**
- `.github/workflows/deploy-development.yml` (DigitalOcean droplet deploy + health smoke)  
- `docker-compose.yml`, `deploy/nginx/klints.conf`, `deploy/scripts/deploy.sh`  
- Client deposit: `DEV_KLINTS_BACKEND/RELEASES.md` (tag-based CD; **`v1.0.2`** live as of 10 Sep 2026)  
- Health: `https://apis.klints.io/health/` → `{"status":"ok"}`

**Answered by you (11 Sep 2026)**
1. Droplet region = **Frankfurt** (visible on DigitalOcean).  
2. Database = **Managed Postgres in Frankfurt** (not Postgres on the droplet).  

**Still need from you**
3. Confirm which GitHub remote is the **live SoT** for the droplet today: `Rohan070/klints_backend` (main-push) vs `georgechief/DEV_KLINTS_BACKEND` (tags).

---

### A2. Multi-tenant model

**Answer:** Product is **shared multi-tenant**. Users belong to a **Tenant**; companies hang under tenant; APIs resolve the caller’s company via **`get_user_company`** (first company for that tenant). Isolation today is **application filters + role checks**, not database RLS.

**Evidence**
- `tenants/models.py` — `User.tenant`, `Company`  
- `tenants/auth/services.py` — `get_user_company`  
- Roles: `admin` / `analyst` / `viewer` on `User.Role`  
- M3-SEC-01 PRD already notes residual risk: multi-company-per-tenant not productized  

**Need from you**
4. For Gate B / WP2: do we **commit to adding Postgres RLS**, or propose an **Alternative** (app-level isolation + evidence suite) for Comenius to accept?  
5. Confirm product intent: **one company per tenant** for MVP1 live, or multi-company later?

---

### A3. Connector credentials

**Answer:** Connector secrets (API keys/tokens) are **encrypted at rest with Fernet**. The key comes from env **`CONNECTOR_FERNET_KEY`** — **one key for all tenants**. Secrets are masked in API responses. There is **no** per-tenant data-encryption key, and **no** app-level KEK rotation product.

**Evidence**
- `tenants/crypto.py`  
- `core/settings/base.py` — `CONNECTOR_FERNET_KEY`  
- `docs/API_AUTH_CONNECTORS.md`  
- Shopify default scopes in code: `read_orders,read_customers` (`.env.example`)

**Need from you**
6. Preferred secrets product after O-01 (env Fernet vs DO Spaces/KMS vs something else) — your **recommendation for O-13**.  
7. Staging: is `SHOPIFY_SCOPES` still **read-only**, or have write scopes been granted?

---

### A4. Writebacks (important conflict)

**Answer:** **Writeback execute/rollback code is in the product** under `/api/v1/writebacks/`. Defaults are **off** (`WRITEBACKS_ENABLED` false; company flag false). This is **not** “unreachable scaffolding” — it is a real API. Blueprint Gate C says write paths stay blocked until Gate C.

**Evidence**
- `core/urls.py` → writebacks include  
- Writeback adapters/views under `dataruns/writebacks/`  
- Settings flags in `core/settings/base.py`

**Need from you**
8. How should we **disposition** this for Comenius?  
   - **Option A:** Keep flags OFF in staging/prod until Gate C; document as dormant-but-gated; add verify that flags are off  
   - **Option B:** Ask Comenius to allow Gate C early for allowlisted writebacks  
   - **Option C:** Strip/disable routes until Gate C  

---

### A5. AI path

**Answer:** AI goes **direct to Mistral** (no OpenRouter adapter in code). Default model id is **`mistral-small-latest`**. Before each call we run **allowlist projection + PrivacyGate** (fail closed if PII/secrets remain). We do **not** hard-pin EU endpoint in code. We do **not** implement the blueprint’s 50-subject cohort/suppression rules. Reports still work without AI (deterministic payload); AI narrative is optional / fail-open on attach.

**Evidence**
- `dataruns/ai/providers/mistral.py`, `dataruns/ai/privacy_gate.py`, `dataruns/ai/allowlist.py`  
- `core/settings/base.py` / `dataruns/ai/constants.py` — `mistral-small-latest`  
- `docs/sahil/PRD_AI_01_…` (allows pinning `mistral-small-2603` via env)  
- Security doc still describes **LiteLLM** as target — **not** what compose runs today  

**Answered by you (11 Sep 2026)**
10. Mistral is used from the **EU region only for now** (ops confirmation).  

**Still need from you**
9. Pin staging/prod to **`mistral-small-2603`** now (match blueprint), or propose keeping `latest` with written Alternative?  
11. Is LangSmith tracing **on** in staging? If yes, confirm only allowlisted I/O is sent.  
12. Confirm: we will **not** claim LiteLLM is live until it actually is.  

**Honesty note for Comenius:** EU usage is an **ops/account practice** today. App code does **not** yet fail-closed if a non-EU endpoint were configured — that remains a Gate B gap unless we add a hard pin.

---

### A6. Assessment reports

**Answer:** Canonical **JSON payload** is stored and hashed (`payload_hash`). PDF is **streamed on download** (not stored as a file on the model). Download is audited. PDF footer uses payload hash — we do **not** separately store a SHA-256 of the PDF bytes today.

**Evidence**
- `dataruns/reports/payload.py`  
- `AssessmentReport` model fields (`payload`, `payload_hash`)  
- PDF view streams `HttpResponse`  
- PRD-RPT-01 docs  

**Need from you**
13. Report **audience** decision (**O-09**) — who may download?  
14. Do we need a true **issued-PDF byte hash** for Gate B, or is payload hash + stream enough as an Alternative?

---

### A7. Audit / tamper detection

**Answer:** Per-company **hash chain** exists. Management command **`verify_audit_chain`** exists. DB triggers in migration **`0030`** block silent UPDATE of protected fields and DELETE. Tests exist. Periodic Celery verify is **not** required yet (optional later).

**Evidence**
- `dataruns/audit.py`  
- `dataruns/management/commands/verify_audit_chain.py`  
- `dataruns/migrations/0030_audit_logs_immutability_triggers.py`  
- `dataruns/tests/test_audit.py`, `test_audit_immutability.py`  

**Need from you**
15. Nothing critical for “does it exist?” — for Gate B we still need a **named company id** and a saved command transcript as evidence when you want the packet filled.

---

### A8. Observability (Grafana)

**Answer:** Staging stack includes **Grafana + Loki + Alloy**. Intended URL: **`https://apis.klints.io/grafana/`**. Deploy workflow smokes Grafana/Loki. This supports contract “Grafana” language — it does **not** replace security review / tenant isolation evidence.

**Evidence**
- `docker-compose.yml` (grafana/loki/alloy)  
- Workflow M3-OBS smoke steps  
- `docs/sahil/M3_OBS_01_RUNBOOK.md`  
- Client claim notes credentials under M2 writeup Staging access  

**Need from you**
16. Confirm Grafana login still works with the shared ops account (or say if password was rotated).  
17. OBS Phase 6 (induce ERROR + alert email) — do you want that closed now or after SEC-01?

---

### A9. CI/CD (what the repo proves)

**Answer:** Production-like staging deploy is automated via GitHub Actions + SSH. **Product repo** deploys on **`main` push**. **Client DEV repo** deploys on **semver tags only**. Workflow does **not** show dual-control approval gates or SBOM generation in-repo.

**Evidence**
- `Rohan070/klints_backend` `.github/workflows/deploy-development.yml`  
- `georgechief/DEV_KLINTS_BACKEND` tag workflow + `RELEASES.md`  

**Need from you**
18. GitHub **plan** + **repo visibility** (O-02/O-03).  
19. Is **branch protection** on `main` (required review)?  
20. Who is the **independent production approver** / **secondary operator**?  
21. Do we need SBOM + pinned Actions hashes as a Gate B hard ask now?

---

### A10. What is clearly NOT done (say so cleanly)

| Blueprint ask | Status in one line |
|---------------|--------------------|
| Postgres RLS + FORCE RLS | **Not in code** |
| Per-tenant DEKs + formal KMS | **Not in code** |
| AI EU region hard-pin + start-up fail | **Not in code** |
| 50-subject cohort / suppression | **Not in code** |
| Legal DPAs / Art. 28 / Art. 50 / DPIA / ROPA | **Not ours alone — Comenius/counsel** |
| Approved retention matrix | **Not approved** (reports only have a label `tenant-default`) |
| Incident tabletop + restore drill evidence | **No packet in repo** |
| Independent isolation/credential review | **Not completed** |
| Customer security evidence pack (GB-25) | **Not assembled** |

---

# Part B — Your answers (Rohan, 11 Sep 2026)

### Platform (O-01 / WP1)

- [x] **B1.** Droplet region = **Frankfurt**
- [x] **B2.** Database = **Managed Postgres, Frankfurt**
- [x] **B3.** Today: **Droplet + Managed Postgres (~2 GB)** only. **No load balancer, no autoscaling, no Spaces called out.** LB/autoscaling planned when a **design partner goes live** (avoid spike cost in development). Estimate to implement LB/autoscaling later: **~3 days with testing**.
- [x] **B4.** Live deploy SoT for client staging = **`georgechief/DEV_KLINTS_BACKEND`** (tag-based).

### Isolation & access (WP2 / GB-13 / GB-15)

- [x] **B5.** **Today:** app-level company scoping (shared multi-tenant). **Not building Postgres RLS now.** **Future recommendation (post phase 1):** package system that spins **one Docker stack per tenant** (cloud or on-prem) from workflow — estimate **+7–10 days** with patching; decide after phase 1.
- [x] **B6.** People who can touch staging/ops: **Rohan Girdhani (Lead)** and **Sahil Kumar (Astrapse — code tester/reviewer; training for expansion)**.
- [x] **B7.** **24-hour critical break resolution** supported; broader team can jump in if needed. Formal break-glass runbook not named beyond that.
- [x] **B8.** Independent review path: schedule **industry-grade online pen test** (e.g. [pentest-tools.com](https://pentest-tools.com/)). Firm/engagement **not booked yet**.

### Secrets (O-13 / WP3 / GB-14)

- [x] **B9.** **Stay on env Fernet for MVP1.** Ops position: Fernet/env secret is **never leaked**; injected via **GitHub Actions** secrets into deploy; **rotatable anytime** without prior value being known to operators after rotation. Still a **single shared key** (not per-tenant DEK / KMS) — disclose as Alternative.
- [x] **B10 / B29.** **Disposition A (explained):** Shopify **`write_customers` is enabled for sandbox/test proof only** so adapters can be exercised against a real Shopify permission. **Actual writes in Klints are still gated in-app** (see A4 / Part D). Global `WRITEBACKS_ENABLED` defaults **False**; company `writeback_execute_enabled` defaults **False**. Execute also needs allowlisted check + approval. Gate C = when Comenius allows real/live write policy.
- [x] **B11.** Staging Shopify scopes (Rohan):  
  `read_customers`, **`write_customers`**, `read_inventory`, `read_orders`, `read_products`, `read_store_credit_account_transactions`  
  **Honesty:** this is **not read-only** — `write_customers` is a write capability toward Shopify and must be dispositioned vs Gate C.

### AI (WP4 / GB-08…12)

- [x] **B12.** Use the **model we actually ship**: **`mistral-small-latest`** (Mistral Small 4 alias in code/PRD). Blueprint pin `mistral-small-2603` is optional env freeze — **not claiming 2603 unless env says so**.
- [x] **B13a.** Mistral **EU region only for now**.
- [ ] **B13b.** Formal Mistral **DPA** — **ask Comenius** (agreed).
- [x] **B14.** **LangSmith is active** on staging, account **`noreplyklints@gmail.com`**, until Jiri provides a **klints.io** domain email for development accounts.

### Reports & retention (O-09 / O-11 / O-12 / WP5–6)

- [x] **B15.** Only **authorized account personnel** may generate/stream the PDF. Intent: **do not keep a shareable file trail** so PDFs are not passed around inside the org / Klints.
- [x] **B16.** Assessment **PDFs are live-generated → stated zero retention for PDF files**. (Canonical JSON payload may still exist in DB — disclose carefully; see honesty note.)
- [x] **B17.** Postgres **backups off** during development (fabricated data). Enable when onboarding a **live partner**. Restore to go-live again: **~5–10 minutes** (target).

### Legal (Comenius/counsel)

- [x] **B18–B22.** Agreed: formal legal actuals = **ask George / Comenius counsel** (Art. 28 / SCCs / Mistral DPA / Art. 50 / DPIA / controller-processor). Astrapse records engineering practice only.

### Ops continuity (WP6–7 / GB-19…21)

- [x] **B23.** **Never** restore-tested for Klints. Backups intentionally **off** in development. DO can turn backups on anytime.
- [x] **B24.** Ops visibility now: **Grafana live** + **LangSmith** for AI/error tracing. Full incident tabletop packet: **not done**. Recent DO incident (service deletion) noted as learned risk.
- [x] **B25.** Deployments are **auto** (tag workflow). **Sahil Kumar** can operate under guidance as secondary.

### Estimate / process (WP0 / §4.2)

- [x] **B26.** **Gate B rough estimate = 7–10 days outside phase 1 scope**, working with independent reviewer on comments/suggestions. Split: reviewer **~3–4 days**; Astrapse address + recheck to pass tests **~6 days**. (Also: LB/autoscaling later ~3 days; per-tenant package later ~7–10 days after phase 1.)
- [x] **B27.** Independent review = commercial pen-test style engagement (e.g. Pentest-Tools); effort as in B26. Calendar: earlier “August” intent slipped — schedule aligned to the **7–10 day Gate B window** when phase 1 allows.
- [x] **B28.** Evidence files live in the **backend repository**.

### Writebacks disposition

- [x] **B29.** **A — with honest test rationale:**  
  - **Why Shopify write scope is on now:** needed for **test/sandbox** customer-update proof (`write_customers` → `SHOPIFY.CUSTOMER.UPDATE`); without the OAuth scope, even sandbox execute cannot hit Shopify.  
  - **When a write actually happens in the app:** only if **all** of the following pass (code in `dataruns/writebacks/gates.py`):  
    1. Check id is on **WritebackAllowedCheck** allowlist  
    2. **Either** company `writeback_execute_enabled=True` **or** global `WRITEBACKS_ENABLED=True`  
    3. Valid **approval** + **diff_hash** bind  
  - Defaults: global flag **False**, company flag **False** → execute returns `writebacks_disabled`.  
  - **Gate C** = client permission for live/production write policy; until then keep product execute opt-in off for non-sandbox tenants and disclose Shopify scope as **granted for test capability**, not “production write open.”

---

# Part C — Plain explanations you asked for

### What is Gate B?

Think of the blueprint’s **gates** as traffic lights before real customer data:

| Gate | Meaning in plain English |
|------|---------------------------|
| **Gate A** | Engineering on **synthetic / staging** data — where we are now. OK to build. |
| **Gate B** | **Security / privacy / AI compliance bar** before **live tenant (real) data** is allowed. Checklist: hosting inventory, isolation evidence, secrets story, AI EU/model controls, audit, retention, legal DPAs, backups/IR, independent review packet, etc. |
| **Gate C** | **Writebacks / changing customer systems** allowed only after extra controls. |

So: **Gate B is not a code ticket name** — it is the client’s **“may we process real live data yet?”** gate. Until Gate B evidence is accepted, we must **not** claim live-data ready.

### What is “trust?” (secrets question B9)

This is about **who we trust to hold the key that decrypts connector secrets** (Shopify tokens, etc.).

Today:
- Secrets are encrypted with **Fernet**
- There is **one key** in the server environment (`CONNECTOR_FERNET_KEY`) for **all tenants**
- Anyone with droplet/env access can decrypt **all** connector secrets

Blueprint wants stronger “trust” later (per-tenant keys / KMS).

**Your decision for MVP1 (answered 11 Sep 2026):**
> Stay on **env Fernet**. Key is held in **GitHub Actions / deploy secrets**, not shared in chat or repo; **rotatable anytime** so prior value need not remain known. Disclose honestly: still **one shared encryption key** for all tenants — not per-tenant DEK/KMS.

### Legal “actuals” (B18–B22)

These are **lawyer / Comenius** documents, not something we invent from code:

| Item | What it is | Who owns the answer |
|------|------------|---------------------|
| Art. 28 / SCCs | Contract between Klints/Comenius and Astrapse for processing personal data | Comenius + counsel |
| Mistral DPA | Contract with Mistral for AI processing | Comenius / Klints account owner |
| Art. 50 | Legal view on **who may see assessment reports** | Comenius counsel |
| DPIA | Privacy impact screening | Comenius counsel |
| Controller vs processor | Who decides purpose of data vs who processes it | Comenius counsel |

**Honest actual from Astrapse today:** *engineering practices recorded; formal legal status = ask George/Comenius — not signed in this repo.*

---

# Part D — Write levels (how the app actually works)

Two different things get confused:

| Layer | What it is | Why it can be “on” in test |
|-------|------------|----------------------------|
| **Shopify OAuth scopes** | Permission Shopify grants the app (includes `write_customers`) | Needed so **sandbox/test** can prove a real customer update API call. Scope ≠ “Klints is writing to every shop.” |
| **Klints execute gates** | App code that must say yes before any writeback job runs | Defaults **off**. This is the real control for “is write allowed?” |

**When Klints actually allows a write** (`execute_allowed` in `dataruns/writebacks/gates.py`):

1. **Check allowlist** — that DCS/writeback check id is enabled in `WritebackAllowedCheck`  
2. **Company or global opt-in** — `company.writeback_execute_enabled` **or** env `WRITEBACKS_ENABLED`  
3. **Human approval bind** — `approval_id` + matching `diff_hash`  

If (2) is false → **`writebacks_disabled`** (403). Preview/planning can still run; execute cannot.

**Levels in plain English**

| Level | Meaning | Typical now |
|-------|---------|-------------|
| Shopify scope granted | App *could* call Shopify write APIs if Klints asks | `write_customers` **on for test** |
| Global kill-switch | `WRITEBACKS_ENABLED` | **False** (default) |
| Per-company opt-in | `writeback_execute_enabled` | **False** unless turned on for a sandbox/demo company |
| Allowlisted check + approval | Only specific fixes, after Approve | Required for execute |
| **Gate C (client)** | Policy OK to write on live partner systems | **Not claimed yet** |

**Honest sentence for Comenius**
> Shopify `write_customers` is installed so we can test the sandbox writeback path. Production-like execute stays blocked unless a company opts in (or the global flag is on) and an allowlisted check has approval. We are not claiming Gate C / unrestricted live writebacks.

---

# Part E — Suggested honest language (for replies to Comenius)

**Safe to say now**
> Client staging deploys from `georgechief/DEV_KLINTS_BACKEND` tags to DigitalOcean **Frankfurt**: droplet + Managed Postgres (~2 GB), no LB/autoscaling yet. Product is shared multi-tenant with **application-level company scoping**. Connector secrets use **Fernet** with the key in **GitHub Actions / deploy secrets** (rotatable; not committed to git). AI uses **Mistral EU**, model id **`mistral-small-latest`**, PrivacyGate/allowlist; **LangSmith** active (`noreplyklints@gmail.com` pending klints.io ops email). Assessment PDFs are **streamed for authorized users** (no retained PDF file store by design). Grafana is live for ops. Dev backups are **off** (fabricated data); DO backups to be enabled for live partner; restore target **5–10 minutes**. Gate B engineering+review window estimated **7–10 days outside phase 1** (reviewer ~3–4 days; remediations ~6 days). Independent review via commercial pen-test tooling — not completed. Legal DPAs / Art. 50 / DPIA = **Comenius counsel**. Future isolation direction under consideration: **per-tenant packaged Docker** (post phase 1). Synthetic development continues under **Gate A**.

**Do not say yet**
> “Gate B complete” · “pen test passed” · “Postgres RLS” · “per-tenant DEKs” · “read-only Shopify” · “EU AI hard-pin in code” · “LiteLLM live” · “backups restore-tested” · “legal DPAs complete”

**Must disclose as deviation / Alternative**
> No RLS today (app isolation). Single env Fernet key (rotatable via Actions). Model alias `mistral-small-latest`. Shopify OAuth includes **`write_customers` for sandbox/test capability**; Klints execute remains gated (global + company flags default off + allowlist + approval). Zero PDF file retention ≠ zero retention of all assessment data in DB. Per-tenant container packaging is a **future** proposal, not current live architecture.

---

*Part B answers complete. Merged into `SECURITY_QUESTIONS_FROM_EXECUTION_BLUEPRINT_v1.0.md` (Status + Answer + evidence) on 11 Sep 2026.*
