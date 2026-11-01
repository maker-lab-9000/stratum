# Eval corpus

Checks Stratum's LLM verdict against reality. Each **case** is one real report
frozen in time (its DNS records, response headers and traceroute hops, copied
verbatim) plus an optional **answer key** you write from inside knowledge of the
setup. The eval replays every case through the *current* prompt and any number
of models, then prints expected vs actual **serving layer** and **chain**.

Because the evidence is frozen, a score change means the prompt or the model
changed — not the site. Cases without an answer key ("observed" cases) still
run: their rows show each model's reading of the caching layers with no score,
which is how you use the tool on setups you don't know yet.

Design: `docs/superpowers/specs/2026-10-31-eval-corpus-design.md`.

## 1. Capture a case

Run the URL in Stratum as usual (homelab Docker or local), then freeze that
report. From the repo root:

```bash
make eval-capture REPORT=http://homelab:8000/reports/<id> NAME=persil-checkout
```

- Accepts `…/reports/<id>`, `…/runs/<id>` or `…/api/analyses/<id>`.
- Auth: put `user:pass@` in the link, or set `BASIC_AUTH_USER` /
  `BASIC_AUTH_PASS` in `.env`. Credentials are never written to the case file.
- Only finished (`done`) reports with at least one successful sample. A report
  whose LLM step failed (degraded) is fine — the evidence is intact.
- Case names are `[a-z0-9-]+`. Existing case files are never overwritten;
  delete the file to re-capture.

The case lands in `backend/evals/cases/<name>.json` with `"expected": null`.

## 2. Write the answer key (optional)

Edit `"expected"` in the case file. Both parts are optional and scored
independently:

```json
"expected": {
  "serving": { "label": "Akamai edge", "match": ["akamai"], "role": ["edge"] },
  "chain": [
    { "label": "Akamai edge",    "match": ["akamai"], "role": ["edge"] },
    { "label": "Akamai parent",  "match": ["akamai"], "role": ["shield"] },
    { "label": "AEM dispatcher", "match": ["dispatcher"] },
    { "label": "AEM origin",     "role": ["origin"] }
  ],
  "notes": "Free text for humans."
}
```

Each entry is a **layer spec**:

| Field | Meaning |
|---|---|
| `label` | Required. What the expected row shows. |
| `match` | Keywords; matches if **any** is a case-insensitive substring of the model's `layer_name`, `vendor` and `cache_type` joined. |
| `role` | Allowed roles: `client`, `edge`, `shield`, `security`, `load_balancer`, `reverse_proxy`, `app_cache`, `origin`, `unknown`. |
| `optional` | Chain entries only. The model may omit this layer without failing. |

At least one of `match` / `role` is required; if both are given, both must hold.
Matching never depends on exact names, so "Fastly shared cache" and "Varnish
tier" both satisfy `"match": ["fastly", "varnish"]`. Use `role` to tell apart
two layers of the same vendor (edge vs parent).

An answer key describes **this frozen moment**. If the captured headers show
the edge missing on every request, the serving layer for that case is not the
edge — re-run the analysis to capture a warm moment, or label what the evidence
actually shows.

## 3. Run

```bash
make eval MODELS="anthropic:claude-opus-4-8 openrouter:openai/gpt-5"
```

or, from `backend/`:

```bash
uv run --env-file ../.env python -m evals run --model anthropic:claude-opus-4-8 --case ufs-home
```

- `--model` is `provider:model`, split on the first colon (`openrouter:meta-llama/x:free` works).
  Every provider needs its API key in `.env`; otherwise nothing runs.
- Calls go through the production path (JSON retry, rate-limit backoff, and the
  citation validator), one at a time. Cost = cases × models calls.
- Output: per case an `expected` row and one row per model. `✓`/`✗` appear only
  where an expectation exists; `⚠ N unverified` means N citations failed the
  validator; `degraded: …` means the model call failed. The chain ends with the
  model's own count of caching layers (shown, not scored).
- Scores count only cases that define that part of the answer key.
- Full results (every verdict) go to `backend/evals/runs/<timestamp>.json`
  (git-ignored), including a hash of the system prompt used.

## Investigate mode (1.4.0, experiment)

```bash
make eval MODELS="anthropic:claude-opus-4-8" INVESTIGATE=1
```

Every case then runs twice per model: the frozen replay as above, and a row
labelled `<model> +investigate` where the model may call `request_page` up to
5 times. **Those rows make live requests to the case's URL** (the one place the
eval touches a target). Cases store no custom request headers, so the live
calls carry only the model's; a case captured behind a cookie or User-Agent
may compare against a different page — leave such cases out (`--case`) or
recapture them without custom headers. The note column shows `live · N req ·
T tok`; the results file keeps every tool call (`tool_calls`) and the extra
samples. Case files are never modified.

## Scoring rules

- **Serving ✓** — the layer the report would flag as serving (the layer named
  by `serving_layer`, else the first `HIT`) matches `expected.serving`.
- **Chain ✓** — the model's layers (excluding `client`), in order, line up
  one-to-one with `expected.chain`; optional entries may be skipped. A layer the
  model reports that you didn't list fails the chain (add it as `optional` if it
  doesn't matter).

## Limits

Reports store DNS, samples and traceroute, not the exact bundle the model saw.
Replays rebuild it from those, so the browser warm-up timing and the run options
(request count, interval, extra request headers) are missing. Neither feeds the
serving-layer or chain verdict.
