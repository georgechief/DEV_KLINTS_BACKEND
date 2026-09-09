# PRD-WB-05 — Fix writeback Loom / staging proof (CI-01 · CC-03 · WB-SHOP-01)

**Status:** Ready for implementation — **P1 (M2 demo reliability)**  
**Owner track:** Engineering  — **BE + FE only if gaps found**; primarily **staging proof + Loom**  
**Surfaces:** Settings → Workspace · Fix · Connected Manago / Shopify admin UIs · Activity  
**Depends on:** WB-02 · WB-03 · (recommended) WB-04 gate so Loom does not re-Approve accidentally  
**Out of scope:** New mappings · LE-04 enable · Studio / QA / Handoff · Engineering tracks · changing pack blueprints  

---

## 0. Cursor agent brief (paste this)

```text
Execute PRD-WB-05 — staging Fix writeback Loom proof.

Read:
- docs/engineering/PRD_WB_05_FIX_WRITEBACK_LOOM_STAGING_PROOF.md
- docs/engineering/PRD_WB_03_REAL_WRITEBACK_DB_GATE_AND_LOOM.md §8 (parent Loom script)

Ship:
1. Walk §4 script on staging for Lumera (or named demo company).
2. File any product bugs as tiny follow-up commits under this PRD
   (copy, entry path for WB-SHOP-01, rollback UX) — no scope creep.
3. Attach Loom URL + checklist (§5) on the PR / Notion.
4. Confirm Settings toggle ON path; no manage.py.

Acceptance: §6.
```

---

## 1. Why

WB-03 defined the Loom. M2 still needs a **fresh, recorded proof** on current staging after later PRs (DCS enqueue guards, writeback rename, etc.). This PRD is the **acceptance artifact** plus a short fix list if anything is broken — not a new feature surface.

---

## 2. Demo company (locked for this pass)

| Item | Value |
|------|--------|
| Preferred account | Staging user used for M2 demos (e.g. `rohan1@mailinator.com` / **Lumera Skin**) |
| Connectors | Manago.ai + Shopify **connected**; Manago API v3 present if CI-01/catalog needs it |
| Settings | Admin · **Allow writebacks ON** for Loom segment only; leave OFF after recording if policy requires |
| Allowlist | CI-01 · CC-03 · WB-SHOP-01 enabled in `WritebackAllowedCheck` |

If company data lacks FAIL evidence for a check, document “skipped — no FAIL on latest run” and use Postman/fixture tenant **only** as last resort (call out in checklist).

---

## 3. What “done” means per check

| check_id | Write target | Reflect | Rollback |
|----------|--------------|---------|----------|
| **CI-01** | Manago contact upsert / `klints_backfill` (per mapping) | Visible in Manago UI | Reversed / cleared per rollback strategy |
| **CC-03** | Manago detail `klints_consent_evidence` | Visible on contact | Reversed |
| **WB-SHOP-01** | Shopify customer `note` | Visible in Shopify admin | Note restored |

Negative: **LE-04** Approve stays blocked.

---

## 4. Loom script (UI-first — required)

Video must start in the **product**, not a terminal.

### 4.1 Setup

1. Login as **Admin**.  
2. **Settings → Workspace** — show **Allow writebacks** OFF → turn **ON** → save.  
3. Optional: open Activity later for `writeback.*` events.

### 4.2 Per check (CI-01 → CC-03 → WB-SHOP-01)

1. Data Consistency → open failing issue (or `/fix?issue=<id>`).  
2. Fix → **Writeback preview** → table shows ready rows.  
3. **Approve writeback** → Written (network execute 2xx).  
4. If WB-04 shipped: refresh page → Approve stays locked / Written (optional clip).  
5. Switch to **Manago or Shopify** → show field written.  
6. Back to Fix → **Rollback** → platform shows reverse.  
7. (Optional) re-score callout — not required for this Loom.

### 4.3 Negatives (short)

- LE-04: Approve disabled / honest.  
- Toggle writebacks **OFF** → Approve blocked.

### 4.4 Entry for WB-SHOP-01

If not on worklist: document deep-link `/fix?issue=WB-SHOP-01` or Integrations/ops path. If entry is broken, **fix that path** under this PRD (small FE/BE only).

---

## 5. PR / handoff checklist (paste)

```text
WB-05 Loom: <url>
Demo company: <name>
Date: <ISO date>
Staging API host: <host>

Settings Allow writebacks shown: Y/N
manage.py used to enable: N (must be N)

CI-01: preview Y/N · execute Y/N · Manago reflect Y/N · rollback Y/N
CC-03: preview Y/N · execute Y/N · Manago reflect Y/N · rollback Y/N
WB-SHOP-01: preview Y/N · execute Y/N · Shopify reflect Y/N · rollback Y/N
LE-04 blocked: Y/N

WB-04 gate on refresh (if merged): Y/N/NA
Bugs fixed in this PR: <list or none>
```

---

## 6. Acceptance

- [ ] Loom URL attached and follows §4  
- [ ] Checklist §5 completed (Y/N per row; skips explained)  
- [ ] Settings UI used to enable — **not** manage.py  
- [ ] Any entry/copy/rollback bugs found during recording are fixed or explicitly deferred with ticket id  
- [ ] No Engineering surface changes  

---

## 7. Allowed code fixes under this PRD

| Allowed | Not allowed |
|---------|-------------|
| WB-SHOP-01 deep-link / empty-state copy | New check mappings |
| Rollback button visibility / confirm copy | Handoff Send |
| Toast / error message clarity for execute | Studio Proceed / QA engine |
| Allowlist seed if missing on staging | Capability Matrix |

Larger gate work → WB-04 / WB-06, not here.

---

## 8. PR title / branch

- Branch: `chore/wb-05-writeback-loom-staging-proof` (or docs-only + tiny fixes)  
- Title: `chore(WB-05): staging Fix writeback Loom proof (CI-01/CC-03/WB-SHOP-01)`

---

## 9. Traceability

| Item | Note |
|------|------|
| Parent Loom | WB-03 §8 |
| Milestone | M2 — Fix demo readiness for T2 |
| Independent of | Engineering HO-01 · CAP-01 · pilot seed (ops) |
