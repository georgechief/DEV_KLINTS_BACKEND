# M3-OBS-01B — Phase 4 notes (disable induce + §11 + PR)

**Date:** 2026-09-14  
**Branch:** `feature/m3-obs-01b-grafana-alert-closeout`  
**PRD:** [PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md](./PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md)  
**SoT:** [M3_OBS_01_PHASE_6.md](./M3_OBS_01_PHASE_6.md) § employer checklist  
**Depends on:** Phase 2 Explore (A5) + Phase 3 email or stop-and-flag (A7) for **full** §11 sign  

| Slice | Status |
|-------|--------|
| **Sahil (repo / prep)** | **DONE** (2026-09-14) — PR notes + §11 template + disable checklist |
| **Ops live (Rohan)** | **PENDING** — disable induce after proof; help fill A5/A7 |
| **PRD Phase 4 full close** | **NOT done** until induce off + §11 signed with evidence |

## Goal

1. Ensure induce is **off** after proof window  
2. Fill parent §11 A1–A10 (must have A5 + A7)  
3. Open/merge PR with honest closeout notes  

## Ownership split

| Owner | Scope |
|-------|--------|
| **Sahil** | Phase docs 0–4, WORKING_GAPS, PR title/body draft, §11 paste block, verify PASS claim (static) |
| **Rohan / ops** | `M3_OBS_INDUCE_ENABLED=false` after proof, redeploy/restart web, A5/A7 evidence |
| **Sahil after ops** | Tick §11 from evidence, sign off, open PR |

## Sahil checklist (prep)

| # | Task | Done |
|---|------|------|
| S1 | Disable-induce ops steps documented | [x] |
| S2 | §11 template ready to paste (below) | [x] |
| S3 | PR title + body draft (below) | [x] |
| S4 | WORKING_GAPS Phase 4 Sahil prep marked | [x] |
| S5 | Manual commit (user) — do **not** agent-commit | [x] noted |

## Ops / live checklist (Rohan → then Sahil)

| # | Task | Done |
|---|------|------|
| 4.1 | After Phase 2–3 proof: set `M3_OBS_INDUCE_ENABLED=false` in `DEV_ENV_FILE` / `.env` | [ ] |
| 4.2 | Restart/redeploy `web` so gate is off | [ ] |
| 4.3 | Confirm induce POST returns 404 when flag off | [ ] optional |
| 4.4 | Paste A5 Explore + A7 email/stop-and-flag into §11 | [ ] |
| 4.5 | Sign §11; open PR from this branch | [ ] |
| 4.6 | WORKING_GAPS → Phase 4 full `[x]` | [ ] |

### Disable induce (ops)

```bash
# DEV_ENV_FILE / droplet .env
M3_OBS_INDUCE_ENABLED=false
# keep or rotate M3_OBS_INDUCE_TOKEN — do not leave enabled=true
# then redeploy or: docker compose up -d web
```

## §11 paste block (fill after live)

```markdown
### M3-OBS-01 / OBS-01B employer acceptance (§11)

**Staging only · free OSS · Alloy not Promtail · no product UI link · alerts → noreplyklints@gmail.com · workflow is deploy SoT**

- [x] **A1** — loki / alloy / grafana in compose (pinned tags + volumes) — already on main
- [x] **A2** — deploy-development.yml / https://apis.klints.io/health/ — confirm Actions green
- [x] **A3** — https://apis.klints.io/grafana/ reachable; login required
- [x] **A4** — Explore filters service= web / celery_worker / celery_beat / nginx / redis
- [ ] **A5** — Induced ERROR `M3-OBS-01-INDUCE-WEB` appears under service=web
- [x] **A6** — Five separate alert rules (not one combined rule) — as code on main
- [ ] **A7** — Alert email → noreplyklints@gmail.com (send proven **or** stop-and-flag note)
- [x] **A8** — Dashboards + Loki datasource provisioned as code
- [x] **A9** — `python scripts/verify_m3_obs01_backend.py` PASS (static); workflow OBS smoke — confirm live
- [x] **A10** — Runbook present; no product UI Grafana link; no Promtail; no Prometheus required

**Induce evidence:** _paste Explore / LogQL_
**False-fire check:** _redis/other did not fire for marker_
**Email / stop-and-flag:** _paste_
**Actions URL:** _paste_
**Induce disabled again:** _yes / date_

Signed off: _name / date_
```

A1/A3/A4/A6/A8/A10 are **repo-proven** or known staging facts; **A5 + A7 stay unchecked** until ops evidence. Re-confirm A2/A9 Actions on the proof day.

## PR draft (Sahil — open when ready)

**Title:** `docs(M3-OBS-01B): Grafana alert closeout phase notes and handoff`

**Body:**

```markdown
## Summary
- Phase notes for M3-OBS-01B (Grafana alert closeout): Phase 0–4
- Working gaps tracker with Sahil vs ops ownership split
- No runtime code changes — induce/alert/mailer already on main
- Live A5 (Explore marker) + A7 (email / stop-and-flag) remain ops after enable window

## Test plan
- [x] `python scripts/verify_m3_obs01_backend.py` → PASS
- [x] `manage.py test core.tests.M3ObsInduceErrorTests` → 3 OK
- [ ] Ops: induce → Explore `M3-OBS-01-INDUCE-WEB` → email or stop-and-flag → disable induce
- [ ] Paste §11 into PR comment after live proof

## Allowed claim
Staging Grafana log alerts path is ready; live induce + email proof tracked for ops sign-off.

## Do not claim
Pen-test · SEC complete because of Grafana · DP1 · demo/Shopify · Prometheus
```

## Exit criteria

| Exit | When |
|------|------|
| Sahil Phase 4 prep | **Met** — this file + PR draft |
| PRD Phase 4 full | Induce disabled + §11 signed with A5 + A7 |

## Do not

Agent git commit (user commits manually) · claim A5/A7 without evidence · demo/SEC · leave `M3_OBS_INDUCE_ENABLED=true`
