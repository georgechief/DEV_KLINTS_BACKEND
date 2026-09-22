# PRD-M3-OBS-01B — Grafana Alert Closeout (Phase 6)

**Status:** **Sahil prep done** (Phase 0–4 notes) · **live A5/A7/§11 still open (Rohan/ops)** — **P0 (M3)** · **Separate from demo**  
**Owner track:** Sahil (`docs/sahil/`) for docs/verify/induce polish; **Rohan/ops** for staging env + live sign-off  
**Surfaces:** Grafana · Loki · Alloy · induce ERROR · alert → mailer → `noreplyklints@gmail.com`  
**Milestone:** **M3** — finish observability AC (*… Grafana*) after stack already live  
**Parent:** [PRD_M3_OBS_01_STAGING_GRAFANA_LOKI_ALLOY.md](./PRD_M3_OBS_01_STAGING_GRAFANA_LOKI_ALLOY.md) (Phases 0–5 shipped)  
**SoT:** Parent PRD + [M3_OBS_01_PHASE_6.md](./M3_OBS_01_PHASE_6.md) + [M3_OBS_01_RUNBOOK.md](./M3_OBS_01_RUNBOOK.md)

**Locked decisions (employer · 2026-09-14):**

| # | Decision |
|---|----------|
| D1 | **This PRD is Grafana alerts only** — no demo seed, no Shopify, no SEC rewrite |
| D2 | Stack already on staging (`/grafana/`) — work is **prove induce + alert email + §11** |
| D3 | Induce stays **gated** (`M3_OBS_INDUCE_ENABLED` + token); default off after proof |
| D4 | Alert mail → **`noreplyklints@gmail.com`** via existing mailer bridge (or stop-and-flag with evidence) |
| D5 | Honest claim: *staging Grafana log alerts proven* — **not** security review / DP1 / pen-test |

**Out of scope:** Prometheus (OBS-02) · product FE link · demo contacts · DP1 · SEC-01 · seed scripts  

**Progress:** Tracker [M3_OBS_01B_WORKING_GAPS.md](./M3_OBS_01B_WORKING_GAPS.md) · notes [PHASE_0](./M3_OBS_01B_PHASE_0.md) · [PHASE_1](./M3_OBS_01B_PHASE_1.md) · [PHASE_2](./M3_OBS_01B_PHASE_2.md) · [PHASE_3](./M3_OBS_01B_PHASE_3.md) · [PHASE_4](./M3_OBS_01B_PHASE_4.md) · parent live SoT [M3_OBS_01_PHASE_6.md](./M3_OBS_01_PHASE_6.md)  
**Sahil DoD:** induce/alert path accurate · no code drift · verify PASS · phase notes + PR draft ready  
**PRD DoD (full):** still needs ops A5 Explore marker + A7 email/stop-and-flag + induce off + §11 sign

---

## 0. Cursor agent brief

```text
Implement PRD-M3-OBS-01B — Grafana Alert Closeout only.

Read:
- docs/sahil/PRD_M3_OBS_01B_GRAFANA_ALERT_CLOSEOUT.md
- docs/sahil/PRD_M3_OBS_01_STAGING_GRAFANA_LOKI_ALLOY.md
- docs/sahil/M3_OBS_01_PHASE_6.md
- docs/sahil/M3_OBS_01_RUNBOOK.md
- deploy/scripts/m3-obs-induce-web-error.sh (if present)
- scripts/verify_m3_obs01_backend.py

Ship:
1. Confirm induce path + runbook steps are accurate for current main
2. Close any code gaps blocking induce/alert (flag Rohan for env secrets)
3. Document live proof checklist; fill PHASE_6 evidence when staging proof done
4. Do NOT touch demo seed / Shopify / SEC packet

Acceptance: parent §11 A1–A10 with A5 induce + A7 email proven (or stop-and-flag).
```

---

## 1. Why this PRD exists

OBS-01 shipped Grafana + Loki + Alloy on staging. **Phase 6 live proof is still open:** controlled ERROR → Explore → **alert email**. Without that, M3 observability is incomplete.

This PRD is **separate** from M3-DEMO-01 (Shopify contacts).

---

## 2. What “done” means (simple)

1. Turn on induce briefly on staging  
2. Fire marker `M3-OBS-01-INDUCE-WEB`  
3. See it in Grafana Explore under `service=web`  
4. Confirm alert rule fires and **email arrives** (or documented mailer failure)  
5. Turn induce off  
6. Sign employer checklist  

---

## 3. Contract slice

| # | Need | This PRD |
|---|------|----------|
| M3-O1 | Grafana observability | **YES** — closeout proof |
| M3-D* | Demo / Shopify contacts | **NO** — M3-DEMO-01 |
| M3-S* | Security packet | **NO** — SEC-01 done |

---

## 4. Phases (short)

| Phase | Work |
|-------|------|
| 0 | Confirm env keys on staging (`GF_*`, `MAILER_*`, induce token) with Rohan |
| 1 | Code/docs gap fix if induce/script/runbook drift |
| 2 | Live induce + Explore evidence |
| 3 | Alert email evidence or stop-and-flag |
| 4 | §11 sign-off + PR notes |

---

## 5. Employer checklist (from Phase 6)

See [M3_OBS_01_PHASE_6.md](./M3_OBS_01_PHASE_6.md) § employer checklist A1–A10.  
**Must prove:** A5 induce line · A7 email (or stop-and-flag).

**Allowed claim:** Staging Grafana shows Docker logs and per-service ERROR alerts; alert email path proven (or flagged).

---

## 6. Do not claim

Pen-test · SEC complete because of Grafana · DP1 live · demo contacts from Shopify · Prometheus
