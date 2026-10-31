# Eval corpus for LLM cache verdicts — design

**Date:** 2026-10-31 · **Status:** draft, awaiting operator approval

## Intent

Stratum's headline answer (which layer served the page, and what the chain
from user to origin looks like) is produced entirely by the LLM. Today there is
no way to measure whether that answer is right. Prompt fixes (e.g. the 1.0.2
multi-CDN fix) are validated against one site by eye, and model choice is a
guess.

The operator knows the real infrastructure behind some sites from the inside.
For those sites the correct verdict is known with certainty. The eval corpus
turns that knowledge into a repeatable check: frozen evidence from real runs +
an answer key the operator writes, replayed through the current prompt and any
number of models, printed as an expected-vs-actual table.

The same tool must also be useful for sites where the operator does **not**
know the setup: there the table simply shows each model's reading of the
serving layer and chain, side by side, with no score.

## Goals

1. **Freeze a real run into a case.** Point a command at a finished report on a
   running Stratum instance (homelab Docker or local), give it a case name, get
   a case file in the repo.
2. **Optional answer key per case.** The operator may write the expected
   serving layer and/or the expected chain. Cases without one are still run and
   shown ("observed" cases).
3. **Replay across several models side by side** through the current
   `SYSTEM_PROMPT` and the real analysis path (parse → retry → evidence
   validator), so the result is exactly what a real report would show.
4. **Print one table**: per case, an expected row and one row per model, with
   serving layer and chain; ✓/✗ marks where an expectation exists; per-model
   scores at the bottom.

## Non-goals

- Scoring findings, narration, provider string, confidence, or per-sample
  states. Only serving layer and chain are scored.
- Re-collecting evidence. Cases are frozen; the eval never touches the target
  sites.
- Storing the exact bundle in the database (see *Constraints*). Bundles are
  rebuilt from stored columns.
- Comparing two eval runs automatically (before/after a prompt change). The
  operator runs the eval at both points and compares tables.
- A UI. Terminal only.

## Anti-goals (would make this a failure even if it works)

- **Correct answers marked wrong because of wording.** The model names layers
  freely ("Fastly shared cache" vs "Varnish tier"); matching must not depend on
  exact names.
- **Vendor knowledge creeping into code.** Architecture rule #1 (no vendor
  names, header signatures, or CNAME fingerprints in code) applies to the eval
  code too. Vendor names appear only in case data written by the operator.
- **Live calls in the default test run.** The eval itself is an explicit CLI
  command; the default `pytest` run uses fakes only.
- **An unlabeled case looking like a failure.** Observed cases show no ✓/✗ and
  are excluded from scores.

## Constraints

- Backend is Python 3.12 + uv, run from `backend/`. No new runtime
  dependencies (plain-text table, `httpx` already present). Env (API keys,
  basic-auth creds) comes from the repo `.env` via `uv run --env-file ../.env`.
- `stratum-requirements.md` / `stratum-action-plan.md` are not edited. This
  work adds tooling only; it changes no schema, prompt, or pipeline behavior.
- `progress.md` gets a session-log entry and decisions (it is git-ignored, so
  local only). Exactly one commit for the session, including this document.
- **Bundle fidelity limit (operator accepted):** reports store `dns_json`,
  `samples_json`, `traceroute_json`, not the full bundle. A rebuilt bundle lacks
  the browser warm-up timing (`warm`) and the run options
  (`meta.request_options`). Neither feeds the serving-layer/chain verdict.

## Decided by the operator

- Ground truth comes from the operator's inside knowledge of the setup.
- Scored dimensions: **serving layer** (which CDN / inner CDN tier / dispatcher
  / origin) and **chain** (ordered layers user → origin, and how many).
- Answer key is optional; unlabeled rows show the LLM's reading.
- Output is a table: expected vs actual serving layer and chain per case.
- Several models side by side in one run.
- Cases are captured from a report on a running Stratum instance (homelab
  Docker or local Mac).
- Case files are committed to this repo (headers included).
- No bundle storage change for now.
- Seed sites: **persil.de** (CloudFront in front of Fastly) and
  **www.unileverfoodsolutions.nl** (Akamai edge + parent → AEM dispatcher →
  origin), several cases per site over time. Seed cases are captured from local
  runs on this Mac; answer keys are in *Seed corpus* below.

## Design

### Where things live

```
backend/evals/
  __init__.py
  __main__.py        # CLI: `python -m evals capture|run`
  capture.py         # report link → case file
  case.py            # load/validate case files, rebuild bundle
  score.py           # layer-spec matching, serving/chain resolution, scores
  table.py           # plain-text table rendering
  runner.py          # cases × models through the real analyze path
  cases/             # committed case files, one JSON per case
  runs/              # git-ignored: full results of each eval run
  README.md          # how to capture, label, and run
backend/tests/test_evals.py
```

Makefile wrappers at the repo root:

- `make eval-capture REPORT=<report link> NAME=<case-name>`
- `make eval MODELS="anthropic:claude-opus-4-8 openrouter:openai/gpt-5"`

### Case file (`backend/evals/cases/<name>.json`)

```json
{
  "name": "persil-home",
  "url": "https://www.persil.de/",
  "source": {
    "report_link": "http://homelab:8000/reports/3f2a…",
    "report_id": "3f2a…",
    "captured_at": "2026-10-31T12:00:00Z",
    "vantage": "Berlin, DE · homelab",
    "provider": "anthropic",
    "model": "claude-opus-4-8"
  },
  "evidence": { "dns": {…}, "samples": […], "traceroute": {…} },
  "original_verdict": { … } ,
  "expected": {
    "serving": { "label": "Fastly", "match": ["fastly", "varnish"] },
    "chain": [
      { "label": "CloudFront edge", "match": ["cloudfront"] },
      { "label": "Fastly",          "match": ["fastly", "varnish"] },
      { "label": "origin",          "role": ["origin"], "optional": true }
    ],
    "notes": "CloudFront fronts Fastly; Fastly's x-cache is overwritten."
  }
}
```

- `evidence` is the report's `dns_json` / `samples_json` / `traceroute_json`,
  verbatim.
- `original_verdict` is the report's `verdict_json` at capture time (reference
  only; not displayed or scored). `null` if the report was degraded.
- `expected` is `null`, or an object with optional `serving`, optional `chain`,
  optional `notes`. Each of `serving` / `chain` is scored independently, so a
  case can know the serving layer without knowing the full chain.

### Layer spec (how the operator describes a layer)

A layer spec has:

- `label` (required): what the table shows in the expected row.
- `match` (optional): list of keywords; matches if **any** is a
  case-insensitive substring of the actual layer's
  `"{layer_name} {vendor} {cache_type}"`.
- `role` (optional): list of allowed `role` values (the §5.2 enum).
- `optional` (chain entries only, default false): the layer may be absent from
  the model's chain without failing the match.

At least one of `match` / `role` is required; if both are given, both must
hold. This keeps all vendor vocabulary in the case data, and lets two layers of
the same vendor be told apart by role (e.g. Akamai edge `role: ["edge"]` vs
Akamai parent `role: ["shield"]`).

### Resolving the model's answer

Both come from the **validated** verdict (`verdict_json` after the evidence
validator), i.e. what the report shows.

- **Actual serving layer** — mirror the report UI (`serving.ts`
  `findServingIndex`): the layer whose `layer_name` equals `serving_layer`;
  else the first layer with `state == "HIT"`; else none. Displayed as
  `layer_name (STATE)`. None → `—`.
- **Actual chain** — `layers` in order, excluding `role == "client"`.
  Displayed as `name [STATE] → name [STATE] … · N caching`, where N is the
  model's own `layer_count_to_origin`.
- **Degraded verdict** (`status: unavailable`) — both cells show
  `degraded: <reason>`; counts as a miss for any scored dimension.

### Scoring

- **Serving ✓** when the resolved serving layer matches `expected.serving`.
- **Chain ✓** when the actual chain aligns with `expected.chain` in order:
  every actual layer is consumed by exactly one expected entry that it
  matches, and every non-optional expected entry is consumed. Optional entries
  may be skipped. An extra actual layer the operator didn't list is a ✗ (the
  operator can add it to the case as `optional` if it doesn't matter).
- **Per-model score**: `serving x/y`, `chain x/y`, where `y` counts only cases
  that define that dimension. Observed cases never count.

### Table

```
case          model             serving layer               chain
persil-home   expected          Fastly                      CloudFront edge → Fastly → origin?
              claude-opus-4-8   Fastly shared cache (HIT) ✓ CloudFront edge [MISS] → Fastly shared cache [HIT] · 2 ✓
              gpt-5             CloudFront edge (MISS)    ✗ CloudFront edge [MISS] · 1 ✗
some-site     expected          —                           —
              claude-opus-4-8   nginx cache (HIT)           nginx cache [HIT] → Origin [UNKNOWN] · 1

score         claude-opus-4-8   serving 1/1   chain 1/1
              gpt-5             serving 0/1   chain 0/1
```

Optional expected entries render with a trailing `?`. A row whose validated
verdict carries validation flags shows a `⚠ N unverified` note. Long chains
wrap; nothing is silently truncated.

### Commands

From `backend/`:

```
uv run --env-file ../.env python -m evals capture <report link> --name <case-name>
uv run --env-file ../.env python -m evals run --model <provider:model> [--model …] [--case <name> …]
```

**capture**

- Accepts any of `…/reports/<id>`, `…/runs/<id>`, `…/api/analyses/<id>`; the id
  is the last path segment. Fetches `<scheme://host[:port]>/api/analyses/<id>`.
- Auth: URL userinfo if present, else `BASIC_AUTH_USER` / `BASIC_AUTH_PASS`
  from env if both set. A 401 gives a clear message naming those vars.
- Refuses reports whose `status` is not `done`, or with no successful samples.
  A degraded (`done`, verdict unavailable) report is accepted — its evidence is
  intact.
- Case name must match `[a-z0-9-]+`. Refuses to overwrite an existing case file
  (protects a hand-written answer key); delete the file to re-capture.
- Writes the case with `"expected": null` and prints the path plus a one-line
  reminder to fill in `expected`.

**run**

- `--model` is `provider:model`, split on the **first** colon (OpenRouter ids
  like `meta-llama/…:free` keep their suffix). At least one required.
- Before any call, every provider must be configured (key present); otherwise
  exit with a clear message and make no calls.
- Rebuilds each case's bundle with `assemble_bundle(url, dns, samples,
  warm=None, traceroute=<stored traceroute>, enrichment=<hops, geo_available,
  notes from the stored traceroute>, vantage=<source.vantage>,
  request_options={})`, so the stored traceroute fields survive unchanged.
- Calls go through `make_llm_analyze(...)` (the production
  run_analysis → validate_verdict path, including JSON retry and 429/5xx
  backoff), **one call at a time**, with a progress line per call on stderr.
- Prints the table to stdout. Writes the full results (per case × model:
  `verdict_json`, `llm_json`, timing) to `backend/evals/runs/<UTC timestamp>.json`
  and prints that path, so a wrong answer can be inspected afterwards.
- Exit code 0 when the run completes (scores are information, not a gate);
  non-zero only for setup errors (bad args, unconfigured provider, malformed
  case file).

### Tests (default suite, no live calls)

`backend/tests/test_evals.py`, reusing `FakeProvider` / `VALID_RESULT`
(`tests/test_analysis.py`) and `golden_bundle.json` where they fit:

- capture: respx-mocked report GET → case file with verbatim evidence; link
  forms parsed; basic-auth header sent; non-`done` / no-samples / existing-name
  / bad-name refused; degraded report accepted with `original_verdict: null`.
- bundle rebuild: rebuilt `dns` / `samples` / `traceroute` equal the stored
  evidence exactly (incl. `geo_available`, `enrichment_notes`).
- layer-spec matching: keyword any-of, role filter, both-must-hold, invalid
  spec (neither) rejected at load.
- serving resolution mirrors `serving.ts` (by name, fallback first HIT, none).
- chain alignment: exact, optional skipped, extra actual layer fails, client
  layer ignored, order matters.
- degraded verdict → `degraded:` cells and counted as a miss.
- scores count only labeled dimensions.
- runner: two fake "models" via an injected resolver → expected table rows and
  scores; unconfigured provider → setup error with zero calls.
- model-spec parsing incl. `openrouter:meta-llama/x:free`.
- guard: no vendor names / header signatures in `backend/evals/*.py` (same
  token list as the validator guard).

### Seed corpus (part of this session's deliverable)

Two cases: the home pages of persil.de and www.unileverfoodsolutions.nl.

**Source (operator decision):** run Stratum locally on the operator's Mac
(`make dev-backend`), analyze both home pages, then freeze the two reports with
`evals capture` against `http://localhost:8000/reports/<id>`. This sends real
requests to the two sites. The local run uses an LLM key from `.env` if present;
without one the report is degraded but the evidence is complete, which is all a
case needs. Traceroute will be empty without sudo; that doesn't affect the
serving-layer/chain verdict.

**Answer keys (operator decision):**

- `persil-home` — serving: Fastly. Chain (all required):
  CloudFront edge → Fastly → origin.
  ```json
  "serving": { "label": "Fastly", "match": ["fastly", "varnish"] },
  "chain": [
    { "label": "CloudFront edge", "match": ["cloudfront"] },
    { "label": "Fastly",          "match": ["fastly", "varnish"] },
    { "label": "origin",          "role": ["origin"] }
  ]
  ```
- `ufs-home` — serving: Akamai edge. Chain (all required):
  Akamai edge → Akamai parent → AEM dispatcher → AEM origin.
  ```json
  "serving": { "label": "Akamai edge", "match": ["akamai"], "role": ["edge"] },
  "chain": [
    { "label": "Akamai edge",    "match": ["akamai"], "role": ["edge"] },
    { "label": "Akamai parent",  "match": ["akamai"], "role": ["shield"] },
    { "label": "AEM dispatcher", "match": ["dispatcher"] },
    { "label": "AEM origin",     "role": ["origin"] }
  ]
  ```
  (Origin is required here too, matching the operator's persil decision.)

**Key vs. captured moment:** an answer key describes what normally happens,
but a case freezes one moment. Before committing, the builder reads each
captured case's headers. If they plainly contradict the key at that moment
(e.g. the Akamai edge reports a miss on every sample of `ufs-home`, or `Age` is
0 throughout `persil-home`), the builder stops and tells the operator instead of
committing a key that is wrong for that evidence. Re-running the analysis to
capture a warm moment is an acceptable fix.

After the seed cases are in, the builder runs the eval once with whichever
model(s) `.env` provides and includes the resulting table in the handoff.

More cases per site (static asset, bypassed path, other pages) are added by the
operator over time with `make eval-capture`.

## Calls made by the designer (not operator decisions)

- **Layer count is display-only.** The chain ✓ already requires exactly the
  right layers in the right order, so it covers "how many layers to origin".
  The model's own `layer_count_to_origin` is shown (`· N caching`) but not
  scored.
- **Layer matching by keyword + role**, not by exact name (`match` / `role`
  specs), so wording differences don't fail correct answers.
- **Score the validated verdict**, i.e. exactly what a report shows.
- **One call at a time** (free-tier rate limits); no concurrency flag.
- **Full results saved** to git-ignored `backend/evals/runs/` for inspection.
- **No overwrite on capture**; delete a case file to re-capture.
- **Vendor-name guard reused:** the forbidden-token list in
  `tests/test_validator.py::test_no_vendor_names_in_source` moves to a shared
  test helper so both the validator guard and the new `backend/evals/` guard use
  it.

## Left to the builder

- Exact column widths, wrapping, and alignment of the table.
- Internal module boundaries within `backend/evals/` (the layout above is a
  starting point).
- Progress-line wording; results-file field names beyond those listed.
- Whether the Makefile targets take extra pass-through args.
