"""Local scraper smoke: dry-run and one accepted lead, with no error logs."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("HERCULE_DATA_ROOT", "/tmp/hercule-scraper-tests")

from core_logic import _process_business, activate_output_paths, run_scraper_pipeline  # noqa: E402
from scrape_log import scrape_log_path  # noqa: E402
from shared.central_leads import scraped_row_to_lead  # noqa: E402

_ERROR_RE = re.compile(r"\b(ERROR|WARNING|Traceback|CRITICAL)\b")


def _assert_clean(text: str) -> None:
    bad = [line for line in text.splitlines() if _ERROR_RE.search(line)]
    assert bad == []


def test_process_business_maps_uncleaned_plombier_lead(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    activate_output_paths("plombier")
    row, audit = _process_business(
        {
            "name": "Dupont Plomberie",
            "site": "https://dupont.fr",
            "email": "jean@dupont.fr",
            "phone": "+33 1 84 80 12 34",
            "place_id": "place-1",
            "first_name": "Jean",
            "last_name": "Dupont",
            "city": "Lyon",
            "type": "Plombier",
            "category": "Plumber",
        },
        {
            "EXCLUDE_DOMAINS": [],
            "WEBSITE_REQUIRED": True,
            "TAXONOMY_GATE_ENABLED": False,
            "SERVICE_DEFAULT": "Plomberie",
            "SERVICE_RULES": [],
            "NICHE_GROUP_LABEL": "Plombier",
            "SUBNICHE_LABEL": "Artisan",
        },
        seen_domain=set(),
        seen_em=set(),
    )
    assert audit is not None
    assert audit["Verdict"] == "accepted"
    assert row is not None
    lead = scraped_row_to_lead(row, preset="plombier")
    assert lead["category"] == "PLOMBIER"
    assert lead["status"] == "uncleaned"
    assert lead["company"] == "Dupont Plomberie"
    assert lead["website"] == "dupont.fr"
    assert lead["phone"] == "+33184801234"
    assert lead["first_name"] == "Jean"
    assert lead["last_name"] == "Dupont"
    from instantly_client import _lead_payload

    payload = _lead_payload({**row, "Preset": "plombier"}, "list-1")
    assert payload["phone"] == "+33184801234"
    assert payload["custom_variables"]["category"] == "PLOMBIER"
    assert payload["custom_variables"]["status"] == "uncleaned"
    assert "siret" not in payload.get("custom_variables", {})
    assert "city" not in payload.get("custom_variables", {})


def test_dry_run_log_has_no_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("HERCULE_ALLOW_UNCLEANED_INSTANTLY_PUSH", raising=False)
    logs: list[str] = []
    summary = asyncio.run(run_scraper_pipeline(
        {
            "TARGET_LEADS": 3,
            "TARGET_MODE": "csv_saved",
            "KEYWORDS": ["plombier"],
            "LOCATIONS": ["Lyon"],
            "EXPANSION_KEYWORDS": [],
            "EXPANSION_LOCATIONS": [],
            "QUERY_PLANNER_USE_DEPARTMENTS": False,
            "OUTSCRAPER_API_KEY": "dry-run-key",
            "OUTSCRAPER_BATCH_SIZE": 5,
            "OUTSCRAPER_CONCURRENCY": 1,
            "OUTSCRAPER_LIMIT_PER_QUERY": 5,
            "EXCLUDE_DOMAINS": [],
            "ENRICH_ENABLED": False,
            "PRESET_ID": "plombier",
        },
        log_cb=logs.append,
        progress_cb=lambda _progress: None,
        metric_cb=lambda *_args: None,
        dry_run=True,
        push_to_instantly=False,
        preset="plombier",
    ))
    assert summary["dry_run"] is True
    assert summary["queries_total"] >= 1
    text = "\n".join(logs)
    log_path = Path(scrape_log_path(str(tmp_path / "streamlit_scraper" / "output" / "plombier")))
    if log_path.is_file():
        text += "\n" + log_path.read_text(encoding="utf-8")
    _assert_clean(text)
    assert "zero Outscraper requests made" in text


def test_central_lead_write_failure_is_not_swallowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    activate_output_paths("plombier")
    from core_logic import (
        _active,
        _append_lead_row,
        _flush_pending_lead_rows_sync,
        _reset_lead_save_buffer,
        _retry_unpersisted_leads,
        _sidecar_path,
    )

    _reset_lead_save_buffer()

    def boom(_rows: list, *, preset: str) -> dict:
        raise RuntimeError(f"schema mismatch for {preset}")

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", boom)
    _append_lead_row({"Email": "a@ex.fr", "Company": "A"})
    with pytest.raises(RuntimeError, match="schema mismatch"):
        _flush_pending_lead_rows_sync()
    csv_path = Path(_active.csv)
    if csv_path.exists():
        assert "a@ex.fr" not in csv_path.read_text(encoding="utf-8")
    sidecar = Path(_sidecar_path()).read_text(encoding="utf-8")
    assert "a@ex.fr" in sidecar

    def ok(rows: list, *, preset: str) -> dict:
        assert preset == "plombier"
        return {"inserted": len(rows), "updated": 0, "skipped": 0}

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", ok)
    _reset_lead_save_buffer()
    asyncio.run(_retry_unpersisted_leads())
    assert "a@ex.fr" in csv_path.read_text(encoding="utf-8")
    assert not Path(_sidecar_path()).exists()


def test_lead_saves_are_batched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    activate_output_paths("plombier")
    from core_logic import LEAD_SAVE_BATCH, _active, _append_lead_row, _reset_lead_save_buffer

    _reset_lead_save_buffer()
    calls: list[int] = []

    def record(rows: list, *, preset: str) -> dict:
        calls.append(len(rows))
        return {"inserted": len(rows), "updated": 0, "skipped": 0}

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", record)
    for index in range(LEAD_SAVE_BATCH):
        _append_lead_row({"Email": f"user{index}@ex.fr", "Company": "A"})
    assert calls == [LEAD_SAVE_BATCH]
    text = Path(_active.csv).read_text(encoding="utf-8")
    assert "user0@ex.fr" in text
    assert f"user{LEAD_SAVE_BATCH - 1}@ex.fr" in text


def test_failed_save_stops_the_run_and_resume_refetches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    calls: list[list[str]] = []
    saves = {"n": 0}

    async def fake_search(self, queries, limit, **kwargs):  # noqa: ANN001
        calls.append(list(queries))
        city = "lyon" if any("Lyon" in query for query in queries) else "paris"
        return [
            [
                {
                    "name": "Dupont",
                    "site": f"https://{city}.fr",
                    "email": f"{city}@ex.fr",
                    "phone": "+33184801234",
                    "place_id": city,
                    "city": city,
                    "type": "Plombier",
                    "category": "Plumber",
                }
            ]
        ]

    def persist(rows: list, *, preset: str) -> dict:
        saves["n"] += 1
        if saves["n"] == 1:
            raise RuntimeError("schema mismatch")
        return {"inserted": len(rows), "updated": 0, "skipped": 0}

    monkeypatch.setattr("core_logic.OutscraperClient.google_maps_search_batch", fake_search)
    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)
    from core_logic import LeadPersistenceError, output_paths, run_scraper_pipeline

    config = {
        "TARGET_LEADS": 20,
        "TARGET_MODE": "csv_saved",
        "KEYWORDS": ["plombier"],
        "LOCATIONS": ["Lyon", "Paris"],
        "EXPANSION_KEYWORDS": [],
        "EXPANSION_LOCATIONS": [],
        "QUERY_PLANNER_USE_DEPARTMENTS": False,
        "OUTSCRAPER_API_KEY": "test-key",
        "OUTSCRAPER_BATCH_SIZE": 1,
        "OUTSCRAPER_CONCURRENCY": 1,
        "OUTSCRAPER_LIMIT_PER_QUERY": 5,
        "EXCLUDE_DOMAINS": [],
        "ENRICH_ENABLED": False,
        "PRESET_ID": "plombier",
        "SERVICE_DEFAULT": "Plomberie",
        "SERVICE_RULES": [],
    }

    def _run(*, resume: bool) -> dict:
        return asyncio.run(
            run_scraper_pipeline(
                config,
                log_cb=lambda _message: None,
                progress_cb=lambda _progress: None,
                metric_cb=lambda *_args: None,
                dry_run=False,
                push_to_instantly=False,
                resume=resume,
                preset="plombier",
            )
        )

    with pytest.raises(LeadPersistenceError, match="schema mismatch"):
        _run(resume=False)
    assert len(calls) == 1
    assert "Lyon" in calls[0][0]
    csv_path = Path(output_paths("plombier").csv)
    if csv_path.exists():
        assert "lyon@ex.fr" not in csv_path.read_text(encoding="utf-8")

    summary = _run(resume=True)
    assert summary["leads_saved"] >= 1
    assert len(calls) >= 2
    assert "Lyon" in calls[1][0]
    assert any("Paris" in query for batch in calls[1:] for query in batch)
    text = csv_path.read_text(encoding="utf-8")
    assert "lyon@ex.fr" in text
    assert "paris@ex.fr" in text


def test_reset_deletes_pending_supabase_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    from core_logic import _sidecar_path, activate_output_paths, clear_local_leads

    activate_output_paths("plombier")
    sidecar = Path(_sidecar_path())
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text('{"Email": "a@ex.fr"}\n', encoding="utf-8")
    asyncio.run(clear_local_leads(cancel_remote=False, preset="plombier"))
    assert not sidecar.exists()


def test_permanent_reject_does_not_block_the_next_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    from core_logic import (
        _rejected_sidecar_path,
        _reset_lead_save_buffer,
        _retry_unpersisted_leads,
        _sidecar_path,
        activate_output_paths,
    )

    activate_output_paths("plombier")
    _reset_lead_save_buffer()
    sidecar = Path(_sidecar_path())
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    long_email = ("a" * 320) + "@ex.fr"
    sidecar.write_text(
        '{"Email": "%s", "Company": "Bad"}\n{"Email": "ok@ex.fr", "Company": "Ok"}\n' % long_email,
        encoding="utf-8",
    )
    seen: list[str] = []

    def persist(rows: list, *, preset: str) -> dict:
        seen.extend(str(row.get("Email") or "") for row in rows)
        return {"inserted": len(rows), "updated": 0, "skipped": 0}

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)
    assert asyncio.run(_retry_unpersisted_leads()) is None
    assert seen == ["ok@ex.fr"]
    assert not sidecar.exists()
    rejected = Path(_rejected_sidecar_path()).read_text(encoding="utf-8")
    assert long_email in rejected
    assert "exceeds 320" in rejected
    _reset_lead_save_buffer()
    assert asyncio.run(_retry_unpersisted_leads()) is None
    assert seen == ["ok@ex.fr"]


def test_postgres_data_errors_move_to_rejected_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from postgrest.exceptions import APIError

    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    from core_logic import (
        LeadPersistenceError,
        _rejected_sidecar_path,
        _reset_lead_save_buffer,
        _retry_unpersisted_leads,
        _sidecar_path,
        activate_output_paths,
    )

    activate_output_paths("plombier")
    _reset_lead_save_buffer()
    sidecar = Path(_sidecar_path())
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        "\n".join(
            [
                '{"Email": "ok-a@ex.fr", "Company": "A"}',
                '{"Email": "bad@ex.fr", "Company": "Bad"}',
                '{"Email": "ok-b@ex.fr", "Company": "B"}',
                "",
            ]
        ),
        encoding="utf-8",
    )
    saved: list[str] = []
    attempts = {"n": 0}

    def persist(rows: list, *, preset: str) -> dict:
        attempts["n"] += 1
        emails = [str(row.get("Email") or "") for row in rows]
        if "bad@ex.fr" in emails:
            raise APIError({"message": "value too long for type character varying(320)", "code": "22001"})
        saved.extend(emails)
        return {"inserted": len(rows), "updated": 0, "skipped": 0}

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)
    assert asyncio.run(_retry_unpersisted_leads()) is None
    assert set(saved) == {"ok-a@ex.fr", "ok-b@ex.fr"}
    assert "bad@ex.fr" not in saved
    assert not sidecar.exists()
    rejected = Path(_rejected_sidecar_path()).read_text(encoding="utf-8")
    assert "bad@ex.fr" in rejected
    assert "22001" in rejected
    calls_after_save = attempts["n"]
    _reset_lead_save_buffer()
    assert asyncio.run(_retry_unpersisted_leads()) is None
    assert attempts["n"] > calls_after_save
    rejected_again = Path(_rejected_sidecar_path()).read_text(encoding="utf-8")
    assert rejected_again.count("bad@ex.fr") == 1

    _reset_lead_save_buffer()
    sidecar.write_text('{"Email": "wide@ex.fr", "Company": "Wide"}\n', encoding="utf-8")

    def persist_check(rows: list, *, preset: str) -> dict:
        raise APIError({"message": "new row violates check constraint leads_category_check", "code": "23514"})

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist_check)
    assert asyncio.run(_retry_unpersisted_leads()) is None
    rejected = Path(_rejected_sidecar_path()).read_text(encoding="utf-8")
    assert "wide@ex.fr" in rejected
    assert "23514" in rejected
    assert not sidecar.exists()
    _reset_lead_save_buffer()
    assert asyncio.run(_retry_unpersisted_leads()) is None

    _reset_lead_save_buffer()
    sidecar.write_text('{"Email": "unicode@ex.fr", "Company": "Unicode"}\n', encoding="utf-8")

    def persist_unicode(rows: list, *, preset: str) -> dict:
        raise RuntimeError("unsupported Unicode escape sequence (SQLSTATE 22P05)")

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist_unicode)
    assert asyncio.run(_retry_unpersisted_leads()) is None
    rejected = Path(_rejected_sidecar_path()).read_text(encoding="utf-8")
    assert "unicode@ex.fr" in rejected
    assert "22P05" in rejected
    assert not sidecar.exists()

    _reset_lead_save_buffer()
    sidecar.write_text('{"Email": "later@ex.fr", "Company": "Later"}\n', encoding="utf-8")

    def persist_transient(rows: list, *, preset: str) -> dict:
        raise APIError({"message": "duplicate key value violates unique constraint", "code": "23505"})

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist_transient)
    with pytest.raises(LeadPersistenceError):
        asyncio.run(_retry_unpersisted_leads())
    assert "later@ex.fr" in sidecar.read_text(encoding="utf-8")


def test_all_bad_batch_stops_the_run_without_more_outscraper_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from postgrest.exceptions import APIError

    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    calls: list[list[str]] = []
    attempts = {"n": 0}
    solo: list[str] = []

    async def fake_search(self, queries, limit, **kwargs):  # noqa: ANN001
        calls.append(list(queries))
        city = queries[0].split(" in ", 1)[1].split(",", 1)[0].lower()
        return [
            [
                {
                    "name": city,
                    "site": f"https://{city}.fr",
                    "email": f"{city}@ex.fr",
                    "phone": "+33184801234",
                    "place_id": city,
                    "city": city,
                    "type": "Plombier",
                    "category": "Plumber",
                }
            ]
        ]

    def persist(rows: list, *, preset: str) -> dict:
        del preset
        attempts["n"] += 1
        emails = [str(row.get("Email") or "") for row in rows]
        if len(emails) == 1:
            solo.append(emails[0])
        raise APIError({"message": "value too long for type character varying(320)", "code": "22001"})

    monkeypatch.setattr("core_logic.OutscraperClient.google_maps_search_batch", fake_search)
    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)
    from core_logic import (
        LeadRejectionStormError,
        _rejected_sidecar_path,
        _sidecar_path,
        output_paths,
        run_scraper_pipeline,
    )

    config = {
        "TARGET_LEADS": 200,
        "TARGET_MODE": "csv_saved",
        "KEYWORDS": ["plombier"],
        "LOCATIONS": [f"City{index:02d}" for index in range(12)],
        "EXPANSION_KEYWORDS": [],
        "EXPANSION_LOCATIONS": [],
        "QUERY_PLANNER_USE_DEPARTMENTS": False,
        "OUTSCRAPER_API_KEY": "test-key",
        "OUTSCRAPER_BATCH_SIZE": 1,
        "OUTSCRAPER_CONCURRENCY": 1,
        "OUTSCRAPER_LIMIT_PER_QUERY": 5,
        "EXCLUDE_DOMAINS": [],
        "ENRICH_ENABLED": False,
        "PRESET_ID": "plombier",
        "SERVICE_DEFAULT": "Plomberie",
        "SERVICE_RULES": [],
    }
    with pytest.raises(LeadRejectionStormError, match="schema mismatch"):
        asyncio.run(
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
    assert len(calls) == 10
    assert all("City10" not in query and "City11" not in query for batch in calls for query in batch)
    paths = output_paths("plombier")
    sidecar = Path(_sidecar_path())
    assert not sidecar.exists()
    rejected = Path(_rejected_sidecar_path()).read_text(encoding="utf-8")
    assert rejected.count("@ex.fr") == 10
    state_path = Path(paths.scrape_state)
    state = __import__("json").loads(state_path.read_text(encoding="utf-8"))
    assert set(state["planner"]["exhausted_slots"]) == set(range(9))
    assert "9" not in state["planner"]["slot_skips"]

    from core_logic import MAX_SUPABASE_CALLS_PER_FLUSH, _reset_lead_save_buffer, _retry_unpersisted_leads

    _reset_lead_save_buffer()
    rejected_path = Path(_rejected_sidecar_path())
    if rejected_path.exists():
        rejected_path.unlink()
    attempts["n"] = 0
    solo.clear()
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'{{"Email": "user{index}@ex.fr", "Company": "Co"}}' for index in range(50)]
    sidecar.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(LeadRejectionStormError, match="schema mismatch"):
        asyncio.run(_retry_unpersisted_leads())
    assert 1 <= attempts["n"] <= MAX_SUPABASE_CALLS_PER_FLUSH * 3
    rejected_emails = _jsonl_emails(_rejected_sidecar_path())
    rejected_emails = {email for email in rejected_emails if email.startswith("user")}
    pending_emails = _jsonl_emails(sidecar)
    proven = {email for email in solo if email.startswith("user")}
    assert rejected_emails == proven
    assert rejected_emails.isdisjoint(pending_emails)
    assert rejected_emails | pending_emails == {f"user{index}@ex.fr" for index in range(50)}
    assert pending_emails
    assert sidecar.exists()


def test_concurrent_flushes_reject_each_email_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    from postgrest.exceptions import APIError

    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    from core_logic import (
        _PENDING_LEAD_ROWS,
        _append_sidecar,
        _rejected_sidecar_path,
        _reset_lead_save_buffer,
        _flush_pending_lead_rows_async,
        activate_output_paths,
    )

    activate_output_paths("plombier")
    _reset_lead_save_buffer()
    rows = [{"Email": f"ok{index}@ex.fr", "Company": "Ok"} for index in range(6)]
    rows.append({"Email": "bad@ex.fr", "Company": "Bad"})
    saved: list[str] = []

    def persist(batch: list, *, preset: str) -> dict:
        del preset
        time.sleep(0.02)
        emails = [str(row.get("Email") or "") for row in batch]
        if "bad@ex.fr" in emails:
            raise APIError({"message": "value too long", "code": "22001"})
        saved.extend(emails)
        return {"inserted": len(emails), "updated": 0, "skipped": 0}

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)
    for row in rows:
        _PENDING_LEAD_ROWS.append(row)
        _append_sidecar(row)

    async def _flush_together() -> None:
        await asyncio.gather(
            _flush_pending_lead_rows_async(),
            _flush_pending_lead_rows_async(),
            _flush_pending_lead_rows_async(),
        )

    asyncio.run(_flush_together())
    assert sorted(saved) == sorted(f"ok{index}@ex.fr" for index in range(6))
    assert saved.count("ok0@ex.fr") == 1
    rejected_lines = [
        line
        for line in Path(_rejected_sidecar_path()).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rejected_lines) == 1
    assert "bad@ex.fr" in rejected_lines[0]


def test_reject_ratio_is_configurable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from postgrest.exceptions import APIError

    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("HERCULE_REJECT_STOP_RATIO", "0.20")
    monkeypatch.setenv("HERCULE_REJECT_MIN_SAMPLE", "4")
    from core_logic import (
        LeadRejectionStormError,
        _reset_lead_save_buffer,
        _retry_unpersisted_leads,
        _sidecar_path,
        activate_output_paths,
    )

    activate_output_paths("plombier")
    _reset_lead_save_buffer()
    sidecar = Path(_sidecar_path())
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        "\n".join(
            [
                '{"Email": "ok1@ex.fr", "Company": "A"}',
                '{"Email": "bad1@ex.fr", "Company": "B"}',
                '{"Email": "ok2@ex.fr", "Company": "C"}',
                '{"Email": "bad2@ex.fr", "Company": "D"}',
                "",
            ]
        ),
        encoding="utf-8",
    )

    def persist(rows: list, *, preset: str) -> dict:
        del preset
        emails = [str(row.get("Email") or "") for row in rows]
        if any(email.startswith("bad") for email in emails):
            raise APIError({"message": "check violation", "code": "23514"})
        return {"inserted": len(rows), "updated": 0, "skipped": 0}

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)
    with pytest.raises(LeadRejectionStormError, match="schema mismatch"):
        asyncio.run(_retry_unpersisted_leads())

    monkeypatch.setenv("HERCULE_REJECT_MIN_SAMPLE", "100")
    _reset_lead_save_buffer()
    sidecar.write_text(
        "\n".join(
            [
                '{"Email": "ok3@ex.fr", "Company": "A"}',
                '{"Email": "bad3@ex.fr", "Company": "B"}',
                '{"Email": "ok4@ex.fr", "Company": "C"}',
                '{"Email": "bad4@ex.fr", "Company": "D"}',
                "",
            ]
        ),
        encoding="utf-8",
    )
    assert asyncio.run(_retry_unpersisted_leads()) is None


def _jsonl_emails(path: str | Path) -> set[str]:
    import json

    file_path = Path(path)
    if not file_path.is_file():
        return set()
    emails: set[str] = set()
    for line in file_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        item = json.loads(text)
        email = str(item.get("Email") or "").strip().lower()
        if email:
            emails.add(email)
    return emails


def _csv_emails(path: str | Path) -> set[str]:
    file_path = Path(path)
    if not file_path.is_file():
        return set()
    emails: set[str] = set()
    for line in file_path.read_text(encoding="utf-8").splitlines()[1:]:
        email = line.split(",", 1)[0].strip().lower()
        if "@" in email:
            emails.add(email)
    return emails


def _plombier_pipeline_config(
    locations: list[str],
    *,
    concurrency: int,
    target: int,
    limit: int,
) -> dict:
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


def _run_plombier(config: dict, *, resume: bool) -> dict:
    return asyncio.run(
        run_scraper_pipeline(
            config,
            log_cb=lambda _message: None,
            progress_cb=lambda _progress: None,
            metric_cb=lambda *_args: None,
            dry_run=False,
            push_to_instantly=False,
            resume=resume,
            preset="plombier",
        )
    )


@pytest.mark.parametrize("concurrency", [3, 6])
def test_sparse_permanent_errors_do_not_stop_a_concurrent_run(
    concurrency: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """About 10% bad rows at concurrency 3 and 6: reject only those rows."""
    from postgrest.exceptions import APIError

    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    locations = [f"city{index}" for index in range(6)]
    per_city = 10
    bad = {f"city{index}-0@ex.fr" for index in range(6)}
    good = {f"city{city}-{lead}@ex.fr" for city in range(6) for lead in range(1, per_city)}

    async def fake_search(self, queries, limit, **kwargs):  # noqa: ANN001
        del self, limit, kwargs
        found = []
        for query in queries:
            city = query.split(" in ", 1)[1].split(",", 1)[0]
            found.append(
                [
                    {
                        "name": f"{city} {lead}",
                        "site": f"https://{city}-{lead}.fr",
                        "email": f"{city}-{lead}@ex.fr",
                        "phone": "+33184801234",
                        "place_id": f"{city}-{lead}",
                        "city": city,
                        "type": "Plombier",
                        "category": "Plumber",
                    }
                    for lead in range(per_city)
                ]
            )
        return found

    def persist(rows: list, *, preset: str) -> dict:
        del preset
        emails = [str(row.get("Email") or "") for row in rows]
        if any(email in bad for email in emails):
            raise APIError({"message": "value too long for type character varying(320)", "code": "22001"})
        return {"inserted": len(rows), "updated": 0, "skipped": 0}

    monkeypatch.setattr("core_logic.OutscraperClient.google_maps_search_batch", fake_search)
    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)
    from core_logic import _rejected_sidecar_path, _sidecar_path, output_paths

    _run_plombier(
        _plombier_pipeline_config(locations, concurrency=concurrency, target=200, limit=20),
        resume=False,
    )
    rejected_lines = [
        line
        for line in Path(_rejected_sidecar_path()).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rejected_lines) == len(bad)
    assert _jsonl_emails(_rejected_sidecar_path()) == bad
    saved = _csv_emails(output_paths("plombier").csv)
    assert good <= saved
    assert bad.isdisjoint(saved)
    assert not Path(_sidecar_path()).exists()


@pytest.mark.parametrize("bad_indexes", [(1, 40), (0, 25, 49), (0, 7, 25, 49)])
def test_few_bad_rows_in_a_full_batch_reject_only_those_rows(
    bad_indexes: tuple[int, ...], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from postgrest.exceptions import APIError

    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    from core_logic import (
        _rejected_sidecar_path,
        _reset_lead_save_buffer,
        _retry_unpersisted_leads,
        _sidecar_path,
        activate_output_paths,
        output_paths,
    )

    activate_output_paths("plombier")
    _reset_lead_save_buffer()
    bad = {f"user{index}@ex.fr" for index in bad_indexes}
    good = {f"user{index}@ex.fr" for index in range(50)} - bad
    sidecar = Path(_sidecar_path())
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'{{"Email": "user{index}@ex.fr", "Company": "Co"}}' for index in range(50)]
    sidecar.write_text("\n".join(lines) + "\n", encoding="utf-8")
    attempts = {"n": 0}

    def persist(rows: list, *, preset: str) -> dict:
        del preset
        attempts["n"] += 1
        emails = [str(row.get("Email") or "") for row in rows]
        if any(email in bad for email in emails):
            raise APIError({"message": "value too long for type character varying(320)", "code": "22001"})
        return {"inserted": len(rows), "updated": 0, "skipped": 0}

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)
    assert asyncio.run(_retry_unpersisted_leads()) is None
    assert attempts["n"] < 99
    assert _jsonl_emails(_rejected_sidecar_path()) == bad
    saved = _csv_emails(output_paths("plombier").csv)
    assert good <= saved
    assert bad.isdisjoint(saved)
    assert not sidecar.exists()


def test_second_event_loop_can_flush_overlapping_saves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    from core_logic import (
        _flush_pending_lead_rows_async,
        _queue_lead_row_async,
        _reset_lead_save_buffer,
        _sidecar_path,
        activate_output_paths,
        output_paths,
    )

    activate_output_paths("plombier")
    _reset_lead_save_buffer()
    saved: list[str] = []

    def persist(rows: list, *, preset: str) -> dict:
        del preset
        saved.extend(str(row.get("Email") or "") for row in rows)
        return {"inserted": len(rows), "updated": 0, "skipped": 0}

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)

    async def _overlap(emails: list[str]) -> None:
        async def _one(email: str) -> None:
            await _queue_lead_row_async({"Email": email, "Company": email})

        await asyncio.gather(*(_one(email) for email in emails))
        await _flush_pending_lead_rows_async()

    asyncio.run(_overlap(["a1@ex.fr", "a2@ex.fr"]))
    asyncio.run(_overlap(["b1@ex.fr", "b2@ex.fr"]))
    assert sorted(saved) == ["a1@ex.fr", "a2@ex.fr", "b1@ex.fr", "b2@ex.fr"]
    assert _csv_emails(output_paths("plombier").csv) == {"a1@ex.fr", "a2@ex.fr", "b1@ex.fr", "b2@ex.fr"}
    assert not Path(_sidecar_path()).exists()


def test_storm_stop_then_fixed_fault_resumes_with_every_good_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from postgrest.exceptions import APIError

    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    calls: list[list[str]] = []
    fault = {"on": True}

    async def fake_search(self, queries, limit, **kwargs):  # noqa: ANN001
        del self, limit, kwargs
        calls.append(list(queries))
        query = queries[0]
        if "Lyon" in query:
            return [
                [
                    {
                        "name": f"Lyon {index}",
                        "site": f"https://lyon{index}.fr",
                        "email": f"lyon{index}@ex.fr",
                        "phone": "+33184801234",
                        "place_id": f"lyon{index}",
                        "city": "Lyon",
                        "type": "Plombier",
                        "category": "Plumber",
                    }
                    for index in range(30)
                ]
            ]
        return [
            [
                {
                    "name": "Paris",
                    "site": "https://paris.fr",
                    "email": "paris@ex.fr",
                    "phone": "+33184801234",
                    "place_id": "paris",
                    "city": "Paris",
                    "type": "Plombier",
                    "category": "Plumber",
                }
            ]
        ]

    def persist(rows: list, *, preset: str) -> dict:
        del preset
        if fault["on"]:
            raise APIError({"message": "value too long for type character varying(320)", "code": "22001"})
        return {"inserted": len(rows), "updated": 0, "skipped": 0}

    monkeypatch.setattr("core_logic.OutscraperClient.google_maps_search_batch", fake_search)
    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)
    from core_logic import (
        LeadRejectionStormError,
        _rejected_sidecar_path,
        _sidecar_path,
        output_paths,
    )

    config = _plombier_pipeline_config(
        ["Lyon", "Paris"], concurrency=1, target=400, limit=100
    )
    with pytest.raises(LeadRejectionStormError, match="schema mismatch"):
        _run_plombier(config, resume=False)
    assert len(calls) == 1
    assert "Lyon" in calls[0][0]
    lyon = {f"lyon{index}@ex.fr" for index in range(30)}
    rejected = _jsonl_emails(_rejected_sidecar_path())
    pending = _jsonl_emails(_sidecar_path())
    assert rejected
    assert pending
    assert rejected.isdisjoint(pending)
    assert rejected | pending == lyon
    state_path = Path(output_paths("plombier").scrape_state)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["planner"]["slot_skips"] == {}
    assert state["planner"]["exhausted_slots"] == []

    fault["on"] = False
    summary = _run_plombier(config, resume=True)
    assert summary["leads_saved"] >= 31
    assert any("Lyon" in query for query in calls[1])
    assert any("Paris" in query for batch in calls[2:] for query in batch)
    saved = _csv_emails(output_paths("plombier").csv)
    assert lyon <= saved
    assert "paris@ex.fr" in saved
    assert not Path(_sidecar_path()).exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(state["planner"]["exhausted_slots"]) == {0, 1}
    assert all(int(value) == 0 for value in state["planner"]["slot_skips"].values())


def test_retry_upserts_a_row_already_written_to_the_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    from core_logic import (
        _reset_lead_save_buffer,
        _retry_unpersisted_leads,
        _sidecar_path,
        activate_output_paths,
        output_paths,
    )

    activate_output_paths("plombier")
    _reset_lead_save_buffer()
    csv_path = Path(output_paths("plombier").csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("Email,Company\nalready@ex.fr,Already\n", encoding="utf-8")
    sidecar = Path(_sidecar_path())
    sidecar.write_text('{"Email": "already@ex.fr", "Company": "Already"}\n', encoding="utf-8")
    seen: list[str] = []

    def persist(rows: list, *, preset: str) -> dict:
        del preset
        seen.extend(str(row.get("Email") or "") for row in rows)
        return {"inserted": len(rows), "updated": 0, "skipped": 0}

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)
    assert asyncio.run(_retry_unpersisted_leads()) is None
    assert seen == ["already@ex.fr"]
    assert not sidecar.exists()
    assert csv_path.read_text(encoding="utf-8").lower().count("already@ex.fr") == 1


@pytest.mark.parametrize("concurrency", [3, 6])
def test_one_row_flushes_do_not_storm(
    concurrency: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One proven bad row per flush must not stop a concurrent run."""
    from postgrest.exceptions import APIError

    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    from core_logic import (
        _FLUSH_THREAD_LOCK,
        _PENDING_LEAD_ROWS,
        _append_sidecar,
        _flush_async_lock,
        _flush_one_pending_pass,
        _rejected_sidecar_path,
        _reset_lead_save_buffer,
        _sidecar_path,
        activate_output_paths,
        output_paths,
    )

    activate_output_paths("plombier")
    _reset_lead_save_buffer()
    bad = {f"bad{index}@ex.fr" for index in range(3)}
    good = {f"good{index}@ex.fr" for index in range(27)}
    order = [f"good{index}@ex.fr" for index in range(27)]
    for index, email in enumerate(sorted(bad)):
        order.insert(index * 9, email)

    def persist(rows: list, *, preset: str) -> dict:
        del preset
        emails = [str(row.get("Email") or "") for row in rows]
        if any(email in bad for email in emails):
            raise APIError({"message": "value too long for type character varying(320)", "code": "22001"})
        return {"inserted": len(rows), "updated": 0, "skipped": 0}

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)
    semaphore = asyncio.Semaphore(concurrency)

    async def _one(email: str) -> None:
        row = {"Email": email, "Company": "Co"}

        def _body() -> None:
            with _FLUSH_THREAD_LOCK:
                _PENDING_LEAD_ROWS.append(row)
                _append_sidecar(row)
            _flush_one_pending_pass()

        async with semaphore:
            async with _flush_async_lock():
                await asyncio.to_thread(_body)

    async def _all() -> None:
        await asyncio.gather(*(_one(email) for email in order))

    asyncio.run(_all())
    assert _jsonl_emails(_rejected_sidecar_path()) == bad
    saved = _csv_emails(output_paths("plombier").csv)
    assert good <= saved
    assert bad.isdisjoint(saved)
    assert not Path(_sidecar_path()).exists()


def test_fault_rejected_rows_are_saved_after_the_fault_is_fixed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from postgrest.exceptions import APIError

    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    from core_logic import (
        _rejected_sidecar_path,
        _reset_lead_save_buffer,
        _retry_unpersisted_leads,
        _sidecar_path,
        activate_output_paths,
        output_paths,
    )

    activate_output_paths("plombier")
    _reset_lead_save_buffer()
    sidecar = Path(_sidecar_path())
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        "\n".join(
            [
                '{"Email": "good1@ex.fr", "Company": "A"}',
                '{"Email": "good2@ex.fr", "Company": "B"}',
                '{"Email": "still@ex.fr", "Company": "C"}',
                "",
            ]
        ),
        encoding="utf-8",
    )
    fault = {"on": True}

    def persist(rows: list, *, preset: str) -> dict:
        del preset
        emails = [str(row.get("Email") or "") for row in rows]
        if fault["on"] or any(email == "still@ex.fr" for email in emails):
            code = "22001" if any(email == "still@ex.fr" for email in emails) else "23514"
            raise APIError({"message": "permanent data error", "code": code})
        return {"inserted": len(rows), "updated": 0, "skipped": 0}

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)
    assert asyncio.run(_retry_unpersisted_leads()) is None
    assert _jsonl_emails(_rejected_sidecar_path()) == {"good1@ex.fr", "good2@ex.fr", "still@ex.fr"}
    assert not sidecar.exists()

    fault["on"] = False
    _reset_lead_save_buffer()
    assert asyncio.run(_retry_unpersisted_leads()) is None
    saved = _csv_emails(output_paths("plombier").csv)
    assert {"good1@ex.fr", "good2@ex.fr"} <= saved
    assert "still@ex.fr" not in saved
    assert _jsonl_emails(_rejected_sidecar_path()) == {"still@ex.fr"}
    assert not sidecar.exists()


def test_one_flush_stays_within_the_call_cap_and_drain_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from postgrest.exceptions import APIError

    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    from core_logic import (
        MAX_SUPABASE_CALLS_PER_FLUSH,
        _PENDING_LEAD_ROWS,
        _append_sidecar,
        _rejected_sidecar_path,
        _reset_lead_save_buffer,
        _save_pending_batch,
        activate_output_paths,
        output_paths,
    )

    activate_output_paths("plombier")
    _reset_lead_save_buffer()
    pattern = (["b", "b", "g"] * 10) + (["b", "g"] * 10)
    assert pattern.count("b") == 30 and pattern.count("g") == 20
    bad: set[str] = set()
    good: set[str] = set()
    rows: list[dict[str, str]] = []
    for index, kind in enumerate(pattern):
        email = f"user{index}@ex.fr"
        (bad if kind == "b" else good).add(email)
        row = {"Email": email, "Company": "Co"}
        rows.append(row)
        _PENDING_LEAD_ROWS.append(row)
        _append_sidecar(row)
    attempts = {"n": 0}

    def persist(batch: list, *, preset: str) -> dict:
        del preset
        attempts["n"] += 1
        emails = [str(row.get("Email") or "") for row in batch]
        if any(email in bad for email in emails):
            raise APIError({"message": "value too long", "code": "22001"})
        return {"inserted": len(rows), "updated": 0, "skipped": 0}

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)
    _save_pending_batch(list(rows))
    assert attempts["n"] == MAX_SUPABASE_CALLS_PER_FLUSH
    assert _jsonl_emails(_rejected_sidecar_path()).isdisjoint(good)
    saved = _csv_emails(output_paths("plombier").csv)
    assert bad.isdisjoint(saved)
    assert _PENDING_LEAD_ROWS


def test_scrape_spend_plan_caps_places_at_the_target() -> None:
    from core_logic import format_scrape_spend, scrape_spend_plan

    plan = scrape_spend_plan({"OUTSCRAPER_ENRICHMENT": ["leads_n_contacts"]}, target=100)
    assert plan["places"] == 100
    assert plan["worst_case_usd"] == 0.6
    text = format_scrape_spend(plan)
    assert "worst case $0.60" in text
    assert "at most 100 places" in text
    tiny = scrape_spend_plan(
        {"OUTSCRAPER_ENRICHMENT": ["leads_n_contacts"], "MAX_SCRAPE_COST_USD": 0.001},
        target=100,
    )
    assert tiny["refused"] is True
    assert tiny["places"] == 0


def test_spend_cap_bounds_places_before_any_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    calls: list[tuple[int, int]] = []
    logs: list[str] = []

    async def fake_search(self, queries, limit, **kwargs):  # noqa: ANN001
        del self, kwargs
        calls.append((len(queries), int(limit)))
        found = []
        for index, query in enumerate(queries):
            city = query.split(" in ", 1)[1].split(",", 1)[0]
            found.append(
                [
                    {
                        "name": city,
                        "site": f"https://{city}.fr",
                        "email": f"{city}@ex.fr",
                        "phone": "+33184801234",
                        "place_id": city,
                        "city": city,
                        "type": "Plombier",
                        "category": "Plumber",
                    }
                ]
            )
        return found

    def persist(rows: list, *, preset: str) -> dict:
        del preset
        return {"inserted": len(rows), "updated": 0, "skipped": 0}

    monkeypatch.setattr("core_logic.OutscraperClient.google_maps_search_batch", fake_search)
    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)
    from core_logic import run_scraper_pipeline

    locations = [f"City{index:02d}" for index in range(30)]
    config = _plombier_pipeline_config(locations, concurrency=6, target=100, limit=50)
    config["OUTSCRAPER_BATCH_SIZE"] = 25
    config["OUTSCRAPER_ENRICHMENT"] = ["leads_n_contacts"]
    config["MAX_SCRAPE_COST_USD"] = 10
    asyncio.run(
        run_scraper_pipeline(
            config,
            log_cb=logs.append,
            progress_cb=lambda _progress: None,
            metric_cb=lambda *_args: None,
            dry_run=False,
            push_to_instantly=False,
            preset="plombier",
        )
    )
    requested = sum(count * limit for count, limit in calls)
    assert requested <= 100
    assert requested > 0
    assert any("worst case" in line for line in logs)

    calls.clear()
    from core_logic import output_paths

    out_dir = Path(output_paths("plombier").out_dir)
    for child in out_dir.iterdir():
        if child.is_file():
            child.unlink()
    config["MAX_SCRAPE_COST_USD"] = 0.001
    with pytest.raises(SystemExit, match="Refusing scrape"):
        asyncio.run(
            run_scraper_pipeline(
                config,
                log_cb=logs.append,
                progress_cb=lambda _progress: None,
                metric_cb=lambda *_args: None,
                dry_run=False,
                push_to_instantly=False,
                preset="plombier",
            )
        )
    assert calls == []


def test_two_threads_keep_flush_exclusion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    from core_logic import (
        _flush_pending_lead_rows_async,
        _queue_lead_row_async,
        _reset_lead_save_buffer,
        _sidecar_path,
        activate_output_paths,
        output_paths,
    )

    activate_output_paths("plombier")
    _reset_lead_save_buffer()
    saved: list[str] = []
    saved_lock = threading.Lock()

    def persist(rows: list, *, preset: str) -> dict:
        del preset
        with saved_lock:
            saved.extend(str(row.get("Email") or "") for row in rows)
        return {"inserted": len(rows), "updated": 0, "skipped": 0}

    monkeypatch.setattr("shared.central_leads.persist_scraped_leads", persist)

    def _run(emails: list[str]) -> None:
        async def _go() -> None:
            await asyncio.gather(
                *(_queue_lead_row_async({"Email": email, "Company": email}) for email in emails)
            )
            await _flush_pending_lead_rows_async()

        asyncio.run(_go())

    first = threading.Thread(target=_run, args=(["t1a@ex.fr", "t1b@ex.fr"],))
    second = threading.Thread(target=_run, args=(["t2a@ex.fr", "t2b@ex.fr"],))
    first.start()
    second.start()
    first.join()
    second.join()
    assert sorted(saved) == ["t1a@ex.fr", "t1b@ex.fr", "t2a@ex.fr", "t2b@ex.fr"]
    assert _csv_emails(output_paths("plombier").csv) == {
        "t1a@ex.fr",
        "t1b@ex.fr",
        "t2a@ex.fr",
        "t2b@ex.fr",
    }
    assert not Path(_sidecar_path()).exists()


def test_load_config_rejects_an_unmapped_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    from config_loader import load_config
    from shared.central_leads import PRESET_CATEGORY

    monkeypatch.delitem(PRESET_CATEGORY, "plombier")
    with pytest.raises(SystemExit, match="Unknown preset"):
        load_config("plombier", require_keys=False)


def test_taxonomy_push_refuses_uncleaned_leads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HERCULE_ALLOW_UNCLEANED_INSTANTLY_PUSH", raising=False)
    csv_path = tmp_path / "leads.csv"
    csv_path.write_text("Email,Company\na@ex.fr,Dupont\n", encoding="utf-8")
    from core_logic import backfill_taxonomy_push
    from shared.central_leads import InstantlyUncleanedPushError

    with pytest.raises(InstantlyUncleanedPushError):
        asyncio.run(
            backfill_taxonomy_push(
                {
                    "INSTANTLY_API_KEY": "test-key",
                    "INSTANTLY_LIST_ID": "list-1",
                    "TAXONOMY_GATE_ENABLED": False,
                },
                csv_path=str(csv_path),
                state_path=str(tmp_path / "state.json"),
                log_cb=lambda _message: None,
                dry_run=False,
            )
        )
