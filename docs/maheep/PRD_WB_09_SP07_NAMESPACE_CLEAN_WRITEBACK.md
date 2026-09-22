# PRD-WB-09 — SP-07 namespace clean writeback

**Status:** Ready for implementation — **P0 (M2 — Gate Fix; unlocks all writebacks)**  
**Owner track:** Maheep (`docs/maheep/`) — **BE primary · FE Approve allowlist + Fix copy**  
**Surfaces:** Fix `/fix` Approve · Settings Allow writebacks · `WritebackAllowedCheck` · registry / mapping · possible sheet · SP-07 DCS detector allowlist · Activity/audit  
**Milestone:** M2 Activation & Blueprint (T2) — Writeback depth after WB-08  
**Depends on:** WB-03…WB-08 · FE-08/09 · POLISH-01 · DCS SP-07 executor (`evaluate_sp_07`) live  
**Parallel with:** Sahil Studio / HO / QA — **no shared files / no dependency**  
**Contract SoT:** Catalogue Automated writeback for SP-07; Writeback + Lifecycle live  
**Pack SoT:**  
- `Klints_Spec_InitialDataConsistencyCheck_v1.4.1` sheet **02 Check Catalogue** row **SP-07**  
- sheet **09 MVP1 Check Scope** (#22, weight 5, SCORED, MVP1-A)  
- `docs/dcs_scoring/CHECK_MASTER_42.md`  
- Manago Execution Capability Matrix · `RESTV2.CONTACT.UPSERT` (CONFIRMED_LIVE)  
- Pilot UC-23 gating (`SP-07`) · blueprint namespace `klints_` / `klints:`  
**Out of scope:**  
- Tenant-wide **versioned Klints prefix** (Excel option B) — deferred; see §2  
- SP-01 tag consolidation (not in MVP1 42)  
- LE-09 / PT-04 / other catalogue AW waves  
- Shopify metafield writers  
- Manual REST runbooks as product UX  
- Turning global `WRITEBACKS_ENABLED=True` outside Settings gate  
- New Manago MCP property-rename APIs  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-09 — SP-07 namespace clean Automated writeback.

Read:
- docs/maheep/PRD_WB_09_SP07_NAMESPACE_CLEAN_WRITEBACK.md (this file)
- docs/maheep/WRITEBACK_SURFACE_MATRIX.md
- docs/dcs_scoring/CHECK_MASTER_42.md (SP-07 row)
- dataruns/dcs/executors/segment.py (evaluate_sp_07)
- dataruns/dcs/segment_join.py (collision detection + owned keys)
- dataruns/writebacks/preflight.py (SP-07 gate — chicken-egg rules §5)
- dataruns/writebacks/mappings/CC-03.consent_provenance.v1.json (detail_set pattern)
- dataruns/writebacks/adapters/manago.py (detail_set + tag_add / deleteTag)
- FE: src/lib/writebacks.ts WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS

Ship:
1. Lock product decisions in §2 (rename MVP; owned allowlist; no self-preflight).
2. Expand SP-07 owned-key allowlist so Klints writebacks do not FAIL the gate (§3).
3. New mapping SP-07.namespace_clean.v1.json — rename collisions off namespace (§4–6).
4. Transform: expand account-level collision keys → per-contact intents (§6).
5. Seed WritebackAllowedCheck + possible sheet + FE allowlist (§7–8).
6. Rollback via reverse map snapshots (§9).
7. Tests + verify script (§11). No Loom required for v1 (ops optional).

Do NOT implement versioned prefix (§2 Option B).
Do NOT set requires_consent_namespace_clean=true on SP-07 mapping.
Do NOT touch handoff / Studio / QA / CAP.
Acceptance: §12.
```

---

## 1. Why (simple)

| Today | Gap |
|-------|-----|
| SP-07 **detects** `klints_` / `klints:` collisions and **scores** FAIL | Catalogue Fix Type = **Automated writeback (approved)** — **no mapping** |
| Other writebacks can **block** when SP-07 ≠ PASS (`requires_consent_namespace_clean`) | Users cannot clear the gate in-app (only Manago REST / ops) |
| Excel P0 · Critical · “Gate — blocks writeback” | Gate without Fix = product trap (same class as PT-04 gap) |

**WB-09** ships Fix Approve for SP-07 so a tenant can **catalogue → rename legacy collisions → re-score PASS**, then other writebacks can proceed.

```text
DCS SP-07 FAIL (collisions in evidence)
  → Fix Preview (rename intents + reverse map)
  → Approve (Settings Allow writebacks ON)
  → Manago: move legacy detail/tag off klints namespace
  → Re-run DCS → SP-07 PASS
  → Other writebacks unblocked
```

---

## 2. Product decisions (locked)

### 2.1 Fix strategy — Option A only for MVP

Excel Suggested Fix allows:

1. Catalogue collisions  
2. **Rename legacy items with approval**  
3. **Or version the Klints prefix for this tenant**  
4. Writeback stays blocked until namespace is clean  

| Option | Ship in WB-09? | Notes |
|--------|----------------|-------|
| **A — Rename legacy off namespace** | **Yes** | Default. Logged reverse map (Excel Rollback Note) |
| **B — Version Klints prefix per tenant** | **No** | Deferred WB-09B — needs config surface + every mapping aware of prefix |

**Rename convention (locked):**

| Collision kind | From | To |
|----------------|------|-----|
| Detail key | `klints_<rest>` (not owned) | `legacy_klints_<rest>` |
| Tag | `klints:<rest>` | `legacy_klints:<rest>` |

- Never write **new** values into the Klints namespace in this job (only move legacy **off**).  
- If target `legacy_*` already exists on that contact with a **different** value → row `error` + reason `rename_target_conflict` (do not overwrite).  
- If target already equals source value → treat as already-renamed (idempotent skip / ready-noop).

### 2.2 What counts as a collision (detector honesty)

Excel: *pre-existing* details/tags that collide with the Klints convention.

**Locked rule:**

```text
collision = key/tag matches klints_ / klints:  AND  NOT in Klints-owned allowlist
```

| Surface | Owned allowlist (v1) |
|---------|----------------------|
| Details | Explicit set in `segment_join` (start: `klints_backfill`, `klints_consent_evidence`) + any key declared by **enabled** writeback mappings with `namespace: klints_` |
| Tags | Tags declared by **enabled** writeback mappings with `namespace: klints:` (none required for SP-07 itself). VIP / pilot tags stay **out** until those writebacks ship |

**Must change with this PRD:** today only `klints_backfill` is owned; after CC-03 / future writes, SP-07 would FAIL on Klints-owned keys. WB-09 **fixes detector + join** in the same PR as the writeback.

### 2.3 Preflight chicken-egg (locked)

| Mapping | `requires_consent_namespace_clean` |
|---------|-------------------------------------|
| **SP-07** | **`false`** (must clear the gate while dirty) |
| CC-03 and others that already set `true` | Unchanged |

SP-07 execute still requires: Settings Allow writebacks · sandbox/allowlist · once-per-run · claim-before-write · Manago connected.

### 2.4 Scope of rows

Collisions in DCS evidence are **account-level key/tag names**. Execute expands to **every Manago contact** in the latest snapshot that still holds that key or tag.

- Preview may cap intents (`max_rows` / existing pipeline clamp) with honest `truncated` summary.  
- Cadence Excel = **Initial** — expect one clean-up job early; recurring re-entry if new foreign collisions appear.

### 2.5 Approval tier

| Field | Value |
|-------|--------|
| `approval_tier` | **`batch`** (hygiene rename; pack: tag/detail `klints_` hygiene → batch) |
| `irreversible` | **`false`** (reverse map rollback) |
| Fix Owner | Klints (automated) — Excel |

### 2.6 Non-goals (collision guard)

- Do **not** delete collision keys/tags without rename (data loss).  
- Do **not** silently claim legacy values as Klints-owned.  
- Do **not** auto-merge semantic duplicates (that is SP-03 / other).  
- Do **not** implement Option B versioned prefix.  
- Do **not** advertise SP-07 Approve until mapping `enabled=true` + allowlist + sheet row live.

---

## 3. Excel + pack traceability

| Catalogue field | Value (SoT) |
|-----------------|-------------|
| Check ID | SP-07 |
| Check Name | klints_ namespace availability |
| Entity | Detail / Tag namespace |
| Systems | Manago |
| Check Type | Uniqueness |
| Detection | Verify no pre-existing details/tags collide with `klints_` / `klints:`; reserve namespace in mapping config |
| Root Causes | RC-04 |
| Severity | Critical |
| DCS Weight | Gate — blocks writeback |
| Suggested Fix | Catalogue → rename with approval **or** version prefix; blocked until clean |
| Fix Type | Automated writeback (approved) |
| Fix Owner | Klints (automated) |
| Rollback Note | Renames logged with reverse map |
| Cadence | Initial |
| Fix Template | — |
| Build Priority | P0 |
| MVP1 Scope | #22 · weight 5 · SCORED · MVP1-A |

**Capability:** rename via `RESTV2.CONTACT.UPSERT` (set new detail / clear old) + existing tag add/remove (`deleteTag`). No separate rename capability ID.

**Workflows:** Excel — *All Klints writeback operations*; UC-23 gates on SP-07.

---

## 4. Today vs ship

| Artifact | Today | After WB-09 |
|----------|-------|-------------|
| `evaluate_sp_07` | FAIL on any non-`klints_backfill` `klints_*` / any `klints:` | FAIL only on **non-owned** collisions |
| `segment_join` owned set | `{klints_backfill}` | Expanded allowlist §2.2 |
| Mapping | **None** | `SP-07.namespace_clean.v1.json` enabled |
| `WritebackAllowedCheck` | No SP-07 | Seed SP-07 |
| Possible sheet | No SP-07 row | `write_possible_today=yes` (or `sandbox_only` if matching other AW) |
| FE Approve allowlist | No SP-07 | Include `SP-07` |
| Preflight | Blocks *other* mappings when dirty | Unchanged; SP-07 exempt via `requires_consent_namespace_clean: false` |
| Manual REST | Ops-only clear path | Remains fallback; product path = Fix Approve |

---

## 5. Mapping contract

**File:** `dataruns/writebacks/mappings/SP-07.namespace_clean.v1.json`

```json
{
  "schema_version": "1.0.0",
  "check_id": "SP-07",
  "template_id": null,
  "title": "Rename legacy klints_ / klints: collisions off namespace",
  "enabled": true,
  "approval_tier": "batch",
  "requires_consent_namespace_clean": false,
  "irreversible": false,
  "operator_disclosure": "Renames legacy Manago detail keys and tags that collide with the Klints namespace. Prior names are preserved under legacy_* for rollback.",
  "rollback": {
    "strategy": "reverse_rename_map"
  },
  "operations": [
    {
      "operation_id": "manago.detail_rename.off_klints",
      "op_kind": "detail_set",
      "target": "manago",
      "namespace": "native",
      "capability_id": "RESTV2.CONTACT.UPSERT",
      "entity_type": "contact",
      "from_evidence": {
        "match": { "path": "side", "const": "klints_detail_collision" },
        "entity_key": { "path": "person.email" },
        "fields": {
          "detail_key": { "path": "rename_to" },
          "detail_value": { "path": "detail_value" },
          "clear_detail_key": { "path": "key" },
          "contact_id": { "path": "manago_contact_id" }
        }
      },
      "guards": ["entity_key_required", "email_format"]
    },
    {
      "operation_id": "manago.tag_rename.off_klints",
      "op_kind": "tag_add",
      "target": "manago",
      "namespace": "native",
      "capability_id": "RESTV2.CONTACT.UPSERT",
      "entity_type": "contact",
      "from_evidence": {
        "match": { "path": "side", "const": "klints_tag_collision" },
        "entity_key": { "path": "person.email" },
        "fields": {
          "tag": { "path": "rename_to" },
          "remove_tag": { "path": "tag" },
          "contact_id": { "path": "manago_contact_id" }
        }
      },
      "guards": ["entity_key_required", "email_format"]
    }
  ]
}
```

**Implementation notes (locked intent, flexible shape):**

- Prefer **one atomic per-contact sequence**: write `legacy_*` → clear/remove old `klints_*` / `klints:`.  
- If adapter lacks combined clear+set today, extend Manago adapter minimally (same PR) — do **not** invent MCP.  
- `namespace: native` on ops is intentional: targets are **off** Klints prefix; guards must **not** require `klints_prefix` on the new key.  
- Registry entry + `enabled: true`.

---

## 6. Evidence → intents (transform)

### 6.1 Inputs

From latest terminal DCS run worklist / check result for SP-07:

- `evidence[].value.klints_detail_collisions[]`  
- `evidence[].value.klints_tag_collisions[]`  
- Provenance mismatches with `side` ∈ {`klints_detail_collision`, `klints_tag_collision`}

Filter to **non-owned** only (same allowlist as detector).

### 6.2 Expand to contacts

For each colliding detail key `K`:

1. Scan latest Manago contact snapshot (`properties` / `dictionaryProperties` / details bags).  
2. Every contact with key `K` → intent:  
   - `rename_to = legacy_` + `K` (if `K` already starts with `klints_`, result `legacy_klints_…`)  
   - `detail_value` = current value  
   - `clear_detail_key = K`  
   - `side = klints_detail_collision`

For each colliding tag `T`:

1. Contacts with tag `T` → intent:  
   - `rename_to = legacy_` + `T` (e.g. `legacy_klints:foo`)  
   - `remove_tag = T`  
   - `side = klints_tag_collision`

### 6.3 Sandbox enrichment

When SP-07 is PASS / not on FAIL worklist: optional sandbox proof rows **disabled by default**. Prefer live FAIL only (unlike LE-01). Document in mapping `evidence_note` if a fixture path is added later.

### 6.4 Preview honesty

Preview must show:

- Collision catalogue (keys/tags + contact counts)  
- Sample before → after renames  
- `operator_disclosure`  
- Truncation if contact fan-out exceeds batch cap  

---

## 7. Allowlist + possible sheet + FE

| Layer | Change |
|-------|--------|
| Migration | Seed `WritebackAllowedCheck` for `SP-07` (pattern from WB-08 / 0034–0036) |
| `WRITEBACK_POSSIBLE_NOT_SHEET.csv` | Add SP-07 rows (detail rename + tag rename) · `fix_type=Automated writeback (approved)` · `write_possible_today=yes` (or `sandbox_only` if company policy matches CI-01) · rollback `yes` via reverse map |
| `WRITEBACK_SURFACE_MATRIX.md` | Document SP-07 rename surface |
| FE `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` | Add `"SP-07"` |
| `PRD_WB_02` §3.2 list | Remove SP-07 from “Approve must stay OFF” (doc note in this PR) |

---

## 8. Gates reuse (do not weaken)

Keep WB-03…07:

- Settings Allow writebacks default OFF  
- Once-per-DCS-run successful execute  
- Claim-before-adapter-I/O  
- PII mask on entity_key  
- Audit hash chain events  
- Capability CONFIRMED_LIVE for UPSERT  

**SP-07-specific:** after successful execute, UI copy should prompt **re-run DCS** (or wait for daily beat) — SP-07 status does not flip until rescore.

---

## 9. Rollback

Excel: *Renames logged with reverse map.*

| Strategy id | Behavior |
|-------------|----------|
| `reverse_rename_map` | From `rollback_snapshot`: restore original key/tag; remove `legacy_*` target written by this job |

- Persist per-intent: `{ from, to, op: detail|tag, prior_value, contact_id }`  
- Extend `rollback_strategy.py` allowlist for SP-07  
- If contact changed again after our write → best-effort + audit `rollback_conflict` (do not force overwrite without disclosure)

---

## 10. Detector + join changes (same PR)

| File | Change |
|------|--------|
| `dataruns/dcs/segment_join.py` | Expand `_KLINTS_OWNED_DETAIL_KEYS` / add owned tags helper; optionally derive from enabled mappings registry |
| `dataruns/dcs/executors/segment.py` | Detail text stays; evidence still lists collisions (non-owned only) |
| Tests `test_batch_4c_checks.py` | Owned key does **not** FAIL; foreign `klints_net_ltv` still FAIL |

---

## 11. Tests + verify

| Test | Expect |
|------|--------|
| Unit transform | Collision keys → N contact intents with `legacy_*` targets |
| Unit detector | Owned keys PASS; foreign FAIL |
| Preflight | Mapping with `requires_consent_namespace_clean: true` still blocks when SP-07 FAIL; SP-07 mapping preview/execute allowed when FAIL |
| Pipeline dry-run | No Manago mutate |
| Sandbox execute (marked) | Rename one fixture collision → deleteTag/clear → rollback restores |
| FE allowlist | SP-07 Approve enabled when sheet + Settings ON |
| Verify script | `scripts/verify_wb09_sp07_namespace_clean.py` — registry enabled, allowlist, sheet row, owned keys include CC-03 key |

---

## 12. Acceptance

- [ ] Excel Suggested Fix path A implemented: catalogue + rename with approval  
- [ ] Option B versioned prefix **not** shipped  
- [ ] `requires_consent_namespace_clean: false` on SP-07 mapping  
- [ ] Detector allowlist includes Klints-owned writeback keys (at least `klints_backfill`, `klints_consent_evidence`)  
- [ ] Fix Approve for SP-07 on FAIL worklist when Settings ON  
- [ ] Preview shows reverse-map renames; execute writes Manago; audit events  
- [ ] Rollback restores prior names via reverse map (or honest conflict)  
- [ ] After clean + DCS rescore, SP-07 PASS and gated writebacks can preview  
- [ ] No Handoff / Studio / QA file changes  
- [ ] Possible sheet + SURFACE matrix + FE allowlist updated  
- [ ] Tests + verify script green  

---

## 13. Explicit non-goals

- Versioned tenant prefix (WB-09B)  
- Deleting collisions without rename  
- SP-01 / LE-09 / PT-04 in this PR  
- Changing RC-04 taxonomy  
- Bypassing Settings Allow writebacks  
- Claiming MCP `MCP.TAG.PROPERTY.LIST` as required (optional future discovery)  

---

## 14. Code reference map

| Path | Role |
|------|------|
| `dataruns/dcs/segment_join.py` | Collision detection + owned allowlist |
| `dataruns/dcs/executors/segment.py` | `evaluate_sp_07` |
| `dataruns/writebacks/preflight.py` | Gate for *other* mappings |
| `dataruns/writebacks/mappings/SP-07.namespace_clean.v1.json` | **New** |
| `dataruns/writebacks/mappings/registry.json` | Register SP-07 |
| `dataruns/writebacks/transform.py` | Fan-out collisions → contacts |
| `dataruns/writebacks/adapters/manago.py` | detail set/clear + tag add/remove |
| `dataruns/writebacks/rollback*.py` | `reverse_rename_map` |
| `dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv` | Honesty sheet |
| FE `src/lib/writebacks.ts` | Approve allowlist |
| **Forbidden:** `dataruns/use_cases/handoff*` · Studio / QA | Sahil |

---

## 15. Branch / PR

- Branch: `feature/wb-09-sp07-namespace-clean`  
- BE title: `feat(WB-09): SP-07 namespace collision rename writeback`  
- FE title (if split): `feat(WB-09): enable SP-07 Fix Approve`  
- PR body: link this PRD · “clears writeback gate in-app; no versioned prefix”  
- Merge: BE (detector + mapping + allowlist) first, then FE allowlist if separate  

---

## 16. Traceability

| Field | Value |
|-------|--------|
| Milestone | M2 — Writeback gate Fix |
| Pack | Catalogue SP-07 P0 Automated writeback |
| Parents | WB-01…08 · DCS-04 batch 4c SP-07 |
| Unblocks | All mappings with `requires_consent_namespace_clean` · UC-23 gate honesty |
| Next | **WB-10** LE-09 AW · then PT-04 AW · or WB-09B versioned prefix if product asks |
| Independent of | Handoff · Studio · Track B · DCS-09/10 |

---

## 17. Open questions (resolved in this PRD — do not reopen in impl)

| # | Question | Decision |
|---|----------|----------|
| 1 | Rename vs version prefix? | **Rename only** (MVP) |
| 2 | Self-preflight? | **No** — `requires_consent_namespace_clean: false` |
| 3 | Any `klints_*` = FAIL? | **No** — owned allowlist |
| 4 | Delete vs rename? | **Rename** to `legacy_*` |
| 5 | Per-key or per-contact? | Evidence = keys; execute = **per contact** holding key/tag |
| 6 | Approval template? | Excel `—` → `template_id: null` |
