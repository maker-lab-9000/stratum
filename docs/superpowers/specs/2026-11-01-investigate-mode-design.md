# Investigate mode (agentic analysis) — design

**Date:** 2026-11-01 · **Status:** approved by the operator 2026-11-01 · **Scope:** experiment

## Intent

Today the model reads a frozen evidence bundle once: N samples, one cache-bust
probe, DNS, the route. When that is not enough (a CDN strips its hit tokens,
a debug header would settle it, a cookie may be forcing a bypass) the model can
only guess and lower its confidence. Several real runs ended this way
(theguardian.com: hidden Fastly state; kleinanzeigen.de: "Akamai's debug cache
headers were not requested").

Investigate mode lets the model ask for more evidence while it reads: up to
five extra requests to the **same URL** with headers of its choosing. The
collection stays deterministic code; the model only decides *what to ask for*.
The purpose is an **experiment**: measure whether the extra requests improve
the verdict against the eval corpus, at what cost in tokens, time and requests.

## Goals

1. A per-analysis option, off by default, that lets the model request the URL
   again with chosen headers (vendor debug headers, a cache-bust query, a
   different `User-Agent`, `Cache-Control: no-cache`, …), at most 5 times.
2. Every extra request is real evidence: recorded verbatim as a sample, shown
   in the report and the live run, citable by the model and checked by the
   validator like any other sample.
3. The report gains two model-written parts: an account of what it tried and
   what each probe showed, and **Recommendations**: what else could be done
   when its tools were not enough.
4. The eval can run each case with the mode off and on and print the two side
   by side, with serving and chain scores, tokens, wall time and the number of
   extra requests the model chose to make.
5. **A faithful log of what the model did.** Every tool call is recorded by
   the code, not the model: the exact request sent, when, what came back, what
   the model was told, and the model's own words around the call. The report
   shows it call by call.

## Non-goals

- Fetching any other URL (assets, other pages, the origin directly). The tool
  has no URL parameter.
- Tool support for OpenRouter. Anthropic only; other providers run the mode
  as if it were off and the report says so.
- A scripted investigation in the fake provider or the Docker e2e stack. The
  loop is unit-tested with a stub provider inside the test file.
- Re-running DNS, warm-up or the traceroute during investigation.
- A UI for the request budget. Five is a constant.
- Changing the stored report shape (no new DB columns).

## Anti-goals

- **Vendor knowledge in code.** The tool executes headers verbatim. Which
  header to send for which CDN is the prompt's knowledge (the vendor table
  already lists debug headers), never the code's.
- **The code interpreting a probe result.** The tool returns status, headers
  and timing; the model reads them.
- **Unbounded or wandering requests.** Same URL, 5 requests, sequential, same
  timeouts as the sampler, the outbound allowlist and private-range policy
  unchanged (the host is the one already approved for this analysis).
- **Losing evidence.** A tool failure (timeout, transport error) is returned to
  the model as a failed sample; a loop that breaks still ends in the existing
  degraded verdict with every collected sample persisted.
- **Silent mode changes.** If the provider cannot run tools, the report says
  the mode was requested but unavailable.

## Constraints

- Architecture rules §2 hold: deterministic collection, LLM interprets, the
  validator checks citation existence only, no layers from hops.
- No live network or live LLM in default tests. Live behaviour is checked by
  the eval and marked `@pytest.mark.live`.
- Secrets from env only; the model never sees the API key; tool inputs are
  logged without values that look like credentials (see *Headers*).
- The eval's existing non-goal "never touches the target sites" is **set aside
  for this experiment**, by operator decision: the "on" run must make live
  requests to each case's URL. The table marks those rows live.

## The option

`AnalysisOptions.investigate: bool = False` (API, bundle `meta.request_options`,
Launch checkbox under More options: *"Let the model investigate: up to 5 extra
requests to this URL with headers it chooses"*). Re-run from a report submits
empty options today (options are not persisted per report, decision 1.1.0), so a
re-run does **not** keep the option; the operator ticks it again from Launch.
No new columns.

## The tool

One tool, `request_page`, offered to the model only when the option is on and
the provider supports tools.

Input (JSON schema given to the model):

| Field | Type | Meaning |
|---|---|---|
| `headers` | object of string → string | request headers to add or override, applied over the analysis' `extra_request_headers` |
| `cache_bust` | boolean, default false | append the random `stratum-cb` query parameter, as the existing probe does |
| `reason` | string, required | one sentence: what this request should settle (recorded, shown in the report) |

Execution (deterministic, in `app/pipeline/investigate.py`):

- Same URL as the analysis; redirects not followed; no caching; same timeout
  as the sampler. Uses the sampler's `_one_request` (made public as
  `one_request`) so the sample shape is identical: `status`, `http_version`,
  `headers` (verbatim wire order), `timing`, `peer_ip`, `ok`, `error`.
- The sample is tagged `"probe": "investigation"` and carries
  `"investigation": {"n": k, "headers": {...}, "cache_bust": bool, "reason": "..."}`.
  `request` numbering continues after the existing samples (N requests, then
  the cache-bust probe, then investigation 1..5), so citations stay the plain
  `request <k>` form.
- **Evidence standing.** An investigation response is full evidence: its
  headers may be cited for layers, sample states, the provider and findings.
  The one exception is an investigation request with `cache_bust: true`: it is
  a forced miss like the original probe, so the probe rule applies to it (cite
  it only in `timing_check` and for the origin layer). The validator's
  evidence index, which today skips every sample with a truthy `probe`, is
  changed to skip only `probe == "cache_bust"` and investigation samples with
  `investigation.cache_bust == true`; `is_probe()` (sampler, bundle,
  frontend `isProbe`/`splitSamples`) is narrowed to `probe == "cache_bust"` so
  "the probe" keeps meaning the original one and investigation samples never
  enter the request columns, the progression or the seam by accident.
- **Timing facts.** After the loop, the bundle's `timing` section is recomputed
  over the extended sample list (the per-sample `server_ms` computation in
  `timing_section` is extracted into a helper the tool result reuses), so
  `timing.facts` carries each investigation request's facts and the model may
  cite them in `timing_check.evidence` under the existing exact-match check.
- Requests run one at a time, in the order the model asks.
- **Budget:** the sixth call is not executed; the tool returns
  `{"error": "budget exhausted: 5 investigation requests were made; conclude with the evidence you have"}`.
- **Headers:** names must be RFC 7230 tokens; values must not contain CR or LF;
  `Host`, `Content-Length`, `Transfer-Encoding` and `Connection` are refused
  with an error the model sees. Anything else, including `Cookie` and
  `Authorization`, is allowed: the operator can already send those through
  custom headers, and a model-chosen cookie is part of the experiment. Header
  values are stored verbatim in the sample (they are the evidence); the
  pipeline's log line for a tool call prints header **names** only.
- The tool result returned to the model is the sample as JSON, plus the same
  timing facts the bundle computes for a single sample (`ttfb_ms`,
  `server_ms` against the known edge RTT) so it can compare like with like.
- **The call log** (`llm_json.investigation_log`, written by the pipeline, one
  entry per tool call in order, including refused and failed ones):

  | Field | Content |
  |---|---|
  | `n` | call number, 1-based (refused calls count too) |
  | `request` | the sample's request number, or `null` when refused |
  | `asked_at_ms` / `answered_at_ms` | wall clock, epoch ms |
  | `model_said` | the assistant text in the same turn as the tool call, verbatim (empty when the model called the tool without text) |
  | `input` | the tool input exactly as the model sent it (`headers`, `cache_bust`, `reason`) |
  | `sent` | what actually went on the wire: final URL (with the cache-bust parameter if any), method, merged header set in order |
  | `response` | status, http version, `peer_ip`, timing, header count; or `error` for a transport failure |
  | `returned` | the tool result JSON as handed back to the model, verbatim |
  | `refused` | `null`, or the reason (`budget`, `header_policy: <detail>`) |

  The log is the deterministic record; the model's `investigation.steps` is
  its narration. They are shown together but never merged. Header values in
  `sent` are stored verbatim (they are the experiment's evidence); the
  pipeline log line still prints names only.
- Each call emits a live-run event `{"stage": "investigate", "status": "progress", "data": {"n": k, "reason": ..., "header_names": [...], "status_code": ...}}`
  so the live view fills in as the model works.

## The provider loop (Anthropic)

`LLMProvider` gains an optional capability:

```python
class ToolCall(TypedDict): name: str; input: dict; result: dict
class ToolRun(TypedDict): text: str; tool_calls: list[ToolCall]; usage: dict

def supports_tools(self) -> bool: return False

async def analyze_with_tools(self, *, system, user, model, tools: list[dict],
                             call_tool: Callable[[str, dict], Awaitable[dict]],
                             settings, max_rounds: int = 8) -> ToolRun:
    raise NotImplementedError
```

The signature takes a `messages` list (not a single `user` string) and
returns it extended with every assistant and tool-result turn, so the caller
can continue the same conversation:

```python
async def analyze_with_tools(self, *, system, messages: list[dict], model, tools,
                             call_tool, settings, max_rounds: int = 8) -> ToolRun
# ToolRun: text, tool_calls, usage, messages (the full transcript so far)
```

`AnthropicProvider.supports_tools()` is true. `analyze_with_tools` runs the
Messages API tool-use loop: send `tools`, on `stop_reason == "tool_use"` run
every `tool_use` block through `call_tool`, append the assistant turn and a
user turn of `tool_result` blocks, repeat. It stops on `end_turn` (returns the
joined text) or after `max_rounds` assistant turns, in which case it sends one
final user message, *"No more tool calls are available. Return the JSON object
now."*, and returns whatever text comes back. `usage` sums input and output
tokens across rounds. Transient errors use the existing `request_json` →
`ProviderError` path. **Retries and the budget:** the budget counter and the
collected samples live in the tool closure for the whole analysis, not in the
loop call. A 429/5xx mid-loop is retried by the existing backoff by calling
`analyze_with_tools` again with the transcript returned so far, so the model
keeps its earlier tool results, no live request is repeated, request numbers
stay unique and the leftover budget carries over. The backoff helper gains the
transcript as its retry state; its attempt and total-wait limits are unchanged.

`OpenRouterProvider` keeps the default (`supports_tools()` false).

## The analysis call

`run_analysis(bundle, …, tools=None)`:

- `tools is None` or provider lacks tools → today's path, unchanged.
- Otherwise: system prompt = `SYSTEM_PROMPT` + the investigation section (below);
  call `analyze_with_tools`; parse strictly as today. **Invalid JSON retry:**
  the correction is appended as one more user turn to the returned transcript
  and `analyze_with_tools` is called again with it (the tool results stay in
  context and the budget carries over), once; a second failure raises
  `AnalysisParseError` as today.
- Returns `StructuredResult` plus the tool calls and usage (a small
  `AnalysisOutcome` dataclass), so the pipeline can persist the samples and the
  eval can count requests and tokens.

`make_llm_analyze` builds the tool for this analysis (URL, base headers, edge
RTT, emit) when `options.investigate` is true; the orchestrator passes `emit`
and the URL into the analyze dependency for this. The investigation samples
are **appended to the bundle's `samples`** and the timing section recomputed
before validation, so `validate_verdict` checks citations against them (with
the evidence-index change above), and the orchestrator writes `samples_json`
again after the LLM step so they are persisted with the rest. If the
provider lacks tools, `llm_json.investigation` is
`{"requested": true, "available": false, "reason": "provider has no tool support"}`.

## Prompt additions (only when the tool is offered)

A section **"Investigating"** appended to the system prompt:

- You may call `request_page` up to 5 times when the evidence does not settle
  the serving layer, a layer's state, or a finding. Say what each request should
  settle in `reason`. Prefer the vendor's debug header from the table when the
  hit/miss state is hidden; a cache-bust request when you need a known miss; a
  changed `User-Agent` or `Accept-Language` when `Vary` suggests a split key.
  Do not repeat a request that already answered the question.
- Investigation responses are samples like any other: cite their headers as
  `request <k>` headers. The cache-bust-only citation rule applies only to the
  original probe.
- The output gains two keys (schema below). `investigation.steps` names each
  request you made and what it showed, in order; `recommendations` lists what
  else would settle the open questions and why, when your requests were not
  enough (a run from another region, a vendor debug header that needs a secret,
  comparing with the origin directly, a HEAD vs GET check). Empty lists are
  fine when nothing is open.

The vendor table in the prompt already carries debug headers (Fastly, Akamai);
the 1.3.2 "suggest a debug re-run" finding rule gains the clause *"unless you
could and did send it yourself in investigate mode"*.

## Schema

```python
class InvestigationStep(BaseModel):
    request: int            # the sample's request number
    purpose: str            # what it was meant to settle
    observed: str           # what the response showed, one or two sentences

class Investigation(BaseModel):
    summary: str
    steps: list[InvestigationStep] = []

class Recommendation(BaseModel):
    action: str             # what to do
    reason: str             # what it would settle
    confidence: Confidence | None = None

class StructuredResult(BaseModel):
    ...
    investigation: Investigation | None = None       # 1.4.0
    recommendations: list[Recommendation] = []       # 1.4.0
```

Both optional, so existing reports and mode-off runs parse unchanged. The
validator checks that every `steps[].request` exists among the samples (an
existence check, consistent with §2 rule 3); a missing one is flagged under
`investigation.steps[i]`, never dropped.

## Report and live run

- **Live run:** a step *"Investigate"* between *Read the evidence*'s start and
  its end, present only when the option is on. Each `investigate` event adds a
  line: *"3 of 5: Fastly-Debug: 1 · 200"* (header names, status). Raw headers
  one click away, as for the samples.
- **Report**, after *What the requests showed*: **"What the model tried"**, one
  row per call-log entry, in order: the call number and time offset from the
  first, the headers the model asked for (names and values, mono), its
  `reason`, the status (or *"no response: <error>"*, or *"refused: budget"*),
  and the model's `observed` text for that request from `investigation.steps`
  when it wrote one. Each row expands (a disclosure) to the full record: what
  the model said in that turn, the exact request sent, the response headers,
  and the tool result it was given. The raw drawer gains a tab
  per investigation request (the 8-tab limit already falls back to a select).
- **Recommendations**, after *What to look at*: one list, each with the action
  as the title, the reason beneath, the confidence meter at the right. Present
  only when non-empty. When the mode was requested but unavailable, one note
  line: *"Investigate mode was requested, but <provider> has no tool support."*
- The progression table keeps investigation samples **out** of its request
  columns (they have their own section), as the cache-bust probe is kept out
  of the request count today.
- History and Recent: unchanged.

## Eval

`python -m evals run --model anthropic:<m> [--investigate]`:

- Without the flag: today's behaviour.
- With it: every case runs twice per model, `off` (frozen, as today) and `on`
  (frozen bundle, live `request_page` calls to the case's URL). Cases do not
  record the run's custom request headers (decision 1.1.0), so live calls carry
  only the model's headers. A case captured behind a cookie or User-Agent the
  live run lacks may compare against a different page; the results file records
  this, and such cases should be left out of the experiment or recaptured
  without custom headers. Rows are labelled `<model>` and
  `<model> +investigate`, the latter marked *live*. The table gains two
  columns, **extra requests** and **tokens** (input + output), and the score
  footer shows both rows so the delta is readable. `records` carry
  `tool_calls`, `usage` and the appended samples.
- The Makefile target accepts `INVESTIGATE=1`.
- Cases are **not** modified by an eval run; the live samples live only in the
  run's results file.

## Tests (default run, no network, no live LLM)

- Stub provider in the test file that scripts two tool calls then a final JSON;
  asserts: samples appended with `probe: "investigation"` and sequential
  `request` numbers, `investigation.steps` validated, events emitted, tokens
  summed, and `investigation_log` has one entry per call with `model_said`,
  `input`, `sent`, `response` and `returned` filled from the stub's data.
- A refused call (budget or header policy) appears in the log with `refused`
  set and `request: null`, and no request is made.
- Budget: a stub asking six times gets the budget error on the sixth and the
  loop still ends with a verdict; exactly five samples recorded.
- Header policy: `Host` refused; a CRLF value refused; names case preserved.
- Max rounds: a stub that never stops gets the "return the JSON now" turn and
  the loop ends.
- Invalid JSON after tools: the correction is sent in-conversation and succeeds
  on the retry; two failures → `AnalysisParseError`, degraded verdict, samples
  persisted.
- Provider without tools: mode requested → plain analysis, `investigation`
  carries `available: false`.
- Anthropic request/response shape: respx-mocked Messages API with a
  `tool_use` turn and an `end_turn`; asserts the `tool_result` message shape.
- Frontend: checkbox posts `investigate: true`; *What the model tried* rows and
  *Recommendations* render from a fixture; the progression columns exclude
  investigation samples; live step line from an `investigate` event.
- Live (`@pytest.mark.live`): one Anthropic call with the tool against a local
  HTTP server, asserting at least one tool round-trip.

## Left to the builder

- Exact copy of the prompt section and the Launch hint.
- Where the model's `observed` text sits when the sample failed.
- Labelling investigation tabs in the raw drawer (today every `probe` sample is
  labelled "Cache-bust probe").
- One `httpx.AsyncClient` per investigation session for the sampler's request
  function.
- The timing fields returned in the tool result (reuse the bundle's per-sample
  timing helper rather than re-deriving).
- Event payload field names, within the shape above.

## Decisions made in this design (the operator's)

- Same URL only, headers of the model's choosing. (operator)
- Budget: 5 requests. (operator)
- Anthropic only for now. (operator)
- Test-only stub, no scripted fake, e2e stack stays non-agentic. (operator)
- A Recommendations section for what else could be done. (operator)

## Decisions made in this design (mine, say if wrong)

- Option name `investigate`; checkbox wording as above.
- Re-run does not keep the option (options are not persisted; adding a column
  was ruled out by the no-new-columns non-goal).
- Investigation responses are full evidence, except a `cache_bust: true` one,
  which follows the original probe's citation rule; `is_probe` narrows to the
  original cache-bust probe.
- The bundle's timing facts are recomputed after the loop so investigation
  timing is citable.
- Provider loop takes and returns the message transcript; budget and samples
  live per analysis, so transient retries and the JSON correction continue the
  same conversation without re-requesting.
- Eval `on` rows send only the model's headers (cases store no run headers).
- `Cookie` / `Authorization` allowed in model-chosen headers; `Host` and
  framing headers refused.
- Investigation samples are appended to `samples_json` and the bundle, not
  stored separately, so the validator and raw drawer need no new paths.
- Request numbering continues after the cache-bust probe.
- Max 8 assistant turns before the "return the JSON now" nudge.
- The eval's "never touches the target" rule is suspended only for `on` rows.
- The call log is written by the pipeline into `llm_json.investigation_log`
  (no new column), one entry per call including refused ones. (operator asked
  for a record of exactly what the agent does at each call)
- Version 1.4.0.
