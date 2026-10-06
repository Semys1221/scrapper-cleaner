"""In-flight query slots: concurrent batches must not repeat a (query, skip)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from query_planner import QueryPlanner


def _config(locations: list[str]) -> dict:
    return {
        "KEYWORDS": ["plombier"],
        "LOCATIONS": locations,
        "EXPANSION_KEYWORDS": [],
        "EXPANSION_LOCATIONS": [],
        "QUERY_PLANNER_USE_DEPARTMENTS": False,
        "EXCLUDE_DOMAINS": [],
        "ENRICH_ENABLED": False,
        "TARGET_LEADS": 1000,
        "TARGET_MODE": "csv_saved",
    }


def _planner(locations: list[str]) -> QueryPlanner:
    return QueryPlanner.from_config(_config(locations))


def _simulate_fill(
    planner: QueryPlanner,
    *,
    concurrency: int,
    batch_size: int,
    limit: int,
    full_pages: int,
) -> list[tuple[str, int]]:
    """Issue up to ``concurrency`` batches before any result is recorded."""
    inflight: list = []
    issued: list[tuple[str, int]] = []
    while True:
        while len(inflight) < concurrency:
            batch = planner.next_batch(batch_size)
            if batch is None:
                break
            for query in batch.queries:
                issued.append((query, batch.skip_places))
            inflight.append(batch)
        if not inflight:
            break
        batch = inflight.pop(0)
        raw = limit if batch.skip_places < full_pages * limit else limit - 1
        planner.record_batch_result(
            batch,
            raw_places_per_query=[raw] * len(batch.slot_ids),
            limit_per_query=limit,
        )
    return issued


@pytest.mark.parametrize("concurrency", [3, 6])
def test_concurrent_fill_fetches_each_page_once(concurrency: int) -> None:
    limit = 100
    full_pages = 2
    locations = [f"City{index}" for index in range(8)]
    planner = _planner(locations)
    issued = _simulate_fill(
        planner,
        concurrency=concurrency,
        batch_size=1,
        limit=limit,
        full_pages=full_pages,
    )

    assert len(issued) == len(set(issued))
    by_query: dict[str, list[int]] = {}
    for query, skip in issued:
        by_query.setdefault(query, []).append(skip)
    expected_skips = [page * limit for page in range(full_pages + 1)]
    assert len(by_query) == len(locations)
    for skips in by_query.values():
        assert skips == expected_skips
    cursor = full_pages * limit
    assert set(planner.slot_skips) == {str(slot_id) for slot_id in range(len(locations))}
    assert set(planner.slot_skips.values()) == {cursor}
    assert planner.exhausted_slots == set(range(len(locations)))
    assert planner.inflight == {}


def test_release_reissues_the_same_page_and_record_is_idempotent() -> None:
    planner = _planner(["Lyon", "Paris"])
    first = planner.next_batch(1)
    assert first is not None
    second = planner.next_batch(1)
    assert second is not None
    assert first.queries != second.queries
    assert planner.next_batch(1) is None

    planner.release_batch(first)
    reissued = planner.next_batch(1)
    assert reissued is not None
    assert reissued.queries == first.queries
    assert reissued.skip_places == first.skip_places == 0

    planner.record_batch_result(reissued, raw_places_per_query=[10], limit_per_query=10)
    planner.record_batch_result(reissued, raw_places_per_query=[10], limit_per_query=10)
    assert planner.slot_skips[str(reissued.slot_ids[0])] == 10

    lone = _planner(["Lyon"])
    failed = lone.next_batch(1)
    assert failed is not None
    lone.abandon_batch(failed)
    state = {"version": 4}
    lone.persist(state)
    assert "inflight" not in state["planner"]
    assert "failed_this_run" not in state["planner"]
    assert lone.next_batch(1) is None
    restored = QueryPlanner.from_config(_config(["Lyon"]), state)
    resumed = restored.next_batch(1)
    assert resumed is not None
    assert resumed.queries == failed.queries
    assert resumed.skip_places == 0


class _PageClient:
    def __init__(self, *, limit: int, full_pages: int) -> None:
        self.limit = limit
        self.full_pages = full_pages
        self.last_error = ""
        self.calls: list[tuple[str, int]] = []

    async def google_maps_search_batch(self, queries, limit, skip_places=0, **kwargs):  # noqa: ANN001
        del limit, kwargs
        query = queries[0]
        self.calls.append((query, skip_places))
        if len(self.calls) > 40:
            self.last_error = "retry loop"
            return []
        self.last_error = ""
        count = self.limit if skip_places < self.full_pages * self.limit else self.limit - 1
        return [[{"name": f"{query}-{skip_places}-{index}"} for index in range(count)]]


@pytest.mark.parametrize("concurrency", [3, 6])
def test_planner_loop_fetches_each_page_once_at_concurrency(
    concurrency: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    from core_logic import (
        OutscraperSettings,
        _reset_lead_save_buffer,
        _run_planner_scrape,
        activate_output_paths,
    )

    limit = 10
    full_pages = 2
    locations = [f"City{index}" for index in range(8)]
    config = _config(locations)
    activate_output_paths(f"planner_c{concurrency}")
    _reset_lead_save_buffer()
    planner = QueryPlanner.from_config(config)
    client = _PageClient(limit=limit, full_pages=full_pages)
    leads_saved, *_rest, exhausted, budget_exhausted = asyncio.run(
        _run_planner_scrape(
            client=client,
            planner=planner,
            config=config,
            settings=OutscraperSettings(batch_size=1, concurrency=concurrency, limit_per_query=limit),
            target=1000,
            target_mode="csv_saved",
            run_state=None,
            seen_domain=set(),
            seen_em=set(),
            leads_saved=0,
            leads_enriched_valid=0,
            leads_enriched_rejected=0,
            pending_scraped=[],
            pending_instantly=[],
            instantly_enabled=False,
            push_every=100,
            enrich_enabled=False,
            enrich_batch_size=50,
            log_cb=lambda _message: None,
            progress_cb=lambda _progress: None,
            metric_cb=lambda *_args: None,
            instantly_pushed=0,
            preset="plombier",
            out_dir=str(tmp_path),
        )
    )
    assert leads_saved == 0
    assert exhausted is True
    assert budget_exhausted is False
    assert len(client.calls) == len(set(client.calls))
    by_query: dict[str, list[int]] = {}
    for query, skip in client.calls:
        by_query.setdefault(query, []).append(skip)
    expected = [page * limit for page in range(full_pages + 1)]
    assert len(by_query) == len(locations)
    for skips in by_query.values():
        assert skips == expected
    assert set(planner.slot_skips.values()) == {full_pages * limit}
    assert planner.exhausted_slots == set(range(len(locations)))


@pytest.mark.parametrize("failure", ["last_error", "raise"])
def test_failed_batch_is_released_for_resume(
    failure: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    from core_logic import (
        OutscraperSettings,
        _reset_lead_save_buffer,
        _run_planner_scrape,
        activate_output_paths,
    )

    locations = ["Lyon", "Paris"]
    config = _config(locations)
    activate_output_paths("planner_fail")
    _reset_lead_save_buffer()
    planner = QueryPlanner.from_config(config)
    run_state: dict = {"version": 4}
    calls: list[tuple[str, int]] = []

    class _Client:
        last_error = ""

        async def google_maps_search_batch(self, queries, limit, skip_places=0, **kwargs):  # noqa: ANN001
            del limit, kwargs
            query = queries[0]
            calls.append((query, skip_places))
            if len(calls) > 6:
                self.last_error = "retry loop"
                return []
            if "Lyon" in query:
                if failure == "last_error":
                    self.last_error = "HTTP 500"
                    return []
                raise RuntimeError("outscraper down")
            self.last_error = ""
            return [[{"name": "Paris"}]]

    asyncio.run(
        _run_planner_scrape(
            client=_Client(),
            planner=planner,
            config=config,
            settings=OutscraperSettings(batch_size=1, concurrency=2, limit_per_query=5),
            target=1000,
            target_mode="csv_saved",
            run_state=run_state,
            seen_domain=set(),
            seen_em=set(),
            leads_saved=0,
            leads_enriched_valid=0,
            leads_enriched_rejected=0,
            pending_scraped=[],
            pending_instantly=[],
            instantly_enabled=False,
            push_every=100,
            enrich_enabled=False,
            enrich_batch_size=50,
            log_cb=lambda _message: None,
            progress_cb=lambda _progress: None,
            metric_cb=lambda *_args: None,
            instantly_pushed=0,
            preset="plombier",
            out_dir=str(tmp_path),
        )
    )
    lyon = [skip for query, skip in calls if "Lyon" in query]
    paris = [skip for query, skip in calls if "Paris" in query]
    assert lyon == [0]
    assert paris == [0]
    restored = QueryPlanner.from_config(config, run_state)
    resumed = restored.next_batch(1)
    assert resumed is not None
    assert "Lyon" in resumed.queries[0]
    assert resumed.skip_places == 0
    assert str(resumed.slot_ids[0]) not in restored.slot_skips or restored.slot_skips[str(resumed.slot_ids[0])] == 0


def test_cancelled_inflight_batch_is_refetched_on_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    from core_logic import (
        LeadPersistenceError,
        OutscraperSettings,
        _reset_lead_save_buffer,
        _run_planner_scrape,
        activate_output_paths,
    )

    config = _config(["Lyon", "Paris"])
    activate_output_paths("plombier")
    _reset_lead_save_buffer()
    planner = QueryPlanner.from_config(config)
    run_state: dict = {"version": 4}
    calls: list[str] = []

    class _Client:
        last_error = ""

        async def google_maps_search_batch(self, queries, limit, skip_places=0, **kwargs):  # noqa: ANN001
            del limit, skip_places, kwargs
            query = queries[0]
            calls.append(query)
            if "Paris" in query:
                await asyncio.Event().wait()
            return [
                [
                    {
                        "name": "Dupont",
                        "site": "https://lyon.fr",
                        "email": "lyon@ex.fr",
                        "phone": "+33184801234",
                        "place_id": "lyon",
                        "city": "Lyon",
                        "type": "Plombier",
                        "category": "Plumber",
                    }
                ]
            ]

    def persist(rows: list, *, preset: str) -> dict:
        del rows, preset
        raise RuntimeError("schema mismatch")

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)
    with pytest.raises(LeadPersistenceError, match="schema mismatch"):
        asyncio.run(
            _run_planner_scrape(
                client=_Client(),
                planner=planner,
                config=config,
                settings=OutscraperSettings(batch_size=1, concurrency=2, limit_per_query=5),
                target=20,
                target_mode="csv_saved",
                run_state=run_state,
                seen_domain=set(),
                seen_em=set(),
                leads_saved=0,
                leads_enriched_valid=0,
                leads_enriched_rejected=0,
                pending_scraped=[],
                pending_instantly=[],
                instantly_enabled=False,
                push_every=100,
                enrich_enabled=False,
                enrich_batch_size=50,
                log_cb=lambda _message: None,
                progress_cb=lambda _progress: None,
                metric_cb=lambda *_args: None,
                instantly_pushed=0,
                preset="plombier",
                out_dir=str(tmp_path),
            )
        )
    assert sorted(calls) == sorted(
        ["plombier in Lyon, France", "plombier in Paris, France"]
    )
    assert planner.slot_skips == {}
    assert planner.exhausted_slots == set()
    restored = QueryPlanner.from_config(config, run_state)
    first = restored.next_batch(1)
    second = restored.next_batch(1)
    assert first is not None and second is not None
    assert {first.queries[0], second.queries[0]} == {
        "plombier in Lyon, France",
        "plombier in Paris, France",
    }
    assert first.skip_places == 0
    assert second.skip_places == 0
