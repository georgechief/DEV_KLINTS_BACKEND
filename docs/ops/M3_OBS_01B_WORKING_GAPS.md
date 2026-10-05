# M3-OBS-01B — Working gaps (Grafana alert closeout)

**PRD:** [PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md](./PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md)  
**Branch:** `feature/m3-obs-01b-grafana-alert-closeout`  
**Status:** Phase 0–4 **Sahil prep done** · ops live (A5/A7/disable/§11) pending · separate from DEMO-01  
**Commit:** user will commit manually (no agent commit)

## Phase board

| Phase | Status | Notes |
|-------|--------|--------|
| 0 — Lock / inventory | [x] | [M3_OBS_01B_PHASE_0.md](./M3_OBS_01B_PHASE_0.md) |
| 1 — Code/docs gap fix | [x] | [M3_OBS_01B_PHASE_1.md](./M3_OBS_01B_PHASE_1.md) — **N/A, no drift** |
| 2 — Live induce + Explore | Sahil [x] · PRD [ ] | [M3_OBS_01B_PHASE_2.md](./M3_OBS_01B_PHASE_2.md) — A5 needs ops |
| 3 — Alert email / stop-and-flag | Sahil [x] · PRD [ ] | [M3_OBS_01B_PHASE_3.md](./M3_OBS_01B_PHASE_3.md) — A7 needs ops |
| 4 — Disable + §11 + PR | Sahil [x] · PRD [ ] | [M3_OBS_01B_PHASE_4.md](./M3_OBS_01B_PHASE_4.md) — sign after live |

## Ownership

| Slice | Owner | Status |
|-------|--------|--------|
| Repo induce + alert/mailer + Phase 0–4 docs | Sahil | **Done** |
| SSH / droplet / induce enable+disable | Rohan/ops | Pending |
| Explore `M3-OBS-01-INDUCE-WEB` (A5) | Ops (+ paste) | **Open** |
| Alert email / stop-and-flag (A7) | Ops (+ paste) | **Open** |
| §11 signed + PR after evidence | Sahil after ops | **Open** |

## Live gaps

| Gap | Status |
|-----|--------|
| Staging induce env enabled briefly | Open (**ops**) |
| Explore shows `M3-OBS-01-INDUCE-WEB` under `service=web` | Open (**ops** → Phase 2) |
| Alert email to noreplyklints@gmail.com | Open (**ops** → Phase 3) |
| Induce disabled again | Open (**ops** → Phase 4) |
| Phase 6 §11 signed | Open (Phase 4 after A5+A7) |

## Repo / static (Sahil)

| Item | Status |
|------|--------|
| Induce view + command + droplet script on `main` | [x] present |
| Five alert rules + mailer bridge | [x] present |
| `verify_m3_obs01_backend.py` | [x] **PASS** |
| `M3ObsInduceErrorTests` | [x] **3 OK** |
| Phase notes 0–4 + WORKING_GAPS | [x] ready to commit |
| README + parent PHASE_6 + runbook link OBS-01B | [x] deep-check fix 2026-09-14 |

**Deep-check (2026-09-14):** No runtime code bugs. Doc gaps fixed: README PHASE_0–4 links; PRD status honesty; PHASE_6 + runbook §7 point at OBS-01B; runbook lists email + disable steps. **PRD still not fully done** until ops A5/A7/§11.

```bash
python scripts/verify_m3_obs01_backend.py
python manage.py test core.tests.M3ObsInduceErrorTests --keepdb
# live (ops): induce → Explore → email/stop-and-flag → disable induce → §11
```
