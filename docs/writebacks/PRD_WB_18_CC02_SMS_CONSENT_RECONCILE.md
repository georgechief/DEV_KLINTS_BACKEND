# PRD-WB-18 — CC-02 SMS / mobile consent reconcile (plan + gated forcePhoneOpt)

**Status:** **Phase A complete 2026-09-25** · Phase B optional (not required for ownership Correct — plan-only) · P0 M2 Catalogue · Sahil  

**Owner track:** Sahil — **BE primary · FE Preview/Download + policy honesty** (pack Fix Owner = **Data lead** — not Klints automated)  
**Surfaces:** Fix `/fix` Preview · FE-12 Download · Settings Allow writebacks · registry / mapping · possible sheet · Activity/audit · **DCS SMS consent mismatches** · Manago `contact_upsert` **`forcePhoneOptIn` / `forcePhoneOptOut`** (Phase B optional)  
**Milestone:** M2 Activation & Blueprint — Channel & Consent  
**Depends on:** WB-17 Phase A (CC-01 pattern live) · WB-03…WB-16 · FE-08/09/12 · live `evaluate_cc_02` + `consent_join` · CC-03 evidence stamp (gate only)  
**PRD path:** `docs/writebacks/`  
**Analysis SoT:** [`ANALYSIS_CC02_SMS_CONSENT_RECONCILE.md`](./ANALYSIS_CC02_SMS_CONSENT_RECONCILE.md)  
**Ownership SoT:** [`WRITEBACK_FIX_OWNERSHIP_MVP1_42.md`](./WRITEBACK_FIX_OWNERSHIP_MVP1_42.md) §6 #2  

**Pack SoT:**  
- `Klints_Spec_InitialDataConsistencyCheck_v1.4.1` sheet **02 Check Catalogue** row **CC-02** (exact extract §3.1)  
- sheet **01 Overview** — **T8 Consent reconciliation** covers **CC-01 / CC-02**  
- sheet **09 MVP1 Check Scope** · SCORED · MVP1-A · weight 4 · Critical  
- `docs/dcs_scoring/CHECK_MASTER_42.md` row CC-02 — *SMS / mobile consent parity* · RC-07, RC-05 · **Critical**  
- WB-01 §1b.2 — T8 → implement via `contact_upsert` + **`forcePhoneOpt*`** (not a new adapter)  
- WB-01 §10.1 — Fix Owner ≠ Klints → preview-only unless product override  
- Ownership §6 #2 — **same pattern as CC-01**; **Klints Approve? No** until product overrides  
- **Do not** copy CC-03’s Data-lead Approve exception  

**Out of scope:**  
- **CC-01** changes (already Phase A)  
- **CC-05** opt-out propagation / webhooks (External integrator)  
- **Live bi-directional sync** (Excel “thereafter” / integrator)  
- Shopify Admin **SMS marketing consent** writer  
- Changing CC-02 PASS/FAIL bands or making unreachable alone FAIL  
- Silent Approve for Data lead without logged product override  
- Inventing Manago APIs beyond upsert `forcePhoneOpt*`  
- Phase B forcePhoneOpt execute (optional; **not required** for ownership Correct — plan-only)  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-18 — CC-02 SMS / mobile consent reconcile (plan + gated forcePhoneOpt).

Read:
- docs/writebacks/PRD_WB_18_CC02_SMS_CONSENT_RECONCILE.md (this file)
- docs/writebacks/ANALYSIS_CC02_SMS_CONSENT_RECONCILE.md
- docs/writebacks/WRITEBACK_FIX_OWNERSHIP_MVP1_42.md (§6 #2)
- docs/writebacks/PRD_WB_17_CC01_EMAIL_CONSENT_RECONCILE.md (pattern parent — mirror Phase A wires)
- dataruns/dcs/executors/consent.py (evaluate_cc_02)
- dataruns/dcs/consent_join.py (sms quadrants, mismatch_samples, reachability)
- dataruns/writebacks/adapters/manago_transport.py (forcePhoneOptIn/Out already in _UPSERT_ROOT_KEYS)
- FE: src/lib/writebacks.ts (do NOT add CC-02 to WRITEBACK_APPROVE_EXECUTABLE in Phase A)

Ship Phase A only unless product explicitly opens Phase B.

CRITICAL (carry WB-17 lessons):
- Fix Owner = Data lead — Phase A MUST use execute_mode=plan_only + no FE allowlist + no WritebackAllowedCheck seed
- pipeline plan_only reason: add CC-02→cc02_plan_only alongside CI-03/CC-01 (do not hardcode a single reason)
- pipeline effective_max + truncation probe set: add CC-02 → CC_SAMPLE (today only CC-01 is wired)
- enrich _sample channel-conditionally: SMS rows get optedOutPhone / SMS gate fields — do NOT leave email prior_optedOut as the phone prior
- side MUST come from sms_quadrant only — never email_quadrant (same string values out_in/in_out)
- add consent_mismatch_sms uncapped + persist on scoring snapshot (§3.4)
- transform: _cc02_evidence_rows + _cc02_plan_payload + _build_payload_and_state branch when check_id=CC-02 (plain contact_upsert DROPS plan fields — same bug class as WB-17)
- _cc02_evidence_gate_pass MUST read shopify_sms_opt_in_level + shopify_sms_consent_updated_at (do not reuse email-only gate helper blindly)
- SKIP_UNEVIDENCED → status=skipped for CC-02 (extend the CC-01 skip branch or key off proposed_action)
- mapping: TWO const ops (out_in / in_out) — NO oneOf; hand-authored; requires_consent_namespace_clean=false
- mapping phone field: use flat key "phone": { "path": "person.phone" } (not "person.phone" as field name)
- consented_but_unreachable: Download only — NEVER forcePhoneOptIn / never match plan ops
- Update BOTH possible sheets: docs/writebacks/ AND dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv
- Do NOT copy CC-03 Approve; Do NOT write Shopify SMS consent; Do NOT ship CC-05; Do NOT regress CC-01

PHASE A (MVP1 must-ship):
1. consent_join._sample: channel-conditional SMS enrich (§3.3); keep email enrich for channel=email.
2. consent_mismatch_sms = linked where sms_quadrant in {out_in,in_out}; persist on scoring snapshot (mirror email).
3. evaluate_cc_02: uncapped provenance from consent_mismatch_sms (fallback samples); proposed_action / evidence_gate; evidence value counts; unreachable samples as non-write sides.
4. Mapping CC-02.consent_reconcile.v1.json — plan_only; T8; batch; irreversible; two const ops; phone flat field.
5. transform: collect_evidence_rows CC-02 → _cc02_evidence_rows; _build_payload_and_state → _cc02_plan_payload; SKIP→skipped.
6. pipeline/messages: cc02_plan_only; effective_max; truncation + empty-intents SMS copy.
7. Possible sheet (both CSVs) + SURFACE + FE honesty CC-02 case. Registry enabled; no allowlist seed.
8. Confirm CheckMaster.fix_owner for CC-02 is "Data lead".
9. Tests + scripts/verify_wb18_cc02_sms_consent_reconcile.py Phase A.

PHASE B (optional — only after product sign-off §14):
10. forcePhoneOptOut / forcePhoneOptIn on upsert root payload; skip unevidenced; opt-out not rolled back; FE allowlist + WritebackAllowedCheck migration.
```

---

## 1. Goal / user story

### 1.0 Problem → outcome

| Today | After Phase A | After Phase B (optional) |
|-------|---------------|---------------------------|
| CC-02 FAILs on SMS quadrant mismatches; Fix has Download evidence only / no reconcile plan | Fix Preview shows **FORCE_PHONE_OPT_OUT / FORCE_PHONE_OPT_IN / SKIP_UNEVIDENCED** + unreachable Download rows + Data lead disclosure | Approved Manago `forcePhoneOpt*` batch per policy |
| UC-06B gated on CC-02 PASS | Operators can act from Download / plan | Re-score → PASS when matrix clean |

### 1.1 Excel Suggested Fix = three products (+ phone surface)

| Part | Product | Phase |
|------|---------|-------|
| **A. Policy** | Same SoT as CC-01, mobile-specific | **Phase A** |
| **B. Approved batch** | Upsert `forcePhoneOptIn` / `forcePhoneOptOut` | Plan in A; execute **B** (gated) |
| **C. Live bi-di sync** | Ongoing sync | **Out** (CC-05) |
| **D. Phone validity** | Consented-but-unreachable surfaced | **Phase A** Download / provenance — **no mutate** |

### 1.2 Decision locks

| # | Lock | Value |
|---|------|-------|
| 1 | Catalogue starts with same SoT as CC-01 | **Yes** — Phase A ships policy + plan |
| 2 | Fix Owner | **Data lead** — plan-only Phase A |
| 3 | Do not copy CC-03 Approve | **Yes** |
| 4 | Op implementation | **`contact_upsert` + `forcePhoneOpt*`**; `template_id: "T8"` |
| 5 | Match rule | **Two const ops** (`out_in` / `in_out` from **sms_quadrant**) — **no oneOf** |
| 6 | `requires_consent_namespace_clean` | **`false`** for forcePhoneOpt-only |
| 7 | Preview sample | **`CC_SAMPLE` = 50** |
| 8 | Download | Uncapped `consent_mismatch_sms` |
| 9 | Unevidenced `in_out` | `SKIP_UNEVIDENCED` — intent **skipped**, never Ready |
| 10 | Unreachable phone | Surface only — **never** forcePhoneOptIn |
| 11 | Rollback | Same as CC-01: **forcePhoneOptOut not rolled back** |
| 12 | Shopify SMS writer | **Out** |
| 13 | Phase B | **Optional** — not required for ownership Correct — plan-only |
| 14 | Same PR as CC-01 / CC-05 | **No** |
| 15 | Side source | **`sms_quadrant` only** (values collide with email — do not mix) |
| 16 | Gate fields | **SMS** opt_in_level + ts — not email |
| 17 | `_sample` | Channel-conditional; no CC-01 regression |

---

## 2. Policy (mobile)

Excel: opt-outs everywhere immediately; opt-ins only with provable record (see CC-03); agent-set opt-ins do not qualify. Mobile-specific + CI-09 joint surface.

Sheet **01 Overview** T8 text names `forceOptIn/Out` for CC-01/CC-02/CC-05. **Lock for CC-02:** Manago root keys are **`forcePhoneOptIn` / `forcePhoneOptOut`** (already in `manago_transport._UPSERT_ROOT_KEYS`). Do not send email `forceOpt*` for SMS mismatches.

| Condition | `proposed_action` | `evidence_gate` |
|-----------|-------------------|-----------------|
| `side == out_in` (from **sms_quadrant**) | `FORCE_PHONE_OPT_OUT` | `opt_out_wins` |
| `side == in_out` and gate pass | `FORCE_PHONE_OPT_IN` | see gate list below |
| `side == in_out` and gate fail | `SKIP_UNEVIDENCED` | `fail` |
| `side == consented_but_unreachable` | *(none — not a plan op)* | — |

**Evidence-gate pass** (any one unlocks `FORCE_PHONE_OPT_IN`):

1. `provenance_ok is True` (Manago `consents[]`)  
2. `klints_consent_evidence == "shopify_verified"` (CC-03 stamp — transform-time)  
3. Shopify **SMS** `opt_in_level` non-empty **and** SMS `consent_updated_at` present (`shopify_sms_opt_in_level` + `shopify_sms_consent_updated_at`)

If `provenance_weak` and neither (2) nor (3) → **fail** (SKIP).

**Do not** use `shopify_email_opt_in_level` / email `consent_updated_at` as the SMS gate.

---

## 3. Catalogue + live scoring

### 3.1 Catalogue (sheet 02) + CHECK_MASTER

Exact Excel CC-02 row (v1.4.1). Verified via workbook extract 2026-09-25.

| Column | Value |
|--------|--------|
| Check ID | **CC-02** |
| DCS Dimension | 05 Channel & Consent |
| Check Name | SMS / mobile consent parity |
| Entity | Consent |
| Systems Compared | Shopify vs Manago |
| Check Type | Consent compliance |
| Detection Logic | Shopify `sms_marketing_consent` vs Manago mobile marketing status on linked identities; same four-quadrant treatment as CC-01 |
| Manago Surface | mobile marketing consent |
| Shopify Surface | `customers.sms_marketing_consent` |
| Inconsistency Type | Mobile channel consent diverges |
| Root Causes | RC-07, RC-05 |
| Business Impact | SMS high-cost / high-regulation; sending to revoked consent = fine risk + money burned |
| Affected Workflows | SMS flows, WhatsApp |
| Severity | **Critical** |
| DCS Weight | High (numeric **4**) |
| Suggested Fix | Same source-of-truth policy as CC-01, mobile-specific; reconcile with approval; phone validity (CI-09) checked jointly so consented-but-unreachable is also surfaced |
| Fix Type | Integration build + Automated writeback (approved) |
| Fix Owner | **Data lead** |
| Rollback Note | Same posture as CC-01 (opt-out propagation deliberately not rolled back) |
| Cadence | Initial + Recurring |
| MVP1 Fix Blueprint | Y |
| Fix Template | **T8 Consent reconciliation** |
| Build Priority | **P0** |

CHECK_MASTER_42: RULE_BASED · SCORED · MVP1-A · weight 4 · Critical · RC-07, RC-05.

### 3.2 Live scoring (do not change bands)

| Piece | Location |
|-------|----------|
| Join | `consent_join.build_consent_snapshot` |
| Score | `evaluate_cc_02` |
| FAIL if | `compliance_exposure_sms > 0` **or** `sms_mismatches > 0` |
| UNKNOWN if | no linked identities / missing inputs |
| Sample cap | `CC_SAMPLE = 50` |
| Unreachable | Surfaced on PASS/FAIL detail; **not** a FAIL driver alone |

Quadrant axes:

| Side | Field | In |
|------|-------|-----|
| Shopify | `sms_marketing_consent.state` | `subscribed` only (`pending` = out) |
| Manago | `optedOutPhone` | `False` = in |

### 3.3 Evidence enrich (Phase A required)

Today `evaluate_cc_02` provenance is **thin** (side, email, ids, channel). `_sample` already has some phone fields but **omits** `optedOutPhone` / SMS in flags / SMS opt_in_level+ts needed for plan + gate. It currently stamps **email** `optedOut` / `prior_optedOut` even on SMS sample rows — **wrong prior for phone ops**.

**Lock — `_sample` channel-conditional:**

| When `channel=="email"` | When `channel=="sms"` |
|-------------------------|------------------------|
| Keep WB-17 email enrich (`optedOut`, `prior_optedOut`, email_in, email opt_in_level/ts) | Add `optedOutPhone`, `prior_optedOutPhone`, `manago_sms_in`, `shopify_sms_in`, `shopify_sms_opt_in_level`, `shopify_sms_consent_updated_at` |
| Do not require SMS phone prior | Do **not** use email `prior_optedOut` as phone prior |

Shared on both: `provenance_*`, `link_kind`, `person.phone`, `phone_valid`, ids, both quadrant fields (informational).

**Must enrich evaluate provenance (plan rows):**

| Field | Source |
|-------|--------|
| `side` | **`sms_quadrant` only** (never `email_quadrant`) |
| `person.email` / `person.phone` / `phone_valid` | linked |
| ids / `link_kind` / `channel=sms` | linked |
| `provenance_ok` / `provenance_weak` / `provenance_note` | linked |
| `optedOutPhone` / `prior_optedOutPhone` | Manago |
| `manago_sms_in` / `shopify_sms_in` | linked |
| `shopify_sms_opt_in_level` / `shopify_sms_consent_updated_at` | linked |
| `proposed_action` / `evidence_gate` | score-time and/or transform (transform wins after stamp lookup) |
| `klints_consent_evidence` | **transform-time** via `find_manago_contact` + `contact_detail_value` |

Evidence aggregate `value` (honesty, mirror WB-17):

| Key | Meaning |
|-----|---------|
| `consent_mismatch_sms_count` | `len(provenance plan mismatches)` / full list |
| `preview_sample_cap` | `CC_SAMPLE` |

Mismatch sample keys (do not rename):

| Key | Plan |
|-----|------|
| `mismatch_samples.sms_out_in` | → `FORCE_PHONE_OPT_OUT` |
| `mismatch_samples.sms_in_out` | → gate → `FORCE_PHONE_OPT_IN` or `SKIP_UNEVIDENCED` |
| `mismatch_samples.consented_unreachable_sms` | Download only — **exclude from plan ops** |

**Entity key:** `person.email` (Manago upsert identity), same as CC-01. If email missing/invalid → intent `error` via existing `email_format` / `entity_key_required` guards (honest; do not invent phone-as-entity_key in Phase A).

**Tests must fail if** SMS provenance plan rows lack `optedOutPhone` / `provenance_ok` after this PR.  
**Tests must fail if** `_sample(..., channel="sms")` still only exposes email `prior_optedOut` without `prior_optedOutPhone`.  
**Tests must fail if** `_sample(..., channel="email")` regresses WB-17 fields.

### 3.4 Download honesty

| Path | Behaviour |
|------|-----------|
| Preview / plan intents | Cap `CC_SAMPLE` via pipeline `effective_max` |
| FE-12 Download | Full `consent_mismatch_sms` with `proposed_action` / `evidence_gate` + unreachable samples |
| Hard cap today | `consent_rows[:500]` insufficient |

**Lock:** add **`consent_mismatch_sms`** unsliced (prefer) and persist on scoring snapshot (mirror `consent_mismatch_email`). Do not claim uncapped while only reading samples or `consent_rows[:500]`.

---

## 4. Mapping (Phase A)

**File:** `dataruns/writebacks/mappings/CC-02.consent_reconcile.v1.json`  
**Hand-authored.** Do **not** use `stub_factory` (T8→detail_set and CC-*→`requires_consent_namespace_clean=true` are both wrong).

```json
{
  "schema_version": "1.0.0",
  "check_id": "CC-02",
  "template_id": "T8",
  "title": "SMS consent reconcile plan (forcePhoneOpt policy)",
  "enabled": true,
  "approval_tier": "batch",
  "execute_mode": "plan_only",
  "requires_consent_namespace_clean": false,
  "irreversible": true,
  "fix_owner": "Data lead",
  "operator_disclosure": "CC-02 proposes an SMS/mobile consent reconcile plan from the Shopify↔Manago four-quadrant matrix (same SoT policy as CC-01, mobile-specific). Catalogue Fix Owner is Data lead — not Klints automated. Policy: opt-outs propagate everywhere immediately (out_in → forcePhoneOptOut on Manago); opt-ins propagate only with a provable consent record — agent-set Manago opt-ins do not qualify (see CC-03). Consented-but-unreachable phones are Download-only (CI-09-lite) — never forcePhoneOptIn. Phase A: Preview + Download only. Phase B (optional, after product sign-off): Manago contact upsert with forcePhoneOptOut / forcePhoneOptIn strictly per policy. Opt-out writes are deliberately not rolled back. Does not write Shopify SMS marketing consent and does not replace live bi-directional sync (CC-05 / integration). Re-run DCS after Manago state changes.",
  "rollback": {
    "strategy": "none",
    "note": "Excel: same posture as CC-01 — opt-out propagation deliberately not rolled back."
  },
  "operations": [
    {
      "operation_id": "manago.contact_upsert.force_phone_opt_out_plan",
      "op_kind": "contact_upsert",
      "target": "manago",
      "namespace": "native",
      "capability_id": "RESTV2.CONTACT.UPSERT",
      "entity_type": "contact",
      "from_evidence": {
        "match": { "path": "side", "const": "out_in" },
        "entity_key": { "path": "person.email" },
        "fields": {
          "contact_id": { "path": "manago_contact_id" },
          "proposed_action": { "path": "proposed_action" },
          "evidence_gate": { "path": "evidence_gate" },
          "prior_optedOutPhone": { "path": "prior_optedOutPhone" },
          "shopify_customer_id": { "path": "shopify_customer_id" },
          "phone": { "path": "person.phone" }
        }
      },
      "guards": ["entity_key_required", "email_format", "plan_only"]
    },
    {
      "operation_id": "manago.contact_upsert.force_phone_opt_in_plan",
      "op_kind": "contact_upsert",
      "target": "manago",
      "namespace": "native",
      "capability_id": "RESTV2.CONTACT.UPSERT",
      "entity_type": "contact",
      "from_evidence": {
        "match": { "path": "side", "const": "in_out" },
        "entity_key": { "path": "person.email" },
        "fields": {
          "contact_id": { "path": "manago_contact_id" },
          "proposed_action": { "path": "proposed_action" },
          "evidence_gate": { "path": "evidence_gate" },
          "prior_optedOutPhone": { "path": "prior_optedOutPhone" },
          "shopify_customer_id": { "path": "shopify_customer_id" },
          "phone": { "path": "person.phone" }
        }
      },
      "guards": ["entity_key_required", "email_format", "plan_only"]
    }
  ]
}
```

**Registry:**

```json
"CC-02": {
  "file": "CC-02.consent_reconcile.v1.json",
  "enabled": true,
  "template_id": "T8"
}
```

`SKIP_UNEVIDENCED` rows appear in Preview/Download; intents must be **`status=skipped`**, `error_reason=skip_unevidenced` — never Ready / execute-eligible.

---

## 5. Transform + pipeline

### 5.0 Critical wires

| Wire | Action |
|------|--------|
| `consent_join._sample` | **Channel-conditional** SMS enrich §3.3; no CC-01 email regression |
| `consent_mismatch_sms` + `snapshot.py` persist | Uncapped Download/rebuild SoT |
| `evaluate_cc_02` provenance | `side=sms_quadrant`; full gate fields + proposed_action; unreachable separate; evidence value counts |
| `pipeline` plan_only map | Add `"CC-02": "cc02_plan_only"` (keep CI-03 / CC-01) |
| `pipeline` `effective_max` | `elif CC-02: CC_SAMPLE` |
| `pipeline` truncation probe set | Include `"CC-02"` with SMS-specific note |
| `pipeline` empty intents | CC-02 honesty when no out_in/in_out plan rows |
| `messages.py` | `cc02_plan_only` |
| `transform.collect_evidence_rows` | `elif CC-02: _cc02_evidence_rows(...)` |
| `_cc02_evidence_rows` / `_cc02_filter_plan_rows` | Filter `side in {out_in,in_out}` from **sms** rows only; live rebuild via pins + `consent_mismatch_sms`; stamp enrich; set proposed_action via **SMS** gate helper |
| `_cc02_evidence_gate_pass` | SMS fields only (§2) |
| `_build_payload_and_state` | **New branch:** `check_id=CC-02` + `contact_upsert` → `_cc02_plan_payload` (do **not** fall through to bare `_contact_upsert_payload`) |
| `_cc02_plan_payload` | `{mode:"plan", side, proposed_action, evidence_gate, prior_optedOutPhone, email, phone, contactId, shopify_customer_id, …}` — no Manago mutate |
| Intent status | `SKIP_UNEVIDENCED` → `skipped`/`skip_unevidenced` for CC-02; FORCE_* → ready (`before` ≠ `after`) |
| Rollback on error intents | Forward mapping `rollback.strategy=none` |
| `manago.dry_run` | Plan intents (`payload.mode=plan`) already skip mutate — keep |

### 5.1 Denial copy

```text
cc02_plan_only:
  CC-02 is plan-only: Preview and Download show the SMS consent reconcile plan.
  Klints does not auto-apply forcePhoneOpt in Phase A. Data lead applies policy
  in Manago (or Phase B Approve after product sign-off).
```

Truncation note (example):  
`SMS consent plan sample capped at {N} mismatches. Download for full estate; re-score after Data lead clears remaining FAIL.`

Empty note (example):  
`No SMS consent mismatch rows in this sample. CC-02 proposes a reconcile plan only — forcePhoneOpt is not auto-applied.`

### 5.2 Phase B execute (appendix — gated / optional)

| Action | Upsert root fields |
|--------|-------------------|
| `FORCE_PHONE_OPT_OUT` | `forcePhoneOptOut: true` + identity email/contactId |
| `FORCE_PHONE_OPT_IN` | `forcePhoneOptIn: true` — only if gate ≠ fail |
| `SKIP_UNEVIDENCED` | Never execute |

Transport already allowlists both keys. Opt-out not rolled back. Log `prior_optedOutPhone` for audit.

---

## 6. Sheet / SURFACE / FE

### 6.1 Possible sheet

Update **both** runtime and docs copies:

- `dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv` (SoT for `GET …/possible/`)  
- `docs/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv` (keep in sync)

| Column | Value |
|--------|--------|
| check_id | CC-02 |
| check_name | SMS / mobile consent parity |
| pack_fix_type | Integration build + Automated writeback (approved) |
| pack_fix_owner | Data lead |
| pack_suggested_fix_summary | Propose SMS consent reconcile plan (forcePhoneOpt per policy); not auto-applied Phase A; Data lead |
| platform | manago |
| op_kind | contact_upsert |
| entity | contact |
| field_or_key | forcePhoneOptIn\|forcePhoneOptOut |
| namespace | native |
| creates_new / updates_existing | n/a / n/a |
| write_possible_today | preview_only |
| rollback_possible_today | no |
| mapping_file | CC-02.consent_reconcile.v1.json |
| registry_enabled | true |
| blocker | plan_only_data_lead |
| evidence_note | four-quadrant SMS; out_in compliance first; in_out needs evidence; unreachable Download-only; T8 via upsert forcePhoneOpt*; opt-out not rolled back |
| last_verified | 2026-09-25 |

### 6.2 SURFACE

Add row: SMS consent reconcile — Phase A plan (WB-18); Data lead; Phase B forcePhoneOpt optional after product; unreachable Download-only; opt-out not rolled back.

### 6.3 FE

| Item | Phase A |
|------|---------|
| `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` | **Do not add CC-02** |
| `writebackNonExecutableHonesty` | CC-02 case (mirror CC-01; mention FORCE_PHONE_* + SKIP + unreachable) |
| Friendly evidence | `out_in` / `in_out` / `consented_but_unreachable` readable with action/gate |

---

## 7. Allowlist / Settings / fix_owner

| Gate | Phase A | Phase B |
|------|---------|---------|
| Settings Allow writebacks | N/A for mutate (plan_only) | Required |
| `WritebackAllowedCheck` CC-02 | **Do not seed** | Migration only after product sign-off |
| FE allowlist | Off | On after sign-off |
| CheckMaster `fix_owner=Data lead` | Keep | Keep unless product flips |

---

## 8. Tests + verify

| Item | Path |
|------|------|
| Django tests | `dataruns/tests/test_writeback_wb18.py` |
| Verify script | `scripts/verify_wb18_cc02_sms_consent_reconcile.py` |

**Phase A must assert:**

- Registry CC-02 enabled; mapping `execute_mode=plan_only`; two const ops; no oneOf  
- Provenance / samples carry `optedOutPhone` + SMS gate fields (not email prior alone)  
- `_cc02_evidence_rows` sets FORCE_PHONE_OPT_OUT / FORCE_PHONE_OPT_IN / SKIP correctly  
- `_cc02_evidence_gate_pass` ignores email opt_in_level  
- SKIP intents `status=skipped` for CC-02  
- Unreachable never produces Ready forcePhoneOptIn  
- Execute → `blocked_reason=cc02_plan_only` under sandbox ON  
- `effective_max` == `CC_SAMPLE` when `max_rows=None`  
- Truncation probe includes CC-02  
- FE allowlist excludes CC-02; honesty case present  
- No `WritebackAllowedCheck` seed  
- `consent_mismatch_sms` uncapped path covered by test  
- Mapping `requires_consent_namespace_clean=false`; phone field is flat `phone`  
- CC-01 `_sample` / evaluate still carries email priors (no regression)  

---

## 9. Files to touch (Phase A)

| Area | Files |
|------|--------|
| DCS | `consent_join.py`, `consent.py` (`evaluate_cc_02`), `snapshot.py` |
| Mapping / registry | `CC-02.consent_reconcile.v1.json`, `registry.json` |
| Pipeline / messages / transform | `pipeline.py`, `messages.py`, `transform.py` |
| Sheet / SURFACE | **Both** `WRITEBACK_POSSIBLE_NOT_SHEET.csv` paths + `WRITEBACK_SURFACE_MATRIX.md` |
| Ownership doc | Update §3 CC-02 row + §5 buckets after ship |
| FE | `writebacks.ts` honesty (+ optional `dcs.ts` friendly sides) |
| Tests / verify | `test_writeback_wb18.py`, `verify_wb18_cc02_sms_consent_reconcile.py` |
| Docs | this PRD · ANALYSIS · README |

---

## 10. Acceptance

### Phase A

- [x] Excel §3.1 language in mapping disclosure  
- [x] CheckMaster `fix_owner=Data lead` confirmed  
- [x] `_sample` + provenance SMS gate fields  
- [x] `consent_mismatch_sms` + snapshot persist  
- [x] Two const ops; hand-authored; `requires_consent_namespace_clean=false`  
- [x] Preview plan rows with correct `FORCE_PHONE_*` / `SKIP`  
- [x] SKIP → skipped (not Ready)  
- [x] Unreachable Download-only  
- [x] Execute denied `cc02_plan_only`  
- [x] FE allowlist excludes CC-02; honesty present  
- [x] Possible sheet `preview_only` + SURFACE  
- [x] verify_wb18 Phase A green  
- [x] `_sample` SMS enrich + **no CC-01 email regression**  
- [x] `side` from `sms_quadrant` only; gate uses **SMS** opt_in_level+ts  
- [x] `_build_payload_and_state` uses `_cc02_plan_payload` (not bare upsert)  
- [x] Both possible-sheet CSVs updated  
- [x] No CC-05 / Shopify SMS writer / CC-01 regression  

### Phase B (optional)

- [ ] Product sign-off logged §14  
- [ ] forcePhoneOpt* on upsert root payload  
- [ ] Unevidenced skipped; opt-out not rolled back  
- [ ] Allowlist + FE allowlist  

---

## 11. Non-goals

CC-01 reopen · CC-05 · Shopify SMS consent API · live bi-di sync · Phase A Approve · making unreachable alone FAIL · `oneOf` · `consent_reconcile` new adapter · CC-03 Approve copy.

---

## 12. Risks

| Risk | Mitigation |
|------|------------|
| Copy CC-03 | Ownership + plan_only |
| Unreachable → forcePhoneOptIn | Explicit non-op |
| Sample masquerading as full estate | `consent_mismatch_sms` |
| SKIP Ready | Explicit skip status |
| Mixing email FORCE_OPT_* names | Use `FORCE_PHONE_OPT_*` |
| Irreversible opt-out surprise | `irreversible=true` + disclosure |
| Email/SMS field mix (`side`, gate, prior) | `sms_quadrant` + SMS gate + channel-conditional `_sample` |
| Bare upsert drops plan fields | `_build_payload_and_state` CC-02 branch |
| Docs CSV only | Both possible-sheet paths |

---

## 13. Parents / next

| | |
|--|--|
| Parents | WB-17 · ownership §6 #2 · consent_join |
| MVP1 · P0 order | **#8** after CC-01 Phase A |
| Next code after Phase A | **SP-03** (Klints Approve) **or** product-gated CC-01/02 Phase B |
| Unblocks | UC-06B SMS honesty; Data lead Fix workflow |

---

## 14. Open questions (product)

| # | Question | PRD default |
|---|----------|-------------|
| 1 | Same SoT as CC-01 for SMS opt-out/in? | **Yes** |
| 2 | Phase B Approve while owner stays Data lead? | **Only with explicit sign-off** — not required for MVP1 |
| 3 | Upsert forcePhoneOpt\* vs new adapter? | **Upsert forcePhoneOpt\*** |
| 4 | Unreachable alone FAIL? | **No** (Excel: surface jointly) |
| 5 | Roll back forcePhoneOptOut? | **No** |

**Sign-off log (Phase B only):**

| Date | Who | Decision |
|------|-----|----------|
| | | |

---

## 15. Related

- [`ANALYSIS_CC02_SMS_CONSENT_RECONCILE.md`](./ANALYSIS_CC02_SMS_CONSENT_RECONCILE.md)  
- [`PRD_WB_17_CC01_EMAIL_CONSENT_RECONCILE.md`](./PRD_WB_17_CC01_EMAIL_CONSENT_RECONCILE.md)  
- [`WRITEBACK_FIX_OWNERSHIP_MVP1_42.md`](./WRITEBACK_FIX_OWNERSHIP_MVP1_42.md)  
- `dataruns/dcs/consent_join.py` · `dataruns/dcs/executors/consent.py`  
- `dataruns/writebacks/adapters/manago_transport.py` (`forcePhoneOptIn` / `forcePhoneOptOut`)  
- `dataruns/writebacks/mappings/CC-01.consent_reconcile.v1.json` (pattern)  
- `klints_frontend/src/lib/writebacks.ts`
