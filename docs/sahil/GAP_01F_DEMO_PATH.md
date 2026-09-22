# GAP-01F — Demo path (W9-04)

Operator walkthrough for the **offline skincare demo tenant**. Not an in-app tour (F0.8).

**Slice:** GAP-01 F · **Branch:** `feature/gap01-slice-f-demo-seed`  
**Depends on:** Phase 1–2 (`seed_demo_tenant` identity + corpus + offline DCS REMEDIATE)

---

## What this demo is

| Fact | Detail |
|------|--------|
| Tenant | Separate demo workspace — does **not** change your real tenant’s contacts/orders |
| Masters | `seed_dcs_master` + `load_use_case_pilots` upsert **shared** catalogue rows (all workspaces) |
| Connectors | Shopify + Manago stubs (`gap01f_demo_seed`) — **not** live OAuth |
| Score | Offline DCS headline **~61** (REMEDIATE band 50–69; ~62 not hard AC) |
| Network | Seed path does **not** call live Shopify/Manago APIs |

Do **not** claim: live sync health, webhook latency, MCP publish, or Matrix `CONFIRMED_LIVE`.

### What the seed actually unlocks

| Ready after seed | Not auto-ready |
|------------------|----------------|
| Login as demo admin | Built workflow package |
| Stub connectors connected | QA PASS on a package |
| DCS score in mid-band (~61) | Handoff staged Send / activation |
| Fix worklist with FAIL/WARN checks | Pilots **ready** to build (see below) |

**Studio / QA / Handoff:** seed does **not** create a build package. Pilots use `min_dcs: 70`. With headline **~61**, UC recommendations show **Needs higher score** (`blocked_dcs_score`). That is intentional for a REMEDIATE demo — diagnose on Data Consistency + Fix first; do not expect a green Studio→QA→Handoff completion from seed alone.

---

## 0. Seed (backend)

From `klints_backend` (venv active, DCS workbook available for `seed_dcs_master`):

```bash
# Full default (~5000 corpus slots) — first time or recreate
python manage.py seed_demo_tenant --vertical=skincare --reset

# Faster smoke
python manage.py seed_demo_tenant --vertical=skincare --contacts=200 --reset --require-remediate
```

| Default | Value |
|---------|--------|
| Slug | `klints-demo-skincare` |
| Email | `demo@example.com` |
| Password | `DemoPass123!` |
| `--contacts` | `5000` (corpus index size; DB contact rows are higher because of Manago dup rows) |

**Reset:** `--reset` **retires** the existing demo slug (rename + deactivate + free email) then recreates. It does **not** hard-delete — Postgres forbids deleting `audit_logs`. Without `--reset`, the command refuses if the slug already exists.

**Useful flags**

| Flag | Effect |
|------|--------|
| `--skip-dcs` | Identity + stubs only (no corpus/score) |
| `--require-remediate` | Exit non-zero if headline not in REMEDIATE (cannot combine with `--skip-dcs`) |
| `--skip-masters` | Dev only — skip pilots + CheckMaster seed |
| `--slug` / `--email` / `--password` | Overrides |

---

## 1. Sign in (UI)

1. Open the app → `/signin`
2. Log in as **`demo@example.com`** / **`DemoPass123!`**
   (Use `example.com` — browsers often reject `*.local` on `type="email"` sign-in fields.)
3. You are now on the **demo tenant only** — use a separate session or sign out to return to your normal account

---

## 2. Demo path (connect → score → fix → studio → qa → handoff)

Nav labels match AppShell. Seed already ran offline import + DCS.

| Step | Route (nav label) | What you should see |
|------|-------------------|---------------------|
| **Connect** | `/integrations` (**Connected stack**); `/onboarding` only if you revisit connect UX | Shopify + Manago **connected** — **demo stubs** (`gap01f_demo_seed`), not live OAuth. Health badge shows **Demo** / lag **offline seed** (not Healthy). Do not re-run live connect expecting tokens. |
| **Score** | `/data-consistency` (**Data Consistency Score**); Overview at `/dashboard` | Numeric headline **~61** (not the word “REMEDIATE” in UI). Badge often **Below 70 threshold** (build-ready bar is 70). Backend `run_state` may be `INCOMPLETE` (coverage) — band is the AC. |
| **Fix** | `/fix` (**Fix**) | Worklist / check routing for FAIL/WARN (e.g. CI / LE / PT). Use Fix where a check gates a use case; some checks are evidence-only. |
| **Studio** | `/workflow` → `/workflow/$id` (**Workflow Studio**) | Package builder UI. Expect pilots **Needs higher score** until DCS ≥ 70 (or after remediating + re-score). No package is pre-built by seed. |
| **QA** | `/qa` (**QA validation**) | Empty / blocked until a package exists and hard tests run. PASS unlocks handoff CTA. |
| **Handoff** | `/handoff` (**Handoff**) | Empty / locked until QA PASS package bind. **Send** = human activation (approve → guide → confirm) — **not** live MCP publish. |

**Optional side paths:** `/lifecycle` (**Lifecycle cockpit**), `/opportunities` (**Opportunity tracker**).

**If you click “Run score” in the UI:** may attempt live fresh import against stub connectors and fail — expected. Prefer the offline seed for a known mid-band score; re-seed with `--reset` to refresh the demo score.

---

## 3. Reset and re-seed

```bash
python manage.py seed_demo_tenant --vertical=skincare --reset
```

- Wipes/replaces the active demo tenant: **retires** the old slug (audit-safe), then recreates identity, stubs, corpus, and offline DCS
- Does **not** delete other tenants’ companies/contacts
- Does **not** hard-delete audit rows (append-only) — retired demo tenants remain deactivated under `*-retired-*` slugs
- Re-login as `demo@example.com` after reset (old tenant id sessions are invalid)

To stop using the active demo without recreating: run `--reset` once (retires the slug) and do not re-seed, or seed a throwaway `--slug` for experiments. Do **not** hard-delete the tenant in admin/shell after audit activity — append-only `audit_logs` block CASCADE delete.

---

## 4. Honesty / known limits

| Limit | Note |
|-------|------|
| Offline seed | No live Shopify/Manago HTTP in `seed_demo_tenant` DCS path (website scrape skipped) |
| Stub connectors | UI refresh / re-score outside seed may fail — expected. Failed later runs can become “latest” and hide the seeded headline until you re-seed |
| Sign-in email | Default `demo@example.com` (not `*.local`) so HTML5 `type="email"` accepts it |
| Score vs Studio | REMEDIATE ~61 **by design** · pilots need **≥70** to leave `blocked_dcs_score` |
| UI vs backend band | UI shows number + 70-threshold badge · “REMEDIATE” is backend band language |
| Handoff Send | Human Manago activation (HO-02) — Slice B MCP still blocked |
| Shared masters | CheckMaster / pilots upserts are global, not tenant-private |
| Not in Slice F | In-app tour · W9-07 50k perf · partner API · Matrix live flips · pre-built package |

---

## Related

- Working gaps: [GAP_01_WORKING_GAPS.md](./GAP_01_WORKING_GAPS.md) (Slice F)
- PRD: [PRD_GAP_01_M2_CODE_GAPS_WEEKS_5_9.md](./PRD_GAP_01_M2_CODE_GAPS_WEEKS_5_9.md) (W9-03/04/05)
- Verify: `python scripts/verify_gap01f_backend.py` · `--run-tests`
- Command: `dataruns/management/commands/seed_demo_tenant.py`
