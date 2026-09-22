# PRD-WB-10 — LE-09 return / cancellation event writeback

**Status:** Ready for implementation — **P0 (M2 — Catalogue Automated writeback)** · **impl landed (WB-10)**  
**Owner track:** Sahil — **BE primary · FE Approve allowlist only**  
**Surfaces:** Fix `/fix` Approve · Settings Allow writebacks · `WritebackAllowedCheck` · registry / mapping · possible sheet · Activity/audit  
**Milestone:** M2 Activation & Blueprint (T2) — Lifecycle depth after WB-08/09  
**Depends on:** WB-03…WB-09 · FE-08/09 · POLISH-01 · DCS `evaluate_le_09` + `lifecycle_join` live  
**PRD path:** `docs/maheep/` (writeback series numbering only — **owner is Sahil**)  
**Parallel with:** Maheep WB-08/09 stack if unmerged — shares `dataruns/writebacks/**`; coordinate branch base  
**Contract SoT:** Catalogue Automated writeback for LE-09; Writeback + Lifecycle live  
**Pack SoT:**  
- `Klints_Spec_InitialDataConsistencyCheck_v1.4.1` sheet **02 Check Catalogue** row **LE-09**  
- sheet **09 MVP1 Check Scope** (Lifecycle · SCORED · MVP1-A)  
- `docs/dcs_scoring/CHECK_MASTER_42.md`  
- Manago Execution Capability Matrix · `RESTV2.EVENT.INGEST` (CONFIRMED_LIVE)  
- Excel Suggested Fix: *Build the returns pipe: RETURN events via addContactExtEvent with externalId=order ID and value=refund amount*  
**Out of scope:**  
- PT-04 `klints_net_ltv` (next wave after LE-09)  
- ERP credit-note cross-check (pack “Integration” half — not Fix Approve)  
- Shopify Order / refund writers  
- Changing LE-09 DCS scoring thresholds or executor status bands (mapping-only unless blocked)  
- Turning global `WRITEBACKS_ENABLED=True` outside Settings gate  
- New adapter protocols beyond existing `event_ingest`  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-10 — LE-09 return/cancellation event Automated writeback.

Read:
- docs/maheep/PRD_WB_10_LE09_RETURN_EVENT_WRITEBACK.md (this file)
- docs/maheep/PRD_WB_08_CATALOGUE_WAVE2_SP01_LE01.md (§5 LE-01 pattern)
- docs/maheep/WRITEBACK_SURFACE_MATRIX.md
- dataruns/dcs/executors/lifecycle.py (evaluate_le_09)
- dataruns/dcs/lifecycle_join.py (refund_cancel + return_coverage)
- dataruns/writebacks/mappings/LE-01.event_backfill.v1.json
- dataruns/writebacks/transform.py (_le01_evidence_rows / _event_ingest_payload)
- dataruns/writebacks/adapters/manago.py (event_ingest)
- FE: src/lib/writebacks.ts WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS

Ship:
1. New mapping LE-09.event_backfill.v1.json — event_ingest RETURN/CANCELLATION (§4).
2. Transform: match side=shopify_only_return; enrich email/contactId/amount/event_type (§5).
3. Enable registry + seed WritebackAllowedCheck LE-09 (§6).
4. Possible sheet + SURFACE matrix + FE allowlist (§7–8).
5. Irreversible disclosure + limited rollback honesty (same as LE-01) (§4.3).
6. Tests + verify script (§10). No Loom required.

Do NOT ship PT-04 in this PR.
Do NOT write manago_only_return rows (backfill Shopify→Manago only).
Do NOT touch handoff / Studio / QA / CAP.
Acceptance: §12.
```

---

## 1. Why (simple)

| Today | Gap |
|-------|-----|
| LE-09 **detects** Shopify refunds/cancels missing Manago RETURN/CANCELLATION | Catalogue Fix Type = **Integration + Automated writeback** — **no mapping** |
| LE-01 already backfills **PURCHASE** via `event_ingest` | Same adapter can backfill RETURN/CANCELLATION; evidence side differs |
| Pack P0 · Critical · unlocks PT-04 / VIP / churn honesty after re-score | Manual REST only (easy-fix JSON path) — not Fix Approve |

**WB-10** ships Fix Approve for LE-09 so a tenant can **catalogue FAIL → backfill return events → re-score**, without ops REST runbooks.

```text
DCS LE-09 FAIL (shopify_only_return gaps)
  → Fix Preview (event_ingest RETURN|CANCELLATION intents)
  → Approve (Settings Allow writebacks ON + irreversible disclosure)
  → Manago batchAddContactExtEvent
  → Re-run DCS → LE-09 PASS (when gaps cleared)
  → Unlocks PT-04 / money-truth follow-ons
```

---

## 2. Product decisions (locked)

| # | Decision | Lock |
|---|----------|------|
| 1 | Ship LE-09 only (not PT-04) | **Yes** |
| 2 | Reuse Manago `event_ingest` (T5) — no new op_kind | **Yes** |
| 3 | Write **Shopify → Manago** gaps only (`shopify_only_return`) | **Yes** |
| 4 | Ignore `manago_only_return` (no delete / no reverse invent) | **Yes** |
| 5 | `irreversible: true`; sheet rollback = **limited**; runtime `event_ingest` + `tagged_backfill_delete` → **`rollback_not_supported`** (same as LE-01) | **Yes** |
| 6 | `requires_consent_namespace_clean: false` | **Yes** (match LE-01; SP-07 gate is separate) |
| 7 | Event type from Shopify row: refunded → **RETURN**; cancelled → **CANCELLATION** | **Yes** |
| 8 | Ambiguous / unknown → default **RETURN** | **Yes** (matches easy-fix ops) |
| 9 | Do not change `evaluate_le_09` status logic | **Yes** — mapping + transform only |
| 10 | FE = allowlist `LE-09` only (reuse irreversible UI) | **Yes** |
| 11 | Value = Shopify order `total_price` / Order.amount (DCS `amount_gross`) — **not** partial-refund line sum | **Yes** (parity with LE-09 join) |
| 12 | No event `date` / `currency` in payload (LE-01 parity); join is `externalId` | **Yes** |
| 13 | No contact `klints_backfill` stamp on `event_ingest` (Excel wording ≠ adapter; same as LE-01) | **Yes** |

**Lane wall:**

```text
Sahil WB-10   =  LE-09 mapping + transform + allowlist + FE Approve list
Do not regress  =  live writebacks (CI-01 / CC-03 / LE-01 / SP-07 / WB-SHOP-01)
Out of this PR  =  Studio / HO / QA / CAP unless required for LE-09 Fix path
```

---

## 3. Excel / executor contract (do not invent)

### 3.1 Catalogue (sheet 02)

| Field | Value |
|-------|--------|
| Check | Returns and cancellations reflected |
| Surfaces | Shopify refunds / `cancelled_at` vs Manago External Events `RETURN` / `CANCELLATION` |
| Join | `externalId` = Shopify `orders.id` |
| Suggested Fix | RETURN via `addContactExtEvent`; `externalId`=order ID; `value`=refund amount; historical backfill |
| Fix Type | Integration build + **Automated writeback (approved)** |
| Fix Owner | Klints (automated) |
| Template | **T5** Event backfill |
| Priority | **P0** |
| Rollback note | Backfilled events carry permanence; state approval clearly |

### 3.2 Live executor evidence (`evaluate_le_09`)

Mismatch rows today:

```json
{ "side": "shopify_only_return", "order.id": "<shopify_order_id>" }
{ "side": "manago_only_return", "order.id": "<id>" }
```

**Critical:** LE-01 match const is `shopify_only`. LE-09 match const is **`shopify_only_return`**. Do not reuse LE-01 `match.const` by mistake.

Aggregate FAIL when Shopify has refunds but Manago return stream is empty still exposes `shopify_only_returns` in coverage → same mismatch sides after sample truncate (`LE_GAP_SAMPLE` / `LE_MISMATCH_SAMPLE` = **50**). Counts in coverage stay full; **writeback only sees the sampled mismatch rows** unless a later PR raises the sample or re-runs after partial backfill.

### 3.3 When Fix preview is empty (honest — not a bug)

| LE-09 outcome | Actionable `shopify_only_return` rows? | Fix Approve |
|---------------|----------------------------------------|-------------|
| FAIL — Shopify returns, Manago stream empty / id gaps | **Yes** (up to sample 50) | Preview intents |
| FAIL — **only** `manago_only_return` | **No** (by product lock) | Preview **0** — Download evidence |
| WARN — ids matched, value delta only | **No** | Preview **0** — not a backfill case |
| PASS | **No** | N/A |

### 3.4 Adapter already live

`ManagoWriteAdapter` `event_ingest` → `batchAddContactExtEvent` requires `externalId` + (`email` or `contactId`).  
`_event_ingest_payload` already accepts `event_type` (defaults `PURCHASE`).  
`rollback_strategy.py`: `event_ingest` + `tagged_backfill_delete` → **`rollback_not_supported`** (LE-01 same).

---

## 4. Mapping — `LE-09.event_backfill.v1.json`

### 4.1 Target shape

Mirror LE-01 with return-stream fields:

```json
{
  "schema_version": "1.0.0",
  "check_id": "LE-09",
  "template_id": "T5",
  "title": "Return / cancellation event backfill",
  "enabled": true,
  "approval_tier": "batch",
  "requires_consent_namespace_clean": false,
  "irreversible": true,
  "operator_disclosure": "Bulk RETURN/CANCELLATION event backfill may not be fully reversible. Rollback best-effort only.",
  "rollback": { "strategy": "tagged_backfill_delete" },
  "operations": [
    {
      "operation_id": "manago.event_ingest.return_cancel",
      "op_kind": "event_ingest",
      "target": "manago",
      "namespace": "native",
      "capability_id": "RESTV2.EVENT.INGEST",
      "entity_type": "event",
      "from_evidence": {
        "match": { "path": "side", "const": "shopify_only_return" },
        "entity_key": { "path": "order.id" },
        "fields": {
          "order_id": { "path": "order.id" },
          "email": { "path": "person.email" },
          "contact_id": { "path": "manago_contact_id" },
          "value": { "path": "amount_gross" },
          "event_type": { "path": "event_type" }
        }
      },
      "guards": ["entity_key_required"]
    }
  ]
}
```

### 4.2 Registry

```json
"LE-09": {
  "file": "LE-09.event_backfill.v1.json",
  "enabled": true,
  "template_id": "T5"
}
```

### 4.3 Irreversible honesty

Same rules as WB-08 §5.4 / live LE-01:

- Preview/API expose `irreversible: true` + `operator_disclosure`
- Fix Approve shows disclosure before write
- Rollback button: **hide or disabled** — runtime returns `rollback_not_supported` for `event_ingest` (do not claim best-effort delete works)
- Possible sheet keeps `rollback_possible_today=limited` (honesty = not fully reversible)
- Never toast “Fully reversed” / “Rolled back”

---

## 5. Transform — evidence bind + enrich

### 5.1 Worklist bind

Add `LE-09` branch beside LE-01 in `evidence_rows_for_check` / equivalent:

```text
elif normalized == "LE-09":
    rows = _le09_evidence_rows(...)
```

### 5.2 `_le09_evidence_rows`

| Rule | Behavior |
|------|----------|
| Match | `_evidence_side(row) == "shopify_only_return"` only |
| Skip | `manago_only_return`, aggregate-only rows without order id |
| Enrich | Flatten nested worklist `value` (same as LE-01) |
| Resolve | From Shopify `Order` (+ raw refund/cancel when needed): `person.email`, `amount_gross`, `manago_contact_id`, **`event_type`** |
| Cap | Honor pipeline `max_rows` / UPSERT batch_max; disclose truncation like SP-07/LE-01. **Also** DCS sample caps gaps at 50 — one Approve may not clear a large LE-09 FAIL; re-run DCS and Approve again |
| Empty / non-actionable worklist | Prefer **no sandbox** by default (live FAIL only). Optional sandbox from refund/cancel Shopify orders **only if** Settings execute ON **and** product asks — default **off** (stricter than LE-01) |
| Prefer enrich source | Shopify `Order` (+ contact); if status/financial thin, fall back to latest ConnectorSnapshot raw order row / lifecycle `shopify_refund_cancel_orders_detail` when present |

### 5.3 `event_type` enrichment (locked)

| Shopify signal | `event_type` |
|----------------|--------------|
| `financial_status` in refund set **or** Order status refunded | `RETURN` |
| `cancelled_at` set **or** cancel financial / Order failed-as-cancel | `CANCELLATION` |
| Both | Prefer **CANCELLATION** if cancelled_at present, else **RETURN** |
| Unresolvable | `RETURN` |

Payload after bind:

```text
contactExtEventType = event_type
externalId          = order.id
value               = amount_gross (refund/order total)
email | contactId   = resolved identity
```

### 5.4 Skip rows without identity

If enrich cannot resolve email **and** Manago contactId → drop intent / fail row with honest reason (`missing_contact_reference`) — do **not** invent `@….invalid` emails (WB-09 lesson).

---

## 6. Allowlist + migration

New data migration after `0037_writeback_allowed_sp07`:

```text
get_or_create check_id=LE-09, enabled=True, note="PRD-WB-10 LE-09 return event backfill"
```

Do **not** remove CI-01 / CC-03 / WB-SHOP-01 / LE-01 / SP-07.  
Do **not** seed PT-04 / CI-03 / LE-04 / SP-01.

Execute formula unchanged (WB-03…07).

---

## 7. Possible sheet + matrix

### 7.1 CSV (`WRITEBACK_POSSIBLE_NOT_SHEET.csv`)

Add row:

| Column | Value |
|--------|--------|
| `check_id` | `LE-09` |
| `check_name` | Returns and cancellations reflected |
| `pack_fix_type` | Integration build + Automated writeback (approved) |
| `pack_fix_owner` | Klints (automated) |
| `pack_suggested_fix_summary` | Backfill missing Manago RETURN/CANCELLATION events from Shopify refunds/cancels |
| `platform` / `op_kind` | `manago` / `event_ingest` |
| `entity` / `field_or_key` | `event` / `RETURN\|CANCELLATION` |
| `write_possible_today` | `yes` |
| `rollback_possible_today` | `limited` |
| `mapping_file` | `LE-09.event_backfill.v1.json` |
| `registry_enabled` | `true` |
| `blocker` | empty |
| `evidence_note` | event_ingest RETURN/CANCELLATION; side=shopify_only_return; irreversible disclosure; Settings gated |
| `last_verified` | ship date |

### 7.2 `WRITEBACK_SURFACE_MATRIX.md`

- Extend **Transaction / purchase event** row (or add sibling): **LE-09 enabled** — RETURN/CANCELLATION via same `event_ingest`; irreversible; limited rollback.  
- Enabled mappings table: add **LE-09**.

### 7.3 `PRD_WB_02` pending list

When shipping, remove `LE-09` from WB-02 §3.2 “Approve OFF until built” list (same note style as LE-01 / SP-07).

---

## 8. Frontend (minimal)

| File | Change |
|------|--------|
| `src/lib/writebacks.ts` | Add **`LE-09`** to `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` |
| same | Reuse existing irreversible disclosure helpers (no new modal) |
| `scripts/verify-wb02-frontend.mjs` | Assert LE-09 allowlisted |

Optional copy: Settings / honesty blurb may mention “Event ingest (LE-01 / LE-09) has limited rollback.”

No new Fix route or chrome.

---

## 9. Reuse existing harden (do not regress)

| PRD | Must still hold |
|-----|-----------------|
| WB-03 | Settings default OFF; Admin toggle |
| WB-04 / WB-07 | Once-per-run + claim before adapter I/O |
| WB-06 | Status / Written restore |
| WB-07 | Mask entity_key / no exc leaks |
| WB-09 | SP-07 gate for CC-* still intact; LE-09 does not self-require namespace clean |
| POLISH-01 | Audit append-only |

Deep-link: `/fix?issue=LE-09`.

---

## 10. Tests + verify

### 10.1 Backend

| Case | Expect |
|------|--------|
| Registry loads LE-09 enabled | |
| Preview with `side=shopify_only_return` | ≥1 `event_ingest` intent; `contactExtEventType` in {RETURN, CANCELLATION} |
| Preview ignores `manago_only_return` | 0 intents from those rows |
| Match does not fire on LE-01 `shopify_only` | |
| Enrich supplies email/value/event_type from Order | |
| Missing identity → validation fail, no fake email | |
| Settings OFF → execute denied | |
| Allowlist after migrate includes LE-09 | |
| `irreversible` true in preview payload | |
| Concurrent double Approve → 409 | |
| Rollback path returns not supported / does not claim undo | |
| WARN value-parity only → 0 intents | |
| manago_only-only FAIL → 0 intents | |

### 10.2 Verify script

```text
scripts/verify_wb10_le09_return_writeback.py
```

Checks: registry · mapping enabled · allowlist · possible sheet · FE allowlist string if checked from monorepo · side const `shopify_only_return`.

### 10.3 Staging smoke (optional)

Settings ON → LE-09 FAIL → Preview shows RETURN/CANCELLATION → Approve → re-run DCS → LE-09 improves/PASS.  
No Loom required.

---

## 11. Branch / PR

- Branch: `feature/wb-10-le09-return-writeback`  
- **Base:** current unmerged tip that already has WB-08 + WB-09 (`feature/wb-09-sp07-namespace-clean` or stacked equivalent) — **not** bare `main` if those PRs are unmerged  
- BE title: `feat(WB-10): LE-09 RETURN/CANCELLATION event writeback`  
- FE title (if split): `feat(WB-10): enable LE-09 Fix Approve`  
- PR body: link this PRD · “same T5 path as LE-01; side=shopify_only_return; irreversible honesty”  
- Merge: BE (mapping + transform + allowlist) first, then FE allowlist if separate  

---

## 12. Acceptance checklist

- [x] Mapping `LE-09.event_backfill.v1.json` enabled; registry entry live  
- [x] Match const **`shopify_only_return`** (not `shopify_only`)  
- [x] Enrich resolves email / contactId / amount / event_type without fake emails  
- [x] `manago_only_return` never written  
- [x] `WritebackAllowedCheck` seeds LE-09; PT-04 still off  
- [x] Possible sheet + SURFACE matrix updated  
- [x] FE Approve allowlist includes LE-09  
- [x] Irreversible disclosure visible before Approve  
- [x] Settings OFF → no execute  
- [x] Settings ON → Approve writes via existing Manago `event_ingest`  
- [x] Rollback honesty = limited / `rollback_not_supported` for event_ingest (same as LE-01)  
- [x] WB-04/07 once-per-run + claim-before-write still hold  
- [x] Tests + `verify_wb10_le09_return_writeback.py` green  
- [x] No handoff / Studio / QA / CAP edits  

---

## 13. Explicitly not in this PR

- PT-04 `klints_net_ltv` / net vs gross writeback  
- Deleting Manago-only return events  
- Shopify refund/order mutation  
- Changing LE-09 FAIL thresholds or revenue formula ids  
- Claiming ERP integration half of the pack Fix Type  
- Versioned Klints prefix (WB-09B)  

---

## 14. Code reference map

| Path | Role |
|------|------|
| `dataruns/dcs/lifecycle_join.py` | Shopify refund/cancel + return coverage ids |
| `dataruns/dcs/executors/lifecycle.py` | `evaluate_le_09` mismatch sides |
| `dataruns/writebacks/mappings/LE-01.event_backfill.v1.json` | Pattern to clone |
| `dataruns/writebacks/mappings/LE-09.event_backfill.v1.json` | **New** |
| `dataruns/writebacks/mappings/registry.json` | Register LE-09 |
| `dataruns/writebacks/transform.py` | `_le09_evidence_rows` + enrich |
| `dataruns/writebacks/adapters/manago.py` | `event_ingest` (unchanged protocol) |
| `dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv` | Honesty sheet |
| FE `src/lib/writebacks.ts` | Approve allowlist |
| **Avoid regressing:** existing allowlisted writebacks · HO/Studio/QA unless LE-09 needs them | — |

---

## 15. Traceability

| Field | Value |
|-------|--------|
| Milestone | M2 — Catalogue Automated writeback |
| Pack | Catalogue LE-09 P0 T5 |
| Parents | WB-01…09 · DCS-04 LE-09 · DCS-08 revenue (consume only) |
| Unblocks | PT-04 AW wave · VIP / churn honesty after re-score |
| Next | **WB-11** PT-04 AW · remaining catalogue AW as product prioritizes |
| Independent of | Handoff · Studio · Track B · DCS-09/10 |

---

## 16. Open questions (resolved — do not reopen in impl)

| # | Question | Decision |
|---|----------|----------|
| 1 | PURCHASE vs RETURN ops? | **Separate mapping**; same `event_ingest` |
| 2 | Match side string? | **`shopify_only_return`** (executor SoT) |
| 3 | Write manago-only gaps? | **No** |
| 4 | Sandbox when PASS? | **Default off** (live FAIL preferred) |
| 5 | Namespace preflight? | **`requires_consent_namespace_clean: false`** |
| 6 | Ship PT-04 together? | **No** — next PRD |
| 7 | Change DCS executor? | **No** unless evidence paths unblock mapping |
| 8 | Partial refund amount? | Use DCS `amount_gross` (`total_price`) — do not invent refund-line math |
| 9 | Event date on payload? | **Omit** (LE-01 parity); optional later |
| 10 | Raise LE_GAP_SAMPLE? | **No** in WB-10 — re-Approve after re-score if gaps remain |
