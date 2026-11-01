# Timing Corroboration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add HTTP-level timing (TTFB split, peer IP, a cache-bust probe) as an independent signal the LLM uses to confirm or question the header-based verdict, and show the verdict's confidence (with its reason and any timing gap) at the top of the report.

**Architecture:** The sampler records per-request timing + peer IP and one probe entry (marked `probe: "cache_bust"`) inside `samples_json`. The bundle computes timing arithmetic, citable fact strings and a three-state seam (stored in `traceroute_json.seam`). The LLM returns `confidence_reason` + `timing_check`; the validator checks timing citations by exact match. The report renders a headline confidence line (layout C), a timing-gap tag, a timing finding card, and timing rows.

**Tech Stack:** Python 3.12 / FastAPI / httpx+httpcore / pytest (+respx); React + TS + Vite / vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-31-timing-corroboration-design.md`

## Global Constraints

- No new dependencies; no new DB columns (timing + probe live in `samples_json`, seam in `traceroute_json`).
- No vendor names / header signatures in code (`tests/vendor_tokens.py` guard on the validator; `test_no_interpretation_keys_anywhere` rejects bundle keys containing `vendor|hit|miss|layer|verdict`). Timing interpretation lives only in `app/llm/prompt.py`.
- Default test runs make no live network/LLM calls.
- Do not edit `stratum-requirements.md`, `stratum-action-plan.md`, or `cache-report-mockup.html`; record spec deviations (confidence moved off the Cached tile, §5.2 fields, probe) in `progress.md`.
- Status palette: amber = anomaly (timing gap tag/card); confidence bar keeps the accent gradient; green stays HIT-only.
- Exact names: option `cache_bust_probe` (default `true`); probe marker `"probe": "cache_bust"`; query param `stratum-cb=<random hex>`; bundle `timing.{edge_rtt_ms, requests, server_ms_spread, cache_bust, facts}`; `progression.wall_deltas_s`; `traceroute.seam.{status, traced_ip, peer_ips}` with status `confirmed|different_edge|unconfirmed`; verdict `confidence_reason`, `timing_check.{status, summary, hidden_layer_suspected, confidence, evidence}` with status `consistent|gap|insufficient`.
- Fact strings, exact format: `edge_rtt_ms: <v>`, `request <n> ttfb_ms: <v>`, `request <n> server_ms: <v>`, `warm server_ms min|median|max: <v>`, `cache_bust ttfb_ms: <v>`, `cache_bust server_ms: <v>`, `cache_bust status: <code>`; numbers rounded to 0.1 and printed with Python `str(round(x, 1))`.
- UI copy: `Verdict confidence`, tag `timing gap`, card title `Timing doesn't match the headers`, launch checkbox `Cache-bust probe (forced miss)`, progression column `cache-bust`, raw-drawer tab `Cache-bust probe`.
- Exactly one commit for this work, on a branch off `main` (Task 8).

## Review Focus

1. **A probe entry leaking into "the N requests"** (request counts, sample states, the progression columns, "no successful samples", claim evidence) → it must be excluded everywhere → `test_probe_excluded_from_progression_and_success_check` (Task 2), `test_probe_headers_not_claim_evidence` (Task 4), `probe excluded from request columns and counts` (Task 6).
2. **Old reports / frozen eval cases without any timing fields** → render and replay exactly as before; `timing_check` becomes `insufficient` → `test_bundle_without_timing_fields` (Task 2), `old report renders without confidence reason or tag` (Task 7).
3. **Cache-bust probe fails** (timeout / connection error / 4xx) → the run still completes; the probe is recorded with `ok: false` or its status → `test_probe_failure_does_not_fail_run` (Task 1).
4. **A fabricated timing number that happens to appear in another fact** (e.g. `request 2 server_ms: 412.5` when only `cache_bust server_ms: 412.5` exists) → rejected → `test_timing_citation_must_be_exact_fact` (Task 4).
5. **A model that omits `timing_check` / `confidence_reason`** → verdict kept, `insufficient` default + flag, no degraded report → `test_missing_timing_check_defaults_and_flags` (Task 4), `test_parse_without_new_fields` (Task 3).

---

### Task 1: Sampler — timing split, peer IP, cache-bust probe

**Files:**
- Modify: `backend/app/collectors/http_sampler.py`, `backend/app/api/schemas.py` (`AnalysisOptions`), `backend/app/pipeline/orchestrator.py` (`_sample`, `_no_successful_samples`), `backend/evals/capture.py` (`non_2xx_summary`)
- Test: `backend/tests/test_sampler.py`, `backend/tests/test_pipeline.py`, `backend/tests/test_evals.py`

**Interfaces:**
- Produces: `sample_requests(url, *, request_count=4, interval_ms=0, extra_request_headers=None, timeout_ms=10_000, cache_bust_probe=False) -> list[dict]`. Each sample adds `peer_ip: str | None` and `timing: {connect_ms, tls_ms, ttfb_ms, total_ms}` (floats ms rounded to 0.1, or `None`). With `cache_bust_probe=True` one extra entry is appended: `request = request_count + 1`, `probe = "cache_bust"`, `url` = the busted URL, same fields. `is_probe(sample: dict) -> bool` (module-level helper, exported). `AnalysisOptions.cache_bust_probe: bool = True`.

- [ ] **Step 1: Write the failing tests** (RawHTTPServer, as existing tests do):
- `test_sample_has_timing_and_peer_ip` — N=2 → each sample: `peer_ip == "127.0.0.1"`; `timing` keys exactly `{connect_ms, tls_ms, ttfb_ms, total_ms}`; `ttfb_ms > 0`, `total_ms >= ttfb_ms`; `tls_ms is None` (plain http); `connect_ms` is a float ≥ 0 on request 1.
- `test_cache_bust_probe_appended` — N=3, `cache_bust_probe=True` → 4 entries; last has `probe == "cache_bust"`, `request == 4`; server-side the 4th request path has query `stratum-cb=<hex>` (≥ 8 hex chars) while 1–3 do not; for a URL that already has `?a=1`, the probe path keeps `a=1` and adds `stratum-cb`.
- `test_probe_off_by_default` — no `probe` entries when the flag is omitted.
- `test_probe_failure_does_not_fail_run` — responder sleeps past the timeout only on the 4th request → 3 ok samples + a probe entry with `ok is False`, `probe == "cache_bust"`.
- `test_no_successful_samples_ignores_probe` (`test_pipeline.py`) — samples = all `ok: False` plus an ok probe → pipeline report `status == "error"` ("no successful samples collected").
- `test_non_2xx_summary_ignores_probe` (`test_evals.py`) — 4 × 200 samples + a 403 probe → `None`; 4 × 403 + 200 probe → `"403×4"`.

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/test_sampler.py tests/test_pipeline.py tests/test_evals.py -q` — Expected: new tests FAIL (missing keys / unexpected kwarg).

- [ ] **Step 3: Implement.** Timing via `client.get(url, headers=…, extensions={"trace": <async callback>})`; httpcore emits `"<prefix>.<event>.started|complete"` with prefix `connection` (`connect_tcp`, `start_tls`) and `http11`/`http2` (`send_request_headers`, `receive_response_headers`); measure with `time.perf_counter()` per event pair; `ttfb_ms` = `send_request_headers.started` → `receive_response_headers.complete`. `peer_ip` from `response.extensions["network_stream"].get_extra_info("server_addr")[0]` guarded (`None` on any failure). Probe URL: add `stratum-cb=secrets.token_hex(8)` with `urllib.parse` (keep existing query). Keep `elapsed_ms` unchanged. `_sample` passes `cache_bust_probe=options.get("cache_bust_probe", True)`; `_no_successful_samples` and `non_2xx_summary` skip `is_probe` entries.

- [ ] **Step 4: Run** the same command — Expected: all PASS; then `uv run pytest -q` — Expected: full backend PASS.

---

### Task 2: Bundle — timing arithmetic, facts, wall deltas, seam

**Files:**
- Modify: `backend/app/pipeline/bundle.py`; regenerate `backend/tests/fixtures/bundle/golden_bundle.json`
- Test: `backend/tests/test_bundle.py`

**Interfaces:**
- Consumes: sample shape + `is_probe` (Task 1).
- Produces: `assemble_bundle(...)` output gains `progression.wall_deltas_s: list[float | None]`, top-level `timing` (spec §2 shape), `traceroute.seam`. Helpers: `timing_section(samples: list[dict]) -> dict`, `seam(traceroute_hops: list[dict], samples: list[dict], dns: dict | None) -> dict`. Progression and `meta.gaps` "samples" check ignore probe entries. `different_edge` adds `meta.gaps` entry `{"stage": "seam", "reason": "route reached <traced_ip>; samples connected to <peer_ips>"}`.

- [ ] **Step 1: Write the failing tests:**
- `test_timing_section_arithmetic` — samples: req1 `connect_ms 38.2, ttfb_ms 79.5`; req2 `ttfb 41.4`; req3 `ttfb 42.0`; probe `ttfb 450.7, status 200` → `edge_rtt_ms == 38.2`; `requests == [{"request":1,"ttfb_ms":79.5,"server_ms":41.3}, {"request":2,"ttfb_ms":41.4,"server_ms":3.2}, {"request":3,"ttfb_ms":42.0,"server_ms":3.8}]`; `server_ms_spread == {"min":3.2,"median":3.5,"max":3.8,"count":2}`; `cache_bust == {"ttfb_ms":450.7,"server_ms":412.5,"status":200}`; `facts` contains exactly, in order: `"edge_rtt_ms: 38.2"`, `"request 1 ttfb_ms: 79.5"`, `"request 1 server_ms: 41.3"`, `"request 2 ttfb_ms: 41.4"`, `"request 2 server_ms: 3.2"`, `"request 3 ttfb_ms: 42.0"`, `"request 3 server_ms: 3.8"`, `"warm server_ms min: 3.2"`, `"warm server_ms median: 3.5"`, `"warm server_ms max: 3.8"`, `"cache_bust ttfb_ms: 450.7"`, `"cache_bust server_ms: 412.5"`, `"cache_bust status: 200"`.
- `test_bundle_without_timing_fields` — `akamai_inputs()` (no timing) → `timing == {"edge_rtt_ms": None, "requests": [], "cache_bust": None, "facts": []}` (no `server_ms_spread` key); no exception.
- `test_spread_omitted_with_one_warm_value` — two samples → no `server_ms_spread`, no `warm …` facts.
- `test_wall_deltas` — `started_at_ms` 0, 1500, 3010 → `wall_deltas_s == [1.5, 1.5]`; missing value → `None`.
- `test_probe_excluded_from_progression_and_success_check` — probe entry not in `age_values`/`status`; all real samples `ok: False` + ok probe → `meta.gaps` contains the `samples` gap.
- `test_seam_states` — parametrize: traced `23.55.1.1` ∈ peer IPs → `confirmed`; traced ∈ DNS `a` but ∉ peer IPs → `different_edge` + a `seam` gap; traced elsewhere / no hops / no peer IPs → `unconfirmed`, no gap. `seam == {"status":…, "traced_ip":…, "peer_ips": sorted distinct}`.
- Keep `test_no_interpretation_keys_anywhere` green; regenerate the golden snapshot by dumping `assemble_bundle(**akamai_inputs())` and assert the existing golden test passes.

- [ ] **Step 2: Run** `uv run pytest tests/test_bundle.py -q` — Expected: new tests FAIL.

- [ ] **Step 3: Implement** in `bundle.py`. `edge_rtt_ms` = first non-null `connect_ms` among non-probe samples in request order; `server_ms = round(ttfb − edge_rtt, 1)` when both present; spread over non-probe requests 2…N with non-null `server_ms` (median via `statistics.median`, rounded 0.1); traced IP = last hop with `ip`, not `unresponsive`, not `private`. Then regenerate the golden file.

- [ ] **Step 4: Run** `uv run pytest -q` — Expected: full backend PASS (golden-dependent tests in `test_validator`, `test_analysis`, `test_evals` included).

---

### Task 3: LLM schema, prompt, fake provider

**Files:**
- Modify: `backend/app/llm/schema.py`, `backend/app/llm/prompt.py`, `backend/app/llm/fake.py`
- Test: `backend/tests/test_analysis.py`, `backend/tests/test_fake_llm.py`

**Interfaces:**
- Produces: `class TimingCheck(BaseModel): status: Literal["consistent","gap","insufficient"]; summary: str = ""; hidden_layer_suspected: bool = False; confidence: Confidence = "low"; evidence: list[str] = []`. `CacheVerdict` gains `confidence_reason: str = ""` and `timing_check: TimingCheck | None = None`.

- [ ] **Step 1: Write the failing tests:**
- `test_parse_with_timing_check` — `VALID_RESULT` + `timing_check={"status":"gap","summary":"s","hidden_layer_suspected":True,"confidence":"medium","evidence":["edge_rtt_ms: 38.2"]}` + `confidence_reason="r"` → parsed fields equal; bad status `"maybe"` → `ValidationError`.
- `test_parse_without_new_fields` — plain `VALID_RESULT` parses; `timing_check is None`, `confidence_reason == ""`.
- `test_prompt_timing_guidance` — `SYSTEM_PROMPT` contains `"timing_check"`, `"confidence_reason"`, `"timing.facts"`, `"warm server_ms"`, `"cache_bust"`, the noise rule phrase `"clearly exceeds the warm spread"`, and `"Timing never adds, removes, or re-states layers"`; still contains `"Do not infer cache layers from traceroute hops."`.
- `test_fake_emits_timing_check` (`test_fake_llm.py`) — fake verdict has `timing_check.status == "insufficient"` and a string `confidence_reason`, and still validates with zero flags against the golden bundle.

- [ ] **Step 2: Run** `uv run pytest tests/test_analysis.py tests/test_fake_llm.py -q` — Expected: new tests FAIL.

- [ ] **Step 3: Implement.** Schema per Interfaces. Prompt: add both fields to `OUTPUT_SCHEMA` under `cache_verdict`; add a `## Timing corroboration` section covering every bullet in spec §3 "Prompt additions" (field meanings, guidance without thresholds, probe-header check, noise rule with the exact phrase "clearly exceeds the warm spread", gap/insufficient definitions, verbatim citation from `timing.facts`, "Timing never adds, removes, or re-states layers and never changes `serving_layer`"). Fake: add `confidence_reason: ""` and `timing_check: {"status":"insufficient","summary":"fake provider does not assess timing","hidden_layer_suspected":False,"confidence":"low","evidence":[]}`.

- [ ] **Step 4: Run** `uv run pytest -q` — Expected: full backend PASS.

---

### Task 4: Validator — timing citations, probe exclusion, honest headline

**Files:**
- Modify: `backend/app/pipeline/validator.py`
- Test: `backend/tests/test_validator.py`

**Interfaces:**
- Consumes: bundle `timing.facts` (Task 2), `TimingCheck` (Task 3), `is_probe` semantics (key `probe` present).
- Produces: `validate_verdict` additionally: excludes probe-sample headers from the claim index; validates `timing_check`; fills a missing `timing_check` with the insufficient default; appends fixed notes to `confidence_reason`. Fixed strings: `NOTE_SERVING = " · citation check: serving-layer evidence not found in the captured data"`, `NOTE_TIMING = " · citation check: timing evidence not found — timing assessment discarded"`.

- [ ] **Step 1: Write the failing tests** (bundle = golden + a `timing.facts` list and one probe sample with a unique header `["x-probe-only", "abc123"]`):
- `test_probe_headers_not_claim_evidence` — a layer citing `x-probe-only: abc123` → downgraded to UNKNOWN with a flag.
- `test_timing_check_valid_citations` — evidence `["edge_rtt_ms: 38.2", "x-probe-only: abc123"]` → unchanged, no timing flag (probe headers allowed here).
- `test_timing_citation_must_be_exact_fact` — facts contain `cache_bust server_ms: 412.5`; evidence `["edge_rtt_ms: 38.2", "request 2 server_ms: 412.5"]` → `status == "insufficient"`, `hidden_layer_suspected is False`, flag path `cache_verdict.timing_check`, and `confidence_reason` ends with `NOTE_TIMING`.
- `test_timing_check_without_any_fact_fails` — evidence `["x-probe-only: abc123"]` only → `insufficient` + flag.
- `test_missing_timing_check_defaults_and_flags` — `timing_check=None` → verdict has `timing_check.status == "insufficient"`, flag reason `"not provided"`; `confidence_reason` unchanged (no note — nothing was discarded).
- `test_serving_cascade_appends_note` — serving layer's citation fabricated → `confidence == "low"` and `confidence_reason` ends with `NOTE_SERVING`.
- Existing `test_no_vendor_names_in_source` stays green.

- [ ] **Step 2: Run** `uv run pytest tests/test_validator.py -q` — Expected: new tests FAIL.

- [ ] **Step 3: Implement.** Build two indexes: claim index (non-probe samples + DNS + hops) and a probe-inclusive index for `timing_check`. Timing-fact shape regex: `^(edge_rtt_ms|request \d+ |warm server_ms|cache_bust )` (case-insensitive, after trim). Rule: pass iff ≥1 citation ∈ facts set, every fact-shaped citation ∈ facts set, every other citation `contains()` in the probe-inclusive index.

- [ ] **Step 4: Run** `uv run pytest -q` — Expected: full backend PASS.

---

### Task 5: Frontend data layer — types and timing helpers

**Files:**
- Modify: `frontend/src/views/report/types.ts`
- Create: `frontend/src/views/report/timing.ts`, `frontend/src/views/report/timing.test.ts`

**Interfaces:**
- Produces (in `types.ts`): `TimingCheck { status: "consistent"|"gap"|"insufficient"; summary: string; hidden_layer_suspected: boolean; confidence: string; evidence: string[] }`; `CacheVerdict` gains `confidence_reason?: string; timing_check?: TimingCheck`; `Seam { status: "confirmed"|"different_edge"|"unconfirmed"; traced_ip: string|null; peer_ips: string[] }`; `SampleTiming { connect_ms: number|null; tls_ms: number|null; ttfb_ms: number|null; total_ms: number|null }`; `RawSample { request: number; http_version?: string; status?: number; started_at_ms?: number; headers: [string,string][]; probe?: string; peer_ip?: string|null; timing?: SampleTiming }`.
- Produces (in `timing.ts`): `isProbe(s: RawSample): boolean`; `splitSamples(samples: RawSample[]): { requests: RawSample[]; probe: RawSample | null }`; `edgeRttMs(requests: RawSample[]): number | null`; `serverMs(s: RawSample, edgeRtt: number | null): number | null` (rounded to 0.1, same rule as the bundle).

- [ ] **Step 1: Write the failing tests** in `timing.test.ts`:
- `splits probe from requests` — 3 requests + probe → `requests.length === 3`, `probe.request === 4`; no probe → `null`.
- `edge rtt is first non-null connect_ms` — `[null-timing, {connect 38.2}, {connect 40}]` → `38.2`; none → `null`.
- `server time matches bundle arithmetic` — ttfb `41.4`, rtt `38.2` → `3.2`; missing ttfb or rtt → `null`.

- [ ] **Step 2: Run** `cd frontend && npx vitest run src/views/report/timing.test.ts` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement** `timing.ts` and the type additions (rounding: `Math.round(x * 10) / 10`).

- [ ] **Step 4: Run** `npx vitest run` — Expected: all PASS; `npx tsc -b` clean.

---

### Task 6: Frontend evidence views — progression, raw drawer, counts, seam

**Files:**
- Modify: `frontend/src/views/report/Progression.tsx`, `RawDrawer.tsx`, `Section02.tsx` (eyebrow count), `ReportView.tsx` (requests pill), `MeasurementSeam.tsx`, `Section01.tsx` (pass `seam`)
- Test: `frontend/src/views/report/Section02.test.tsx`, `frontend/src/views/report/report.test.tsx`

**Interfaces:**
- Consumes: `RawSample`, `Seam`, `splitSamples`, `edgeRttMs`, `serverMs` (Task 5).
- Produces: `MeasurementSeam({ hops, seam }: { hops: Hop[]; seam?: Seam })`.

- [ ] **Step 1: Write the failing tests:**
- `probe excluded from request columns and counts` — samples = 3 requests + probe → progression has `Request 1..3` headers plus a `cache-bust` column; the eyebrow reads `3 consecutive requests`; the top pill reads `3 requests`; the cache-state row has 3 tags + an empty probe cell.
- `timing rows render from samples` — rows `TTFB` and `Server time` with values `79.5 ms`, `41.4 ms` … and `41.3 ms`, `3.2 ms` …; the probe column shows its ttfb/server time; samples without timing → rows omitted entirely.
- `probe note when N > 6` — 8 requests + probe → no `cache-bust` column; a note containing `cache-bust probe` and the probe's server time below the table.
- `raw drawer probe tab` — a tab labelled `Cache-bust probe` showing the probe's headers.
- `seam text per status` — `confirmed`/absent → existing text containing `the same node`; `different_edge` → text contains `another server for this hostname` and not `the same node`; `unconfirmed` → contains `inferred, not measured`.

- [ ] **Step 2: Run** `npx vitest run src/views/report` — Expected: new tests FAIL.

- [ ] **Step 3: Implement.** Progression: build columns from `requests`; `TTFB`/`Server time` rows use the `Table`/`TableRow` primitives and `.flat` muted class like `Age`; values formatted `${v} ms`, `—` when null; probe column header `cache-bust`. RawDrawer tab label `Cache-bust probe` for the probe. Seam copy: `different_edge` → "The route reached {traced_ip}, another server for this hostname; the samples connected to {peer_ips}. The hops above describe a sibling edge, not the one that served the headers." `unconfirmed` → "The trace didn't reach the IP that served the samples ({peer_ips}), so this seam is inferred, not measured."

- [ ] **Step 4: Run** `npx vitest run` and `npx tsc -b` — Expected: all PASS, clean.

---

### Task 7: Frontend verdict top — confidence line, tag, timing card, launch option

**Files:**
- Create: `frontend/src/views/report/VerdictConfidence.tsx`
- Modify: `frontend/src/views/report/VerdictTiles.tsx` (remove Cached `ConfBar`; tag on Served-from), `frontend/src/components/Badge.tsx` (variant `timing-gap`), `frontend/src/views/report/Findings.tsx` + its caller (pass `timing`), `frontend/src/views/report/ReportView.tsx` (render `VerdictConfidence` above tiles), `frontend/src/index.css` (`.verdict-conf` styles from mockup tokens), `frontend/src/views/Launch.tsx`, `frontend/src/api/client.ts` (`AnalysisOptions.cache_bust_probe: boolean`)
- Test: `frontend/src/views/report/report.test.tsx`, `frontend/src/components/Badge.test.tsx`, `frontend/src/views/Launch.test.tsx`

**Interfaces:**
- Consumes: `CacheVerdict.confidence_reason`, `TimingCheck` (Task 5); `ConfBar`, `Badge` primitives.
- Produces: `VerdictConfidence({ verdict }: { verdict: CacheVerdict | null })`; Badge variant `"timing-gap"` → classes `unverified timing-gap`, default text `timing gap`; `Findings({ security, performance, timing }: {…; timing?: TimingCheck })`.

- [ ] **Step 1: Write the failing tests:**
- `confidence line shows level, bar and reason` — verdict `confidence:"medium"`, `confidence_reason:"lowered: timing disagrees with the headers"` → text `Verdict confidence`, `Medium`, the reason; one `.conf-bar` rendered **inside the confidence line** and **none inside the Cached tile**.
- `confidence line shows unverified badge for validator notes` — reason containing `citation check:` → an `unverified` badge in the line.
- `confidence line hidden when degraded` — degraded verdict → no `Verdict confidence` text.
- `timing gap tag on served-from tile` — `timing_check.status:"gap"` → Served-from tile contains `timing gap`; `consistent` → absent.
- `timing card first among warnings` — gap with summary `S`, confidence `medium`, evidence `["request 2 server_ms: 3.2"]`, plus one critical and one warning perf finding → performance column order: critical card, timing card (title `Timing doesn't match the headers`, text `S`, `LLM confidence · medium`, code `request 2 server_ms: 3.2`), then the other warning.
- `insufficient summary renders as info card` — status `insufficient`, summary `T` → an info card containing `T`; empty summary → no card.
- `old report renders without confidence reason or tag` — the existing `akamaiReport` fixture (no new fields) → `Verdict confidence` + `High`, no reason text, no `timing gap`.
- `Badge timing-gap variant` (`Badge.test.tsx`) — renders `timing gap` with classes `unverified timing-gap`.
- `launch sends cache_bust_probe` (`Launch.test.tsx`) — default POST body `options.cache_bust_probe === true`; unchecking `Cache-bust probe (forced miss)` → `false`.

- [ ] **Step 2: Run** `npx vitest run` — Expected: new tests FAIL.

- [ ] **Step 3: Implement.** Confidence line markup: an eyebrow-style `k` label `Verdict confidence`, the level capitalised in display font, `ConfBar` (reuse `CONF_PERCENT` high 92 / medium 66 / low 33 — move it to `VerdictConfidence.tsx`), reason text in `--mid`. `.verdict-conf` layout like option C of the approved mockup (panel background, border, 10px radius, flex row). Keep `colorLint`/`contrast` tests green (no new hex values; tokens only).

- [ ] **Step 4: Run** `npx vitest run && npx tsc -b && npm run build` — Expected: all PASS, build clean; then `npm run test:e2e` — Expected: mocked Playwright suite PASS (a11y/keyboard/visual).

---

### Task 8: Real-data check, progress, single commit

**Files:**
- Create: `backend/evals/cases/persil-home-timing.json`
- Modify (local, git-ignored): `progress.md`; `backend/pyproject.toml` → `version = "1.2.0"`, `backend/uv.lock`

- [ ] **Step 1: Full suites.** `make test` — Expected: backend and frontend all PASS.
- [ ] **Step 2: Local persil run.** Start `uv run --env-file ../.env uvicorn app.main:app --port 8000` (background); POST `{"url":"https://www.persil.de/","provider":"anthropic","model":"claude-opus-4-8","options":{"request_count":4,"interval_ms":1500}}`; poll until `done`. Expected: 5 sample entries (4 + probe), each with `timing` and `peer_ip`; `verdict_json.timing_check` present.
- [ ] **Step 3: Capture** `python -m evals capture http://localhost:8000/reports/<id> --name persil-home-timing`; copy `persil-home`'s `expected` block into it.
- [ ] **Step 4: Eval + by-eye check.** `python -m evals run --model anthropic:claude-opus-4-8 --model openrouter:openai/gpt-5`. Read each model's `timing_check` in the results file. Expected: serving ✓ (Fastly); `timing_check.status` `consistent` or `insufficient`. **A hidden-layer `gap` whose numbers are inside the warm spread is a defect** — revise the prompt's noise rule and re-run before committing. Stop the server.
- [ ] **Step 5: progress.md** — session-log entry (`1.2.0 · timing corroboration`), decisions (layout C replaces the Cached-tile bar; `cache_bust` naming; probe in `samples_json`; seam in `traceroute_json`; optional new verdict fields; exact-match timing facts; validator notes), fixture inventory (`persil-home-timing`, regenerated golden bundle).
- [ ] **Step 6: Commit once** on branch `timing-corroboration`: `git add` the touched backend/frontend files, the case, the spec + plan, `backend/pyproject.toml`, `backend/uv.lock`; `git commit -m "feat: timing corroboration + headline verdict confidence (v1.2.0)"` with the session's Co-Authored-By trailer. Expected: `git show --stat HEAD` lists no `.env`, `backend/evals/runs/`, or `progress.md`.
