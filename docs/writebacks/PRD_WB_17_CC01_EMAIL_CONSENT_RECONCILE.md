# PRD-WB-17 — CC-01 email consent reconcile (plan + gated forceOpt)

**Status:** **Phase A shipping** — P0 M2 Catalogue · Sahil · gap-closed 2026-09-25  

**Owner track:** Sahil — **BE primary · FE Preview/Download + policy honesty** (pack Fix Owner = **Data lead** — not Klints automated)  
**Surfaces:** Fix `/fix` Preview · FE-12 Download · Settings Allow writebacks · registry / mapping · possible sheet · Activity/audit · **DCS consent mismatches** · Manago `contact_upsert` **`forceOptIn` / `forceOptOut`** (Phase B)  
**Milestone:** M2 Activation & Blueprint — Channel & Consent  
**Depends on:** WB-03…WB-16 Phase A · FE-08/09/12 · live `evaluate_cc_01` + `consent_join` · CC-03 Approve live (evidence stamp) · SP-07 (namespace; only if `klints_` keys written)  
**PRD path:** `docs/writebacks/`  
**Analysis SoT:** [`ANALYSIS_CC01_EMAIL_CONSENT_RECONCILE.md`](./ANALYSIS_CC01_EMAIL_CONSENT_RECONCILE.md)  
**Ownership SoT:** [`WRITEBACK_FIX_OWNERSHIP_MVP1_42.md`](./WRITEBACK_FIX_OWNERSHIP_MVP1_42.md) §6 #1  

**Pack SoT:**  
- `Klints_Spec_InitialDataConsistencyCheck_v1.4.1` sheet **02 Check Catalogue** row **CC-01** (headers row 5 — full column map §3.1)  
- sheet **01 Overview** — **T8 Consent reconciliation** covers **CC-01 / CC-02** (and names CC-05; CC-05 is Integration-only — out of this PRD)  
- sheet **09 MVP1 Check Scope** (Channel & Consent · SCORED · MVP1-A · weight 4 · Critical)  
- `docs/dcs_scoring/CHECK_MASTER_42.md` row CC-01 — *Email opt-in parity* · RC-07, RC-05, RC-01 · **Critical**  
- WB-01 §1b.2 — T8 → `consent_reconcile` (this PR **implements T8 via `contact_upsert` + forceOpt\*** — §2 #7)  
- WB-01 §10.1 — Fix Owner ≠ Klints → **preview-only execute** unless product override  
- **MVP1 · P0 next list #7** — after CI-03 Phase A → **CC-01** → CC-02…  
- WB-02 §3.2 — CC-01 today on “Approve OFF until built” — this PR **does not** enable silent Approve in Phase A  
- **Do not** copy CC-03’s Data-lead Approve exception as the Phase A template (`WRITEBACK_FIX_OWNERSHIP_MVP1_42.md`)  

**Out of scope:**  
- **CC-02** SMS / `forcePhoneOpt*` (twin PRD after Phase A)  
- **CC-05** opt-out propagation loop / webhooks / callbacks (External integrator)  
- **Live bi-directional sync** (Excel Suggested Fix “thereafter” — Phase C / integrator)  
- Shopify Admin **marketing consent** writer (no capability today; `SHOPIFY.CUSTOMER.UPDATE` is note-proof only)  
- Changing CC-01 PASS/FAIL bands or adding WARN  
- Silent Approve for Data lead without logged product override  
- Contact merge / email-delete / inventing Manago consent APIs beyond upsert forceOpt\*  
- Handoff / Studio / QA / CAP product work beyond Fix honesty  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-17 — CC-01 email consent reconcile (plan + gated forceOpt).

Read:
- docs/writebacks/PRD_WB_17_CC01_EMAIL_CONSENT_RECONCILE.md (this file)
- docs/writebacks/ANALYSIS_CC01_EMAIL_CONSENT_RECONCILE.md
- docs/writebacks/WRITEBACK_FIX_OWNERSHIP_MVP1_42.md (§6 #1)
- docs/writebacks/PRD_WB_16_CI03_CONTACT_MERGE_WRITEBACK.md (plan_only / pipeline / FE honesty pattern)
- docs/writebacks/PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md (T8)
- dataruns/dcs/executors/consent.py (evaluate_cc_01)
- dataruns/dcs/consent_join.py (quadrants, mismatch_samples, provenance)
- dataruns/writebacks/adapters/manago_transport.py (forceOptIn/forceOptOut already in _UPSERT_ROOT_KEYS)
- dataruns/writebacks/mappings/CC-03.consent_provenance.v1.json (evidence stamp — NOT Approve template)
- FE: src/lib/writebacks.ts (do NOT add CC-01 to WRITEBACK_APPROVE_EXECUTABLE in Phase A)

Ship in two hard-gated phases (same PRD; Phase B cannot ship without Phase A + Loom + product).

CRITICAL:
- Fix Owner = Data lead — sandbox ON bypasses fix_owner gate; Phase A MUST use execute_mode=plan_only + no FE allowlist + no WritebackAllowedCheck seed
- pipeline.py today hardcodes blocked_reason=ci03_plan_only for ALL plan_only mappings — generalize to check-specific reason (cc01_plan_only for CC-01; keep ci03_plan_only for CI-03); add messages.py cc01_plan_only
- mismatch_samples + evaluate_cc_01 provenance today OMIT provenance_ok / provenance_weak / optedOut — enrich BOTH _sample() and provenance builder (§3.3) or FORCE_OPT_IN gate is blind
- transform.py has NO CC-01 branch — must add _cc01_evidence_rows + _cc01_plan_payload in _build_payload_and_state (same pattern as CI-03 contact_merge plan). Plain _contact_upsert_payload DROPS proposed_action / evidence_gate
- _match_evidence does NOT support oneOf — do NOT use oneOf in mapping; use two const ops OR dedicated transform filter (§4)
- pipeline effective_max: add CC-01 → CC_SAMPLE (else wrong SANDBOX_MAX_ROWS)
- FE writebackNonExecutableHonesty: add CC-01 case (today only CI-03 is special-cased)
- Mapping MUST be hand-authored — stub_factory T8→detail_set/individual and CC-*→requires_consent_namespace_clean=true are BOTH wrong for CC-01
- Do NOT copy CC-03 FE allowlist pattern in Phase A
- Do NOT implement consent_reconcile adapter — use contact_upsert + forceOpt* (template_id T8)
- Do NOT write Shopify marketing consent
- Do NOT ship CC-02 / CC-05 in this PR

PHASE A (MVP1 must-ship — policy + plan Preview/Download):
1. consent_join._sample: add provenance_ok, provenance_weak, provenance_note, optedOut, manago_email_in, shopify_email_in, link_kind (§3.3).
2. evaluate_cc_01: pass those fields (+ prior_optedOut alias) through provenance mismatches; side = email_quadrant.
3. Mapping CC-01.consent_reconcile.v1.json — hand-authored; execute_mode=plan_only; template_id=T8; approval_tier=batch; irreversible=true; requires_consent_namespace_clean=false; TWO ops with const side out_in / in_out (§4) — no oneOf.
4. transform: _cc01_evidence_rows (filter sides; live rebuild via pins + build_consent_snapshot; enrich klints_consent_evidence via find_manago_contact + contact_detail_value like CC-03); _cc01_plan_payload + _build_payload_and_state branch when check_id=CC-01 and execute_mode=plan_only (§5).
5. pipeline: plan_only reason helper; CC-01 effective_max=CC_SAMPLE; CC-01 truncation + empty-intents copy (§5.0).
6. messages.py: cc01_plan_only (+ generic plan_only fallback).
7. Possible sheet + SURFACE + FE honesty including writebackNonExecutableHonesty CC-01 case (§7–8). Registry enabled; WritebackAllowedCheck NOT seeded; FE allowlist NOT added.
8. Confirm CheckMaster.fix_owner for CC-01 is "Data lead".
9. Tests + scripts/verify_wb17_cc01_consent_reconcile.py Phase A.

PHASE B (gated — only after §5.3 Loom + product sign-off):
10. _build_payload_and_state CC-01 execute: proposed_action→forceOptOut/forceOptIn bools on upsert payload (transport already allows root keys).
11. Rollback: log prior optedOut; forceOptOut NOT rolled back (Excel); forceOptIn best-effort restore optional.
12. FE allowlist + WritebackAllowedCheck CC-01 only after product override logged in §16; migration number = next after head at Phase B start (today head includes 0043_contact_excluded — expect ~0044_writeback_allowed_cc01).
13. Batch ceiling = UPSERT (≤1000) with sample honesty; Settings still required; toast "re-run DCS to clear CC-01".

Do NOT enable FE WRITEBACK_APPROVE_EXECUTABLE for CC-01 in Phase A.
Do NOT forceOptIn unevidenced / weak agent-like opt-ins.
Do NOT invent sandbox mismatch rows.
Do NOT change CC-01 FAIL bands.
Do NOT auto-stub CC-01 from stub_factory.
Acceptance: §12.
```

---

## 1. Why (simple)

| Before WB-17 | After Phase A | After Phase B (gated) |
|--------------|---------------|------------------------|
| CC-01 FAILs on email quadrant mismatches; Fix has Download only / no plan | Fix Preview shows **proposed actions** per mismatch + policy disclosure | Approved Manago `forceOpt*` batch per policy |
| Operators guess opt-in vs opt-out direction | Plan rows: `FORCE_OPT_OUT` / `FORCE_OPT_IN` / `SKIP_UNEVIDENCED` | Compliance `out_in` cleared safely; `in_out` only when evidenced |
| Excel T8 / Data lead unused on Fix | Honest plan-only (like CI-03) | Execute only after Loom + product |
| UC-06B / UC-17 / UC-21 gated on CC-01 PASS | Operators can act from Download | Re-score → PASS when matrix clean |

```text
CC-01 FAIL
  → Phase A: Fix Preview shows consent_reconcile_plan rows
       → Download Excel for Data lead
       → Approve execute DENIED (plan_only + Data lead; reason cc01_plan_only)
  → Data lead applies policy in Manago  OR  Phase B Approve on gated forceOpt*
  → Re-run DCS → email_mismatches↓ → CC-01 PASS
```

### 1.1 Excel Suggested Fix = three products

| Part | Meaning | This PRD |
|------|---------|----------|
| **A. Policy** | SoT + precedence per direction | **Phase A** (disclosure + plan actions) |
| **B. Approved batch** | Upsert `forceOptIn` / `forceOptOut` | **Phase B** (gated) |
| **C. Live bi-di sync** | Ongoing Shopify↔Manago | **Out** → CC-05 / integrator |

---

## 2. Product decisions (locked)

| # | Decision | Lock |
|---|----------|------|
| 1 | Catalogue Suggested Fix starts with **Define consent source-of-truth…** | **Yes** — Phase A ships policy honesty + plan |
| 2 | Pack Fix Owner = **Data lead** | **Yes** — CheckMaster SoT. Mapping `fix_owner` documentary only. Phase A hard stops: `execute_mode=plan_only` + FE allowlist **off** + no `WritebackAllowedCheck`. Do **not** rely on `fix_owner_not_klints_automated` alone when sandbox execute ON |
| 3 | Eng owner = **Sahil**; mutate owner stays Data lead unless product flips Fix Owner | **Yes** |
| 4 | Default policy matrix | **Yes** — §2.1 |
| 5 | Phase A `execute_mode` = **`plan_only`** | **Yes** — reuse WB-16 pipeline wire; generalize deny reason by check |
| 6 | Phase A FE Approve allowlist | **OFF** |
| 7 | Op implementation | **`contact_upsert` + `forceOptIn`/`forceOptOut`**; mapping `template_id: "T8"`; do **not** require new `consent_reconcile` adapter for Phase B |
| 8 | Write target Phase A/B | **Manago only** |
| 9 | Shopify marketing consent API | **Out of scope** |
| 10 | `out_in` → `FORCE_OPT_OUT` | **Yes** — opt-out wins / compliance first |
| 11 | `in_out` → `FORCE_OPT_IN` only if evidence gate passes | **Yes** — §2.1 |
| 12 | Unevidenced / `provenance_weak` → `SKIP_UNEVIDENCED` | **Yes** — Download / re-permission; never forceOptIn |
| 13 | `requires_consent_namespace_clean` | **`false`** for forceOpt-only (native root flags). If Phase B+ also stamps `klints_*`, set **true** for those ops only |
| 14 | `approval_tier` | **`batch`** (Excel “approved reconciliation batch”) |
| 15 | `irreversible` | **`true`** — Excel: opt-out deliberately not rolled back; disclose |
| 16 | Rollback | Log prior `optedOut` + source; **`forceOptOut` not rolled back**; `forceOptIn` best-effort restore optional in Phase B |
| 17 | Sample Preview = **`CC_SAMPLE` = 50**; Download = full mismatch list (uncapped from consent snapshot / pinned rebuild) | **Yes** — CI-03 / CI-05 honesty pattern |
| 18 | No sandbox invent of mismatch rows | **Yes** |
| 19 | Do **not** copy CC-03 Approve-as-Data-lead into Phase A | **Yes** |
| 20 | CC-02 / CC-05 | **Out** of this PRD |
| 21 | Capability | Reuse **`RESTV2.CONTACT.UPSERT`** CONFIRMED_LIVE |
| 22 | Prefer clear CC-03 Shopify-evidence cohort before mass `FORCE_OPT_IN` | **Yes** — operator order §6 |
| 23 | Do **not** add CC-01 to `suppressFixProceedToStudio` | **Yes** |
| 24 | Pipeline plan_only reason | Generalize: CC-01 → `cc01_plan_only`; CI-03 → `ci03_plan_only`; unknown plan_only → `plan_only` |
| 25 | Mapping match | **Two `const` ops** — **no `oneOf`** until `_match_evidence` supports it with tests |
| 26 | Transform plan path | Dedicated `_cc01_evidence_rows` + `_cc01_plan_payload` — not bare `_contact_upsert_payload` |
| 27 | Mapping authorship | Hand-authored only — **never** stub_factory for CC-01 |
| 28 | Download SoT | Prefer uncapped mismatch export; do not claim uncapped while reading `consent_rows[:500]` only |

### 2.1 Locked policy matrix (product must not weaken without §16)

| Quadrant | Shopify | Manago | Risk | Proposed action | Evidence gate |
|----------|---------|--------|------|-----------------|---------------|
| **`out_in`** | out | in | **Compliance** | `FORCE_OPT_OUT` | Always (opt-out everywhere) |
| **`in_out`** | in | out | Lost reach | `FORCE_OPT_IN` | Pass if **any** of: `provenance_ok` · Contact `klints_consent_evidence=shopify_verified` · Shopify `opt_in_level` present **and** `consent_updated_at` present |
| `in_out` fail gate | in | out | — | `SKIP_UNEVIDENCED` | Weak / empty consents / agent-like |
| `in_in` / `out_out` | aligned | — | No write | — |

**Shopify `pending`** remains **out** (existing `_shopify_consent_in`) — do not treat as opted-in.

### 2.2 Excel vs automation (honest)

| Catalogue text | WB-17 interpretation |
|----------------|----------------------|
| Fix Type = Integration build + Automated writeback | Phase A = Klints **plan**; Phase B = optional approved batch; Integration = live sync later |
| Fix Owner = Data lead | Execute gated; Data lead owns policy |
| Suggested Fix forceOpt\* | Phase B only |
| Rollback: opt-out not rolled back | Disclosure + rollback strategy |

### 2.3 Lane wall

```text
Sahil WB-17 Phase A  =  DCS sample enrich + plan Preview/Download + policy disclosure
Sahil WB-17 Phase B  =  Manago forceOpt* batch + FE Approve (product override)
Do not regress       =  CC-03 / SP-07 / CI-* / LE-* / PT-04 live writebacks
Out of this PR       =  CC-02 · CC-05 · Shopify consent API · live bi-di sync
```

---

## 3. Excel / executor contract (do not invent)

### 3.1 Catalogue (sheet 02) + CHECK_MASTER

Exact Excel CC-01 row (v1.4.1). Verified via workbook extract 2026-09-25 + `CHECK_MASTER_42.md`.

| Column | Value |
|--------|--------|
| Check ID | **CC-01** |
| DCS Dimension | 05 Channel & Consent |
| Check Name | Email opt-in parity |
| Entity | Consent |
| Systems Compared | Shopify vs Manago |
| Check Type | Consent compliance |
| Detection Logic | Per linked identity: Shopify `email_marketing_consent` (state, opt_in_level, consent_updated_at) vs Manago email marketing status; four-quadrant matrix with counts |
| Manago Surface | email marketing consent + reason/source |
| Shopify Surface | `customers.email_marketing_consent` |
| Inconsistency Type | Consent states disagree between commerce and marketing platform |
| Root Causes | RC-07, RC-05, RC-01 |
| Business Impact | in Shopify / out Manago = lost reach; out Shopify / in Manago = compliance exposure |
| Affected Workflows | Every email send |
| Severity | **Critical** |
| DCS Weight | High (numeric **4**) |
| Suggested Fix | Define consent source-of-truth and precedence per direction (opt-outs propagate everywhere immediately; opt-ins propagate only with provable consent record — agent-set opt-ins do not qualify, see CC-03); approved reconciliation batch via upsert with forceOptIn/forceOptOut used strictly per policy; live bi-directional sync thereafter |
| Fix Type | Integration build + Automated writeback (approved) |
| Fix Owner | **Data lead** |
| Rollback Note | Consent writes logged with prior state + source; **opt-out propagation is deliberately not rolled back** |
| Cadence | Initial + Recurring |
| MVP1 Fix Blueprint | Y |
| Fix Template | **T8 Consent reconciliation** |
| Build Priority | **P0** |

CHECK_MASTER_42: RULE_BASED · SCORED · MVP1-A · weight 4 · Critical · RC-07, RC-05, RC-01.

### 3.2 Live scoring (already shipped — do not change bands)

| Piece | Location |
|-------|----------|
| Join | `consent_join.build_consent_snapshot` |
| Score | `evaluate_cc_01` |
| FAIL if | `compliance_exposure_email > 0` **or** `email_mismatches > 0` |
| UNKNOWN if | no linked identities / missing inputs |
| Sample cap | `CC_SAMPLE = 50` |

Quadrant axes:

| Side | Field | In |
|------|-------|-----|
| Shopify | `email_marketing_consent.state` | `subscribed` only (`pending` = out) |
| Manago | `optedOut` | `False` = in |

Link: `externalId` ↔ `customers.id`; fallback email.

### 3.3 Evidence enrich (Phase A required)

Today `_sample()` in `consent_join` **and** `evaluate_cc_01` provenance builders **omit** provenance / optedOut. Transform cannot gate `FORCE_OPT_IN` honestly.

**Must enrich in both places (not only one):**

| Field | Source | Where |
|-------|--------|-------|
| `provenance_ok` | linked row | `_sample()` + provenance mismatch dict |
| `provenance_weak` | linked row | same |
| `provenance_note` | linked row | same |
| `optedOut` / `prior_optedOut` | Manago (`optedOut`) | same; alias `prior_optedOut` for plan payload |
| `manago_email_in` / `shopify_email_in` | linked | same |
| `link_kind` | linked | same |
| `klints_consent_evidence` | **transform-time** | `_cc01_evidence_rows`: `find_manago_contact` + `contact_detail_value(..., "klints_consent_evidence")` — same pattern as CC-03. Do **not** require consent_join to load details |

Keep existing: email, ids, opt_in_level, consent_updated_at, modified_on, lag, quadrant.

**Side values for writeback match:** `out_in` | `in_out` (from `email_quadrant` → provenance `side`).

Mismatch sample keys (existing — do not rename):

| Key | Meaning | Plan action default |
|-----|---------|---------------------|
| `mismatch_samples.email_out_in` | Shopify out / Manago in — compliance | → rows with `side=out_in` → `FORCE_OPT_OUT` |
| `mismatch_samples.email_in_out` | Shopify in / Manago out — lost reach | → rows with `side=in_out` → gate → `FORCE_OPT_IN` or `SKIP_UNEVIDENCED` |

Also available (Download / gate helpers): `shopify_holds_evidence`, `manago_only_unevidenced`, `weak_provenance`.

**Tests must fail if** provenance mismatch rows lack `provenance_ok` / `optedOut` after this PR.

### 3.4 Download honesty

Preview may show ≤50 plan rows (`CC_SAMPLE`). **Download** must not silently pretend the sample is the estate.

| Path | Behaviour |
|------|-----------|
| Preview / plan intents | Cap `CC_SAMPLE` via pipeline `effective_max` |
| FE-12 Download | Rebuild from **pinned** consent snapshot: filter full `linked` list (or expose `consent_mismatch_rows` uncapped) where `email_quadrant in {out_in,in_out}`; attach `proposed_action` / `evidence_gate` |
| Hard cap today | `build_consent_snapshot` stores `consent_rows: linked[:500]` — **insufficient as SoT for uncapped Download** |

**Lock:** Phase A must either (a) add `consent_mismatch_email` (or `consent_rows_full`) unsliced for Download/rebuild, **or** (b) document Download truncation at 500 with an explicit truncation banner in the CSV. Prefer **(a)**. Do not claim “uncapped” while only reading `consent_rows[:500]`.

Pins: Fix live rebuild uses `resolve_scoring_pins` + `build_consent_snapshot` (same universe honesty as CI-03 / identity).

---

## 4. Mapping (Phase A)

**File:** `dataruns/writebacks/mappings/CC-01.consent_reconcile.v1.json`  
**Must be hand-authored.** Do **not** generate from `stub_factory` — factory maps `T8→detail_set/individual` and forces `requires_consent_namespace_clean=true` for all `CC-*` (both wrong here).

### 4.0 Match rule lock (critical)

`transform._match_evidence` today supports **`const` only** — **`oneOf` is NOT implemented** and would silently match any row with a `side` field.  

**Lock:** Phase A mapping uses **two operations** with `"const": "out_in"` and `"const": "in_out"`. Do **not** ship `oneOf` unless a separate transform PR adds real `oneOf` support + tests first.

```json
{
  "schema_version": "1.0.0",
  "check_id": "CC-01",
  "template_id": "T8",
  "title": "Email consent reconcile plan (forceOpt policy)",
  "enabled": true,
  "approval_tier": "batch",
  "execute_mode": "plan_only",
  "requires_consent_namespace_clean": false,
  "irreversible": true,
  "fix_owner": "Data lead",
  "operator_disclosure": "CC-01 proposes an email consent reconcile plan from the Shopify↔Manago four-quadrant matrix. Catalogue Fix Owner is Data lead — not Klints automated. Policy: opt-outs propagate everywhere immediately (out_in → forceOptOut on Manago); opt-ins propagate only with a provable consent record — agent-set Manago opt-ins do not qualify (see CC-03). Phase A: Preview + Download only. Phase B (if enabled after Loom + product): Manago contact upsert with forceOptOut / forceOptIn strictly per policy. Opt-out writes are deliberately not rolled back. Does not write Shopify marketing consent and does not replace the live bi-directional sync (CC-05 / integration). Re-run DCS after Manago state changes.",
  "rollback": {
    "strategy": "none",
    "note": "Excel: opt-out propagation deliberately not rolled back. Phase B may log prior optedOut for audit; forceOptOut not reverted."
  },
  "operations": [
    {
      "operation_id": "manago.contact_upsert.force_opt_out_plan",
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
          "prior_optedOut": { "path": "prior_optedOut" }
        }
      },
      "guards": ["entity_key_required", "email_format", "plan_only"]
    },
    {
      "operation_id": "manago.contact_upsert.force_opt_in_plan",
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
          "prior_optedOut": { "path": "prior_optedOut" }
        }
      },
      "guards": ["entity_key_required", "email_format", "plan_only"]
    }
  ]
}
```

**Registry:**

```json
"CC-01": {
  "file": "CC-01.consent_reconcile.v1.json",
  "enabled": true,
  "template_id": "T8"
}
```

Phase A: **enabled true**, plan_only. Phase B: remove/flip `execute_mode`; extend payload builder for real forceOpt bools — **separate migration + allowlist**.  

`SKIP_UNEVIDENCED` rows: still appear in Preview/Download via `_cc01_evidence_rows`; they **must not** produce execute-ready intents (filter in plan payload builder when `proposed_action=SKIP_UNEVIDENCED`, or mark intent non-ready).

---

## 5. Transform + pipeline

### 5.0 Critical wires (must ship in Phase A)

| Wire | Action |
|------|--------|
| `consent_join._sample` | Pass provenance_ok/weak/note, optedOut, manago/shopify email_in, link_kind |
| `evaluate_cc_01` provenance | Forward those fields; `side=email_quadrant`; `prior_optedOut=optedOut` |
| `pipeline.py` `execute_mode==plan_only` | Reason helper: `CI-03→ci03_plan_only`, `CC-01→cc01_plan_only`, else `plan_only` (**today hardcodes ci03_plan_only — wrong for CC-01**) |
| `pipeline.py` `effective_max` | `elif CC-01: effective_max = CC_SAMPLE` (import from consent_join) |
| `pipeline.py` truncation note | CC-01-specific: “Consent plan sample capped at {N} mismatches…” (do not reuse PT-04 net-LTV copy) |
| `pipeline.py` empty intents | CC-01-specific honesty when no out_in/in_out rows |
| `messages.py` | Add `cc01_plan_only` (+ optional generic `plan_only`) |
| `transform.collect_evidence_rows` | `elif CC-01: _cc01_evidence_rows(...)` |
| `transform._cc01_evidence_rows` | Filter `side in {out_in,in_out}`; set `proposed_action` / `evidence_gate` per §5.2; live rebuild via `resolve_scoring_pins` + `build_consent_snapshot` when worklist empty/stale; enrich `klints_consent_evidence` via `find_manago_contact` + `contact_detail_value` |
| `transform._build_payload_and_state` | **New branch:** if check_id=CC-01 and mapping `execute_mode=plan_only` → `_cc01_plan_payload` (like `_contact_merge_plan_payload`). Do **not** use plain `_contact_upsert_payload` — it drops plan fields |
| `_cc01_plan_payload` | `{mode:"plan", side, proposed_action, evidence_gate, prior_optedOut, email, contactId, shopify_customer_id, …}` — no Manago mutate |
| `manago.dry_run` | Plan intents (`payload.mode=plan` / execute_mode plan_only) skip capability hard-fail (same as CI-03) |
| `guards.plan_only` | Already no-op pass |
| FE `writebackNonExecutableHonesty` | Add CC-01 case (§8) |

### 5.1 Denial copy

```text
cc01_plan_only:
  CC-01 is plan-only: Preview and Download show the consent reconcile plan.
  Klints does not auto-apply forceOpt in Phase A. Data lead applies policy
  in Manago (or Phase B Approve after Loom + product sign-off).
```

### 5.2 Transform rules (Phase A)

For each mismatch row with `side in {out_in, in_out}` (set in `_cc01_evidence_rows` **before** mapping match):

| Condition | `proposed_action` | `evidence_gate` |
|-----------|-------------------|-----------------|
| `side == out_in` | `FORCE_OPT_OUT` | `opt_out_wins` |
| `side == in_out` and gate pass (§2.1) | `FORCE_OPT_IN` | `provenance_ok` \| `klints_consent_evidence` \| `shopify_opt_in_level+ts` |
| `side == in_out` and gate fail | `SKIP_UNEVIDENCED` | `fail` |

Evidence-gate pass (§2.1) = any of:

1. `provenance_ok is True`  
2. `klints_consent_evidence == "shopify_verified"`  
3. Shopify `opt_in_level` non-empty **and** `consent_updated_at` present  

If `provenance_weak` and neither (2) nor (3) → **fail** (SKIP).

`SKIP_UNEVIDENCED`: include in Preview/Download; plan payload may still be emitted with `ready=false` / excluded from execute-eligible count.

### 5.3 Phase B execute (appendix — gated)

| Action | Upsert root fields (via CC-01 `_build_payload_and_state` execute branch) |
|--------|-------------------|
| `FORCE_OPT_OUT` | `forceOptOut: true` + identity email/contactId |
| `FORCE_OPT_IN` | `forceOptIn: true` — **only** if evidence_gate ≠ fail |
| `SKIP_UNEVIDENCED` | Never execute |

Transport: `manago_transport._UPSERT_ROOT_KEYS` already includes `forceOptIn` / `forceOptOut`. Phase B must put those keys on the **upsert payload dict** that `_upsert_request_payload` merges as extras — not only inside `properties`.

**Loom proof (required before Phase B product flip):**

1. Sandbox contact `out_in` → Approve forceOptOut → Manago `optedOut=true` → re-score quadrant clears  
2. Sandbox contact `in_out` with Shopify evidence → forceOptIn → `optedOut=false`  
3. Unevidenced `in_out` → skipped / deny  
4. Rollback attempt on forceOptOut → honest “not rolled back”  
5. Settings OFF → execute denied  

FE Phase B: toast append `· re-run DCS to clear CC-01` (mirror CI-05/LE-05).

### 5.4 Batch / ceiling

| Mode | Cap |
|------|-----|
| Phase A Preview | `CC_SAMPLE` (50) via pipeline `effective_max` |
| Phase A Download | Uncapped mismatch list per §3.4 (prefer full linked filter) |
| Phase B execute | UPSERT `batch_max` ≤1000; once-per-DCS-run gate (WB-04) |

---

## 6. Operator order (runtime)

Prefer when multiple FAIL:

```text
SP-07 (if klints_ writes) → CI-01 → CI-05 → CI-03 plan
→ LE-05 → LE-01 → LE-02 → LE-09 → PT-04
→ CC-03 evidence stamp
→ CC-01 plan / Phase B
→ (later) CC-02
```

Pilots UC-06B / UC-17 / UC-21 remain hard-gated on CC-01 PASS.

---

## 7. Possible sheet + SURFACE

### 7.1 `WRITEBACK_POSSIBLE_NOT_SHEET.csv` (both docs + dataruns copies)

| Field | Value |
|-------|--------|
| check_id | CC-01 |
| pack_fix_type | Integration build + Automated writeback (approved) |
| pack_fix_owner | Data lead |
| pack_suggested_fix_summary | Propose email consent reconcile plan (forceOptOut/In per policy); not auto-applied Phase A; Data lead |
| platform | manago |
| op_kind | contact_upsert |
| entity | contact |
| field_or_key | forceOptIn \| forceOptOut |
| namespace | native |
| write_possible_today | **preview_only** |
| rollback_possible_today | **no** (opt-out deliberately not rolled back) |
| mapping_file | CC-01.consent_reconcile.v1.json |
| registry_enabled | true |
| blocker | `plan_only_data_lead` |
| evidence_note | four-quadrant; out_in compliance first; in_out needs CC-03/Shopify evidence; T8 via upsert forceOpt\* |

### 7.2 `WRITEBACK_SURFACE_MATRIX.md`

Add / update row: Consent email reconcile — Phase A plan live (WB-17); Phase B Manago forceOpt\* after Loom; Data lead; not Shopify consent API.

---

## 8. Frontend

| Item | Phase A | Phase B |
|------|---------|---------|
| `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` | **Do not add CC-01** | Add only after product + Loom |
| Preview | Show plan rows + policy disclosure | Same |
| Download | Full mismatch + proposed_action (§3.4) | Same |
| Approve | Disabled / honest plan-only message | Enabled when allowlisted |
| Trust copy | Data lead · irreversible opt-out | Same |
| `writebackNonExecutableHonesty` | **Add CC-01 case** (today only CI-03) | Keep until allowlisted |
| Surface blurb / toast | Optional mention CC-01 plan-only | Toast: re-run DCS to clear CC-01 |

**Required FE honesty copy (Phase A):**

```text
title: Consent reconcile plan — Data lead executes
detail: CC-01: plan_only_data_lead. Preview + Download show FORCE_OPT_OUT /
  FORCE_OPT_IN / SKIP_UNEVIDENCED plan rows. Approve will not apply forceOpt
  in Phase A. Data lead applies policy in Manago and re-runs DCS.
```

Reuse CI-03 Preview/Download patterns; do **not** reuse CC-03 Approve chrome.

---

## 9. Allowlist / Settings / fix_owner

| Gate | Phase A | Phase B |
|------|---------|---------|
| Settings Allow writebacks | N/A for mutate (blocked by plan_only) | Required |
| `WritebackAllowedCheck` CC-01 | **Do not seed** | Migration after product sign-off — verify next number at Phase B start (repo head today includes `0043_contact_excluded_tombstone`; expect e.g. `0044_writeback_allowed_cc01`) |
| CheckMaster `fix_owner=Data lead` | preview_only_owner when execute off; **insufficient alone when sandbox ON** | Product override logged §16 if Approve allowed under Data lead |
| FE allowlist | Off | On after sign-off |

---

## 10. Tests + verify

| Item | Path |
|------|------|
| Django tests | `dataruns/tests/test_writeback_wb17.py` |
| Verify script | `scripts/verify_wb17_cc01_consent_reconcile.py` |

**Phase A must assert:**

- Registry CC-01 enabled; mapping `execute_mode=plan_only`; **two const ops** (no oneOf)  
- `_sample` + provenance carry provenance_ok / optedOut / prior_optedOut  
- `_cc01_evidence_rows` sets FORCE_OPT_OUT / FORCE_OPT_IN / SKIP_UNEVIDENCED correctly  
- `_cc01_plan_payload` used (not plain contact_upsert payload) for plan intents  
- Execute → `blocked_reason=cc01_plan_only` (even with sandbox execute ON) — **not** `ci03_plan_only`  
- `effective_max` for CC-01 == `CC_SAMPLE`  
- FE allowlist constant does **not** include CC-01  
- FE `writebackNonExecutableHonesty` has CC-01 case  
- No `WritebackAllowedCheck` seed for CC-01  
- CheckMaster fix_owner == `Data lead`  
- Messages include `cc01_plan_only`  
- Mapping was not stub_factory-generated (`requires_consent_namespace_clean=false`)  

**Phase B (later):** forceOpt upsert payload root keys; skip unevidenced; opt-out not rolled back; allowlist migration; toast re-run DCS.

---

## 11. Files to touch (Phase A)

| Area | Files |
|------|--------|
| DCS | `consent_join.py` (`_sample` + optional uncapped mismatch export), `consent.py` (provenance pass-through) |
| Mapping / registry | **Hand-authored** `CC-01.consent_reconcile.v1.json`, `registry.json` — **not** stub_factory |
| Pipeline / messages / transform | `pipeline.py` (reason + effective_max + truncation/empty copy), `messages.py`, `transform.py` (`_cc01_evidence_rows`, `_cc01_plan_payload`, `_build_payload_and_state` branch) |
| Sheet / SURFACE | `WRITEBACK_POSSIBLE_NOT_SHEET.csv` (×2), `WRITEBACK_SURFACE_MATRIX.md` |
| FE | `writebacks.ts` honesty for CC-01 — **no** allowlist add |
| Tests / verify | `test_writeback_wb17.py`, `verify_wb17_cc01_consent_reconcile.py` |
| Docs | this PRD · README |

Phase B adds: execute payload branch, rollback honesty, FE allowlist, `WritebackAllowedCheck` migration, toast.

---

## 12. Acceptance

### Phase A

- [ ] Excel §3.1 language preserved in mapping disclosure  
- [ ] CheckMaster `fix_owner=Data lead` confirmed  
- [ ] `_sample` + provenance carry provenance + optedOut fields  
- [ ] Mapping uses **two const ops** (no oneOf); hand-authored; `requires_consent_namespace_clean=false`  
- [ ] `_cc01_evidence_rows` + `_cc01_plan_payload` (not bare upsert)  
- [ ] Preview plan rows for `out_in` / `in_out` with correct proposed_action  
- [ ] Unevidenced `in_out` → `SKIP_UNEVIDENCED`  
- [ ] Download honesty per §3.4 (not sample-masquerading-as-full)  
- [ ] Execute denied with **`cc01_plan_only`** under sandbox ON (not `ci03_plan_only`)  
- [ ] `effective_max` = `CC_SAMPLE` for CC-01  
- [ ] FE Approve allowlist excludes CC-01; honesty case present  
- [ ] Possible sheet `preview_only` + SURFACE updated  
- [ ] verify_wb17 Phase A green  
- [ ] No CC-02 / CC-05 / Shopify consent writer shipped  

### Phase B (gated)

- [ ] Loom §5.3 passed  
- [ ] Product sign-off logged in §16 (Data lead Approve exception)  
- [ ] FE allowlist + WritebackAllowedCheck seeded (migration # verified at time)  
- [ ] forceOptOut / forceOptIn on upsert **root** payload per §2.1 / §5.3  
- [ ] Opt-out not rolled back (honest)  
- [ ] Re-score can PASS CC-01 after successful batch  
- [ ] Toast mentions re-run DCS for CC-01

---

## 13. Out of scope (explicit)

See header list. Especially: **CC-02**, **CC-05**, live bi-di sync, Shopify marketing consent API, changing FAIL bands, Phase A Approve.

---

## 14. Risks

| Risk | Mitigation |
|------|------------|
| Sandbox ON bypasses fix_owner | plan_only + no allowlist (WB-16 lesson) |
| forceOptIn without proof | evidence gate + SKIP |
| Operators think CC-03 Approve = CC-01 template | Ownership doc + disclosure |
| Sample-only Download | Uncapped Download requirement §3.4 |
| Mixing SMS into email PR | Hard out of scope |
| Irreversible opt-out surprise | `irreversible=true` + disclosure + Excel rollback note |

---

## 15. Parents / next

| | |
|--|--|
| Parents | WB-01…16 · CC-03 · consent_join · ownership matrix |
| MVP1 · P0 order | **#7** after CI-03 Phase A |
| Next | **CC-02** (twin T8 SMS) after CC-01 Phase A; Phase B can parallel product review |
| Unblocks | Pilot gates UC-06B / UC-17 / UC-21 honesty; Data lead Fix workflow |

---

## 16. Open questions (product)

| # | Question | PRD default until answered |
|---|----------|----------------------------|
| 1 | Shopify always SoT for opt-**out**? | **Yes** |
| 2 | Shopify SoT for opt-**in** only with proven record? | **Yes** |
| 3 | Allow Phase B Approve while Fix Owner stays Data lead? | **Only with explicit sign-off** (CC-03-class exception) |
| 4 | Upsert forceOpt\* vs new consent_reconcile adapter? | **Upsert forceOpt\*** |
| 5 | Same PR as CC-02? | **No** |
| 6 | Require SP-07 for Phase A/B forceOpt-only? | **No** (`requires_consent_namespace_clean=false`) |
| 7 | Roll back forceOptOut? | **No** |
| 8 | Evidence gate: is Shopify opt_in_level+ts enough without CC-03 stamp? | **Yes** as alternate gate (§2.1); prefer CC-03 stamp when present |

**Sign-off log (fill when Phase B starts):**

| Date | Who | Decision |
|------|-----|----------|
| | | |

---

## 17. Related

- [`ANALYSIS_CC01_EMAIL_CONSENT_RECONCILE.md`](./ANALYSIS_CC01_EMAIL_CONSENT_RECONCILE.md)  
- [`WRITEBACK_FIX_OWNERSHIP_MVP1_42.md`](./WRITEBACK_FIX_OWNERSHIP_MVP1_42.md)  
- [`PRD_WB_16_CI03_CONTACT_MERGE_WRITEBACK.md`](./PRD_WB_16_CI03_CONTACT_MERGE_WRITEBACK.md)  
- [`PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md`](./PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md)  
- `dataruns/dcs/consent_join.py` · `dataruns/dcs/executors/consent.py`  
- `dataruns/writebacks/adapters/manago_transport.py` (`forceOptIn` / `forceOptOut`)  
- `dataruns/writebacks/mappings/CC-03.consent_provenance.v1.json`  
- `dataruns/writebacks/transform.py` (`_match_evidence` const-only; CI-03 plan payload pattern)  
- `klints_frontend/src/lib/writebacks.ts` (`writebackNonExecutableHonesty` CI-03 case to mirror)

---

## 18. Gap-closure log (audit 2026-09-25)

Closed against live code before implement:

| Gap | Fix in this PRD |
|-----|-----------------|
| `oneOf` unsupported in `_match_evidence` | §4.0 — two `const` ops |
| pipeline always `ci03_plan_only` | §5.0 + §2 #24 |
| missing `cc01_plan_only` message | §5.1 |
| provenance / `_sample` missing gate fields | §3.3 both layers |
| no `_cc01_evidence_rows` / plan payload | §5.0 + §2 #26 |
| bare upsert drops plan fields | §5.0 `_cc01_plan_payload` |
| `effective_max` wrong for CC-01 | §5.0 / §5.4 |
| Download vs `consent_rows[:500]` | §3.4 honest options |
| `klints_consent_evidence` lookup | §3.3 transform-time |
| FE honesty only CI-03 | §8 copy |
| stub_factory wrong for CC-01 | §4 + §2 #27 |
| Phase B migration # | §9 verify-at-time |
| Phase B forceOpt root payload | §5.3 |
