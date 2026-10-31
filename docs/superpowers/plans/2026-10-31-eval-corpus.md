# Eval Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze real Stratum reports into labeled cases and replay them through the current prompt across several models, printing an expected-vs-actual table of serving layer and chain.

**Architecture:** A dev-tooling package `backend/evals/` beside `backend/app/`. `case.py` loads and validates case files and rebuilds the evidence bundle; `score.py` resolves and matches the model's serving layer and chain; `table.py` renders text; `runner.py` drives cases × models through the production `make_llm_analyze` path; `capture.py` pulls a finished report from a running instance; `__main__.py` is the CLI. No app behavior changes.

**Tech Stack:** Python 3.12, uv, httpx, pytest + pytest-asyncio + respx (all existing).

**Spec:** `docs/superpowers/specs/2026-10-31-eval-corpus-design.md`

## Global Constraints

- Run everything from `backend/` with uv; **no new dependencies** (runtime or dev).
- Env comes from the repo `.env` via `uv run --env-file ../.env …`.
- **No vendor names or header signatures in `backend/evals/*.py`** — the token list in `tests/vendor_tokens.py` (Task 6) is enforced by test. Note `dispatcher`, `x-cache`, `server-timing` are on that list; don't use them even in comments/docstrings. Vendor vocabulary lives only in case JSON and tests.
- Default `pytest` makes **no live network or LLM calls** — respx and `FakeProvider` only.
- Do not edit `stratum-requirements.md` / `stratum-action-plan.md`; do not change anything under `backend/app/`.
- **Exactly one commit for the whole session** (CLAUDE.md overrides per-task commits). Tasks 1–6 end with a green test run, not a commit; Task 7 makes the single commit.
- Case names match `^[a-z0-9-]+$`.
- Fixed copy: missing value `—`; chain suffix `· N caching` (N = model's `layer_count_to_origin`); optional expected entry suffix `?`; degraded cells `degraded: <reason>`; validation note `⚠ N unverified`; marks `✓` / `✗`.

## Review Focus

1. **Credentials in the report link** (`http://user:pass@host/reports/<id>`) must be used for auth but never written into the committed case file → `test_capture_strips_userinfo_from_source_link` (Task 5).
2. **A verdict whose `serving_layer` names no layer and has no HIT** (or empty `layers`) → serving `—`, `✗` when expected, no crash → `test_evaluate_no_serving_layer` (Task 2).
3. **A hand-edited case file with a mistake** (missing `label`, unknown role like `"cdn"`, `optional` on `serving`, invalid JSON) → `CaseError` naming the file, before any LLM call; CLI exits 2 → `test_load_case_errors_name_file` (Task 1), `test_cli_bad_case_exits_2_without_calls` (Task 6).
4. **`--case` naming a case that doesn't exist, or no cases at all** → setup error, zero LLM calls → `test_load_cases_unknown_name` (Task 1), `test_cli_bad_case_exits_2_without_calls` (Task 6).
5. **`analyze` raising unexpectedly mid-run** (not the usual degraded dict) → that cell shows `degraded: <ExcType>: <msg>` and the remaining cases still run → `test_run_eval_survives_analyze_exception` (Task 4).

---

### Task 1: Case files — load, validate, rebuild bundle

**Files:**
- Create: `backend/evals/__init__.py` (docstring only), `backend/evals/case.py`, `backend/evals/cases/.gitkeep`
- Test: `backend/tests/test_evals.py`

**Interfaces:**
- Produces (in `evals/case.py`):
  - `CASES_DIR: Path` = `Path(__file__).parent / "cases"`
  - `class CaseError(ValueError)`
  - `@dataclass(frozen=True) class LayerSpec: label: str; match: tuple[str, ...] = (); role: tuple[str, ...] = (); optional: bool = False`
  - `@dataclass(frozen=True) class Expected: serving: LayerSpec | None; chain: tuple[LayerSpec, ...] | None; notes: str | None`
  - `@dataclass(frozen=True) class Case: name: str; url: str; source: dict; evidence: dict; original_verdict: dict | None; expected: Expected | None`
  - `parse_case(data: dict, *, origin: str = "<case>") -> Case` — `origin` (file path) prefixes every `CaseError` message
  - `load_case(path: Path) -> Case`
  - `load_cases(directory: Path = CASES_DIR, names: Sequence[str] | None = None) -> list[Case]` — sorted by name; unknown name or zero cases → `CaseError`
  - `rebuild_bundle(case: Case) -> dict`

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_evals.py`. Module helpers (reused by later tasks):

```python
GOLDEN = json.loads((Path(__file__).parent / "fixtures/bundle/golden_bundle.json").read_text())

def make_case_data(name="golden", expected=None) -> dict:
    return {"name": name, "url": GOLDEN["meta"]["url"],
            "source": {"report_link": "http://localhost:8000/reports/r1", "report_id": "r1",
                       "captured_at": "2026-10-31T12:00:00Z", "vantage": GOLDEN["meta"]["vantage"],
                       "provider": "anthropic", "model": "m"},
            "evidence": {"dns": GOLDEN["dns"], "samples": GOLDEN["samples"], "traceroute": GOLDEN["traceroute"]},
            "original_verdict": None, "expected": expected}
```

Tests:
- `test_parse_case_minimal_observed` — `expected=None` → `case.expected is None`, `case.name == "golden"`.
- `test_parse_case_expected_specs` — expected `{"serving": {"label": "Edge", "match": ["Akamai"], "role": ["edge"]}, "chain": [{"label": "Edge", "match": ["akamai"]}, {"label": "origin", "role": ["origin"], "optional": True}], "notes": "n"}` → `serving == LayerSpec("Edge", ("akamai",), ("edge",))` (keywords lower-cased), `chain[1].optional is True`, `notes == "n"`. A dict with only `serving` gives `chain is None`.
- `test_load_case_errors_name_file` — parametrize over: spec without `label`; spec with neither `match` nor `role`; `role: ["cdn"]`; `serving` with `optional: true`; name `"Bad Name"`; missing `evidence`; file content `"{not json"`. Each written to `tmp_path / "x.json"`; `pytest.raises(CaseError, match="x.json")`.
- `test_load_cases_sorted_and_filtered` — two files `b.json`/`a.json` → names `["a", "b"]`; `names=["b"]` → `["b"]`.
- `test_load_cases_unknown_name` — `names=["nope"]` → `CaseError` mentioning `nope`; empty dir → `CaseError`.
- `test_rebuild_bundle_preserves_evidence` — `b = rebuild_bundle(parse_case(make_case_data()))`: `b["dns"] == GOLDEN["dns"]`, `b["samples"] == GOLDEN["samples"]`, `b["traceroute"] == GOLDEN["traceroute"]` (incl. `geo_available`, `enrichment_notes`), `b["meta"]["vantage"] == GOLDEN["meta"]["vantage"]`, `b["warm"] is None`, `b["progression"] == GOLDEN["progression"]`.

- [ ] **Step 2: Run** `uv run pytest tests/test_evals.py -v` — Expected: FAIL (`ModuleNotFoundError: evals`).

- [ ] **Step 3: Implement `evals/case.py`.** Valid roles = `typing.get_args(app.llm.schema.Role)`. `rebuild_bundle` calls `app.pipeline.bundle.assemble_bundle(url=case.url, dns=…, samples=…, warm=None, traceroute=tr, enrichment={"hops": tr.get("hops", []), "geo_available": tr.get("geo_available", False), "notes": tr.get("enrichment_notes", [])}, vantage=case.source.get("vantage"), request_options={})`.

- [ ] **Step 4: Run** `uv run pytest tests/test_evals.py -v` — Expected: all PASS.

---

### Task 2: Scoring — resolve, match, evaluate

**Files:**
- Create: `backend/evals/score.py`
- Test: `backend/tests/test_evals.py` (append)

**Interfaces:**
- Consumes: `LayerSpec`, `Expected`, `Case` (Task 1).
- Produces (in `evals/score.py`):
  - `@dataclass(frozen=True) class Outcome: serving_text: str; chain_text: str; serving_ok: bool | None; chain_ok: bool | None; unverified: int` — `*_ok is None` means not scored.
  - `layer_matches(spec: LayerSpec, layer: dict) -> bool`
  - `resolve_serving(verdict: dict) -> dict | None`
  - `actual_chain(verdict: dict) -> list[dict]`
  - `chain_matches(expected: Sequence[LayerSpec], actual: Sequence[dict]) -> bool`
  - `evaluate(case: Case, verdict_json: dict) -> Outcome`
  - `expected_texts(expected: Expected | None) -> tuple[str, str]` — `(serving_text, chain_text)`

- [ ] **Step 1: Write the failing tests.** Helpers:

```python
def L(name, role="edge", state="MISS", vendor="", cache_type="cache", caches=True):
    return {"layer_name": name, "vendor": vendor, "cache_type": cache_type, "role": role,
            "caches": caches, "state": state, "evidence_headers": ["x"]}

def V(layers, serving, count=1, flags=()):
    return {"cached": True, "confidence": "high", "provider": "p", "provider_evidence": [],
            "serving_layer": serving, "layer_count_to_origin": count, "layers": layers,
            "sample_states": [], "validation": {"ok": not flags, "flags": list(flags)}}
```

Tests:
- `test_layer_matches_keyword_any_of` — spec `match=("fastly","varnish")` matches `L("Inner tier", vendor="Varnish")` and `L("x", cache_type="fastly shared cache")`; not `L("CloudFront edge")`. Case-insensitive.
- `test_layer_matches_role_and_both` — `role=("shield",)` matches only role shield; `match=("akamai",), role=("edge",)` rejects an akamai shield layer.
- `test_resolve_serving_by_name_then_first_hit` — by exact `serving_layer` name; if name matches none → first `state=="HIT"`; neither → `None`.
- `test_actual_chain_drops_client` — `role="client"` layer removed, order kept.
- `test_chain_matches` — parametrized: exact match True; optional expected entry absent True; required entry absent False; extra actual layer False; swapped order False; empty actual vs all-optional expected True.
- `test_evaluate_scored_match` — expected serving `match=("fastly",)` + chain `[cloudfront, fastly, origin-role]`; verdict layers `CloudFront edge MISS`, `Fastly shared cache HIT (role shield)`, `Origin (role origin, state UNKNOWN)`, serving `"Fastly shared cache"`, count 2 → `serving_text == "Fastly shared cache (HIT)"`, `chain_text == "CloudFront edge [MISS] → Fastly shared cache [HIT] → Origin [UNKNOWN] · 2 caching"`, both ok True, `unverified == 0`.
- `test_evaluate_observed_case` — `expected=None` → both ok `None`, texts still filled.
- `test_evaluate_no_serving_layer` — `layers=[]`, serving `"Ghost"` → `serving_text == "—"`, `serving_ok is False` when expected.serving set.
- `test_evaluate_degraded` — `{"status": "unavailable", "reason": "auth error"}` → both texts `"degraded: auth error"`; ok False where expected defines it, None otherwise.
- `test_evaluate_counts_unverified` — two validation flags → `unverified == 2`.
- `test_expected_texts` — `("Fastly", "CloudFront edge → Fastly → origin?")` for an optional origin; `None` expected or missing parts → `"—"`.

- [ ] **Step 2: Run** `uv run pytest tests/test_evals.py -v` — Expected: new tests FAIL (`ImportError`).

- [ ] **Step 3: Implement `evals/score.py`.** `layer_matches` searches `f"{layer_name} {vendor} {cache_type}".lower()`. `resolve_serving` mirrors `frontend/src/views/report/serving.ts` `findServingIndex`. Chain alignment (order-preserving, optional entries skippable, every actual layer consumed):

```python
def _align(exp, act, i=0, j=0) -> bool:
    if j == len(act):
        return all(e.optional for e in exp[i:])
    if i == len(exp):
        return False
    if exp[i].optional and _align(exp, act, i + 1, j):
        return True
    return layer_matches(exp[i], act[j]) and _align(exp, act, i + 1, j + 1)
```

- [ ] **Step 4: Run** `uv run pytest tests/test_evals.py -v` — Expected: all PASS.

---

### Task 3: Table rendering

**Files:**
- Create: `backend/evals/table.py`
- Test: `backend/tests/test_evals.py` (append)

**Interfaces:**
- Consumes: `Case` (Task 1); `Outcome`, `expected_texts` (Task 2).
- Produces: `render_table(cases: Sequence[Case], model_labels: Sequence[str], outcomes: Mapping[tuple[str, str], Outcome]) -> str` — outcomes keyed by `(case.name, model_label)`.

- [ ] **Step 1: Write the failing tests** (build `Outcome`s directly; no LLM):
- `test_table_rows_and_marks` — one scored case, models `["m1","m2"]` (m1 both ok, m2 both wrong): output contains header words `case`, `model`, `serving layer`, `chain`; an `expected` row with the expected texts; the m1 row contains `"Fastly shared cache (HIT) ✓"` and ends its chain with `"✓"`; the m2 row contains `"✗"`.
- `test_table_observed_case_has_no_marks` — `expected=None` case: its expected row shows `—` twice; its model rows contain neither `✓` nor `✗`.
- `test_table_scores_count_only_labeled` — one scored + one observed case → score lines `"m1"` with `"serving 1/1"` and `"chain 1/1"`; a case with only `expected.serving` contributes to serving `y` but not chain `y` (`"chain 0/0"` shown as `"chain —"`).
- `test_table_unverified_note` — `Outcome(unverified=2)` row contains `"⚠ 2 unverified"`.
- `test_table_wraps_without_truncation` — a chain text of 200 chars: every word of it appears in the output and no output line exceeds 160 chars.

- [ ] **Step 2: Run** `uv run pytest tests/test_evals.py -k table -v` — Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `render_table`.** Plain fixed-width columns; cells wider than their column wrap onto continuation lines (`textwrap.wrap`, break on spaces); case name printed only on the case's first row; a blank line between cases; score block last. Exact widths are the implementer's call within the 160-char line limit.

- [ ] **Step 4: Run** `uv run pytest tests/test_evals.py -v` — Expected: all PASS.

---

### Task 4: Runner — cases × models

**Files:**
- Create: `backend/evals/runner.py`; append `backend/evals/runs/` to the root `.gitignore`
- Test: `backend/tests/test_evals.py` (append)

**Interfaces:**
- Consumes: `Case`, `rebuild_bundle` (Task 1); `Outcome`, `evaluate` (Task 2); `app.pipeline.analyze.make_llm_analyze`; `app.llm.registry.get_provider`; `app.llm.prompt.SYSTEM_PROMPT`.
- Produces (in `evals/runner.py`):
  - `RUNS_DIR: Path` = `Path(__file__).parent / "runs"`
  - `class SetupError(Exception)`
  - `@dataclass(frozen=True) class ModelSpec: provider: str; model: str` with property `label -> str` (= `model`)
  - `parse_model_spec(text: str) -> ModelSpec` — split on the **first** `:`; empty part → `SetupError`
  - `Analyze = Callable[[dict, str, str], Awaitable[dict]]`
  - `@dataclass class EvalRun: outcomes: dict[tuple[str, str], Outcome]; records: list[dict]`
  - `async def run_eval(cases: Sequence[Case], models: Sequence[ModelSpec], *, analyze: Analyze, is_configured: Callable[[str], bool], progress: Callable[[str], None] = lambda _: None) -> EvalRun`
  - `write_results(run: EvalRun, models: Sequence[ModelSpec], directory: Path = RUNS_DIR, *, now: datetime) -> Path`

- [ ] **Step 1: Write the failing tests:**
- `test_parse_model_spec` — `"anthropic:claude-opus-4-8"` → `("anthropic","claude-opus-4-8")`; `"openrouter:meta-llama/x:free"` → model `"meta-llama/x:free"`; `"nocolon"`, `":m"`, `"p:"` → `SetupError`.
- `test_run_eval_two_models` — case = golden case with expected serving `{"label":"Dispatcher","match":["dispatcher"]}`; providers `{"fa": FakeProvider([json.dumps(VALID_RESULT)]), "fb": FakeProvider(["not json", "not json"])}`; `analyze = make_llm_analyze(resolver=providers.get)`; models `fa:m1`, `fb:m2`. → `outcomes[("golden","m1")].serving_ok is True`, `serving_text == "Apache Dispatcher (HIT)"`; `outcomes[("golden","m2")].serving_text.startswith("degraded:")` and `serving_ok is False`; `len(run.records) == 2`, each record has keys `case, provider, model, duration_ms, verdict_json, llm_json`.
- `test_run_eval_unconfigured_provider_makes_no_calls` — `is_configured=lambda p: p == "fa"`, models `fa:m1`, `zz:m2` → `SetupError` mentioning `zz`; `providers["fa"].calls == []`.
- `test_run_eval_survives_analyze_exception` — two cases; `analyze` raises `RuntimeError("boom")` for the first case only → first outcome text `"degraded: RuntimeError: boom"`, second case evaluated normally.
- `test_run_eval_rejects_duplicate_models` — same spec twice → `SetupError`.
- `test_write_results` — file named `20261031T120000Z.json` in `tmp_path`; JSON has `started_at`, `prompt_sha256 == sha256(SYSTEM_PROMPT)`, `models == ["fa:m1"]`, `records` equal to `run.records`.

- [ ] **Step 2: Run** `uv run pytest tests/test_evals.py -k "run_eval or model_spec or write_results" -v` — Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `evals/runner.py`.** Check duplicates + `is_configured` for every model before any call. Calls run sequentially (case-major, then model). Per call: `progress(f"[{k}/{total}] {case.name} × {spec.label}")`; time it; on exception record `{"status": "unavailable", "reason": f"{type(e).__name__}: {e}"}` as `verdict_json` and `llm_json=None`.

- [ ] **Step 4: Run** `uv run pytest tests/test_evals.py -v` — Expected: all PASS.

---

### Task 5: Capture — report link → case file

**Files:**
- Create: `backend/evals/capture.py`
- Test: `backend/tests/test_evals.py` (append)

**Interfaces:**
- Consumes: `CASES_DIR`, `parse_case`, `CaseError` (Task 1).
- Produces (in `evals/capture.py`):
  - `class CaptureError(Exception)`
  - `parse_report_link(link: str) -> tuple[str, str, tuple[str, str] | None, str]` — `(api_url, report_id, userinfo_auth, clean_link)`; `clean_link` has userinfo removed
  - `async def fetch_report(link: str, *, env: Mapping[str, str] | None = None) -> tuple[dict, str]` — `(report, clean_link)`
  - `build_case(report: dict, *, name: str, link: str, now: datetime) -> dict`
  - `write_case(case_data: dict, directory: Path = CASES_DIR) -> Path`
  - `async def capture(link: str, name: str, *, directory: Path = CASES_DIR, env: Mapping[str, str] | None = None, now: datetime | None = None) -> Path`

- [ ] **Step 1: Write the failing tests.** Helper `make_report(**over)` = a GET-report dict: `id "r1"`, `url GOLDEN["meta"]["url"]`, `status "done"`, `vantage`, `provider "anthropic"`, `model "m"`, `dns_json/samples_json/traceroute_json` from GOLDEN, `verdict_json {"cached": True, "layers": []}`, `llm_json None`, `error None`, then `over` applied.
- `test_parse_report_link_forms` — `http://localhost:8000/reports/r1`, `…/runs/r1`, `…/api/analyses/r1`, `…/reports/r1/?x=1#y` → all `("http://localhost:8000/api/analyses/r1", "r1", None, …)`; `http://h/other/r1` and `http://h/reports/` → `CaptureError`.
- `test_capture_writes_case` (respx) — GET `http://localhost:8000/api/analyses/r1` → `make_report()`; `capture(..., name="golden", directory=tmp_path, env={}, now=datetime(2026,10,31,12,tzinfo=UTC))` → `tmp_path/"golden.json"`; loaded JSON: `evidence == {"dns": GOLDEN["dns"], "samples": GOLDEN["samples"], "traceroute": GOLDEN["traceroute"]}`, `expected is None`, `source.report_id == "r1"`, `source.captured_at == "2026-10-31T12:00:00Z"`, `original_verdict == {"cached": True, "layers": []}`; `parse_case` accepts it.
- `test_capture_strips_userinfo_from_source_link` (respx) — link `http://u:p@localhost:8000/reports/r1` → request carries `Authorization: Basic dTpw`; written file text contains neither `u:p@` nor `dTpw`; `source.report_link == "http://localhost:8000/reports/r1"`.
- `test_capture_env_basic_auth` — env `{"BASIC_AUTH_USER": "a", "BASIC_AUTH_PASS": "b"}` → `Authorization: Basic YTpi`.
- `test_capture_401_names_env_vars` — 401 → `CaptureError` matching `BASIC_AUTH_USER`.
- `test_capture_refusals` — parametrize: `status="running"`; `status="error"`; `samples_json=[{**GOLDEN["samples"][0], "ok": False}]`; 404 → each `CaptureError`; no file written.
- `test_capture_degraded_report_accepted` — `verdict_json={"status": "unavailable", "reason": "x"}` → `original_verdict is None`.
- `test_write_case_refuses_overwrite_and_bad_name` — existing `golden.json` → `CaptureError`, file unchanged; name `"Bad Name"` → `CaptureError`.

- [ ] **Step 2: Run** `uv run pytest tests/test_evals.py -k "capture or report_link or write_case" -v` — Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `evals/capture.py`.** id = segment after the last `reports` / `runs` / `analyses` in the path. Auth: URL userinfo, else env `BASIC_AUTH_USER` + `BASIC_AUTH_PASS` if both set; pass as `httpx.BasicAuth` on a URL without userinfo. Connection errors → `CaptureError("could not reach …")`. Write JSON with `indent=2, ensure_ascii=False` + trailing newline. `build_case` output must pass `parse_case`.

- [ ] **Step 4: Run** `uv run pytest tests/test_evals.py -v` — Expected: all PASS.

---

### Task 6: CLI, Makefile, README, shared vendor guard

**Files:**
- Create: `backend/evals/__main__.py`, `backend/evals/README.md`, `backend/tests/vendor_tokens.py`
- Modify: `backend/tests/test_validator.py` (`test_no_vendor_names_in_source` imports the list), root `Makefile` (two targets + `.PHONY`)
- Test: `backend/tests/test_evals.py` (append)

**Interfaces:**
- Consumes: everything above.
- Produces: `main(argv: Sequence[str] | None = None, *, analyze: Analyze | None = None, is_configured: Callable[[str], bool] | None = None, cases_dir: Path = CASES_DIR, runs_dir: Path = RUNS_DIR, env: Mapping[str, str] | None = None) -> int`; `tests/vendor_tokens.py: FORBIDDEN_VENDOR_TOKENS: list[str]` (the exact list currently inline in `test_no_vendor_names_in_source`).

- [ ] **Step 1: Write the failing tests:**
- `test_cli_run_prints_table_and_writes_results` — one case file in `tmp_path/"cases"`; `main(["run", "--model", "fa:m1"], analyze=make_llm_analyze(resolver={"fa": FakeProvider([json.dumps(VALID_RESULT)])}.get), is_configured=lambda p: p == "fa", cases_dir=…, runs_dir=tmp_path/"runs")` → returns 0; `capsys` stdout contains `"Apache Dispatcher (HIT)"` and `"serving"`; exactly one file in `runs`, its path printed.
- `test_cli_bad_case_exits_2_without_calls` — parametrize: `--case nope`; a malformed case file present; `--model zz:m` unconfigured → returns 2, stderr has a one-line reason, the fake provider recorded zero calls.
- `test_cli_requires_model` — `main(["run"])` → non-zero (argparse `SystemExit` is acceptable).
- `test_cli_capture` (respx, `make_report()`) — `main(["capture", "http://localhost:8000/reports/r1", "--name", "golden"], cases_dir=tmp_path, env={})` → 0; file exists; stdout contains the path and the word `expected`.
- `test_no_vendor_names_in_evals_source` — every `backend/evals/*.py`, lower-cased, contains no token from `FORBIDDEN_VENDOR_TOKENS`.

- [ ] **Step 2: Run** `uv run pytest tests/test_evals.py -k "cli or vendor" -v` — Expected: FAIL.

- [ ] **Step 3: Implement.** `__main__.py`: argparse subcommands `capture <link> --name NAME` and `run --model SPEC (repeatable, required) [--case NAME (repeatable)]`; `CaseError` / `SetupError` / `CaptureError` → message on stderr, return 2; progress lines on stderr; table on stdout; then `results: <path>`. Defaults: `analyze = make_llm_analyze()`, `is_configured = lambda p: get_provider(p) is not None`, `env = os.environ`; end with `if __name__ == "__main__": raise SystemExit(main())`. Makefile (root):

```make
eval-capture: ## Freeze a report into an eval case: make eval-capture REPORT=<link> NAME=<case>
	cd backend && uv run $(if $(wildcard .env),--env-file ../.env) python -m evals capture "$(REPORT)" --name "$(NAME)"

eval: ## Replay eval cases: make eval MODELS="anthropic:<model> openrouter:<model>"
	cd backend && uv run $(if $(wildcard .env),--env-file ../.env) python -m evals run $(foreach m,$(MODELS),--model $(m))
```

README (`backend/evals/README.md`): what the eval is for; capture; the case format with the layer-spec rules (`label`, `match` any-of substring over name+vendor+cache type, `role`, `optional`) and the two seed keys as examples; run; how scores count; the bundle-fidelity limit (no warm timing / run options).

- [ ] **Step 4: Run** `uv run pytest -v` (full backend) — Expected: all PASS, incl. the moved validator guard.

---

### Task 7: Seed corpus, live run, progress, commit

**Files:**
- Create: `backend/evals/cases/persil-home.json`, `backend/evals/cases/ufs-home.json` (remove `.gitkeep`)
- Modify (local, git-ignored): `progress.md`

- [ ] **Step 1: Find non-redirecting home URLs.** `curl -sIL -o /dev/null -w '%{url_effective} %{http_code}\n' https://www.persil.de/` and the same for `https://www.unileverfoodsolutions.nl/`. Use each final URL (the sampler does not follow redirects). Expected: a 200 final URL for each.

- [ ] **Step 2: Start a local instance.** `cd backend && uv run --env-file ../.env uvicorn app.main:app --port 8000` in the background. Expected: `GET http://localhost:8000/api/health` → 200; `GET /api/models` lists ≥1 provider (if none, runs still work, degraded).

- [ ] **Step 3: Run both analyses.** `POST /api/analyses` with `{"url": <final URL>, "provider": <configured>, "model": <its first static model>, "options": {"request_count": 4, "interval_ms": 1500}}`; poll `GET /api/analyses/<id>` until `status` is `done`. Expected: `done`, samples with status 200.

- [ ] **Step 4: Capture.** `uv run --env-file ../.env python -m evals capture http://localhost:8000/reports/<id> --name persil-home` and `--name ufs-home`.

- [ ] **Step 5: Check the frozen moment against the keys** (spec *Seed corpus → Key vs. captured moment*). Read each case's sample headers. **Stop and report to the operator** if `persil-home` shows `age` 0 on every sample, or `ufs-home`'s edge cache status header reports a miss on every sample. Otherwise write the spec's two `expected` blocks verbatim into the case files.

- [ ] **Step 6: Live eval.** `uv run --env-file ../.env python -m evals run --model <provider:model> [...]` with each provider configured in `.env`. Expected: table printed, results file written. Keep the table for the handoff. Stop the local server.

- [ ] **Step 7: Full suite.** From the repo root: `make test`. Expected: backend all pass (was 155 + new), frontend all pass (58).

- [ ] **Step 8: Update `progress.md`** — new session-log entry at the top (`2026-10-31 · 1.1.0 · eval corpus`), decisions-log rows (layer-spec matching; validated-verdict scoring; display-only count; one-call-at-a-time; results dir; no-overwrite capture; shared vendor-token list), fixture-inventory rows (`make_case_data`/`make_report`/`L`/`V` in `tests/test_evals.py`; `backend/evals/cases/*`).

- [ ] **Step 9: Bump version and commit once.** `backend/pyproject.toml` `version = "1.1.0"`. Then:

```bash
git add backend/evals backend/tests/test_evals.py backend/tests/vendor_tokens.py backend/tests/test_validator.py \
        backend/pyproject.toml backend/uv.lock Makefile .gitignore docs/superpowers
git commit -m "feat: eval corpus for LLM cache verdicts (v1.1.0)"
```

Expected: `git status` clean except git-ignored files; `git show --stat` lists no `.env`, no `backend/evals/runs/`.
