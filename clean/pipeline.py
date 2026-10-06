"""Cleaning pipeline: quick verify → MyEmailVerifier → optional Instantly push."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import pandas as pd

from bulk_verifier import fetch_mev_credits, verify_emails_bulk
from clean_column import stamp_cleaned_valid, stamp_verified_cleaned_column
from checkpoint import (
    load_checkpoint,
    save_checkpoint,
    save_partial_verified_csv,
)
from paths import data_dir
from quick_verifier import quick_verify_dataframe

from instantly_client import get_api_key, push_leads_to_campaign, purge_leads_from_list
from instantly_mark_cleaned import mark_cleaned_leads_in_instantly

logger = logging.getLogger(__name__)

RUN_MODE_DRY = "dry_run"
RUN_MODE_TEST_50 = "test_50"
RUN_MODE_FULL = "full"
RUN_MODE_CUSTOM = "custom"


@dataclass
class PipelineResult:
    raw_count: int
    quick_clean_count: int
    quick_rejected_count: int
    verified_count: int
    final_clean_count: int
    rejected_count: int
    credits_used: int
    push_attempted: int
    push_pushed: int
    push_batches: int
    push_skipped_duplicate: int
    purged_count: int
    email_column: str
    run_mode: str
    mark_attempted: int = 0
    mark_patched: int = 0
    mark_failed: int = 0
    mark_skipped_no_lead: int = 0
    artifact_paths: dict[str, str] = field(default_factory=dict)
    quick_stats: dict[str, int] = field(default_factory=dict)
    status_counts: dict[str, int] = field(default_factory=dict)
    credits_before: int | None = None
    credits_remaining: int | None = None
    verified_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    final_clean_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    rejected_df: pd.DataFrame = field(default_factory=pd.DataFrame)


def run_mode_to_verify_label(run_mode: str) -> str:
    if run_mode == RUN_MODE_DRY:
        return "Dry Run (Test logic only, 0 credits)"
    if run_mode == RUN_MODE_TEST_50:
        return "Test Mode (Clean first 50 leads, 50 credits)"
    return "Full Clean (Process entire CSV)"


def estimate_credits(row_count: int, run_mode: str) -> int:
    if run_mode == RUN_MODE_DRY:
        return 0
    return row_count


def estimate_minutes(row_count: int, run_mode: str) -> int:
    credits = estimate_credits(row_count, run_mode)
    if credits == 0:
        return 0
    # Bulk API processes server-side; allow queue overhead (~2 min minimum).
    return max(2, round(credits / 2000))


def _apply_row_limit(
    df: pd.DataFrame,
    run_mode: str,
    custom_limit: int | None,
) -> pd.DataFrame:
    if run_mode == RUN_MODE_TEST_50:
        return df.head(50).copy()
    if run_mode == RUN_MODE_CUSTOM and custom_limit is not None and custom_limit > 0:
        return df.head(custom_limit).copy()
    return df.copy()


def _timestamp_prefix() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _save_csv(df: pd.DataFrame, prefix: str, suffix: str) -> str:
    path = os.path.join(data_dir(), f"{prefix}_{suffix}.csv")
    export = df.copy()
    if "custom_variables" in export.columns:
        export["custom_variables"] = export["custom_variables"].apply(
            lambda value: json.dumps(value) if isinstance(value, dict) else value
        )
    export.to_csv(path, index=False)
    return path


def run_cleaning_pipeline(
    *,
    source_df: pd.DataFrame,
    run_mode: str,
    custom_limit: int | None,
    allowed_statuses: list[str],
    destination_campaign_id: str | None,
    source_list_id: str | None = None,
    purge_source: bool = False,
    email_column: str | None = None,
    on_progress: Callable[[str, float], None] | None = None,
    artifact_prefix: str | None = None,
    resume_prefix: str | None = None,
    skip_quick_verify: bool = False,
) -> PipelineResult:
    prefix = resume_prefix or artifact_prefix or _timestamp_prefix()
    raw_count = len(source_df)

    if skip_quick_verify:
        if not email_column or email_column not in source_df.columns:
            raise ValueError("email_column is required when skip_quick_verify=True")
        quick_clean_df = source_df.copy()
        quick_result_email_col = email_column
        quick_stats = {
            "format_errors": 0,
            "garbage_domains": 0,
            "dns_errors": 0,
            "total_processed": len(source_df),
        }
        quick_rejected_count = 0
        if on_progress:
            on_progress("Skipping quick verify (resuming saved list)...", 0.05)
    else:
        if on_progress:
            on_progress("Running quick local verification (free)...", 0.05)

        quick_result = quick_verify_dataframe(
            source_df,
            email_column=email_column,
            on_progress=lambda current, total: on_progress(
                f"Quick verify: {current}/{total}",
                0.05 + (current / total) * 0.25,
            )
            if on_progress
            else None,
        )
        quick_clean_df = quick_result.clean_df
        quick_result_email_col = quick_result.email_column
        quick_stats = {
            "format_errors": quick_result.format_errors,
            "garbage_domains": quick_result.garbage_domains,
            "dns_errors": quick_result.dns_errors,
            "total_processed": quick_result.total_processed,
        }
        quick_rejected_count = len(quick_result.rejected_df)
    limited_df = _apply_row_limit(quick_clean_df, run_mode, custom_limit)
    is_dry = run_mode == RUN_MODE_DRY

    raw_path = _save_csv(source_df, prefix, "raw")
    quick_path = _save_csv(quick_clean_df, prefix, "quick_clean")

    purged_count = 0
    if purge_source and source_list_id and not is_dry:
        if on_progress:
            on_progress("Purging source list on Instantly...", 0.28)

        def purge_log(message: str) -> None:
            if on_progress:
                on_progress(message, 0.28)

        purged_count = purge_leads_from_list(source_list_id, log_cb=purge_log)
        if on_progress:
            on_progress(f"Purged {purged_count} lead(s) from source list.", 0.29)

    total_emails = len(limited_df)
    email_col = quick_result_email_col
    credits_before: int | None = None
    if not is_dry:
        credits_before = fetch_mev_credits()

    existing_status_map: dict[str, str] = {}
    checkpoint_loaded = load_checkpoint(prefix)
    if checkpoint_loaded:
        existing_status_map, checkpoint_meta = checkpoint_loaded
        if on_progress:
            on_progress(
                f"Loaded checkpoint — {len(existing_status_map)} email(s) already verified.",
                0.29,
            )

    def persist_checkpoint(status_map: dict[str, str]) -> None:
        save_checkpoint(
            prefix,
            status_map,
            total_target=total_emails,
            source_artifact=os.path.join(data_dir(), f"{prefix}_quick_clean.csv"),
        )
        save_partial_verified_csv(prefix, limited_df, email_col, status_map)

    def bulk_progress(message: str, fraction: float) -> None:
        if on_progress:
            on_progress(message, 0.3 + fraction * 0.5)

    emails = limited_df[email_col].astype(str).str.strip().tolist()
    # #region agent log
    try:
        from agent_debug_log import agent_debug_log

        agent_debug_log(
            "pipeline.py:run_cleaning_pipeline",
            "mev_bulk_start",
            {"email_count": len(emails), "run_mode": run_mode, "prefix": prefix},
            "B",
        )
    except Exception:
        pass
    # #endregion
    status_map = verify_emails_bulk(
        emails,
        run_mode=run_mode,
        on_progress=bulk_progress,
        artifact_prefix=prefix,
        existing_status_map=existing_status_map,
        on_status_map_updated=persist_checkpoint if not is_dry else None,
    )
    if not is_dry:
        persist_checkpoint(status_map)
    verification_results = [
        status_map.get(str(email).strip().lower(), "Missing Status")
        for email in limited_df[email_col]
    ]

    verified_df = limited_df.copy()
    verified_df["Verification_Status"] = verification_results
    verified_df = stamp_verified_cleaned_column(verified_df, allowed_statuses)
    verified_path = _save_csv(verified_df, prefix, "verified")

    final_clean_df = verified_df[verified_df["Verification_Status"].isin(allowed_statuses)].copy()
    rejected_df = verified_df[~verified_df["Verification_Status"].isin(allowed_statuses)].copy()

    final_clean_df = stamp_cleaned_valid(final_clean_df)
    final_path = _save_csv(final_clean_df, prefix, "final_clean")
    if not final_clean_df.empty:
        try:
            from shared.central_leads import mark_emails_cleaned

            cleaned_emails = (
                final_clean_df[email_col].astype(str).str.strip().str.lower().tolist()
            )
            mark_stats_db = mark_emails_cleaned(cleaned_emails)
            if on_progress and mark_stats_db.get("updated"):
                on_progress(
                    f"Marked {mark_stats_db['updated']} lead(s) cleaned in Supabase.",
                    0.82,
                )
        except Exception as exc:
            logger.warning("Central leads cleaned-status update skipped: %s", exc)

    push_stats = {
        "attempted": 0,
        "batches": 0,
        "pushed": 0,
        "skipped_duplicate": 0,
        "failed": 0,
    }
    if destination_campaign_id and not is_dry and not final_clean_df.empty:
        if on_progress:
            on_progress("Pushing cleaned leads to Instantly campaign...", 0.85)

        # #region agent log
        try:
            from agent_debug_log import agent_debug_log

            agent_debug_log(
                "pipeline.py:run_cleaning_pipeline",
                "push_start",
                {
                    "final_clean_count": len(final_clean_df),
                    "campaign_id_len": len(destination_campaign_id.strip()),
                },
                "A",
            )
        except Exception:
            pass
        # #endregion
        push_stats = push_leads_to_campaign(
            destination_campaign_id,
            final_clean_df,
            dry_run=False,
            on_progress=on_progress,
        )
        # #region agent log
        try:
            from agent_debug_log import agent_debug_log

            agent_debug_log(
                "pipeline.py:run_cleaning_pipeline",
                "push_end",
                dict(push_stats),
                "A",
            )
        except Exception:
            pass
        # #endregion

    mark_stats = {
        "attempted": 0,
        "patched": 0,
        "failed": 0,
        "skipped_no_lead": 0,
    }
    if not is_dry and not final_clean_df.empty and get_api_key():
        if on_progress:
            on_progress("Marking cleaned leads on Instantly...", 0.92)
        mark_stats = mark_cleaned_leads_in_instantly(
            final_clean_df,
            campaign_id=destination_campaign_id,
            email_column=email_col,
            on_progress=on_progress,
        )

    if on_progress:
        on_progress("Pipeline complete.", 1.0)

    credits_used = 0 if is_dry else total_emails
    credits_remaining: int | None = None
    if not is_dry:
        credits_remaining = fetch_mev_credits()

    status_counts = {
        str(status): int(count)
        for status, count in verified_df["Verification_Status"].value_counts().items()
    }

    return PipelineResult(
        raw_count=raw_count,
        quick_clean_count=len(quick_clean_df),
        quick_rejected_count=quick_rejected_count,
        verified_count=total_emails,
        final_clean_count=len(final_clean_df),
        rejected_count=len(rejected_df),
        credits_used=credits_used,
        push_attempted=push_stats["attempted"],
        push_pushed=push_stats["pushed"],
        push_batches=push_stats["batches"],
        push_skipped_duplicate=push_stats.get("skipped_duplicate", 0),
        mark_attempted=mark_stats["attempted"],
        mark_patched=mark_stats["patched"],
        mark_failed=mark_stats["failed"],
        mark_skipped_no_lead=mark_stats["skipped_no_lead"],
        purged_count=purged_count,
        email_column=email_col,
        run_mode=run_mode,
        artifact_paths={
            "raw": raw_path,
            "quick_clean": quick_path,
            "verified": verified_path,
            "final_clean": final_path,
            "checkpoint": os.path.join(data_dir(), f"{prefix}_checkpoint.json"),
            "verified_partial": os.path.join(data_dir(), f"{prefix}_verified_partial.csv"),
        },
        quick_stats=quick_stats,
        status_counts=status_counts,
        credits_before=credits_before,
        credits_remaining=credits_remaining,
        verified_df=verified_df,
        final_clean_df=final_clean_df,
        rejected_df=rejected_df,
    )
