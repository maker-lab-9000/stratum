# Minimal Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild all four views in the approved minimal, story-first look, with the model's confidence prominent and a meter beside every model claim.

**Architecture:** Backend adds optional verdict fields (headline, per-claim confidence, layer location), the origin-layer prompt rule, validator downgrades, and a cancel endpoint. Frontend adds two shared primitives (`ConfidenceMeter`, `TopBar`) and pure story helpers, then rebuilds the report as Answer → Strata → Claims → Measured → Findings → Hosted, and restyles Launch, LiveRun and History to match. Unused components and CSS are deleted.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 / pytest; React + TS + Vite / vitest + Testing Library / Playwright.

**Spec:** `docs/superpowers/specs/2026-11-01-minimal-redesign-design.md` — visual references `docs/design/report-strata.html` (report) and `docs/design/views.html` (launch, live run, history).

## Global Constraints

- No new dependencies; no DB schema change. API additions only: optional verdict fields + `POST /api/analyses/{id}/cancel`.
- Tokens unchanged (`index.css :root`); green (`--hit`) only in selectors matching the colour-lint allow-list (`hit|served|origin|…`) — name new green rules `.band.served`, `.state.hit`; origin-serve uses `--accent`.
- JetBrains Mono only for URLs, header values, IPs, measured numbers. Sentence-case headings; no all-caps labels, no numbered section markers, no middle-dot joined UI strings.
- Shared patterns render only through primitives (`Badge`, `Table`, `ConfidenceMeter`, `TopBar`).
- No vendor names or header signatures in code; vendor words in the UI come only from model fields.
- Unrated claim → `—` (never a default "Low"); degraded report → no confidence anywhere.
- Fixed copy: band states — served `Hit, served the page`; served-origin `Served by the origin, nothing cached`; passthrough `Miss, passed the request on`; forwards `Forwards without caching`; unknown `Unknown`; not-reached `Not reached`. Headline fallbacks — cached `Served from <serving_layer>.`; not cached `Not cached. The origin served it.`; degraded `No verdict` + `The model couldn't read the evidence: <reason>.`; failed `Analysis failed` + `<error>`. Strata marker `You, in <vantage>`; missing origin note `The model didn't list the origin layer.` Section headings `What the requests showed`, `What to look at`, `Where it's hosted`; hosted lead `Measured from <vantage>`. Launch heading `Which layer serves this page?`, button `Analyze`, recent heading `Recent`; live heading `Analyzing…`; history heading `History`. Timing words `Agrees with the headers` / `Doesn't match the headers` / `Not enough timing data`.
- Role labels: edge `Edge cache`, shield `Shield cache`, security `Security layer`, load_balancer `Load balancer`, reverse_proxy `Reverse proxy`, app_cache `App cache`, origin `Origin`, unknown `Unidentified layer`.
- Do not edit `stratum-requirements.md`, `stratum-action-plan.md`, `cache-report-mockup.html`; record deviations in `progress.md`.
- Exactly one commit, on branch `minimal-redesign` off `main` (Task 10); version `1.3.0`.

## Review Focus

1. **A model that still omits the origin layer** → strata end at the last listed layer with the note, no invented band → `strata note when origin not listed` (Task 4).
2. **Old reports without the new fields** → fallback headline, `—` meters, role without location, no crash → `old report renders with fallbacks` (Task 4).
3. **Nothing cached and the origin serves** → blue served-origin band, never green; headline says not cached → `origin-serve band is blue, not green` (Task 4).
4. **Degraded or failed report** → no meters anywhere, vantage still disclosed, Re-run offered, evidence sections still render → `degraded and failed reports keep evidence and vantage` (Task 5).
5. **Long values on a phone** (long layer names, long header values, many requests) → wrap inside the column, no horizontal page scroll at 390 px → `report with long values has no horizontal scroll at 390` (Task 9).

---

### Task 1: Model output fields, origin rule, validator downgrades, fake LLM

**Files:**
- Modify: `backend/app/llm/schema.py`, `backend/app/llm/prompt.py`, `backend/app/pipeline/validator.py`, `backend/app/llm/fake.py`
- Test: `backend/tests/test_analysis.py`, `backend/tests/test_validator.py`, `backend/tests/test_fake_llm.py`

**Interfaces:**
- Produces: `CacheVerdict.headline: str = ""`, `CacheVerdict.headline_detail: str = ""`, `CacheVerdict.provider_confidence: Confidence | None = None`; `Layer.confidence: Confidence | None = None`, `Layer.location: str = ""`; `Finding.confidence: Confidence | None = None`. Invalid confidence values coerce to `None`; `None` strings coerce to `""`.

- [ ] **Step 1: Write the failing tests:**
- `test_parse_new_story_fields` — `VALID_RESULT` + headline `"Served from the Apache Dispatcher."`, detail `"Akamai passed every request on."`, `provider_confidence:"high"`, layer[0] `confidence:"medium", location:"Frankfurt"`, a finding `confidence:"low"` → all parsed.
- `test_story_fields_optional_and_coerced` — plain `VALID_RESULT` → headline `""`, `provider_confidence is None`, layer `confidence is None`, `location == ""`, finding `confidence is None`; values `"moderate"` / `"very high"` / `5` for any confidence → `None`; `headline: null` → `""`; parsing never raises.
- `test_prompt_story_rules` — `SYSTEM_PROMPT` contains `"headline"`, `"headline_detail"`, `"provider_confidence"`, `"location"`, and `"Always list the origin as the last layer"`.
- `test_failed_layer_citation_sets_low_confidence` — layer[1] cites a fabricated header with `confidence:"high"` → validated layer `state == "UNKNOWN"`, `confidence == "low"`.
- `test_failed_provider_evidence_sets_low_confidence` — fabricated `provider_evidence`, `provider_confidence:"high"` → `provider == "UNKNOWN"`, `provider_confidence == "low"`.
- `test_failed_finding_citation_sets_low_confidence` — finding `evidence_header:"X-Fake: nope"`, `confidence:"high"` → flagged and `confidence == "low"`; a bare-name absence finding keeps its confidence.
- `test_fake_emits_story_fields` — fake verdict has non-empty `headline`, every layer has a `confidence`, the last layer has `role == "origin"`, and it validates with zero flags against the golden bundle.

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/test_analysis.py tests/test_validator.py tests/test_fake_llm.py -q` — Expected: new tests FAIL.

- [ ] **Step 3: Implement.** Coercion via `field_validator(mode="before")` on each confidence field (allowed set → value, else `None`) and on the string fields (`None` → `""`). Prompt: add the fields to `OUTPUT_SCHEMA`; a short `## Story fields and confidence` section — `headline` names the serving layer (or says nothing is cached) and never contradicts the verdict; `headline_detail` one sentence of context; each confidence rates that one claim, low/UNKNOWN preferred to guessing; `location` only from a captured value; and the rule, verbatim: "Always list the origin as the last layer (`role: origin`); when a cache served the page, its state is `UNKNOWN`." Validator: set the three `"low"` downgrades where the existing flags are raised. Fake: add headline/detail, `provider_confidence`, per-layer `confidence`, and a final origin layer citing the same real header.

- [ ] **Step 4: Run** `uv run pytest -q` — Expected: full backend PASS.

---

### Task 2: Cancel endpoint

**Files:**
- Modify: `backend/app/api/routes.py`, `frontend/src/api/client.ts`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Produces: `POST /api/analyses/{report_id}/cancel` → `200 {"id": str, "status": str}` (status after the call); 404 if missing. `client.cancelAnalysis(id: string): Promise<{ id: string; status: string }>`.

- [ ] **Step 1: Write the failing tests** (use the existing fake-deps manager with a slow sampler, as in the pipeline cancellation tests):
- `test_cancel_running_keeps_report` — start a slow analysis, POST cancel → 200; after the task settles the report exists with `status == "error"`, `error == "cancelled"`.
- `test_cancel_finished_is_noop` — a `done` report → 200, `status == "done"`, row unchanged.
- `test_cancel_unknown_404`.

- [ ] **Step 2: Run** `uv run pytest tests/test_api.py -q -k cancel` — Expected: FAIL (405/404 route missing).

- [ ] **Step 3: Implement** the route with `manager.cancel(report_id)` (no delete), await the job briefly via `manager.wait` when a task was cancelled, return the current status. Add `cancelAnalysis` to `client.ts` (POST, `json()` helper).

- [ ] **Step 4: Run** `uv run pytest -q` — Expected: full backend PASS.

---

### Task 3: Frontend foundations — ConfidenceMeter, TopBar, story helpers, types, base CSS

**Files:**
- Create: `frontend/src/components/ConfidenceMeter.tsx`, `frontend/src/components/TopBar.tsx`, `frontend/src/views/report/story.ts`
- Modify: `frontend/src/components/index.ts`, `frontend/src/views/report/types.ts`, `frontend/src/index.css`
- Test: `frontend/src/components/ConfidenceMeter.test.tsx`, `frontend/src/components/TopBar.test.tsx`, `frontend/src/views/report/story.test.ts`

**Interfaces:**
- Produces: `ConfidenceMeter({ level, size = "sm", showWord = true }: { level: string | null | undefined; size?: "sm" | "lg"; showWord?: boolean })` — `role="img"`, `aria-label="Confidence: high|medium|low"`; filled bars 3/2/1; unknown/null → `—` with `aria-label="Not rated"`. `TopBar({ context, actions }: { context?: ReactNode; actions?: ReactNode })` — brand link to `/`, nav links `New analysis` (`/`) and `History` (`/history`) with `aria-current="page"` on the active route.
- `story.ts`: `confidenceLevel(v: unknown): "high" | "medium" | "low" | null`; `headlineFor(verdict: CacheVerdict): { headline: string; detail: string }`; `servedPhrase(verdict: CacheVerdict | null, degraded: boolean): string`; `bandState(kind: LayerKind): string`; `roleLabel(role: string): string`.
- `types.ts`: `CacheVerdict` += `headline?: string; headline_detail?: string; provider_confidence?: string | null`; `Layer` += `confidence?: string | null; location?: string`; `Finding` += `confidence?: string | null`.

- [ ] **Step 1: Write the failing tests:**
- `ConfidenceMeter` — `level="medium"` → 2 filled bars, text `Medium`, label `Confidence: medium`; `size="lg"` adds class `meter-lg`; `level={null}` and `level="moderate"` → `—` with label `Not rated`; `showWord={false}` hides the word but keeps the label.
- `TopBar` — renders `Stratum`, links `New analysis` / `History`; at `/history` the History link has `aria-current="page"`; `context` and `actions` render.
- `headlineFor` — uses `headline`/`headline_detail` when present; else cached → `Served from Apache Dispatcher.` / `""`; not cached → `Not cached. The origin served it.`.
- `servedPhrase` — serving layer index > 0 with a different first vendor → `Fastly, behind Amazon CloudFront` (from `vendor`); serving is first → `Fastly`; serving role origin → `Origin`; no serving layer → `Origin` when `cached` is false; degraded → `No verdict`; vendor empty → falls back to `layer_name`.
- `bandState` / `roleLabel` — every kind/role maps to the exact copy in Global Constraints; unknown role → `Unidentified layer`.

- [ ] **Step 2: Run** `cd frontend && npx vitest run src/components src/views/report/story.test.ts` — Expected: FAIL (modules missing).

- [ ] **Step 3: Implement.** Meter bars per `docs/design/report-strata.html` (`.bars` 3 ascending bars; `lg` 13 px wide / 16–40 px tall, `sm` 5 px / 6–12 px; filled `--accent`, empty `--raise`). Add base layout CSS from the references (page `wrap` max 1000 px, top bar, section spacing, headings) to `index.css` alongside the existing rules (old rules are removed in Task 9).

- [ ] **Step 4: Run** `npx vitest run && npx tsc -b` — Expected: PASS, clean.

---

### Task 4: Report top — Answer, Strata, Claims

**Files:**
- Create: `frontend/src/views/report/Answer.tsx`, `Strata.tsx`, `Claims.tsx`
- Modify: `frontend/src/views/report/ReportView.tsx` (new order + `TopBar`), `frontend/src/fixtures/akamaiReport.ts` (add the new fields, keep a copy without them as `akamaiReportLegacy`), `frontend/src/index.css`
- Test: `frontend/src/views/report/report.test.tsx` (rewrite the verdict/Section-01 tests for the new structure)

**Interfaces:**
- Consumes: `ConfidenceMeter`, `TopBar`, `story.ts` helpers (Task 3); `classifyLayers` (`serving.ts`, unchanged); `flagsFor`.
- Produces: `Answer({ report, onRerun }: { report: Report; onRerun?: () => void })`; `Strata({ verdict, vantage }: { verdict: CacheVerdict; vantage: string | null })`; `Claims({ verdict }: { verdict: CacheVerdict })`. `ReportView` order: `TopBar` (context = URL + `read by <model>` + time; actions = `Re-run`) → `Answer` → `Strata` + `Claims` (non-degraded only) → measured / findings / hosted (Task 5 slots; keep today's Section01/Section02 content below until Task 5 replaces it).

- [ ] **Step 1: Write the failing tests:**
- `answer shows headline, detail, big meter and reason` — fixture headline/detail render as heading text; one `.meter-lg` with label `Confidence: high`; `confidence_reason` text shown; a reason containing `citation check:` adds an `unverified` badge.
- `strata bands follow the chain` — first child text `You, in Berlin, DE · Playwright runner` (the fixture vantage); one band per non-client layer in order; the served band has class `served`, contains `Hit, served the page`, its evidence values in `code`/mono, and a meter labelled with that layer's confidence; bands after it have class `unreached` and `Not reached`; a layer with validation flags shows `unverified`.
- `strata note when origin not listed` — verdict whose last layer isn't `role: origin` → text `The model didn't list the origin layer.` and no extra band.
- `origin-serve band is blue, not green` — `cached:false`, `serving_layer` = the origin layer → that band has class `served-origin` (not `served`), state `Served by the origin, nothing cached`; headline fallback `Not cached. The origin served it.` when no `headline`.
- `claims rows` — `Delivered by` shows provider + first `provider_evidence` + meter from `provider_confidence`; `Timing` gap → `Doesn't match the headers` + `timing gap` badge + meter; insufficient → `Not enough timing data` and `—`; no `timing_check` → no Timing row.
- `old report renders with fallbacks` — `akamaiReportLegacy` → headline `Served from Apache Dispatcher.`, every band meter shows `—`, role labels without location, no crash.

- [ ] **Step 2: Run** `npx vitest run src/views/report/report.test.tsx` — Expected: FAIL.

- [ ] **Step 3: Implement** per `docs/design/report-strata.html` (answer grid with the gauge right / below on mobile; bands as grid rows with the drop line, served dot, hatched unreached). Delete `VerdictTiles.tsx`, `VerdictConfidence.tsx`, `TopologyChain.tsx`, `LayerTable.tsx` and their tests' obsolete cases once `ReportView` no longer uses them.

- [ ] **Step 4: Run** `npx vitest run && npx tsc -b` — Expected: PASS, clean.

---

### Task 5: Report lower half — Measured, Findings, Hosted, degraded/failed

**Files:**
- Create: `frontend/src/views/report/Hosted.tsx`
- Modify: `frontend/src/views/report/Progression.tsx`, `Findings.tsx`, `RawDrawer.tsx` (no behaviour change; styling hook only), `ReportView.tsx`, `index.css`; delete `Section01.tsx`, `Section02.tsx`, `MeasurementSeam.tsx` (its `seamText` moves into `Hosted.tsx`)
- Test: `frontend/src/views/report/Section02.test.tsx` → rename to `lower.test.tsx` (keep the still-valid Progression / RawDrawer / timing tests), `report.test.tsx`

**Interfaces:**
- Consumes: Task 3 primitives/helpers; existing `DnsPanel`, `Geomap`, `HopLadder`, `SegmentNarration`, `RawDrawer`, `timing.ts`.
- Produces: `Hosted({ report }: { report: Report })`; `Findings({ security, performance, timing })` (same props, single list).

- [ ] **Step 1: Write the failing tests:**
- `measured section` — heading `What the requests showed`; first body row labelled `Model's reading` holds the per-request tags; Age / Cache-Control / Via / TTFB / Server time rows as today; cache-bust column and N > 6 note unchanged; edge round trip line `One round trip to the edge took 12.9 ms.` when `rtt_ms` present.
- `findings are one severity-sorted list with meters` — security + performance merged: critical first, the timing gap item first among warnings; each row shows the category (`Security` / `Performance`), title, description, evidence in `code`, and a meter from `confidence` (`—` when absent); more than 5 → `Show all (7)` reveals the rest.
- `hosted summary` — heading `Where it's hosted`; `Measured from <vantage>`; DNS shows queried name and final CNAME target; `Answered by` shows the sample `peer_ip` and the seam sentence for each status (texts as today); Route shows `<n> hops` + edge city + edge RTT, or `Not traced` + the traceroute error message; two `details` (`Map and hop list`, `Raw response headers`) closed by default and containing the existing DNS panel/geomap/hop ladder/narration and raw drawer.
- `degraded and failed reports keep evidence and vantage` — degraded fixture → heading `No verdict`, detail with the reason, a `Re-run` button, no `[role=img][aria-label^="Confidence"]` anywhere, measured + hosted sections present, `Measured from` shown; an `error` report with `error:"no successful samples collected"` → `Analysis failed` + that text + `Re-run`.

- [ ] **Step 2: Run** `npx vitest run src/views/report` — Expected: FAIL.

- [ ] **Step 3: Implement.** Findings rows as in the reference (severity word coloured: critical `--crit`, warning `--miss`, info `--lo`; category under it in `--lo`). Hosted route summary: hop count = responsive hops; edge = last responsive non-private hop (`city`, `rtt_ms`).

- [ ] **Step 4: Run** `npx vitest run && npx tsc -b` — Expected: PASS, clean.

---

### Task 6: Launch

**Files:**
- Modify: `frontend/src/views/Launch.tsx`, `frontend/src/api/client.ts` (`ListFilters.limit?: number` → `limit` query param), `index.css`
- Test: `frontend/src/views/Launch.test.tsx`

**Interfaces:**
- Consumes: `TopBar`, `ConfidenceMeter`, `servedPhrase`, `listAnalyses({ limit: 5 })`.

- [ ] **Step 1: Update/write the failing tests:** existing POST-body tests switch the button name to `Analyze` (body unchanged); `heading and quiet model line` — heading `Which layer serves this page?`, `Read by` with provider + model selects (labels `Provider`, `Model` still accessible), and the 1.0.1 live-list filter still appears for > 15 models; `more options disclosure` — closed by default, contains Requests, Interval (ms), warm, `Cache-bust probe (forced miss)`, Geo hint, custom headers; `recent list` — `listAnalyses` called with `{ limit: 5 }`; rows show URL, served phrase, meter (or `—` for degraded), and link to `/reports/:id`; no `Recent` heading when the list is empty.

- [ ] **Step 2: Run** `npx vitest run src/views/Launch.test.tsx` — Expected: FAIL.

- [ ] **Step 3: Implement** per `docs/design/views.html` (launch screen).

- [ ] **Step 4: Run** `npx vitest run && npx tsc -b` — Expected: PASS.

---

### Task 7: Live run

**Files:**
- Modify: `frontend/src/views/LiveRun.tsx`, `index.css`
- Test: `frontend/src/views/LiveRun.test.tsx`

**Interfaces:**
- Consumes: `TopBar`, `cancelAnalysis` (Task 2), existing `subscribeAnalysis`.

- [ ] **Step 1: Update/write the failing tests:** keep the reducer/reconnect/terminal-navigation tests, re-targeted to the new markup; `steps in order` — `Look up DNS`, `Warm the cache`, `Request the page 3×` (N from router state, else non-probe sample count), `Force a miss` only when the probe sample arrives, `Trace the route`, `Read the evidence`; `inline measurements` — DNS completed shows the last CNAME target and address count; samples completed shows `Age <first> → <last>` and status; probe shows its Age and `ms to first byte`; traceroute shows `<n> hops`; failed traceroute shows its message in an amber (`.fail`) step; `raw headers disclosure` — `Show raw headers` reveals request 1's headers; `cancel` — clicking `Cancel` calls `cancelAnalysis("rep-1")` then navigates to `/reports/rep-1`.

- [ ] **Step 2: Run** `npx vitest run src/views/LiveRun.test.tsx` — Expected: FAIL.

- [ ] **Step 3: Implement** per `docs/design/views.html` (live-run screen). The active step's pulse animation is named `step-pulse` and disabled under `prefers-reduced-motion`; keep `data-testid="stepper"` on the step list.

- [ ] **Step 4: Run** `npx vitest run && npx tsc -b` — Expected: PASS.

---

### Task 8: History

**Files:**
- Modify: `frontend/src/views/History.tsx`, `index.css`
- Test: `frontend/src/views/History.test.tsx`

**Interfaces:**
- Consumes: `TopBar`, `ConfidenceMeter`, `servedPhrase`.

- [ ] **Step 1: Update the failing tests:** keep filter/URL-mirroring, permalink, delete-confirm and empty-state tests on the new markup (`data-testid="history-table"` stays on the list); `columns` — headers `Page`, `Served from`, `Confidence`, `Findings`, `When`; a cached row shows the served phrase and a meter labelled with its confidence; a degraded row shows `No verdict` and `—`; findings `2 critical` uses the crit colour class, warnings the warn class, none → `none`.

- [ ] **Step 2: Run** `npx vitest run src/views/History.test.tsx` — Expected: FAIL.

- [ ] **Step 3: Implement** per `docs/design/views.html` (history screen).

- [ ] **Step 4: Run** `npx vitest run && npx tsc -b` — Expected: PASS.

---

### Task 9: Cleanup, quality floor, screenshots

**Files:**
- Delete: components/CSS no longer used (expected: `Tile`, `ConfBar`, `DegradedBanner`, `Card` if unused, `views/report/icons.tsx` if unused, and their CSS); update `frontend/src/dev/Components.tsx` + test to show the current primitives (`Badge`, `Table`, `ConfidenceMeter`, `TopBar`)
- Modify: `frontend/e2e/{a11y,keyboard,reduced-motion,visual}.spec.ts`, `frontend/e2e/mocks.ts`; `docs/screenshots/launch.png` + report screenshots; `README.md` image references if names change
- Test: the e2e specs above

- [ ] **Step 1: Update the e2e specs:** axe clean on all four views; keyboard: tab to URL → Enter → stepper visible, tab to a history permalink → Enter → report; reduced motion: `step-pulse` → `none` under reduce; visual: report has `Where it's hosted` + `What the requests showed` at 1280 and 390, no horizontal page scroll; add `report with long values has no horizontal scroll at 390` (a mocked report whose layer names and header values are 120+ chars and 10 requests).
- [ ] **Step 2: Run** `npm run test:e2e` — Expected: the new/updated specs FAIL before cleanup only where selectors changed; fix markup/CSS until PASS.
- [ ] **Step 3: Delete dead code** (`grep` each candidate for imports first); `npx vitest run && npx tsc -b && npm run build && npm run test:e2e` — Expected: all PASS; colour-lint and contrast tests green.
- [ ] **Step 4: Refresh screenshots** of launch and a report (`/dev/report` with the updated fixture) at 1280 wide via a throwaway Playwright script outside the repo; replace the files referenced by `README.md`.

---

### Task 10: Eval before/after, real-browser check, progress, single commit

- [ ] **Step 1:** `make test` — Expected: backend and frontend PASS.
- [ ] **Step 2: Eval.** Before = the 1.2.0 result already recorded (both models chain ✗ on `persil-home` and `persil-home-timing`). Run `uv run --env-file ../.env python -m evals run --model anthropic:claude-opus-4-8 --model openrouter:openai/gpt-5` from `backend/`. Expected: serving ✓ unchanged; chain improves where the model now lists the origin. Record the table.
- [ ] **Step 3: Real browser.** Start `uvicorn` on `127.0.0.1:8000` (the Docker stack owns `localhost:8000`), run persil.de, open `/reports/<id>` and `/`, `/history` in a Playwright screenshot; check against the references by eye. Stop the server.
- [ ] **Step 4: progress.md** — session log `1.3.0 · minimal redesign`; decisions (references supersede the mockup's layout; strata replace chain + table; per-claim confidence fields; origin rule; cancel endpoint; seam visual retired; findings single list; recent list); fixture inventory (`akamaiReportLegacy`, long-values e2e mock).
- [ ] **Step 5: Commit once** on `minimal-redesign`: bump `backend/pyproject.toml` to `1.3.0` (+ `uv lock`), stage backend, frontend, `docs/design/`, `docs/screenshots/`, `README.md`, the spec and this plan; `git commit -m "feat: minimal story-first redesign + per-claim confidence (v1.3.0)"` with the Co-Authored-By trailer. Expected: no `.env`, `evals/runs/`, `progress.md`, `.superpowers/` staged.
