# Maheep PRD series

Product/implementation contracts for connector uniqueness, auth route guards, daily DCS scheduling, Shopify offline token refresh (+ failure handling), DCS-based app lock, signup company website, governance audit / Activity timeline, Integrations connector status/stats, audit notifications, gated DCS run progress, Spotlight global search, Manago API v3 key on Connected stack, live guided DCS worklist (Overview + Data Consistency), Manago primary owner picker (FD-06), onboarding v3 key step, Settings honesty (Coming soon for API keys / Billing), Overview period compare / Captured wiring (consumes DCS-10), Fix screen ↔ live Data Center issue bridge, DCS title casing + Fix friendly evidence (no raw JSON), and writeback adapter foundation (dry-run + mapping JSON; live writes off).

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
