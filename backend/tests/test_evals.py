"""Eval corpus (docs/superpowers/specs/2026-10-31-eval-corpus-design.md).

Frozen real reports + optional operator answer keys, replayed through the
current prompt across several models. Everything here runs on fakes / respx —
no live network or LLM calls.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from evals.case import (
    CaseError,
    LayerSpec,
    load_case,
    load_cases,
    parse_case,
    rebuild_bundle,
)

GOLDEN = json.loads((Path(__file__).parent / "fixtures/bundle/golden_bundle.json").read_text())


def make_case_data(name: str = "golden", expected: dict | None = None) -> dict:
    """A valid case-file dict built from the golden bundle's evidence."""
    return {
        "name": name,
        "url": GOLDEN["meta"]["url"],
        "source": {
            "report_link": "http://localhost:8000/reports/r1",
            "report_id": "r1",
            "captured_at": "2026-10-31T12:00:00Z",
            "vantage": GOLDEN["meta"]["vantage"],
            "provider": "anthropic",
            "model": "m",
        },
        "evidence": {
            "dns": GOLDEN["dns"],
            "samples": GOLDEN["samples"],
            "traceroute": GOLDEN["traceroute"],
        },
        "original_verdict": None,
        "expected": expected,
    }


def write_case_file(directory: Path, data: dict, filename: str | None = None) -> Path:
    path = directory / (filename or f"{data['name']}.json")
    path.write_text(json.dumps(data))
    return path


# --- Task 1: case files -------------------------------------------------------

def test_parse_case_minimal_observed():
    case = parse_case(make_case_data())
    assert case.expected is None
    assert case.name == "golden"
    assert case.url == GOLDEN["meta"]["url"]


def test_parse_case_expected_specs():
    case = parse_case(make_case_data(expected={
        "serving": {"label": "Edge", "match": ["Akamai"], "role": ["edge"]},
        "chain": [
            {"label": "Edge", "match": ["akamai"]},
            {"label": "origin", "role": ["origin"], "optional": True},
        ],
        "notes": "n",
    }))
    assert case.expected.serving == LayerSpec("Edge", ("akamai",), ("edge",))
    assert case.expected.chain[1].optional is True
    assert case.expected.chain[0] == LayerSpec("Edge", ("akamai",))
    assert case.expected.notes == "n"

    only_serving = parse_case(make_case_data(expected={"serving": {"label": "O", "role": ["origin"]}}))
    assert only_serving.expected.chain is None
    assert only_serving.expected.serving.role == ("origin",)


_BAD_SPECS = {
    "missing-label": {"expected": {"serving": {"match": ["x"]}}},
    "neither-match-nor-role": {"expected": {"chain": [{"label": "x"}]}},
    "unknown-role": {"expected": {"serving": {"label": "x", "role": ["cdn"]}}},
    "optional-serving": {"expected": {"serving": {"label": "x", "role": ["edge"], "optional": True}}},
    "bad-name": {"name": "Bad Name"},
    "missing-evidence": {"evidence": None},
    # Final review fix: typos must not be silently ignored.
    "typo-optional": {"expected": {"chain": [{"label": "x", "role": ["origin"], "optinal": True}]}},
    "typo-chain": {"expected": {"chian": [{"label": "x", "role": ["origin"]}]}},
    "typo-match": {"expected": {"serving": {"label": "x", "mach": ["akamai"], "role": ["edge"]}}},
    "typo-expected": {"expectd": {"serving": {"label": "x", "role": ["edge"]}}},
    # Final review fix: malformed evidence is a load error, not a mid-run crash.
    "bad-sample-entry": {"evidence": {"dns": None, "samples": ["oops"], "traceroute": None}},
    "bad-headers": {"evidence": {"dns": None, "samples": [{"request": 1, "headers": "x"}], "traceroute": None}},
    "bad-traceroute": {"evidence": {"dns": None, "samples": [], "traceroute": ["hop"]}},
}


@pytest.mark.parametrize("override", list(_BAD_SPECS.values()), ids=list(_BAD_SPECS))
def test_load_case_errors_name_file(tmp_path, override):
    data = make_case_data("x")  # name matches the file stem, so each case fails for its own reason
    data.update(override)
    if data.get("evidence") is None:
        del data["evidence"]
    path = write_case_file(tmp_path, data, filename="x.json")
    with pytest.raises(CaseError, match="x.json"):
        load_case(path)


def test_load_case_invalid_json_names_file(tmp_path):
    path = tmp_path / "x.json"
    path.write_text("{not json")
    with pytest.raises(CaseError, match="x.json"):
        load_case(path)


def test_load_cases_sorted_and_filtered(tmp_path):
    write_case_file(tmp_path, make_case_data("b"))
    write_case_file(tmp_path, make_case_data("a"))
    assert [c.name for c in load_cases(tmp_path)] == ["a", "b"]
    assert [c.name for c in load_cases(tmp_path, names=["b"])] == ["b"]


def test_load_cases_unknown_name(tmp_path):
    write_case_file(tmp_path, make_case_data("a"))
    with pytest.raises(CaseError, match="nope"):
        load_cases(tmp_path, names=["nope"])
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(CaseError):
        load_cases(empty)


def test_load_case_name_must_match_filename(tmp_path):
    path = write_case_file(tmp_path, make_case_data("persil-home"), filename="persil-home-2.json")
    with pytest.raises(CaseError, match="persil-home-2.json"):
        load_case(path)


def test_load_cases_dedupes_names(tmp_path):
    write_case_file(tmp_path, make_case_data("a"))
    assert [c.name for c in load_cases(tmp_path, names=["a", "a"])] == ["a"]


def test_rebuild_bundle_preserves_evidence():
    bundle = rebuild_bundle(parse_case(make_case_data()))
    assert bundle["dns"] == GOLDEN["dns"]
    assert bundle["samples"] == GOLDEN["samples"]
    assert bundle["traceroute"] == GOLDEN["traceroute"]
    assert bundle["meta"]["vantage"] == GOLDEN["meta"]["vantage"]
    assert bundle["meta"]["url"] == GOLDEN["meta"]["url"]
    assert bundle["warm"] is None
    assert bundle["progression"] == GOLDEN["progression"]


# --- Task 2: scoring ----------------------------------------------------------

from evals.score import (  # noqa: E402
    actual_chain,
    chain_matches,
    evaluate,
    expected_texts,
    layer_matches,
    resolve_serving,
)


def L(name, role="edge", state="MISS", vendor="", cache_type="cache", caches=True):
    return {"layer_name": name, "vendor": vendor, "cache_type": cache_type, "role": role,
            "caches": caches, "state": state, "evidence_headers": ["x"]}


def V(layers, serving, count=1, flags=()):
    return {"cached": True, "confidence": "high", "provider": "p", "provider_evidence": [],
            "serving_layer": serving, "layer_count_to_origin": count, "layers": layers,
            "sample_states": [], "validation": {"ok": not flags, "flags": list(flags)}}


def spec(label="x", match=(), role=(), optional=False):
    return LayerSpec(label, tuple(match), tuple(role), optional)


def test_layer_matches_keyword_any_of():
    s = spec(match=("fastly", "varnish"))
    assert layer_matches(s, L("Inner tier", vendor="Varnish"))
    assert layer_matches(s, L("x", cache_type="Fastly shared cache"))
    assert not layer_matches(s, L("CloudFront edge", vendor="Amazon CloudFront"))


def test_layer_matches_role_and_both():
    assert layer_matches(spec(role=("shield",)), L("a", role="shield"))
    assert not layer_matches(spec(role=("shield",)), L("a", role="edge"))
    both = spec(match=("akamai",), role=("edge",))
    assert layer_matches(both, L("Akamai Edge", role="edge"))
    assert not layer_matches(both, L("Akamai Parent", role="shield"))


def test_resolve_serving_by_name_then_first_hit():
    a, b, c = L("A", state="MISS"), L("B", state="HIT"), L("C", state="HIT")
    assert resolve_serving(V([a, b, c], "C")) is c
    assert resolve_serving(V([a, b, c], "nobody")) is b
    assert resolve_serving(V([a], "nobody")) is None


def test_actual_chain_drops_client():
    client, edge, origin = L("Browser", role="client"), L("Edge"), L("Origin", role="origin")
    assert actual_chain(V([client, edge, origin], "Edge")) == [edge, origin]


_CF, _FASTLY, _ORIGIN = (
    L("CloudFront edge"), L("Fastly shared cache", role="shield"), L("Origin", role="origin"))
_EXP = (spec(match=("cloudfront",)), spec(match=("fastly",)), spec(role=("origin",)))


@pytest.mark.parametrize("expected,actual,result", [
    (_EXP, [_CF, _FASTLY, _ORIGIN], True),
    ((_EXP[0], _EXP[1], spec(role=("origin",), optional=True)), [_CF, _FASTLY], True),
    (_EXP, [_CF, _FASTLY], False),
    (_EXP, [_CF, _FASTLY, _ORIGIN, L("WAF", role="security")], False),
    (_EXP, [_FASTLY, _CF, _ORIGIN], False),
    ((spec(role=("origin",), optional=True),), [], True),
], ids=["exact", "optional-absent", "required-absent", "extra-actual", "swapped", "empty-all-optional"])
def test_chain_matches(expected, actual, result):
    assert chain_matches(expected, actual) is result


def _scored_case(serving=True, chain=True):
    expected = {}
    if serving:
        expected["serving"] = {"label": "Fastly", "match": ["fastly"]}
    if chain:
        expected["chain"] = [{"label": "CloudFront edge", "match": ["cloudfront"]},
                             {"label": "Fastly", "match": ["fastly"]},
                             {"label": "origin", "role": ["origin"]}]
    return parse_case(make_case_data(expected=expected))


_GOOD = V([L("CloudFront edge", state="MISS"),
           L("Fastly shared cache", role="shield", state="HIT"),
           L("Origin", role="origin", state="UNKNOWN", caches=False)],
          "Fastly shared cache", count=2)


def test_evaluate_scored_match():
    out = evaluate(_scored_case(), _GOOD)
    assert out.serving_text == "Fastly shared cache (HIT)"
    assert out.chain_text == (
        "CloudFront edge [MISS] → Fastly shared cache [HIT] → Origin [UNKNOWN] · 2 caching")
    assert out.serving_ok is True
    assert out.chain_ok is True
    assert out.unverified == 0


def test_evaluate_observed_case():
    out = evaluate(parse_case(make_case_data()), _GOOD)
    assert out.serving_ok is None and out.chain_ok is None
    assert out.serving_text == "Fastly shared cache (HIT)"
    assert out.chain_text.endswith("· 2 caching")


def test_evaluate_no_serving_layer():
    out = evaluate(_scored_case(), V([], "Ghost", count=0))
    assert out.serving_text == "—"
    assert out.serving_ok is False
    assert out.chain_ok is False


def test_evaluate_degraded():
    degraded = {"status": "unavailable", "reason": "auth error"}
    out = evaluate(_scored_case(chain=False), degraded)
    assert out.serving_text == out.chain_text == "degraded: auth error"
    assert out.serving_ok is False
    assert out.chain_ok is None


def test_evaluate_counts_unverified():
    flagged = V(_GOOD["layers"], "Fastly shared cache", count=2,
                flags=[{"path": "a", "citation": "x", "reason": "r"},
                       {"path": "b", "citation": "y", "reason": "r"}])
    assert evaluate(parse_case(make_case_data()), flagged).unverified == 2


def test_expected_texts():
    case = parse_case(make_case_data(expected={
        "serving": {"label": "Fastly", "match": ["fastly"]},
        "chain": [{"label": "CloudFront edge", "match": ["cloudfront"]},
                  {"label": "Fastly", "match": ["fastly"]},
                  {"label": "origin", "role": ["origin"], "optional": True}]}))
    assert expected_texts(case.expected) == ("Fastly", "CloudFront edge → Fastly → origin?")
    assert expected_texts(None) == ("—", "—")
    assert expected_texts(_scored_case(chain=False).expected) == ("Fastly", "—")


# --- Task 3: table ------------------------------------------------------------

from evals.score import Outcome  # noqa: E402
from evals.table import render_table  # noqa: E402

_CHAIN_OK = "CloudFront edge [MISS] → Fastly shared cache [HIT] → Origin [UNKNOWN] · 2 caching"


def _line_with(output: str, *needles: str) -> str:
    lines = [l for l in output.splitlines() if all(n in l for n in needles)]
    assert lines, f"no line containing {needles!r} in:\n{output}"
    return lines[0]


def test_table_rows_and_marks():
    case = _scored_case()
    outcomes = {
        ("golden", "m1"): Outcome("Fastly shared cache (HIT)", _CHAIN_OK, True, True, 0),
        ("golden", "m2"): Outcome("CloudFront edge (MISS)", "CloudFront edge [MISS] · 1 caching",
                                  False, False, 0),
    }
    out = render_table([case], ["m1", "m2"], outcomes)
    header = out.splitlines()[0]
    for word in ("case", "model", "serving layer", "chain"):
        assert word in header
    expected_row = _line_with(out, "expected")
    assert "Fastly" in expected_row and "CloudFront edge → Fastly → origin" in expected_row
    m1 = _line_with(out, "m1", "Fastly shared cache (HIT) ✓")
    assert m1.rstrip().endswith("✓")
    m2 = _line_with(out, "m2", "CloudFront edge (MISS)")
    assert m2.count("✗") == 2


def test_table_observed_case_has_no_marks():
    case = parse_case(make_case_data("observed"))
    outcomes = {("observed", "m1"): Outcome("nginx cache (HIT)", "nginx cache [HIT] · 1 caching",
                                            None, None, 0)}
    out = render_table([case], ["m1"], outcomes)
    assert _line_with(out, "expected").count("—") == 2
    case_rows = [l for l in out.splitlines() if "nginx cache" in l]
    assert case_rows and all("✓" not in l and "✗" not in l for l in case_rows)


def test_table_scores_count_only_labeled():
    scored = parse_case(make_case_data("a-scored", expected={
        "serving": {"label": "Fastly", "match": ["fastly"]},
        "chain": [{"label": "Fastly", "match": ["fastly"]}]}))
    observed = parse_case(make_case_data("b-observed"))
    serving_only = parse_case(make_case_data("c-serving", expected={
        "serving": {"label": "Fastly", "match": ["fastly"]}}))
    good = Outcome("Fastly (HIT)", "Fastly [HIT] · 1 caching", True, True, 0)
    outcomes = {
        ("a-scored", "m1"): good,
        ("b-observed", "m1"): Outcome("x (HIT)", "x [HIT] · 1 caching", None, None, 0),
        ("c-serving", "m1"): Outcome("x (HIT)", "x [HIT] · 1 caching", False, None, 0),
    }
    out = render_table([scored, observed, serving_only], ["m1"], outcomes)
    score = _line_with(out, "score", "m1")
    assert "serving 1/2" in score and "chain 1/1" in score

    only_serving = render_table([serving_only], ["m1"], {("c-serving", "m1"): outcomes[("c-serving", "m1")]})
    assert "chain —" in _line_with(only_serving, "score", "m1")


def test_table_unverified_note():
    case = parse_case(make_case_data())
    out = render_table([case], ["m1"], {("golden", "m1"): Outcome("a (HIT)", "a [HIT] · 1 caching",
                                                                  None, None, 2)})
    assert "⚠ 2 unverified" in _line_with(out, "m1", "a (HIT)")


def test_table_wraps_without_truncation():
    long_chain = " → ".join(f"Layer{i} [MISS]" for i in range(14)) + " · 13 caching"
    assert len(long_chain) > 200
    case = parse_case(make_case_data())
    out = render_table([case], ["m1"], {("golden", "m1"): Outcome("Layer13 (HIT)", long_chain,
                                                                  None, None, 0)})
    assert all(len(line) <= 160 for line in out.splitlines())
    flat = " ".join(out.split())
    for word in long_chain.split():
        assert word in flat


# --- Task 4: runner -----------------------------------------------------------

import hashlib  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

from app.llm.prompt import SYSTEM_PROMPT  # noqa: E402
from app.pipeline.analyze import make_llm_analyze  # noqa: E402
from evals.runner import (  # noqa: E402
    ModelSpec,
    SetupError,
    parse_model_spec,
    run_eval,
    write_results,
)
from tests.test_analysis import VALID_RESULT, FakeProvider  # noqa: E402

_DISPATCHER_CASE = make_case_data(expected={"serving": {"label": "Dispatcher", "match": ["dispatcher"]}})


def test_parse_model_spec():
    assert parse_model_spec("anthropic:claude-opus-4-8") == ModelSpec("anthropic", "claude-opus-4-8")
    assert parse_model_spec("openrouter:meta-llama/x:free").model == "meta-llama/x:free"
    assert parse_model_spec("anthropic:claude-opus-4-8").label == "claude-opus-4-8"
    for bad in ("nocolon", ":m", "p:"):
        with pytest.raises(SetupError):
            parse_model_spec(bad)


async def test_run_eval_two_models():
    providers = {"fa": FakeProvider([json.dumps(VALID_RESULT)]),
                 "fb": FakeProvider(["not json", "not json"])}
    run = await run_eval(
        [parse_case(_DISPATCHER_CASE)],
        [ModelSpec("fa", "m1"), ModelSpec("fb", "m2")],
        analyze=make_llm_analyze(resolver=providers.get),
        is_configured=lambda p: p in providers,
    )
    good = run.outcomes[("golden", "m1")]
    assert good.serving_ok is True
    assert good.serving_text == "Apache Dispatcher (HIT)"
    bad = run.outcomes[("golden", "m2")]
    assert bad.serving_text.startswith("degraded:")
    assert bad.serving_ok is False
    assert len(run.records) == 2
    for record in run.records:
        assert set(record) == {"case", "provider", "model", "duration_ms", "verdict_json", "llm_json",
                               "investigate", "extra_requests", "tokens"}
        assert record["investigate"] is False and record["extra_requests"] == 0 and record["tokens"] is None


async def test_run_eval_unconfigured_provider_makes_no_calls():
    providers = {"fa": FakeProvider([json.dumps(VALID_RESULT)])}
    with pytest.raises(SetupError, match="zz"):
        await run_eval(
            [parse_case(_DISPATCHER_CASE)],
            [ModelSpec("fa", "m1"), ModelSpec("zz", "m2")],
            analyze=make_llm_analyze(resolver=providers.get),
            is_configured=lambda p: p == "fa",
        )
    assert providers["fa"].calls == []


async def test_run_eval_survives_analyze_exception():
    calls = {"n": 0}
    real = make_llm_analyze(resolver={"fa": FakeProvider([json.dumps(VALID_RESULT)])}.get)

    async def flaky(bundle, provider, model):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return await real(bundle, provider, model)

    cases = [parse_case(make_case_data("a")), parse_case(make_case_data("b"))]
    run = await run_eval(cases, [ModelSpec("fa", "m1")], analyze=flaky, is_configured=lambda p: True)
    assert run.outcomes[("a", "m1")].serving_text == "degraded: RuntimeError: boom"
    assert run.outcomes[("b", "m1")].serving_text == "Apache Dispatcher (HIT)"


async def test_run_eval_rejects_duplicate_models():
    with pytest.raises(SetupError):
        await run_eval([parse_case(make_case_data())], [ModelSpec("fa", "m1"), ModelSpec("fa", "m1")],
                       analyze=make_llm_analyze(resolver={}.get), is_configured=lambda p: True)


async def test_write_results(tmp_path):
    providers = {"fa": FakeProvider([json.dumps(VALID_RESULT)])}
    models = [ModelSpec("fa", "m1")]
    run = await run_eval([parse_case(make_case_data())], models,
                         analyze=make_llm_analyze(resolver=providers.get), is_configured=lambda p: True)
    path = write_results(run, models, tmp_path, now=datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC))
    assert path == tmp_path / "20261031T120000Z.json"
    data = json.loads(path.read_text())
    assert data["started_at"] == "2026-10-31T12:00:00Z"
    assert data["prompt_sha256"] == hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
    assert data["models"] == ["fa:m1"]
    assert data["records"] == run.records


# --- Task 5: capture ----------------------------------------------------------

import httpx  # noqa: E402
import respx  # noqa: E402

from evals.capture import CaptureError, capture, parse_report_link, write_case  # noqa: E402

_API = "http://localhost:8000/api/analyses/r1"
_NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)


def make_report(**over) -> dict:
    report = {
        "id": "r1", "url": GOLDEN["meta"]["url"], "created_at": "2026-10-31T11:59:00",
        "status": "done", "provider": "anthropic", "model": "m",
        "vantage": GOLDEN["meta"]["vantage"],
        "dns_json": GOLDEN["dns"], "samples_json": GOLDEN["samples"],
        "traceroute_json": GOLDEN["traceroute"],
        "verdict_json": {"cached": True, "layers": []}, "llm_json": None,
        "error": None, "domain": "www.example-foods.com", "has_critical": False,
    }
    report.update(over)
    return report


@pytest.mark.parametrize("link", [
    "http://localhost:8000/reports/r1",
    "http://localhost:8000/runs/r1",
    "http://localhost:8000/api/analyses/r1",
    "http://localhost:8000/reports/r1/?x=1#y",
])
def test_parse_report_link_forms(link):
    api_url, report_id, auth, clean = parse_report_link(link)
    assert (api_url, report_id, auth) == (_API, "r1", None)
    assert clean.startswith("http://localhost:8000/")


@pytest.mark.parametrize("link", ["http://h/other/r1", "http://h/reports/", "not a url"])
def test_parse_report_link_rejects(link):
    with pytest.raises(CaptureError):
        parse_report_link(link)


@respx.mock
async def test_capture_writes_case(tmp_path):
    respx.get(_API).mock(return_value=httpx.Response(200, json=make_report()))
    path = await capture("http://localhost:8000/reports/r1", "golden",
                         directory=tmp_path, env={}, now=_NOW)
    assert path == tmp_path / "golden.json"
    data = json.loads(path.read_text())
    assert data["evidence"] == {"dns": GOLDEN["dns"], "samples": GOLDEN["samples"],
                                "traceroute": GOLDEN["traceroute"]}
    assert data["expected"] is None
    assert data["source"]["report_id"] == "r1"
    assert data["source"]["captured_at"] == "2026-10-31T12:00:00Z"
    assert data["source"]["report_link"] == "http://localhost:8000/reports/r1"
    assert data["original_verdict"] == {"cached": True, "layers": []}
    assert parse_case(data).name == "golden"


@respx.mock
async def test_capture_strips_userinfo_from_source_link(tmp_path):
    route = respx.get(_API).mock(return_value=httpx.Response(200, json=make_report()))
    path = await capture("http://u:p@localhost:8000/reports/r1", "golden",
                         directory=tmp_path, env={}, now=_NOW)
    assert route.calls.last.request.headers["authorization"] == "Basic dTpw"
    text = path.read_text()
    assert "u:p@" not in text and "dTpw" not in text
    assert json.loads(text)["source"]["report_link"] == "http://localhost:8000/reports/r1"


@respx.mock
async def test_capture_env_basic_auth(tmp_path):
    route = respx.get(_API).mock(return_value=httpx.Response(200, json=make_report()))
    await capture("http://localhost:8000/reports/r1", "golden", directory=tmp_path,
                  env={"BASIC_AUTH_USER": "a", "BASIC_AUTH_PASS": "b"}, now=_NOW)
    assert route.calls.last.request.headers["authorization"] == "Basic YTpi"


@respx.mock
async def test_capture_401_names_env_vars(tmp_path):
    respx.get(_API).mock(return_value=httpx.Response(401))
    with pytest.raises(CaptureError, match="BASIC_AUTH_USER"):
        await capture("http://localhost:8000/reports/r1", "golden", directory=tmp_path, env={}, now=_NOW)


_REFUSALS = {
    "running": (200, make_report(status="running")),
    "error": (200, make_report(status="error")),
    "no-ok-samples": (200, make_report(samples_json=[{**GOLDEN["samples"][0], "ok": False}])),
    "not-found": (404, {"detail": "not found"}),
}


@pytest.mark.parametrize("status,body", list(_REFUSALS.values()), ids=list(_REFUSALS))
async def test_capture_refusals(tmp_path, status, body):
    with respx.mock:
        respx.get(_API).mock(return_value=httpx.Response(status, json=body))
        with pytest.raises(CaptureError):
            await capture("http://localhost:8000/reports/r1", "golden", directory=tmp_path, env={}, now=_NOW)
    assert list(tmp_path.iterdir()) == []


@respx.mock
async def test_capture_degraded_report_accepted(tmp_path):
    respx.get(_API).mock(return_value=httpx.Response(
        200, json=make_report(verdict_json={"status": "unavailable", "reason": "x"})))
    path = await capture("http://localhost:8000/reports/r1", "golden", directory=tmp_path, env={}, now=_NOW)
    assert json.loads(path.read_text())["original_verdict"] is None


def test_write_case_refuses_overwrite_and_bad_name(tmp_path):
    existing = write_case_file(tmp_path, make_case_data())
    before = existing.read_text()
    with pytest.raises(CaptureError):
        write_case(make_case_data(), tmp_path)
    assert existing.read_text() == before
    with pytest.raises(CaptureError):
        write_case(make_case_data("Bad Name"), tmp_path)


# --- Task 6: CLI + vendor guard -----------------------------------------------

from evals.__main__ import main  # noqa: E402
from tests.vendor_tokens import FORBIDDEN_VENDOR_TOKENS  # noqa: E402


def _cli_cases(tmp_path, data=None) -> Path:
    cases = tmp_path / "cases"
    cases.mkdir()
    write_case_file(cases, data or _DISPATCHER_CASE)
    return cases


def test_cli_run_prints_table_and_writes_results(tmp_path, capsys):
    provider = FakeProvider([json.dumps(VALID_RESULT)])
    code = main(["run", "--model", "fa:m1"],
                analyze=make_llm_analyze(resolver={"fa": provider}.get),
                is_configured=lambda p: p == "fa",
                cases_dir=_cli_cases(tmp_path), runs_dir=tmp_path / "runs")
    assert code == 0
    out = capsys.readouterr().out
    assert "Apache Dispatcher (HIT)" in out and "serving" in out
    results = list((tmp_path / "runs").iterdir())
    assert len(results) == 1
    assert str(results[0]) in out


@pytest.mark.parametrize("scenario", ["unknown-case", "malformed-case", "unconfigured-provider"])
def test_cli_bad_case_exits_2_without_calls(tmp_path, capsys, scenario):
    provider = FakeProvider([json.dumps(VALID_RESULT)])
    cases = _cli_cases(tmp_path)
    argv = ["run", "--model", "fa:m1"]
    if scenario == "unknown-case":
        argv += ["--case", "nope"]
    elif scenario == "malformed-case":
        (cases / "broken.json").write_text("{not json")
    else:
        argv = ["run", "--model", "zz:m"]
    code = main(argv, analyze=make_llm_analyze(resolver={"fa": provider}.get),
                is_configured=lambda p: p == "fa", cases_dir=cases, runs_dir=tmp_path / "runs")
    assert code == 2
    err = capsys.readouterr().err.strip()
    assert err and len(err.splitlines()) == 1
    assert provider.calls == []


def test_cli_requires_model(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["run"], cases_dir=_cli_cases(tmp_path))
    assert exc.value.code != 0


@respx.mock
def test_cli_capture(tmp_path, capsys):
    respx.get(_API).mock(return_value=httpx.Response(200, json=make_report()))
    code = main(["capture", "http://localhost:8000/reports/r1", "--name", "golden"],
                cases_dir=tmp_path, env={})
    assert code == 0
    path = tmp_path / "golden.json"
    assert path.is_file()
    out = capsys.readouterr().out
    assert str(path) in out and "expected" in out


def test_no_vendor_names_in_evals_source():
    evals_dir = Path(__file__).resolve().parents[1] / "evals"
    sources = sorted(evals_dir.glob("*.py"))
    assert sources, "no eval sources found"
    leaked = {
        src.name: [t for t in FORBIDDEN_VENDOR_TOKENS if t in src.read_text().lower()]
        for src in sources
    }
    assert {k: v for k, v in leaked.items() if v} == {}



# --- Final review fixes ---------------------------------------------------------

async def test_run_eval_prebuilds_bundles_before_any_call():
    provider = FakeProvider([json.dumps(VALID_RESULT)])
    good = parse_case(make_case_data("a"))
    broken = dataclasses.replace(parse_case(make_case_data("b")),
                                 evidence={"dns": None, "samples": ["oops"], "traceroute": None})
    with pytest.raises(CaseError, match="b"):
        await run_eval([good, broken], [ModelSpec("fa", "m1")],
                       analyze=make_llm_analyze(resolver={"fa": provider}.get),
                       is_configured=lambda p: True)
    assert provider.calls == []


@respx.mock
def test_cli_capture_warns_when_no_2xx(tmp_path, capsys):
    blocked = [{**s, "status": 403} for s in GOLDEN["samples"]]
    respx.get(_API).mock(return_value=httpx.Response(200, json=make_report(samples_json=blocked)))
    code = main(["capture", "http://localhost:8000/reports/r1", "--name", "golden"],
                cases_dir=tmp_path, env={})
    assert code == 0
    assert (tmp_path / "golden.json").is_file()  # still captured — useful as an observed case
    assert "warning: no sample returned 2xx (403×4)" in capsys.readouterr().err


@respx.mock
def test_cli_capture_no_warning_on_2xx(tmp_path, capsys):
    respx.get(_API).mock(return_value=httpx.Response(200, json=make_report()))
    assert main(["capture", "http://localhost:8000/reports/r1", "--name", "golden"],
                cases_dir=tmp_path, env={}) == 0
    assert "warning" not in capsys.readouterr().err


@pytest.mark.parametrize("link", ["http://u:s3cret@h/other/r1", "ftp://u:s3cret@h/reports/r1",
                                  "http://u:x@s3cret@h/other/r1"])
def test_capture_errors_do_not_echo_credentials(link):
    with pytest.raises(CaptureError) as exc:
        parse_report_link(link)
    assert "s3cret" not in str(exc.value)


def test_makefile_eval_capture_recipe_is_silent():
    makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text()
    recipe = makefile.split("eval-capture:", 1)[1].splitlines()[1]
    assert recipe.lstrip("\t").startswith("@"), "make would echo a user:pass@ link"


# --- 1.2.0: probe-aware consumers ---------------------------------------------

from evals.capture import non_2xx_summary  # noqa: E402


def test_non_2xx_summary_ignores_probe():
    ok = [{**s, "status": 200} for s in GOLDEN["samples"]]
    blocked = [{**s, "status": 403} for s in GOLDEN["samples"]]
    probe_403 = {**GOLDEN["samples"][0], "request": 5, "status": 403, "probe": "cache_bust"}
    probe_200 = {**probe_403, "status": 200}
    assert non_2xx_summary(ok + [probe_403]) is None
    assert non_2xx_summary(blocked + [probe_200]) == "403×4"



# --- 1.4.0: --investigate runs each case frozen and live ------------------------

async def test_investigate_runs_each_case_twice_with_labels():
    seen_options = []

    async def analyze(bundle, provider, model, *, emit=None):
        opts = bundle["meta"]["request_options"]
        seen_options.append(opts)
        out = {"verdict_json": {**VALID_RESULT["cache_verdict"], "validation": {"ok": True, "flags": []}},
               "llm_json": dict(VALID_RESULT)}
        if opts.get("investigate"):
            out["llm_json"] = {**out["llm_json"], "investigation_log": [{"n": 1}, {"n": 2}, {"n": 3, "refused": "budget"}],
                               "usage": {"input_tokens": 12000, "output_tokens": 400}}
            out["samples"] = bundle["samples"] + [{"request": 5, "probe": "investigation"}]
        return out

    run = await run_eval([parse_case(_DISPATCHER_CASE)], [ModelSpec("fa", "m1")],
                         analyze=analyze, is_configured=lambda p: True, investigate=True)
    assert set(run.outcomes) == {("golden", "m1"), ("golden", "m1 +investigate")}
    assert run.outcomes[("golden", "m1 +investigate")].serving_ok is True
    assert seen_options[0].get("investigate") is None
    assert seen_options[1]["investigate"] is True and seen_options[1]["extra_request_headers"] == {}
    off, on = run.records
    assert off["investigate"] is False and off["extra_requests"] == 0 and off["tokens"] is None
    assert on["investigate"] is True and on["extra_requests"] == 2  # refused calls are not requests
    assert on["tokens"] == {"input": 12000, "output": 400}
    assert on["samples"][-1]["probe"] == "investigation"


def test_table_shows_live_note_for_investigate_rows():
    case = _scored_case()
    outcomes = {
        ("golden", "m1"): Outcome("Fastly shared cache (HIT)", _CHAIN_OK, True, True, 0),
        ("golden", "m1 +investigate"): Outcome("Fastly shared cache (HIT)", _CHAIN_OK, True, True, 0),
    }
    out = render_table([case], ["m1", "m1 +investigate"], outcomes,
                       notes={("golden", "m1 +investigate"): "live · 2 req · 12.4k tok"})
    assert "live · 2 req · 12.4k tok" in _line_with(out, "m1 +investigate")
    plain = [l for l in out.splitlines() if " m1 " in l and "+investigate" not in l and "score" not in l]
    assert plain and all("live" not in l for l in plain)


def test_cli_investigate_flag_parses(tmp_path):
    seen = []

    async def analyze(bundle, provider, model, *, emit=None):
        seen.append(bool(bundle["meta"]["request_options"].get("investigate")))
        return {"verdict_json": {**VALID_RESULT["cache_verdict"], "validation": {"ok": True, "flags": []}},
                "llm_json": dict(VALID_RESULT)}

    code = main(["run", "--model", "fa:m1", "--investigate"], analyze=analyze,
                is_configured=lambda p: True, cases_dir=_cli_cases(tmp_path), runs_dir=tmp_path / "runs")
    assert code == 0
    assert seen == [False, True]



@respx.mock
async def test_capture_strips_investigation_samples(tmp_path):
    inv = {**GOLDEN["samples"][0], "request": 9, "probe": "investigation",
           "investigation": {"n": 1, "headers": {"X-Debug": "1"}, "cache_bust": False, "reason": "r"}}
    respx.get(_API).mock(return_value=httpx.Response(200, json=make_report(samples_json=[*GOLDEN["samples"], inv])))
    path = await capture("http://localhost:8000/reports/r1", "golden", directory=tmp_path, env={}, now=_NOW)
    data = json.loads(path.read_text())
    assert data["evidence"]["samples"] == GOLDEN["samples"]


def test_row_note_for_both_modes():
    from evals.runner import row_note
    assert row_note({"investigate": False, "tokens": {"input": 8000, "output": 100}, "duration_ms": 8200}) == "frozen · 8.1k tok · 8 s"
    assert row_note({"investigate": True, "extra_requests": 2, "tokens": {"input": 12000, "output": 400}, "duration_ms": 31400}) == "live · 2 req · 12.4k tok · 31 s"
    assert row_note({"investigate": False, "tokens": None, "duration_ms": 1400}) == "frozen · tokens n/a · 1 s"
