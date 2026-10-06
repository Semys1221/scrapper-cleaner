"""PATCH Instantly leads with cleaned=valid after MEV (source list + campaign)."""

from __future__ import annotations

from typing import Callable

import pandas as pd

from clean_column import CLEANED_VALUE_VALID, merge_custom_variables
from instantly_client import _get_client


def custom_variables_patch_for_row(row: pd.Series) -> dict[str, str]:
    """Build Instantly PATCH custom_variables for one cleaned lead row.

    Only core variables are sent: phone, category, status, cleaned.
    """
    from shared.central_leads import core_instantly_custom_variables, normalize_phone

    merged = merge_custom_variables(row.get("custom_variables"))
    phone = normalize_phone(row.get("phone") if "phone" in row.index else row.get("Phone"))
    category = ""
    if "category" in row.index:
        raw_category = row.get("category")
        if raw_category is not None and not (isinstance(raw_category, float) and pd.isna(raw_category)):
            category = str(raw_category).strip()
    return core_instantly_custom_variables(
        merged,
        phone=phone,
        category=category,
        status="cleaned",
        cleaned=CLEANED_VALUE_VALID,
    )


def _read_lead_id(row: pd.Series) -> str | None:
    raw = row.get("instantly_lead_id")
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    lead_id = str(raw).strip()
    return lead_id or None


def _read_email(row: pd.Series, email_column: str | None) -> str:
    if email_column and email_column in row.index:
        email = row.get(email_column)
    else:
        email = row.get("email")
    if email is None or (isinstance(email, float) and pd.isna(email)):
        return ""
    return str(email).strip().lower()


def mark_cleaned_leads_in_instantly(
    df: pd.DataFrame,
    *,
    campaign_id: str | None = None,
    email_column: str | None = None,
    on_progress: Callable[[str, float], None] | None = None,
) -> dict[str, int]:
    """
    PATCH custom_variables.cleaned=valid on Instantly for verified final-clean rows.

    Uses instantly_lead_id when present; falls back to campaign email lookup when
    source leads were purged or IDs are missing.
    """
    stats = {
        "attempted": 0,
        "patched": 0,
        "failed": 0,
        "skipped_no_lead": 0,
    }
    if df.empty:
        return stats

    client = _get_client()
    campaign = (campaign_id or "").strip()
    items: list[tuple[str, dict[str, str]]] = []
    seen_ids: set[str] = set()

    for _, row in df.iterrows():
        stats["attempted"] += 1
        lead_id = _read_lead_id(row)
        if not lead_id and campaign:
            email = _read_email(row, email_column)
            if email:
                found = client.find_lead_by_email_in_campaign(
                    campaign,
                    email,
                    search_only=True,
                )
                if found:
                    lead_id = str(found.get("id") or "").strip() or None
        if not lead_id:
            stats["skipped_no_lead"] += 1
            continue
        if lead_id in seen_ids:
            continue
        seen_ids.add(lead_id)
        items.append((lead_id, custom_variables_patch_for_row(row)))

    if not items:
        return stats

    def patch_progress(done: int, total: int) -> None:
        if on_progress and total:
            on_progress(
                f"Marking cleaned on Instantly ({done}/{total})...",
                0.92 + (done / total) * 0.07,
            )

    result = client.patch_leads_custom_variables_parallel(
        items,
        on_progress=patch_progress,
    )
    stats["patched"] = int(result.get("patched") or 0)
    stats["failed"] = int(result.get("failed") or 0)
    return stats
