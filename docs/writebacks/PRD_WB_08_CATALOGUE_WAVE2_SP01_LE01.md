# PRD-WB-08 — Catalogue writeback wave 2 (SP-01 + LE-01)

**Status:** Ready for implementation — **P0 (M2 contract — Writeback + Lifecycle depth)**  
**Owner track:** Engineering  — **BE primary · FE only if irreversible disclosure / Fix copy needs wire**  
**Surfaces:** Fix `/fix` Approve · Settings Allow writebacks (unchanged) · `WritebackAllowedCheck` · registry / mappings · possible sheet · Activity/audit  
**Milestone:** M2 Activation & Blueprint (T2) — contract bundle **“Writeback + Lifecycle live (SM REST writeback, rollback, audit hash chain)”**  
**Depends on:** WB-03…WB-07 · FE-08/09 · POLISH-01 (audit immutable)  
**Parallel with:** Engineering **HO-02** (Handoff Send) — **no shared files / no dependency**  
**Contract SoT:** Schedule 1 M2 deliverable — *Writeback + Lifecycle live*  
**Pack SoT:**  
- Check Catalogue Suggested Fix for **SP-01** / **LE-01** (Automated writeback approved)  
- `dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv`  
- `dataruns/writebacks/mappings/registry.json`  
- `docs/engineering/WRITEBACK_SURFACE_MATRIX.md`  
**Out of scope:**  
- Engineering HO-02 / `/handoff` / Send / Studio / QA / CAP / Track B / 8-state ORCH  
- **CI-03** contact merge (empty ops · irreversible · separate PRD)  
- **LE-04** (pack Fix Type = Integration + Manual — stay disabled)  
- Shopify Order/Transaction writers  
- Turning global `WRITEBACKS_ENABLED=True`  
- New adapter protocols beyond existing `tag_add` / `event_ingest`

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-08 — Catalogue writeback wave 2: SP-01 + LE-01.

Read:
- docs/engineering/PRD_WB_08_CATALOGUE_WAVE2_SP01_LE01.md (this file)
- docs/engineering/WRITEBACK_SURFACE_MATRIX.md
- dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv
- dataruns/writebacks/mappings/registry.json
- dataruns/writebacks/mappings/SP-01.tag_consolidation.v1.json (ops empty today)
- dataruns/writebacks/mappings/LE-01.event_backfill.v1.json (ops exist, enabled=false)
- dataruns/writebacks/adapters/manago.py (tag_add + event_ingest already implemented)
- dataruns/writebacks/gates.py · run_gate.py · pipeline.py (reuse WB-03…07)
- dataruns/migrations/0025_writeback_allowed_check.py (seed pattern)
- FE: src/routes/fix.tsx — irreversible disclosure if not already wired

Ship:
1. Build SP-01 mapping operations (tag_add · klints: namespace) + enable registry (§4).
2. Enable LE-01 registry with irreversible disclosure + honest rollback limits (§5).
3. Seed WritebackAllowedCheck for SP-01 + LE-01 (§6).
4. Update possible sheet + SURFACE matrix rows (§7).
5. Transform/evidence paths work for FAIL/WARN worklist rows (§4.3 · §5.3).
6. Keep all WB-03…07 gates: Settings OFF default · once-per-run · claim-before-write · PII mask · audit (§8).
7. Tests + verify script (§10). Loom notes (§11).

Do NOT touch handoff / Studio / QA / CAP.
Do NOT enable CI-03 or LE-04.
Acceptance: §12.
```

---

## 1. Why (simple)

| Today | Gap vs contract |
|-------|-----------------|
| Writeback **pipeline** live for **3** checks (CI-01, CC-03, WB-SHOP-01) | Contract says Writeback + Lifecycle **live** — still thin catalogue coverage |
| Adapters already implement `tag_add` + `event_ingest` | SP-01 / LE-01 mappings disabled or empty |
| Engineering ships HO-02 Send in parallel | Engineering must deepen **Fix writebacks**, not Handoff |

**WB-08** turns on the next two **Catalogue “Automated writeback (approved)”** checks that adapters already support, without colliding with Send.

```text
Settings Allow writebacks ON (existing)
  → Fix SP-01 or LE-01 FAIL
  → Preview → Approve → Manago write
  → Audit hash chain event
  → Rollback when strategy allows (SP-01 yes; LE-01 limited/honest)
```

---

## 2. Product decision (locked)

| Check | Ship in WB-08? | Why |
|-------|----------------|-----|
| **SP-01** Tag consolidation | **Yes** | Pack Automated writeback; adapter `tag_add` live; rollback `remove_tag` |
| **LE-01** Purchase event backfill | **Yes** | Pack Automated writeback; mapping ops exist; adapter `event_ingest` live; **irreversible** — disclose |
| **CI-03** Contact merge | **No** | Ops empty; irreversible merge; needs own PRD |
| **LE-04** Duplicate purchase tag | **No** | Pack = Integration + Manual (T6) — stay off allowlist |
| **WB-SHOP-01** | Unchanged | Still allowlisted |
| Shopify metafield `klints` | **No** (optional later WB-09) | Hygienic Shopify path; not required for this wave |

**Lane wall (do not cross):**

```text
Engineering WB-08  =  dataruns/writebacks/**  + Fix copy for irreversible
Engineering HO-02   =  dataruns/use_cases/handoff*  + /handoff FE
```

---

## 3. Contract + lifecycle meaning

**Contract line (M2 bundle):**  
*Writeback + Lifecycle live (SM REST writeback, rollback, audit hash chain)*

In this PRD, **Lifecycle** means the writeback job lifecycle — not Engineering `/lifecycle` Architecture AF:

```text
preview → approval → execute → (optional) rollback → audit events
```

Already enforced by WB-03…07. WB-08 **extends** which catalogue checks can run that loop.

---

## 4. SP-01 — Tag consolidation (build + enable)

### 4.1 Today

| Artifact | State |
|----------|--------|
| `SP-01.tag_consolidation.v1.json` | `enabled: false`, **`operations: []`** |
| `registry.json` | `enabled: false` |
| Possible sheet | `write_possible_today=disabled`, blocker `mapping_stub_not_built` |
| Adapter | `tag_add` + rollback remove_tag **implemented** |

### 4.2 Target mapping (lock)

Fill `operations` (do not leave empty). Minimum viable:

| Field | Value |
|-------|--------|
| `op_kind` | `tag_add` |
| `target` | `manago` |
| `namespace` | `klints:` |
| `capability_id` | Use same live contact tag capability as LE-04 stub (`RESTV2.CONTACT.UPSERT` or Matrix-confirmed tag API — **match existing `add_contact_tag` transport**) |
| `entity_type` | `contact` |
| Tag written | Prefer evidence-driven **or** const `klints:consolidated` / pack Suggested Fix tag — **must** start with `klints:` |
| `rollback.strategy` | `remove_tag` |
| `approval_tier` | `batch` |
| `irreversible` | `false` |
| `enabled` | `true` (file + registry) |

**Evidence bind (required):**  
`from_evidence` must resolve `entity_key` (email or contact id) from LE/SP executor evidence shape for SP-01 FAIL/WARN rows. If current evidence paths differ from LE-04’s `side` match, **inspect one real SP-01 FAIL payload on staging/local** and pin paths in the mapping — do not invent fields.

**Operator rule:** Only write `klints:` tags. Never strip or rewrite arbitrary customer marketing tags in this PRD.

### 4.3 Transform / preview

- Preview must emit ≥1 intent when worklist has SP-01 FAIL/WARN with resolvable contact key.  
- If evidence cannot resolve contact → skip row with honest `error_reason` (no silent Written).  
- Cap batch size consistent with existing pipeline (do not invent unbounded tag storms).

### 4.4 Rollback

- After execute, Rollback removes the tag added by the job (`remove_tag`).  
- Idempotent if tag already absent.

---

## 5. LE-01 — Purchase event backfill (enable + honesty)

### 5.1 Today

| Artifact | State |
|----------|--------|
| `LE-01.event_backfill.v1.json` | Ops **exist**; `enabled: false`; `irreversible: true` |
| `registry.json` | `enabled: false` |
| Possible sheet | disabled; blocker `event_ingest_rollback_limited` |
| Adapter | `event_ingest` → `batchAddContactExtEvent` **implemented** |
| Rollback | Strategy `tagged_backfill_delete` — **limited / may not fully reverse events** |

### 5.2 Target

| Change | Detail |
|--------|--------|
| Registry + mapping `enabled` | `true` |
| Keep `irreversible: true` | Required |
| `operator_disclosure` | Keep / sharpen: *Bulk PURCHASE event backfill may not be fully reversible. Rollback best-effort only.* |
| Allowlist | Seed `LE-01` enabled |
| Sheet | `write_possible_today=yes`; `rollback_possible_today=limited` (not `yes`) |

### 5.3 Evidence bind

Mapping already expects paths like `side=missing_purchase_event`, `order.id`, `person.email`, etc.  
**Verify** against a real LE-01 FAIL evidence blob from DCS. If paths drifted, fix mapping paths in this PR — do not change the DCS executor (Engineering) unless blocked; prefer mapping-only fix. If executor change is unavoidable, stop and escalate — do not silently reshape scores.

### 5.4 Fix UI — irreversible

When `irreversible` (or sheet `rollback_possible_today=limited|no`):

| UI | Behavior |
|----|----------|
| Approve | Still allowed when Settings ON + Admin + gates |
| Before Approve | Show mapping `operator_disclosure` (modal or trust-step copy) |
| After Written | Rollback button: **hidden** or **enabled with “best effort / may not fully reverse”** — pick one; prefer **show with warning** if rollback endpoint exists, else hide + honest “No full rollback” |
| Toast | Never “Fully reversed” if strategy cannot guarantee it |

### 5.5 Once-per-run / claim

Same WB-04/07 rules: one successful execute per `(company, LE-01, dcs_data_run_id)` until rollback-or-newer-run.  
If rollback is best-effort and leaves events in Manago, gate semantics stay: **rolled_back_at set → gate open**; do not claim data was fully undone in audit summary.

---

## 6. Allowlist + migration

### 6.1 `WritebackAllowedCheck`

New data migration (follow `0025_writeback_allowed_check.py`):

```text
get_or_create check_id=SP-01, enabled=True
get_or_create check_id=LE-01, enabled=True
```

Do **not** remove CI-01 / CC-03 / WB-SHOP-01.  
Do **not** seed CI-03 / LE-04.

### 6.2 Execute gate (unchanged formula)

```text
execute_allowed =
  check in WritebackAllowedCheck(enabled=True)
  AND company.writeback_execute_enabled
  AND Admin + approval_id + diff_hash (WB-03…07)
  AND once-per-run claim (WB-04/07)
```

---

## 7. Possible sheet + matrix

### 7.1 CSV rows to update (`WRITEBACK_POSSIBLE_NOT_SHEET.csv`)

**SP-01** — set approximately:

| Column | Value |
|--------|--------|
| `write_possible_today` | `yes` |
| `rollback_possible_today` | `yes` |
| `registry_enabled` | `true` |
| `blocker` | empty |
| `evidence_note` | Catalogue Automated writeback; tag_add `klints:…`; gated by Settings Allow writebacks |
| `last_verified` | ship date |

**LE-01** — set approximately:

| Column | Value |
|--------|--------|
| `write_possible_today` | `yes` |
| `rollback_possible_today` | `limited` |
| `registry_enabled` | `true` |
| `blocker` | empty or `rollback_best_effort` |
| `evidence_note` | event_ingest PURCHASE; irreversible disclosure required; Settings gated |
| `last_verified` | ship date |

Keep LE-04 / CI-03 / order rows **disabled** as today.

Also update runtime copy under `dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv` (Docker SoT — not only `docs/`).

### 7.2 `WRITEBACK_SURFACE_MATRIX.md`

- Manago **Contact tags** row: note **SP-01 enabled** (not stub).  
- Manago **Transaction / purchase event** row: note **LE-01 enabled** with irreversible disclosure.  
- Enabled mappings table: add SP-01 + LE-01.

---

## 8. Reuse existing harden (do not regress)

| PRD | Must still hold for SP-01 / LE-01 |
|-----|-----------------------------------|
| WB-03 | Settings default OFF; Admin toggle |
| WB-04 / WB-07 | Once-per-run + claim before adapter I/O |
| WB-06 | Status / Written restore after refresh |
| WB-07 | Mask entity_key / no exc leaks |
| POLISH-01 | Audit append-only; Fix/shell honesty |

**Audit actions** (reuse existing writeback audit event names if present; do not invent a second system):

| Event | When |
|-------|------|
| Existing writeback execute / rollback actions | SP-01 / LE-01 jobs |
| Metadata | `check_id`, `job_id`, `dcs_data_run_id`, irreversible flag for LE-01 |

Bell / Activity deep-links to Fix already from FE-13 — verify they still work for new check ids (`/fix?issue=SP-01`, `/fix?issue=LE-01`).

---

## 9. Frontend (minimal)

Prefer **no Fix redesign**. Only:

1. Allowlist-driven Approve already works for any allowlisted check — confirm SP-01 / LE-01 appear when FAIL on worklist.  
2. Wire **irreversible / limited rollback** disclosure for LE-01 (§5.4) if missing.  
3. Download evidence (FE-12) stays available for non-writable and writable alike — no change required unless broken.  
4. **Never** toast “Sent to Manago agent” / Handoff language on Fix Approve.

---

## 10. Tests + verify

### 10.1 Backend tests (add/extend)

| Case | Expect |
|------|--------|
| Registry loads SP-01 + LE-01 enabled | Mapping ops non-empty for SP-01 |
| Preview SP-01 with fixture evidence | ≥1 `tag_add` intent, tag starts with `klints:` |
| Preview LE-01 with fixture evidence | ≥1 `event_ingest` intent with externalId |
| Execute denied when Settings OFF | `writebacks_disabled` |
| Execute denied when not allowlisted | unchanged for CI-03 / LE-04 |
| Allowlist contains SP-01 + LE-01 after migrate | |
| LE-01 mapping `irreversible` true | exposed to FE/API if already in preview payload |
| Concurrent double Approve | 409 (WB-07) |
| Rollback SP-01 | removes tag |
| Rollback LE-01 | best-effort; does not claim full undo in summary |

### 10.2 Verify script

Add or extend:

```text
scripts/verify_wb08_catalogue_wave2.py
```

Checks: registry enabled flags · allowlist rows · possible sheet `write_possible_today` for SP-01/LE-01 · LE-04 still disabled · CI-03 still disabled.

Optional FE: only if disclosure copy is asserted via string fixture — otherwise BE verify is enough.

---

## 11. Loom / staging proof (Engineering owns)

Short recording (can be one Loom, two chapters):

1. Settings → Allow writebacks **ON**.  
2. **SP-01** FAIL → Approve → tag visible in Manago → Rollback → tag gone.  
3. **LE-01** FAIL → disclosure shown → Approve → event visible in Manago → note rollback limited.  
4. Settings **OFF** → Approve disabled / denied.

Attach link in PR description. Does **not** block Engineering HO-02 merge.

If no FAIL evidence on demo tenant: seed/sandbox path (same honesty as WB-01B CC-03 fallback) **or** document skip with owner — do not fake Written.

---

## 12. Acceptance checklist

- [ ] SP-01 mapping has real `tag_add` operations; registry `enabled=true`  
- [ ] LE-01 registry `enabled=true`; irreversible disclosure visible before Approve  
- [ ] `WritebackAllowedCheck` seeds SP-01 + LE-01; CI-03 / LE-04 still off  
- [ ] Possible sheet + SURFACE matrix updated  
- [ ] Settings OFF → neither check executes  
- [ ] Settings ON → Approve writes via existing Manago adapter  
- [ ] SP-01 rollback removes `klints:` tag  
- [ ] LE-01 does not claim full reverse  
- [ ] WB-04/07 once-per-run + claim-before-write still hold  
- [ ] Audit events appear on Activity/bell for execute (and rollback when used)  
- [ ] No edits under `dataruns/use_cases/handoff*` / FE `/handoff`  
- [ ] Verify script green  
- [ ] Loom notes or video linked in PR  

---

## 13. Explicit non-goals (collision guard)

| Do not | Owner / later |
|--------|----------------|
| Handoff Send / approve / ACTIVATED | Engineering HO-02 |
| MCP workflow publish / Track B | Engineering CAP-01B |
| 8-state ORCH SM | Negotiate / Engineering |
| CI-03 merge execute | Future WB-10+ |
| LE-04 enable | Pack forbids automated |
| `/lifecycle` AF changes | Engineering AF-01 |
| Catalogue score / DCS-09/10 | Engineering (done) |

---

## 14. Expected data models / API (no new public surface preferred)

### 14.1 Prefer reuse

| Existing | Use for |
|----------|---------|
| `POST /api/v1/writebacks/run/` | preview / execute / rollback |
| `POST /api/v1/writebacks/approvals/` | approval gate |
| `GET /api/v1/writebacks/possible/` | sheet truth |
| `GET /api/v1/writebacks/status/` | Written restore (WB-06) |
| `WritebackJob` | job + intents + rollback snapshot |
| `WritebackApprovalToken` | approve bind |
| `WritebackAllowedCheck` | allowlist |
| `Company.writeback_execute_enabled` | Settings gate |

### 14.2 New / changed rows only

| Model / file | Change |
|--------------|--------|
| `WritebackAllowedCheck` | + SP-01, + LE-01 via migration |
| `registry.json` | enable SP-01, LE-01 |
| `SP-01.tag_consolidation.v1.json` | fill `operations`, `enabled: true` |
| `LE-01.event_backfill.v1.json` | `enabled: true` (ops already present) |
| Possible CSV | §7 |

**No new Django models** unless claim-before-write forces a column already planned in WB-07 (do not invent parallel job tables).

### 14.3 Preview / execute response expectations

Unchanged envelope; new checks appear as:

```json
{
  "check_id": "SP-01",
  "intents": [
    {
      "op_kind": "tag_add",
      "target": "manago",
      "entity_key": "<masked>",
      "payload": { "tag": "klints:…", "email": "…" }
    }
  ],
  "diff_hash": "…",
  "irreversible": false
}
```

```json
{
  "check_id": "LE-01",
  "intents": [
    {
      "op_kind": "event_ingest",
      "target": "manago",
      "entity_key": "<masked>",
      "payload": { "externalId": "…", "email": "…", "eventType": "PURCHASE" }
    }
  ],
  "diff_hash": "…",
  "irreversible": true,
  "operator_disclosure": "Bulk PURCHASE event backfill may not be fully reversible…"
}
```

(Field names must match **existing** serializer — adapt to current keys; do not rename the public API in this PR.)

---

## 15. Code reference map (start here)

| Path | Role |
|------|------|
| `dataruns/writebacks/mappings/SP-01.tag_consolidation.v1.json` | Fill ops |
| `dataruns/writebacks/mappings/LE-01.event_backfill.v1.json` | Flip enabled |
| `dataruns/writebacks/mappings/registry.json` | Enable both |
| `dataruns/writebacks/adapters/manago.py` | `tag_add` / `event_ingest` execute + rollback |
| `dataruns/writebacks/transform.py` | `_tag_add_payload` / `_event_ingest_payload` |
| `dataruns/writebacks/gates.py` | allowlist |
| `dataruns/writebacks/pipeline.py` / `run_gate.py` | execute order |
| `dataruns/writebacks/possible_sheet.py` + CSV | honesty API |
| `dataruns/migrations/0025_writeback_allowed_check.py` | seed pattern |
| `docs/engineering/WRITEBACK_SURFACE_MATRIX.md` | docs SoT |
| FE `src/routes/fix.tsx` | irreversible disclosure |
| **Forbidden:** `dataruns/use_cases/handoff*` · `src/routes/handoff.tsx` | Engineering |

---

## 16. Branch / PR

- Branch: `feature/wb-08-catalogue-wave2-sp01-le01`  
- BE title: `feat(WB-08): enable SP-01 tag + LE-01 event writebacks`  
- FE title (only if disclosure needed): `feat(WB-08): LE-01 irreversible disclosure on Fix`  
- PR body: link this PRD · Loom · “independent of HO-02”  
- Merge order: BE first (mapping + allowlist), then FE if any  

---

## 17. Traceability

| Field | Value |
|-------|--------|
| Milestone | M2 — Writeback + Lifecycle depth (T2) |
| Contract | Schedule 1 M2 bundle: Writeback + Lifecycle live |
| Parents | WB-03…07 · FE-08/09 · POLISH-01 |
| Parallel | Engineering HO-02 (no dependency) |
| Next | Optional WB-09 Shopify metafield · or WB-10 CI-03 (separate) · E2E-01 Loom |
| Independent of | Handoff Send · Track B · 8-state SM · DCS-09/10 |
