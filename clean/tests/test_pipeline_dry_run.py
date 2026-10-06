"""Cleaner dry-run on a fixture list. No verifier credits and no error logs."""

from __future__ import annotations

import os
import re

import pandas as pd
import pytest

os.environ.setdefault("HERCULE_DATA_ROOT", "/tmp/hercule-clean-tests")

from pipeline import RUN_MODE_DRY, run_cleaning_pipeline  # noqa: E402

_ERROR_RE = re.compile(r"\b(ERROR|WARNING|Traceback|CRITICAL)\b")


def test_dry_run_pipeline_log_has_no_errors(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "quick_verifier._resolve_mx_batch",
        lambda domains, max_workers=8, on_progress=None: {domain: True for domain in domains},
    )
    logs: list[str] = []
    frame = pd.DataFrame(
        [
            {
                "email": "jean@dupont.fr",
                "first_name": "Jean",
                "last_name": "Dupont",
                "company_name": "Dupont Plomberie",
                "website": "dupont.fr",
                "phone": "",
                "category": "PLOMBIER",
            },
            {
                "email": "not-an-email",
                "first_name": "",
                "last_name": "",
                "company_name": "Bad",
                "website": "",
                "phone": "",
                "category": "PLOMBIER",
            },
        ]
    )
    result = run_cleaning_pipeline(
        source_df=frame,
        run_mode=RUN_MODE_DRY,
        custom_limit=None,
        allowed_statuses=["Valid"],
        destination_campaign_id=None,
        email_column="email",
        on_progress=lambda message, _fraction: logs.append(message),
        artifact_prefix="fixture",
    )
    assert result.raw_count == 2
    assert result.quick_rejected_count == 1
    assert result.credits_used == 0
    assert result.run_mode == RUN_MODE_DRY
    bad = [line for line in logs if _ERROR_RE.search(line)]
    assert bad == []
    assert any("Pipeline complete" in line for line in logs)


def test_cleaned_status_write_failure_is_raised(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERCULE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "quick_verifier._resolve_mx_batch",
        lambda domains, max_workers=8, on_progress=None: {domain: True for domain in domains},
    )
    monkeypatch.setattr("pipeline.fetch_mev_credits", lambda: 10)
    monkeypatch.setattr(
        "pipeline.verify_emails_bulk",
        lambda emails, **_kwargs: {str(email).strip().lower(): "Valid" for email in emails},
    )

    def boom(_emails, **_kwargs):
        raise RuntimeError("schema mismatch")

    monkeypatch.setattr("shared.central_leads.mark_emails_cleaned", boom)
    frame = pd.DataFrame(
        [
            {
                "email": "jean@dupont.fr",
                "first_name": "Jean",
                "company_name": "Dupont",
                "website": "dupont.fr",
                "phone": "",
                "category": "PLOMBIER",
            }
        ]
    )
    with pytest.raises(RuntimeError, match="schema mismatch"):
        run_cleaning_pipeline(
            source_df=frame,
            run_mode="custom",
            custom_limit=1,
            allowed_statuses=["Valid"],
            destination_campaign_id=None,
            email_column="email",
            artifact_prefix="fixture-fail",
        )
