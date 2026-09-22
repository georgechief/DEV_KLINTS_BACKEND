# PRD-FE-11 — Evidence “Elements” = platform field / model from connector map

**Status:** Ready for implementation  
**Owner track:** Maheep (`docs/maheep/`) — FE + worklist display enrichment  
**Consult:** **Sahil** when BE touches check executors / provenance shape / worklist contracts he owns (`docs/sahil/`) — do not silently change DCS result semantics without him  
**Depends on:** FE-09 (friendly evidence table) · connector `map.json` · DCS worklist detail  
**Pack / product:** Operators must see **which field/model** the difference was found on (Shopify / Manago API names), not blank “—”  
**Out of scope:** Writeback execute · changing check PASS/FAIL logic · inventing fields not in evidence or map

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-FE-11 — Elements column from connector map / field metadata.

Read: docs/maheep/PRD_FE_11_EVIDENCE_ELEMENTS_FROM_MAP.md
Screenshot bug: Differences Found → Elements = "—" for CI-13 etc.

Root cause (understand before coding):
1. Many mismatch rows are bare dicts {side, count, …} with NO locator/field.
2. worklist _normalize_evidence_item sets locator="—" when missing.
3. FE friendlyEvidenceElement() prefers locator leaf BEFORE side —
   so leaf "—" wins and side/field never show.

Fix both sides:
BE: enrich evidence/mismatch rows with entity + field metadata
    (db_key / api_key / platform) from check + map.json when known.
FE: ignore placeholder locators ("—", empty); resolve Elements from
    element | field | api_key | db_key | map lookup | side; never show "—""
    as a real element label when better data exists.

Acceptance: §6. Verify on CI-13 and at least one field-level check (e.g. CI-01).

Consult Sahil if you change executor provenance shapes, CheckResult
contracts, or worklist detail fields beyond additive element metadata.
```

---

## 0b. When to consult Sahil

| Situation | Who |
|-----------|-----|
| FE-only: fix `friendlyEvidenceElement` resolve order / placeholder `"—"` | Maheep alone |
| Additive API fields on evidence rows (`element`, `api_key`, `db_key`, `entity`) via worklist normalize | Maheep; **ping Sahil** for a quick review on the PR |
| Changing what executors put in `provenance.mismatches` / `evidence` (CI-13, CI-01, …) | **Consult Sahil first** — he owns DCS check/result surface |
| Renaming/removing existing evidence keys FE already consumes | **Must consult Sahil** — breaking change |
| Unsure whether a check’s “element” is a map field vs drift metric | **Ask Sahil** for the check’s intended surface |

Sahil track pointer: `docs/sahil/README.md` (DCS / worklist / related PRDs). Leave a short note on the PR: “Sahil consulted: yes/no — …”.

---

## 1. Bug (from live UI)

**Differences found** (CI-13 — Contact state distribution sanity):

| Where | What we found | Details | Elements | Checked |
|-------|---------------|---------|----------|---------|
| Shopify & Manago | — | Count: 3 | **—** | — |

**What we checked** (same issue) already shows Elements = “Contact state distribution” because that row has a real `locator` (`drift.contact_state_distribution`).

Operators need Elements on **difference** rows too: the **platform field / model** the delta was about (and ideally the `map.json` `api_key` when it is a mapped contact/order field).

---

## 2. Code path (current)

```text
Executor provenance.mismatches
  e.g. CI-13: { side: "dead_state", bucket, count }  // no field/locator
       → worklist._normalize_evidence_item
            locator = "—" , value = {side,bucket,count}
       → FE formatFriendlyEvidenceRows
            friendlyEvidenceElement(locator="—", value)
                 → uses leaf of "—"  → displays "—"
                 → never reaches side / field fallbacks
```

Relevant files:

| Layer | File |
|-------|------|
| BE emit | `dataruns/dcs/executors/*.py` (per-check mismatches) |
| BE normalize | `dataruns/dcs/worklist.py` → `_normalize_evidence_item` |
| FE format | `src/lib/dcs.ts` → `friendlyEvidenceElement` / `formatFriendlyEvidenceRows` |
| Map | `dataruns/connectors/{shopify,manago_ai}/map.json` (`entity`, `api_key`, `db_key`) |

---

## 3. Normative Element resolution order

### 3.1 Backend — enrich before API response (preferred)

When building worklist detail / normalizing evidence, attach (when known):

```json
{
  "source": "manago_ai",
  "locator": "drift.contact_state_distribution",
  "entity": "contact",
  "db_key": null,
  "api_key": null,
  "element": "contact.state",
  "element_label": "Contact state (Manago)",
  "value": { "...": "..." }
}
```

| Field | Meaning |
|-------|---------|
| `entity` | `contact` \| `order` \| `config` \| check-specific (`event`, `drift`, …) |
| `db_key` | Canonical Klints key from `map.json` when applicable |
| `api_key` | **Platform column** from `map.json` for that `source` (e.g. Manago `email`, Shopify `total_price`) |
| `element` | Stable machine id for the thing compared |
| `element_label` | Optional human label for FE |

**Rules:**

1. If the check compares a **mapped** contact/order field → set `entity` + `db_key` + per-source `api_key` via `load_connector_map` / reverse helpers from WB-01 `dataruns/connectors/mapping.py`.  
2. If the check is **aggregate / drift** (CI-13) → still set `element` / `element_label` to the Manago surface being scored (e.g. contact dead/blocked/resigned state), **not** leave empty. Source for difference rows should be `manago_ai` when only Manago was scanned — do not invent “Shopify & Manago” without shopify evidence.  
3. Never overwrite a rich executor-provided `element` / `api_key`.  
4. Do **not** use literal `"—"` as `locator`; use `""` or omit and let FE show “—” only as last resort.

Minimum BE change for FE-11: enrich in `_normalize_evidence_item` **or** a dedicated `enrich_evidence_element(check_id, item)` that CI-13 and field checks call into. Per-check executor updates for top FAIL/WARN checks can follow, but **worklist enrichment must fix empty Elements for current payloads**.

### 3.2 Frontend — display

`friendlyEvidenceElement` resolution order:

1. `value.element_label` / `value.element` / `value.element_name` / `value.fix_target`  
2. `value.api_key` (platform field) — prefer showing **`api_key` (`db_key`)** when both exist, e.g. `email (contact)`  
3. `value.db_key` / `value.field`  
4. `value.entity` + humanized side/bucket if present  
5. Locator leaf **only if** locator is non-empty and not placeholder (`—`, `-`, `n/a`)  
6. Humanize `value.side`  
7. `"—"`

Also fix **What we found** when value is `{side, count}` — use side/bucket, not blank.

**Where it came from:** if mismatch has no shopify signal, do not label “Shopify & Manago” (CI-13 is Manago drift).

---

## 4. Examples (acceptance fixtures)

### 4.1 CI-13 difference row (after)

| Where | What we found | Details | Elements | Checked |
|-------|---------------|---------|----------|---------|
| Manago.ai | Dead-state cluster | Spike day / Count: 3 | **Contact state** (or `contact.state` / blocked·resigned) | date if known |

### 4.2 Field-level check (e.g. email / externalId)

| Where | Elements |
|-------|----------|
| Shopify | `email` (map `api_key`) · entity contact |
| Manago.ai | `email` or `externalId` as applicable |

Show platform **api_key** from that platform’s `map.json` when the db_key is known.

### 4.3 Orders / transactions

| Platform | Entity in map | Element should show |
|----------|---------------|---------------------|
| Shopify | `order` | e.g. `id`, `total_price`, `financial_status` (api_keys) |
| Manago | `order` ← transactions collection | e.g. `transactionId`, `value`, `contactExtEventType` |

If the check only has aggregate counts, Element = the **metric/surface name**, not blank.

---

## 5. Files to touch

| Repo | Path |
|------|------|
| BE | `dataruns/dcs/worklist.py` — stop `locator="—"`; enrich element fields |
| BE | `dataruns/dcs/executors/drift.py` (CI-13) — richer mismatch objects |
| BE | Optional helper `dataruns/dcs/evidence_elements.py` using connector maps |
| BE | Tests: normalize CI-13-shaped mismatch → element non-empty |
| FE | `src/lib/dcs.ts` — `friendlyEvidenceElement` order + placeholder ignore |
| FE | `scripts/verify-fe11-frontend.mjs` (or extend fe09) — CI-13 fixture Elements ≠ "—" when side present |
| Docs | Link from FE-09; this PRD is the contract |

---

## 6. Acceptance checklist

- [ ] CI-13 (and similar) **Differences found** Elements ≠ "—" when side/field exists  
- [ ] Placeholder locator `"—"` never wins over `side` / `api_key` / `element`  
- [ ] When `db_key` is mapped, Elements includes platform **`api_key`** from that source’s `map.json`  
- [ ] Aggregate checks still get a human Element (surface/metric name)  
- [ ] “Where it came from” matches actual sources (CI-13 → Manago, not fake Shopify)  
- [ ] Unit/verify coverage for FE helper + BE normalize  
- [ ] No JSON dump regress (FE-09 still holds)  
- [ ] Sahil consulted if executor/provenance/worklist contract changed (note on PR)  

---

## 7. Relationship

| PRD | Role |
|-----|------|
| FE-09 | Friendly table + Elements column introduced |
| **FE-11** | Make Elements **correct** (map/field/model) |
| WB-01 / 01B | Writebacks consume same field metadata later |

---

## 8. One-page summary

| Question | Answer |
|----------|--------|
| Bug? | Elements blank on Differences; locator `"—"` masks side |
| Fix? | BE enrich entity/api_key/element; FE resolve order + ignore placeholders |
| Map? | Use `connectors/*/map.json` api_key for field-level diffs |
| Who? | Maheep |

**PRD:** FE-11 · **Track:** Maheep · **Bar:** Elements shows real field/model  
