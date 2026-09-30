# PRD-WB-16 — CI-03 contact merge (merge plan + gated safe-delete)

**Status:** **Phase A shipped** — P0 M2 Catalogue · Sahil  

**Owner track:** Sahil — **BE primary · FE Preview/Download + honesty** (pack Fix Owner = **CRM manager** — not Klints automated)  
**Surfaces:** Fix `/fix` Preview · FE-12 Download · Settings Allow writebacks · registry / mapping · possible sheet · Activity/audit · **DCS identity mismatches (new)** · Manago `batchDelete` (**CONTACT_ID only**, Phase B)  
**Milestone:** M2 Activation & Blueprint — Customer Identity uniqueness  
**Depends on:** WB-03…WB-15 · FE-08/09/12 · live `evaluate_ci_03` + `identity_join` · CI-05 shipped (reused → this PR)  
**PRD path:** `docs/maheep/`  
**Contract SoT:** Catalogue Automated writeback for CI-03; Writeback + Identity  
**Pack SoT:**  
- `Klints_Spec_InitialDataConsistencyCheck_v1.4.1` sheet **02 Check Catalogue** row **CI-03** (headers row 5 — full column map §3.1)  
- sheet **01 Overview** — **T3 Contact merge** covers **CI-03** (“Propose merge plan / survivor”)  
- sheet **09 MVP1 Check Scope** (Identity · SCORED · MVP1-A · weight 4)  
- `docs/dcs_scoring/CHECK_MASTER_42.md` row CI-03 — *Duplicate contacts in Manago* · RC-04, RC-08 · **High**  
- WB-01 §1b.2 — T3 → `contact_merge`; stub_factory T3 `approval_tier=individual`, `irreversible=true`  
- WB-01 §10.1 — Consent / identity-key / **merge → `individual`**; irreversible ops require `operator_disclosure`; Fix Owner ≠ Klints → **preview-only execute** unless override  
- **MVP1 · P0 next list #6** — after LE-09 → LE-05 → LE-02 → PT-04 → CI-05 (all live) → **CI-03** → CC-01/02…  
- WB-02 §3.2 — CI-03 today on “Approve OFF until built” — this PR **does not** enable silent auto-merge Approve  
- WB-15 — reused `externalId` clusters deferred here; CI-05 Preview 0 on reused-only estates  

**Out of scope:**  
- Native Manago “merge contacts” API (does **not** exist — do not invent)  
- Blind `api/contact/delete` by **email** (destroys both sides of an email dup)  
- Auto-deleting losers that still hold PURCHASE / external events without migration  
- Changing CI-03 FAIL/WARN bands (`CI03_WARN_DUP_RATE` 0.01 / `CI03_FAIL_DUP_RATE` 0.02 / `cluster_count > 10`) **except** fixing capped-list undercount for scoring honesty (§3.2)  
- Phone-only soft duplicates as auto-delete candidates (quarantine)  
- Shopify Customer writers · ERP · Handoff / Studio / QA / CAP product work  
- Rewriting CI-05 dangling keys  
- Full estate wipe + Shopify re-export playbooks (ops runbook only; not writeback)  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-16 — CI-03 contact merge (merge plan + gated safe-delete).

Read:
- docs/maheep/PRD_WB_16_CI03_CONTACT_MERGE_WRITEBACK.md (this file)
- docs/maheep/PRD_WB_15_CI05_IDENTITY_KEY_REPAIR_WRITEBACK.md (§2 reused → CI-03)
- docs/maheep/PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md (T3 contact_merge; irreversible; fix_owner gate)
- exports/dcs_fresh_import_raw/dcs_486_*/DCS_486_contact_ci_investigation.md
- exports/dcs_fresh_import_raw/dcs_482_*/analysis/DCS_482_contact_delete_safety_audit.md
- dataruns/dcs/executors/identity.py (evaluate_ci_03)
- dataruns/dcs/identity_join.py (duplicate_clusters)
- dataruns/writebacks/mappings/CI-03.contact_merge.v1.json (stub)
- Manago docs: api/contact/batchDelete (addresseeType=CONTACT_ID) — NO merge endpoint

Ship in two hard-gated phases (same PRD; Phase B cannot ship without Phase A + Loom).

CRITICAL — today these crash or silently no-op if ignored (§5.0):
- transform.py has NO contact_merge payload branch → ValueError on Preview once ops exist
- manago.dry_run rejects capability_id=null → capability_not_confirmed
- guards.py unknown guards are NO-OPs (plan_only string alone does nothing)
- pipeline.py does NOT read execute_mode today — you MUST wire it
- identity_join clusters lack per-UUID event counts — compute in emit helper (§3.4.1)
- Order.contact is CASCADE — never hard-delete Contact rows without tombstone field

PHASE A (MVP1 must-ship — “propose merge plan — not auto-merged”):
1. identity_join: uncapped duplicate_cluster_counts + duplicate_extra_contacts_total; keep sample [:50].
2. identity.py evaluate_ci_03: score from uncapped totals; attach provenance merge_candidate via helper (§3.3–3.4).
3. NEW helper (prefer identity_join or identity.py): per-UUID purchase/event counts from Order(source=manago_ai) + optional raw event cache (§3.4.1).
4. Mapping CI-03.contact_merge.v1.json — execute_mode=plan_only; approval_tier=individual; irreversible; rollback.strategy=none; capability_id omitted/null on plan op (§4).
5. pipeline.py: if mapping.execute_mode==plan_only and mode in (execute,sandbox_execute) → blocked_reason=ci03_plan_only (do not mutate).
6. transform.py: elif CI-03 → _ci03_evidence_rows; _build_payload_and_state contact_merge → plan payload (no Manago call).
7. manago.dry_run: if intent.payload.mode==plan OR mapping execute_mode plan_only → skip capability gate; status ready/preview (never error capability_not_confirmed).
8. guards.py: add plan_only (no-op pass) AND safety_class_safe_delete / cluster_size_eq_2 / loser_contact_id_required for Phase B.
9. FE-12: merge_candidate fields must appear inside evidence value JSON (existing CSV `value` column) — optional column extend later (§8).
10. Possible sheet + SURFACE + FE honesty (§7–8). Registry enabled; WritebackAllowedCheck NOT seeded; FE allowlist NOT added.
11. Confirm CheckMaster.fix_owner for CI-03 is "CRM manager" (seed from catalogue Excel via seed_dcs_master) — mapping.fix_owner is documentary only.
12. Tests + verify_wb16_ci03_contact_merge.py Phase A.

PHASE B (gated — only after §5.2 Loom CONFIRMED_LIVE):
13. capabilities.json RESTV2.CONTACT.BATCH_DELETE → CONFIRMED_LIVE after Loom.
14. manago_transport.batch_delete_contacts_by_id; adapter contact_merge execute; add contact_merge to _IMPLEMENTED_OP_KINDS.
15. Contact.excluded (+ excluded_at) soft tombstone; identity_join skips excluded; NEVER hard-delete Contact (Order CASCADE).
16. FE allowlist + WritebackAllowedCheck only after product sign-off; note sandbox bypass of fix_owner gate (§9).
17. MIGRATE_THEN_DELETE helper optional after SAFE works.

Do NOT use api/contact/delete by email.
Do NOT invent a Manago merge endpoint.
Do NOT auto-delete HIGH_LOSS / MIGRATE classes without event migration.
Do NOT enable FE WRITEBACK_APPROVE_EXECUTABLE for CI-03 in Phase A.
Do NOT change CI-03 rate thresholds except uncapped honesty.
Do NOT invent sandbox merge_candidate rows.
Do NOT hard-delete Contact rows (Order.on_delete=CASCADE).
Acceptance: §12.
```

---

## 1. Why (simple)

| Before WB-16 | After WB-16 Phase A | After Phase B (gated) |
|--------------|---------------------|------------------------|
| CI-03 FAILs on duplicate clusters; evidence aggregate-only | Per-cluster **merge plan** in provenance + Fix Preview + Download | Safe losers deleted by **contactId** in Manago |
| CI-05 reused-only estates → CI-05 Preview 0 (honest) | Operator sees **which** UUIDs to keep/remove | Reused clusters shrink → CI-05 can PASS after re-score |
| Stub mapping `enabled=false`, empty ops | Plan mapping live; **not auto-merged** | Irreversible delete with disclosure |
| Cap artifact understates duplicate rate | Uncapped totals for score + sample for plan | Same |

```text
CI-03 FAIL / WARN
  → Phase A: Fix Preview shows merge_candidate rows (survivor / loser / safety_class)
       → Download Excel for CRM
       → Approve execute DENIED (plan_only + CRM manager fix_owner)
  → CRM merges in Manago UI  OR  Phase B Approve on SAFE_DELETE only
  → Re-ingest / tombstone Klints Contact rows for losers
  → Re-run DCS → CI-03 rate↓; CI-05 reused↓; CI-01 manago count↓
```

### 1.1 Live proof (why this PR exists)

DCS **486** / localhost-style estates:

| Fact | Value |
|------|-------|
| Manago Contact DB | ~403 |
| Shopify customers | ~201 |
| Uncapped email / phone / link_key dup clusters | **~201 each** (snapshot caps at 50 → evidence shows ≤150 clusters) |
| CI-05 reused | ~201 (evidence sample 50) |
| PURCHASE events on **newer** UUID | **76** clusters (`HIGH_LOSS_IF_DELETE_NEWER`) |
| Older UUID in fresh Manago raw | **0 / 201** |

**Deleting “newer” without migration drops the live PURCHASE spine.**  
**Deleting by email when both share email is catastrophic.**  
**“Keep oldest” is wrong for this estate.**

---

## 2. Product decisions (locked)

| # | Decision | Lock |
|---|----------|------|
| 1 | Catalogue Suggested Fix = **propose merge plan — not auto-merged** | **Yes** — Phase A is the MVP1 deliverable |
| 2 | Pack Fix Owner = **CRM manager** | **Yes** — CheckMaster SoT (`seed_dcs_master` from Excel). Mapping `fix_owner` is documentary only. **Hard execute stops in Phase A:** `execute_mode=plan_only` (new pipeline wire) + FE allowlist off + no WritebackAllowedCheck. Do **not** rely on `fix_owner_not_klints_automated` alone — sandbox ON bypasses that gate (`pipeline.py` `preview_only_owner` requires `not is_writeback_execute_enabled`) |
| 3 | Eng owner = **Sahil**; automated mutate owner stays CRM unless product explicitly flips Fix Owner | **Yes** |
| 4 | Manago has **no** merge API | **Yes** — compose plan + optional `batchDelete` |
| 5 | Delete transport = **`api/contact/batchDelete`** with `addresseeType=CONTACT_ID` | **Yes** — Phase B only |
| 6 | Forbidden = `api/contact/delete` by **email** for CI-03 | **Yes** — hard ban |
| 7 | `op_kind` remains **`contact_merge`** (plan + composed delete) | **Yes** — WB-01 T3 |
| 8 | `approval_tier` = **`individual`** | **Yes** — WB-01 merge rule; one cluster per Approve in Phase B |
| 9 | `irreversible` = **true**; rollback = **`none`** (not `restore_prior_field`) | **Yes** — stub was inconsistent; fix mapping. Ensure rollback schema accepts `none` (or omit strategy + document) |
| 10 | Phase A `execute_mode` = **`plan_only`** | **Yes** — **new mapping field**; must be **read in `pipeline.py`** (§5.0). Not enforced today |
| 10b | Phase A dry_run capability | Plan intents **skip** `capability_allows_execute` when `payload.mode=plan` / `execute_mode=plan_only` (§5.0) — else Preview errors |
| 10c | Transform `contact_merge` branch | **Must ship** in `_build_payload_and_state` or Preview raises `unsupported_op_kind` |
| 11 | Phase B execute only for `safety_class=SAFE_DELETE` | **Yes** |
| 12 | `MIGRATE_THEN_DELETE` / `QUARANTINE` / `UNSAFE` → Download only (or migrate-then-delete in Phase B+ after event re-ingest proves) | **Yes** |
| 13 | Survivor selection = **event-spine first** (not “always oldest”) | **Yes** — §3.4 |
| 14 | FE Approve allowlist for CI-03 | **Phase A: OFF** · **Phase B: ON only after Loom + product sign-off** |
| 15 | `requires_consent_namespace_clean: false` | **Yes** |
| 16 | **No sandbox invent** of merge rows | **Yes** |
| 17 | Sample cap for plan rows = **`CI_MISMATCH_SAMPLE` = 50** (stable order) | **Yes** — uncapped totals still used for scoring |
| 18 | Write priority cluster kind = **`externalId` (link_key) first**, then email, phone **quarantine** | **Yes** — clears CI-05 reused |
| 19 | Cluster size must be **exactly 2** for Phase B delete; size ≥3 → `QUARANTINE` | **Yes** |
| 20 | After Manago delete: **soft-tombstone** loser UUID on Klints `Contact` (`excluded` Boolean + `excluded_at`) | **Yes** — `Order.contact` is **CASCADE**; hard-delete Contact wipes orders. `identity_join` must skip `excluded=True` |
| 21 | Interaction with CI-05 | CI-03 clears **reused**; CI-05 still owns **missing** backfill. Prefer CI-03 when reused dominate |
| 22 | Interaction with CI-01 | Merging/deleting Manago dups shrinks manago_n toward Shopify — expected |
| 23 | Interaction with LE-* | Never delete the UUID that currently owns PURCHASE events without migration |
| 24 | Capability id Phase B = **`RESTV2.CONTACT.BATCH_DELETE`** | **Yes** — start `DISCOVERY_REQUIRED`; promote after sandbox Loom |
| 25 | Do **not** add CI-03 to `suppressFixProceedToStudio` | **Yes** |

### 2.1 Excel vs automation (honest)

| Catalogue text | WB-16 interpretation |
|----------------|----------------------|
| Fix Type = Automated writeback (approved) | Klints **automates the plan** (and Phase B safe-delete if signed off) |
| Suggested Fix = **not auto-merged** | Phase A must **not** silently merge/delete |
| Fix Owner = CRM manager | Execute gated; CRM acts on plan or Phase B override |

### 2.2 Lane wall

```text
Sahil WB-16 Phase A  =  DCS merge_candidate + plan Preview/Download + honesty
Sahil WB-16 Phase B  =  CONTACT_ID batchDelete SAFE only + Contact tombstone + FE Approve
Do not regress        =  CI-05 / CI-01 / LE-* / PT-04 live writebacks
Out of this PR        =  email-delete · invented merge API · phone auto-merge · estate wipe playbooks
```

---

## 3. Excel / executor contract (do not invent)

### 3.1 Catalogue (sheet 02) + CHECK_MASTER

Exact Excel CI-03 row (v1.4.1). **Verified in-repo sources:** `WRITEBACK_POSSIBLE_NOT_SHEET.csv` (Suggested Fix / Fix Type / Fix Owner), `CHECK_MASTER_42.md` (name / weight / RC / severity), WB-01 T3. Full sheet-02 column prose below is **reconstructed for implementers** — confirm against the xlsx when seeding; do not invent new Suggested Fix language.

| Column | Value | In-repo proof |
|--------|--------|----------------|
| Check ID | **CI-03** | CHECK_MASTER_42 · possible sheet |
| DCS Dimension | 01 Customer Identity | CHECK_MASTER_42 |
| Check Name | Duplicate contacts in Manago | CHECK_MASTER_42 · possible sheet |
| Entity | Contact | possible sheet entity |
| Systems Compared | Manago | CHECK_MASTER_42 |
| Check Type | Uniqueness | CHECK_MASTER_42 |
| Detection Logic | Duplicate Manago contacts sharing email / phone / externalId | Matches `evaluate_ci_03` + `identity_join.duplicate_clusters` |
| Manago Surface | contact | possible sheet |
| Inconsistency Type | Duplicate contacts | Derived from check name |
| Root Causes | RC-04, RC-08 | CHECK_MASTER_42 |
| Severity | **High** | CHECK_MASTER_42 |
| DCS Weight | High (numeric 4) | CHECK_MASTER_42 |
| Suggested Fix | **Propose duplicate-contact merge plan — not auto-merged** | possible sheet `pack_suggested_fix_summary` |
| Fix Type | **Automated writeback (approved)** | possible sheet |
| Fix Owner | **CRM manager** | possible sheet · CheckMaster help_text |
| Rollback Note | Merges / deletes **not reversible in bulk** | WB-01 irreversible catalogue note for CI-03 |
| Cadence | Initial + Recurring | CHECK_MASTER_42 |
| MVP1 Fix Blueprint | **Y** | MVP1 scope |
| Fix Template | **T3 Contact merge** | WB-01 · stub mapping |
| Build Priority | **P0** | MVP1 P0 list #6 |

CHECK_MASTER_42: RULE_BASED · SCORED · MVP1-A · weight 4 · High · RC-04, RC-08.

**Suggested Fix split (normative):**

| Part | Catalogue text | WB-16 |
|------|----------------|-------|
| **A** | Propose duplicate-contact merge plan | **Phase A — in scope** |
| **B** | not auto-merged | **Phase A — Execute off**; Phase B only SAFE + Loom |
| **C** | CRM executes / reviews | **Fix Owner gate** |

### 3.2 Executor SoT (`evaluate_ci_03`) — scoring honesty

```text
UNKNOWN        ⇔  missing identity / manago_n=0
NOT_CONNECTED  ⇔  Manago not connected
FAIL           ⇔  rate > 0.02 OR uncapped_cluster_count > 10
WARN           ⇔  rate > 0.01 OR uncapped_cluster_count > 0 (and not FAIL)
PASS           ⇔  else
```

Thresholds (do **not** change numeric bands):  
`CI03_WARN_DUP_RATE = 0.01`, `CI03_FAIL_DUP_RATE = 0.02`, cluster FAIL if `> 10`.

**Bug to fix (required):** today `duplicate_clusters` lists are **capped at 50** per kind before `evaluate_ci_03` computes `cluster_count` / `dup_contacts` / `rate`. That **understates** FAIL severity on large estates and misleads operators.

**Ship:**

1. `identity_join` stores:
   - `duplicate_clusters.{email,phone,externalId}` — sample lists **[:50]** (unchanged for evidence display)
   - **new** totals: `duplicate_cluster_counts`, `duplicate_extra_contacts_total` (uncapped)
2. `evaluate_ci_03` scores from **uncapped totals**, not `len(capped_list)`.
3. Evidence `identity.duplicate_contacts` includes both totals and capped samples.

### 3.3 Provenance mismatches (ship) — `merge_candidate`

Today: aggregate evidence only → **no** transform bind.  

**Emit on FAIL and WARN** (not PASS / NOT_CONNECTED). Cap actionable rows at 50.

```json
{
  "side": "merge_candidate",
  "cluster_kind": "externalId",
  "cluster_key": "<link_key or email or phone>",
  "cluster_size": 2,
  "survivor_manago_id": "<uuid>",
  "loser_manago_ids": ["<uuid>"],
  "person.email": "<normalized email or empty>",
  "survivor_created_at": "<iso>",
  "loser_created_at": "<iso>",
  "survivor_event_count": 3,
  "loser_event_count": 0,
  "survivor_purchase_count": 2,
  "loser_purchase_count": 0,
  "safety_class": "SAFE_DELETE",
  "safety_reason": "loser_events_0_survivor_holds_link_key",
  "link_key": "<shopify customers.id or empty>",
  "ci05_reused": true
}
```

**Emit priority (stable):**

1. `cluster_kind=externalId` (reused link_key) — clears CI-05 driver  
2. `cluster_kind=email` where contacts do **not** already appear in an externalId merge row  
3. `cluster_kind=phone` → emit only as `safety_class=QUARANTINE` (never Phase B delete)

**Do not emit** invent rows when clusters empty.

Driver tags (optional honesty, non-writeable):

```json
{ "side": "driver", "driver": "duplicate_rate", "rate": 0.37 }
{ "side": "driver", "driver": "cluster_cap_note", "sample_cap": 50 }
```

### 3.4 Survivor / loser / safety_class (normative — no gaps)

For each cluster of Manago contact rows sharing a key:

#### Survivor selection (ordered)

1. Prefer contact with **max `purchase_count`** (Manago external PURCHASE / Klints order links — use same sources DCS-486 audit used).  
2. Else prefer max **any external event count**.  
3. Else prefer contact whose `link_key` equals Shopify `customers.id` for the shared email (when joinable).  
4. Else prefer **newest `created_at`** among contacts present in the latest Manago contact ingest window (if detectable).  
5. Else prefer **newest `created_at`**.  
6. Ties → lexicographically greater `external_id` (stable).

**Never** hard-code “always keep oldest” — DCS-482/486 proved oldest often has **0** window events.

#### 3.4.1 Event / purchase count data source (required — not on cluster dicts today)

`identity_join` cluster entries are only `{key, value, count}` today. Phase A **must** compute per-UUID stats when emitting `merge_candidate`:

| Metric | Primary source (ship) | Fallback |
|--------|----------------------|----------|
| `purchase_count` | `Order.objects.filter(company=…, source=manago_ai, contact__external_id=uuid).count()` (and/or status=paid) | 0 |
| `event_count` | Same Order count as proxy **or** count from latest Manago raw/ext-event cache if already loaded for the DCS run | If neither available → treat as **incomplete** → `safety_class=UNSAFE` (never SAFE_DELETE) |
| `created_at` | `Contact.created_at` for that Manago row | |
| Present in fresh ingest window | Optional: set membership from latest Manago contact import ids if available on run | Skip step 4 if unknown |

**Honesty rule:** If event visibility is incomplete, **do not** emit `SAFE_DELETE`. Prefer `UNSAFE` or `QUARANTINE` over false SAFE.

DCS-486 offline audits joined fresh raw PURCHASE `contactId` — implementers may reuse that pattern inside the DCS run if Order rows understate events; document which source was used in `safety_reason`.

#### Loser set

All other UUIDs in the cluster.

#### `safety_class`

| Class | Rule | Phase A | Phase B execute |
|-------|------|---------|-----------------|
| **SAFE_DELETE** | `cluster_size==2` AND loser `event_count==0` AND loser `purchase_count==0` AND survivor identified AND (for email clusters: emails equal) AND no conflicting distinct Shopify link_keys on survivor vs loser | Plan row | **Allowed** after Loom |
| **MIGRATE_THEN_DELETE** | loser has events/purchases OR class B from DCS audit | Plan row + migration steps in Download | **Denied** until migration helper succeeds in-job |
| **QUARANTINE** | size≥3 · phone-only · conflicting emails · conflicting non-empty link_keys that disagree · both sides have unique non-empty event sets that cannot be ranked · missing UUID | Plan row | **Denied** |
| **UNSAFE** | Any rule failure / incomplete event visibility | Plan row | **Denied** |

Phase B **MIGRATE_THEN_DELETE** path (optional same PR after SAFE works):

1. Re-ingest loser’s PURCHASE/RETURN events onto `survivor_manago_id` via existing `event_ingest` (idempotent externalId).  
2. Verify event counts on survivor.  
3. Then `batchDelete` loser by CONTACT_ID.  
4. If any step fails → stop; mark intent failed; **do not** delete.

### 3.5 Does Approve / CRM action clear CI-03 / CI-05?

| Action | CI-03 | CI-05 |
|--------|-------|-------|
| Phase A Preview/Download only | No status change | No |
| CRM merges in Manago + Klints DB still has losers | Still FAIL (DB accumulation) | reused may remain in DB |
| Manago losers deleted **and** Klints Contact tombstoned + re-score | Rate/clusters drop → WARN/PASS possible | reused↓ → can PASS if coverage OK |
| Phase B SAFE_DELETE sample (≤50) | Partial clear; re-Approve after re-score | Partial |

Toast (Phase B only): “Writeback applied · CI-03 · N merges · re-run DCS.”  
Do **not** toast PASS until score returns PASS.

### 3.6 When Fix preview is empty

| CI-03 outcome | Actionable `merge_candidate`? | Fix |
|---------------|-------------------------------|-----|
| FAIL/WARN with clusters | **Yes** (up to 50) | Preview plan rows |
| PASS / NOT_CONNECTED / UNKNOWN(no contacts) | **No** | N/A |
| FAIL but all clusters quarantined into non-sample | Possible 0 in sample — Download still exports uncapped totals + honesty | |

---

## 4. Mapping — `CI-03.contact_merge.v1.json`

### 4.1 Phase A target shape

```json
{
  "schema_version": "1.0.0",
  "check_id": "CI-03",
  "template_id": "T3",
  "title": "Contact merge plan (Manago duplicates)",
  "enabled": true,
  "approval_tier": "individual",
  "requires_consent_namespace_clean": false,
  "irreversible": true,
  "execute_mode": "plan_only",
  "fix_owner": "CRM manager",
  "operator_disclosure": "CI-03 proposes a duplicate-contact merge plan (survivor vs loser). Catalogue: not auto-merged. Fix Owner is CRM manager — Klints does not silently merge. Deletes are irreversible and must never use email-delete when contacts share an email. Phase A: Preview + Download only. Phase B (if enabled): only SAFE_DELETE losers via batchDelete CONTACT_ID after sandbox Loom. Losers with PURCHASE/events require migration first. Re-run DCS after Manago+DB cleanup. Reused externalId clusters also drive CI-05 FAIL until resolved here.",
  "rollback": { "strategy": "none" },
  "operations": [
    {
      "operation_id": "manago.contact_merge.plan_ci03",
      "op_kind": "contact_merge",
      "target": "manago",
      "namespace": "native",
      "capability_id": null,
      "entity_type": "contact",
      "from_evidence": {
        "match": { "path": "side", "const": "merge_candidate" },
        "entity_key": { "path": "survivor_manago_id" },
        "fields": {
          "cluster_kind": { "path": "cluster_kind" },
          "cluster_key": { "path": "cluster_key" },
          "survivor_manago_id": { "path": "survivor_manago_id" },
          "loser_manago_ids": { "path": "loser_manago_ids" },
          "safety_class": { "path": "safety_class" },
          "safety_reason": { "path": "safety_reason" },
          "email": { "path": "person.email" },
          "link_key": { "path": "link_key" }
        }
      },
      "guards": ["entity_key_required", "plan_only"]
    }
  ]
}
```

### 4.2 Phase B operation addendum (same file when gated)

Add second operation (or replace plan op for execute path):

```json
{
  "operation_id": "manago.contact_merge.safe_delete_ci03",
  "op_kind": "contact_merge",
  "target": "manago",
  "namespace": "native",
  "capability_id": "RESTV2.CONTACT.BATCH_DELETE",
  "entity_type": "contact",
  "from_evidence": {
    "match": { "path": "side", "const": "merge_candidate" },
    "entity_key": { "path": "survivor_manago_id" },
    "fields": {
      "survivor_manago_id": { "path": "survivor_manago_id" },
      "loser_manago_ids": { "path": "loser_manago_ids" },
      "safety_class": { "path": "safety_class" }
    }
  },
  "guards": [
    "entity_key_required",
    "safety_class_safe_delete",
    "cluster_size_eq_2",
    "loser_contact_id_required"
  ]
}
```

Registry: `"enabled": true` for Phase A. Phase B execute still requires Settings + allowlist + capability + FE allowlist.

Stub today has `rollback.strategy=restore_prior_field` — **replace with `none`**.

---

## 5. Adapter / transform / pipeline

### 5.0 Implementation contract (audit blockers — must ship or Preview breaks)

| # | Gap today | Required ship |
|---|-----------|----------------|
| A | `transform._build_payload_and_state` — no `contact_merge` → `ValueError: unsupported_op_kind` | Add branch returning plan payload `{ "mode": "plan", "survivor_id", "loser_ids", "safety_class", "cluster_kind", "cluster_key" }` |
| B | `manago.dry_run` — `capability_allows_execute(None)` is False | If `payload.get("mode")=="plan"` **or** mapping `execute_mode==plan_only`: skip capability check; leave intent ready for Preview |
| C | `pipeline.py` ignores `execute_mode` | Before mutate: if `mapping.get("execute_mode")=="plan_only"` and mode is execute/sandbox_execute → return `blocked_reason="ci03_plan_only"` (message in `messages.py`) |
| D | `guards.py` unknown guards no-op | Add explicit handlers: `plan_only` (always pass), `safety_class_safe_delete`, `cluster_size_eq_2`, `loser_contact_id_required` |
| E | `collect_evidence_rows` no CI-03 branch | `_ci03_evidence_rows` from `provenance.mismatches` / live rebuild like CI-05 |
| F | No per-UUID event stats | §3.4.1 helper used by emit |
| G | Stub `rollback.strategy=restore_prior_field` | Change to `none` |
| H | Mapping `fix_owner` unused by pipeline | Enforcement = CheckMaster + §5.0 C + FE allowlist |

### 5.1 Transform

| Concern | Rule |
|---------|------|
| `collect_evidence_rows` | `elif normalized == "CI-03": return _ci03_evidence_rows(...)` |
| Live rebuild | If stale score empty but live join has dups — rebuild candidates (CI-05 pattern) |
| `_build_payload_and_state` | `op_kind == "contact_merge"` → plan or delete payload (§5.0 A) |
| Phase A execute | Pipeline `ci03_plan_only` (§5.0 C); never call transport |
| Phase B | Only `safety_class=SAFE_DELETE`; reject others in transform + guard |
| Empty | 0 intents; disclosure “no merge candidates in sample” |

### 5.2 Manago transport (Phase B)

| Item | Spec |
|------|------|
| Path | `api/contact/batchDelete` |
| Addressing | `addresseeType=CONTACT_ID`; pass loser UUID(s) only |
| Owner | Primary Manago owner (CONN-07) |
| Forbidden | `api/contact/delete` with email for CI-03 |
| Capability | `RESTV2.CONTACT.BATCH_DELETE` — add to `capabilities.json` as `DISCOVERY_REQUIRED` until Loom |
| Implemented kinds | Add `contact_merge` to `_IMPLEMENTED_OP_KINDS` only when Phase B ships |
| Rollback | **None** — snapshot stores deleted UUIDs for audit only |

**Loom proof (required before CONFIRMED_LIVE):**

1. Sandbox: 2 contacts sharing externalId; loser with **0** events.  
2. Preview shows SAFE_DELETE.  
3. Execute deletes **only** loser UUID.  
4. Survivor retained with externalId + events.  
5. Re-fetch confirms loser gone.  
6. Negative: email-delete unused; MIGRATE refused.

### 5.3 Klints Contact DB cleanup (required for PASS)

`Order.contact` → `on_delete=CASCADE`. **Hard-deleting Contact deletes Orders.**

| Step | Spec |
|------|------|
| Migration | Add `Contact.excluded` BooleanField default False + `excluded_at` nullable DateTime |
| After Manago loser delete (Phase B) | Set `excluded=True`, `excluded_at=now` on Manago Contact rows for loser UUIDs |
| `identity_join` | Skip `excluded=True` contacts when building manago sets / dup clusters |
| Manual CRM merge (Phase A) | Ops/runbook: same tombstone via admin/script — Download column `klints_db_action_required=tombstone_loser` |
| Orders | **Do not** CASCADE-delete; leave orders on excluded contact **or** re-point `Order.contact_id` to survivor in a follow-on migration — **lock for Phase B:** prefer **re-point Manago orders to survivor** when `source=manago_ai` and contact was loser; Shopify orders untouched |

Until tombstone, CI-03 stays FAIL on DB accumulation even if Manago UI is clean.

### 5.4 Pipeline ceilings

| Tier | Behavior |
|------|----------|
| Phase A | Preview sample ≤50; Execute → `ci03_plan_only` |
| Phase B individual | `max_rows=1` / `individual_tier_single_intent_required` when ready>1 |
| Truncation | Re-score + re-Approve for next 50 |

### 5.5 Empty / reused honesty (CI-05 cross-link)

Keep WB-15 empty-preview copy pointing at CI-03.  
CI-03 Preview must not claim auto-clear of CI-05 until deletes+tombstones land.

---

## 6. Allowlist / migration

| Phase | `WritebackAllowedCheck` CI-03 | Notes |
|-------|-------------------------------|-------|
| A | **Do not seed** (or seed with execute denied) | Preview uses registry enabled + mapping; execute blocked by plan_only + fix_owner |
| B | Migration `0043_writeback_allowed_ci03` **only after** Loom + product sign-off | May also require CheckMaster `fix_owner` override discussion |

Do **not** silently change CheckMaster Fix Owner away from **CRM manager** without product decision logged in §16.

---

## 7. Possible sheet + SURFACE

### 7.1 `WRITEBACK_POSSIBLE_NOT_SHEET.csv` (both `docs/maheep/` + `dataruns/writebacks/`)

Update CI-03 row:

| Field | Phase A value |
|-------|----------------|
| `suggested_fix` | Propose Manago duplicate merge plan (survivor/loser/safety_class); not auto-merged; CRM manager |
| `write_possible_today` | **preview_plan** (or `disabled` execute + note) |
| `rollback_possible_today` | **no** |
| `registry_enabled` | **true** |
| `blocker` | Phase A: `plan_only_not_auto_merged`; Phase B clear when live |
| `evidence_note` | merge_candidate; externalId clusters first; SAFE_DELETE only for future delete; no email-delete; tombstone Klints DB |

### 7.2 `WRITEBACK_SURFACE_MATRIX.md`

| Row | Update |
|-----|--------|
| Merge contacts | Phase A **Plan live**; Phase B **Enabled (CONTACT_ID batchDelete SAFE)** |
| Enabled mappings | Add CI-03 plan row; note reused clears CI-05 |

---

## 8. Frontend

| Item | Phase A | Phase B |
|------|---------|---------|
| `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` | **Do not add CI-03** | Add CI-03 after Loom |
| Preview table | Show survivor / loser / safety_class / cluster_kind | Same |
| Request approval | Disabled (0 executable) with honesty: “Merge plan ready — CRM executes / Download” | Enabled for SAFE only |
| Download (FE-12) | Flatten `merge_candidate` into evidence `value` JSON so existing CSV `value` column carries survivor/loser/safety_class. Optional later: extend `EVIDENCE_EXPORT_COLUMNS` | Same |
| Honesty blurb | CI-03 proposes plan; not auto-merged; CI-05 reused waits on CI-03 | Deletes irreversible |
| Toast | N/A | Applied · re-run DCS — no false PASS |
| Deep-link | `/fix?issue=CI-03` | Same |

No new Fix chrome required.

---

## 9. Gates / settings

Unchanged global gates. Additional **hard** stops (Phase A):

| Gate | Behavior |
|------|----------|
| `execute_mode=plan_only` | **Wired in pipeline** → `blocked_reason=ci03_plan_only` on execute/sandbox_execute |
| FE `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` | CI-03 **absent** |
| `WritebackAllowedCheck` | CI-03 **not seeded** |
| CheckMaster `fix_owner=CRM manager` | `preview_only_owner` only when Settings/sandbox execute is **off**. **When sandbox execute is ON, this gate does NOT block** — do not treat it as sufficient |
| Phase B capability | `RESTV2.CONTACT.BATCH_DELETE` ∈ `{CONFIRMED_LIVE, CONFIRMED_LIMITED}` |
| Irreversible disclosure | Must render before any Phase B Approve |

Message key: add `ci03_plan_only` to `dataruns/writebacks/messages.py`.

---

## 10. Tests + verify

| Case | Expect |
|------|--------|
| Uncapped totals drive FAIL even when sample lists len=50 | |
| `evaluate_ci_03` emits ≤50 `merge_candidate` on FAIL/WARN | |
| Survivor prefers purchase/event spine over oldest | |
| Phone-only → QUARANTINE | |
| Size≥3 → QUARANTINE | |
| Loser with purchases → MIGRATE_THEN_DELETE | |
| Transform builds plan intents; Phase A execute denied | |
| No email-delete code path for CI-03 | |
| Capability BATCH_DELETE absent/DISCOVERY → execute denied | |
| Phase B SAFE deletes loser CONTACT_ID only (unit/mocked) | |
| Tombstone removes loser from identity_join | |
| CI-05 path still never writes reused | |
| FE allowlist excludes CI-03 in Phase A | |
| Possible sheet + SURFACE updated | |
| Mapping `irreversible=true`, rollback `none`, tier `individual` | |

Script: `scripts/verify_wb16_ci03_contact_merge.py`  
- Phase A: registry, mapping, plan_only, no FE allowlist, both sheet copies, mismatch helper, no email-delete, rollback none  
- Phase B flag: `--phase-b` asserts capability + adapter + allowlist + FE string  

---

## 11. PR / branch

- **Base:** tip with WB-15 merged  
- BE Phase A: `feat(WB-16): CI-03 merge plan (not auto-merged)`  
- BE Phase B (separate PR preferred): `feat(WB-16B): CI-03 SAFE contactId delete`  
- FE Phase A: honesty + Preview columns (Approve still off)  
- FE Phase B: allowlist CI-03  
- PR body: link this PRD · “T3 merge plan; CRM owner; not auto-merged; SAFE batchDelete CONTACT_ID only in 16B; event-spine survivor; tombstone DB”

---

## 12. Acceptance checklist

### Phase A

- [ ] Uncapped duplicate totals used for CI-03 score  
- [ ] `merge_candidate` provenance on FAIL/WARN (cap 50; externalId first)  
- [ ] §3.4.1 event counts; incomplete → not SAFE_DELETE  
- [ ] Survivor rule = event-spine first (DCS-486 safe)  
- [ ] Mapping enabled, `plan_only`, `irreversible`, rollback `none`, tier `individual`  
- [ ] §5.0 A–H all shipped (transform / dry_run / pipeline / guards)  
- [ ] Fix Preview shows plan; execute returns `ci03_plan_only`  
- [ ] FE allowlist excludes CI-03; no WritebackAllowedCheck seed  
- [ ] FE-12 `value` carries merge plan fields  
- [ ] Possible sheet + SURFACE + README updated  
- [ ] `verify_wb16_ci03_contact_merge.py` green  
- [ ] No Manago mutate in Phase A  
- [ ] No email-delete helper used by CI-03  
- [ ] No hard-delete of Contact rows  

### Phase B (separate gate)

- [ ] Sandbox Loom for `batchDelete` CONTACT_ID → capability CONFIRMED_LIVE  
- [ ] Execute only `SAFE_DELETE`  
- [ ] MIGRATE/QUARANTINE/UNSAFE refused  
- [ ] `Contact.excluded` tombstone + identity_join skip; Order re-point rule tested  
- [ ] FE allowlist + Settings allowlist seeded  
- [ ] Irreversible disclosure shown  
- [ ] Re-score improves CI-03 and CI-05 reused on fixture estate  
- [ ] Sandbox-ON cannot bypass without allowlist (FE + WritebackAllowedCheck)

---

## 13. Explicitly not in this PR

- Inventing `RESTV2.CONTACT.MERGE`  
- Email-based contact delete for CI-03  
- Auto-merge of phone-only or size≥3 clusters  
- Changing CI-03 rate thresholds (only uncapped honesty)  
- CI-05 dangling rewrite  
- Estate wipe + full Shopify re-export automation  
- Changing Fix Owner to Klints without §16 decision  
- Handoff / Studio / QA / CAP  

---

## 14. Code reference map

| Area | Path |
|------|------|
| Score | `dataruns/dcs/executors/identity.py` → `evaluate_ci_03` |
| Join / clusters | `dataruns/dcs/identity_join.py` |
| Mapping stub | `dataruns/writebacks/mappings/CI-03.contact_merge.v1.json` |
| Registry | `dataruns/writebacks/mappings/registry.json` |
| Transform | `dataruns/writebacks/transform.py` |
| Adapter | `dataruns/writebacks/adapters/manago.py` + `manago_transport.py` |
| Capabilities | `dataruns/writebacks/capabilities.py` + `capabilities.json` |
| Fix owner gate | `dataruns/writebacks/pipeline.py` + `fix_ownership.py` |
| Possible sheet | `dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv` (+ docs copy) |
| FE allowlist | `klints_frontend/src/lib/writebacks.ts` |
| Live audits | `exports/dcs_fresh_import_raw/dcs_482_*`, `dcs_486_*` |
| Manago API | `api/contact/batchDelete` (CONTACT_ID); **no** merge |

---

## 15. Traceability

| | |
|--|--|
| Parents | WB-01…15 · DCS identity · catalogue T3 · DCS-482/486 delete safety |
| Catalogue | CI-03 · T3 · not auto-merged · CRM manager |
| Unblocks | CI-05 reused FAIL · CI-01 manago inflation · LE-* event targeting clarity |
| Next | CC-01 / CC-02 (MVP1 P0 #7–8) after CI-03 Phase A (Phase B can parallel) |

---

## 16. Decision log

| # | Question | Decision |
|---|----------|----------|
| 1 | Auto-merge in MVP1? | **No** — Excel “not auto-merged”; Phase A plan only |
| 2 | Keep oldest UUID? | **No** — keep event-spine / newest-with-events |
| 3 | Manago merge endpoint? | **Does not exist** — plan + batchDelete |
| 4 | Delete by email? | **Forbidden** for CI-03 |
| 5 | Fix Owner Klints? | **No** unless product flips — stay CRM manager |
| 6 | Include phone auto-delete? | **No** — quarantine |
| 7 | Cap 50 for writes/plan? | **Yes** sample; uncapped for score |
| 8 | Rollback strategy? | **none** (irreversible) |
| 9 | Same PR as Phase B? | Prefer **split PRs**; one PRD |
| 10 | Will plan-only clear CI-05? | **No** — need real merges + DB tombstone |
| 12 | Will incomplete event visibility allow SAFE_DELETE? | **No** — UNSAFE/QUARANTINE |
| 13 | Hard-delete Contact? | **No** — CASCADE Orders; use `excluded` |
| 14 | Is fix_owner gate enough in sandbox? | **No** — bypassed when execute enabled; need plan_only + FE allowlist |

---

## 17. Deep-check evidence (pre-implement + rev-2 audit)

| Check | Result |
|-------|--------|
| Stub mapping | `enabled=false`, empty ops, rollback wrongly `restore_prior_field` |
| Transform / adapter | No `contact_merge` → Preview would ValueError once ops added |
| `manago.dry_run` | `capability_id=null` → `capability_not_confirmed` without plan exception |
| `guards.py` | Unknown guards silently pass — `plan_only` string alone is not a gate |
| `pipeline.execute_mode` | **Not read today** — must wire (§5.0 C) |
| `fix_owner` gate | Bypassed when sandbox execute ON — FE allowlist + plan_only are real Phase A stops |
| Capability | No CONTACT.DELETE / BATCH_DELETE in `capabilities.json` |
| Manago public API | upsert · delete(email) · **batchDelete(CONTACT_ID)** · **no merge** |
| Excel (in-repo) | possible sheet: plan — **not auto-merged**; Fix Owner **CRM manager** |
| Contact / Order | No soft-delete field; `Order.contact` **CASCADE** |
| Event counts on clusters | **Absent** — §3.4.1 required |
| FE-12 | Fixed columns; plan fields via evidence `value` JSON |
| DCS-486 | 201 reused; 76 HIGH_LOSS if delete newer; 0 older in fresh raw |
| DCS-482 delete audit | **0** class-A under keep-oldest policy |
| CI-05 WB-15 | Refuses reused; points here |
| Cap artifact | `[:50]` ×3 → evidence clusters=150 vs uncapped ~201 each |

### Rev-2 verdict

Product locks (Excel, no merge API, CONTACT_ID delete, event-spine survivor, Phase A not auto-merged) = **solid**.  
Implementability before rev-2 = **FAIL** (6 blockers).  
After §0 / §5.0 / §3.4.1 / §9 patches = **PASS_WITH_FIXES** — ready to implement Phase A.

---

## 18. Operator / CRM runbook (Phase A Download)

Download (via FE-12 `value` JSON and/or friendly rows) must expose at least:

`cluster_kind, cluster_key, survivor_manago_id, loser_manago_ids, safety_class, safety_reason, survivor_purchase_count, loser_purchase_count, person.email, link_key, ci05_reused, klints_db_action_required, recommended_manago_ui_action`

Recommended CRM actions by class:

| Class | Action |
|-------|--------|
| SAFE_DELETE | In Manago UI delete **loser** by contact id; then tombstone Klints DB (`excluded`) **or** wait Phase B |
| MIGRATE_THEN_DELETE | Move/re-create events onto survivor first; only then delete loser |
| QUARANTINE / UNSAFE | Manual review — do not bulk delete |

---

**End PRD-WB-16 (rev 2).**
