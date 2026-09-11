# PRD-OPS-UC-01 — Seed MVP1 pilots on every environment

**Status:** Implemented (Option A — Dockerfile + verify script)  
**Owner track:** Sahil (`docs/ops/`) — **BE / deploy** (tiny FE only if empty-state copy)  
**Surfaces:** Staging/prod DB · `load_use_case_pilots` · Workflow Studio / recommendations  
**Depends on:** UC-01 (`UseCasePilot` / blueprint models + command already exist)  
**Milestone:** M2 — unblocks `/workflow?uc=UC-02` and Fix → Studio eligibility  
**Out of scope:** New pilots · CAP-01 Matrix · Handoff · Maheep writebacks · changing blueprint JSON  

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-OPS-UC-01 — pilots must exist on staging/prod.

Read:
- docs/ops/PRD_OPS_UC_01_SEED_MVP1_PILOTS_ON_DEPLOY.md
- dataruns/management/commands/load_use_case_pilots.py
- dataruns/use_cases/loader.py

Ship:
1. Run load_use_case_pilots on staging NOW (verify count=16, UC-02 present).
2. Wire seed into deploy path so empty DB cannot recur (§3).
3. Optional: health/assert script or management check (§4).
4. Document one-liner in deploy README / PR note.

Acceptance: §6.
```

---

## 1. Why

Staging DB (e.g. Lumera / `rohan1@mailinator.com`) had:

| Table | Count |
|-------|------:|
| `UseCasePilot` | **0** |
| `UseCaseBlueprint` | **0** |

Effects:

- `/workflow?uc=UC-02` → **404 Use case not found**
- Recommendations empty → Fix **Proceed to Workflow Studio** hidden for CC-03
- QA / Handoff journey blocked before product code is “wrong”

Pilots are **global** (not per-company). Seed once per environment.

---

## 2. Authoritative source

| Artifact | Path |
|----------|------|
| Manifest | `Klints_MVP1_Rohan_Build_Pack_v1.2_20260718/04_MVP1_Pilot_Blueprints/pilot_manifest.json` |
| Blueprints | same dir `UC-*_blueprint.json` (16 files) |
| Command | `python manage.py load_use_case_pilots` |

Expect **exactly 16** pilots including **UC-02**.

---

## 3. Deploy wiring (pick one — document which)

**Implemented: Option A** — `Dockerfile` `web` `CMD` runs `ensure_runtime_catalogue` after `migrate`:
- `seed_dcs_master` **only when** `CheckMaster` is empty/incomplete (empty-DB recovery; workbook shipped via `.dockerignore` exception for `docs/dcs_scoring/`)
- `load_use_case_pilots` **every boot** (idempotent upsert)
Post-deploy verify: `scripts/verify_use_case_pilots.py` + `scripts/verify_dcs_master_catalogue.py` (from `deploy/scripts/deploy.sh`).

| Option | Approach |
|--------|----------|
| **A (preferred)** ✅ | Deploy / entrypoint after migrate: `python manage.py ensure_runtime_catalogue` |
| **B** | CI job / release checklist step with explicit owner |
| **C** | Celery worker/web startup one-shot if count=0 (only if A/B hard) |

Must be **idempotent** (re-run safe). Do not delete company data.

---

## 4. Verify

```bash
python manage.py load_use_case_pilots
# then
python manage.py shell -c "from dataruns.use_cases.models import UseCasePilot; print(UseCasePilot.objects.count()); print(list(UseCasePilot.objects.order_by('pilot_rank').values_list('use_case_id', flat=True)))"
```

Expect: `16` and `UC-02` in the list.

Optional: `scripts/verify_use_case_pilots.py` asserting count=16 + required keys — run in CI or post-deploy (`deploy.sh` invokes this after HTTPS health).

---

## 5. FE (optional, tiny)

If catalogue empty, Studio empty-state may say “Pilot library not seeded — contact ops” instead of bare “not found.” **Not required** if seed is fixed on staging the same day.

---

## 6. Acceptance

- [x] Seed command is on deploy path (**Option A** — `Dockerfile` web CMD after migrate)
- [x] Re-run command is safe (idempotent upsert)
- [x] Verify script: `scripts/verify_use_case_pilots.py` (+ `deploy.sh` post-health)
- [x] Local: `UseCasePilot` count = **16**; UC-02 present (verified Aug 2026)
- [ ] Staging: `UseCasePilot` count = **16**; UC-02 detail **200** (after next deploy)
- [ ] `/workflow?uc=UC-02` opens Studio (not 404) on staging
- [ ] PR note lists who ran seed + verify output on staging

---

## 7. PR title / branch

- Branch: `chore/ops-uc-01-seed-mvp1-pilots`  
- Title: `chore(OPS-UC-01): seed MVP1 pilots on deploy; fix empty Studio catalogue`

---

## 8. Traceability

| Item | Note |
|------|------|
| Parent | UC-01 / BL-010 |
| Unblocks | WF-01 Studio · WF-02 Proceed · QA-01 · HO-01 demos |
| Observed gap | Staging pilots = 0 (Aug 2026) |
