# Minimal, story-first redesign + per-claim confidence — design

**Date:** 2026-11-01 · **Status:** draft, awaiting operator approval (builder-checked)

## Intent

The report has the right evidence but no story: a lot of text in boxes, in an
order that starts with the network route instead of the answer. The operator
wants a clear story to follow, a more minimal look, the model's confidence
impossible to miss, and a confidence meter next to **every** claim the model
makes. The same minimal look applies across the whole app (launch, live run,
history), so it reads as one product.

## Approved visual references (committed)

- `docs/design/report-strata.html` — the report (approved "v4").
- `docs/design/views.html` — launch, live run, history (approved "v2").

These supersede `cache-report-mockup.html` for **layout and structure** of all
four views. The mockup's `:root` tokens (colours, fonts) and the status-palette
rules stay normative. (`cache-report-mockup.html`, `stratum-requirements.md`,
`stratum-action-plan.md` are not edited; the deviation is recorded in
`progress.md`.)

## Decided by the operator

- Story order with the serving layer before the network route; a more minimal
  look; confidence meter more evident; a meter beside every model claim.
- The layer bands replace the layer table completely.
- Consistent look across launch, live run, report and history.
- Approved references: `docs/design/report-strata.html`, `docs/design/views.html`.
- Add the prompt rule "always list the origin as the last layer".

## Goals

1. **Report tells one story, top to bottom:** the answer → how the request was
   served → what the requests showed → what to look at → where it's hosted.
   (Operator: serving layer before network route.)
2. **Confidence is the loudest element after the verdict:** a large three-bar
   signal meter next to the headline.
3. **Every model claim carries its own confidence meter:** each layer, the
   provider, the timing assessment, each finding, and each row in history /
   recent lists.
4. **The layer bands ("strata") replace both the topology chain and the
   layer-by-layer table** (operator decision).
5. **One consistent, minimal look across launch, live run, report and history.**

## Non-goals

- New colours or fonts. Tokens and font roles stay as in the mockup.
- Changing what's measured, the pipeline, the eval corpus scoring, or the DB
  schema.
- Removing information. Everything reachable today (DNS panel, map, hop
  ladder, segment narration, raw headers, findings, progression rows,
  validation/unverified tags, degraded banner, re-run) stays reachable — it is
  re-ordered and folded, not dropped.
- A numeric confidence scale. Levels stay `high | medium | low`.

## Anti-goals

- **Faked confidence.** A claim the model didn't rate shows `—`, never a
  default "Low". A degraded report shows no confidence at all.
- **Palette drift.** Green = served from cache only; amber = anomaly/warning;
  red = critical; blue = structure and confidence meters; dashed grey =
  unknown. An origin that serves (nothing cached) is blue, never green.
- **Vendor logic in code.** Any vendor wording in the UI comes from the model's
  own fields (`vendor`, `layer_name`, `provider`), never from code that reads
  headers.
- **Losing the accessibility floor.** Keyboard operable, visible focus,
  `prefers-reduced-motion`, the contrast audit and axe checks stay green; every
  meter has an accessible text equivalent.
- **Breaking old reports.** Reports without the new fields render with
  fallbacks (below).

## Visual language (all views)

- Tokens unchanged (`--bg #0e1419`, `--panel #151d25`, `--line #26323d`,
  `--hi/--mid/--lo`, `--accent #5b9df0`, `--hit #54d98c`, `--miss #f0b34a`,
  `--crit #f4736b`). Space Grotesk for headings, verdict and layer names;
  system sans for prose; JetBrains Mono **only** for URLs, header values, IPs
  and measured numbers.
- Minimal: content separated by whitespace and single hairlines, not boxes.
  Sentence-case headings, no all-caps eyebrow labels, no numbered section
  markers, no strings joined with middle dots in UI copy.
- **One shared top bar** on every view: `Stratum` on the left; page context in
  the middle (report: URL + "read by <model>" + time; live run: URL); on the
  right the nav (`New analysis`, `History`) and the page action (report:
  `Re-run`).
- **One shared confidence meter primitive** (`ConfidenceMeter`): three
  ascending bars, filled in `--accent` (high 3, medium 2, low 1); sizes `lg`
  (headline) and `sm` (inline); `level = null` renders `—`. Always paired with
  the word (High / Medium / Low) and an `aria-label` ("Confidence: high").
  Replaces `ConfBar`.

## Report (top to bottom)

1. **The answer.**
   - Headline: the model's new `headline` (one sentence naming the layer that
     served the page) in large display type, with `headline_detail` (one
     sentence of context) beneath it in `--mid`.
   - Beside it (right on desktop, below on mobile): the `lg` meter, the word
     "High/Medium/Low confidence", and `confidence_reason` in small text when
     non-empty (with an `unverified` badge when it contains a citation-check
     note, as today).
   - Under the headline: `overall_summary` as the "why" paragraph.
2. **The strata** — the request's path as stacked bands, from a "You, in
   <vantage>" marker at the top down to the origin:
   - One band per layer (excluding `role: client`), in order. Each band: layer
     name (`vendor` or `layer_name`), role in words + optional `location`, the
     state in words, the layer's cited evidence (verbatim, mono, one per
     line), and the layer's `sm` meter.
   - Band kinds come from the existing `classifyLayers` (`serving.ts`), never
     re-derived from headers: **served** (green left rule + green dot where the
     drop line stops; state "Hit, served the page"); **served-origin** (same
     treatment in accent blue; "Served by the origin, nothing cached");
     **passthrough** ("Miss, passed the request on"); **forwards** ("Forwards
     without caching"); **unknown** (dashed grey; "Unknown"); **not reached**
     (hatched, dimmed; "Not reached").
   - Per-layer `unverified` tag when that layer has validation flags (as today).
   - **Origin always listed (operator decision):** the prompt gains the rule
     "always list the origin as the last layer" — `role: origin`, state
     `UNKNOWN` (rendered "Not reached") when a cache served the page. **Safety
     net** if a model still omits it: the strata end at the last listed layer
     with a one-line note "The model didn't list the origin layer." Code never
     invents a layer.
   - If no layer resolves as serving (`classifyLayers` returns -1) and
     `cached` is false, the bands render as listed and the headline fallback
     says "Not cached. The origin served it." — no green or blue serving
     marker is drawn on a layer the model didn't name.
3. **Two claim rows** under the strata, each with an `sm` meter:
   - **Delivered by:** `provider`, plus a short note of what it rests on (first
     `provider_evidence` item), meter from `provider_confidence`.
   - **Timing:** from `timing_check` — "Agrees with the headers" (consistent),
     "Doesn't match the headers" (gap: amber text + the existing `timing gap`
     badge), "Not enough timing data" (insufficient); `summary` in small text;
     meter from `timing_check.confidence` for `consistent` / `gap` only —
     `insufficient` shows `—` (no assessment was made; the validator's default
     "low" is not a rating). Hidden for reports without `timing_check`.
4. **What the requests showed** — the existing progression table restyled as a
   plain table: request columns (+ the cache-bust column / note), verbatim rows
   (Age, Cache-Control, Via, Time to first byte, Time behind the edge), and the
   model's per-request reading (`sample_states`) as its own first row,
   labelled as the model's reading. The N > 6 strip rule stays. A one-line note
   gives the edge round trip.
5. **What to look at** — findings as **one list** (security and performance
   together), sorted critical → warning → info; each row: severity word
   (coloured), category in `--lo` under it, title, description, evidence
   (mono), and the finding's `sm` meter. The timing card (gap / info) joins
   this list as today. First 5 shown, then "Show all (N)".
6. **Where it's hosted** — opens with "Measured from <vantage>" (always shown,
   including degraded and failed reports — §10 vantage disclosure), then a
   three-item summary: **DNS** (queried name → final
   CNAME target), **Answered by** (sample `peer_ip`, else the edge hop IP) with
   the seam sentence (confirmed / different edge / unconfirmed, as today),
   **Route** (hop count + edge city + edge RTT, or "Not traced" + reason). Two
   disclosures, closed by default: **Map and hop list** (existing DNS panel,
   geomap, hop ladder, segment narration) and **Raw response headers**
   (existing drawer).

**Degraded report** (`verdict_json.status == "unavailable"`): headline "No
verdict", detail "The model couldn't read the evidence: <reason>.", a
`Re-run` button in place of the meter; strata and claim rows hidden; sections
4–6 render normally (findings section hidden — there are none).

**Failed report** (`status == "error"`, e.g. no successful samples or
cancelled): headline "Analysis failed", detail = the report's `error`, a
`Re-run` button; sections 4–6 render whatever evidence was persisted.
A report still `queued`/`running` opened at `/reports/:id` keeps today's
behaviour.

**Old reports (no new fields):** headline falls back to a sentence built from
verdict fields — cached: "Served from <serving layer>."; not cached: "Not
cached. The origin served it."; no `headline_detail`. Missing per-layer /
per-finding / provider confidence → `—`. Missing `location` → role only.

## Launch

As in `views.html`: heading "Which layer serves this page?", one-line
explanation, a wide URL field with an **Analyze** button, a quiet "Read by
<provider> <model>" line (the live model list and its filter for long lists —
1.0.1 behaviour — must survive), and a **More options** disclosure holding the
existing advanced fields (requests, interval, warm, cache-bust probe, geo hint,
custom headers). Below: **Recent** — the last 5 analyses
(`GET /api/analyses?limit=5`): verdict dot, URL, short "served from" phrase,
confidence meter (or `—`), time; each row opens the report; hidden when empty.

## Live run

As in `views.html`: heading "Analyzing…", one line of explanation, then a
vertical list of steps on a thin spine: **Look up DNS**, **Warm the cache**,
**Request the page N×** (one step — the stream reports the sample stage as a
whole), **Force a miss** (only when the probe ran / is enabled), **Trace the
route**, **Read the evidence**. Each finished step shows its key measurement
inline, from verbatim data only (e.g. final CNAME + address count; warm load
time; status + Age first → last; probe status + Age + time to first byte; hop
count + last hop IP; "<model> is reading N responses…"). Failed / skipped steps
are amber with the reason. A **Show raw headers** disclosure under the request
step keeps "evidence as it lands" (spec §8.1.2). Reconnect note, idempotent
reducer and terminal → report navigation are unchanged. A **Cancel** action in
the top bar (it is in the approved reference) calls a new
`POST /api/analyses/{id}/cancel`: it cancels the running job through the
existing manager cancel path, the report ends `error` / "cancelled" with the
evidence persisted so far, and the view navigates to that report. Cancelling a
finished report is a no-op (200, unchanged). Reduced motion: the active-step
pulse is disabled under `prefers-reduced-motion` (the T23 reduced-motion test
moves to the new step markup).

## History

As in `views.html`: heading, domain filter, "Only with critical findings"
checkbox (both still URL-mirrored), and a quiet list with columns: verdict dot,
page, served from (short phrase), confidence (`sm` meter + word, `—` when
degraded), findings (critical count in red, warnings in amber, else "none"),
when. Row opens the report (permalink); inline delete-with-confirm stays,
keyboard-reachable.

**Short "served from" phrase** (launch recent + history), built only from
verdict fields: the serving layer's `vendor` (else `layer_name`), plus
`, behind <first layer's vendor>` when the serving layer isn't the first layer
and that vendor differs; "Origin" when the serving layer's role is origin;
"No verdict" when degraded.

## Model output changes (backend)

New **optional** fields (defaults keep old outputs valid; malformed values are
coerced, never cost the verdict — same pattern as `timing_check`):

| Field | Type | Meaning |
|---|---|---|
| `cache_verdict.headline` | string, default "" | One sentence naming the layer that served the page (≤ ~70 chars). |
| `cache_verdict.headline_detail` | string, default "" | One sentence of context (e.g. what the outer layer did). |
| `cache_verdict.provider_confidence` | `high\|medium\|low` or null | Confidence in the provider identification. |
| `cache_verdict.layers[].confidence` | `high\|medium\|low` or null | Confidence in that layer's identification and state. |
| `cache_verdict.layers[].location` | string, default "" | City/PoP only when a captured header or hop names it. |
| `security_findings[].confidence`, `performance_findings[].confidence` | `high\|medium\|low` or null | Confidence in the finding. |

Prompt: add the fields to the schema block; one short section saying what each
confidence rates, that `UNKNOWN`/low is preferred to guessing, that `headline`
must name the serving layer (or say nothing is cached) and must not contradict
the verdict, and that `location` must come from a captured value. Plus the
operator-approved rule: **always list the origin as the last layer**
(`role: origin`; state `UNKNOWN` when a cache served the page), which also
changes eval chain results — re-run `make eval` and record the before/after.

Validator (still existence-only, vendor-agnostic):
- A layer whose citation fails (already → `UNKNOWN`) also gets
  `confidence: "low"`.
- Failed `provider_evidence` (already → provider `UNKNOWN`) also sets
  `provider_confidence: "low"`.
- A finding whose `Name: value` citation fails (already flagged) also gets
  `confidence: "low"`.
- `headline` / `headline_detail` / `location` are prose and not validated.

Fake LLM (e2e) emits all new fields.

## Constraints

- No new dependencies; no DB schema changes. API changes: the optional model
  fields (inside existing JSON columns) and `POST /api/analyses/{id}/cancel`.
- Shared primitives remain the only way to render shared patterns (`Badge`,
  `Table`, new `ConfidenceMeter`, new `TopBar`); remove CSS and components
  that become unused (tiles, topology chain, layer table, old stepper) rather
  than leaving dead code.
- All existing behaviour tests are updated to the new structure; the T23
  quality floor (axe on all four views, keyboard paths, reduced motion,
  contrast audit, no horizontal page scroll at 1280 / 390) must pass.
- README screenshots refreshed (launch + report) to match.
- One commit; `progress.md` session log + decisions (layout supersedes the
  mockup; per-claim confidence fields; strata replace chain + table; no cancel
  in live run).

## Calls made by the designer (not operator decisions)

- Headline written by the model (`headline` / `headline_detail`) with a
  constructed fallback, rather than code-generated prose.
- Optional `layers[].location`, shown only when the model provides it.
- Findings as one list with a category label, instead of two columns.
- `sample_states` kept as the first row of the measured table, labelled as the
  model's reading (it carries warm-up behaviour the strata can't show).
- The "Recent" list on launch (last 5).
- Live run: requests as one step; Cancel kept (approved reference) via a new
  cancel endpoint that keeps the report.
- The measurement-seam visual (spec §8.1.3 "signature element") is retired;
  its sentence lives in "Where it's hosted". The strata are the new signature
  element.
- Timing row shows `—` for `insufficient`; failed reports get an "Analysis
  failed" headline; vantage always shown in "Where it's hosted".

## Left to the builder

- Exact spacing, breakpoints and CSS within the approved references.
- Component boundaries inside `views/report/`.
- Wording of small helper copy not fixed above.
- How the README screenshots are captured.
