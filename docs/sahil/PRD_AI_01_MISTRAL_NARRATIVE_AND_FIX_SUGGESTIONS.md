# PRD-AI-01 — Mistral narrative layer + Fix AI suggestion box

**Status:** Ready for implementation  
**Owner track:** Sahil (`docs/sahil/`) — BE AI stack + Fix FE suggestion box  
**Depends on:** Live Fix issue bridge (Maheep FE-08 / worklist detail) · CheckMaster suggested_fix · DCS scored run · optional RPT-01 payload hooks  
**Reference (patterns only):** [`docs/AI_AGENT_ORCHESTRATION_BLUEPRINT.md`](../AI_AGENT_ORCHESTRATION_BLUEPRINT.md) — state > prompt, LLM proposes / code disposes, ensure\* gates, JSON retry, named ops, fail closed  
**Security boundary:** [`docs/security/KLINTS_AI_SECURITY_AND_DATA_PROCESSING_RESPONSE.md`](../security/KLINTS_AI_SECURITY_AND_DATA_PROCESSING_RESPONSE.md) §7 — AI explains/narrates only; never scores, gates, or writebacks  
**Out of scope:** Writeback Approve/execute · changing DCS pass/fail · ORCH priority/waves · LiteLLM self-host (adapter interface only) · chat agent / multi-turn support bot · OpenAI/Anthropic as primary

---

## 0. Cursor agent brief (paste this)

```text
Implement PRD-AI-01 — Mistral Small 4 narratives + Fix AI suggestion box.

Read:
- docs/sahil/PRD_AI_01_MISTRAL_NARRATIVE_AND_FIX_SUGGESTIONS.md
- docs/AI_AGENT_ORCHESTRATION_BLUEPRINT.md (patterns only)
- docs/security/KLINTS_AI_SECURITY_AND_DATA_PROCESSING_RESPONSE.md §7

Must ship:
1. Common PrivacyGate — strip PII/client secrets; allow only check defs,
   sanitized findings, platform names, fix_type/owner, aggregate counts.
2. All model I/O is JSON-only (response_format / parse + retry).
3. Primary model: Mistral Small 4 via API id mistral-small-latest
   (pin mistral-small-2603 in env if alias drifts).
4. LangSmith tracing on every AI call (redacted metadata only).
5. Persist every accepted AI suggestion row (AiSuggestion) — never discard.
6. Fix screen: AI suggestion box always shown for live issues
   (load cached suggestion or generate).
7. Task types v1: explain_finding, fix_suggestion, report_narrative,
   nba_blurb (optional).
8. No tools bound to the model. No scores/€ invented. Fail closed.

Acceptance: §12. Ops bootstrap: §11 (LangSmith + sheet + env).
```

---

## 1. Why

Maheep surfaces **facts** on Fix (issue, evidence, CheckMaster fix text). That copy is often technical or thin for merchants.

AI-01 adds a **wording layer**:

| Deterministic (code) | AI (Mistral) |
|----------------------|--------------|
| Check pass/fail, scores, € impact, priority | Plain-language *what’s wrong* |
| CheckMaster `suggested_fix` / fix_type / fix_owner | Merchant-friendly *what to do* steps |
| Platforms connected (Shopify, Manago, …) | Short “why it matters” |
| Evidence counts / mismatch *shapes* (no raw PII) | Suggestion box on Fix |

**Rule of thumb (from blueprint):** *If a wrong answer would lose money, trust, or compliance, put it in code — not only in the prompt.* AI never invents revenue, never approves writebacks, never changes check status.

---

## 2. Blueprint mapping (Klints)

| Blueprint principle | Klints AI-01 |
|---------------------|--------------|
| State > prompt | `AiSuggestion` + DCS run/check ids are truth; prompts only word |
| LLM proposes; code disposes | Model returns JSON; Pydantic validates; UI shows validated fields only |
| ensure\* before speech | **PrivacyGate** + **ContextAllowlist** run *before* every Mistral call |
| Specialize nodes | Separate task types / prompt IDs — not one mega-agent |
| Minimal tool menu | **Zero tools** in v1 (no function calling) |
| JSON retry | Parse fail → re-invoke up to 3×; then fail closed |
| Observable by default | LangSmith trace per call + DB row with model/prompt versions |
| Fail closed | Invalid JSON / gate deny → hide AI box body, show “Suggestion unavailable”, keep deterministic CheckMaster text |

---

## 3. Architecture

```text
Caller (Fix API / Report compose / Overview NBA)
  → build AiTaskRequest (task_type, company_id, check_id, run_id, …)
  → PrivacyGate.ensure_safe_context()     # FAIL CLOSED if leaks
  → ContextAllowlist.project()            # only approved fields
  → fingerprint = hash(task_type + allowlisted payload + prompt_version)
  → AiSuggestion lookup by fingerprint   # reuse if fresh
  → if miss: Mistral structured JSON (traced in LangSmith)
  → validate JSON schema
  → ALWAYS persist AiSuggestion (+ AiCall metadata)
  → return to FE / attach to report payload
```

**No side-effect tools.** Model cannot call Shopify/Manago/DB.

---

## 4. Common PrivacyGate (mandatory)

Single module used by **every** AI task. This is the product’s `ensure*` for AI.

### 4.1 Never send to the model

| Class | Examples |
|-------|----------|
| Contact / customer PII | email, phone, name, address, externalId, contactId, smclient, cookie ids |
| Order / commerce PII | order numbers tied to people, shipping addresses, payment refs |
| Secrets | API keys, tokens, Authorization, webhook secrets, OAuth |
| Raw dumps | full `mismatches[].value` objects that embed customer fields, raw JSON blobs, log lines with emails |
| Tenant internals | DB PKs beyond check/run ids, staff emails (except operator’s own session — **not** in prompt), invoices |
| Free-text customer messages | support tickets, chat transcripts |

### 4.2 Always allowed (enough for good messages)

| Field | Source |
|-------|--------|
| `check_id`, `check_name` (Title Case) | CheckMaster / worklist |
| `dimension`, `severity`, `status` | worklist |
| `systems_compared` / platform names | e.g. `Shopify`, `Manago`, `Excel` — **product names only** |
| `suggested_fix`, `fix_type`, `fix_owner` | CheckMaster (definition-level) |
| Sanitized finding summary | Aggregates only: counts, % drift, field *paths* (`contact.email`), mismatch *kinds* (`missing`, `stale`, `conflict`) — **no values** |
| `revenue_impact` as **already computed** number + currency | DCS-08 — AI may *restate*, never invent |
| Architecture verdict enums | Keep / Improve / Fix-first / … (labels only) |
| Company **display name** + industry vertical if set | No domain/URL required; if domain present, strip to registrable hostname only (optional) |

### 4.3 Sanitizer rules (code)

1. Walk evidence / mismatches → emit `{ path, kind, side }` only; drop `value`, `raw`, `sample`.  
2. Regex scrub emails, E.164 phones, UUIDs that look like contact ids, `Bearer …`.  
3. Cap list lengths (e.g. max 12 mismatch rows, max 800 chars per string).  
4. If after sanitize the payload still matches PII patterns → **deny call** (fail closed).  
5. Gate result logged as metadata only (`gate=pass|deny`, reason code) — **never** log the rejected payload body to app logs.

### 4.4 What LangSmith may see

Same allowlist as the model prompt. **Do not** put raw customer evidence into LangSmith inputs/outputs. Prefer:

- `company_id`, `check_id`, `run_id`, `task_type`, `prompt_version`, `fingerprint`
- Allowlisted JSON (already gated)
- Validated output JSON
- Token counts, latency, errors

Turn off any LangSmith feature that stores full unconstrained chat history outside our wrapper.

---

## 5. Task types (product surfaces)

| `task_type` | Where used | Purpose |
|-------------|------------|---------|
| **`fix_suggestion`** | **Fix screen suggestion box (v1 must-ship)** | Merchant steps + plain “what’s wrong” |
| **`explain_finding`** | Data Center detail / Diagnose drawer (optional same PR) | Short explanation of the finding |
| **`report_narrative`** | Assessment PDF / report payload (after RPT-01B ok) | Exec summary + “why it matters” paragraphs |
| **`nba_blurb`** | Overview next-best-action card (optional) | One-line why this is next — **does not change plan order** |
| **`af_rationale`** | Lifecycle card (later) | One sentence on verdict — enum unchanged |
| **`pilot_blurb`** | Opportunities pilot card (later) | Why this pilot fits — gates stay deterministic |

**v1 acceptance = `fix_suggestion` + shared gate + persist + LangSmith.**  
Wire `report_narrative` in the same BE module so RPT can call it next; FE PDF hook may be a follow-up commit in the same PR if time allows.

### Hard bans (all tasks)

- No new scores, severities, check statuses  
- No invented € / revenue  
- No writeback field patches or API payloads  
- No “approve this” language that implies execution  
- No ranking / reordering of ORCH plan  

---

## 6. JSON-only contracts

Every call: **response must be a single JSON object**. Prefer Mistral JSON mode / schema. On parse failure: retry ≤3, then fail closed.

### 6.1 `fix_suggestion` (Fix box)

```json
{
  "task_type": "fix_suggestion",
  "check_id": "LE-04",
  "headline": "Lifecycle stage is out of sync between Shopify and Manago",
  "whats_wrong": "The two platforms disagree on where customers sit in the lifecycle for a meaningful share of the base.",
  "why_it_matters": "The agent may message the wrong people or skip win-back when stage is wrong.",
  "suggestions": [
    {
      "step": 1,
      "title": "Confirm the source of truth for stage",
      "detail": "Decide whether commerce or CDP owns lifecycle for this brand."
    },
    {
      "step": 2,
      "title": "Align the mapped stage fields",
      "detail": "Use the CheckMaster remediation: repair the mapped stage / detail fields — do not invent new native fields."
    }
  ],
  "cautions": [
    "Do not bulk-overwrite native fields without a sandbox proof."
  ],
  "confidence": "medium"
}
```

**Rules for model (system prompt):**

- `suggestions` length 2–5  
- Steps must stay consistent with CheckMaster `suggested_fix` / `fix_type` / `fix_owner` — paraphrase, don’t contradict  
- No contact examples, no fake emails, no invented SKUs  
- `confidence` ∈ `low|medium|high`  
- English, Title Case for `title` fields (FE-09 spirit)

### 6.2 `explain_finding`

```json
{
  "task_type": "explain_finding",
  "check_id": "CI-13",
  "headline": "…",
  "explanation": "2–4 sentences",
  "systems": ["Shopify", "Manago"]
}
```

### 6.3 `report_narrative`

```json
{
  "task_type": "report_narrative",
  "exec_summary": "3–5 sentences",
  "top_themes": ["…", "…"],
  "recommended_focus": "1–2 sentences pointing at top plan items by check_id only"
}
```

Input to this task is an **allowlisted rollup** (score, top N check_ids + names + severities + restated € if present) — not full worklist dumps.

### 6.4 Envelope stored on every call

```json
{
  "schema_version": 1,
  "prompt_version": "ai01.fix_suggestion.v1",
  "policy_version": "privacy_gate.v1",
  "model": "mistral-small-latest",
  "provider": "mistral",
  "fingerprint": "sha256:…",
  "output": { }
}
```

---

## 7. Persistence (always save)

**Never throw away a successful model response.** Failed parses after retries still write an `AiCall` row with `status=failed` (no suggestion body).

### 7.1 Models (Django)

**`AiCall`** — one row per provider attempt/batch:

| Column | Notes |
|--------|-------|
| `id` | UUID |
| `company_id` | tenant |
| `task_type` | enum |
| `check_id` | nullable (report-level null) |
| `dcs_run_id` | nullable FK/id |
| `fingerprint` | sha256 of allowlisted input + prompt_version |
| `prompt_version`, `policy_version` | strings |
| `model`, `provider` | e.g. mistral / mistral-small-latest |
| `langsmith_run_id` | nullable |
| `status` | `success` \| `failed` \| `gate_denied` |
| `error_code` | nullable |
| `latency_ms`, `input_tokens`, `output_tokens` | nullable |
| `created_at` | |

**`AiSuggestion`** — customer-facing artifact (always on success):

| Column | Notes |
|--------|-------|
| `id` | UUID |
| `ai_call_id` | FK |
| `company_id` | |
| `task_type` | |
| `check_id` | |
| `dcs_run_id` | |
| `fingerprint` | unique per company+task+fingerprint (upsert) |
| `payload_json` | validated output object |
| `headline` | denormalized for list UIs |
| `created_at`, `updated_at` | |

**Retention:** keep suggestions for the life of the company (or product retention policy). Do **not** regenerate silently and overwrite without fingerprint change — upsert same fingerprint; new fingerprint = new row (or version column).

### 7.2 Cache / freshness

- Reuse `AiSuggestion` when fingerprint matches (same check + same allowlisted inputs + same prompt_version).  
- Invalidate when DCS run changes for that check, or CheckMaster remediation text changes, or prompt_version bumps.  
- Fix UI: show cached instantly; optional “Regenerate” only for staff/admin later (not required v1).

---

## 8. Provider + model + tracing

### 8.1 Mistral (primary)

| Item | Value |
|------|-------|
| Provider | Mistral AI (La Plateforme) |
| Primary model (product name) | **Mistral Small 4** |
| API model id | `mistral-small-latest` (alias) |
| Pin (recommended in env) | `mistral-small-2603` if you need freeze |
| Adapter | `dataruns/ai/providers/mistral.py` implementing `AiProvider.complete_json(...)` |
| Temperature | low (e.g. 0.2–0.4) for remediation copy |
| Timeout | hard timeout per call (e.g. 30s) |
| Fallback | none in v1 (fail closed); optional second Mistral model later |

Env (names indicative):

```text
MISTRAL_API_KEY=…
MISTRAL_MODEL=mistral-small-latest
AI_ENABLED=true
AI_PRIVACY_POLICY_VERSION=privacy_gate.v1
```

### 8.2 LangSmith (all AI runs traced)

| Item | Value |
|------|-------|
| Purpose | Trace every AI call (latency, tokens, allowlisted I/O, errors) |
| Account email | **`noreplyklints@gmail.com`** (Klints no-reply Gmail) |
| Project name | `klints-mvp1-ai` (or `klints-ai-prod` / `klints-ai-staging` split) |
| SDK | `langsmith` Python; wrap Mistral calls with `@traceable` / `RunTree` |
| Tags | `task_type`, `check_id`, `company_id`, `prompt_version`, `policy_version` |

Env:

```text
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=…
LANGCHAIN_PROJECT=klints-mvp1-ai
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
```

**Install (BE):**

```bash
pip install langsmith mistralai
# pin versions in requirements / uv lock
```

Wire tracing in the shared `complete_json` helper so **no caller can forget** to trace.

### 8.3 Credentials inventory (Google Sheet — ops)

Create / update a private Google Sheet (access: founders + Sahil only), e.g. **`Klints — AI credentials inventory`**:

| Column | Example |
|--------|---------|
| Service | Mistral / LangSmith |
| Account email | noreplyklints@gmail.com |
| Project / workspace | klints-mvp1-ai |
| Secret name | `MISTRAL_API_KEY` / `LANGCHAIN_API_KEY` |
| Where stored | DO App Platform / Doppler / 1Password (never commit) |
| Model | mistral-small-latest (Small 4) |
| Created | date |
| Rotated | date |
| Notes | EU processing note; LangSmith is tracing SaaS — only gated payloads |

**Do not put live secret values in git or this PRD.** Sheet holds inventory + pointers; secrets live in the secret manager.

---

## 9. API (BE)

### 9.1 Get or create Fix suggestion

```http
POST /api/v1/ai/suggestions/fix/
Authorization: Bearer …
Content-Type: application/json

{
  "check_id": "LE-04",
  "dcs_run_id": 123   // optional; default = latest scored run for company
}
```

**Response 200:**

```json
{
  "suggestion_id": "…",
  "check_id": "LE-04",
  "fingerprint": "sha256:…",
  "cached": true,
  "model": "mistral-small-latest",
  "prompt_version": "ai01.fix_suggestion.v1",
  "payload": { /* §6.1 */ }
}
```

**404** — check not in worklist / unknown  
**422** — gate denied (no model call)  
**503** — AI disabled or provider down (FE shows fallback)

Idempotent: same fingerprint → return existing row (`cached: true`).

### 9.2 Optional batch for report

```http
POST /api/v1/ai/narratives/report/
{ "dcs_run_id": 123, "assessment_report_id": "…" }
```

Attaches `report_narrative` into report payload under `ai.narratives` (does not regenerate PDF history by re-prompting — store on compose).

---

## 10. Fix FE — suggestion box

**File focus:** `klints_frontend` Fix route (`src/routes/fix.tsx`) + small client in `src/lib/ai.ts`.

### Placement

Below the Fix hero KV / touchpoints (after deterministic summary), **above** Evidence / Writeback preview:

```text
┌─────────────────────────────────────────┐
│ AI suggestion                           │
│ {headline}                              │
│ What’s wrong · Why it matters           │
│ 1. …  2. …  3. …                        │
│ Cautions                                │
│ Source: Mistral · cached · check LE-04  │
└─────────────────────────────────────────┘
```

### Behaviour

| State | UI |
|-------|-----|
| Loading | Skeleton in the box |
| Success | Show payload fields; keep CheckMaster “What changes” KV as source of truth |
| Cached | Same UI; subtle “Saved suggestion” |
| Fail / gate deny / AI off | Box remains with short message: “AI suggestion unavailable — follow the suggested fix above.” **Never blank the whole Fix page** |
| Fixture / no issue | Hide box |

Always call `POST …/ai/suggestions/fix/` when `isLive && check_id` present (on issue load). Do not require a separate button for v1 (auto). Optional “Refresh” later.

Copy rules: Title Case titles; no raw JSON in the box (render fields). Show JSON only in devtools/network.

---

## 11. Ops bootstrap (Rohan / Sahil — before merge to prod)

Do this once; PRD does not embed secrets.

1. **LangSmith**  
   - Sign up / log in with **`noreplyklints@gmail.com`** at [https://smith.langchain.com](https://smith.langchain.com)  
   - Create project `klints-mvp1-ai`  
   - Create API key → store in secret manager + inventory sheet  

2. **Mistral**  
   - Ensure La Plateforme project under same ops ownership  
   - Confirm model access to **Mistral Small 4** (`mistral-small-latest` / pin `mistral-small-2603`)  
   - Create API key → secret manager + inventory sheet  

3. **Google Sheet**  
   - Create **Klints — AI credentials inventory** (private)  
   - Rows for Mistral + LangSmith as in §8.3  
   - Link sheet URL in Notion/ops wiki (not in public README if sensitive)  

4. **Deploy env**  
   - Set `MISTRAL_*`, `LANGCHAIN_*`, `AI_ENABLED` on staging first  
   - Smoke: one Fix suggestion for Lumera sandbox → row in DB + trace visible in LangSmith  

5. **Verify redaction**  
   - Open LangSmith run → inputs must **not** contain emails/phones/order ids  

---

## 12. Acceptance

### BE

- [ ] `PrivacyGate` unit tests: email/phone/token in evidence → deny or stripped; allowlisted-only payload passes  
- [ ] `complete_json` retries invalid JSON ≤3; then `status=failed` AiCall  
- [ ] Success path always inserts `AiSuggestion`  
- [ ] Fingerprint hit returns `cached: true` without second billable call (or with explicit cache skip flag off by default)  
- [ ] LangSmith run id stored when tracing enabled  
- [ ] Model id defaults to Mistral Small 4 alias  
- [ ] No code path sends mismatch `value` fields to the provider  

### FE

- [ ] Live Fix shows AI suggestion box  
- [ ] Renders headline / what’s wrong / steps / cautions from JSON fields  
- [ ] Failure state does not break Fix evidence/writeback preview  
- [ ] No raw JSON dumped into the box  

### Product / security

- [ ] AI cannot change scores or writebacks  
- [ ] Inventory sheet exists; secrets not in git  
- [ ] Staging trace reviewed for PII leak  

---

## 13. Prompt ID family

| ID | Use |
|----|-----|
| `ai01.system.v1` | Shared: JSON only, no PII, no invent €, paraphrase CheckMaster |
| `ai01.fix_suggestion.v1` | Fix box |
| `ai01.explain_finding.v1` | Diagnose |
| `ai01.report_narrative.v1` | PDF / payload |
| `ai01.nba_blurb.v1` | Overview (optional) |

Bump version suffix on any behaviour change → new fingerprints → new stored suggestions.

**REQUIRED THIS TURN** (injected per task, blueprint style), example for Fix:

```text
REQUIRED THIS TURN: Return ONLY the fix_suggestion JSON schema.
Paraphrase CheckMaster suggested_fix; do not contradict fix_type/fix_owner.
Do not invent revenue. Do not include any email, phone, or contact identifier.
```

---

## 14. Suggested code layout

```text
dataruns/ai/
  privacy_gate.py      # ensure_safe_context + scrubbers
  allowlist.py         # project worklist → AiContext
  fingerprints.py
  schemas.py           # Pydantic models per task_type
  service.py           # get_or_create_suggestion
  providers/
    base.py
    mistral.py
  tracing.py           # LangSmith wrappers
  prompts/
    fix_suggestion_v1.txt
    …
dataruns/models.py     # AiCall, AiSuggestion
api routes under /api/v1/ai/…
```

FE:

```text
src/lib/ai.ts
src/components/klints/FixAiSuggestionBox.tsx
src/routes/fix.tsx     # mount box
```

---

## 15. Sequencing vs other Sahil work

| Order | Work | Notes |
|-------|------|-------|
| 1 | **RPT-01B** (deterministic PDF polish) | Can ship in parallel; do not block AI-01 |
| 2 | **AI-01** (this PRD) | Fix box + gate + Mistral + LangSmith + persist |
| 3 | Hook `report_narrative` into report compose | After 01B content solid |
| 4 | ORCH-02 / BL-012 waves | Still no LLM ranking |

Maheep continues writeback Approve / FE-11 Elements — **orthogonal**.

---

## 16. Definition of done

1. PrivacyGate is the only path into the model.  
2. Fix live issues show a saved, JSON-validated AI suggestion box.  
3. Every success is in `AiSuggestion`; every attempt is in `AiCall` (+ LangSmith when enabled).  
4. Primary model is **Mistral Small 4**; traces land in LangSmith project under **noreplyklints@gmail.com**.  
5. A teammate can explain “what AI may see” from §4 without reading prompts.
