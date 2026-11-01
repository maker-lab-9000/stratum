# Investigate Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the model request the analysed URL again, up to five times with headers of its choosing, while it reads the evidence; record every call faithfully; show what it tried and what it recommends; measure the effect in the eval.

**Architecture:** A `request_page` tool (deterministic, reusing the sampler) is offered to Anthropic models through a tool-use loop added behind the existing `LLMProvider` abstraction. Budget, header policy, the call log and the collected samples live in one per-analysis `Investigation` object; its samples are appended to the bundle before validation and persisted with the rest. The schema gains two optional fields; the report two sections; the eval an `--investigate` flag that runs each case frozen and live.

**Tech Stack:** Python 3.12, FastAPI, httpx + respx, pydantic, pytest; React 19 + TypeScript, Vitest + Testing Library, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-01-investigate-mode-design.md`

## Global Constraints

- Architecture rules (CLAUDE.md §2): no vendor names, header signatures or CNAME fingerprints in code; code never interprets a probe result; the validator checks existence only; no cache layers from hops; LLM failure never loses evidence.
- No live network or live LLM in the default test run; live tests carry `@pytest.mark.live`.
- Budget: exactly `5` investigation requests per analysis. Max assistant turns before the nudge: `8`.
- Same URL only; the tool has no URL parameter. Refused header names: `host`, `content-length`, `transfer-encoding`, `connection` (case-insensitive). Values with `\r` or `\n` refused.
- Sample tag: `"probe": "investigation"`; `is_probe()` and `isProbe()` narrow to `probe == "cache_bust"`.
- Log lines print header names only, never values. Secrets stay in env.
- Version `1.4.0` (`backend/pyproject.toml`, `uv.lock`).
- Status palette unchanged: green = HIT only; amber = anomaly; UNKNOWN dashed grey. Shared `Badge`/`Table`/`ConfidenceMeter` primitives for shared patterns.
- `progress.md` updated at the end (status board note, session log, decisions log); one commit per task.

## Review Focus

1. A tool call whose `headers` value is not an object of strings (a list, a number, nested JSON): the tool must refuse with a clear error the model sees, never raise out of the loop. Test in Task 2.
2. The model's final text arrives alongside a trailing `tool_use` block in the same turn (Anthropic may emit text and a tool call together): the loop must execute the tool and continue, not treat the text as the answer. Test in Task 3.
3. The cache-bust probe is off (`cache_bust_probe: false`) and the model's first investigation request uses `cache_bust: true`: `splitSamples` and `timing_section` must not adopt it as "the" probe. Tests in Task 1 and Task 10.
4. A report from before 1.4.0 (no `investigation`, no `investigation_log`, no `recommendations`) renders unchanged with no empty sections. Test in Task 11.
5. The provider's `end_turn` arrives with text that is not JSON after tool calls were made: the correction retry continues the same transcript and the samples already collected are persisted even when the second attempt fails. Test in Task 5.

---

### Task 1: Narrow `is_probe` and the timing helper (backend)

**Files:**
- Modify: `backend/app/collectors/http_sampler.py:42-44` (`is_probe`)
- Modify: `backend/app/pipeline/bundle.py:129-193` (`timing_section`)
- Test: `backend/tests/test_bundle.py`, `backend/tests/test_sampler.py`

**Interfaces:**
- Produces: `is_probe(sample) -> bool` true only when `sample.get("probe") == "cache_bust"`; `is_investigation(sample) -> bool` true when `sample.get("probe") == "investigation"` (both in `http_sampler.py`, `PROBE_MARKER` unchanged, new `INVESTIGATION_MARKER = "investigation"`).
- Produces: `sample_timing_facts(sample: dict, edge_rtt_ms: float | None) -> dict` in `bundle.py`: `{"request": n, "ttfb_ms": float|None, "server_ms": float|None, "facts": [str]}` with the facts in the existing `request <n> ttfb_ms: <v>` / `request <n> server_ms: <v>` form; `timing_section` uses it for its rows and also appends one row and its facts per investigation sample (they are excluded from `requests`, from the warm spread and from `cache_bust`).

- [ ] **Step 1: Write the failing tests**

```python
# test_sampler.py
def test_is_probe_is_only_the_cache_bust_probe():
    assert is_probe({"probe": "cache_bust"})
    assert not is_probe({"probe": "investigation"})
    assert not is_probe({})
    assert is_investigation({"probe": "investigation"})

# test_bundle.py
def test_timing_section_keeps_investigation_out_of_requests_and_probe():
    samples = [_sample(1, ttfb=30, rtt=20), _sample(2, ttfb=28),
               {**_sample(3, ttfb=200), "probe": "investigation", "investigation": {"cache_bust": True}}]
    section = timing_section(samples)
    assert [r["request"] for r in section["requests"]] == [1, 2]
    assert section["cache_bust"] is None
    assert "request 3 ttfb_ms: 200" in section["facts"]
    assert "request 3 server_ms: 180.0" in section["facts"]

def test_sample_timing_facts_shape():
    assert sample_timing_facts(_sample(7, ttfb=41.2), 20) == {
        "request": 7, "ttfb_ms": 41.2, "server_ms": 21.2,
        "facts": ["request 7 ttfb_ms: 41.2", "request 7 server_ms: 21.2"]}
```
(`_sample` is the test file's existing sample factory; add `rtt` support if missing.)

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && uv run pytest tests/test_sampler.py tests/test_bundle.py -k "is_probe or investigation or timing_facts" -v`
Expected: FAIL (`is_investigation` undefined; `request 3` facts missing)

- [ ] **Step 3: Implement** `is_probe`, `is_investigation`, `INVESTIGATION_MARKER` in `http_sampler.py`; extract `sample_timing_facts` in `bundle.py` and rewrite `timing_section` to use it, adding investigation rows under a new `section["investigation"]` list (same row shape) and their facts to `facts`.

- [ ] **Step 4: Run the backend suite**

Run: `cd backend && uv run pytest -q`
Expected: all pass (the golden bundle fixture may need `"investigation": []` added to its timing section; update the fixture, not the test logic).

- [ ] **Step 5: Commit** `feat: narrow is_probe to the cache-bust probe; per-sample timing facts`

---

### Task 2: The investigation tool (backend)

**Files:**
- Create: `backend/app/pipeline/investigate.py`
- Modify: `backend/app/collectors/http_sampler.py:93` (rename `_one_request` → `one_request`, keep a `_one_request = one_request` alias)
- Test: `backend/tests/test_investigate.py`

**Interfaces:**
- Produces:
```python
BUDGET = 5
REFUSED_HEADERS = frozenset({"host", "content-length", "transfer-encoding", "connection"})
TOOL_NAME = "request_page"
TOOL_SCHEMA: dict  # the Anthropic tool definition: name, description, input_schema with headers (object, additionalProperties string), cache_bust (boolean), reason (string, required)

class Investigation:
    def __init__(self, *, url: str, base_headers: dict[str, str], edge_rtt_ms: float | None,
                 next_request: int, emit: Callable[[dict], object] | None = None,
                 request_fn=one_request, timeout_ms: int = 10_000, clock=time.time) -> None
    samples: list[dict]          # appended in order, tagged probe="investigation"
    log: list[dict]              # one entry per call, the spec's call-log fields
    async def call(self, tool_input: dict, *, model_said: str = "") -> dict
        # returns the tool result handed to the model; never raises for bad input
    def remaining(self) -> int
```
- `call()` result on success: `{"request": n, "sample": <sample>, "timing": sample_timing_facts(...)}`; on refusal: `{"error": "<reason>"}` with the budget text from the spec; on transport failure: `{"request": n, "sample": <ok=False sample>, "timing": {...}}`.
- Sample additions: `probe="investigation"`, `investigation={"n": k, "headers": <model headers>, "cache_bust": bool, "reason": str}`.
- Emits `{"stage": "investigate", "status": "progress", "data": {"n": k, "reason": ..., "header_names": [...], "status_code": int|None, "refused": str|None}}` per call.

- [ ] **Step 1: Write the failing tests** (a stub `request_fn` that records calls and returns a canned sample dict shaped like `one_request`'s return; no network)

```python
async def test_call_records_sample_log_and_event()  # headers merged over base, request numbers continue from next_request, log entry has model_said/input/sent/response/returned, event emitted
async def test_cache_bust_appends_stratum_cb_param()  # sent.url contains "stratum-cb="
async def test_sixth_call_is_refused_without_a_request()  # 5 samples, 6 log entries, log[5]["refused"] == "budget", result["error"].startswith("budget exhausted")
@pytest.mark.parametrize("name", ["Host", "content-length", "Transfer-Encoding", "Connection"])
async def test_refused_header_names(name)  # refused == "header_policy: ...", no request
async def test_crlf_value_refused()
async def test_non_object_headers_refused()  # headers=["a"], headers=3, headers={"a": 1}
async def test_transport_failure_is_a_failed_sample()  # request_fn returns ok=False → sample appended, result has sample, log response has error
async def test_header_names_preserve_case_in_sent()
```

- [ ] **Step 2: Run to verify they fail**: `uv run pytest tests/test_investigate.py -v` → ImportError.

- [ ] **Step 3: Implement `investigate.py`**. `call()` validates input (`headers` must be `dict[str, str]`, names RFC 7230 token `^[!#$%&'*+.^_`|~0-9A-Za-z-]+$`), refuses by policy or budget, opens one `httpx.AsyncClient(http2=True, follow_redirects=False, timeout=...)` lazily and keeps it for the session (`aclose()` method), calls `request_fn(client, url, index, merged_headers, start_ref)`, tags the sample, builds the log entry, emits, returns the result. Logging: `logger.info("investigate %d: %s", k, sorted(header_names))`.

- [ ] **Step 4: Run the tests**: all pass. Also `uv run pytest tests/test_sampler.py` (alias keeps old imports working).

- [ ] **Step 5: Commit** `feat: request_page investigation tool with budget, header policy and call log`

---

### Task 3: Anthropic tool-use loop (backend)

**Files:**
- Modify: `backend/app/llm/base.py` (add `ToolCall`, `ToolRun`, `supports_tools`, `analyze_with_tools`)
- Modify: `backend/app/llm/anthropic.py`
- Test: `backend/tests/test_llm_providers.py`

**Interfaces:**
- Produces in `base.py`:
```python
class ToolCall(TypedDict): id: str; name: str; input: dict; result: dict; model_said: str
class ToolRun(TypedDict): text: str; tool_calls: list[ToolCall]; usage: dict; messages: list[dict]; stop_reason: str
NUDGE = "No more tool calls are available. Return the JSON object now."
class LLMProvider:
    def supports_tools(self) -> bool: return False
    async def analyze_with_tools(self, *, system: str, messages: list[dict], model: str, tools: list[dict],
                                 call_tool: Callable[[str, dict, str], Awaitable[dict]],
                                 settings: LLMSettings = DEFAULT_SETTINGS, max_rounds: int = 8) -> ToolRun:
        raise NotImplementedError
```
  `call_tool(name, input, model_said)` is the tool dispatcher; `messages` is the Anthropic-shaped transcript and the returned `messages` includes every assistant and `tool_result` turn.
- `AnthropicProvider.supports_tools()` → `True`; `usage = {"input_tokens": int, "output_tokens": int}` summed across rounds.

- [ ] **Step 1: Write the failing tests** (respx on `ANTHROPIC_MSGS`, a side-effect function returning a `tool_use` response first, then `end_turn`)

```python
async def test_tool_loop_executes_tool_and_returns_final_text()
    # 2 POSTs; second request body's messages[-1] == {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "<json>"}]}
    # run["tool_calls"][0]["input"] == {...}; run["text"] == final text; usage summed; run["messages"] has 4 entries
async def test_text_and_tool_use_in_one_turn_continues_the_loop()  # Review Focus 2: content = [text, tool_use] → tool executed, model_said == that text
async def test_max_rounds_sends_the_nudge()  # always tool_use; after max_rounds=2 assistant turns the 3rd request body ends with the NUDGE user message; returns that response's text
async def test_openrouter_has_no_tool_support()  # supports_tools() False; analyze_with_tools raises NotImplementedError
```

- [ ] **Step 2: Run to verify they fail**: `uv run pytest tests/test_llm_providers.py -k tool -v`.

- [ ] **Step 3: Implement**. Body per round: `{"model", "max_tokens", "system", "tools", "messages"}`; parse `content` blocks; for `stop_reason == "tool_use"` run every `tool_use` block in order through `call_tool`, append the assistant content verbatim and one user message of `tool_result` blocks (`content` = `json.dumps(result)`); stop on `end_turn` (text = joined text blocks of that turn). Errors go through `request_json` as today.

- [ ] **Step 4: Run**: `uv run pytest tests/test_llm_providers.py -v` → pass.

- [ ] **Step 5: Commit** `feat: Anthropic tool-use loop behind LLMProvider.analyze_with_tools`

---

### Task 4: Schema and prompt additions (backend)

**Files:**
- Modify: `backend/app/llm/schema.py` (after `Finding`)
- Modify: `backend/app/llm/prompt.py` (`OUTPUT_SCHEMA`, new `INVESTIGATE_PROMPT`, the 1.3.2 finding rule at line ~201)
- Test: `backend/tests/test_analysis.py`

**Interfaces:**
- Produces:
```python
class InvestigationStep(BaseModel): request: int; purpose: str; observed: str
class Investigation(BaseModel): summary: str; steps: list[InvestigationStep] = []
class Recommendation(BaseModel): action: str; reason: str; confidence: Confidence | None = None  # same coercion as Finding
class StructuredResult: ... investigation: Investigation | None = None; recommendations: list[Recommendation] = []
INVESTIGATE_PROMPT: str  # the "## Investigating" section from the spec, with TOOL_NAME and BUDGET interpolated
```
- `OUTPUT_SCHEMA` gains `"investigation": { "summary": "string", "steps": [ { "request": 1, "purpose": "string", "observed": "string" } ] }` and `"recommendations": [ { "action": "string", "reason": "string", "confidence": "high|medium|low" } ]`, both documented in the schema block as "omit or null when not investigating".
- The 1.3.2 rule gains: *"unless you could and did send it yourself in investigate mode."*

- [ ] **Step 1: Write the failing tests**

```python
def test_result_without_investigation_fields_still_parses()  # VALID_RESULT unchanged → investigation None, recommendations []
def test_investigation_and_recommendations_parse_and_coerce()  # confidence "High" → "high"; steps request int
def test_investigate_prompt_markers()  # for m in ("request_page", "up to 5", "Investigating", "investigation.steps", "recommendations"): assert m in INVESTIGATE_PROMPT; "did send it yourself" in SYSTEM_PROMPT
def test_output_schema_lists_investigation_keys()  # '"investigation"' and '"recommendations"' in OUTPUT_SCHEMA
```

- [ ] **Step 2: Run to verify they fail.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run `tests/test_analysis.py`** → pass; also run the full backend suite (the vendor-token guard in `tests/vendor_tokens.py` scans only `validator.py` and `evals/*.py`; the prompt may name vendors).

- [ ] **Step 5: Commit** `feat: investigation and recommendations in the result schema and prompt`

---

### Task 5: `run_analysis` with tools and the transcript-carrying retry (backend)

**Files:**
- Modify: `backend/app/llm/analysis.py`
- Test: `backend/tests/test_analysis.py`

**Interfaces:**
- Consumes: Task 3's `analyze_with_tools`, `ToolRun`, `NUDGE`; Task 4's `INVESTIGATE_PROMPT`.
- Produces:
```python
@dataclass
class AnalysisOutcome:
    result: StructuredResult
    tool_calls: list[ToolCall]      # [] when no tools
    usage: dict                     # {} when the provider reports none
async def run_analysis(bundle, *, provider, model, settings=..., max_retries=1, max_call_attempts=..., max_backoff_total_s=..., sleep=...,
                       tools: list[dict] | None = None, call_tool=None) -> StructuredResult   # unchanged return for callers
async def run_analysis_outcome(bundle, *, ..., tools=None, call_tool=None) -> AnalysisOutcome   # the new entry point; run_analysis wraps it
```
- With `tools` and a provider whose `supports_tools()` is true: system = `SYSTEM_PROMPT + "\n\n" + INVESTIGATE_PROMPT`; `messages = [{"role": "user", "content": base_user}]`; the invalid-JSON correction appends `{"role": "user", "content": _RETRY_CORRECTION}` to the **returned transcript** and calls again; a transient `ProviderError` retries with the transcript accumulated so far (the backoff helper takes a `state` dict `{"messages": [...]}` that the loop call updates in place before raising). With tools but no support: plain path, `AnalysisOutcome.tool_calls == []`.

- [ ] **Step 1: Write the failing tests** (a `StubToolProvider(LLMProvider)` in the test file: `supports_tools() → True`; `analyze_with_tools` scripted: a list of turns, each either `("tool", name, input, model_said)` or `("text", str)`; records every `messages` it receives; a `raise_once` hook for a retryable `ProviderError`)

```python
async def test_tools_path_runs_scripted_calls_and_parses()  # 2 tool turns then valid JSON → outcome.tool_calls 2, result parsed, call_tool invoked with (name, input, model_said)
async def test_invalid_json_after_tools_retries_in_same_transcript()  # first text invalid → second call's messages include the tool results and end with the correction; succeeds
async def test_two_invalid_after_tools_raise_parse_error()  # Review Focus 5: AnalysisParseError, and call_tool was invoked (samples collected before failure)
async def test_transient_error_mid_loop_continues_transcript()  # ProviderError(retryable) after 1 tool turn → next call receives the transcript with that tool result; tool not re-invoked
async def test_provider_without_tools_falls_back_to_plain()  # FakeProvider from existing tests + tools → analyze() used, tool_calls []
```

- [ ] **Step 2: Run to verify they fail.** - [ ] **Step 3: Implement** per the interface. - [ ] **Step 4: Run `tests/test_analysis.py tests/test_backoff.py`** → pass.

- [ ] **Step 5: Commit** `feat: run_analysis tool path with transcript-carrying retries`

---

### Task 6: Pipeline wiring, option, persistence (backend)

**Files:**
- Modify: `backend/app/api/schemas.py:10-18` (`investigate: bool = False`)
- Modify: `backend/app/pipeline/analyze.py`
- Modify: `backend/app/pipeline/orchestrator.py:147-158, 206-218`
- Modify: `backend/app/pipeline/validator.py:100-101` (evidence index), plus a steps existence check
- Modify: `backend/pyproject.toml` version `1.4.0`
- Test: `backend/tests/test_degraded.py` (or `test_pipeline.py`), `backend/tests/test_validator.py`, `backend/tests/test_api.py`

**Interfaces:**
- Consumes: Task 2 `Investigation`, `TOOL_SCHEMA`, `TOOL_NAME`; Task 5 `run_analysis_outcome`; Task 1 `timing_section`, `is_investigation`.
- Produces: `make_llm_analyze(...)` returns `analyze(bundle, provider, model, *, emit=None) -> dict`. When `bundle["meta"]["request_options"].get("investigate")` is true: builds `Investigation(url=bundle["meta"]["url"], base_headers=options.get("extra_request_headers") or {}, edge_rtt_ms=bundle["timing"]["edge_rtt_ms"], next_request=max(sample["request"])+1, emit=emit)`, passes `tools=[TOOL_SCHEMA]`, `call_tool=lambda name, inp, said: inv.call(inp, model_said=said)`; afterwards `bundle = {**bundle, "samples": bundle["samples"] + inv.samples, "timing": timing_section(all_samples)}`, validates, and returns `{"verdict_json", "llm_json", "samples": all_samples}` where `llm_json` additionally carries `"investigation_log": inv.log` and `"usage": outcome.usage`. When the provider lacks tools: `llm_json["investigation"] = {"requested": True, "available": False, "reason": "provider has no tool support"}`; the pydantic `investigation` field stays None (the dict is set after `model_dump()`).
- Orchestrator: `_analyze(bundle, analyze, provider, model, emit)` passes `emit=emit`; the final `repo.update` also writes `samples_json=verdict["samples"]` when present; emits `{"stage": "investigate", "status": "completed", "data": {"count": n}}` before the analyze `completed` event when the option was on.
- Validator: `_EvidenceIndex(bundle, include_probe=False)` skips a sample only when `is_probe(sample)` or (`is_investigation(sample)` and `sample["investigation"].get("cache_bust")`); `validate_verdict` flags `investigation.steps[i].request` not among `{s["request"]}` with reason `"cited request does not exist"` (flag only, no downgrade).

- [ ] **Step 1: Write the failing tests**

```python
# test_validator.py
def test_investigation_sample_headers_are_evidence_unless_cache_bust()  # a layer citing an investigation header passes; one citing a cache_bust investigation header is flagged _PROBE_ONLY
def test_investigation_step_request_must_exist()  # steps request 99 → flag path "investigation.steps[0].request"
# test_degraded.py / test_pipeline.py (fake repo + StubToolProvider resolver, request_fn stub injected via a factory kwarg on make_llm_analyze: `investigation_factory`)
async def test_investigate_option_appends_samples_log_and_persists()  # samples_json grows by the scripted calls; llm_json["investigation_log"] length; request numbers continue; "investigate" events emitted
async def test_investigate_with_provider_without_tools_marks_unavailable()
async def test_investigate_parse_failure_still_persists_samples()  # degraded verdict, samples_json includes investigation samples
# test_api.py
def test_create_accepts_investigate_option()  # POST with options.investigate true → manager.submit called with options containing investigate True; default False
```

- [ ] **Step 2: Run to verify they fail.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run the full backend suite** → pass. Run `uv run python -c "import app.main"` with `ANTHROPIC_API_KEY=x` to confirm wiring imports.

- [ ] **Step 5: Commit** `feat: investigate option wired through the pipeline; samples and call log persisted (v1.4.0)`

---

### Task 7: Eval `--investigate` (backend)

**Files:**
- Modify: `backend/evals/runner.py`, `backend/evals/__main__.py`, `backend/evals/table.py`, `backend/evals/README.md`, `Makefile:59-60`
- Test: `backend/tests/test_evals.py`

**Interfaces:**
- Consumes: Task 6's `analyze` returning `samples` and `llm_json["investigation_log"]`, `llm_json["usage"]`.
- Produces: `run_eval(cases, models, *, analyze, is_configured, progress, investigate: bool = False)`. With `investigate`, for each model two labels: `m.label` and `f"{m.label} +investigate"`; the `on` call passes a bundle whose `meta.request_options = {"investigate": True, "extra_request_headers": {}}` (and the same `analyze`). Records gain `"investigate": bool, "extra_requests": int, "tokens": {"input": int, "output": int} | None, "tool_calls": list, "samples": list`. `render_table(cases, model_labels, outcomes, extras: Mapping[tuple[str,str], str] | None = None)` prints an extra note column text like `live · 3 req · 12.4k tok` for `on` rows. CLI: `run --investigate`; Makefile: `make eval MODELS=... INVESTIGATE=1` → `$(if $(INVESTIGATE),--investigate)`. README gets a short "Investigate mode" subsection stating that `on` rows make live requests to the case URL and that cases captured behind custom headers should be excluded.

- [ ] **Step 1: Write the failing tests** (fake `analyze` that inspects `bundle["meta"]["request_options"]` and returns a verdict plus `llm_json` with a log of 3 entries and usage)

```python
async def test_investigate_runs_each_case_twice_with_labels()  # outcomes keys include (case, "m") and (case, "m +investigate"); on-row record extra_requests == 3, tokens summed
def test_table_shows_live_note_for_investigate_rows()
def test_cli_investigate_flag_parses()
```

- [ ] **Step 2: Run to verify they fail.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run `tests/test_evals.py`** → pass; `uv run python -m evals run --help` shows the flag.

- [ ] **Step 5: Commit** `feat: eval --investigate runs cases frozen and live, side by side`

---

### Task 8: Live Anthropic test (backend, `@pytest.mark.live`)

**Files:**
- Test: `backend/tests/test_investigate_live.py`

- [ ] **Step 1: Write the test**: skipped unless `ANTHROPIC_API_KEY` set; starts `tests/http_test_server.py`'s local server returning a header that changes when a request header `X-Stratum-Debug: 1` is present; builds a bundle with 2 samples via the real sampler; runs `make_llm_analyze()` with `investigate` on and model `claude-haiku-4-5`; asserts `len(llm_json["investigation_log"]) >= 1`.
- [ ] **Step 2: Run with `-m live`** when the key is available; otherwise confirm it is deselected by the default run.
- [ ] **Step 3: Commit** `test: live investigate round-trip against a local server`

---

### Task 9: API types, Launch checkbox, live-run step (frontend)

**Files:**
- Modify: `frontend/src/api/client.ts` (`AnalysisOptions.investigate?: boolean`)
- Modify: `frontend/src/views/Launch.tsx` (checkbox under More options, label *"Let the model investigate: up to 5 extra requests to this URL with headers it chooses"*, posts `investigate`)
- Modify: `frontend/src/views/LiveRun.tsx` (`InvestigateEvent` handling; a step `Investigate` after *Read the evidence* only when the first `investigate` event arrives; its `out` is the latest line `"<n> of 5: <header names joined by ", "> · <status>"` or `"refused: <reason>"`; `done` on `status: "completed"`)
- Test: `frontend/src/views/Launch.test.tsx`, `frontend/src/views/LiveRun.test.tsx`

- [ ] **Step 1: Write the failing tests**

```ts
test("investigate checkbox is off by default and posts investigate: true when ticked")
test("investigate events add a step that reads the latest call and completes")
```

- [ ] **Step 2: Run** `npx vitest run src/views/Launch.test.tsx src/views/LiveRun.test.tsx` → fail. - [ ] **Step 3: Implement.** - [ ] **Step 4: Run** → pass; `npx tsc -b`.

- [ ] **Step 5: Commit** `feat(ui): investigate option and live-run step`

---

### Task 10: Types, `isProbe`, raw drawer labels (frontend)

**Files:**
- Modify: `frontend/src/views/report/types.ts` (`RawSample.investigation?: {n: number; headers: Record<string,string>; cache_bust: boolean; reason: string}`; `InvestigationLogEntry`, `Investigation`, `Recommendation` types matching the backend)
- Modify: `frontend/src/views/report/timing.ts:7-16` (`isProbe = s.probe === "cache_bust"`; `isInvestigation = s.probe === "investigation"`; `splitSamples` returns `{ requests, probe, investigations }` with `requests` excluding both)
- Modify: `frontend/src/views/report/RawDrawer.tsx` (tab label `Investigation <n>` for investigation samples)
- Test: `frontend/src/views/report/timing.test.ts`, `frontend/src/views/report/lower.test.tsx`

- [ ] **Step 1: Write the failing tests**

```ts
test("isProbe is only the cache-bust probe; investigation samples are split out")  // Review Focus 3: with no cache-bust probe and an investigation sample with cache_bust true, probe is null
test("raw drawer labels investigation tabs")
test("progression columns exclude investigation samples")
```

- [ ] **Step 2: Run → fail.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run `npx vitest run`** → pass (fix any caller of `splitSamples` destructuring).

- [ ] **Step 5: Commit** `feat(ui): investigation samples typed and kept out of the request columns`

---

### Task 11: "What the model tried" and "Recommendations" sections (frontend)

**Files:**
- Create: `frontend/src/views/report/Tried.tsx`, `frontend/src/views/report/Recommendations.tsx`
- Modify: `frontend/src/views/report/ReportView.tsx` (Tried after the measured section; Recommendations after findings; the unavailable note)
- Modify: `frontend/src/index.css` (`.tried` rows: grid `56px minmax(0,1fr) 110px`, mono header list, `details` per row; `.recs` reuse `.findings` row grid with `ConfidenceMeter`)
- Modify: `frontend/src/fixtures/akamaiReport.ts` (export `investigatedReport`: akamaiReport plus 2 investigation samples, `llm_json.investigation`, `investigation_log` (3 entries, the third refused by budget for the test), `recommendations` 2 entries)
- Test: `frontend/src/views/report/report.test.tsx`

**Interfaces:**
- `Tried({ log, steps, samples })` renders one row per log entry in order: `n` and offset `+<s>s` from the first `asked_at_ms`; the requested headers as `code` lines `Name: value`; the `reason`; status (`refused: budget` / `no response: <error>` / `<status>`); the matching `steps[].observed` by request number; a `<details>` with `model_said`, `sent` (url, headers in order), response headers, `returned` as `pre.raw`.
- `Recommendations({ items })` renders nothing when empty; each row: `action` as `h3`, `reason` as `p`, `ConfidenceMeter level={confidence}`.
- Unavailable note (when `llm_json.investigation?.available === false`): `p.note` *"Investigate mode was requested, but <provider> has no tool support."*

- [ ] **Step 1: Write the failing tests**

```ts
test("what the model tried lists every call including the refused one, with details")
test("recommendations render with confidence; absent when empty")
test("a pre-1.4.0 report shows neither section and no note")  // Review Focus 4
test("unavailable note when the provider had no tools")
```

- [ ] **Step 2: Run → fail.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run `npx vitest run`, `npx tsc -b`, `npx playwright test`** → pass. Render `/dev/report` with `investigatedReport` (add a `/dev/report-investigated` route) and check at 1280 and 390.

- [ ] **Step 5: Commit** `feat(ui): what the model tried and recommendations`

---

### Task 12: Docs and progress

**Files:**
- Modify: `README.md` (one paragraph under *Start here* on the investigate option and one under *The report* on the two sections; no new screenshot until a real run exists)
- Modify: `progress.md` (session log entry, decisions log rows for: full-evidence standing except cache-bust investigations; samples appended to `samples_json`; call log in `llm_json`; eval live rows; re-run does not keep the option)
- Modify: `frontend/package.json` version `1.4.0`

- [ ] **Step 1: Write the entries.** - [ ] **Step 2: Run the full suites once more** (`make test`, `npx playwright test`). - [ ] **Step 3: Commit** `docs: investigate mode (v1.4.0)`

---

## Self-review notes

- Spec coverage: option (T6, T9), tool and policy (T2), call log (T2, T6, T11), provider loop (T3), analysis retry semantics (T5), prompt and schema (T4), validator standing and steps check (T6), timing facts (T1, T6), live run (T9), report sections and old reports (T11), eval (T7), live test (T8), version and docs (T12). Non-goals respected: no OpenRouter tools, no scripted fake, no new columns.
- Names used across tasks: `Investigation`, `TOOL_SCHEMA`, `TOOL_NAME`, `BUDGET`, `is_investigation`, `sample_timing_facts`, `analyze_with_tools`, `ToolRun`, `NUDGE`, `run_analysis_outcome`, `AnalysisOutcome`, `INVESTIGATE_PROMPT`, `investigation_log`, `splitSamples().investigations`.
