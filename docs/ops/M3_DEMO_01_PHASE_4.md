# M3-DEMO-01 — Phase 4 notes (full path + DP1 readiness)

**Date:** 2026-09-15  
**Branch:** `feature/m3-demo-01-shopify-klints-dev`  
**PRD:** [PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md](./PRD_M3_DEMO_01_DEMO_ENV_AND_DP1.md)  
**Prior:** [PHASE_3](./M3_DEMO_01_PHASE_3.md) · [SHOPIFY_PATH](./M3_DEMO_01_SHOPIFY_PATH.md)  
**Legacy contrast:** [GAP_01F_DEMO_PATH.md](./GAP_01F_DEMO_PATH.md) (seed — **not** M3 AC)

| Slice | Status |
|-------|--------|
| **Full path docs (Sahil)** | **DONE** (2026-09-15) |
| **Staging walkthrough evidence** | **PENDING** — repeat on Vercel |
| **§11 A4 partial** | **Local done** — live path + seed contrast · staging Loom optional |

## Goal

Document the **live klints-dev** product journey after import: Fix → Studio → QA → Handoff — with honest gates at current score (~44). Add a **DP1 readiness** paragraph: what reuse vs what still needs Gate B.

## Checklist

| # | Task | Done |
|---|------|------|
| 4.1 | Full path table (routes + expect at score 43.549) | [x] |
| 4.2 | Local evidence from recommendations + DCS check_results API | [x] |
| 4.3 | Manago mismatch honesty | [x] |
| 4.4 | DP1 readiness paragraph | [x] |
| 4.5 | Contrast vs seed path (A4) | [x] |
| 4.6 | Update SHOPIFY_PATH §5 + WORKING_GAPS | [x] |
| 4.7 | Staging Loom / screenshot | [ ] optional |

## Full path (live klints-dev — local 2026-09-15)

Tenant **yoyo** · company `4e72da96-5cf0-4005-a16a-02a9ed91b62a` · DCS **43.549** · sweep `run_state=INCOMPLETE` (Celery data_run **440**) · `min_dcs_required=70`

| Step | Route | What you should see (live path) | Local evidence |
|------|-------|----------------------------------|----------------|
| **Connect** | `/integrations` | Shopify **connected** · Manago **connected** · stats from import (189 / 250) | API `latest_bootstrap` · [Phase 3](./M3_DEMO_01_PHASE_3.md) |
| **Score** | `/data-consistency` | Headline **43.549** · badge below **70** threshold · worklist from **live** imports | data_run **440** · 42 checks |
| **Fix** | `/fix` | FAIL/WARN rows from live DCS checks — not seed corpus | **15 FAIL** · **1 WARN** · **18 PASS** (42 total) |
| **Opportunities** | `/opportunities` | Pilots listed; **0 ready** · **16 blocked** · **9 gap_suggested** badges | All `blocked_dcs_score` |
| **Studio** | `/workflow?uc=UC-02` | **Needs higher score** — blueprint **loads** · Generate **disabled** (“Clear gates first”) | UC-02: Score 43.549 &lt; 70 |
| **QA** | `/qa` | Empty until a build package exists | `WorkflowBuildPackage` count **0** |
| **Handoff** | `/handoff` | Empty / locked until QA PASS package | Send = **human** ([HO-02](./PRD_HO_02_HANDOFF_SEND_HUMAN_ACTIVATION.md)) — no MCP |
| **Lifecycle** | `/lifecycle` | Architecture assessment **INCOMPLETE** · lifecycle gaps | `gap_count=12` · assessment **1204a82a** |

**Optional:** `/dashboard` (overview).

### Pilot gate snapshot (API)

`GET /api/v1/use-cases/recommendations/` (local):

```json
{
  "dcs": {
    "headline_score": 43.549,
    "min_dcs_required": 70,
    "data_run_id": 440,
    "score_ready": true
  },
  "architecture": {
    "mode": "INCOMPLETE",
    "gap_count": 12
  },
  "summary": {
    "ready": 0,
    "ready_full": 0,
    "ready_provisional": 0,
    "blocked": 16,
    "gap_suggested": 9
  }
}
```

| Pilot | Status | Blocker |
|-------|--------|---------|
| UC-02 | `blocked_dcs_score` | Score 43.549 &lt; 70 |
| UC-06B | `blocked_dcs_score` | Score 43.549 &lt; 70 |
| **All 16 MVP1 pilots** | **`blocked_dcs_score`** | Score &lt; 70 — **no** `blocked_checks` at this score |

**Note on `gap_suggested=9`:** Architecture assessment flags lifecycle gaps on 9 pilots (e.g. UC-04, UC-11). Studio may show a **Gap suggested** badge, but **DCS score still blocks** Generate on all pilots until headline ≥ 70.

### Fix / DCS check snapshot (data_run 440)

| Verdict | Count |
|---------|-------|
| FAIL | **15** |
| WARN | **1** |
| PASS | **18** |
| NOT_CONNECTED | 4 |
| UNKNOWN | 4 |
| **Total** | **42** |

Fix worklist is **populated from live imports** — not empty, not seed corpus.

This is **correct product behavior** — not a DEMO-01 defect.

## Why score stays ~44 (honest)

| Factor | Detail |
|--------|--------|
| Shopify volume | **189** contacts in window — thin vs Manago **~2k+** |
| Cross-system mismatch | CI/identity checks fail or warn when systems don’t align |
| `INCOMPLETE` | Coverage / lifecycle gaps — not “broken import” |
| Not fixable by seed | Growing Simple Sample Data helps; faking Manago via seed is **out of scope** |

DEMO-01 proves **connect → import → contacts visible**. It does **not** require DCS ≥ 70 or a completed Studio→QA→Handoff chain.

## Contrast: live path vs seed (A4)

| | **M3-DEMO-01 (this PRD)** | **GAP-01F seed (non-AC)** |
|--|---------------------------|---------------------------|
| Contacts source | Shopify Simple Sample Data → OAuth import | `seed_demo_tenant` offline corpus |
| Connectors | Live OAuth (klints-dev + Manago) | Stubs (`gap01f_demo_seed`) |
| Typical score | **~43–44** (current local) | **~61** REMEDIATE band |
| Studio at demo score | **Blocked** (&lt; 70) | Also blocked (&lt; 70) |
| M3 claim | **Yes** — live Shopify path | **No** — local smoke only |

Allowed M3 claim: *demo uses live Shopify klints-dev + Klints import* — not *seed script is the demo*.

## DP1 readiness paragraph

**Readiness (reuse for DP1):** The same technical pattern planned for DP1 is **proven locally**: Partners app OAuth to a real Shopify shop → DCS-10 fresh import → contacts/orders in Klints → Fix/DCS worklist from live data → pilot recommendations gated honestly. Staging still needs Rohan confirm on callbacks/scopes ([Phase 0](./M3_DEMO_01_PHASE_0.md) G2).

**Not ready (do not claim):**

| Item | Blocker |
|------|---------|
| Production partner PII / live cutover | **Gate B** — legal + partner agreement |
| MCP workflow publish | Client-blocked · HO-02 human Send only |
| “DP1 live” headline | Requires partner shop + volume + score trajectory — not klints-dev sample alone |
| Exact ~5k Shopify contacts | Simple Sample Data still growing (189 documented) |
| Grafana / pen-test | Separate PRDs |

**Practical DP1 path after Gate B:** Partner Shopify (or approved sandbox) → same OAuth + scope checklist → fresh import → remediate to ≥70 (or document provisional pilots) → Studio package → QA → human Handoff. **No new connector architecture required** — environment, credentials, and data volume differ.

## Deep-check (2026-09-15 audit)

| Check | Result |
|-------|--------|
| API path `GET /api/v1/use-cases/recommendations/` | **Pass** — matches `core/urls.py` |
| All 16 pilots `blocked_dcs_score` at 43.549 | **Pass** — verified via `build_recommendations_payload` |
| Fix worklist non-empty (live checks) | **Pass** — 15 FAIL + 1 WARN |
| Studio blueprint loads when blocked | **Pass** — `WorkflowStudio` loads detail; `canGenerate=false` |
| QA/Handoff empty (no packages) | **Pass** — `WorkflowBuildPackage` count **0** |
| Manago connected (A8 honesty) | **Pass** — connector status connected |
| Architecture INCOMPLETE on `/lifecycle` | **Pass** — documented |
| Imprecise “blocked by checks” wording | **Fixed** — all DCS-blocked at this score |
| Staging walkthrough | Still open |
| §11 A4 full (staging Loom) | Partial — local docs done |

## What Phase 4 proves

- Full product path is **documented** with honest gates at real score  
- **A4 local:** live path written; seed cited as non-AC  
- DP1 = **pattern readiness**, not production go-live  

## Still open

| Item | Phase |
|------|-------|
| Staging walkthrough / Loom | Residual ops |
| §11 Sahil ship | **Done** — [PHASE_6](./M3_DEMO_01_PHASE_6.md) |

## Exit

Phase 4 **done** (docs + local API evidence).  
**Next:** [Phase 6](./M3_DEMO_01_PHASE_6.md) Sahil ship closed.

## Do not

Claim Studio unlocked · claim QA/Handoff complete · claim DP1 live · claim seed is M3 path · claim Grafana here
