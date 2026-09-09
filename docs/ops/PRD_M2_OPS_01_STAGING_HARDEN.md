# PRD-M2-OPS-01 — Staging harden + Fix support (parallel with DCS-09)

**Status:** Ready for execution — **P0 (M2 ops)** · no new product feature  
**Owner track:** Engineering  — **staging / Fix / writeback smoke · bugfix only**  
**Surfaces:** Staging deploy · Settings writebacks · Fix (CI-01 / CC-03 / WB-SHOP-01) · Activity/bell · shell honesty  
**Depends on:** WB-03…WB-07 · POLISH-01 · OPS-UC-01 seed · FE-13  
**Parallel:** Engineering **DCS-09** (`docs/engineering/PRD_DCS_09_PILOT_SUPPLEMENTAL_GATES.md`)  
**Out of scope:** New Catalogue writeback mappings · HO-02 MCP Send · CAP-01B discovery · CAP registry unify · Studio / QA / Handoff features · inventing Ready without Engineering gates · BL-017  

---

## 0. Cursor agent brief (paste this)

```text
Execute PRD-M2-OPS-01 — staging harden + Fix support while Engineering ships DCS-09.

Read:
- docs/engineering/PRD_M2_OPS_01_STAGING_HARDEN.md (this file)
- docs/engineering/PRD_OPS_UC_01_SEED_MVP1_PILOTS_ON_DEPLOY.md
- docs/engineering/PRD_WB_05_FIX_WRITEBACK_LOOM_STAGING_PROOF.md (Fix segment)
- docs/engineering/PRD_DCS_09_PILOT_SUPPLEMENTAL_GATES.md (do NOT implement — support only)

Ship:
1. Run §3 staging readiness checklist on Lumera (or named demo tenant).
2. Fix smoke: Settings Allow writebacks ON → Approve one allowlisted check → Written + 409 re-Approve → optional rollback (§4).
3. Fix only blockers found (copy, deep-link, gate, deploy) — tiny PRs under this PRD.
4. When Engineering merges DCS-09: re-smoke Fix + shell; confirm UC-02 Ready path does not break writebacks/worklist (§5).
5. Fill §6 checklist; attach notes for E2E-01 (next).

Acceptance: §7. No new mappings. No Studio/QA/Handoff feature work.
```

---

## 1. Why

Engineering owns the last **structural** Build gap (**DCS-09** → UC-02 hard-green Ready).  
Engineering’s writeback harden track (**WB-07**) is done. Claim still needs **staging that actually works** before E2E Loom.

Without this PRD:

| Risk | Effect |
|------|--------|
| Pilots / migrate / audit triggers missing on staging | Studio 404 / broken path |
| Writebacks OFF or allowlist wrong | Fix segment of E2E fails |
| Silent Fix regressions after DCS-09 | Claim Loom blocked mid-recording |
| Scope creep into CAP unify / mappings | Delays claim |

**M2-OPS-01** is the **ops + Fix support contract** so E2E-01 can record cleanly.

---

## 2. Product rules

```text
1. No new product surface — verify, smoke, bugfix only.
2. Demo tenant stays honest: writebacks Settings-gated; LE-04 stays blocked.
3. Do not “help” DCS-09 by faking supplemental PASS or changing 42 assemble.
4. Bugfixes that touch Studio/QA/Handoff only if they block staging smoke — prefer Engineering for those.
5. After checklist green → stop. E2E-01 is a separate PRD.
```

---

## 3. Staging readiness checklist (run once per deploy)

**Tenant (locked for this pass):** staging demo used for M2 (e.g. `rohan1@mailinator.com` / **Lumera Skin**).

### 3.1 Backend / deploy

| # | Check | Pass when |
|---|--------|-----------|
| 1 | Latest `main` (or release tag) deployed BE + FE | Health 200; FE talks to staging API |
| 2 | Migrations applied (incl. audit immutability + WB-07) | `migrate` clean; no pending |
| 3 | Pilots seeded | `UseCasePilot` count = **16**; **UC-02** present (`verify_use_case_pilots.py` or shell) |
| 4 | CAP-01 / HO-01 / WB-07 verify scripts (smoke) | Optional: run `scripts/verify_*` that already exist; note failures |
| 5 | Celery / Beat healthy enough for DCS | Manual or on-connect score can finish |

### 3.2 Connectors + Diagnose

| # | Check | Pass when |
|---|--------|-----------|
| 6 | Manago + Shopify connected | Integrations show Connected; Manago API v3 if catalog needed |
| 7 | Terminal DCS score exists | Overview / Data Center live; worklist not empty-or-stuck forever |
| 8 | Fix deep-link works | `/fix?issue=CC-03` (or live FAIL id) binds real issue |

### 3.3 Writeback gate (Engineering SoT)

| # | Check | Pass when |
|---|--------|-----------|
| 9 | Settings → Workspace **Allow writebacks** | Admin can toggle; persists after refresh |
| 10 | Allowlist | CI-01 · CC-03 · WB-SHOP-01 executable when toggle ON |
| 11 | LE-04 | Approve still blocked |

Document skips: “no FAIL evidence for CI-01 on latest run” — use another allowlisted FAIL or note for E2E.

---

## 4. Fix smoke (required)

Minimum path (10–15 min). Prefer **CC-03** if FAIL on latest run; else CI-01 / WB-SHOP-01.

1. Toggle **Allow writebacks ON** → Save.  
2. Open Fix for allowlisted FAIL → Approve writeback.  
3. Confirm **Written** + provenance after refresh (WB-06).  
4. Re-Approve → **409** once-per-run (WB-04/07).  
5. Optional: Rollback → gate re-opens.  
6. Bell / Activity: executed (or rolled back) entry deep-links honestly (FE-13 / POLISH-01).  
7. Toggle writebacks **OFF** after smoke if policy requires.

**If broken:** file a **tiny** PR under this PRD (copy, status endpoint, Settings save). Do not expand mappings.

Cross-ref script detail: [PRD_WB_05](./PRD_WB_05_FIX_WRITEBACK_LOOM_STAGING_PROOF.md) §4 — reuse; do **not** require a full three-check Loom here (that’s E2E / WB-05 residual).

---

## 5. Support Engineering DCS-09 (do not implement)

| Engineering does | Engineering does **not** |
|-------------|---------------------|
| Re-run Fix smoke after DCS-09 merge | Implement supplemental evaluators |
| Confirm worklist still **42** headline issues | Add CI-08/CC-06 to `assemble_dcs_score` |
| Confirm Fix download / Approve unchanged for allowlisted 3 | Map writebacks for the 12 supplementals |
| Report if Studio Ready unlock breaks Fix CTAs | Change recommend / pilot gate labels |

If DCS-09 needs a Fix surface (e.g. “Evaluate pilot gates” button lives near Fix): **Engineering owns FE**; Engineering only unblocks collisions (shared components, shell lock).

---

## 6. Handoff notes for E2E-01 (fill before Loom)

Paste into E2E PR / Notion when green:

```text
M2-OPS-01 staging notes
- Date / env:
- Tenant:
- Pilots count / UC-02:
- Latest DCS run id:
- Writebacks toggled for smoke (Y/N); check used:
- Fix smoke result (Approve / 409 / rollback):
- Known skips:
- Blockers fixed under this PRD (PR links):
- Ready for E2E-01 Loom: YES / NO
```

---

## 7. Acceptance

- [ ] §3 checklist completed on staging (or explicit skip + owner)  
- [ ] §4 Fix smoke green for ≥1 allowlisted check  
- [ ] LE-04 still blocked  
- [ ] No new Catalogue mappings merged  
- [ ] After DCS-09 (when available): Fix + worklist re-smoke OK  
- [ ] §6 notes filled for E2E-01  
- [ ] Any bugs fixed as small PRs titled under `M2-OPS-01` / this PRD  

---

## 8. Explicitly not this PRD

| Later | Owner |
|-------|--------|
| **DCS-09** implement | Engineering |
| **E2E-01** full journey Loom + T2 submission | Engineering lead · Engineering Fix segment |
| **CAP-UNIFY-01** Matrix ↔ writeback JSON | Optional post-claim |
| Catalogue writeback wave | Engineering post-M2 |
| **HO-02** / CAP-01B | Post-claim |

---

## 9. PR title / branch

- Branch: `chore/m2-ops-01-staging-harden` (or fix branches `fix/m2-ops-01-…`)  
- Title examples:  
  - `chore(M2-OPS-01): staging readiness + Fix smoke notes`  
  - `fix(M2-OPS-01): …` for blockers only  

---

## 10. Traceability

| Item | Note |
|------|------|
| Milestone | M2 — staging green before T2 claim Loom |
| Parents | WB-05 · WB-07 · OPS-UC-01 · POLISH-01 · FE-13 |
| Parallel | Engineering DCS-09 |
| Next | E2E-01 |
