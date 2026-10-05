# Writeback Fix Ownership — MVP1 CheckMaster 42

**Purpose:** Decide carefully what Klints may Approve / mutate vs what stays plan-only, Download, or human/integrator work — and audit prior writebacks against Excel ownership.

**Scope:** Only the **42** checks in `docs/dcs_scoring/CHECK_MASTER_42.md` (sheet **09 MVP1 Check Scope**).  
Out of scope for this matrix: `WB-SHOP-01` (sandbox proof), `SP-01` (not in MVP1 42).

**Authority (SoT):**

| Layer | Source | Role |
|-------|--------|------|
| Check IDs / names / weights | `CHECK_MASTER_42.md` + Excel sheet 09 | Which checks exist in MVP1 |
| **Fix Owner / Fix Type / Suggested Fix** | Excel sheet **02 Check Catalogue** → seeded into `CheckMaster` via `seed_dcs_master` | **Who may execute a fix** |
| Runtime possible/not | `WRITEBACK_POSSIBLE_NOT_SHEET.csv` + registry mappings | What we advertise on Fix |
| Execute allowlist | FE `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` + `WritebackAllowedCheck` | What Approve may write |

**Extract date:** 2026-09-25 · workbook `Klints_Spec_InitialDataConsistencyCheck_v1.4.1_20260718.xlsx`  
**Owner counts (42):** Klints (automated) **18** · Data lead **10** · External integrator **10** · CRM manager **4**

---

## 1. Implementation rules (do not skip)

1. **Only MVP1-42** get catalogue writebacks. Never add Approve for IDs outside the 42 (except explicit sandbox proof like `WB-SHOP-01`).
2. **Default:** Approve / mutate only when `CheckMaster.fix_owner` is **`Klints (automated)`** *and* Fix Type includes automated writeback (or product logs an override).
3. **Never** treat sandbox ON as permission to ignore Fix Owner — FE allowlist + `WritebackAllowedCheck` + (when needed) `execute_mode=plan_only` are the real stops. The pipeline `fix_owner` gate is bypassed when Settings execute is enabled.
4. **CRM manager / Manual / External integrator** → Preview, Download, or plan-only. No silent Manago mutate unless product flips owner in CheckMaster and documents it here.
5. **Data lead** → not Klints by default. **CC-03** is the known early exception (Approve live under Settings); do not copy that pattern without product sign-off.
6. Before building a new writeback: find the row in **§3**, confirm owner + type, then add mapping / sheet / allowlist only if the verdict allows it.
7. If a prior build conflicts with this matrix → fix the build (narrow allowlist, plan-only, or disable), do not quietly change CheckMaster owner.

---

## 2. Verdict legend

| Verdict | Meaning |
|---------|---------|
| **Correct — Approve live** | Built; Klints owner; FE allowlist + registry execute OK |
| **Correct — plan-only** | Built Preview/Download; execute blocked; matches CRM / “not auto-merged” |
| **Correct — disabled** | Mapping present but `enabled=false` / preview blocked; matches Integration+Manual |
| **Correct — not a writeback** | Config / Manual / monitor / integrator — Download or ops only; do not build Approve |
| **Not built — Klints candidate** | Owner is Klints + automated writeback in type; safe to design next |
| **Not built — not Klints execute** | Owner is Data lead / CRM / External; Preview/policy/integration only unless product overrides |
| **Borderline — review** | Built Approve but Excel owner ≠ Klints; keep gated; do not extend pattern |

---

## 3. Full matrix — all 42 checks

Columns: **Fix Owner** / **Fix Type** from Excel → CheckMaster.  
**WB build** = current product state (registry + FE allowlist + PRDs as of WB-16 Phase A).

### 00 Foundation Gate

| Check | Name | Fix Owner | Fix Type | WB build | Verdict |
|-------|------|-----------|----------|----------|---------|
| FD-01 | Manago API authentication valid | Klints (automated) | Configuration | None | **Correct — not a writeback** |
| FD-02 | Shopify API authentication and scopes | Klints (automated) | Configuration | None | **Correct — not a writeback** |
| FD-03 | ERP feed reachable and parseable | Data lead | Configuration | None | **Correct — not a writeback** |
| FD-04 | API rate-limit headroom measured | Klints (automated) | Configuration | None | **Correct — not a writeback** |
| FD-05 | Historical data depth available | Klints (automated) | Configuration | None | **Correct — not a writeback** |
| FD-06 | Manago account/sub-account topology mapped | Data lead | Configuration | None | **Correct — not a writeback** |
| FD-07 | Manago site tracking code active | External integrator | Integration build | None | **Correct — not a writeback** |

### 01 Customer Identity

| Check | Name | Fix Owner | Fix Type | WB build | Verdict |
|-------|------|-----------|----------|----------|---------|
| CI-01 | Contact count reconciliation | Klints (automated) | Automated writeback (approved) | Approve live (`contact_upsert`) | **Correct — Approve live** |
| CI-02 | Guest checkout identity share | External integrator | Integration build | None | **Correct — not a writeback** |
| CI-03 | Duplicate contacts in Manago | CRM manager | Automated writeback (approved) | Plan-only Preview/Download (WB-16A); no FE Approve; no allowlist seed | **Correct — plan-only** (Phase B only after Loom + product; still not silent Klints merge) |
| CI-05 | External ID linkage integrity | Klints (automated) | Automated writeback (approved) | Approve live (`contact_upsert` externalId; missing only) | **Correct — Approve live** |
| CI-13 | Contact state distribution sanity | Data lead | Manual (guided) | None | **Correct — not a writeback** |
| CI-14 | Web identity match rate | External integrator | Integration build | None | **Correct — not a writeback** |
| CI-15 | Contact record freshness | CRM manager | Manual (guided) | None | **Correct — not a writeback** |

### 02 Lifecycle Event

| Check | Name | Fix Owner | Fix Type | WB build | Verdict |
|-------|------|-----------|----------|----------|---------|
| LE-01 | Purchase event count parity | Klints (automated) | Automated writeback (approved) | Approve live (`event_ingest` PURCHASE) | **Correct — Approve live** |
| LE-02 | Purchase value parity | Klints (automated) | Automated writeback (approved) | Approve live (`event_correct`) | **Correct — Approve live** |
| LE-03 | Order ID (externalId) presence on events | External integrator | Integration build | None | **Correct — not a writeback** |
| LE-04 | Duplicate purchase events per order | External integrator | Integration build + Manual (guided) | Mapping **disabled**; FE preview blocked | **Correct — disabled** |
| LE-05 | Order-level event gap list | Klints (automated) | Automated writeback (approved) | Approve live (`event_ingest` PURCHASE gaps) | **Correct — Approve live** |
| LE-08 | Stale open carts | External integrator | Integration build + Automated writeback (approved) | None | **Not built — not Klints execute** (owner External; do not Approve without product flip) |
| LE-09 | Returns and cancellations reflected | Klints (automated) | Integration build + Automated writeback (approved) | Approve live (`event_ingest` RETURN/CANCELLATION) | **Correct — Approve live** |
| LE-11 | Event ingestion lag and loss | External integrator | Integration build | None | **Correct — not a writeback** |
| LE-13 | Event volume drift monitor | Klints (automated) | Configuration | None | **Correct — not a writeback** |

### 03 Product & Transaction

| Check | Name | Fix Owner | Fix Type | WB build | Verdict |
|-------|------|-----------|----------|----------|---------|
| PT-01 | Event product IDs resolve in catalog | External integrator | Integration build + Automated writeback (approved) | None | **Not built — not Klints execute** |
| PT-03 | Catalog completeness vs commerce | Klints (automated) | Integration build + Automated writeback (approved) | Preview live (`product_upsert` T7; WB-20); execute after PRODUCT.IMPORT Loom | **Correct — Preview; Approve after Loom** |
| PT-04 | Net vs gross transaction truth per contact | Klints (automated) | Automated writeback (approved) | Approve live (`detail_set` `klints_net_ltv`) | **Correct — Approve live** |
| PT-14 | Order value distribution anomaly | Klints (automated) | Configuration | None | **Correct — not a writeback** |

### 04 Segment & Property

| Check | Name | Fix Owner | Fix Type | WB build | Verdict |
|-------|------|-----------|----------|----------|---------|
| SP-03 | Standard detail schema consistency | Klints (automated) | Automated writeback (approved) | Approve live (`detail_set` format contract; WB-19) | **Correct — Approve live** |
| SP-07 | klints_ namespace availability | Klints (automated) | Automated writeback (approved) | Approve live (rename collisions) | **Correct — Approve live** |
| SP-08 | Segment population sanity | CRM manager | Manual (guided) | None | **Correct — not a writeback** |
| SP-12 | Property freshness on decision fields | Data lead | Manual (guided) | None | **Correct — not a writeback** |

### 05 Channel & Consent

| Check | Name | Fix Owner | Fix Type | WB build | Verdict |
|-------|------|-----------|----------|----------|---------|
| CC-01 | Email opt-in parity | Data lead | Integration build + Automated writeback (approved) | Plan-only Preview/Download (WB-17A); no FE Approve; no allowlist seed | **Correct — plan-only** (Phase B forceOpt only after Loom + product) |
| CC-02 | SMS / mobile consent parity | Data lead | Integration build + Automated writeback (approved) | Plan-only Preview/Download (WB-18A); no FE Approve; no allowlist seed; unreachable Download-only | **Correct — plan-only** (Phase B forcePhoneOpt only after Loom + product) |
| CC-03 | Consent provenance completeness | Data lead | Automated writeback (approved) + Manual (guided) | Approve live (`detail_set` evidence) | **Borderline — review** (Excel owner Data lead; sandbox exception landed early — keep Settings-gated; do not use as template for CC-01/02) |
| CC-05 | Opt-out propagation loop | External integrator | Integration build | None | **Correct — not a writeback** |
| CC-12 | Consent age and re-permission surface | Data lead | Manual (guided) | None | **Correct — not a writeback** |

### 06 Measurement

| Check | Name | Fix Owner | Fix Type | WB build | Verdict |
|-------|------|-----------|----------|----------|---------|
| ME-02 | Workflow revenue attribution wiring | CRM manager | Manual (guided) | None | **Correct — not a writeback** |
| ME-08 | Baseline computability for impact claims | Klints (automated) | Configuration | None | **Correct — not a writeback** |
| ME-09 | Email deliverability posture snapshot | Data lead | Manual (guided) | None | **Correct — not a writeback** |

### 07 Business Reality

| Check | Name | Fix Owner | Fix Type | WB build | Verdict |
|-------|------|-----------|----------|----------|---------|
| BR-01 | Margin data coverage per product | Data lead | Automated writeback (approved) | None | **Not built — not Klints execute** (Excel AW but Data lead owner) |
| BR-02 | Inventory freshness SLA | External integrator | Integration build | None | **Correct — not a writeback** |
| BR-12 | ERP sync freshness heartbeat | Klints (automated) | Configuration | None | **Correct — not a writeback** |

---

## 4. Prior writeback audit (built vs Excel)

| Check | Owner | Built as | Match? | Action if wrong |
|-------|-------|----------|--------|-----------------|
| CI-01 | Klints | Approve | Yes | Keep |
| CI-05 | Klints | Approve (missing_link_key only) | Yes | Keep; dangling/reused stay evidence → CI-03 |
| LE-01 | Klints | Approve | Yes | Keep |
| LE-02 | Klints | Approve | Yes | Keep |
| LE-05 | Klints | Approve | Yes | Keep |
| LE-09 | Klints | Approve | Yes | Keep |
| PT-04 | Klints | Approve | Yes | Keep |
| SP-07 | Klints | Approve | Yes | Keep |
| CI-03 | CRM manager | Plan-only | Yes | Do **not** FE-allowlist Approve until product + Loom; Phase B ≠ email-delete |
| LE-04 | External integrator | Disabled | Yes | Keep disabled |
| CC-03 | Data lead | Approve | **Borderline** | Documented exception; Settings + allowlist only; no copy-paste for CC-01/02 |
| SP-03 | Klints | Approve (format contract + detail_set; WB-19) | Yes | Keep; semantic dupes stay Download-only |
| PT-03 | Klints | Preview (product_upsert T7; WB-20) | Yes | Keep Preview; FE allowlist only after PRODUCT.IMPORT Loom |
| SP-01 | *(not in 42)* | Disabled stub | N/A | Stay out of MVP1 allowlist |
| WB-SHOP-01 | *(not catalogue)* | Sandbox Approve | N/A | Sandbox proof only |

**Summary:** No MVP1-42 Klints writeback is mis-owned. The only ownership mismatch among live Approves is **CC-03** (Data lead). **CI-03**, **CC-01**, and **CC-02** are correctly plan-only. **PT-03** Preview is correctly gated pending Loom.

---

## 5. Roll-up counts (MVP1 42)

| Bucket | Count | Checks |
|--------|------:|--------|
| Correct — Approve live | 9 | CI-01, CI-05, LE-01, LE-02, LE-05, LE-09, PT-04, SP-07, SP-03 |
| Correct — Preview (Approve after Loom) | 1 | **PT-03** |
| Borderline — Approve (Data lead) | 1 | CC-03 |
| Correct — plan-only | 3 | CI-03, CC-01, CC-02 |
| Correct — disabled | 1 | LE-04 |
| Not built — Klints candidate | 0 | — |
| Not built — not Klints execute | 4 | BR-01, PT-01, LE-08 (+ any future External/Data AW) |
| Correct — not a writeback | 23 | All FD-* except none; drift Manual/Config/External remaining |

*(LE-08 and PT-01 counted in “not Klints execute”; remaining Manual/Config/Integration = “not a writeback”.)*

---

## 6. Consider-first list (remaining writebacks)

**Already shipped (do not re-open):** CI-01 → SP-07 → LE-09 → PT-04 → LE-05 → LE-02 → CI-05 → CI-03 Phase A (plan) → CC-01 Phase A (plan) → CC-02 Phase A (plan) → SP-03 Approve → **PT-03 Preview (WB-20)** · plus borderline CC-03 Approve · LE-04 disabled.

**Dependency spine (why this order):**

```
Identity:     CI-01 → CI-05 → CI-03 (reused / dups)
Events:       (identity linked) → LE-05 / LE-01 → LE-02
Returns/net:  LE-09 → PT-04   (needs SP-07 PASS for klints_ keys)
Consent:      SP-07 clean → CC-03 evidence → CC-01 / CC-02 policy + reconcile
Catalog:      PT-01 ID convention (External) → PT-03 product_upsert (Klints; Preview live — Approve after Loom)
Schema:       SP-07 clean → SP-03 detail normalisation (Klints)
ERP margin:   ERP feed → BR-01 (Data lead; late)
```

### Build / design priority (after WB-20 Preview)

| # | Check | Sev | Owner | Excel Fix Type | Deps already met? | What to build first | Klints Approve? |
|--:|-------|-----|-------|----------------|-------------------|---------------------|-----------------|
| **1** | **PT-03 Loom → Approve** | High | **Klints** | Integration + AW | Preview ✓; PRODUCT.IMPORT still **DISCOVERY_REQUIRED** | Sandbox Loom upsert (+ archive); then CONFIRMED_* + FE allowlist + `WritebackAllowedCheck` | **Yes** after capability CONFIRMED_LIVE / LIMITED |
| **2** | **CI-03 Phase B** | High | CRM manager | AW | Phase A ✓ | Optional SAFE `batchDelete` CONTACT_ID only after Loom; never email-delete | Approve only with product + allowlist |
| **3** | **BR-01** | High | Data lead | AW | Needs ERP | T10 margin feed → catalog; flag margin-unknown | **No** (Data lead) |
| **—** | SP-03 semantic Phase B | High | Klints | AW | MVP ✓ | Optional semantic key consolidation rename map | After product rules |
| **—** | CC-01 / CC-02 Phase B | Critical | Data lead | Integration + AW | Phase A ✓ | Optional forceOpt* / forcePhoneOpt* after Loom + product override | **No** until product overrides owner |
| **—** | PT-01 | High | External | Integration + AW | — | Integrator ID convention + optional catalog upsert | **No** (External) |
| **—** | LE-08 | Medium | External | Integration + AW | — | CART update / close stale (integration) | **No** (External) |

### If you only pick one next engineering PR

| Track | Pick | Why |
|-------|------|-----|
| **Klints executable** | **PT-03 Loom** | Preview already live; unblocks Approve after PRODUCT.IMPORT CONFIRMED_* |
| **Defer** | CI-03B until delete Loom; CC-01/02 Phase B until product; BR-01 / PT-01 / LE-08 forever-as-Klints-Approve |

### Operator Fix order (runtime, when multiple FAIL)

Prefer: **SP-07 → CI-01 → CI-05 → CI-03 (plan) → LE-05 → LE-01 → LE-02 → LE-09 → PT-04 → CC-03 → CC-01/02 (plan) → SP-03 → PT-03**.

---

## 7. Quick gate checklist (before coding)

- [ ] Check ID is in **CHECK_MASTER_42** (not SP-01 / ad-hoc)
- [ ] `CheckMaster.fix_owner` read from DB / Excel (not mapping JSON alone)
- [ ] If owner ≠ Klints (automated) → plan-only / Download / disabled unless product override logged
- [ ] Sheet row + registry + FE allowlist + `WritebackAllowedCheck` migration stay in sync
- [ ] Update **this doc** §3–4 when a new writeback ships or an exception is approved

---

## 8. Related

- `docs/dcs_scoring/CHECK_MASTER_42.md`
- `docs/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv`
- `docs/writebacks/WRITEBACK_SURFACE_MATRIX.md`
- `dataruns/dcs/fix_ownership.py` · `dataruns/writebacks/pipeline.py`
- FE `src/lib/writebacks.ts` → `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS`
- PRDs WB-01 … WB-16 under `docs/writebacks/`
