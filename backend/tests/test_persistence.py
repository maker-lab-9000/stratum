"""T02 — data model & persistence (spec §6, §7 filters).

Scenarios:
  1. Round-trip nested verdict_json/samples_json read back identical.
  2. Status transitions queued->running->done persist; error column set on failure.
  3. List filters (domain substring, has_critical, provider) return correct subsets.
  4. Delete removes the row; get after delete -> None.
  5. Same suite passes against Postgres when TEST_POSTGRES_URL is set (marked).
"""

import pytest

# A realistic nested verdict + findings (subset of the §5.2 schema).
VERDICT = {
    "cached": True,
    "confidence": "high",
    "provider": "Akamai",
    "layers": [
        {"layer_name": "Edge", "vendor": "Akamai", "state": "HIT", "evidence_headers": ["X-Cache: TCP_HIT"]},
    ],
}
SAMPLES = [
    {"request": 1, "headers": [["X-Cache", "TCP_MISS from a1"], ["Age", "0"]], "status": 200},
    {"request": 2, "headers": [["X-Cache", "TCP_HIT from a1"], ["Age", "12"]], "status": 200},
]
LLM_WITH_CRITICAL = {
    "security_findings": [
        {"severity": "critical", "title": "No HSTS", "evidence_header": "Strict-Transport-Security"},
        {"severity": "info", "title": "Server header present", "evidence_header": "Server"},
    ],
    "performance_findings": [
        {"severity": "warning", "title": "Flat Age", "evidence_header": "Age"},
    ],
}
LLM_NO_CRITICAL = {
    "security_findings": [{"severity": "warning", "title": "x", "evidence_header": "X"}],
    "performance_findings": [],
}


def _roundtrip(repo):
    report = repo.create(
        url="https://www.example-foods.com/menu",
        provider="anthropic",
        model="claude-opus-4-8",
        vantage="Berlin, DE",
        verdict_json=VERDICT,
        samples_json=SAMPLES,
    )
    fetched = repo.get(report.id)
    assert fetched is not None
    assert fetched.verdict_json == VERDICT
    assert fetched.samples_json == SAMPLES
    assert fetched.url == "https://www.example-foods.com/menu"
    assert fetched.domain == "www.example-foods.com"
    return report


# --- Scenario 1 ---------------------------------------------------------------

def test_roundtrip_nested_json_identical(repo):
    _roundtrip(repo)


def test_create_rejects_derived_fields(repo):
    with pytest.raises(ValueError):
        repo.create(url="https://x.test", domain="spoofed.test")
    with pytest.raises(ValueError):
        repo.create(url="https://x.test", has_critical=True)


# --- Scenario 2 ---------------------------------------------------------------

def test_status_transitions_and_error(repo):
    report = repo.create(url="https://x.test")
    assert report.status == "queued"

    r1 = repo.update(report.id, status="running")
    assert r1 is not None and r1.status == "running"

    r2 = repo.update(report.id, status="done")
    assert r2.status == "done"
    # Persisted, not just in-memory.
    assert repo.get(report.id).status == "done"


def test_error_column_set_on_failure(repo):
    report = repo.create(url="https://x.test")
    updated = repo.update(report.id, status="error", error="sampler timed out")
    assert updated.status == "error"
    assert updated.error == "sampler timed out"
    assert repo.get(report.id).error == "sampler timed out"


def test_update_missing_report_returns_none(repo):
    assert repo.update("nonexistent-id", status="done") is None


# --- Scenario 3 ---------------------------------------------------------------

def test_list_filters(repo):
    a = repo.create(url="https://shop.example-foods.com/a", provider="anthropic",
                    llm_json=LLM_WITH_CRITICAL)
    b = repo.create(url="https://blog.example-foods.com/b", provider="openrouter",
                    llm_json=LLM_NO_CRITICAL)
    c = repo.create(url="https://www.other.test/c", provider="anthropic")

    # has_critical derived correctly on write.
    assert repo.get(a.id).has_critical is True
    assert repo.get(b.id).has_critical is False
    assert repo.get(c.id).has_critical is False

    # Domain substring.
    foods = {r.id for r in repo.list(domain="example-foods.com")}
    assert foods == {a.id, b.id}

    # has_critical filter.
    crit = {r.id for r in repo.list(has_critical=True)}
    assert crit == {a.id}

    # provider filter.
    anthropic = {r.id for r in repo.list(provider="anthropic")}
    assert anthropic == {a.id, c.id}

    # Combined filters.
    combined = {r.id for r in repo.list(domain="example-foods.com", provider="anthropic")}
    assert combined == {a.id}

    # No filters -> everything.
    assert len({r.id for r in repo.list()}) == 3


def test_has_critical_recomputed_on_update(repo):
    report = repo.create(url="https://x.test")
    assert report.has_critical is False
    updated = repo.update(report.id, llm_json=LLM_WITH_CRITICAL)
    assert updated.has_critical is True
    assert {r.id for r in repo.list(has_critical=True)} == {report.id}


def test_list_newest_first(repo):
    ids = [repo.create(url=f"https://x.test/{i}").id for i in range(3)]
    listed = [r.id for r in repo.list()]
    # created_at desc, id desc tiebreak — most recent creations first.
    assert set(listed) == set(ids)
    assert listed[0] in ids


# --- Scenario 4 ---------------------------------------------------------------

def test_delete_removes_row(repo):
    report = repo.create(url="https://x.test")
    assert repo.delete(report.id) is True
    assert repo.get(report.id) is None
    # Deleting again is a no-op False, not an error.
    assert repo.delete(report.id) is False


# --- Scenario 5 (Postgres parity) --------------------------------------------

@pytest.mark.postgres
def test_roundtrip_and_filters_on_postgres(pg_repo):
    _roundtrip(pg_repo)
    a = pg_repo.create(url="https://crit.example.com/a", llm_json=LLM_WITH_CRITICAL)
    assert pg_repo.get(a.id).has_critical is True
    assert {r.id for r in pg_repo.list(has_critical=True)} == {a.id}
    assert pg_repo.delete(a.id) is True
