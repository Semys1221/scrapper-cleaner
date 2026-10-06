"""Spend-cap tests: no re-POST, worker backoff, recovery budget, cancel leak."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


def _config(locations: list[str], *, concurrency: int, target: int, limit: int) -> dict:
    return {
        "TARGET_LEADS": target,
        "TARGET_MODE": "csv_saved",
        "KEYWORDS": ["plombier"],
        "LOCATIONS": locations,
        "EXPANSION_KEYWORDS": [],
        "EXPANSION_LOCATIONS": [],
        "QUERY_PLANNER_USE_DEPARTMENTS": False,
        "OUTSCRAPER_API_KEY": "test-key",
        "OUTSCRAPER_BATCH_SIZE": 1,
        "OUTSCRAPER_CONCURRENCY": concurrency,
        "OUTSCRAPER_LIMIT_PER_QUERY": limit,
        "EXCLUDE_DOMAINS": [],
        "ENRICH_ENABLED": False,
        "PRESET_ID": "plombier",
        "SERVICE_DEFAULT": "Plomberie",
        "SERVICE_RULES": [],
    }


def test_maps_search_does_not_resubmit_on_timeout() -> None:
    from outscraper_client import OutscraperClient

    posts = {"n": 0}

    def boom(self, payload):  # noqa: ANN001
        del self, payload
        posts["n"] += 1
        raise TimeoutError("timed out")

    client = OutscraperClient("test-key")
    client.qps_delay = 0
    client._submit_maps_once = boom.__get__(client, OutscraperClient)
    result = asyncio.run(client.google_maps_search_batch(["notaire Lyon"], 10, timeout_s=0.2))
    assert result == []
    assert posts["n"] == 1
    assert "timed out" in client.last_error


def test_maps_search_polls_request_id_instead_of_reposting() -> None:
    from outscraper_client import OutscraperClient

    posts = {"n": 0}
    gets = {"n": 0}

    def submit(self, payload):  # noqa: ANN001
        del self, payload
        posts["n"] += 1
        return "req-1"

    def fetch(self, request_id):  # noqa: ANN001
        del self
        gets["n"] += 1
        return {"id": request_id, "status": "Pending"}

    client = OutscraperClient("test-key")
    client.qps_delay = 0
    client.poll_interval_s = 0.01
    client._submit_maps_once = submit.__get__(client, OutscraperClient)
    client._get_request = fetch.__get__(client, OutscraperClient)
    result = asyncio.run(client.google_maps_search_batch(["notaire Lyon"], 10, timeout_s=0.15))
    assert result == []
    assert posts["n"] == 1
    assert gets["n"] >= 2


def test_maps_search_returns_polled_success_payload() -> None:
    from outscraper_client import OutscraperClient

    posts = {"n": 0}

    def submit(self, payload):  # noqa: ANN001
        del payload
        posts["n"] += 1
        self.paid_submits += 1
        return "req-9"

    def fetch(self, request_id):  # noqa: ANN001
        del self, request_id
        return {"id": "req-9", "status": "Success", "data": [[{"name": "Etude"}]]}

    client = OutscraperClient("test-key")
    client.qps_delay = 0
    client._submit_maps_once = submit.__get__(client, OutscraperClient)
    client._get_request = fetch.__get__(client, OutscraperClient)
    result = asyncio.run(client.google_maps_search_batch(["notaire Lyon"], 1, timeout_s=1))
    assert posts["n"] == 1
    assert result == [[{"name": "Etude"}]]


def test_next_worker_wait_backs_off_and_stops_on_budget() -> None:
    from core_logic import next_worker_wait

    streak, wait = next_worker_wait(
        progressed=False, budget_exhausted=False, streak=0, sleep_s=30
    )
    assert streak == 1
    assert wait == 60
    streak, wait = next_worker_wait(
        progressed=False, budget_exhausted=False, streak=1, sleep_s=30
    )
    assert streak == 2
    assert wait == 120
    streak, wait = next_worker_wait(
        progressed=False, budget_exhausted=False, streak=6, sleep_s=30
    )
    assert wait == 900
    streak, wait = next_worker_wait(
        progressed=True, budget_exhausted=False, streak=4, sleep_s=30
    )
    assert streak == 0
    assert wait == 30
    streak, wait = next_worker_wait(
        progressed=False, budget_exhausted=True, streak=3, sleep_s=30
    )
    assert wait is None
    assert streak == 3


def test_email_recovery_stops_at_the_dollar_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    from core_logic import output_paths, run_email_recovery

    paths = output_paths("plombier")
    rows = [{"website": f"d{index}.example", "name": f"N{index}"} for index in range(5)]
    Path(paths.email_recovery).write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    sent: list[list[str]] = []

    async def fake_contacts(self, domains):  # noqa: ANN001
        del self
        sent.append(list(domains))
        return []

    monkeypatch.setattr("core_logic.OutscraperClient.emails_and_contacts", fake_contacts)
    config = {"OUTSCRAPER_API_KEY": "test-key", "OUTSCRAPER_EMAIL_RECOVERY_ENABLED": True}
    summary = asyncio.run(
        run_email_recovery(
            config,
            log_cb=lambda _message: None,
            preset="plombier",
            batch_size=25,
            push_to_instantly=False,
            max_cost_usd=0.009,
        )
    )
    assert summary["domains_sent"] == 3
    assert sent == [["d0.example", "d1.example", "d2.example"]]
    remaining = Path(paths.email_recovery).read_text(encoding="utf-8")
    assert "d3.example" in remaining
    assert "d4.example" in remaining
    assert "d0.example" not in remaining

    sent.clear()
    summary = asyncio.run(
        run_email_recovery(
            config,
            log_cb=lambda _message: None,
            preset="plombier",
            batch_size=25,
            push_to_instantly=False,
            max_cost_usd=0.009,
        )
    )
    assert summary["budget_exhausted"] is True
    assert summary["domains_sent"] == 0
    assert sent == []
    assert "d3.example" in Path(paths.email_recovery).read_text(encoding="utf-8")


def _lead(city: str) -> dict:
    return {
        "name": city,
        "site": f"https://{city}.fr",
        "email": f"{city}@ex.fr",
        "phone": "+33184801234",
        "place_id": city,
        "city": city,
        "type": "Notaire",
        "category": "Notary",
    }


def test_target_stops_new_batches_within_concurrency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    calls: list[int] = []

    async def fake_search(self, queries, limit, **kwargs):  # noqa: ANN001
        del self, limit, kwargs
        calls.append(len(queries))
        return [[_lead(query.split(" in ", 1)[1].split(",", 1)[0])] for query in queries]

    def persist(rows: list, *, preset: str) -> dict:
        del preset
        return {"inserted": len(rows), "updated": 0, "skipped": 0}

    monkeypatch.setattr("core_logic.OutscraperClient.google_maps_search_batch", fake_search)
    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)
    from core_logic import run_scraper_pipeline

    config = _config([f"City{index:02d}" for index in range(10)], concurrency=6, target=1, limit=5)
    config["OUTSCRAPER_ENRICHMENT"] = ["leads_n_contacts"]
    config["MAX_SCRAPE_COST_USD"] = 10
    summary = asyncio.run(
        run_scraper_pipeline(
            config,
            log_cb=lambda _message: None,
            progress_cb=lambda _progress: None,
            metric_cb=lambda *_args: None,
            dry_run=False,
            push_to_instantly=False,
            preset="plombier",
        )
    )
    assert 1 <= len(calls) <= 6
    assert summary["leads_saved"] >= 1


def test_cancel_does_not_start_a_queued_paid_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    calls = {"n": 0}
    entered = asyncio.Event()
    release = asyncio.Event()
    real_semaphore = asyncio.Semaphore

    class _OneSlot:
        def __init__(self, _count: int) -> None:
            self._inner = real_semaphore(1)

        async def __aenter__(self) -> None:
            await self._inner.acquire()

        async def __aexit__(self, *_args) -> None:
            self._inner.release()

    monkeypatch.setattr(asyncio, "Semaphore", _OneSlot)

    async def fake_search(self, queries, limit, **kwargs):  # noqa: ANN001
        del self, queries, limit, kwargs
        calls["n"] += 1
        if calls["n"] == 1:
            entered.set()
        await release.wait()
        return []

    def persist(rows: list, *, preset: str) -> dict:
        del rows, preset
        return {"inserted": 0, "updated": 0, "skipped": 0}

    monkeypatch.setattr("core_logic.OutscraperClient.google_maps_search_batch", fake_search)
    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)
    from core_logic import run_scraper_pipeline

    config = _config(
        [f"City{index:02d}" for index in range(8)],
        concurrency=6,
        target=100,
        limit=5,
    )
    config["MAX_SCRAPE_COST_USD"] = 10

    async def _main() -> None:
        task = asyncio.create_task(
            run_scraper_pipeline(
                config,
                log_cb=lambda _message: None,
                progress_cb=lambda _progress: None,
                metric_cb=lambda *_args: None,
                dry_run=False,
                push_to_instantly=False,
                preset="plombier",
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=5)
        before = calls["n"]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        await asyncio.sleep(0.05)
        assert calls["n"] == before == 1

    asyncio.run(_main())
