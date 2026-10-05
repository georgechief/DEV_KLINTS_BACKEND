# Master Blueprint: Conversational Agent Orchestration

> Supply this document to an AI (or a team) when building a multi-step agent in **any** product.  
> It is domain-agnostic: booking, support, ops, onboarding, sales, internal tools — same skeleton.  
> Copy the **patterns**, not any specific industry nouns.

---

## 0. How to use this doc

1. Paste / attach this file as the architecture brief for a new agent.
2. Fill the checklist in [§16](#16-build-checklist-copy-into-your-prd).
3. Implement in this order: **state → flags/modes → ensure\* gates → tools → prompt IDs → graph → async policy → tests → observability**.
4. Reject designs that put money/trust decisions only in free-form prompts.

---

## 1. Core principles

| # | Principle | Meaning |
|---|-----------|---------|
| 1 | **State > prompt** | Typed statuses decide what may happen next. Prompts only explain and word. |
| 2 | **LLM proposes; code disposes** | Models suggest entities and ask questions. Code validates IDs, eligibility, and side effects. |
| 3 | **Specialize nodes** | Don’t put routing + extraction + reply + safety in one mega-agent. |
| 4 | **Minimal tool menu** | Bind only tools legal for the current stage/mode. |
| 5 | **Preflight before speech** | Compute hard facts (`ensure*`) *before* the customer-facing LLM turn. |
| 6 | **Addressable rules** | Every policy line has a systematic ID; overrides are explicit. |
| 7 | **Per-turn imperatives** | Inject `REQUIRED THIS TURN` from state — stronger than static policy alone. |
| 8 | **Fingerprint invalidation** | When inputs change, clear dependent outputs. Never reuse stale caches. |
| 9 | **Fail closed on irreversible paths** | On uncertainty for money/trust/PII actions → clarify, hand off, or error — don’t invent. |
| 10 | **Cap autonomy** | Bounded tool loops, timeouts, retries with budget, human escape hatch. |
| 11 | **Channel guarantees in code** | Legal disclaimers, receipts, tickets — don’t rely on the model remembering. |
| 12 | **Multi-tenant by data, not hardcoding** | Policy comes from this tenant’s FAQ/catalog/config — not hardcoded product names. |
| 13 | **Observable by default** | One status line per turn; named LLM operations; correlation IDs. |
| 14 | **Test the gates** | Unit-test state transitions with generic fixtures. |

**Rule of thumb:** *If a wrong answer would lose money, trust, or compliance, put it in code/state — not only in the prompt.*

---

## 2. Mental model

```text
Inbound event (message, webhook, job, voice turn)
    → Build Context (tenant, user, thread, history, feature flags)
    → Parallel enrichment agents (extract / retrieve)     [often fire-and-forget]
    → Graph:
         Intent / insights
         → Router (which skill | human)
         → Skill agent (ensure* → tools → reply LLM)
         → Optional supervisor / safety / minifier
         → Reply to channel
    → Post-hooks (guaranteed messages, tickets, labels, audit)
```

### Layer ownership

| Layer | Owns | Must not own |
|-------|------|----------------|
| **Orchestrator / graph** | Node order, edges, channel I/O, pacing | Step logic (“ask X next”) |
| **Context + state** | Truth: IDs, statuses, fingerprints, caches | Natural-language wording |
| **ensure\* / utils** | Deterministic gates, API calls, parsing | Customer-facing prose |
| **Chat LLM** | Wording, questions, choosing among *allowed* tools | Skipping gates; inventing offerings against source of truth |
| **Tools** | Side effects (create, charge, book, email) | Product policy decisions |
| **Post-hooks** | Guarantees the model might omit | Re-deciding business eligibility |

---

## 3. Feature flag → mode → tool menu

### Pattern

1. Tenant/product has a **flag or bitmask** for capabilities.
2. Context exposes booleans (`isFlowA`, `isLegacy`, …).
3. Mode switches:
   - API base URL / credentials scope
   - Which tools are bound
   - Which prompt block is concatenated
   - Which post-hooks run
   - Whether a supervisor node is skipped

```ts
// Pattern — adapt names to your product
get isAdvancedFlow(): boolean {
  return (this.bot.config.modules & Modules.ADVANCED_FLOW) !== 0;
}

const tools = [knowledgeTool(ctx)];
if (ctx.isAdvancedFlow) {
  tools.push(catalogTool(ctx), availabilityTool(ctx), commitTool(ctx), crmLookupTool(ctx));
} else if (ctx.isLegacyFlow) {
  tools.push(/* legacy set */);
} else {
  tools.push(simpleCommitTool(ctx));
}
```

**Best practice:** Never bind a tool that can skip a gate. Prefer both:

- omit the tool from the menu when illegal, **and**
- re-validate state inside the tool (belt and suspenders).

---

## 4. Orchestration graph

### Recommended node set

| Node | Responsibility |
|------|----------------|
| **Insights / intent** | Tags, retrieval queries, “is this about X?” |
| **Router** | Skill A vs skill B vs human |
| **Extractors** (side) | Structured fields from dialogue → state |
| **Skill agent** | Preflight + tools + customer reply |
| **Supervisor / safety** | Emergency takeover, policy veto, length control |
| **Reply** | Channel send, multi-bubble pacing |
| **Human assign** | Handoff + notes |

### Example graph

```text
START
  → insights
  → router
       ├─ human → assign → END
       └─ skill_agent
            ├─ (commit / handoff / “skip supervisor” modes) → reply → END
            ├─ long_reply → minifier → supervisor → …
            └─ supervisor → reply | human
```

### Two timelines

| Timeline | Awaited? | Purpose |
|----------|----------|---------|
| **Critical path** | Yes | Support/eligibility → quote/price → availability/lock → proceed |
| **Enrichment path** | Often no | Early extraction, prefetch catalogs — must not win over critical re-checks |

**Best practice:** Parallel agents may *propose* state; the skill agent’s `ensure*` + cache keys are authoritative before the user-facing turn.

---

## 5. State machine design

### Principle

Free-text alone is **not** progress. Progress = typed fields with explicit statuses.

### Generic state shape

```ts
type FlowState = {
  // Entity lock (UUID / SKU / ticket type — never only free text)
  entityId?: string;
  entityLabel?: string; // friendly name for prompts; never trust alone

  // Eligibility / support
  supportStatus?: 'supported' | 'unsupported' | 'clarify' | 'pending';
  supportCheckedFor?: string; // fingerprint of the user’s ask

  // Downstream readiness
  quoteStatus?: 'ready' | 'clarifying' | 'missing';
  quoteValue?: number;
  quotedForKey?: string; // fingerprint of quote inputs

  availabilityStatus?: 'free' | 'busy' | 'error' | 'pending';
  availabilityCheckedFor?: string; // fingerprint of availability inputs
  availabilityOptions?: unknown[];

  // Explicit customer affirmation before irreversible action
  proceedConfirmed?: boolean;
  proceedFingerprint?: string;

  // Payload the extractors fill
  params?: Record<string, unknown>;
};
```

### Bookable / actionable gate (pattern)

```ts
function isActionable(s?: FlowState): boolean {
  if (!s) return false;
  if (s.supportStatus === 'unsupported') return false;
  if (s.supportStatus === 'clarify' || s.supportStatus === 'pending') return false;
  return !!(s.entityId && String(s.entityId).trim());
}
```

### Canonical progression (adapt nouns)

```text
User names a need
  → supportStatus
       unsupported → decline; STOP (no next commercial step)
       clarify     → offer only real catalog / allowed options
       supported + entityId
         → collect required dimensions (size, duration, plan, …)
         → quoteStatus = ready
         → collect schedule / target
         → availabilityStatus = free | busy | …
         → summary + proceed ask
         → batch missing PII / required fields
         → commit tool
              success path → receipt / payment / next-step hooks
              complex path → soft handoff (no silent auto-commit)
```

### Fingerprints (invalidate stale state)

| Change | Invalidate |
|--------|------------|
| User’s ask / scope text | support status, entityId (if unsupported), quote, availability, proceed |
| entityId or quote inputs | quote |
| entityId / date / time / target | availability cache |
| Any field in proceed fingerprint | `proceedConfirmed` |

```ts
function scopeKey(params): string {
  return [params.need, params.details].map(x => String(x || '').trim().toLowerCase()).join('|');
}

function availabilityKey(entityId, date, slotOrBand): string {
  return `${entityId}|${date}|${slotOrBand || 'day'}`;
}
```

**Best practice:** On key mismatch, clear arrays/statuses — don’t “mostly reuse.”

---

## 6. Deterministic preflight (`ensure*`)

### Pattern

In the skill agent, **before** invoking the reply LLM:

```ts
await ensureSupported(ctx);     // FAQ/policy + catalog → supportStatus [+ entityId]
await ensureQuoted(ctx);        // only if isActionable
await ensureAvailable(ctx);     // only if isActionable + required inputs
syncProceedConfirmed(ctx);      // sync: regex / button / fingerprint
```

Then inject:

1. Machine-readable `<flow_context>` (statuses + key fields).
2. A **REQUIRED THIS TURN** string derived from those statuses.

### Fail policy

| Check | On error / ambiguity |
|-------|----------------------|
| Support / eligibility LLM fails | → `clarify` or handoff (fail closed for commit) |
| Availability / inventory API fails | → `error` / `pending` — do not invent “free” |
| Quote parse fails | stay `clarifying` / `missing` — do not invent totals |
| Commit tool fails | surface error; do not claim success |

### Order = dependency order

Never ask for price dimensions before support.  
Never check availability before entity lock.  
Never allow commit before proceed (when the product requires affirmation).

---

## 7. Prompt system: systematic IDs

### Why IDs

- Addressable in logs and reviews (“violated ID=…”)
- Overridable per mode without deleting shared rules
- Debuggable when the model drifts

### Naming conventions

```text
[ID=<number>]                 # shared / global rules
[ID=<number>-OVERRIDE]        # mode-specific replacement of that number
[ID=<number>-<FLOW>-<NAME>]   # flow family, e.g. 51-BOOK-ORDER, 90-CR-SCOPE
```

### Structure inside the system prompt

```xml
<role>…</role>

<conversation_flow_instructions>
- [ID=10] …
- [ID=51-FLOW-ORDER] Canonical order: (1) … (2) … Never jump ahead.
- [ID=51-FLOW-SCOPE] Honor flow_context.supportStatus. If unsupported: decline and STOP.
…
</conversation_flow_instructions>

<communication_guidelines>
- [ID=20] …
</communication_guidelines>

<flow_context>
supportStatus: unsupported
quoteStatus: not set
availabilityStatus: pending
proceedConfirmed: no
entityId: (not set)
</flow_context>

<required_this_turn>
REQUIRED THIS TURN: supportStatus=unsupported — decline clearly. Do NOT ask for next-step dimensions. Do NOT quote. Do NOT call commit tools.
</required_this_turn>
```

### Writing good IDs

1. **One ID = one job.**
2. Name the **forbidden** action (“Do NOT ask for X”).
3. Reference **state field names** (`supportStatus=unsupported`).
4. Keep IDs short; put long catalogs in tools/retrieval, not in static rules.
5. Use OVERRIDE only when the same numeric ID exists in another mode.
6. Prefer positive order IDs (`*-ORDER`) plus hard stop IDs (`*-SCOPE`).

### Static vs runtime

| Kind | Role |
|------|------|
| Static `[ID=…]` | Constitution — always true for the mode |
| `<flow_context>` | Facts for this turn |
| `REQUIRED THIS TURN` | Traffic light — what must happen *now* |

**Best practice:** When static policy and state disagree in practice, trust state-driven REQUIRED lines and fix the `ensure*` bug — don’t add another paragraph hoping the model notices.

### Suggested ID families for a new flow

| Family | Examples |
|--------|----------|
| Intake | ask missing fields in batch; don’t re-ask CRM-filled |
| Scope / eligibility | unsupported stop; clarify against catalog only |
| Format | channel formatting (bullets, no markdown tables, …) |
| Money / quote | one total; no rate-matrix dumps |
| Lock / availability | never claim free without live check |
| Summary / proceed | no commit until affirmed |
| Commit | must call tool when complete; never fake success |
| Handoff | when to soft-handoff vs auto-execute |
| Safety | PII, no inventing policy, no exposing internal IDs |

---

## 8. Tools

### Manual tool loop (recommended)

Prefer an explicit loop over opaque unbounded agents:

```ts
const boundLlm = llm.bindTools(tools);
const MAX_ITERATIONS = 10;

for (let i = 0; i <= MAX_ITERATIONS; i++) {
  const aiMessage = await boundLlm.invoke(messages);
  const toolCalls = aiMessage.tool_calls ?? [];

  if (toolCalls.length === 0) {
    finalText = String(aiMessage.content ?? '');
    break;
  }

  messages.push(aiMessage);
  for (const call of toolCalls) {
    const tool = toolMap.get(call.name);
    const observation = tool
      ? await tool.invoke(call.args)
      : JSON.stringify({ error: `Unknown tool: ${call.name}` });
    messages.push(new ToolMessage({
      content: typeof observation === 'string' ? observation : JSON.stringify(observation),
      tool_call_id: call.id ?? `call_${i}_${call.name}`,
    }));
  }
}
```

### Tool design

| Do | Don’t |
|----|-------|
| Name for outcome (`commitOrder`, `validateAndSchedule`) | Name for internals (`BackendClientV2Wrapper`) |
| Return structured facts (ids, urls, errors, status) | Return essays the model must re-parse blindly |
| Validate state inside the tool | Trust the model’s claim that “everything is ready” |
| Idempotency keys where possible | Double-charge / double-book on retry |
| Small, sharp tools | One god-tool that does five business steps |

### Tool menu by stage (example)

| Stage | Tools |
|-------|-------|
| Discover | knowledge / FAQ / catalog list |
| Quote | pricing (read-only) |
| Schedule / reserve check | availability (read-only) |
| After proceed + fields complete | commit / pay / provision |
| Anytime (gated) | CRM lookup (read), handoff note |

---

## 9. Async, wait, retry, fallback

### Patterns

| Pattern | When | Notes |
|---------|------|-------|
| **Await critical chain** | User reply depends on it | `ensure*` sequence |
| **Fire-and-forget** | Enrichment | Must not override critical gates later |
| **`Promise.all` prefetch** | Independent I/O | CRM + catalog + pricing in parallel |
| **Poll wait** | Sibling still writing state | Bounded sleep loop with timeout |
| **Channel pacing** | Multi-bubble UX | Delay between messages so order is readable |
| **JSON / schema retry** | Structured LLM output | Re-invoke up to N times on parse fail |
| **Provider fallback** | Rate limit / outage | Primary → secondary model/provider |
| **Hard timeout** | Hung calls | Every LLM/HTTP call has a timeout |
| **Trace wrappers** | External HTTP | Span name + tenant + conversation metadata |
| **Cache keys** | Avoid stale reuse | Always pair data with `checkedFor` |

### Structured LLM helper (pattern)

```ts
async function invokeStructured<T>(args: {
  operationName: string;
  invokePrimary: () => Promise<unknown>;
  invokeFallback: () => Promise<unknown>;
  parse: (raw: string) => T;
  maxAttempts?: number;
  timeoutMs: number;
}): Promise<T> {
  const max = args.maxAttempts ?? 3;
  let lastErr: unknown;
  for (let attempt = 1; attempt <= max; attempt++) {
    try {
      const result = await withProviderFallback(args.invokePrimary, args.invokeFallback, args.timeoutMs);
      const raw = extractText(result);
      return args.parse(raw);
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr;
}
```

### Concurrency rules

1. Critical gates **re-check** fingerprints even if a parallel agent already filled fields.
2. If support = unsupported, enrichment agents must **not** fuzzy-lock a “closest” entity.
3. Prefer await for “what may we ask next?”; parallelize only pure enrichment/retrieval.

---

## 10. Retrieval & source of truth

| Source | Role |
|--------|------|
| Tenant FAQ / policy docs | Eligibility, “we don’t offer X”, process rules |
| Live catalog / config API | What can actually be sold / changed / booked |
| Structured LLM over (ask + FAQ + catalog) | `supported \| unsupported \| clarify` + optional id |
| Live inventory / calendar API | Free vs busy — never invent |

**Best practice:** Do **not** use token-overlap / keyword scoring alone as the eligibility gate. It false-matches shared words and misses explicit “we don’t offer X” policy. Scoring may rank shortlists; the **decision** is FAQ/policy + structured choice from real IDs.

**Best practice:** Bound retrieval context size (chars / top-k). Prefer scoped FAQ intents over dumping the whole KB every turn.

---

## 11. Human handoff & safety

| Trigger | Behavior |
|---------|----------|
| User asks for human | Route to human; preserve notes |
| Unsupported / out of policy | Decline + optional allowed options; handoff only if product requires |
| High risk / multi-step complex | Soft handoff: explain, private note, open queue — **no silent auto-commit** |
| Abuse / jailbreak / PII leak risk | Supervisor veto or hard refuse |
| Model uncertainty on irreversible action | Clarify or handoff — never guess |

**Best practice:** Separate **customer-visible** handoff wording from **private agent notes**.

---

## 12. Channel & post-hooks

The reply LLM is not a reliable courier for guarantees.

| Concern | Where |
|---------|-------|
| Payment / legal disclaimer | Post-hook after successful commit (own message) |
| Receipt / link if model omitted it | Post-hook append |
| Ticket / conversation status | Post-hook |
| Labels / analytics | Post-hook or side webhook |
| Multi-bubble split | Deterministic splitter (`---` / array) + paced send |

---

## 13. Observability

Log **one structured line per skill turn**:

```text
[flow] support=unsupported entityId=none quote=none availability=pending proceed=false tools=catalog,crm
```

Also:

- Correlation / request / thread IDs on every log and LLM metadata tag.
- Named operations: `ServiceSupportCheck`, `QuoteExtract`, `AvailabilityCheck`.
- Persist tool intermediate steps for replay.
- Alert on: commit without proceed, quote without entity, availability free without live key.

---

## 14. Testing strategy

| Layer | What to test |
|-------|----------------|
| Utils / gates | `isActionable`, parse decision, fingerprint changes |
| ensure\* (mocked I/O) | unsupported → no quote; supported+dims → quote; key change → invalidate |
| Tools | Refuse commit when proceed false; idempotency |
| Prompt assembly | REQUIRED line present for each status |
| Golden dialogues (optional) | Few end-to-end transcripts per critical path |

Use **generic fixtures** (“Specialty Service X not in catalog”) — never encode one tenant’s product names as the only test.

---

## 15. Anti-patterns

1. Free-text treated as a locked entity ID.  
2. Token overlap as the only eligibility gate.  
3. Prompt-only sequencing (“please do steps in order”) with no `ensure*`.  
4. Stale caches without fingerprints.  
5. Unbounded tool loops / agent recursion.  
6. One mega-prompt for extract + route + reply + safety.  
7. Hardcoded tenant product names in code.  
8. Fail-open on money, inventory, or PII side effects.  
9. Exposing internal UUIDs to end users.  
10. Letting enrichment agents override a hard stop (e.g. unsupported).  
11. Asking for contact/PII before the commercial summary/proceed (when your UX requires that order).  
12. Dumping full price matrices / entire catalogs into chat instead of stage-appropriate questions.  
13. Claiming success when the commit tool failed or returned no receipt.  
14. Silent auto-execution of complex / recurring / multi-party requests that need a human.

---

## 16. Build checklist (copy into your PRD)

```text
[ ] Name the flow and success metric
[ ] Draw states: … → Done | Decline | Handoff
[ ] List typed fields + statuses + fingerprints
[ ] Define isActionable() and commit preconditions
[ ] Feature flag / mode → tool menu matrix
[ ] ensure* order written down
[ ] Fail-open vs fail-closed per ensure*
[ ] Prompt ID family + OVERRIDE map
[ ] <flow_context> + REQUIRED THIS TURN generator
[ ] Tools: names, args, internal state checks, idempotency
[ ] Graph nodes + edges + when to skip supervisor
[ ] Async policy: await vs parallel vs poll
[ ] Timeouts, JSON retry budget, provider fallback
[ ] Retrieval: FAQ/policy scopes + catalog source
[ ] Post-hooks: guarantees (legal, receipt, ticket)
[ ] Handoff rules + private notes
[ ] Logging line + LLM operation names
[ ] Unit tests for gates + invalidation
[ ] Red-team: unsupported ask, pivot mid-flow, stale cache, tool spam
```

---

## 17. Skeleton you can paste into a new repo

```ts
// --- state ---
type SupportStatus = 'supported' | 'unsupported' | 'clarify' | 'pending';

interface SkillState {
  entityId?: string;
  supportStatus?: SupportStatus;
  supportCheckedFor?: string;
  quoteStatus?: 'ready' | 'clarifying' | 'missing';
  availabilityStatus?: 'free' | 'busy' | 'error' | 'pending';
  availabilityCheckedFor?: string | null;
  proceedConfirmed?: boolean;
  proceedFingerprint?: string;
  params: Record<string, unknown>;
}

function isActionable(s: SkillState): boolean {
  if (s.supportStatus === 'unsupported' || s.supportStatus === 'clarify' || s.supportStatus === 'pending') {
    return false;
  }
  return !!s.entityId;
}

// --- preflight ---
async function runPreflight(ctx: { state: SkillState }) {
  await ensureSupported(ctx);
  if (!isActionable(ctx.state)) return;
  await ensureQuoted(ctx);
  await ensureAvailable(ctx);
  syncProceed(ctx);
}

// --- required line ---
function requiredThisTurn(s: SkillState): string {
  if (s.supportStatus === 'unsupported') {
    return 'REQUIRED THIS TURN: decline — not offered. Do NOT continue the commercial path.';
  }
  if (s.supportStatus === 'clarify' || !s.entityId) {
    return 'REQUIRED THIS TURN: ask them to pick ONE option from the real catalog only.';
  }
  if (s.quoteStatus === 'clarifying') {
    return 'REQUIRED THIS TURN: ask only for the missing quote dimension(s).';
  }
  if (s.availabilityStatus === 'busy') {
    return 'REQUIRED THIS TURN: say unavailable; offer alternatives if present.';
  }
  if (s.availabilityStatus === 'free' && s.quoteStatus === 'ready' && !s.proceedConfirmed) {
    return 'REQUIRED THIS TURN: summary + ask to proceed. Do NOT call commit yet.';
  }
  if (s.proceedConfirmed && /* fields complete */) {
    return 'REQUIRED THIS TURN: call the commit tool now.';
  }
  return '';
}

// --- skill turn ---
async function skillTurn(ctx) {
  await runPreflight(ctx);
  const tools = buildToolsForState(ctx.state); // menu from state/mode
  const system = buildSystemPrompt({
    ids: FLOW_PROMPT_IDS,
    flowContext: ctx.state,
    required: requiredThisTurn(ctx.state),
  });
  return runToolLoop({ system, history: ctx.history, tools, maxIterations: 10 });
}
```

---

## 18. Domain remaps (same skeleton)

| Booking | Support ticket | Ops change | Sales |
|---------|----------------|------------|-------|
| service / SKU | issue category | change type | product / plan |
| supportStatus | in-policy? | allowed change? | sellable? |
| duration / options | severity fields | blast radius | seats / term |
| quote | — | risk score | price |
| calendar slot | SLA window | maintenance window | start date |
| proceed | confirm close plan | CAB / approval | verbal yes |
| schedule + pay | create ticket | execute change | create order |
| recurring → handoff | VIP → handoff | high risk → handoff | custom → handoff |

---

## 19. One-page cheat sheet

```text
FLAG → MODE → TOOL MENU
STATE MACHINE (statuses + fingerprints) > PROMPT
ensure* (awaited, ordered) BEFORE chat LLM
PROMPT = static [ID=…] + <flow_context> + REQUIRED THIS TURN
TOOL LOOP capped; tools re-validate state
PARALLEL enrich OK; critical gates re-check keys
RETRY structured output / FALLBACK provider / TIMEOUT everything
POST-HOOKS for guarantees models skip
FAIL CLOSED on irreversible actions
LOG statuses every turn
TEST gates with generic fixtures
NO hardcoding tenant product names into eligibility
```

---

## 20. Definition of done

A new agent is “blueprint-compliant” when:

1. An unsupported / out-of-policy ask **cannot** reach quote/commit.  
2. Stale availability/quote **cannot** survive an input fingerprint change.  
3. Commit tools refuse to run without coded preconditions.  
4. Every critical policy has an ID **and** a state-driven REQUIRED line where timing matters.  
5. Irreversible failures fail closed and are observable.  
6. A new teammate can explain the state machine without reading the prompts.

---

*This is a master architecture reference. Adapt names and channel details to your stack; keep the control plane (state, ensure\*, IDs, tool menus, async policy) intact.*
