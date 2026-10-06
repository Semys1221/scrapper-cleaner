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
