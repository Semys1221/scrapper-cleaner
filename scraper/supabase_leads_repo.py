"""Persist leads on the central Supabase ``leads`` table.

``temporary_leads`` is not part of the schema. Scraped and imported rows are
written as ``uncleaned`` on ``public.leads`` (owned by hercule.dev).
"""

from __future__ import annotations

import os
import sys
from typing import Any, Callable

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from shared.central_leads import (  # noqa: E402
    LEADS_TABLE,
    instantly_item_to_lead,
    supabase_store_from_env,
)

TABLE_NAME = LEADS_TABLE


def export_list_leads_to_supabase(
    leads: list[dict[str, Any]],
    list_id: str,
    *,
    category: str,
    dry_run: bool = True,
    log_cb: Callable[[str], None] | None = None,
    store: Any | None = None,
) -> dict[str, int]:
    """Upsert Instantly lead payloads as uncleaned central rows for ``category``."""

    def _log(msg: str) -> None:
        if log_cb:
            log_cb(msg)

    rows: list[dict[str, Any]] = []
    skipped = 0
    for item in leads:
        row = instantly_item_to_lead(item, category=category)
        if row is None:
            skipped += 1
            continue
        if list_id:
            row["instantly_list_id"] = list_id.strip()
        rows.append(row)

    target = store if store is not None else supabase_store_from_env()
    if dry_run or target is None:
        reason = "dry-run" if dry_run else "supabase unconfigured"
        _log(f"{reason} — {len(rows)} lead(s) would be upserted ({skipped} skipped without email).")
        return {
            "instantly_total": len(leads),
            "exportable": len(rows),
            "skipped": skipped,
            "upserted": 0,
        }

    stats = target.upsert_uncleaned(rows)
    upserted = int(stats.get("inserted", 0)) + int(stats.get("updated", 0))
    _log(f"Upserted {upserted} lead(s) to {TABLE_NAME}.")
    return {
        "instantly_total": len(leads),
        "exportable": len(rows),
        "skipped": skipped,
        "upserted": upserted,
        "inserted": int(stats.get("inserted", 0)),
        "updated": int(stats.get("updated", 0)),
    }
