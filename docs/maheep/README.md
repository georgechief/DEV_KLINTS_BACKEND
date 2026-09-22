# Maheep PRD series

Product/implementation contracts for connector uniqueness, auth route guards, daily DCS scheduling, Shopify offline token refresh (+ failure handling), DCS-based app lock, signup company website, governance audit / Activity timeline, Integrations connector status/stats, audit notifications, gated DCS run progress, Spotlight global search, Manago API v3 key on Connected stack, live guided DCS worklist (Overview + Data Consistency), Manago primary owner picker (FD-06), onboarding v3 key step, Settings honesty (Coming soon for API keys / Billing), Overview period compare / Captured wiring (consumes DCS-10), Fix screen ↔ live Data Center issue bridge, DCS title casing + Fix friendly evidence (no raw JSON), writeback adapter foundation, Fix Approve writeback (WB-02), evidence download (FE-12), possible-sheet runtime (WB-02B), real writeback DB gate + Loom (WB-03), shell honesty / deep-links / Data Center assessment export (FE-13), once-per-DCS-run writeback gate (WB-04), Fix writeback Loom staging proof (WB-05), Fix writeback provenance / restore Written (WB-06), Fix/shell/notifications polish + Postgres audit immutability (POLISH-01), atomic once-per-run claim + writeback response hygiene (WB-07), M2 staging harden / Fix support (M2-OPS-01), catalogue writeback wave 2 SP-01 + LE-01 (WB-08), SP-07 namespace clean writeback (WB-09), LE-09 return/cancellation event writeback (WB-10), PT-04 klints_net_ltv writeback (WB-11), and PT-04 PASS when stamped net matches (WB-12).

## Build order

| # | File | Delivers |
|---|------|----------|
| 1 | [PRD_CONN_02_DUPLICATE_ACCOUNT_BLOCK.md](./PRD_CONN_02_DUPLICATE_ACCOUNT_BLOCK.md) | Block connecting a Shopify shop / Manago account already used by another company |
| 2 | [PRD_FE_01_SIGNIN_ROUTE_GUARD.md](./PRD_FE_01_SIGNIN_ROUTE_GUARD.md) | Signed-in users hitting `/signin` redirect to onboarding or dashboard |
| 3 | [PRD_FE_02_ONBOARDING_ROUTE_GUARD.md](./PRD_FE_02_ONBOARDING_ROUTE_GUARD.md) | `/onboarding` only when signed in and no connector connected |
| 4 | [PRD_DCS_07_DAILY_BEAT_SCHEDULE.md](./PRD_DCS_07_DAILY_BEAT_SCHEDULE.md) | Celery Beat 15:00 IST → DCS pipeline for all companies with a connected account |
| 5 | [PRD_CONN_03_SHOPIFY_OFFLINE_TOKEN_REFRESH.md](./PRD_CONN_03_SHOPIFY_OFFLINE_TOKEN_REFRESH.md) | Refresh expiring Shopify offline tokens inside Celery jobs before fetch/score |
| 6 | [PRD_FE_03_DCS_APP_LOCK.md](./PRD_FE_03_DCS_APP_LOCK.md) | CheckMaster `isOptional` (FD-03 true); gated dashboard until score; optional fails never block shell; Fix/Workflow menus disabled |
| 7 | [PRD_AUTH_01_SIGNUP_COMPANY_WEBSITE.md](./PRD_AUTH_01_SIGNUP_COMPANY_WEBSITE.md) | Collect customer website on signup; persist normalized value on tenant `Company.domain` |
| 8 | [PRD_AUDIT_01_GOVERNANCE_ACTIVITY.md](./PRD_AUDIT_01_GOVERNANCE_ACTIVITY.md) | Company audit log + hash chain; live `/activity`; Activity always visible (not DCS-locked) |
| 9 | [PRD_CONN_04_INTEGRATIONS_STATUS_AND_STATS.md](./PRD_CONN_04_INTEGRATIONS_STATUS_AND_STATS.md) | Drop products/inventory scopes; show Connected for degraded; live run id / contacts / orders / issues on cards |
| 10 | [PRD_AUDIT_02_AUDIT_NOTIFICATIONS.md](./PRD_AUDIT_02_AUDIT_NOTIFICATIONS.md) | `audit_read` flag; bell badge unread count; top 5 unread in NotificationsPanel; mark-all / mark-one read |
| 11 | [PRD_FE_04_GATED_DCS_RUN_PROGRESS.md](./PRD_FE_04_GATED_DCS_RUN_PROGRESS.md) | Gated dashboard dimension tiles: orange=running, green=passed, red=failed — how far last/current DCS run got |
| 12 | [PRD_CONN_05_SHOPIFY_TOKEN_REFRESH_FAILURE_HANDLING.md](./PRD_CONN_05_SHOPIFY_TOKEN_REFRESH_FAILURE_HANDLING.md) | Patch CONN-03: inactive/expired refresh → `error` + audit + email account owner; stop silent daily fail loop |
| 13 | [PRD_FE_05_SPOTLIGHT_GLOBAL_SEARCH.md](./PRD_FE_05_SPOTLIGHT_GLOBAL_SEARCH.md) | Cmd+K Spotlight: `GET /api/v1/search/` + wire FE; live checks/audit/connectors/runs; drop mock issues/workflows |
| 14 | [PRD_CONN_06_MANAGO_API_V3_KEY.md](./PRD_CONN_06_MANAGO_API_V3_KEY.md) | Connected stack Manago card: paste API v3 key, store encrypted, show masked; unblocks catalog DCS |
| 15 | [PRD_FE_06_GUIDED_DCS_WORKLIST.md](./PRD_FE_06_GUIDED_DCS_WORKLIST.md) | Same real Overview UI always: empty/Not calculated + FE-04 stages until score ready; live NBA/impact/evidence; worklist APIs |
| 16 | [PRD_CONN_07_MANAGO_PRIMARY_OWNER.md](./PRD_CONN_07_MANAGO_PRIMARY_OWNER.md) | Manago multi-user: pick primary owner (FD-06); FE calls GET/PUT owners — **backend done** (deferred unless product asks) |
| 17 | [PRD_FE_07_ONBOARDING_V3_AND_SETTINGS_HONESTY.md](./PRD_FE_07_ONBOARDING_V3_AND_SETTINGS_HONESTY.md) | Onboarding: optional Manago API v3 after connect; Settings: API keys + Billing → Coming soon; Account/Workspace/Team stay live |
| 18 | [PRD_FE_08_FIX_LIVE_ISSUE_BRIDGE.md](./PRD_FE_08_FIX_LIVE_ISSUE_BRIDGE.md) | Fix `/fix?issue=CC-06`: bind live worklist into **original-designs** Fix chrome; no fake Manago writebacks |
| 19 | [PRD_FE_09_DCS_COPY_AND_FIX_EVIDENCE.md](./PRD_FE_09_DCS_COPY_AND_FIX_EVIDENCE.md) | Title Case / sentence case on live issue titles; Fix preview reuses `formatFriendlyEvidenceRows` (no JSON); Where-it-changes ≠ `klints` |
| 20 | [PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md](./PRD_WB_01_WRITEBACK_ADAPTER_FOUNDATION.md) | All pack write kinds (`klints_` details/tags, upserts, events, catalog…); dry-run + **sandbox test-account execute**; prod kill-switched; pre-BL-017 |
| 21 | [PRD_WB_01B_SANDBOX_PROOF_AND_LE04_FIX.md](./PRD_WB_01B_SANDBOX_PROOF_AND_LE04_FIX.md) | Follow-up: disable LE-04; sandbox Manago+Shopify; matrix; **Loom = Postman API then platform UI reflect** |
| 22 | [PRD_FE_11_EVIDENCE_ELEMENTS_FROM_MAP.md](./PRD_FE_11_EVIDENCE_ELEMENTS_FROM_MAP.md) | Differences **Elements** = platform field/model from `map.json` / check metadata (fix CI-13 “—”); BE enrich + FE resolve order; **consult Sahil** if provenance/executors change |
| 23 | [PRD_FE_11B_ELEMENTS_PLATFORM_API_KEY.md](./PRD_FE_11B_ELEMENTS_PLATFORM_API_KEY.md) | **FE-11B** — Correct Elements: show platform **`api_key`** for that row’s source (not humanized side / `element_label`) |
| 24 | [PRD_WB_01C_WRITEBACK_POSSIBLE_NOT_SHEET.md](./PRD_WB_01C_WRITEBACK_POSSIBLE_NOT_SHEET.md) | **WB-01C** — Per-check/field possible vs not sheet (CSV + `GET …/possible/`); common `POST …/run/` for preview\|execute\|rollback (keys by action) |
| 25 | [PRD_WB_02_FIX_APPROVE_WRITEBACK_EXECUTE.md](./PRD_WB_02_FIX_APPROVE_WRITEBACK_EXECUTE.md) | **WB-02 (PR 1)** — Fix **Approve writeback** → sandbox execute for **CI-01 / CC-03 / WB-SHOP-01**; honest trust steps; audit/bell; no prod flip |
| 26 | [PRD_FE_12_FIX_EVIDENCE_EXCEL_DOWNLOAD.md](./PRD_FE_12_FIX_EVIDENCE_EXCEL_DOWNLOAD.md) | **FE-12 (PR 2, after WB-02)** — Download evidence CSV/Excel from Fix for non-writable (and all) live issues |
| 27 | [PRD_WB_02B_POSSIBLE_SHEET_RUNTIME_AND_DEMO.md](./PRD_WB_02B_POSSIBLE_SHEET_RUNTIME_AND_DEMO.md) | **WB-02B (P0)** — Ship possible sheet under `dataruns/writebacks/` (Docker excludes `docs/`); written right/gap report for Approve + Download |
| 28 | [PRD_WB_03_REAL_WRITEBACK_DB_GATE_AND_LOOM.md](./PRD_WB_03_REAL_WRITEBACK_DB_GATE_AND_LOOM.md) | **WB-03 (P0)** — Writebacks default OFF; **Settings UI** Admin toggle (not manage.py); Fix real write; Loom for CI-01/CC-03/WB-SHOP-01 reflect + rollback |
| 29 | [PRD_FE_13_SHELL_HONESTY_AND_DEEP_LINKS.md](./PRD_FE_13_SHELL_HONESTY_AND_DEEP_LINKS.md) | **FE-13** — DCS **Export fix plan** = same assessment PDF as Overview Export brief; bell/Activity deep-links; Settings deferred honesty; Phase 4–5 soft-lock; live Fix routing; fixture bleed gate |
| 30 | [PRD_WB_04_ONCE_PER_DCS_RUN_WRITEBACK_GATE.md](./PRD_WB_04_ONCE_PER_DCS_RUN_WRITEBACK_GATE.md) | **WB-04 (P0)** — One successful execute per check per DCS `data_run_id`; 409 on re-Approve until newer score or rollback |
| 31 | [PRD_WB_05_FIX_WRITEBACK_LOOM_STAGING_PROOF.md](./PRD_WB_05_FIX_WRITEBACK_LOOM_STAGING_PROOF.md) | **WB-05 (P1)** — Staging Loom proof for CI-01 / CC-03 / WB-SHOP-01 (Settings ON → write → reflect → rollback) |
| 32 | [PRD_WB_06_FIX_WRITEBACK_PROVENANCE.md](./PRD_WB_06_FIX_WRITEBACK_PROVENANCE.md) | **WB-06 (P0)** — Persist/show run+job on Fix; `GET …/writebacks/status/`; restore Written after refresh |
| 33 | [PRD_POLISH_01_FIX_SHELL_AUDIT_IMMUTABLE.md](./PRD_POLISH_01_FIX_SHELL_AUDIT_IMMUTABLE.md) | **POLISH-01 (P0)** — Postgres audit immutability (migration trigger/revert + Loom) · Fix/shell/bell/Spotlight harden · pack gate honesty |
| 34 | [PRD_WB_07_ATOMIC_GATE_AND_RESPONSE_HYGIENE.md](./PRD_WB_07_ATOMIC_GATE_AND_RESPONSE_HYGIENE.md) | **WB-07 (P0)** — Claim execute job before adapter I/O · concurrent 409 · mask entity_key/PII · no hash/exc leaks · deny execute without DCS run |
| 35 | [PRD_M2_OPS_01_STAGING_HARDEN.md](./PRD_M2_OPS_01_STAGING_HARDEN.md) | **M2-OPS-01 (P0 ops)** — Staging readiness + Fix smoke while Sahil ships DCS-09 · bugfix only · notes for E2E-01 · no new mappings |
| 36 | [PRD_WB_08_CATALOGUE_WAVE2_SP01_LE01.md](./PRD_WB_08_CATALOGUE_WAVE2_SP01_LE01.md) | **WB-08 (P0 M2)** — Enable catalogue writebacks **SP-01** (tag) + **LE-01** (event ingest); irreversible honesty; parallel with Sahil HO-02 · no handoff |
| 37 | [PRD_WB_09_SP07_NAMESPACE_CLEAN_WRITEBACK.md](./PRD_WB_09_SP07_NAMESPACE_CLEAN_WRITEBACK.md) | **WB-09 (P0 M2)** — SP-07 Automated writeback: rename legacy `klints_` / `klints:` collisions; owned allowlist; unlocks gated writebacks |
| 38 | [PRD_WB_10_LE09_RETURN_EVENT_WRITEBACK.md](./PRD_WB_10_LE09_RETURN_EVENT_WRITEBACK.md) | **WB-10 (P0 M2 · Sahil)** — LE-09 Automated writeback: Manago `event_ingest` RETURN/CANCELLATION from Shopify refunds/cancels; irreversible honesty |
| 39 | [PRD_WB_11_PT04_NET_LTV_WRITEBACK.md](./PRD_WB_11_PT04_NET_LTV_WRITEBACK.md) | **WB-11 (P0 M2 · Sahil)** — PT-04 Automated writeback: `detail_set` `klints_net_ltv` = Shopify net; owns key for SP-07 |
| 40 | [PRD_WB_12_PT04_PASS_ON_KLINTS_NET_LTV.md](./PRD_WB_12_PT04_PASS_ON_KLINTS_NET_LTV.md) | **WB-12 (P0 M2 · Sahil · Shipped)** — PT-04 PASS when `klints_net_ltv` ≈ Shopify net (completes treating loop after WB-11) |

## Deploy order (writeback activation)

1. **WB-02** — Approve → write  
2. **FE-12** — Evidence download  
3. **WB-02B** — Runtime CSV path  
4. **WB-03** — Settings toggle; default off; Loom reflect+rollback all allowlisted checks  
5. **WB-04 + WB-06** — Once-per-run gate + Fix provenance (combined PR OK)  
6. **WB-05** — Fresh staging Loom after gate lands  
7. **POLISH-01** — Audit immutability + shell/notifications honesty  
8. **WB-07** — Atomic claim-before-write + API PII/error hygiene  
9. **M2-OPS-01** — Staging harden + Fix smoke (parallel with Sahil DCS-09; before E2E-01 Loom)  
10. **WB-08** — SP-01 + LE-01 catalogue wave (parallel with Sahil HO-02; no handoff)  
11. **WB-09** — SP-07 namespace clean rename writeback (after WB-08; unlocks gated writebacks)  
12. **WB-10** — LE-09 RETURN/CANCELLATION event writeback (after WB-09; unlocks PT-04 next)  
13. **WB-11** — PT-04 `klints_net_ltv` governed net writeback (after WB-10)  
14. **WB-12** — PT-04 PASS when stamped `klints_net_ltv` matches Shopify net (after WB-11)

Do not merge FE-12 before WB-02.  
WB-04/06/07 do **not** block Sahil HO-01 / CAP-01 / Studio / QA.  
M2-OPS-01 does **not** implement DCS-09 or E2E-01.  
WB-08 does **not** touch Handoff Send / HO-02.  
WB-09 does **not** ship versioned Klints prefix (Option B deferred).  
WB-10 does **not** ship PT-04.  
WB-11 ships PT-04 via `detail_set` (not `event_correct`). Stamp alone may not clear PT-04 PASS.  
WB-12 teaches product truth to PASS when the stamp matches net (closes treating loop).

## Cross-track testing

- **[../CROSS_TRACK_TEST_LAST_5_PRDS.md](../CROSS_TRACK_TEST_LAST_5_PRDS.md)** — Sahil↔Maheep polish: last 5 PRDs each (common TCs TC-M* / TC-S*)

## Related existing docs

- `docs/dcs_scoring/PRD_CONN_01_ON_CONNECT_BOOTSTRAP.md` — on-connect bootstrap
- `docs/dcs_scoring/PRD_DCS_01_ORCHESTRATION_AND_EMAIL.md` — `run_dcs_score` Celery pipeline
- `docs/dcs_scoring/PRD_DCS_06_API_RESPONSES.md` — broader DCS HTTP contracts (status may share helpers)
- `docs/sahil/PRD_DCS_08_REVENUE_IMPACT.md` — per-check revenue formulas consumed by FE-06
- `docs/dcs_scoring/PRD_DCS_10_RUN_DIFF_AND_PERIOD_COMPARE.md` — consecutive run-diff (audit) + history `period_compare` / Captured-from-at-stake for Overview period changes
- `docs/sahil/PRD_UC_01_USE_CASE_LIBRARY_AND_PILOTS.md` — Opportunities pilots (separate from Fix bridge)
- Frontend design ref: branch `original-designs` → `src/routes/fix.tsx` + `src/styles/fix.css`
- `docs/API_AUTH_CONNECTORS.md` — connect/auth API surface (§7b Manago owners)
- Shopify offline tokens: [About offline access tokens](https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/offline-access-tokens)
