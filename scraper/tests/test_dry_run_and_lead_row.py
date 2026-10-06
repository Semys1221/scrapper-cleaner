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
        "TARGET_LEADS": 5,
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
    assert attempts["n"] == calls_after_save

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
