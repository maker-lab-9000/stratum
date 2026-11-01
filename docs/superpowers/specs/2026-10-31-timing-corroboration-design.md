# Timing corroboration & headline confidence — design

**Date:** 2026-10-31 · **Status:** draft, awaiting operator approval (builder-checked)

## Intent

In multi-CDN setups the outer CDN overwrites the inner one's headers
(persil.de: CloudFront → Fastly; unileverfoodsolutions.fr: Akamai → Fastly).
Today the verdict rests only on whatever headers leak through — e.g.
`server: CloudFront`, `x-cache: Miss from cloudfront`, plus a leaked
`x-served-by: cache-fra-…` and `server-timing: cdn-cache;dur=647`. The model has
to untangle several layers from one header set, and nothing independent checks
its reading.

This adds a **second, independent signal: HTTP-level timing**. If the response
came back as fast as an edge hit while the headers say an inner tier served it
(or as slow as a full origin trip while the headers say edge HIT), the report
points out the gap, says a hidden cache layer may exist, and carries the LLM's
confidence in that assumption. The verdict's overall confidence moves to a
headline line at the top of the report, with the reason it was lowered.

## Why timing, not traceroute hops

Traceroute follows the client's packets only to the **first** CDN edge, where
the TCP/TLS connection terminates. The outer CDN fetches from the inner one on
its own connection, which the client's packets never touch, so no hop can show
the inner tier. Inferring cache layers from hops stays forbidden (architecture
rule #4, spec §2 corollary). Timing measured on the **HTTP request** is
different: it reflects how deep the response came from, and is computed
deterministically from the client's own measurements.

## Goals

1. **Per-request timing split** in the sampler: TCP connect, TLS, time to first
   byte (TTFB), total — instead of one `elapsed_ms` that mixes connection setup
   into request 1.
2. **Peer IP** recorded per request (the IP the request actually connected to).
3. **One cache-bust probe** per run (the "forced-miss request", operator
   approved): the same URL with a random query parameter, to measure what a
   full trip to the origin costs.
4. **Deterministic timing arithmetic** in the bundle: edge round trip, estimated
   server-side time per request and its spread, the probe baseline, Age vs
   wall-clock deltas — numbers only, plus ready-to-cite fact strings.
5. **LLM timing assessment**: a `timing_check` in the verdict (status, summary,
   hidden-layer suspicion, confidence, cited timing facts) and a
   `confidence_reason` explaining the overall confidence.
6. **Report top (operator chose layout "C")**: a headline *Verdict confidence*
   line above the four tiles, with a bar and the reason when not high; an amber
   dashed **timing gap** tag on the affected tile; the full explanation as a
   finding card.

## Non-goals

- Inferring or adding cache layers from timing. `layers[]` and the topology
  chain stay header-derived; a suspected hidden layer appears only in
  `timing_check`, the tag, the confidence line, and the finding.
- Retargeting traceroute at the peer IP (would serialize traceroute after
  sampling). Instead the route/sample relationship is recorded (see *seam*).
- Request-header parity between the Playwright warmer and the sampler (separate
  problem; touches bot detection). Parked.
- Scoring `timing_check` in the eval corpus.
- A numeric 0–100 confidence. Confidence stays `high | medium | low`.
- Any new database column.

## Anti-goals

- **Timing overriding headers.** Timing qualifies confidence and raises a
  hidden-layer suspicion; it never flips a header-cited layer state or the
  serving layer.
- **Code interpreting timing.** No thresholds like "< 10 ms = edge hit" in code,
  and no interpretive words ("miss", "hit") in bundle keys — the existing
  `test_no_interpretation_keys_anywhere` guard stays as is. Code computes
  numbers; interpretation guidance lives only in the prompt (§2).
- **False gaps.** A timing difference within the measured noise is not a gap.
  Tiers too close to tell apart (same metro) are reported as such, not as a
  hidden layer.
- **Unverifiable timing claims.** Every timing claim cites a fact string that
  exists verbatim in the bundle.
- **Losing the verdict over the new fields.** A model that omits them gets
  defaults, not a degraded report.
- **Breaking old reports.** Reports without timing fields render exactly as
  before (no tag, confidence line from the existing `confidence`).

## Decided by the operator

- Purpose: an independent second signal for multi-CDN cases where headers are
  overwritten.
- On disagreement: point out the gap between what the headers say and what
  timing says, suggest a possible hidden cache layer, with the LLM's confidence.
- The confidence goes at the top of the report — layout **C**: one headline
  confidence line above the tiles stating what lowered it; a small "timing gap"
  tag on the affected tile; detail in the findings. This **replaces** the
  confidence bar on the Cached tile (a change to spec §8.1/§8.3 and the mockup,
  approved by the operator; the requirements doc and mockup are not edited —
  the decision is recorded in `progress.md`).
- The forced-miss (cache-bust) request is fine.

## Design

### 1. Sampler (`backend/app/collectors/http_sampler.py`)

Each sample gains (existing fields unchanged):

```json
"peer_ip": "18.64.119.98",
"timing": { "connect_ms": 38.2, "tls_ms": 41.0, "ttfb_ms": 79.5, "total_ms": 81.0 }
```

- Timing comes from httpcore's per-request `trace` extension (connect_tcp,
  start_tls, send_request_headers → receive_response_headers). `connect_ms` /
  `tls_ms` are `null` on requests that reuse the connection (normally requests
  2…N and the probe, over one HTTP/2 client). `ttfb_ms` = from sending request
  headers to receiving response headers. `total_ms` mirrors today's
  `elapsed_ms` (kept for compatibility).
- `peer_ip` from the response's network stream (`server_addr`); `null` if
  unavailable.
- **Cache-bust probe:** after the N samples, one more GET on the same client to
  the URL with `stratum-cb=<random hex>` appended to the query (preserving any
  existing query). Recorded as an extra sample entry with `"probe": "cache_bust"`
  and the same fields. Controlled by a new option `cache_bust_probe` (default
  `true`). A probe failure never fails the run.
- The probe lives in `samples_json` (no schema change). Every consumer that
  means "the N requests" excludes entries with a `probe` key: bundle
  progression, the orchestrator's "no successful samples" check, the evidence
  index for verdict claims (§4), `sample_states`, the progression table's
  request columns, the eval capture's 2xx warning.

### 2. Bundle (`backend/app/pipeline/bundle.py`)

`progression` gains `wall_deltas_s` (seconds between consecutive request
starts, from `started_at_ms`) next to `age_deltas`. A new top-level `timing`
section, arithmetic only:

```json
"timing": {
  "edge_rtt_ms": 38.2,
  "requests": [ { "request": 1, "ttfb_ms": 79.5, "server_ms": 41.3 }, … ],
  "server_ms_spread": { "min": 2.1, "median": 3.4, "max": 6.0, "count": 3 },
  "cache_bust": { "ttfb_ms": 450.7, "server_ms": 412.5, "status": 200 },
  "facts": [
    "edge_rtt_ms: 38.2",
    "request 1 ttfb_ms: 79.5", "request 1 server_ms: 41.3", …,
    "warm server_ms min: 2.1", "warm server_ms median: 3.4", "warm server_ms max: 6.0",
    "cache_bust ttfb_ms: 450.7", "cache_bust server_ms: 412.5", "cache_bust status: 200"
  ]
}
```

- `edge_rtt_ms` = the first non-null `connect_ms` (one TCP handshake ≈ one
  round trip to the IP that answered). `server_ms` = `ttfb_ms − edge_rtt_ms`
  (may be slightly negative from jitter; kept as computed, rounded to 0.1).
  Any input missing → `null`, and the fact is omitted.
- `server_ms_spread` covers requests 2…N (reused connection — the comparable,
  warm ones); omitted when fewer than 2 such values. It is the noise yardstick.
- `facts` are the exact strings the model cites (format above, fixed).
- **Seam** — stored inside the bundle's `traceroute` section as
  `"seam": {"status", "traced_ip", "peer_ips"}`, so it persists in
  `traceroute_json` with no new column (the UI reads it from there):
  - `traced_ip` = last responsive, non-private hop IP; `peer_ips` = distinct
    sample `peer_ip`s (probe excluded).
  - `confirmed` — `traced_ip` ∈ `peer_ips`.
  - `different_edge` — `traced_ip` ∉ `peer_ips` but ∈ the DNS A/AAAA records
    (the trace reached another server for the same hostname).
  - `unconfirmed` — anything else (trace stopped short, no peer IP, no route).
  - Only `different_edge` adds a `meta.gaps` entry (`stage: "seam"`).

### 3. LLM output (`app/llm/schema.py`, `app/llm/prompt.py`)

`cache_verdict` gains two fields, **optional with defaults** so a model that
omits them never loses the verdict:

```json
"confidence_reason": "string (default \"\")",
"timing_check": {
  "status": "consistent|gap|insufficient",
  "summary": "string",
  "hidden_layer_suspected": false,
  "confidence": "high|medium|low",
  "evidence": ["string"]
}
```

A missing `timing_check` becomes `{status: "insufficient", summary: "",
hidden_layer_suspected: false, confidence: "low", evidence: []}` and the
validator flags it (`cache_verdict.timing_check`, "not provided"). The prompt's
schema block shows both fields so capable models fill them.

Prompt additions (all interpretation lives here):

- What the timing fields mean: `server_ms` ≈ time spent behind the edge; the
  cache-bust `server_ms` is the cost of a full trip to origin; the warm
  `server_ms` spread is measurement noise.
- Guidance, not thresholds: an outermost-edge hit typically shows server time of
  a few ms; each cache tier behind the edge adds roughly one inter-tier round
  trip (small when tiers share a metro, larger across regions); a full miss adds
  origin generation time (compare against the cache-bust baseline). Check the
  probe's own response headers — if the cache ignored the query string, the
  probe isn't a full origin trip and the baseline is unusable.
- **Noise rule:** call a `gap` only when the difference between what the headers
  imply and what timing shows clearly exceeds the warm spread. If tiers are
  plausibly too close to separate (e.g. same metro), say so in `summary` with
  status `consistent` — never suspect a hidden layer from a difference inside
  the noise.
- `gap` examples: headers say an inner tier/origin served, but server time ≈
  edge-hit speed and far below the cache-bust baseline → `hidden_layer_suspected:
  true`; or headers say edge HIT but server time ≈ the cache-bust baseline.
  Lower `confidence` accordingly and say why in `confidence_reason`.
- `insufficient` when timing can't be trusted: no timing facts, probe
  failed/blocked/non-2xx, samples are block pages/redirects.
- `timing_check.evidence` must include the timing facts it rests on, copied
  verbatim from `timing.facts`; it may also cite headers (e.g. the probe's).
- Timing never adds, removes, or re-states layers and never changes
  `serving_layer`. Layer/sample/provider/finding citations stay header/DNS/ASN
  evidence. Still forbidden: inferring layers from traceroute hops.

### 4. Validator (`app/pipeline/validator.py`)

Still existence-only and vendor-agnostic (the source guard test applies).

- **Probe excluded from the claim index:** headers of `probe` samples are not
  indexed for layers, sample states, provider, or findings.
- **Timing facts are an exact-match set**, kept separate from the loose index
  (not added to it, so loose matching can't accept a fabricated number).
- **`timing_check.evidence`:** passes when it contains ≥ 1 citation that is
  exactly (after trimming) a string in `timing.facts`, **and** every citation
  that *looks like* a timing fact (`<label> <field>_ms…: <number>` shape, or any
  citation starting with `edge_rtt_ms`, `request <n> `, `warm server_ms`,
  `cache_bust `) is an exact fact; other citations are checked against the loose
  index **including** probe headers. Failure → `status: "insufficient"`,
  `hidden_layer_suspected: false`, flag `cache_verdict.timing_check`.
- **Keeping the headline honest:** whenever the validator lowers `confidence`
  (existing serving-layer cascade) or resets `timing_check`, it appends a fixed
  note to `confidence_reason`, e.g. ` · citation check: serving-layer evidence
  not found in the captured data` / ` · citation check: timing evidence not
  found — timing assessment discarded`. (Fixed text, no vendor names.)

### 5. API / launch

- `AnalysisOptions.cache_bust_probe: bool = True`; Launch view "Advanced" gets a
  checkbox **"Cache-bust probe (forced miss)"** beside "Warm"; re-run uses the
  default.

### 6. Report UI (frontend)

- **Verdict confidence line** (new component above `.verdict` tiles):
  `VERDICT CONFIDENCE · Medium` + `ConfBar` + `confidence_reason` (shown when
  non-empty). An `unverified` badge when the reason includes a validator note.
  Hidden when the verdict is degraded (the degraded banner covers it). Old
  reports: level from `confidence`, no reason.
- **Remove the `ConfBar` from the Cached tile.**
- **Timing-gap tag:** when `timing_check.status == "gap"`, the Served-from tile
  shows an amber dashed tag `timing gap` (new `Badge` variant — shared
  primitives remain the only way to render it; amber = anomaly per palette
  rules).
- **Finding card:** when status is `gap`, a Performance finding card rendered
  from `timing_check` (severity warning, title "Timing doesn't match the
  headers", the summary, `LLM confidence · <level>`, cited facts in monospace),
  first among warnings. When `consistent`/`insufficient` with a non-empty
  summary, an info card.
- **Progression table:** two verbatim numeric rows from the samples — `TTFB` and
  `Server time` (computed from `samples_json` the same way as the bundle, never
  from LLM output); the probe appears as a distinct trailing column labelled
  `cache-bust` when N ≤ 6, else as a one-line note under the table.
- **Raw drawer:** the probe gets its own tab, `Cache-bust probe`.
- **Measurement seam** reads `traceroute_json.seam`: `confirmed` (or absent, old
  reports) → today's text; `different_edge` → says the route reached another
  server for this hostname, so the hops describe a sibling edge, not the one
  that served the headers; `unconfirmed` → says the trace didn't reach the
  serving IP, so the seam is inferred, not measured.

### 7. Eval corpus

No scoring change. Capture and replay keep working: probe entries pass through
verbatim; old cases simply lack timing (`timing_check` → `insufficient`). The
"no sample returned 2xx" warning ignores probe entries. The fake LLM (e2e)
emits a schema-valid `timing_check` (`insufficient`) and `confidence_reason`.

### 8. Verification on real data

After the build: run persil.de locally (same way as the eval seed), capture it
as a **new** case `persil-home-timing` with the same answer key as
`persil-home`, run the eval, and read `timing_check` by eye. Expected: serving
Fastly as before, and `timing_check` either `consistent` (with a note if the
tiers are too close to separate — CloudFront `TXL` (Berlin) vs Fastly `FRA`) or
`insufficient` — **not** a hidden-layer `gap` unless the numbers clearly exceed
the warm spread. A false gap here means the prompt's noise rule needs work
before merge. (UFS sites are excluded: Akamai blocks the sampler from this
machine.)

## Calls made by the designer (not operator decisions)

- Hidden layer is **not** added to `layers[]`/the chain — it has no header
  evidence; it lives in `timing_check` and the UI elements above.
- Probe stored inside `samples_json` with a `probe` marker (no DB migration —
  the app creates tables on boot and has no migrations, so a new column would
  break existing SQLite deployments).
- Code/bundle name **`cache_bust`** rather than "forced miss" (the probe may not
  truly miss; "miss" in bundle keys would break the interpretation guard). The
  UI label keeps the operator's wording: "Cache-bust probe (forced miss)".
- `cache_bust_probe` on by default; the operator can turn it off per run.
- Edge RTT from the TCP connect time (works without traceroute privileges).
- **Noise guard:** warm `server_ms` spread in the bundle + a prompt rule that a
  gap must clearly exceed it; same-metro tiers reported as indistinguishable.
- New verdict fields optional with defaults (a missing `timing_check` is
  flagged, not fatal).
- Validator: exact-match timing facts, probe headers excluded from claim
  evidence, deterministic notes appended to `confidence_reason` when it lowers
  confidence or discards the timing assessment.
- Seam three-state stored in `traceroute_json.seam`; only `different_edge`
  becomes a gap.
- Default `interval_ms` unchanged; `wall_deltas_s` makes Age deltas readable at
  any interval.

## Left to the builder

- Exact trace-event wiring and rounding; how `peer_ip` is read for HTTP/1.1 vs
  HTTP/2.
- Visual details of the confidence line and tag within the mockup's tokens and
  class vocabulary.
- Where the probe note sits when N > 6.
- Test fixtures (reuse `RawHTTPServer`, golden bundle — regenerate the golden
  bundle snapshot for the new `timing` / `wall_deltas_s` / `seam` fields).
