# Deep analysis — CC-02 SMS / mobile consent parity (PRD-ready)

**Status:** Analysis complete — shipping PRD drafted: [`PRD_WB_18_CC02_SMS_CONSENT_RECONCILE.md`](./PRD_WB_18_CC02_SMS_CONSENT_RECONCILE.md).  
**Date:** 2026-09-25  
**Scope:** MVP1-42 check **CC-02** only. Twin of CC-01 (same T8); do **not** re-open CC-01 Phase A or ship CC-05.  
**Authority:** Excel `v1.4.1` sheet **02** row CC-02 (extract 2026-09-25) · `CHECK_MASTER_42` · live `evaluate_cc_02` / `consent_join` · ownership doc §6 #2 · WB-17 lessons.

---

## 0. One-line verdict

CC-02 **scoring is complete**; the writeback is **not**. Excel wants the **same SoT policy as CC-01**, mobile-specific, plus **joint CI-09 phone-validity surfacing**. First PRD ships **policy + Preview/Download (plan-only)** — **not** CC-03-style silent Klints Approve. Phase B `forcePhoneOpt*` is optional / product-gated (same as CC-01 Phase B).

---

## 1. Excel catalogue (exact — SoT)

Extracted from `docs/dcs_scoring/Klints_Spec_InitialDataConsistencyCheck_v1.4.1_20260718.xlsx` sheet **02 Check Catalogue** row **CC-02** (headers row 5).

| Column | CC-02 value |
|--------|-------------|
| Check ID | **CC-02** |
| Dimension | 05 Channel & Consent |
| Name | SMS / mobile consent parity |
| Entity | Consent |
| Systems | Shopify vs Manago |
| Check Type | Consent compliance |
| Detection Logic | Shopify `sms_marketing_consent` vs Manago mobile marketing status on linked identities; **same four-quadrant treatment as CC-01** |
| Manago Surface | mobile marketing consent |
| Shopify Surface | `customers.sms_marketing_consent` |
| Inconsistency | Mobile channel consent diverges |
| Root Causes | **RC-07, RC-05** *(no RC-01 — differs from CC-01)* |
| Business Impact | SMS is high-cost, high-regulation (per-message fees + telecom rules); sending to a revoked consent is both a **fine risk** and **money burned** |
| Affected Workflows | SMS flows, WhatsApp |
| Severity | **Critical** |
| DCS Weight | High (numeric **4** on sheet 09) |
| Suggested Fix | **Same source-of-truth policy as CC-01, mobile-specific**; reconcile with approval; **phone validity (CI-09) checked jointly** so consented-but-unreachable is also surfaced |
| Fix Type | **Integration build + Automated writeback (approved)** |
| Fix Owner | **Data lead** |
| Rollback Note | **Same posture as CC-01** (opt-out propagation deliberately not rolled back) |
| Cadence | Initial + Recurring |
| MVP1 Fix Blueprint | Y |
| Fix Template | **T8 Consent reconciliation** |
| Build Priority | **P0** |
| Sheet 09 | RULE_BASED · SCORED · MVP1-A · seq 24 |

**Twin / do-not-conflate:**

| | CC-01 (shipped Phase A) | CC-05 |
|--|-------------------------|-------|
| Channel | Email / `optedOut` / `forceOpt*` | Opt-out **propagation loop** (callbacks/webhooks) |
| Owner | Data lead · plan-only WB-17A | **External integrator** |
| This PRD | Pattern parent | **Out of scope** |

---

## 2. Ownership matrix (lock)

From [`WRITEBACK_FIX_OWNERSHIP_MVP1_42.md`](./WRITEBACK_FIX_OWNERSHIP_MVP1_42.md):

| Fact | Value |
|------|--------|
| §3 row | CC-02 · Data lead · Integration + AW · **None** → **Not built — not Klints execute** |
| §6 priority | **#2** after CC-01 · same pattern · **Klints Approve? No** until product overrides |
| Rule §1.5 | Data lead ≠ silent Approve; **do not copy CC-03** |
| Phase B | Optional — same gate as CC-01 (product override). **Not required** for ownership-correct Phase A |

---

## 3. What already works (DCS)

### 3.1 Pipeline

| Layer | Location | Status |
|-------|----------|--------|
| Join | `consent_join.build_consent_snapshot` | **Live** — SMS quadrants + samples + reachability |
| Score | `evaluate_cc_02` | **Live** — FAIL on compliance / mismatches; PASS may still surface unreachable |
| Registry | `CONSENT_EXECUTORS["CC-02"]` | Registered |
| Tests | `EvaluateCc02Tests` | PASS / FAIL / unreachable surface |
| FE Approve | `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` | **CC-02 absent** (correct) |
| Mapping / registry writeback | — | **Absent** |
| Transport | `forcePhoneOptIn` / `forcePhoneOptOut` in `_UPSERT_ROOT_KEYS` | **Ready** for Phase B |

### 3.2 Field contract (scoring)

| Side | Raw field | Boolean “in” |
|------|-----------|----------------|
| Shopify | `sms_marketing_consent.state` | Same helper as email: `subscribed` → in; else out/unknown |
| Shopify (evidence) | `opt_in_level`, `consent_updated_at` on SMS consent object | Surfaced on linked row as `shopify_sms_opt_in_level` / `shopify_sms_consent_updated_at` |
| Manago | `optedOutPhone` | `False` → in; `True` → out; missing → unknown |

**Link spine:** same as CC-01 (`externalId` ↔ Shopify id; email fallback).

**Quadrants:** identical names (`in_in` / `in_out` / `out_in` / `out_out`) on `sms_quadrant`.

| Quadrant | Shopify SMS | Manago phone | Product meaning | Snapshot counter |
|----------|-------------|--------------|-----------------|------------------|
| `out_in` | out | in | **Compliance / fine risk** | `compliance_exposure_sms` |
| `in_out` | in | out | Lost SMS reach (cost opportunity) | `lost_reach_sms` |

### 3.3 PASS / FAIL (no WARN)

| Condition | Status |
|-----------|--------|
| Connectors / consent fields missing | UNKNOWN / NOT_CONNECTED |
| `linked_identities == 0` | UNKNOWN |
| `compliance_exposure_sms > 0` | **FAIL** (RC-07) — first |
| any other `sms_mismatches > 0` | **FAIL** (RC-07) |
| else | **PASS** (may still mention consented-but-unreachable) |

### 3.4 CI-09-lite (Excel “checked jointly”)

| Piece | Behaviour |
|-------|-----------|
| Snapshot | `sms_phone_reachability.consented_but_unreachable` + sample `consented_unreachable_sms` |
| Score | **Does not FAIL** the check by itself (PASS can still surface rows) |
| Writeback | **Not a forcePhoneOpt target** — Download / Data lead hygiene only |

---

## 4. Gaps vs Excel Suggested Fix

Excel Suggested Fix = three products (same split as CC-01) **plus** phone reachability honesty:

| Part | Meaning | In first PRD? |
|------|---------|---------------|
| **A. Policy** | Same SoT as CC-01, mobile-specific | **Yes** |
| **B. Approved reconcile** | Upsert `forcePhoneOptIn` / `forcePhoneOptOut` | Phase A = plan only; Phase B gated |
| **C. Live bi-di sync** | Ongoing sync | **No** (CC-05 / integrator) |
| **D. Phone validity surface** | Consented-but-unreachable | **Yes** — Download / provenance; **no** mutate |

### 4.1 Code gaps for Phase A writeback

| Gap | Today | Need |
|-----|-------|------|
| `_sample` SMS rows | Stamps **email** `optedOut` even on SMS samples; omits `optedOutPhone` / SMS in / SMS opt_in_level+ts | **Channel-conditional** enrich; no CC-01 regression |
| `evaluate_cc_02` provenance | Thin: side, email, ids, channel only | Full gate fields + `proposed_action`; `side=sms_quadrant` |
| Uncapped Download SoT | Only `consent_mismatch_email` | Add **`consent_mismatch_sms`** + snapshot persist |
| Mapping / registry | None | Hand-authored plan_only twin of CC-01 |
| `_build_payload_and_state` | CC-01 branch only | **CC-02 → `_cc02_plan_payload`** or bare upsert drops plan fields |
| Gate helper | `_cc01_evidence_gate_pass` is email-fielded | Dedicated SMS gate (sms opt_in_level+ts) |
| SKIP ready bug class | Fixed for CC-01 only | Extend skip to CC-02 / `FORCE_PHONE_*` |
| Pipeline | `effective_max` / truncation / plan_reasons only list CC-01 | Add CC-02 everywhere |
| Possible sheet | No CC-02 | **Both** CSV paths |
| FE honesty | No CC-02 case | Mirror CC-01 |

### 4.2 Policy matrix (lock — mobile)

Same as CC-01 with phone flags:

| Quadrant | Default reconcile | Guard |
|----------|-------------------|-------|
| **`out_in`** | `FORCE_PHONE_OPT_OUT` → Manago `forcePhoneOptOut` | Always (opt-out wins) |
| **`in_out`** | `FORCE_PHONE_OPT_IN` only if evidence gate passes | Else `SKIP_UNEVIDENCED` |
| `consented_but_unreachable` | **No write** | Download / re-permission / fix phone |
| `in_in` / `out_out` | No write | — |

**Evidence gate (any one unlocks FORCE_PHONE_OPT_IN):**

1. `provenance_ok is True` (Manago `consents[]`)  
2. `klints_consent_evidence == "shopify_verified"` (CC-03 stamp — transform-time)  
3. Shopify **SMS** `opt_in_level` non-empty **and** SMS `consent_updated_at` present  

**Manago-only Phase A/B** — do not write Shopify `sms_marketing_consent`.  
**Overview T8** names `forceOptIn/Out` for the template family — CC-02 execute keys are **`forcePhoneOpt*`**.

### 4.3 PRD gap-close (2026-09-25 recheck)

Hostile pass against Excel + WB-17 lessons + live pipeline/transform closed:

- Broken gate ref §2 → explicit SMS gate list  
- Missing `_build_payload_and_state` wire  
- Email/SMS field mix risk (`side`, gate, `_sample` prior)  
- Pipeline truncation / effective_max / plan_reasons CC-02 adds  
- Both possible-sheet CSV paths  
- Flat `phone` mapping field  
- §16 typo → §14  
- CC-01 regression tests required  

---

## 5. Differences from CC-01 (do not copy blindly)

| Topic | CC-01 | CC-02 |
|-------|-------|-------|
| Manago flag | `optedOut` | `optedOutPhone` |
| Phase B root keys | `forceOptIn` / `forceOptOut` | `forcePhoneOptIn` / `forcePhoneOptOut` |
| Plan actions | `FORCE_OPT_*` | `FORCE_PHONE_OPT_*` |
| Shopify object | `email_marketing_consent` | `sms_marketing_consent` |
| Root causes | RC-07, RC-05, **RC-01** | RC-07, RC-05 only |
| Extra surface | — | **CI-09-lite unreachable** (Download only) |
| Pilot gate | UC-06B, UC-17, UC-21 | **UC-06B** (and related SMS pilots) |
| Blocked reason | `cc01_plan_only` | `cc02_plan_only` |

Reuse WB-17 patterns: two `const` ops (no `oneOf`), `execute_mode=plan_only`, no FE allowlist, no `WritebackAllowedCheck`, `SKIP_UNEVIDENCED` → intent `skipped` (not Ready), uncapped Download list, hand-authored mapping, `requires_consent_namespace_clean=false`.

---

## 6. Phased shape

### Phase A — must-ship

Policy disclosure + plan Preview/Download + unreachable honesty in Download; execute → `cc02_plan_only`.

### Phase B — optional / product-gated

Manago upsert with `forcePhoneOpt*`; FE allowlist + allowlist migration; opt-out not rolled back. **Not required** for ownership “Correct — plan-only.”

### Phase C — out

Live bi-di sync / CC-05.

---

## 7. Risks

| Risk | Mitigation |
|------|------------|
| Copy CC-03 Approve | Ownership lock + plan_only |
| Bundle email + SMS | Separate WB-18; CC-01 already shipped |
| Treat unreachable as forcePhoneOptIn | Explicit non-op side |
| Claim uncapped Download while sample-only | `consent_mismatch_sms` + snapshot persist |
| Use `oneOf` in mapping | Two const ops |
| SKIP counts as Ready | Explicit skip like WB-17 C-1 fix |
| Reuse email gate / email prior on SMS rows | Channel-conditional `_sample` + SMS gate helper |
| Fall through to bare `contact_upsert` payload | Dedicated `_cc02_plan_payload` branch |
| Update only docs CSV | Both possible-sheet paths |

---

## 8. Recommended next engineering step

Implement [`PRD_WB_18_CC02_SMS_CONSENT_RECONCILE.md`](./PRD_WB_18_CC02_SMS_CONSENT_RECONCILE.md) **Phase A only**. Do not start Phase B unless product overrides Data lead.
