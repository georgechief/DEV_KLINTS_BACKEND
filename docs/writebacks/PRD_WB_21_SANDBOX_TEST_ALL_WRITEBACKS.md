# PRD-WB-21 — Sandbox test for every writeback (harness + phased coverage)

**Status:** **Phase A–D done** — full matrix harness + Phase D honesty/live hooks · P0 · honesty + test contract (not a new writeback mapping)  

**Owner track:** Maheep / Sahil — **BE primary · FE honesty only**  
**Surfaces:** Settings Allow writebacks · Fix `/fix` Preview → Approve → execute → Rollback · `WritebackAllowedCheck` · possible sheet · pytest harness · optional live env suite  
**Depends on:** WB-01…WB-20 · WB-03 Settings gate · WB-04 once-per-run · FE allowlist  
**PRD path:** `docs/writebacks/`  
**Supersedes (scope clarification):** WB-01B / WB-02 / WB-03 language that implied sandbox was **only** CI-01 / CC-03 / WB-SHOP-01 forever. Those three were the **first wave**; the **sandbox-test contract applies to every shipped writeback**.  

**Out of scope:**  
- New connector ops / new catalogue mappings  
- Demo/fixture “Sandboxed … Passed” UI badges as proof  
- Global `WRITEBACKS_ENABLED=True` for all tenants  
- Renaming every historical doc string in one PR (naming cleanup is Phase D, optional)  
- Requiring live Manago/Shopify credentials for CI (mocked transports are enough for Phase A–C)

---

## 0a. Original sandbox behaviour (must preserve in contract)

First-wave sandbox (WB-01B → WB-02 → WB-03) was **not** a background health check and **not** a Fix DCS PASS badge. It was:

| Step | Original behaviour | Still true today? |
|------|--------------------|-------------------|
| Gate | Company allowed to execute (env `WRITEBACK_SANDBOX_COMPANY_IDS`, then DB `writeback_sandbox_enabled`) | **Evolved** → `writeback_execute_enabled` / Settings **Allow writebacks** (WB-03). Env company-id list is **gone**. |
| Modes | Preview `dry_run` → execute (`sandbox_execute` alias) → rollback | **Yes** — `sandbox_execute` still accepted, reported as `execute` |
| Caps | `WRITEBACK_SANDBOX_MAX_ROWS` (often **1** for proof) | **Yes** — still default ceiling for early checks; later checks override with capability batch max |
| Manago proof | **CI-01** and/or **CC-03** real adapter write + rollback | **Yes** — still Tier A |
| Shopify proof | **WB-SHOP-01** customer `note` write + rollback | **Yes** — still Tier A |
| Evidence (CC-03) | Prefer DCS `shopify_holds_evidence`; if Allow writebacks ON and no FAIL rows → **`_cc03_sandbox_evidence_rows`** from Manago contacts | **Still in code** — original proof path; see §2.5 |
| Evidence (WB-SHOP-01) | Shopify `Contact` rows → `sandbox_customer_note` (often **no** DCS worklist FAIL) | **Still in code** — original proof path |
| Approval | WB-01B Postman path often without approval; WB-02 FE always sent approval; WB-03+ BE **requires** `approval_id` when company execute ON | **Today: approval required** — harness must use `issue_approved_writeback_token` |
| Kill switch | `WRITEBACKS_ENABLED=False` for prod | **Yes** |
| Dual connector | Must prove **Manago + Shopify**, not Manago-only | **Phase A must include all three checks** (covers both) |

**WB-21 does not invent a new meaning of sandbox.** It (1) freezes that contract as an automated harness, and (2) extends the **same** contract to every later writeback (Tier A/B/C).

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-WB-21 — sandbox test contract for ALL writebacks.

Read:
- docs/writebacks/PRD_WB_21_SANDBOX_TEST_ALL_WRITEBACKS.md (this file)
- dataruns/tests/writeback_helpers.py
- dataruns/tests/test_writeback_01c.py (gold path: preview → approve → execute → rollback)
- dataruns/tests/test_writeback_sandbox_integration.py (legacy live CC-03 only — extend/replace)
- dataruns/writebacks/gates.py · pipeline.py · WRITEBACK_POSSIBLE_NOT_SHEET.csv
- FE: src/lib/writebacks.ts WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS

Ship in phases (§6):
1. Shared BE harness `assert_writeback_sandbox_pass` / plan_only / execute_blocked variants (§5).
2. Phase A — original 3: CI-01, CC-03, WB-SHOP-01 (mocked transports).
3. Phase B — remaining Tier A execute checks.
4. Phase C — Tier B plan_only + PT-03 execute-blocked + disabled skips.
5. Phase D (optional) — live env suite + naming honesty (no fake Fix PASS).

Do NOT invent a second “sandbox mode.”
Do NOT treat demo fixtures / klints-data badges as pass.
Do NOT require DCS FAIL for WB-SHOP-01 (Shopify Contact seed is the original proof).
Do NOT skip approval_id (current gate requires it when Allow writebacks ON).
Preserve Phase A dual-connector bar (CI-01 + CC-03 + WB-SHOP-01).
Acceptance: §9.
```

---

## 1. Why

| Confusion | Reality in codebase |
|-----------|---------------------|
| “Sandbox” is a background API health check | **No** — not implemented |
| Sandbox = only CI-01 / CC-03 / WB-SHOP-01 forever | **No** — those were **first implemented** writebacks; old PRDs stopped there |
| Sandbox = demo PASS on Fix | **No** — fixtures in `klints-data` are not proof |
| Settings “sandbox checkbox” | Product gate is **Allow writebacks** (`writeback_execute_enabled`); API still exposes `execute_eligible.sandbox` as a **legacy name** for that flag |

**Product rule (locked):** every writeback check must have a **sandbox test** = prove the Fix/API contract for that check against the real pipeline (mocked or live connectors).

```text
Settings Allow writebacks ON
  → POST /writebacks/run/ preview (dry_run)
  → approval token (Admin)
  → execute (or honest block for plan_only / capability)
  → rollback when sheet/mapping supports it
```

There is **no** separate sandbox runtime mode. `sandbox_execute` is a legacy alias of `execute`.

---

## 2. Definition — sandbox test

### 2.1 Pass (Tier A — mutate)

For check_id with possible sheet `write_possible_today=yes` and FE/BE execute allowlisted:

1. Company `writeback_execute_enabled=True`
2. `WritebackAllowedCheck` enabled for that check
3. Evidence available (§2.5) so preview can produce `ready >= 1`
4. Preview: `summary.ready >= 1`, valid `diff_hash`, `job_id`
5. Admin actor + approved `approval_id` (current WB-03/04 gate — not optional)
6. Execute: `summary.executed >= 1` (adapter called); respect once-per-DCS-run gate (WB-04) — use fresh run or rollback between retests
7. Rollback when mapping/sheet supports it (`yes` / `limited`); otherwise assert honest “not supported”
8. Phase A proof uses **`max_rows=1`** (original sandbox cap) unless the check’s pipeline ceiling differs

### 2.2 Pass (Tier B — plan_only) — interim

CI-03, CC-01, CC-02 (Phase A mappings with `execute_mode=plan_only`):

1. Preview/plan succeeds (`ready` or honest plan intents)
2. Execute returns blocked (`ci03_plan_only` / `cc01_plan_only` / `cc02_plan_only`)
3. **No** connector mutate

This **is** the sandbox-test pass **until** product enables Phase B mutate. When Phase B ships, promote those checks to Tier A and add full execute+rollback cases.

### 2.3 Pass (Tier C — execute blocked)

PT-03 (today): Preview OK; execute must **not** write while capability `RESTV2.PRODUCT.IMPORT` is not execute-eligible and/or sheet `write_possible_today=no` (pipeline hard-gate already in `pipeline.py`). When capability+sheet allow execute, promote to Tier A.

### 2.4 Skip (Tier D — disabled)

LE-04, SP-01: registry `enabled=false` — harness records **skip**; no execute claim. (SP-01 was optional third Manago proof in WB-01B; it is **not** MVP1-enabled today.)

### 2.5 Evidence rules (aligned with original sandbox)

| Check | Preferred | Original / allowed proof seed |
|-------|-----------|-------------------------------|
| **CI-01** | DCS FAIL/WARN gap rows | Test seeds DCS-shaped mismatches or Contacts so transform can build intents |
| **CC-03** | DCS `shopify_holds_evidence` | If none: product still has `_cc03_sandbox_evidence_rows` when Allow writebacks ON (WB-01B). Harness may **seed Manago Contacts** and rely on that path, or seed DCS rows. Do **not** treat empty worklist + invent as the *only* long-term product story (Phase D may tighten). |
| **WB-SHOP-01** | N/A (not catalogue worklist) | Seed **Shopify** `Contact` rows → `_shopify_sandbox_evidence_rows` / `sandbox_customer_note` — this **is** the original sandbox proof, not a fake DCS PASS |
| Other Tier A | DCS FAIL/WARN sides for that mapping | Explicit test fixtures only — **do not** add new invent-when-empty product fallbacks |

**Forbidden:** Fix UI / fixtures claiming “Sandboxed … Passed” without going through preview→execute.  
**Allowed:** Seeding DB Contacts / RunIssue rows inside pytest so the **real** pipeline can run (same as `test_writeback_01b` / `01c`).

---

## 3. Coverage matrix (SoT for this PRD)

Sheet SoT: `dataruns/writebacks/WRITEBACK_POSSIBLE_NOT_SHEET.csv` (+ docs copy).  
FE execute allowlist: `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS`.  
BE execute allowlist: `WritebackAllowedCheck`.

| check_id | Tier | Sandbox pass means | Phase |
|----------|------|--------------------|-------|
| **CI-01** | A | execute + rollback | **A (first)** |
| **CC-03** | A | execute + rollback | **A (first)** |
| **WB-SHOP-01** | A | execute + rollback (Shopify note) | **A (first)** |
| CI-05 | A | execute + rollback | B |
| LE-01 | A | execute; rollback limited honesty | B |
| LE-05 | A | execute; rollback limited honesty | B |
| LE-02 | A | execute; rollback **no** honesty | B |
| LE-09 | A | execute; rollback limited honesty | B |
| SP-07 | A | execute + rollback | B |
| SP-03 | A | execute + rollback | B |
| PT-04 | A | execute + rollback | B |
| CI-03 | B | preview OK; execute blocked plan_only | C |
| CC-01 | B | preview OK; execute blocked plan_only | C |
| CC-02 | B | preview OK; execute blocked plan_only | C |
| PT-03 | C | preview OK; execute blocked until sheet/capability allows | C |
| LE-04 | D | skip | C |
| SP-01 | D | skip | C |

When a **new** writeback ships after WB-21: add a row here + harness case in the same PR as the mapping. **Do not ship a writeback without a sandbox-test case.**

---

## 4. Non-goals / anti-patterns

| Anti-pattern | Why forbidden |
|--------------|---------------|
| Fake Fix UI “sandbox PASS” without execute | Lies to operators / employer |
| Claiming Tier B execute “works” while `plan_only` | Plan-only must stay blocked until Phase B |
| One live test only for CC-03 (`test_writeback_sandbox_integration.py`) as full coverage | Incomplete vs original dual-connector + later checks |
| Re-introducing `WRITEBACK_SANDBOX_COMPANY_IDS` as primary gate | Superseded by WB-03 company flag |
| Treating old WB-02 “only 3 checks” as permanent product law | Historical first wave only |
| Skipping approval in harness “because old sandbox didn’t need it” | Current BE requires `approval_id` when Allow writebacks ON |
| Skipping WB-SHOP-01 because “no DCS FAIL” | Original Shopify proof never required a catalogue FAIL |
| Adding new invent-when-empty paths for LE-05/CI-05/… | Only CC-03/LE-01 (and WB-SHOP-01 contact seed) have historical proof fallbacks |

---

## 5. Implementation — shared harness

### 5.1 Location

Prefer extend:

- `dataruns/tests/writeback_helpers.py` — helpers  
- New: `dataruns/tests/test_writeback_sandbox_contract.py` — parametrized contract  
- Live optional: replace/extend `test_writeback_sandbox_integration.py` to loop Tier A when env set  

Gold path reference: `test_writeback_01c.test_run_execute_sandbox_and_rollback`.

### 5.2 Helper contract (sketch)

```text
run_sandbox_preview(company, check_id, *, max_rows, actor) -> preview_result
issue_approved_writeback_token(...)  # already exists
run_sandbox_execute(company, check_id, *, diff_hash, approval_id, actor) -> execute_result
run_sandbox_rollback(company, job_id, actor) -> rollback_result

assert_tier_a_sandbox_pass(check_id, ...)
assert_tier_b_plan_only_blocks_execute(check_id, ...)
assert_tier_c_execute_blocked(check_id, ...)
```

Mock transports per `op_kind` (Manago upsert / detail_set / event_ingest / event_correct / product_upsert; Shopify customer update). Do not require live credentials for CI.

### 5.3 Evidence for tests

| Preferred | Fallback in unit tests only |
|-----------|-----------------------------|
| Seed DCS-shaped mismatches for that check | Explicit fixture rows in the test module |

**Product path:** do not expand invent-when-empty as the sandbox pass mechanism. Phase D may **remove or tightly gate** invent fallbacks for CC-03/LE-01.

### 5.4 Allowlist hygiene

- Keep FE `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS` in sync with Tier A.  
- Keep `WritebackAllowedCheck` migrations in sync.  
- Update `DEFAULT_WRITEBACK_ALLOWLIST` in helpers to cover Tier A used by the harness (or seed per test).  
- Tier B must **not** be on FE execute allowlist (already true for CI-03/CC-01/CC-02).  
- PT-03 must **not** join FE execute allowlist until Tier C → A promotion.

---

## 6. Phased delivery

### Phase A — Foundation + original 3 (ship first)

1. Shared helpers + `test_writeback_sandbox_contract.py`  
2. Parametrize **CI-01, CC-03, WB-SHOP-01** Tier A (mocked transports), matching §0a + §2.5 evidence seeds  
3. Assert **Manago path** (CI-01 **and** CC-03) **and** **Shopify path** (WB-SHOP-01) — original dual-connector bar  
4. `max_rows=1`, approval required, rollback asserted where mapping supports  
5. Document that old “only 3” PRDs are first-wave history  

**Exit:** three green contract tests that reproduce original sandbox proof behaviour on current gates; no product behaviour change required beyond tests/helpers (invent fallbacks may remain until Phase D).

### Phase B — Remaining Tier A

Add harness cases: CI-05, LE-01, LE-05, LE-02, LE-09, SP-07, SP-03, PT-04.

**Exit:** every Tier A check has a green sandbox contract test.

### Phase C — Tier B / C / D

- CI-03 / CC-01 / CC-02: execute blocked asserted  
- PT-03: execute blocked asserted  
- LE-04 / SP-01: skip recorded  

**Exit:** matrix §3 fully covered in CI.

### Phase D — Honesty + optional live (optional / follow-on)

1. Optional live suite: env company + real connectors; same harness; skip if unset  
2. FE: remove/ignore fixture “Sandboxed test complete / Passed” as writeback proof  
3. Naming: prefer `execute_eligible.company` (or keep `sandbox` key with honest docs); Fix `sandbox-mapping` → `mapping-only`  
4. Tighten invent-evidence fallbacks  

---

## 7. FE / Fix honesty

| Do | Don’t |
|----|-------|
| Show Preview / Written / blocked reasons from API | Show a sandbox checkbox that “runs and PASSes” |
| Point disabled Approve to Settings Allow writebacks | Say “sandbox only” as if a separate env |
| Deep-link WB-SHOP-01 via mapping-only target when no worklist FAIL | Treat mapping-only as a DCS PASS |

---

## 8. Relationship to older PRDs

| Doc | How WB-21 treats it |
|-----|---------------------|
| WB-01 / 01B | Foundation + first Manago/Shopify proof — **historical** |
| WB-02 | First Fix Approve for **3** checks — **first wave**, not final coverage |
| WB-03 | Settings Allow writebacks = execute gate — **still SoT** for gating |
| WB-04…20 | Per-check writebacks — each must gain a **§3 matrix row + harness case** under WB-21 |
| Possible sheet | `yes` / `preview_only` / `no` / `disabled` — **not** `sandbox_only` (already cleaned) |

---

## 9. Acceptance

### Phase A

- [x] Shared harness helpers exist and are documented in this PRD (`writeback_helpers.assert_tier_a_sandbox_pass`)  
- [x] CI-01, CC-03, WB-SHOP-01 Tier A mocked sandbox tests pass (§0a behaviour) — `test_writeback_sandbox_contract.py`  
- [x] Tests use Allow writebacks + **approval** + execute + rollback (not a fake PASS badge)  
- [x] WB-SHOP-01 seeded via Shopify Contacts (not “must be on DCS worklist”)  
- [x] Dual connector covered (Manago + Shopify) in Phase A  

### Phase B

- [x] All Tier A checks in §3 have harness cases green (`test_writeback_sandbox_contract.WritebackSandboxContractPhaseBTests`)  

### Phase C

- [x] Tier B plan_only blocks execute (`CI-03` / `CC-01` / `CC-02`)  
- [x] PT-03 execute blocked while sheet/capability forbids (`check_not_allowlisted` + PRODUCT.IMPORT not execute-eligible)  
- [x] LE-04 / SP-01 skipped honestly (`MappingDisabled`)  

### Phase D

- [x] Optional live suite (`test_writeback_sandbox_integration.py`) — env `WRITEBACK_EXECUTE_COMPANY_ID` / legacy `WRITEBACK_SANDBOX_COMPANY_ID`; Phase A checks with approval  
- [x] FE fixture badges no longer claim live “Sandboxed … Passed” writeback proof (`klints-data.ts`)  
- [x] Fix `sandbox-mapping` → `mapping-only`; `execute_eligible.company` added (sandbox alias kept)  
- [x] FE verify scripts updated (`verify:wb01b` / `verify:fe08` / `verify:ai01` / `verify:wb01` / `verify:wb02`) for mapping-only + honest badges + `execute_eligible.company`  
- [x] Invent-evidence paths documented as legacy-only (CC-03 / LE-01); no new invent fallbacks  
- [x] `scripts/verify_wb21_sandbox_contract.py` matrix check (tiers from helpers; FE == Tier A; harness method coverage)  
- [x] HTTP/status payloads assert `execute_eligible.company` (+ sandbox alias)  
- [x] Preflight-blocked preview keeps `execute_eligible.company` when Allow writebacks ON  
- [x] Backend README documents WB-21 verify + contract tests  

### Always

- [x] No new invent-evidence product path introduced for “sandbox pass”  
- [ ] New writeback PRs must add a §3 row + harness case  
- [x] README lists WB-21  

---

## 10. Verify script (optional)

`scripts/verify_wb21_sandbox_contract.py`:

1. Load possible sheet (skip `#` comment lines) + FE `WRITEBACK_APPROVE_EXECUTABLE_CHECK_IDS`  
2. Assert Tier A set ⊆ FE allowlist ∩ sheet `yes`  
3. Assert Tier B not in FE execute allowlist; sheet `preview_only`  
4. Assert PT-03 not in FE execute allowlist while sheet `no`/`preview_only`  
5. Print matrix coverage counts  

---

## 11. Open decisions (product)

| # | Topic | Default in this PRD |
|---|--------|---------------------|
| 1 | Live connector suite required for merge? | **No** — mocked CI required; live optional (Phase D shipped, env-gated) |
| 2 | Remove CC-03/LE-01 invent-when-empty? | **Keep legacy** — documented; no new invent fallbacks |
| 3 | Rename API `execute_eligible.sandbox`? | **Done** — `company` added; `sandbox` kept as alias |
| 4 | Tier B “sandbox pass” = blocked execute only? | **Yes** until Phase B mutate ships; then upgrade to Tier A |

---

## 12. Draft audit (self-check)

| Claim in draft | Verdict |
|----------------|---------|
| Sandbox ≠ background API ping | **Correct** |
| Gate = Allow writebacks today | **Correct** (WB-03) |
| First wave = CI-01, CC-03, WB-SHOP-01 | **Correct** |
| Extend same test to all later writebacks | **Correct** (product intent; old PRDs stopped at 3 because only those existed) |
| Approval always in harness | **Correct for current code**; stricter than raw WB-01B Postman |
| WB-SHOP-01 needs DCS FAIL | **Was wrong in early draft** — fixed §2.5 |
| Ban all invent evidence immediately | **Was too strict vs original CC-03 path** — fixed §2.5 / Phase D |
| Tier B blocked execute = sandbox pass | **Correct interim**; not a full write proof |

---

## 13. One-line employer answer

**Sandbox test** = prove Preview → Approve → execute (or honest block) on the real writeback pipeline with Allow writebacks on — same behaviour as the original CI-01 / CC-03 / WB-SHOP-01 proof, then the same contract for every other shipped writeback.
