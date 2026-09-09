# PRD-FE-11B — Elements = platform source field (`api_key`)

**Status:** Ready for implementation  
**Owner track:** Engineering   
**Depends on:** FE-11 merged ([BE #39](https://github.com/georgechief/klints_backend/pull/39) / [FE #27](https://github.com/georgechief/klints_frontend/pull/27))  
**Corrects:** FE-11 display priority — Elements must show the **platform source field** for that row’s connector, not a marketing / side label  
**Consult Engineering:** only if changing executor provenance; this PRD is worklist display + enrichment priority only  
**Out of scope:** Writebacks · changing PASS/FAIL · inventing fields not in `map.json` / Catalogue surfaces

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-FE-11B — Elements column = platform api_key for that source.

Read: docs/engineering/PRD_FE_11_EVIDENCE_ELEMENTS_FROM_MAP.md
Read: docs/engineering/PRD_FE_11B_ELEMENTS_PLATFORM_API_KEY.md

Bug after FE-11: Elements shows human labels like
“Contact state (dead/blocked/resigned)” instead of platform fields
like contact.email / order.value / order.total_price.

Must:
1. Display = `{entity}.{api_key}` when both known (map entity singular).
2. Never prefer element_label / side prose over api_key.
3. BE: resolve map.json api_key for row.source before inventing side labels.
4. Shopify amount ≠ Manago amount keys (total_price vs value).
5. Aggregates with no map field: short id like contact.state — not marketing copy.

Acceptance: §5.
```

---

## 1. What went wrong

| Layer | FE-11 intent | What shipped |
|-------|--------------|--------------|
| Product | Elements = **which platform field** the diff is on | Humanized **side / check defaults** |
| PRD §1 / §4.2 | Show `map.json` **`api_key`** for that source | Often never reaches UI |
| PRD §3.2 order | Listed `element_label` **before** `api_key` | FE followed that → labels win |
| BE enrich | Fill `api_key` from map when possible | Fills `element_label` from `_SIDE_LABELS` / `_CHECK_DEFAULTS` aggressively |

**User bar (normative now):** Elements = **`{entity}.{api_key}`** for that row’s platform  
(map `entity` is singular: `contact` / `order` — **not** prose labels).

Examples:

| Where (source) | Elements should show |
|----------------|----------------------|
| Shopify · contact email | `contact.email` |
| Shopify · order amount | `order.total_price` |
| Manago.ai · contact email | `contact.email` |
| Manago.ai · transaction amount | `order.value` |
| Manago.ai · transaction id | `order.transactionId` |
| Field mismatch both sides | Each row uses **that row’s** platform `api_key` (Shopify `order.total_price` ≠ Manago `order.value`) |

Do **not** show: `Purchase value parity`, `Contact state (dead/blocked/resigned)…`.

---

## 2. Corrected display order (replaces FE-11 §3.2)

`friendlyEvidenceElement` **must** use:

1. If **`entity` + `api_key`** → show **`{entity}.{api_key}`** (canonical display, e.g. `order.value`)  
2. Else **`api_key` alone** if entity missing  
3. `db_key` / `field` only if no `api_key` (prefer `entity.db_key` when entity known)  
4. Catalogue / map surface field string if BE attached one  
5. Locator leaf if non-placeholder and looks like a field path  
6. `element` machine id already dotted (e.g. `contact.state`) — OK as technical fallback  
7. Humanized `side` / metric — **only** when no field metadata exists (true aggregates)  
8. `"—"`

**Do not use `entity` pluralization** (`orders.value`) unless product later locks collection names; SoT is map `entity` → `order` / `contact`.  
**Do not use `element_label` for the Elements column.**  
Keep `element_label` optional for other copy (“What we found”) if useful.

---

## 3. Backend enrichment rules (additive)

In `enrich_evidence_element`:

1. Resolve `source` → platform (`shopify` \| `manago_ai`).  
2. If `entity` + `db_key` known → set **`api_key` from that platform’s `map.json`** (required when a map row exists).  
3. If evidence already has a platform field name in value (e.g. `email`) → set `db_key`/`api_key` accordingly.  
4. **Stop preferring side labels as `element_label` for Elements.** Side labels may still help “What we found.”  
5. For CI-13-style aggregates with **no** mapped contact field: set `element` to the Manago surface being scored (e.g. contact state property / catalogue Manago Surface text) — not “Shopify & Manago”. Do **not** invent a Shopify `api_key`.  
6. Never invent `api_key` values that are not in `map.json` or the check’s documented surface.

---

## 4. Acceptance fixtures

| Case | Elements |
|------|----------|
| CI-01 email mismatch · Shopify row | `contact.email` |
| CI-01 email mismatch · Manago row | `contact.email` |
| Order value · Shopify | `order.total_price` |
| Order value · Manago transaction | `order.value` |
| CI-13 dead_state · no map field | `contact.state` (or Catalogue surface id) — **not** long prose |
| Placeholder locator `—` | Must not block `entity.api_key` display |

Verify script: update `verify:fe11` / add `verify:fe11b` — assert **api_key wins over element_label**.

---

## 5. Acceptance checklist

- [ ] Elements column prefers **`api_key`** over `element_label` / side prose  
- [ ] Field-level checks show platform source field from correct `map.json` for `source`  
- [ ] Shopify vs Manago rows can show different api_keys for the same canonical `db_key`  
- [ ] No regression to blank `"—"` when `api_key` or side exists  
- [ ] FE-09 still: no raw JSON in Details  
- [ ] Unit + verify scripts updated  

---

## 6. One-page

| Question | Answer |
|----------|--------|
| Bug? | Elements = friendly labels, not platform fields |
| Fix? | Show `{entity}.{api_key}` e.g. `order.value` |
| SoT? | `connectors/{shopify,manago_ai}/map.json` |
| Who? | Engineering |

**PRD:** FE-11B · **Track:** Engineering · **Bar:** Elements = platform source field
