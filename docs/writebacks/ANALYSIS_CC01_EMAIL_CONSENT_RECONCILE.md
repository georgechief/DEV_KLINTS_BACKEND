# Deep analysis — CC-01 Email opt-in parity (PRD-ready)

**Status:** Analysis complete — shipping PRD drafted: [`PRD_WB_17_CC01_EMAIL_CONSENT_RECONCILE.md`](./PRD_WB_17_CC01_EMAIL_CONSENT_RECONCILE.md).  
**Date:** 2026-09-25  
**Scope:** MVP1-42 check **CC-01** only. CC-02 is a twin (same T8); call out shared design but do not implement SMS in the same Phase A unless product insists.  
**Authority:** Excel `v1.4.1` sheet **02** row CC-01 · `CHECK_MASTER_42` · live `evaluate_cc_01` / `consent_join` · ownership doc §6.

---

## 0. One-line verdict

CC-01 **scoring is complete**; the writeback is **not**. Excel wants **T8 Consent reconciliation** with a **Data lead**-owned policy (opt-out everywhere immediately; opt-in only with proven record → CC-03). First PRD must ship **policy + Preview/Download (+ optional plan-only)** — **not** a silent Klints Approve like CC-03.

---

## 1. Excel catalogue (exact — SoT)

| Column | CC-01 value |
|--------|-------------|
| Check ID | **CC-01** |
| Dimension | 05 Channel & Consent |
| Name | Email opt-in parity |
| Entity | Consent |
| Systems | Shopify vs Manago |
| Check Type | Consent compliance |
| Detection Logic | Per linked identity: Shopify `email_marketing_consent` (state, opt_in_level, consent_updated_at) vs Manago email marketing status; **four-quadrant** matrix (in/in, in/out, out/in, out/out) with counts |
| Manago Surface | email marketing consent + reason/source |
| Shopify Surface | `customers.email_marketing_consent` |
| Inconsistency | Consent states disagree between commerce and marketing platform |
| Root Causes | **RC-07, RC-05, RC-01** |
| Business Impact | `in Shopify / out Manago` = **lost reach**; `out Shopify / in Manago` = **compliance exposure** (GDPR) |
| Affected Workflows | Every email send |
| Severity | **Critical** |
| DCS Weight | High (numeric **4** on sheet 09) |
| Suggested Fix | Define consent **source-of-truth and precedence per direction** (opt-outs propagate everywhere immediately; opt-ins propagate only with **provable consent record** — agent-set opt-ins do **not** qualify, see **CC-03**); **approved reconciliation batch** via upsert with **`forceOptIn` / `forceOptOut`** used strictly per policy; **live bi-directional sync thereafter** |
| Fix Type | **Integration build + Automated writeback (approved)** |
| Fix Owner | **Data lead** |
| Rollback Note | Consent writes logged with prior state + source; **opt-out propagation is deliberately not rolled back** |
| Cadence | Initial + Recurring |
| MVP1 Fix Blueprint | Y |
| Fix Template | **T8 Consent reconciliation** |
| Build Priority | **P0** |
| Sheet 09 | RULE_BASED · SCORED · MVP1-A · seq 23 |

**Twin (do not conflate in PRD ship checklist):**

| | CC-02 | CC-05 |
|--|-------|-------|
| Channel | SMS / `optedOutPhone` | Opt-out **propagation loop** (callbacks/webhooks) |
| Owner | Data lead | **External integrator** |
| Template | T8 | T8 named, but Fix Type = **Integration build only** |
| This PRD | Optional Phase C or separate PRD | **Out of scope** |

---

## 2. What already works (DCS)

### 2.1 Pipeline

| Layer | Location | Status |
|-------|----------|--------|
| Join | `dataruns/dcs/consent_join.py` → `build_consent_snapshot()` | **Live** |
| Score | `dataruns/dcs/executors/consent.py` → `evaluate_cc_01` | **Live** |
| Registry | `CONSENT_EXECUTORS` | Registered |
| Tests | `dataruns/tests/test_consent_pt04_checks.py` | PASS + FAIL + provenance |
| FE Approve | `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` | **CC-01 absent** (correct) |
| Mapping / registry | — | **Absent** |
| `consent_reconcile` adapter | OpKind declared; **not** in `_IMPLEMENTED_OP_KINDS` | **Gap** |

### 2.2 Field contract (scoring)

| Side | Raw field | Boolean “in” |
|------|-----------|----------------|
| Shopify | `email_marketing_consent.state` | `subscribed` → in; `not_subscribed` / `unsubscribed` / `redacted` / `pending` → out; empty → unknown |
| Shopify (evidence) | `opt_in_level`, `consent_updated_at` | Surfaced; not quadrant axes |
| Manago | `optedOut` | `False` → in; `True` → out; missing → unknown |

**Link spine:** Manago `externalId` ↔ Shopify `customers.id`; fallback normalised email (`link_kind`).

**Quadrants (Excel):**

| Quadrant | Shopify | Manago | Product meaning | Excel / code name |
|----------|---------|--------|-----------------|-------------------|
| `in_in` | in | in | OK | aligned |
| `in_out` | in | out | Lost email reach | `lost_reach_email` |
| `out_in` | out | in | **Compliance exposure** | `compliance_exposure_email` |
| `out_out` | out | out | OK | aligned |

### 2.3 PASS / FAIL (no WARN)

| Condition | Status |
|-----------|--------|
| Connectors / consent fields missing | UNKNOWN / NOT_CONNECTED |
| `linked_identities == 0` | UNKNOWN |
| `compliance_exposure_email > 0` | **FAIL** (RC-07) — checked **first** |
| any other `email_mismatches > 0` | **FAIL** (RC-07) |
| else | PASS |

Provenance mismatches (≤50): `side` = quadrant, emails/ids, Shopify opt_in_level + consent_updated_at, Manago modified_on.

**PRD implication:** Writeback transform must consume these mismatch sides (`out_in` / `in_out`), not invent new evidence shapes — same pattern as LE-05 `shopify_only` / CI-05 `missing_link_key`.

---

## 3. What Excel fix actually requires (decompose Suggested Fix)

Excel Suggested Fix is **three products**, not one Approve button:

| Part | Meaning | Owner / track | In first PRD? |
|------|---------|---------------|---------------|
| **A. Policy** | Per-direction SoT + precedence | **Data lead** (config / Fix honesty UI) | **Yes — mandatory** |
| **B. Approved batch reconcile** | Upsert with `forceOptIn` / `forceOptOut` per policy | Catalogue AW · T8 | **Phase-gated** (see §5) |
| **C. Live bi-directional sync** | Ongoing Shopify↔Manago consent sync | **Integration build** (overlaps CC-05) | **No** — separate / External |

If the PRD tries to ship A+B+C in one PR, it will slip. **Lock Phase A = A (+ Preview of B); Phase B = B execute after product + Loom.**

---

## 4. Policy matrix (must be locked in PRD §2)

Excel rule of thumb:

1. **Opt-outs propagate everywhere immediately**  
2. **Opt-ins propagate only with provable consent** (CC-03 / Shopify evidence)  
3. **Agent-set Manago opt-ins do not qualify** as proof  

### 4.1 Recommended default policy (propose; product must sign)

| Quadrant | Dangerous? | Default reconcile direction | Guard |
|----------|------------|-----------------------------|-------|
| **`out_in`** | **Yes — compliance** | Prefer **force Manago OUT** (`forceOptOut`) to match Shopify out | Always allowed under “opt-out wins”; log prior state |
| **`in_out`** | Lost reach (not illegal) | Prefer **force Manago IN** (`forceOptIn`) **only if** provenance OK **or** Shopify holds evidence (CC-03 path / `opt_in_level` + `consent_updated_at`) | **Block** if unevidenced / weak agent-like (`provenance_weak`) → Download / re-permission, not forceOptIn |
| `in_in` / `out_out` | — | No write | — |

**Do not** invent a Shopify→Manago “always commerce wins” for opt-**in** without CC-03. That would violate Excel.

**Shopify write direction:** Excel Part C + CC-05 talk about updating Shopify consent. **Phase A/B of CC-01 should default Manago-only** (`forceOpt*` on `api/contact/upsert` — already allowlisted in `manago_transport._UPSERT_ROOT_KEYS`). Shopify Admin consent update = later / CC-05 / product flip (capability today is `SHOPIFY.CUSTOMER.UPDATE` for note proof only — **not** marketing consent API).

### 4.2 Relation to CC-03 (already shipped)

| CC-03 | CC-01 |
|-------|-------|
| Writes `klints_consent_evidence=shopify_verified` via `detail_set` | Uses that evidence as **gate** for `forceOptIn` on `in_out` |
| Fix Owner Data lead but **Approve live** (borderline exception) | **Must not copy** — ownership doc forbids using CC-03 as template |
| `requires_consent_namespace_clean: true` | Same if any `klints_` keys written; **forceOpt\* alone may set `requires_consent_namespace_clean: false`** (native root flags) — **decide in PRD** |
| Does **not** flip `optedOut` | CC-01 **does** flip marketing state |

Shared snapshot already computes `shopify_evidence_backfill_candidates` / `manago_only_unevidenced_optins` — PRD should wire transform to those cohorts.

---

## 5. Phased PRD shape (recommended)

### Phase A — Preview / Download / policy honesty (ship first)

| Deliverable | Notes |
|-------------|-------|
| Mapping `CC-01.consent_reconcile.v1.json` | `enabled: true`, **`execute_mode: plan_only`** *or* sheet `write_possible_today=preview_only` |
| Transform | Build plan rows from `email_out_in` / `email_in_out` samples (+ uncapped Download) with proposed action: `FORCE_OPT_OUT` / `FORCE_OPT_IN` / `SKIP_UNEVIDENCED` |
| FE | Preview + Download; **no** FE Approve allowlist |
| `WritebackAllowedCheck` | **Do not seed** (or seed execute denied) |
| Fix Owner gate | Data lead → preview_only_owner when sandbox execute off; **do not rely on it alone when sandbox ON** (CI-03 lesson) |
| Policy copy | Fix UI / disclosure: SoT table from §4.1 |
| Possible sheet row | T8; blocker `plan_only_data_lead` / `policy_required` |
| Tests + verify script | Plan rows only; execute → deny reason |

**Acceptance Phase A:** Operator can see every mismatch class, proposed action, and Download CSV; Approve execute returns honest deny (`cc01_plan_only` / equivalent).

### Phase B — Approved batch execute (only after product + Loom)

| Deliverable | Notes |
|-------------|-------|
| Implement `consent_reconcile` **or** map ops to `contact_upsert` with `forceOptIn`/`forceOptOut` | Prefer **reuse `contact_upsert`** + capability `RESTV2.CONTACT.UPSERT` (**CONFIRMED_LIVE**) unless product wants a distinct op_kind adapter |
| FE allowlist + `WritebackAllowedCheck` | After Loom |
| Guards | `out_in` → forceOptOut; `in_out` → forceOptIn only if evidence gate passes |
| Rollback | Log prior `optedOut`; **Excel: opt-out propagation deliberately not rolled back** — PRD must disclose irreversible opt-out; opt-in rollback optional/best-effort |
| Batch | Excel “approved batch”; ceiling align UPSERT (≤1000) + sample honesty like CI-05 |
| Settings | Still gated by Allow writebacks |

**Do not** flip CheckMaster `fix_owner` away from Data lead without a logged product decision.

### Phase C — Live bi-directional sync

Out of WB-17. Belongs with **CC-05** / integrator webhooks. Mention only as “thereafter” so Suggested Fix is not silently dropped.

---

## 6. Technical design notes for the PRD author

### 6.1 Op kind choice

| Option | Pros | Cons |
|--------|------|------|
| **A. New `consent_reconcile` adapter** | Matches WB-01 T8 naming | Not implemented; more surface; capability invent |
| **B. `contact_upsert` + forceOpt\*** (**preferred**) | Transport already accepts keys; UPSERT CONFIRMED_LIVE; same as Excel “upsert with forceOptIn/forceOptOut” | OpKind name ≠ T8 label — document mapping `template_id: T8` on upsert ops |

**Recommendation:** Phase B ops = `op_kind: contact_upsert` with fields `forceOptOut` / `forceOptIn`, `template_id: "T8"`. Keep `consent_reconcile` as alias later if needed.

### 6.2 Capability

No new capability required for Manago-only Phase B (`RESTV2.CONTACT.UPSERT`).  
Shopify marketing consent write = **DISCOVERY_REQUIRED** — out of Phase A/B.

### 6.3 Evidence → plan row fields (minimum)

| Field | Source |
|-------|--------|
| `side` | `out_in` \| `in_out` |
| `person.email` | sample |
| `manago_contact_id` / `shopify_customer_id` | sample |
| `proposed_action` | `FORCE_OPT_OUT` \| `FORCE_OPT_IN` \| `SKIP_UNEVIDENCED` |
| `evidence_gate` | `provenance_ok` \| `klints_consent_evidence` \| `shopify_opt_in_level+ts` \| `fail` |
| `shopify_email_opt_in_level` / `consent_updated_at` | sample |
| `prior_optedOut` | Manago raw / DB contact |

### 6.4 Dependencies (runtime order)

```
SP-07 PASS (if klints_ details used)
→ CI-01 / CI-05 link quality (linked_identities > 0)
→ CC-03 evidence backfill for Shopify-holds-evidence cohort
→ CC-01 reconcile (this)
→ CC-02 (twin; later)
→ CC-05 loop (External; not this PRD)
```

Pilot: UC-06B, UC-17, UC-21 hard-gate on CC-01 PASS (Studio / pilots).

### 6.5 Explicit non-goals

- Silent Approve for Data lead without product override  
- Copying CC-03 allowlist pattern  
- Shopify consent Admin API  
- CC-02 SMS in Phase A (unless product expands scope)  
- CC-05 webhook loop  
- Changing CC-01 FAIL bands / adding WARN  
- Email-delete / contact merge  
- Treating `pending` Shopify as opted-in (code correctly treats as out)

### 6.6 Risks / open questions (PRD §16 must answer)

| # | Question | Suggested default |
|---|----------|-------------------|
| 1 | Is commerce (Shopify) SoT for opt-**out** always? | **Yes** (Excel opt-out everywhere) |
| 2 | Is commerce SoT for opt-**in**? | **Only with proven record** |
| 3 | Can Phase B run under sandbox Data lead owner? | Only with FE allowlist + product sign-off (CC-03-class exception) |
| 4 | Implement op as upsert or consent_reconcile? | **Upsert + forceOpt\*** |
| 5 | Uncapped Download vs sample-50 Preview? | Preview 50; Download full mismatch list (CI-03 pattern) |
| 6 | Require SP-07 for forceOpt-only? | **false** if no `klints_` keys; true if stamping evidence |
| 7 | Roll back forceOptOut? | **No** (Excel) |
| 8 | Same PR as CC-02? | **No** — twin PRD after CC-01 Phase A |

---

## 7. Gap checklist (what the PRD must schedule)

| Gap | Today | PRD phase |
|-----|-------|-----------|
| Policy / SoT UI or disclosure | Missing | A |
| Mapping + registry CC-01 | Missing | A |
| Transform plan rows | Missing | A |
| Possible sheet + SURFACE | Missing | A |
| FE preview honesty (no Approve) | Missing | A |
| `execute_mode=plan_only` deny | Missing | A |
| forceOpt execute path | Transport keys exist; unused | B |
| FE allowlist + WritebackAllowedCheck | Absent | B |
| Shopify consent writer | No capability | C / CC-05 |
| Live bi-di sync | Missing | C / integrator |

---

## 8. Suggested PRD skeleton (paste into WB-17)

Mirror `PRD_WB_15` / `PRD_WB_16` structure:

1. Status / Owner track (**Data lead** — Sahil BE · FE Preview) / Depends on WB-16A + CC-03 + SP-07  
2. Cursor agent brief (Phase A only in first paste)  
3. Why / Before-After  
4. Excel § column map (copy §1 table)  
5. Locked decisions (§4 policy + §5 phases)  
6. Mapping JSON draft + disclosure  
7. Transform / pipeline plan_only  
8. FE / sheet / SURFACE  
9. Phase B execute (gated appendix)  
10. Tests + verify script  
11. Acceptance  
12. Out of scope (§6.5)  
13. Open questions (§6.6)

**Proposed filename:** `docs/writebacks/PRD_WB_17_CC01_EMAIL_CONSENT_RECONCILE.md`

---

## 9. Related code & docs

| Path | Why |
|------|-----|
| `dataruns/dcs/consent_join.py` | Quadrants, link, provenance cohorts |
| `dataruns/dcs/executors/consent.py` | `evaluate_cc_01` |
| `dataruns/writebacks/adapters/manago_transport.py` | `forceOptIn` / `forceOptOut` root keys |
| `dataruns/writebacks/mappings/CC-03.consent_provenance.v1.json` | Evidence stamp pattern (not Approve template) |
| `docs/writebacks/WRITEBACK_FIX_OWNERSHIP_MVP1_42.md` §6 | Priority #1 |
| `docs/writebacks/PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md` | T8 → `consent_reconcile` |
| `docs/writebacks/PRD_WB_16_CI03_CONTACT_MERGE_WRITEBACK.md` | Plan-only / Data-lead-adjacent gate lessons |

---

## 10. Bottom line for drafting

| Do | Don't |
|----|-------|
| Lead with **Critical + Data lead + T8 + policy** | Lead with “Approve like CI-01” |
| Phase A = plan/Preview; Phase B = forceOpt batch | Ship bidirectional Shopify sync in WB-17 |
| Gate `forceOptIn` on CC-03 / Shopify evidence | forceOptIn unevidenced Manago-only opt-ins |
| Prefer Manago upsert forceOpt\* | Invent consent Admin API |
| Disclose irreversible opt-out | Promise full rollback |
| Keep CC-02 / CC-05 out of Phase A | Bundle SMS + webhooks “while we’re here” |
