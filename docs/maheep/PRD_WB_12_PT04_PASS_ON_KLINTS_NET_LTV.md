# PRD-WB-12 — PT-04 PASS when `klints_net_ltv` matches net

**Status:** **Shipped (WB-12)** — P0 M2 close gap · Sahil  
**Draft review:** Re-checked vs WB-11 / `product_truth` / verify scripts (2026-09-22) — gaps folded into §2–§3 / §7–§8.  

**Owner track:** Sahil — **BE primary (DCS `product_truth` + `evaluate_pt_04`)** · FE disclosure / Fix copy only  
**Surfaces:** DCS re-score · Fix `/fix` disclosure · worklist (PT-04 clears when eligible) · pilot/Handoff gates that require PT-04 PASS  
**Milestone:** M2 Activation & Blueprint (T2) — complete Automated writeback **treating process** for PT-04  
**Depends on:** WB-11 shipped (`detail_set` `klints_net_ltv`) · live `evaluate_pt_04` + `product_truth` · Manago contact properties on raw snapshot  
**PRD path:** `docs/maheep/` (writeback series numbering — completes WB-11 honesty deferral)  
**Contract SoT:** Catalogue **Automated writeback (approved)** treating loop: FAIL → Approve → re-score → **PASS**  
**Pack SoT:**  
- Excel Suggested Fix: maintain `klints_net_ltv` as governed value **and** point workflows at it  
- WB-11 §3.3 / §13 → points here (**WB-12**)  
- MVP1 gates / CheckMaster: PT-04 SCORED · Automated writeback  
**Out of scope:**  
- New writeback mapping / adapter ops (WB-11 mapping stays)  
- Changing `PT04_DELTA_FAIL` band value (still 2%)  
- Rewriting Manago PURCHASE events / `event_correct`  
- Auto-chaining LE-09 inside PT-04 Approve  
- Changing revenue formula IDs except excluding governed contacts from overstatement amount  
- Handoff / Studio / QA / CAP product changes beyond unlocking when PT-04 becomes PASS  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-12 — PT-04 PASS when klints_net_ltv matches Shopify net.

Read:
- docs/maheep/PRD_WB_12_PT04_PASS_ON_KLINTS_NET_LTV.md (this file)
- docs/maheep/PRD_WB_11_PT04_NET_LTV_WRITEBACK.md (§3.3 deferral)
- dataruns/dcs/product_truth.py
- dataruns/dcs/executors/product.py (evaluate_pt_04)
- dataruns/dcs/segment_join.py (_iter_detail_pairs bags — reuse pattern, not writebacks import)
- dataruns/writebacks/mappings/PT-04.net_ltv.v1.json
- scripts/verify_wb11_pt04_net_ltv_writeback.py (disclosure assert must flip)
- dataruns/tests/test_writeback_wb11.py (disclosure assert must flip)

Ship:
1. product_truth: while building manago_by_id, read klints_net_ltv from contact bags; governed rule (§3).
2. evaluate_pt_04: PASS when over_delta=0 and refund_blind=0 after governed exemption (§4).
3. Update PT-04 mapping operator_disclosure — remove “may not make PT-04 PASS” (§5).
4. FE Fix copy / honesty: after Approve, re-score can clear PT-04 (§6).
5. Tests (§7) + verify_wb12 + flip WB-11 disclosure asserts (§8).
6. Confirm README / WB-11 / M3_DEMO pointers (§9 — index already wired at draft).

Do NOT import dataruns.writebacks from product_truth.
Do NOT change writeback op_kind / mapping fields.
Do NOT invent a new FAIL band.
Do NOT require LE-09 PASS as a hard gate for PT-04 PASS.
Acceptance: §11.
```

---

## 1. Why (simple)

| Today (after WB-11) | Gap |
|---------------------|-----|
| Fix Approve stamps `klints_net_ltv` = Shopify net | Executor ignores the stamp |
| Excel + MVP treating process: Automated writeback → clear fail | Re-score keeps PT-04 **FAIL** |
| Pilots / Handoff gate on PT-04 PASS | Gate stays blocked after a “successful” Fix |

**WB-12** closes the treating loop: after stamp is visible on Manago contacts in the DCS snapshot, PT-04 **PASS**es when every linked overstatement/refund-blind contact is either naturally within band **or** governed by a matching `klints_net_ltv`.

```text
WB-11:  FAIL → Preview → Approve → stamp klints_net_ltv  (check may stay FAIL)
WB-12:  re-score → product_truth reads stamp → PASS when governed matches net
```

**Supersedes WB-11 decision #12** (“stamp does not clear PASS”) for post–WB-12 builds. Stamp still does not clear PASS *without* a fresh score that sees the property.

---

## 2. Product decisions (locked)

| # | Decision | Lock |
|---|----------|------|
| 1 | Teach **product truth** to honor `klints_net_ltv` when it matches Shopify net | **Yes** |
| 2 | Match band = same **`PT04_DELTA_FAIL` (2%)** relative, **or** absolute ≤ **0.01** (cents / already_at_target parity) | **Yes** |
| 3 | Missing / unparseable / mismatched stamp → contact still evaluated on PURCHASE vs net (unchanged) | **Yes** |
| 4 | Partial stamps: only governed contacts exempt; remaining overstatements still FAIL | **Yes** |
| 5 | `refund_blind` false for a contact when that contact is governed | **Yes** |
| 6 | Revenue / total_overstatement **excludes** governed contacts | **Yes** |
| 7 | No hard dependency on LE-09 status for PASS (prefer LE-09 still in disclosure) | **Yes** |
| 8 | No new mapping file; update **disclosure copy** only on existing PT-04 mapping | **Yes** |
| 9 | FE: stop implying “may not PASS”; say re-score can clear PT-04 when stamp matches | **Yes** |
| 10 | Owner = **Sahil** | **Yes** |
| 11 | Read stamp from Manago **contact raw** while building `manago_by_id` (today meta drops properties) | **Yes** |
| 12 | **No** `from dataruns.writebacks…` inside `product_truth` — reuse DCS bag-iteration pattern (`segment_join` / local helper) + `_float_or_none` | **Yes** |
| 13 | When `governed`, contact is exempt from FAIL counts **regardless of purchase over/under** (stamp is SoT for that contact) | **Yes** |
| 14 | Flip WB-11 verify + unit asserts that require “may not make PT-04 PASS” | **Yes** |

**Lane wall:**

```text
Sahil WB-12   =  product_truth + evaluate_pt_04 + disclosure/FE honesty + assert flips
Do not regress =  WB-11 writeback path / SP-07 owned key / once-per-run gate
Out of this PR =  new adapters · LE-09 auto-chain · Handoff product redesign
```

---

## 3. Excel / treating contract

### 3.1 Catalogue intent (close the loop)

| Field | Value |
|-------|--------|
| Check | Net vs gross transaction truth per contact |
| Fix Type | **Automated writeback (approved)** |
| Suggested Fix | LE-09 first; else maintain **`klints_net_ltv`** as governed value |
| Treating process (MVP) | Approve → platform reflects → **re-score → PASS** |

WB-11 shipped the stamp. WB-12 ships the **PASS** half so Fix Type matches operator expectation.

### 3.2 Governed contact rule

**Implementability note:** Today `build_product_truth_snapshot` stores only `manago_contact_id` / email / external_key on `manago_by_id` — **properties are discarded**. WB-12 must capture `klints_net_ltv` in that loop (or keep a pointer to the contact dict).

For each linked contact:

```text
net      = shopify_paid − shopify_refunded          # existing shopify_net
purchase = manago PURCHASE deduped lifetime         # existing
raw_stamp = detail from contact bags named klints_net_ltv
            (properties | dictionaryProperties | details | customFields;
             dict or {name,value} list — same as segment_join._iter_detail_pairs)
stamped  = _float_or_none(raw_stamp)                # None if missing / non-numeric

governed = stamped is not None AND (
             abs(stamped − net) <= 0.01
             OR abs(stamped − net) / max(abs(net), abs(stamped), 1.0) <= PT04_DELTA_FAIL
           )
```

Then:

```text
if governed:
  refund_blind = False
  # do not add to failing; overstatement contribution = 0 for aggregates
else:
  # existing:
  delta_vs_net = abs(purchase − net) / max(abs(net), abs(purchase), 1.0)
  refund_blind = refunded > 0 and purchase > net + 0.01
  failing iff delta_vs_net > PT04_DELTA_FAIL
```

| `governed` | How contact counts toward FAIL |
|------------|--------------------------------|
| **True** | Not in `failing` / not in `refund_blind`; `overstatement` contribution **0** |
| **False** | Existing rules unchanged |

Add row flags for evidence honesty:

- `governed_by_klints_net_ltv`: bool  
- `klints_net_ltv`: stamped float or null  
- Keep existing fields (`shopify_net`, `manago_purchase_value_deduped`, `delta_vs_net`, …). For governed rows, still compute `delta_vs_net` for display if useful, but **exclude from failing/refund_blind samples**.

### 3.3 Aggregate / PASS

```text
contacts_over_delta                  = count(non-governed failing)
contacts_refund_blind                = count(non-governed refund_blind)
contacts_governed_by_klints_net_ltv  = count(governed)   # new evidence field
total_overstatement                  = sum(overstatement of non-governed)

PASS  ⇔  linked > 0 AND contacts_over_delta == 0 AND contacts_refund_blind == 0
FAIL  ⇔  linked > 0 AND (contacts_over_delta > 0 OR contacts_refund_blind > 0)
```

UNKNOWN / NOT_CONNECTED paths unchanged.

### 3.4 Provenance / Fix after PASS

When PASS, mismatches **empty**.  
Fix Approve N/A on PASS (existing).  
Rollback `klints_net_ltv` + re-score → FAIL can return (correct).

### 3.5 Snapshot freshness + batch truncation (operator)

1. Approve writes Manago properties → **next DCS run must refresh Manago contacts** (standard pipeline). Stale snapshot without `klints_net_ltv` → PASS will not flip. Disclose “re-run DCS after Approve.”
2. WB-11 row cap (UPSERT `batch_max` / sample ≤50): one Approve may stamp only a subset. **Multiple Approve → re-score cycles** may be needed until every overstated linked contact is governed or naturally within band. Partial stamp → FAIL remains (decision #4) — honest, not a bug.

---

## 4. Executor

`evaluate_pt_04` keeps FAIL/PASS structure; consumes updated `product_truth` aggregates.

- Detail string on PASS may note governed count, e.g.  
  `Net truth OK on {linked} contacts ({governed} via klints_net_ltv).`  
- Evidence `value` includes `contacts_governed_by_klints_net_ltv`.  
- Do **not** change `formula_id` (`PT-04.ltv_overstatement.v1`) unless product asks; amount on PASS stays `0.0`.

WB-11 §3.4 mismatch union stays for **FAIL** samples (writeback still needs `side=net_overstatement`). Samples must be built from **non-governed** failing ∪ refund_blind only.

---

## 5. Mapping disclosure (copy only)

Update `PT-04.net_ltv.v1.json` `operator_disclosure` to something like:

```text
Prefer LE-09 PASS before stamping net LTV. Sets klints_net_ltv to Shopify net.
After Approve, re-run DCS — PT-04 PASSes when stamped net matches Shopify net on overstated contacts (repeat Approve if batch truncated).
```

Remove: “may not make PT-04 PASS”.

---

## 6. FE honesty

| Surface | Change |
|---------|--------|
| Fix trust / helper text for PT-04 | Prefer preview `operator_disclosure` (updated) |
| Success toast after Approve | Allowed: “Governed net stamped — re-run DCS to clear PT-04” — **not** “PT-04 PASS” until score returns PASS |
| Worklist | No special case; disappears when status PASS |

No new Fix chrome. Allowlist unchanged.

---

## 7. Tests

| Case | Expect |
|------|--------|
| No stamp; purchase over net > 2% | FAIL; contact in failing |
| Stamp == shopify_net (float or numeric string); purchase still over | contact governed; **PASS** if all linked contacts OK |
| Stamp within 2% of net | governed |
| Stamp wrong (far from net) | still FAIL on that contact |
| Mix: 2 governed + 1 unstamped over | FAIL; mismatch only unstamped |
| refund_blind true but stamp matches net | not counted in refund_blind; can PASS |
| Stamp matches; purchase **under** net > 2% | governed → not failing (decision #13) |
| Properties as `{name,value}` list bag | stamp still read |
| linked == 0 | UNKNOWN unchanged |
| `already_at_target` writeback skip | PASS on re-score if stamp present on contact |

Unit: `product_truth` + `evaluate_pt_04` (extend `test_consent_pt04_checks` and/or new `test_pt04_governed_net_ltv.py`).  
Keep WB-11 writeback transform/execute tests green **except** disclosure string asserts (flip those).

---

## 8. Verify scripts

**Must update (else CI red):**

| File | Change |
|------|--------|
| `scripts/verify_wb11_pt04_net_ltv_writeback.py` | Stop requiring `may not make PT-04 PASS`; accept WB-12 disclosure (re-run / PASS) |
| `dataruns/tests/test_writeback_wb11.py` | Same disclosure assert flip |
| `scripts/verify_wb12_pt04_pass_on_klints_net_ltv.py` | **New** — disclosure OK + optional pure governed helper smoke |

---

## 9. Docs / gap close

| Doc | Edit |
|-----|------|
| `docs/maheep/README.md` | WB-12 row + deploy note — **done at draft** |
| `PRD_WB_11_…` §3.3 / §13 | Point → WB-12 — **done at draft** |
| `docs/sahil/M3_DEMO_01_WORKING_GAPS.md` | G10 remaining → WB-12 — **draft pointer done**; mark closed when shipped |
| Possible sheet `evidence_note` | Optional: “re-score PASSes when stamp matches net (WB-12)” |

---

## 10. Branch / PR

- Branch: `feature/wb-12-pt04-pass-on-klints-net-ltv`  
- **Base:** tip with WB-11  
- Title: `feat(WB-12): PT-04 PASS when klints_net_ltv matches Shopify net`  
- PR body: link this PRD · “completes Automated writeback treating loop after WB-11 stamp” · “supersedes WB-11 may-not-PASS disclosure”

---

## 11. Acceptance checklist

- [x] `product_truth` reads `klints_net_ltv` from contact bags when building `manago_by_id`  
- [x] No `dataruns.writebacks` import from `product_truth`  
- [x] Governed rule (§3.2); aggregates exclude governed; `contacts_governed_by_klints_net_ltv` present  
- [x] `evaluate_pt_04` PASS when over_delta=0 and refund_blind=0 after exemption  
- [x] Absolute ≤0.01 **or** relative ≤ `PT04_DELTA_FAIL` match accepted  
- [x] Wrong/missing stamp does not falsely PASS  
- [x] Partial stamps leave FAIL with remaining mismatches  
- [x] Refund-blind cleared only when that contact is governed  
- [x] Understated purchase + matching stamp → not FAIL for that contact  
- [x] Mapping disclosure updated; no “may not make PT-04 PASS”  
- [x] WB-11 verify + `test_writeback_wb11` disclosure asserts flipped  
- [x] FE copy: re-run DCS to clear; no premature PASS toast  
- [x] Tests + `verify_wb12_…` green  
- [x] M3_DEMO G10 remaining honesty closed on ship  
- [x] No mapping op / adapter / LE-09 chain changes  

---

## 12. Explicitly not in this PR

- Changing writeback `detail_set` fields or caps  
- `event_correct` / rewriting PURCHASE values  
- Changing `PT04_DELTA_FAIL` from 2%  
- Requiring LE-09 PASS to allow PT-04 PASS  
- Demo bypass flag changes  
- Auto-Approve of remaining truncated rows  

---

## 13. Code reference map

| Path | Role |
|------|------|
| `dataruns/dcs/product_truth.py` | **Primary** — capture stamp + governed exemption |
| `dataruns/dcs/executors/product.py` | `evaluate_pt_04` PASS/FAIL + evidence counts |
| `dataruns/dcs/segment_join.py` | Bag-iteration pattern to copy/reuse (not writebacks) |
| `dataruns/writebacks/mappings/PT-04.net_ltv.v1.json` | Disclosure copy only |
| `scripts/verify_wb11_pt04_net_ltv_writeback.py` | Flip disclosure assert |
| `dataruns/tests/test_writeback_wb11.py` | Flip disclosure assert |
| FE `src/lib/writebacks.ts` / Fix helpers | Toast / helper honesty |
| `docs/maheep/PRD_WB_11_…` | Parent stamp PRD |

---

## 14. Decision log

| # | Question | Answer |
|---|----------|--------|
| 1 | Stamp clears check? | **Yes after WB-12** on re-score when stamp ≈ net (supersedes WB-11 #12) |
| 2 | Compare stamp to what? | **Shopify net** (same as write value) |
| 3 | Ignore purchase when governed? | **Yes** for FAIL counts (over or under) |
| 4 | Absolute tolerance? | **0.01** in addition to 2% relative |
| 5 | New mapping? | **No** — disclosure only |
| 6 | LE-09 required? | **Prefer**, not hard gate |
| 7 | Closes G10 remaining? | **Yes** when shipped |
| 8 | Where is stamp read? | Manago contact bags in `product_truth` (not writebacks import) |
| 9 | Truncated batch? | Multi-cycle Approve + re-score until all governed / in band |
