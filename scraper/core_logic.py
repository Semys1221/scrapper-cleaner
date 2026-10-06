"""Outscraper pipeline — config-driven scrape, filter, CSV export."""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import urllib3

from outscraper_client import (  # noqa: E402
    OutscraperClient,
    count_places_per_query,
)
import query_planner  # noqa: E402

from category_filter import (
    detect_service,
    format_category_display,
    taxonomy_fields,
    taxonomy_text,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

LIB_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.dirname(LIB_DIR)
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)
from outreach_data import scraper_output_base  # noqa: E402


@dataclass(frozen=True)
class OutputPaths:
    out_dir: str
    csv: str
    raw_jsonl: str
    filter_audit: str
    enrich_audit: str
    metrics: str
    scrape_state: str
    workspace_cache: str
    ingester_audit: str
    borderline: str
    email_recovery: str
    mev_emails: str


def output_paths(preset: str = "biggy_agency") -> OutputPaths:
    out_dir = os.path.join(scraper_output_base(), preset)
    os.makedirs(out_dir, exist_ok=True)
    return OutputPaths(
        out_dir=out_dir,
        csv=os.path.join(out_dir, "outscraper_leads.csv"),
        raw_jsonl=os.path.join(out_dir, "outscraper_raw.jsonl"),
        filter_audit=os.path.join(out_dir, "filter_audit.csv"),
        enrich_audit=os.path.join(out_dir, "enrich_audit.csv"),
        metrics=os.path.join(out_dir, "scrape_metrics.jsonl"),
        scrape_state=os.path.join(out_dir, "scrape_state.json"),
        workspace_cache=os.path.join(out_dir, "workspace_emails.json"),
        ingester_audit=os.path.join(out_dir, "ingester_audit.csv"),
        borderline=os.path.join(out_dir, "borderline.csv"),
        email_recovery=os.path.join(out_dir, "pending_email_recovery.jsonl"),
        mev_emails=os.path.join(out_dir, "mev_emails.csv"),
    )


_default_paths = output_paths("biggy_agency")
_active = _default_paths
_active_preset = "biggy_agency"


def activate_output_paths(preset: str = "biggy_agency") -> OutputPaths:
    global _active, _active_preset
    _active_preset = preset or "biggy_agency"
    _active = output_paths(_active_preset)
    return _active


def _uncleaned_push_allowed() -> bool:
    from shared.central_leads import uncleaned_instantly_push_allowed

    return uncleaned_instantly_push_allowed()


def _apply_uncleaned_push_policy(
    push_to_instantly: bool,
    log_cb: Callable[[str], None],
) -> bool:
    if _uncleaned_push_allowed():
        return push_to_instantly
    if push_to_instantly:
        log_cb(
            "Instantly push withheld — uncleaned leads stay in Supabase (status=uncleaned)."
        )
    return False


# Backward-compatible exports (biggy_agency default paths)
OUT_DIR = _default_paths.out_dir
CSV_OUTPUT_PATH = _default_paths.csv
RAW_JSONL_PATH = _default_paths.raw_jsonl
FILTER_AUDIT_PATH = _default_paths.filter_audit
ENRICH_AUDIT_PATH = _default_paths.enrich_audit
METRICS_PATH = _default_paths.metrics

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

_BACKOFF_BASE = 2.0
_MAX_RETRIES = 4
_CSV_COLUMNS = [
    "Email",
    "Company",
    "Website",
    "Service",
    "Niche",
    "Subniche",
    "City",
    "Type",
    "Category",
    "Subtypes",
    "Siret",
    "Siren",
    "Effectif",
    "TrancheEffectif",
    "Naf",
    "FormeJuridique",
    "AnneeCreation",
    "ChiffreAffaires",
    "TailleEntreprise",
    "LeadScore",
    "RegistrySource",
    "RegistryFetchedAt",
    "Phone",
    "FirstName",
    "LastName",
    "PlaceId",
]
_FILTER_AUDIT_COLUMNS = ["Email", "Company", "Category", "Verdict", "Reason"]
_ENRICH_AUDIT_COLUMNS = [
    "Email",
    "Company",
    "Website",
    "Statut_Lead",
    "Mots_Inclus_Trouvés",
    "Hard_Exclus_Trouvés",
    "Soft_Exclus_Trouvés",
    "Mots_Exclus_Trouvés",
    "Enrich_Reason",
    "Siret",
    "Siren",
    "Effectif",
    "Naf",
    "FormeJuridique",
    "TailleEntreprise",
    "LeadScore",
]


@dataclass
class OutscraperSettings:
    batch_size: int = 500
    concurrency: int = 6
    limit_per_query: int = 20
    poll_initial_s: float = 45.0
    poll_interval_s: float = 5.0
    poll_slow_s: float = 10.0
    poll_timeout_s: float = 480.0
    total_limit_buffer: int = 8


@dataclass
class InflightBatch:
    batch_index: int
    task_id: str
    submitted_at: float
    last_polled_at: float = 0.0

    def to_state(self) -> dict[str, Any]:
        return {
            "batch_index": self.batch_index,
            "task_id": self.task_id,
            "submitted_at": self.submitted_at,
        }

    @classmethod
    def from_state(cls, data: dict[str, Any]) -> InflightBatch:
        return cls(
            batch_index=int(data["batch_index"]),
            task_id=str(data["task_id"]),
            submitted_at=float(data.get("submitted_at", time.time())),
        )


def outscraper_settings(config: dict) -> OutscraperSettings:
    batch = max(int(config.get("OUTSCRAPER_BATCH_SIZE", 25)), 1)
    batch = min(batch, query_planner.MAX_QUERIES_PER_REQUEST)
    limit = max(int(config.get("OUTSCRAPER_LIMIT_PER_QUERY", 50)), 1)
    limit = min(limit, 400)
    return OutscraperSettings(
        batch_size=batch,
        concurrency=min(max(int(config.get("OUTSCRAPER_CONCURRENCY", 2)), 1), 6),
        limit_per_query=limit,
        poll_initial_s=float(config.get("OUTSCRAPER_POLL_INITIAL_S", 45)),
        poll_interval_s=float(config.get("OUTSCRAPER_POLL_INTERVAL_S", 5)),
        poll_slow_s=float(config.get("OUTSCRAPER_POLL_SLOW_S", 10)),
        poll_timeout_s=float(config.get("OUTSCRAPER_POLL_TIMEOUT_S", 480)),
        total_limit_buffer=max(int(config.get("OUTSCRAPER_TOTAL_LIMIT_BUFFER", 8)), 1),
    )


def chunk_batches(queries: list[str], batch_size: int) -> list[list[str]]:
    return [queries[i : i + batch_size] for i in range(0, len(queries), batch_size)]


def compute_total_limit(target: int, progress: int, buffer: int) -> int | None:
    remaining = target - progress
    if remaining <= 0:
        return None
    return remaining * buffer


def outscraper_filters(config: dict) -> list[str]:
    raw = config.get("OUTSCRAPER_FILTERS") or []
    return [str(item).strip() for item in raw if str(item).strip()]


def outscraper_enrichment(config: dict) -> list[str]:
    """Post-processing enrichments for Google Maps Search (modern Outscraper API)."""
    raw = config.get("OUTSCRAPER_ENRICHMENT")
    if raw is None:
        return ["leads_n_contacts"]
    if isinstance(raw, str):
        text = raw.strip()
        return [text] if text else []
    return [str(item).strip() for item in raw if str(item).strip()]


def outscraper_request_language(config: dict) -> str:
    """Outscraper quick filters require language=en."""
    if outscraper_filters(config):
        return "en"
    return str(config.get("OUTSCRAPER_LANGUAGE") or "fr").strip() or "fr"


def website_required_for_scrape(config: dict) -> bool:
    if config.get("ENRICH_ENABLED") or config.get("INGESTER_ENABLED"):
        return True
    return "only_with_website" not in outscraper_filters(config)


DUPLICATE_GEO_ADVANCE_RATE = 0.45
DUPLICATE_GEO_MIN_SAMPLES = 10


def duplicate_geo_advance_rate(config: dict | None = None) -> float:
    if config is None:
        return DUPLICATE_GEO_ADVANCE_RATE
    raw = config.get("DUPLICATE_GEO_ADVANCE_RATE")
    if raw is None:
        return DUPLICATE_GEO_ADVANCE_RATE
    try:
        return float(raw)
    except (TypeError, ValueError):
        return DUPLICATE_GEO_ADVANCE_RATE


def batch_duplicate_saturated(
    accepted: int,
    rejected: int,
    duplicate_rejects: int,
    *,
    rate: float | None = None,
    config: dict | None = None,
) -> bool:
    total = accepted + rejected
    if total < DUPLICATE_GEO_MIN_SAMPLES:
        return False
    threshold = rate if rate is not None else duplicate_geo_advance_rate(config)
    return duplicate_rejects / total > threshold


def _target_mode(config: dict) -> str:
    from scrape_state import target_mode

    return target_mode(config)


def _progress_value(
    *,
    target_mode: str,
    leads_saved: int,
    instantly_pushed: int,
) -> int:
    from scrape_state import target_uses_checkpoint_push

    if target_uses_checkpoint_push(target_mode):
        return instantly_pushed
    return leads_saved


def _is_target_reached(
    *,
    target: int,
    target_mode: str,
    leads_saved: int,
    instantly_pushed: int,
    config: dict | None = None,
) -> bool:
    from scrape_state import is_target_reached

    return is_target_reached(
        target=target,
        mode=target_mode,
        leads_saved=leads_saved,
        instantly_pushed=instantly_pushed,
        config=config,
    )


def _query_pass_lists(
    config: dict,
    query_pass: int,
    *,
    geo_phase: str = "pass",
) -> tuple[list[str], list[str]]:
    del query_pass, geo_phase
    slots = query_planner.build_slots(config)
    if not slots:
        return [], []
    keywords = sorted({s.keyword for s in slots})
    locations = sorted({s.location for s in slots})
    return keywords, locations


def max_query_passes(config: dict) -> int:
    return 0 if query_planner.build_slots(config) else 0


def initial_query_pass(config: dict) -> int:
    """First query pass for a fresh scrape run (0 = primary KEYWORDS/LOCATIONS)."""
    return max(int(config.get("SCRAPE_START_QUERY_PASS", 0) or 0), 0)


def build_queries(
    config: dict,
    query_pass: int = 0,
    *,
    geo_phase: str = "pass",
) -> list[str]:
    del query_pass, geo_phase
    return [
        query_planner.format_query(slot.keyword, slot.location)
        for slot in query_planner.build_slots(config)
        if query_planner.format_query(slot.keyword, slot.location)
    ]


def _normalize_web(raw: str) -> str:
    web = raw.lower().strip()
    for prefix in ("https://", "http://", "www."):
        if web.startswith(prefix):
            web = web[len(prefix):]
    return web.rstrip("/")


def _root_domain(web: str) -> str:
    """Extract registrable hostname from a normalized website string.

    Strips scheme, www prefix, port, path, query-string, and fragment so that
    ``https://www.example.com:443/path?x=1#section`` → ``example.com``.
    """
    if not web:
        return ""
    # Remove any residual scheme (safe even after _normalize_web)
    for prefix in ("https://", "http://", "//"):
        if web.startswith(prefix):
            web = web[len(prefix):]
    # Isolate hostname (drop path)
    host = web.split("/")[0].strip().lower()
    # Drop port
    if ":" in host and not host.startswith("["):
        host = host.rsplit(":", 1)[0]
    # Drop www. prefix
    host = host.removeprefix("www.")
    return host


def _company_dedup_key(web: str, email: str) -> str:
    """Stable dedup key: root domain when available, else email domain."""
    root = _root_domain(web)
    if root:
        return root
    if "@" in email:
        return email.split("@", 1)[1].lower()
    return ""


def _business_website(b: dict[str, Any]) -> str:
    return str(b.get("website") or b.get("site") or "").strip()


def _extract_email(business: dict[str, Any]) -> str:
    extracted: list[str] = []
    single = business.get("email")
    if isinstance(single, str) and "@" in single:
        return single.strip().lower()

    emails_field = business.get("emails")
    if emails_field:
        if isinstance(emails_field, list):
            for item in emails_field:
                if isinstance(item, dict) and item.get("value"):
                    extracted.append(str(item["value"]).strip().lower())
                elif isinstance(item, str):
                    extracted.append(item.strip().lower())
        elif isinstance(emails_field, str):
            if "@" in emails_field:
                extracted.append(emails_field.strip().lower())

    for em in extracted:
        if em and "@" in em:
            return em

    for i in range(1, 10):
        em = business.get(f"email_{i}")
        if em and isinstance(em, str) and "@" in em:
            return em.strip().lower()
    return ""


async def abort_outscraper_jobs(
    api_key: str,
    known_task_ids: list[str] | None = None,
    *,
    also_account_running: bool = True,
    log_cb: Callable[[str], None] | None = None,
) -> int:
    """Cancel Outscraper jobs before clearing local checkpoint (keeps task IDs)."""
    if not api_key:
        return 0

    def _log(msg: str) -> None:
        if log_cb:
            log_cb(msg)

    to_cancel: set[str] = {tid for tid in (known_task_ids or []) if tid}
    client = OutscraperClient(api_key)
    cancelled = 0
    try:
        if also_account_running:
            running = await client.list_running_requests()
            to_cancel.update(running)

        if not to_cancel:
            _log("No Outscraper jobs to cancel.")
            return 0

        _log(f"Cancelling {len(to_cancel)} Outscraper job(s)...")
        for task_id in sorted(to_cancel):
            if await client.cancel_task(task_id):
                cancelled += 1
                _log(f"Cancelled Outscraper task [{task_id}].")
            else:
                _log(f"Could not cancel Outscraper task [{task_id}] (may already be done).")
    finally:
        await client.aclose()

    _log(f"Outscraper cancel complete — {cancelled}/{len(to_cancel)} terminated.")
    return cancelled


def _collect_known_task_ids() -> list[str]:
    from scrape_state import load_scrape_state

    state = load_scrape_state(_active.scrape_state)
    if not state:
        return []
    ids: list[str] = []
    for item in state.get("inflight_tasks") or []:
        if isinstance(item, dict) and item.get("task_id"):
            ids.append(str(item["task_id"]))
    return ids


def _sync_mev_emails_sidecar(log_cb: Callable[[str], None] | None = None) -> int:
    _REPO_ROOT = os.path.dirname(os.path.dirname(_APP_DIR))
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)
    from shared.mev_export import sync_mev_csv_from_leads_csv

    if not os.path.isfile(_active.csv):
        return 0
    count = sync_mev_csv_from_leads_csv(_active.csv, _active.mev_emails, email_column="Email")
    if log_cb and count:
        log_cb(f"MEV export: {count} email(s) → {os.path.basename(_active.mev_emails)}")
    return count


def _csv_fieldnames(path: str) -> list[str]:
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        with open(path, encoding="utf-8", newline="") as handle:
            header = next(csv.reader(handle), [])
        if header:
            return header
    return list(_CSV_COLUMNS)


class LeadPersistenceError(RuntimeError):
    """A Supabase lead save failed. The scrape stops so resume can retry it."""


# Supabase saves are batched so the async loop is not blocked on every row.
# The leads CSV is written only after the batch upsert succeeds. Rows still
# waiting live in pending_supabase.jsonl so a failed save is retried on resume
# instead of being treated as already scraped. A row that can never be stored
# (validation, email longer than 320) is moved to pending_supabase.rejected.jsonl.
LEAD_SAVE_BATCH = 50
_PENDING_LEAD_ROWS: list[dict[str, str]] = []
_COMMITTED_EMAILS: set[str] | None = None
_COMMITTED_EMAILS_PATH: str | None = None


def _reset_lead_save_buffer() -> None:
    global _COMMITTED_EMAILS, _COMMITTED_EMAILS_PATH
    _PENDING_LEAD_ROWS.clear()
    _COMMITTED_EMAILS = None
    _COMMITTED_EMAILS_PATH = None


def _sidecar_path() -> str:
    return os.path.join(os.path.dirname(_active.csv), "pending_supabase.jsonl")


def _rejected_sidecar_path() -> str:
    return os.path.join(os.path.dirname(_active.csv), "pending_supabase.rejected.jsonl")


def _public_lead_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if not str(key).startswith("_")}


def _load_unpersisted_leads() -> list[dict[str, str]]:
    path = _sidecar_path()
    if not os.path.isfile(path):
        return []
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            item = json.loads(text)
            if not isinstance(item, dict):
                continue
            email = str(item.get("Email") or "").strip().lower()
            if email and email in seen:
                continue
            if email:
                seen.add(email)
            rows.append(item)
    return rows


def _rewrite_sidecar(rows: list[dict[str, Any]]) -> None:
    path = _sidecar_path()
    if not rows:
        if os.path.isfile(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(_public_lead_row(row), ensure_ascii=False) + "\n")


def _append_sidecar(row: dict[str, Any]) -> None:
    path = _sidecar_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(_public_lead_row(row), ensure_ascii=False) + "\n")


def _write_csv_row(row: dict[str, str]) -> None:
    fieldnames = _csv_fieldnames(_active.csv)
    write_header = not os.path.exists(_active.csv) or os.path.getsize(_active.csv) == 0
    os.makedirs(os.path.dirname(_active.csv), exist_ok=True)
    with open(_active.csv, "a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow({col: row.get(col, "") for col in fieldnames})


def _committed_emails() -> set[str]:
    """Emails already in the leads CSV. Loaded once per file, then kept in memory."""
    global _COMMITTED_EMAILS, _COMMITTED_EMAILS_PATH
    path = _active.csv
    if _COMMITTED_EMAILS is None or _COMMITTED_EMAILS_PATH != path:
        seen, _domains = _load_seen_from_csv()
        _COMMITTED_EMAILS = set(seen)
        _COMMITTED_EMAILS_PATH = path
    return _COMMITTED_EMAILS


def _row_email(row: dict[str, Any]) -> str:
    return str(row.get("Email") or row.get("email") or "").strip().lower()


def _row_permanent_error(row: dict[str, Any]) -> str | None:
    """Validation failures that will never succeed on retry."""
    from shared.central_leads import scraped_row_to_lead

    try:
        scraped_row_to_lead(row, preset=_active_preset)
    except ValueError as exc:
        return str(exc)
    return None


def _append_rejected_row(row: dict[str, Any], error: str) -> None:
    path = _rejected_sidecar_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    record = _public_lead_row(row)
    record["error"] = error
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.error("Rejected lead permanently (%s): %s", error, _row_email(row) or row.get("Company"))


def _separate_permanent_rejects(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Move rows that can never be stored out of the retry sidecar."""
    saveable: list[dict[str, str]] = []
    rejected_ids: set[int] = set()
    for row in rows:
        error = _row_permanent_error(row)
        if error is None:
            saveable.append(row)
            continue
        _append_rejected_row(row, error)
        rejected_ids.add(id(row))
    if rejected_ids:
        _PENDING_LEAD_ROWS[:] = [row for row in _PENDING_LEAD_ROWS if id(row) not in rejected_ids]
        _rewrite_sidecar(_PENDING_LEAD_ROWS)
    return saveable


def _persist_lead_batch(rows: list[dict[str, str]]) -> None:
    from shared.central_leads import persist_scraped_leads

    persist_scraped_leads(rows, preset=_active_preset)


def _commit_saved_lead_rows(batch: list[dict[str, str]]) -> None:
    """Write the CSV only after the Supabase upsert has returned."""
    already = _committed_emails()
    saved_emails: set[str] = set()
    for row in batch:
        email = _row_email(row)
        if email:
            saved_emails.add(email)
        if email and email in already:
            continue
        _write_csv_row(row)
        if email:
            already.add(email)
    _PENDING_LEAD_ROWS[:] = [
        row
        for row in _PENDING_LEAD_ROWS
        if str(row.get("Email") or "").strip().lower() not in saved_emails
    ]
    remaining = [
        row
        for row in _load_unpersisted_leads()
        if str(row.get("Email") or "").strip().lower() not in saved_emails
    ]
    _rewrite_sidecar(remaining)


def _raise_persistence_error(exc: Exception) -> None:
    logger.error("Central leads upsert failed: %s", exc)
    if isinstance(exc, LeadPersistenceError):
        raise exc
    raise LeadPersistenceError(str(exc)) from exc


def _flush_pending_lead_rows_sync() -> None:
    if not _PENDING_LEAD_ROWS:
        return
    batch = _separate_permanent_rejects(list(_PENDING_LEAD_ROWS))
    if not batch:
        return
    try:
        _persist_lead_batch(batch)
    except Exception as exc:
        _raise_persistence_error(exc)
    _commit_saved_lead_rows(batch)


async def _flush_pending_lead_rows_async() -> None:
    """Upsert off the event loop, then write the CSV on success."""
    if not _PENDING_LEAD_ROWS:
        return
    batch = _separate_permanent_rejects(list(_PENDING_LEAD_ROWS))
    if not batch:
        return
    try:
        await asyncio.to_thread(_persist_lead_batch, batch)
    except Exception as exc:
        _raise_persistence_error(exc)
    _commit_saved_lead_rows(batch)


def _queue_lead_row_sync(row: dict[str, str]) -> None:
    _PENDING_LEAD_ROWS.append(row)
    _append_sidecar(row)
    if len(_PENDING_LEAD_ROWS) >= LEAD_SAVE_BATCH:
        _flush_pending_lead_rows_sync()


async def _queue_lead_row_async(row: dict[str, str]) -> None:
    _PENDING_LEAD_ROWS.append(row)
    _append_sidecar(row)
    if len(_PENDING_LEAD_ROWS) >= LEAD_SAVE_BATCH:
        await _flush_pending_lead_rows_async()


async def _retry_unpersisted_leads() -> None:
    """Replay leads whose Supabase save failed on a previous run."""
    if not _PENDING_LEAD_ROWS:
        _PENDING_LEAD_ROWS.extend(_load_unpersisted_leads())
    await _flush_pending_lead_rows_async()


def _append_lead_row(row: dict[str, str]) -> None:
    """Queue one lead. The CSV row is written when the Supabase batch succeeds."""
    _queue_lead_row_sync(row)


def _append_raw_business(business: dict[str, Any]) -> None:
    with open(_active.raw_jsonl, "a", encoding="utf-8") as f:
        f.write(json.dumps(business, ensure_ascii=False) + "\n")


def _append_filter_audit_row(row: dict[str, str]) -> None:
    write_header = not os.path.exists(_active.filter_audit) or os.path.getsize(_active.filter_audit) == 0
    with open(_active.filter_audit, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_FILTER_AUDIT_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow({col: row.get(col, "") for col in _FILTER_AUDIT_COLUMNS})


def _append_enrich_audit_row(row: dict[str, str]) -> None:
    write_header = not os.path.exists(_active.enrich_audit) or os.path.getsize(_active.enrich_audit) == 0
    with open(_active.enrich_audit, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_ENRICH_AUDIT_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow({col: row.get(col, "") for col in _ENRICH_AUDIT_COLUMNS})


def _pappers_batch_settings(config: dict) -> dict[str, Any]:
    return {
        "enabled": bool(config.get("PAPPERS_ENABLED", False)),
        "batch_size": max(int(config.get("PAPPERS_BATCH_SIZE", 100)), 1),
    }


def _enrich_settings(config: dict) -> dict[str, Any]:
    hard = list(config.get("ENRICH_HARD_EXCLUDED_KEYWORDS") or [])
    soft = list(config.get("ENRICH_SOFT_EXCLUDED_KEYWORDS") or [])
    legacy_excluded = list(config.get("ENRICH_EXCLUDED_KEYWORDS") or [])
    if not hard and not soft and legacy_excluded:
        hard = legacy_excluded
    return {
        "enabled": bool(config.get("ENRICH_ENABLED", False)),
        "batch_size": max(int(config.get("ENRICH_BATCH_SIZE", 50)), 1),
        "concurrency": max(int(config.get("ENRICH_CONCURRENCY", 10)), 1),
        "timeout_ms": max(int(config.get("ENRICH_TIMEOUT_MS", 15000)), 1000),
        "included": list(config.get("ENRICH_INCLUDED_KEYWORDS") or []),
        "hard_excluded": hard,
        "soft_excluded": soft,
    }


async def _run_enrich_batch(
    pending_scraped: list[dict[str, str]],
    config: dict,
    *,
    log_cb: Callable[[str], None],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    from website_verifier import enrich_leads

    settings = _enrich_settings(config)
    batch = pending_scraped[: settings["batch_size"]]
    del pending_scraped[: len(batch)]

    valid, rejected = await enrich_leads(
        batch,
        url_column="Website",
        included=settings["included"],
        hard_excluded=settings["hard_excluded"],
        soft_excluded=settings["soft_excluded"],
        max_concurrent=settings["concurrency"],
        goto_timeout_ms=settings["timeout_ms"],
        service_config={
            "SERVICE_DEFAULT": config.get("SERVICE_DEFAULT", ""),
            "SERVICE_RULES": list(config.get("SERVICE_RULES") or []),
        },
        siret_config=config if bool(config.get("PAPPERS_ENABLED", False)) else None,
        log_cb=log_cb,
    )
    for row in rejected:
        _append_enrich_audit_row(row)
    return valid, rejected


async def _run_ingester_batch(
    pending_scraped: list[dict[str, str]],
    config: dict,
    *,
    log_cb: Callable[[str], None],
    batch_size: int,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    """Run one ingester batch. Returns (accepted, borderline, rejected)."""
    from lead_ingester import ingest_batch

    batch = pending_scraped[:batch_size]
    del pending_scraped[: len(batch)]
    result = await ingest_batch(batch, config, _active)
    log_cb(
        f"Ingester: {len(result.accepted)} accepted, "
        f"{len(result.borderline)} borderline, {len(result.rejected)} rejected"
    )
    return result.accepted, result.borderline, result.rejected


async def _maybe_enrich_and_push(
    *,
    config: dict,
    pending_scraped: list[dict[str, str]],
    pending_instantly: list[dict[str, str]],
    instantly_enabled: bool,
    push_every: int,
    enrich_batch_size: int,
    enrich_enabled: bool,
    log_cb: Callable[[str], None],
    progress_cb: Callable[[float], None],
    metric_cb: Callable[[int, int, int], None],
    target: int,
    target_mode: str,
    leads_saved: int,
    leads_enriched_valid: int,
    leads_enriched_rejected: int,
    instantly_pushed: int,
    batches_total: int,
    last_completed: int,
    force_enrich: bool = False,
    on_progress_persist: Callable[[int, int, int], None] | None = None,
) -> tuple[int, int, int]:
    """Run enrich/ingester batch if buffer full; flush Instantly if buffer full. Returns updated counters."""
    ingester_enabled = bool(config.get("INGESTER_ENABLED", False))
    # Ingester replaces the legacy website enrich path when enabled
    use_enrich = enrich_enabled and not ingester_enabled

    while ingester_enabled and (len(pending_scraped) >= enrich_batch_size or force_enrich):
        if not pending_scraped:
            break
        force_enrich = False
        batch_n = min(len(pending_scraped), enrich_batch_size)
        log_cb(f"Ingester batch — {batch_n} scraped lead(s) queued for scoring")
        accepted, borderline, rejected = await _run_ingester_batch(
            pending_scraped,
            config,
            log_cb=log_cb,
            batch_size=batch_n,
        )
        leads_enriched_valid += len(accepted)
        leads_enriched_rejected += len(rejected) + len(borderline)
        pending_instantly.extend(accepted)
        metric_cb(leads_saved, leads_enriched_valid, instantly_pushed)
        if on_progress_persist:
            on_progress_persist(leads_saved, leads_enriched_valid, instantly_pushed)

    while use_enrich and (len(pending_scraped) >= enrich_batch_size or force_enrich):
        if not pending_scraped:
            break
        force_enrich = False
        batch_n = min(len(pending_scraped), enrich_batch_size)

        log_cb(f"Enrich batch — {batch_n} scraped lead(s) queued for website check")
        valid, rejected = await _run_enrich_batch(pending_scraped, config, log_cb=log_cb)
        leads_enriched_valid += len(valid)
        leads_enriched_rejected += len(rejected)
        pending_instantly.extend(valid)
        log_cb(
            f"Enrich batch done — {len(valid)} valid, {len(rejected)} rejected "
            f"(totals: {leads_enriched_valid} valid / {leads_enriched_rejected} rejected)"
        )

        metric_cb(leads_saved, leads_enriched_valid, instantly_pushed)
        if on_progress_persist:
            on_progress_persist(leads_saved, leads_enriched_valid, instantly_pushed)

    pappers_cfg = _pappers_batch_settings(config)
    while (
        not use_enrich
        and not ingester_enabled
        and pappers_cfg["enabled"]
        and pending_scraped
        and (len(pending_scraped) >= pappers_cfg["batch_size"] or force_enrich)
    ):
        force_enrich = False
        batch_n = min(len(pending_scraped), pappers_cfg["batch_size"])
        to_push = pending_scraped[:batch_n]
        del pending_scraped[:batch_n]
        from company_registry import validate_leads


        log_cb(f"SIRET batch — {batch_n} scraped lead(s) queued for registry check")
        started = time.time()
        valid, rejected = await validate_leads(to_push, config, log_cb=log_cb)
        duration_s = round(time.time() - started, 2)
        for row in rejected:
            _append_enrich_audit_row(row)
        leads_enriched_rejected += len(rejected)
        leads_enriched_valid += len(valid)
        pending_instantly.extend(valid)
        log_cb(
            f"SIRET batch done — {len(valid)} valid, {len(rejected)} rejected "
            f"in {duration_s}s (totals: {leads_enriched_valid} valid / "
            f"{leads_enriched_rejected} rejected)"
        )

        metric_cb(leads_saved, leads_enriched_valid, instantly_pushed)
        if on_progress_persist:
            on_progress_persist(leads_saved, leads_enriched_valid, instantly_pushed)

    if (
        not use_enrich
        and not ingester_enabled
        and pending_scraped
        and not pappers_cfg["enabled"]
    ):
        moved = len(pending_scraped)
        pending_instantly.extend(pending_scraped)
        pending_scraped.clear()


    while instantly_enabled and len(pending_instantly) >= push_every:
        flush_stats = await _flush_instantly_buffer(
            pending_instantly,
            config,
            log_cb=log_cb,
            label=f"{instantly_pushed} pushed so far",
        )
        instantly_pushed += flush_stats["pushed"]
        metric_cb(leads_saved, leads_enriched_valid, instantly_pushed)
        if batches_total:
            progress_cb(
                min(instantly_pushed / target, 1.0)
                if target_mode in ("instantly_pushed", "instantly_pushed_run")
                else (last_completed + 1) / batches_total
            )
        log_cb(
            f"Instantly totals — pushed: {instantly_pushed}/{target}, "
            f"skipped (duplicate): {flush_stats['skipped_duplicate']}"
        )
        if on_progress_persist:
            on_progress_persist(leads_saved, leads_enriched_valid, instantly_pushed)

    return leads_enriched_valid, leads_enriched_rejected, instantly_pushed


def _append_metrics(event: dict[str, Any]) -> None:
    event.setdefault("ts", time.time())
    with open(_active.metrics, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _append_email_recovery(
    business: dict[str, Any],
    *,
    website: str,
    company: str,
) -> None:
    """Queue a no-email business with website for later emails-and-contacts recovery."""
    path = _active.email_recovery
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "website": website,
        "company": company,
        "type": str(business.get("type") or "").strip(),
        "category": str(business.get("category") or "").strip(),
        "subtypes": business.get("subtypes"),
        "city": str(business.get("city") or business.get("full_address") or "").strip(),
        "phone": str(business.get("phone") or "").strip(),
        "name": str(business.get("name") or company).strip(),
        "queued_at": time.time(),
    }
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _process_business(
    b: dict[str, Any],
    config: dict,
    *,
    seen_domain: set[str],
    seen_em: set[str],
) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    """Return (lead_row, audit_row). Minimal scrape gates — website enrich filters later."""
    company = (b.get("name") or "").strip()
    category_display = format_category_display(b)
    email = _extract_email(b)
    web = _normalize_web(_business_website(b))

    if not email or not EMAIL_REGEX.match(email):
        if web and bool(config.get("OUTSCRAPER_EMAIL_RECOVERY_ENABLED")):
            if not any(ex in web for ex in (config.get("EXCLUDE_DOMAINS") or [])):
                _append_email_recovery(b, website=web, company=company)
        audit = {
            "Email": email,
            "Company": company,
            "Category": category_display,
            "Verdict": "rejected",
            "Reason": "invalid or missing email",
        }
        return None, audit

    if not web and website_required_for_scrape(config):
        audit = {
            "Email": email,
            "Company": company,
            "Category": category_display,
            "Verdict": "rejected",
            "Reason": "missing website",
        }
        return None, audit

    if any(ex in web for ex in config["EXCLUDE_DOMAINS"]):
        audit = {
            "Email": email,
            "Company": company,
            "Category": category_display,
            "Verdict": "rejected",
            "Reason": "excluded domain",
        }
        return None, audit

    company_key = _company_dedup_key(web, email)
    if company_key in seen_domain or email in seen_em:
        audit = {
            "Email": email,
            "Company": company,
            "Category": category_display,
            "Verdict": "rejected",
            "Reason": "duplicate company (domain) or email",
        }
        return None, audit

    if config.get("TAXONOMY_GATE_ENABLED"):
        from taxonomy_gate import matches_taxonomy

        from taxonomy_gate import taxonomy_excluded_keywords

        ok, matched = matches_taxonomy(
            b,
            config.get("TAXONOMY_INCLUDED_KEYWORDS") or [],
            excluded_keywords=taxonomy_excluded_keywords(config) or None,
        )
        if not ok:
            reason = "taxonomy_mismatch"
            if matched and matched.startswith("excluded:"):
                reason = f"taxonomy_hard_excluded ({matched[9:]})"
            audit = {
                "Email": email,
                "Company": company,
                "Category": category_display,
                "Verdict": "rejected",
                "Reason": reason,
            }
            return None, audit

    tax = taxonomy_text(b)
    service = detect_service(tax, config)
    fields = taxonomy_fields(b)
    from company_registry.siret_extract import extract_from_outscraper

    siret, siren = extract_from_outscraper(b)
    row = {
        "Email": email,
        "Company": company,
        "Website": web,
        "Service": service,
        "Niche": str(config.get("NICHE_GROUP_LABEL") or ""),
        "Subniche": str(config.get("SUBNICHE_LABEL") or ""),
        "City": (b.get("city") or "").strip(),
        "Type": fields["Type"],
        "Category": fields["Category"],
        "Subtypes": fields["Subtypes"],
        "Siret": siret,
        "Siren": siren,
        "Phone": str(b.get("phone") or "").strip(),
        "FirstName": str(b.get("first_name") or "").strip(),
        "LastName": str(b.get("last_name") or "").strip(),
        "PlaceId": str(b.get("place_id") or b.get("google_id") or "").strip(),
    }
    # Ephemeral: keep reviews for the ingester (not written to CSV columns)
    reviews = b.get("reviews_data")
    if isinstance(reviews, list) and reviews:
        row["_reviews_data"] = reviews
    audit = {
        "Email": email,
        "Company": company,
        "Category": category_display,
        "Verdict": "accepted",
        "Reason": "",
    }
    return row, audit


def _load_seen_from_csv() -> tuple[set[str], set[str]]:
    seen_em: set[str] = set()
    seen_domain: set[str] = set()
    if not os.path.isfile(_active.csv):
        return seen_em, seen_domain
    try:
        df = pd.read_csv(_active.csv)
        if df.empty:
            return seen_em, seen_domain
        for _, row in df.iterrows():
            email = str(row.get("Email") or "").strip().lower()
            web = _normalize_web(str(row.get("Website") or ""))
            if "@" in email:
                seen_em.add(email)
            company_key = _company_dedup_key(web, email)
            if company_key:
                seen_domain.add(company_key)
    except (OSError, pd.errors.EmptyDataError, ValueError):
        pass
    return seen_em, seen_domain


def _persist_workspace_seen_emails(
    emails: set[str],
    config: dict,
    *,
    cache_path: str,
) -> None:
    if not cache_path or not emails:
        return
    from instantly_client import save_workspace_email_cache

    save_workspace_email_cache(
        emails,
        list_ids=list(config.get("INSTANTLY_DEDUP_LIST_IDS") or []),
        campaign_ids=list(config.get("INSTANTLY_DEDUP_CAMPAIGN_IDS") or []),
        complete=True,
        cache_path=cache_path,
    )


_BACKLOG_SKIP_STREAK_ABORT = 2
_BACKLOG_FAIL_STREAK_ABORT = 2


async def _flush_instantly_buffer(
    pending: list[dict[str, str]],
    config: dict,
    *,
    log_cb: Callable[[str], None],
    label: str = "",
) -> dict[str, int]:
    from instantly_client import push_leads_to_list

    if not pending:
        return {"pushed": 0, "skipped_duplicate": 0, "emails": []}

    if label:
        log_cb(f"Instantly flush ({label}) — {len(pending)} lead(s) in buffer")

    batch_emails = [
        str(row.get("Email") or "").strip().lower()
        for row in pending
        if "@" in str(row.get("Email") or "")
    ]

    push_stats = await push_leads_to_list(
        config["INSTANTLY_API_KEY"],
        config["INSTANTLY_LIST_ID"],
        pending,
        skip_if_in_campaign=bool(config.get("INSTANTLY_SKIP_IF_IN_CAMPAIGN", True)),
        skip_if_in_list=bool(config.get("INSTANTLY_SKIP_IF_IN_LIST", True)),
        log_cb=log_cb,
    )
    pending.clear()
    _sync_mev_emails_sidecar(log_cb=log_cb)

    pushed = int(push_stats.get("pushed") or 0)
    skipped = int(push_stats.get("skipped_duplicate") or 0)
    failed = int(push_stats.get("failed") or 0)
    should_provision = bool(
        pushed > 0 and batch_emails and config.get("INSTANTLY_PROVISION_LINKS")
    )

    if should_provision:
        from link_provision_client import provision_leads_after_push

        await provision_leads_after_push(
            batch_emails,
            config=config,
            log_cb=log_cb,
        )
    elif batch_emails and config.get("INSTANTLY_PROVISION_LINKS") and pushed <= 0:
        log_cb("Link provision skipped — Instantly uploaded 0 lead(s)")

    return {
        "pushed": pushed,
        "skipped_duplicate": skipped,
        "failed": failed,
        "emails": batch_emails,
    }


def _backlog_push_min(config: dict) -> int:
    raw = config.get("INSTANTLY_BACKLOG_PUSH_MIN")
    if raw is not None:
        return max(int(raw), 1)
    return max(int(config.get("INSTANTLY_PUSH_EVERY", 100)), 1)


async def _push_csv_backlog_if_needed(
    config: dict,
    *,
    workspace_emails: set[str],
    csv_path: str,
    state_path: str,
    log_cb: Callable[[str], None],
    instantly_pushed: int,
    run_state: dict[str, Any] | None,
    cache_path: str = "",
) -> tuple[int, int]:
    """Push CSV rows not yet on Instantly when backlog exceeds threshold."""
    if not os.path.isfile(csv_path):
        return instantly_pushed, 0

    min_backlog = _backlog_push_min(config)
    push_every = max(int(config.get("INSTANTLY_PUSH_EVERY", 100)), 1)

    from taxonomy_gate import matches_taxonomy_csv_row, taxonomy_excluded_keywords

    try:
        df = pd.read_csv(csv_path)
    except (OSError, pd.errors.EmptyDataError, ValueError):
        return instantly_pushed, 0

    if df.empty or "Email" not in df.columns:
        return instantly_pushed, 0

    included = list(config.get("TAXONOMY_INCLUDED_KEYWORDS") or [])
    excluded = taxonomy_excluded_keywords(config)
    taxonomy_enabled = bool(config.get("TAXONOMY_GATE_ENABLED"))

    backlog_rows: list[dict[str, str]] = []
    for _, series in df.iterrows():
        row = {str(k): ("" if pd.isna(v) else str(v)) for k, v in series.items()}
        email = str(row.get("Email") or "").strip().lower()
        if not email or "@" not in email:
            continue
        if email in workspace_emails:
            continue
        if taxonomy_enabled:
            ok, _matched = matches_taxonomy_csv_row(row, included, excluded or None)
            if not ok:
                continue
        backlog_rows.append(row)

    if len(backlog_rows) < min_backlog:
        log_cb(
            f"Backlog push skip — {len(backlog_rows)} CSV row(s) not on Instantly "
            f"(min {min_backlog})"
        )
        return instantly_pushed, 0

    log_cb(
        f"Backlog push — {len(backlog_rows)} CSV row(s) not yet on Instantly "
        f"(threshold {min_backlog})"
    )

    total_pushed = 0
    total_skipped = 0
    skip_streak = 0
    fail_streak = 0
    for offset in range(0, len(backlog_rows), push_every):
        batch = backlog_rows[offset : offset + push_every]
        pending = list(batch)
        flush_stats = await _flush_instantly_buffer(
            pending,
            config,
            log_cb=log_cb,
            label=f"backlog batch {offset // push_every + 1}",
        )
        pushed = int(flush_stats.get("pushed") or 0)
        skipped = int(flush_stats.get("skipped_duplicate") or 0)
        failed = int(flush_stats.get("failed") or 0)
        total_pushed += pushed
        total_skipped += skipped
        seen_emails = [
            str(email).strip().lower()
            for email in (flush_stats.get("emails") or [])
            if "@" in str(email)
        ]
        if skipped > 0 and seen_emails:
            workspace_emails.update(seen_emails)
            _persist_workspace_seen_emails(
                workspace_emails,
                config,
                cache_path=cache_path,
            )
        if pushed <= 0 and skipped > 0:
            skip_streak += 1
        else:
            skip_streak = 0
        if pushed <= 0 and skipped <= 0 and failed > 0:
            fail_streak += 1
        else:
            fail_streak = 0
        if fail_streak >= _BACKLOG_FAIL_STREAK_ABORT:
            log_cb(
                f"Backlog push defer — Instantly upload fail streak {fail_streak} "
                f"(rate limit or API errors); continuing scrape"
            )
            break
        if skip_streak >= _BACKLOG_SKIP_STREAK_ABORT:
            remaining = backlog_rows[offset + push_every :]
            remaining_emails = {
                str(row.get("Email") or "").strip().lower()
                for row in remaining
                if "@" in str(row.get("Email") or "")
            }
            if remaining_emails:
                workspace_emails.update(remaining_emails)
                _persist_workspace_seen_emails(
                    workspace_emails,
                    config,
                    cache_path=cache_path,
                )
            log_cb(
                f"Backlog push abort — Instantly duplicate skip streak "
                f"{skip_streak} (marked {len(remaining_emails)} remaining as seen)"
            )
            break

    instantly_pushed += total_pushed

    from scrape_state import load_scrape_state, save_scrape_state

    state = run_state if run_state is not None else load_scrape_state(state_path) or {}
    state["instantly_pushed"] = instantly_pushed
    state["instantly_skipped_duplicate"] = int(state.get("instantly_skipped_duplicate", 0) or 0) + total_skipped
    state["push_to_instantly"] = True
    save_scrape_state(state, path=state_path)

    log_cb(
        f"Backlog push done — pushed {total_pushed}, skipped duplicate {total_skipped} "
        f"(checkpoint {instantly_pushed})"
    )
    return instantly_pushed, total_pushed


async def clear_local_leads(
    *,
    cancel_remote: bool = True,
    api_key: str = "",
    log_cb: Callable[[str], None] | None = None,
    preset: str = "biggy_agency",
) -> dict[str, int | bool]:
    """Remove local CSV/checkpoint; optionally cancel Outscraper jobs first."""
    from scrape_state import clear_scrape_state, count_csv_leads

    paths = activate_output_paths(preset)
    known_ids = _collect_known_task_ids()
    outscraper_cancelled = 0
    if cancel_remote and api_key:
        outscraper_cancelled = await abort_outscraper_jobs(
            api_key,
            known_ids,
            log_cb=log_cb,
        )

    lead_count = count_csv_leads(paths.csv)
    had_csv = os.path.isfile(paths.csv)
    had_state = os.path.isfile(paths.scrape_state)

    if had_csv:
        os.remove(paths.csv)
    if os.path.isfile(paths.raw_jsonl):
        os.remove(paths.raw_jsonl)
    if os.path.isfile(paths.enrich_audit):
        os.remove(paths.enrich_audit)
    sidecar = os.path.join(os.path.dirname(paths.csv), "pending_supabase.jsonl")
    if os.path.isfile(sidecar):
        os.remove(sidecar)
    _reset_lead_save_buffer()
    clear_scrape_state(paths.scrape_state)

    return {
        "leads_removed": lead_count,
        "csv_cleared": had_csv,
        "state_cleared": had_state,
        "outscraper_cancelled": outscraper_cancelled,
    }


def _persist_run_state(
    run_state: dict[str, Any] | None,
    *,
    leads_saved: int,
    leads_enriched_valid: int = 0,
    leads_enriched_rejected: int = 0,
    instantly_pushed: int = 0,
    last_completed_batch_index: int,
    last_submitted_batch_index: int,
    inflight: dict[str, InflightBatch],
) -> None:
    if run_state is None:
        return
    from scrape_metrics import touch_worker_heartbeat
    from scrape_state import save_scrape_state

    run_state["leads_saved"] = leads_saved
    run_state["leads_enriched_valid"] = leads_enriched_valid
    run_state["leads_enriched_rejected"] = leads_enriched_rejected
    run_state["instantly_pushed"] = instantly_pushed
    run_state["last_completed_batch_index"] = last_completed_batch_index
    run_state["last_submitted_batch_index"] = last_submitted_batch_index
    run_state["inflight_tasks"] = [job.to_state() for job in inflight.values()]
    run_state["status"] = "running"
    save_scrape_state(run_state, path=_active.scrape_state)
    preset = str(run_state.get("preset") or "").strip()
    if preset:
        touch_worker_heartbeat(_active.out_dir, preset=preset, status="running")


async def _process_batch_results(
    results: list,
    config: dict,
    *,
    seen_domain: set[str],
    seen_em: set[str],
    target: int,
    target_mode: str,
    leads_saved: int,
    leads_enriched_valid: int,
    leads_enriched_rejected: int,
    pending_scraped: list[dict[str, str]],
    pending_instantly: list[dict[str, str]],
    instantly_enabled: bool,
    push_every: int,
    enrich_enabled: bool,
    enrich_batch_size: int,
    log_cb: Callable[[str], None],
    progress_cb: Callable[[float], None],
    metric_cb: Callable[[int, int, int], None],
    instantly_pushed: int,
    batches_total: int,
    last_completed: int,
    on_progress_persist: Callable[[int, int, int], None] | None = None,
) -> tuple[int, int, int, int, bool]:
    log_cb("Applying scrape gates (email, website, dedup)...")
    raw_places = 0
    with_email = 0
    accepted = 0
    rejected = 0
    duplicate_rejects = 0
    taxonomy_mismatches = 0
    taxonomy_hard_excluded = 0
    started = time.time()
    target_reached = False

    for query_result in results:
        b_list = query_result if isinstance(query_result, list) else [query_result]
        for b in b_list:
            if not b or not isinstance(b, dict):
                continue

            raw_places += 1
            _append_raw_business(b)
            row, audit = _process_business(b, config, seen_domain=seen_domain, seen_em=seen_em)
            if _extract_email(b):
                with_email += 1
            if audit:
                if audit["Verdict"] == "accepted":
                    accepted += 1
                else:
                    rejected += 1
                    reason = str(audit.get("Reason") or "")
                    if "duplicate" in reason.lower():
                        duplicate_rejects += 1
                    if reason == "taxonomy_mismatch":
                        taxonomy_mismatches += 1
                    elif reason.startswith("taxonomy_hard_excluded"):
                        taxonomy_hard_excluded += 1
                        taxonomy_mismatches += 1
                    _append_filter_audit_row(audit)
            if not row:
                continue

            seen_domain.add(_company_dedup_key(row["Website"], row["Email"]))
            seen_em.add(row["Email"])
            await _queue_lead_row_async(row)
            pending_scraped.append(row)
            leads_saved += 1
            metric_cb(leads_saved, leads_enriched_valid, instantly_pushed)

            (
                leads_enriched_valid,
                leads_enriched_rejected,
                instantly_pushed,
            ) = await _maybe_enrich_and_push(
                config=config,
                pending_scraped=pending_scraped,
                pending_instantly=pending_instantly,
                instantly_enabled=instantly_enabled,
                push_every=push_every,
                enrich_batch_size=enrich_batch_size,
                enrich_enabled=enrich_enabled,
                log_cb=log_cb,
                progress_cb=progress_cb,
                metric_cb=metric_cb,
                target=target,
                target_mode=target_mode,
                leads_saved=leads_saved,
                leads_enriched_valid=leads_enriched_valid,
                leads_enriched_rejected=leads_enriched_rejected,
                instantly_pushed=instantly_pushed,
                batches_total=batches_total,
                last_completed=last_completed,
                on_progress_persist=on_progress_persist,
            )

            if _is_target_reached(
                target=target,
                target_mode=target_mode,
                leads_saved=leads_saved,
                instantly_pushed=instantly_pushed,
                config=config,
            ):
                target_reached = True
                break
            if on_progress_persist:
                on_progress_persist(leads_saved, leads_enriched_valid, instantly_pushed)
        if target_reached:
            break

    taxonomy_total = taxonomy_mismatches
    taxonomy_rate = round(taxonomy_total / max(raw_places, 1) * 100, 1)

    _append_metrics(
        {
            "event": "batch_complete",
            "raw_places": raw_places,
            "with_email": with_email,
            "accepted": accepted,
            "rejected": rejected,
            "duplicate_rejects": duplicate_rejects,
            "taxonomy_mismatches": taxonomy_mismatches,
            "taxonomy_hard_excluded": taxonomy_hard_excluded,
            "taxonomy_trash_rate_pct": taxonomy_rate,
            "leads_saved": leads_saved,
            "leads_enriched_valid": leads_enriched_valid,
            "leads_enriched_rejected": leads_enriched_rejected,
            "instantly_pushed": instantly_pushed,
            "duration_s": round(time.time() - started, 1),
        }
    )
    log_cb(
        f"Scrape stats — places={raw_places}, emails={with_email}, "
        f"accepted={accepted}, rejected={rejected}, enriched_valid={leads_enriched_valid}"
    )

    # Taxonomy trash-rate monitoring — warn when the taxonomy gate is too loose
    if config.get("TAXONOMY_GATE_ENABLED") and raw_places >= 10:
        from taxonomy_gate import TAXONOMY_TRASH_RATE_WARN, is_taxonomy_trash_rate_high

        if is_taxonomy_trash_rate_high(taxonomy_mismatches, raw_places):
            log_cb(
                f"⚠️  Taxonomy trash rate high: {taxonomy_rate}% of places rejected by taxonomy "
                f"(threshold {int(TAXONOMY_TRASH_RATE_WARN * 100)}%). "
                f"Hard-excluded: {taxonomy_hard_excluded}. "
                f"Consider tightening TAXONOMY_INCLUDED_KEYWORDS or adding TAXONOMY_HARD_EXCLUDED_KEYWORDS."
            )
    duplicate_saturated = batch_duplicate_saturated(
        accepted, rejected, duplicate_rejects, config=config
    )
    if duplicate_saturated:
        rate = duplicate_rejects / max(accepted + rejected, 1) * 100
        log_cb(
            f"Geo advance — duplicate saturation on batch "
            f"({duplicate_rejects}/{accepted + rejected} = {rate:.0f}%)."
        )
    return (
        leads_saved,
        leads_enriched_valid,
        leads_enriched_rejected,
        instantly_pushed,
        target_reached,
        duplicate_saturated,
    )



async def _run_planner_scrape(
    *,
    client: OutscraperClient,
    planner: query_planner.QueryPlanner,
    config: dict,
    settings: OutscraperSettings,
    target: int,
    target_mode: str,
    run_state: dict[str, Any] | None,
    seen_domain: set[str],
    seen_em: set[str],
    leads_saved: int,
    leads_enriched_valid: int,
    leads_enriched_rejected: int,
    pending_scraped: list[dict[str, str]],
    pending_instantly: list[dict[str, str]],
    instantly_enabled: bool,
    push_every: int,
    enrich_enabled: bool,
    enrich_batch_size: int,
    log_cb: Callable[[str], None],
    progress_cb: Callable[[float], None],
    metric_cb: Callable[[int, int, int], None],
    instantly_pushed: int,
    preset: str = "",
    out_dir: str = "",
) -> tuple[int, int, int, int, bool]:
    """Drive Outscraper via SDK wait + query planner until target or exhaustion."""
    out_filters = outscraper_filters(config)
    out_language = outscraper_request_language(config)
    out_enrichment = outscraper_enrichment(config)
    batches_run = 0
    target_reached = False
    semaphore = asyncio.Semaphore(settings.concurrency)

    async def _run_one_batch(batch: query_planner.SearchBatch) -> None:
        nonlocal leads_saved, leads_enriched_valid, leads_enriched_rejected
        nonlocal instantly_pushed, batches_run, target_reached
        async with semaphore:
            skip_label = f", skipPlaces={batch.skip_places}" if batch.skip_places else ""
            log_cb(
                f"Outscraper SDK batch {batch.batch_index + 1} "
                f"({len(batch.queries)} queries{skip_label})..."
            )
            results = await client.google_maps_search_batch(
                batch.queries,
                settings.limit_per_query,
                skip_places=batch.skip_places,
                filters=out_filters or None,
                language=out_language,
                enrichment=out_enrichment or None,
                preset=preset,
                out_dir=out_dir,
                timeout_s=settings.poll_timeout_s,
            )
            if not results and client.last_error:
                log_cb(f"Outscraper batch failed: {client.last_error}")
            per_query = count_places_per_query(results, len(batch.queries))

            def _persist_now(ls: int, lev: int, ip: int) -> None:
                if run_state is None:
                    return
                planner.persist(run_state)
                _persist_run_state(
                    run_state,
                    leads_saved=ls,
                    leads_enriched_valid=lev,
                    leads_enriched_rejected=leads_enriched_rejected,
                    instantly_pushed=ip,
                    last_completed_batch_index=batch.batch_index,
                    last_submitted_batch_index=batch.batch_index,
                    inflight={},
                )

            (
                leads_saved,
                leads_enriched_valid,
                leads_enriched_rejected,
                instantly_pushed,
                batch_target_reached,
                _duplicate_saturated,
            ) = await _process_batch_results(
                results,
                config,
                seen_domain=seen_domain,
                seen_em=seen_em,
                target=target,
                target_mode=target_mode,
                leads_saved=leads_saved,
                leads_enriched_valid=leads_enriched_valid,
                leads_enriched_rejected=leads_enriched_rejected,
                pending_scraped=pending_scraped,
                pending_instantly=pending_instantly,
                instantly_enabled=instantly_enabled,
                push_every=push_every,
                enrich_enabled=enrich_enabled,
                enrich_batch_size=enrich_batch_size,
                log_cb=log_cb,
                progress_cb=progress_cb,
                metric_cb=metric_cb,
                instantly_pushed=instantly_pushed,
                batches_total=max(planner.total_slots(), 1),
                last_completed=batch.batch_index,
                on_progress_persist=_persist_now,
            )
            await _flush_pending_lead_rows_async()
            planner.record_batch_result(
                batch,
                raw_places_per_query=per_query,
                limit_per_query=settings.limit_per_query,
            )
            batches_run += 1
            log_cb(
                f"Batch {batch.batch_index + 1} processed. "
                f"Scraped: {leads_saved} | Enriched: {leads_enriched_valid} | "
                f"Instantly: {instantly_pushed}/{target}"
            )
            if run_state is not None:
                planner.persist(run_state)
                run_state["batches_total"] = batches_run
                _persist_run_state(
                    run_state,
                    leads_saved=leads_saved,
                    leads_enriched_valid=leads_enriched_valid,
                    leads_enriched_rejected=leads_enriched_rejected,
                    instantly_pushed=instantly_pushed,
                    last_completed_batch_index=batch.batch_index,
                    last_submitted_batch_index=batch.batch_index,
                    inflight={},
                )
            if batch_target_reached:
                target_reached = True
            if target_mode in ("instantly_pushed", "instantly_pushed_run"):
                progress_cb(min(instantly_pushed / target, 1.0) if target else 0.0)
            else:
                progress_cb(min(leads_saved / target, 1.0) if target else 0.0)

    inflight_tasks: set[asyncio.Task] = set()
    while (
        not target_reached
        and not planner.exhausted()
        and not _is_target_reached(
            target=target,
            target_mode=target_mode,
            leads_saved=leads_saved,
            instantly_pushed=instantly_pushed,
            config=config,
        )
    ):
        while (
            len(inflight_tasks) < settings.concurrency
            and not planner.exhausted()
            and not target_reached
        ):
            batch = planner.next_batch(settings.batch_size)
            if batch is None:
                break
            task = asyncio.create_task(_run_one_batch(batch))
            inflight_tasks.add(task)
            task.add_done_callback(inflight_tasks.discard)

        if not inflight_tasks:
            break

        done, pending = await asyncio.wait(
            inflight_tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        persistence_error: LeadPersistenceError | None = None
        for finished in done:
            try:
                await finished
            except LeadPersistenceError as exc:
                persistence_error = exc
                break
            except Exception as exc:
                log_cb(f"Batch processing error: {exc}")
        if persistence_error is not None:
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            log_cb(f"Lead save failed — stopping the scrape: {persistence_error}")
            raise persistence_error

    if inflight_tasks:
        await asyncio.gather(*inflight_tasks, return_exceptions=True)

    exhausted = planner.exhausted()
    return (
        leads_saved,
        leads_enriched_valid,
        leads_enriched_rejected,
        instantly_pushed,
        exhausted,
    )


async def run_scraper_pipeline(
    config: dict,
    log_cb: Callable[[str], None],
    progress_cb: Callable[[float], None],
    metric_cb: Callable[[int, int, int], None],
    *,
    dry_run: bool = False,
    push_to_instantly: bool = False,
    resume: bool = False,
    reset: bool = False,
    preset: str = "biggy_agency",
) -> dict[str, Any]:
    if not dry_run:
        from shared.central_leads import probe_leads_table

        probe_leads_table()
    from scrape_state import (
        apply_pipeline_config_migration,
        build_config_fingerprint,
        config_fingerprint_compatible,
        is_instantly_push_mode,
        load_scrape_state,
        mark_scrape_completed,
        mark_scrape_incomplete,
        new_scrape_state,
        save_scrape_state,
        target_mode,
        target_progress_value,
        target_uses_checkpoint_push,
        target_uses_live_list,
    )
    from scrape_metrics import fetch_instantly_live

    paths = activate_output_paths(preset)
    settings = outscraper_settings(config)
    mode = target_mode(config)
    target = int(config["TARGET_LEADS"])
    fingerprint = build_config_fingerprint(config)

    from scrape_log import make_file_log_cb
    from scrape_metrics import touch_worker_heartbeat

    log_cb = make_file_log_cb(paths.out_dir, also=log_cb)
    touch_worker_heartbeat(paths.out_dir, preset=preset, status="running")

    if reset:
        await clear_local_leads(
            cancel_remote=True,
            api_key=config.get("OUTSCRAPER_API_KEY", ""),
            log_cb=log_cb,
            preset=preset,
        )
        resume = False

    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "target": target,
        "target_mode": mode,
        "keywords": len(config["KEYWORDS"]),
        "locations": len(config["LOCATIONS"]),
        "queries_total": 0,
        "batches_total": 0,
        "batch_size": settings.batch_size,
        "concurrency": settings.concurrency,
        "limit_per_query": settings.limit_per_query,
        "leads_saved": 0,
        "leads_enriched_valid": 0,
        "leads_enriched_rejected": 0,
        "instantly_pushed": 0,
        "instantly_skipped_duplicate": 0,
        "query_passes_run": 0,
        "geo_reload_exhausted": False,
        "resumed": resume,
        "preset": preset,
    }

    pass0_queries = build_queries(config, 0)
    slot_estimate = query_planner.estimate_query_count(config)
    log_cb(
        f"Config: query planner ~{slot_estimate} slot(s) "
        f"(batch {settings.batch_size}, concurrency {settings.concurrency})"
    )
    log_cb(
        f"Outscraper SDK: limit/query={settings.limit_per_query}, "
        f"wait_async (no manual poll loop)"
    )
    log_cb(f"Target: {target} ({mode}) — output: {paths.out_dir}")
    enrich_cfg = _enrich_settings(config)
    if bool(config.get("INGESTER_ENABLED", False)):
        weights = config.get("INGESTER_SIGNAL_WEIGHTS") or {}
        log_cb(
            f"Ingester enabled — min_score={config.get('INGESTER_MIN_SCORE', 0.60)}, "
            f"borderline_min={config.get('INGESTER_BORDERLINE_MIN', 0.40)}, "
            f"concurrency={config.get('INGESTER_CONCURRENCY', 10)}, "
            f"weights={weights}"
        )
    elif enrich_cfg["enabled"]:
        log_cb(
            f"Website enrich enabled — batch {enrich_cfg['batch_size']}, "
            f"concurrency {enrich_cfg['concurrency']}, timeout {enrich_cfg['timeout_ms']}ms"
        )
    else:
        if _uncleaned_push_allowed():
            log_cb("Website enrich disabled — scraped leads go directly to Instantly push")
        else:
            log_cb(
                "Website enrich disabled — scraped leads are saved as uncleaned Supabase rows"
            )
    if bool(config.get("PAPPERS_ENABLED", False)):
        pappers_batch = _pappers_batch_settings(config)
        max_effectif = int(config.get("PAPPERS_MAX_EMPLOYEES") or 0)
        max_label = f", max effectif {max_effectif}" if max_effectif > 0 else ""
        fast_label = ", fast_mode" if config.get("PAPPERS_FAST_MODE") else ""
        log_cb(
            f"SIRET lookup enabled — batch {pappers_batch['batch_size']}, "
            f"min effectif {int(config.get('PAPPERS_MIN_EMPLOYEES', 3))}{max_label}, "
            f"min_score={int(config.get('PAPPERS_MIN_SCORE', 55) or 55)}, "
            f"on_unknown={config.get('PAPPERS_ON_UNKNOWN') or 'reject'}{fast_label}"
        )
        if bool(config.get("SIRENE_INDEX_ENABLED", True)):
            from company_registry.sirene_build import check_index
            from company_registry.config import CompanyGateConfig

            gate_cfg = CompanyGateConfig.from_dict(config)
            sirene_status = check_index(gate_cfg.resolve_sirene_path())
            if not sirene_status.get("exists"):
                log_cb(
                    "⚠️  SIRENE index missing — registry uses API fast path only. "
                    "Build with: python -m company_registry.sirene_build"
                )
            else:
                log_cb(
                    f"SIRENE index ready — {sirene_status.get('rows', 0):,} rows "
                    f"({sirene_status.get('age_days', '?')} days old)"
                )
    else:
        log_cb("SIRET lookup disabled")

    for sample in pass0_queries[:3]:
        log_cb(f"  sample query: {sample}")

    # Taxonomy gate summary — helps operators verify config before scraping begins
    if config.get("TAXONOMY_GATE_ENABLED"):
        included_n = len(config.get("TAXONOMY_INCLUDED_KEYWORDS") or [])
        excluded_n = len(config.get("TAXONOMY_HARD_EXCLUDED_KEYWORDS") or [])
        log_cb(
            f"Taxonomy gate enabled — {included_n} included keyword(s), "
            f"{excluded_n} hard-excluded keyword(s)"
        )

    if dry_run:
        push_to_instantly = _apply_uncleaned_push_policy(push_to_instantly, log_cb)
        if not config.get("OUTSCRAPER_API_KEY"):
            log_cb("WARNING: OUTSCRAPER_API_KEY is missing")
        else:
            log_cb("OUTSCRAPER_API_KEY present (dry-run — no API calls)")
        if is_instantly_push_mode(mode) and push_to_instantly:
            if config.get("INSTANTLY_API_KEY") and config.get("INSTANTLY_LIST_ID"):
                log_cb(f"Instantly push enabled — target metric is {mode}")
            else:
                log_cb(f"WARNING: TARGET_MODE={mode} requires Instantly keys + push")
        elif is_instantly_push_mode(mode):
            log_cb(
                f"Target mode {mode} counts saved leads while uncleaned Instantly push is off."
            )
        log_cb("Dry-run complete — zero Outscraper requests made.")
        summary["queries_total"] = slot_estimate
        if slot_estimate and settings.batch_size:
            summary["batches_total"] = (slot_estimate + settings.batch_size - 1) // settings.batch_size
        progress_cb(1.0)
        return summary

    if not config.get("OUTSCRAPER_API_KEY"):
        raise SystemExit("OUTSCRAPER_API_KEY is required for live scrape")

    if is_instantly_push_mode(mode) and _uncleaned_push_allowed():
        if not push_to_instantly:
            push_to_instantly = True
            log_cb(f"Auto-enabling Instantly push (target metric = {mode}).")
    push_to_instantly = _apply_uncleaned_push_policy(push_to_instantly, log_cb)

    if push_to_instantly and not dry_run:
        from bootstrap.validators import require_instantly_list_for_scrape_push

        try:
            require_instantly_list_for_scrape_push(config, preset_id=preset or "")
        except ValueError as exc:
            prefix = f"TARGET_MODE={mode}: " if is_instantly_push_mode(mode) else ""
            raise SystemExit(f"{prefix}{exc}") from exc

    from scrape_state import detect_recoverable_run

    existing_state = load_scrape_state(paths.scrape_state)
    if resume:
        if existing_state and not config_fingerprint_compatible(
            str(existing_state.get("config_fingerprint") or ""),
            config,
        ):
            log_cb(
                "Config fingerprint changed — migrating checkpoint and continuing resume."
            )
        if (
            existing_state
            and existing_state.get("push_to_instantly")
            and not push_to_instantly
            and _uncleaned_push_allowed()
        ):
            push_to_instantly = True
            log_cb("Resuming with auto-push (enabled in saved run).")
    elif not reset:
        leftover = detect_recoverable_run(
            config,
            paths.csv,
            state_path=paths.scrape_state,
        )
        if leftover.has_leftover_work:
            hint = leftover.message or (
                "Incomplete scrape detected — use resume=True or reset=True."
            )
            raise SystemExit(hint)

    _reset_lead_save_buffer()
    await _retry_unpersisted_leads()
    seen_em, seen_domain = _load_seen_from_csv()
    leads_saved = len(seen_em)
    if leads_saved:
        log_cb(f"Loaded {leads_saved} existing lead(s) from CSV for dedup.")
    touch_worker_heartbeat(paths.out_dir, preset=preset, status="running")

    instantly_enabled = push_to_instantly and bool(
        config.get("INSTANTLY_API_KEY") and config.get("INSTANTLY_LIST_ID")
    )
    workspace_emails: set[str] = set()
    if instantly_enabled:
        import asyncio

        from instantly_client import fetch_workspace_emails
        from scrape_metrics import wrap_progress_with_heartbeat

        log_cb("Loading Instantly dedup emails for duplicate skip...")
        dedup_list_ids = config.get("INSTANTLY_DEDUP_LIST_IDS") or []
        dedup_campaign_ids = config.get("INSTANTLY_DEDUP_CAMPAIGN_IDS") or []

        def _dedup_progress(n: int) -> None:
            log_cb(f"  dedup index: {n} emails loaded...")

        dedup_progress_cb = wrap_progress_with_heartbeat(
            _dedup_progress,
            lambda: touch_worker_heartbeat(paths.out_dir, preset=preset, status="running"),
            interval_s=30.0,
        )

        workspace_emails = await asyncio.to_thread(
            fetch_workspace_emails,
            config["INSTANTLY_API_KEY"],
            list_ids=dedup_list_ids,
            campaign_ids=dedup_campaign_ids,
            cache_path=paths.workspace_cache,
            log_cb=log_cb,
            on_progress=dedup_progress_cb,
        )
        before = len(seen_em)
        seen_em.update(workspace_emails)
        log_cb(
            f"Instantly workspace dedup — {len(seen_em) - before} new email(s) added to skip set "
            f"({len(seen_em)} total)."
        )
        touch_worker_heartbeat(paths.out_dir, preset=preset, status="running")

    query_pass = initial_query_pass(config)
    start_batch = 0
    resume_inflight: list[InflightBatch] = []
    run_state: dict[str, Any] | None = None
    instantly_pushed = 0
    instantly_skipped = 0
    leads_enriched_valid = 0
    leads_enriched_rejected = 0

    if resume and existing_state:
        if not config_fingerprint_compatible(
            str(existing_state.get("config_fingerprint") or ""),
            config,
        ):
            log_cb(
                "Config fingerprint changed — migrating checkpoint and continuing resume."
            )
        if apply_pipeline_config_migration(existing_state, config, log_cb=log_cb):
            save_scrape_state(existing_state, path=_active.scrape_state)
        query_pass = int(existing_state.get("query_pass", 0))
        geo_phase = str(existing_state.get("geo_phase") or "pass")
        skip_places = int(existing_state.get("skip_places", 0) or 0)
        instantly_pushed = int(existing_state.get("instantly_pushed", 0))
        instantly_skipped = int(existing_state.get("instantly_skipped_duplicate", 0))
        leads_enriched_valid = int(existing_state.get("leads_enriched_valid", 0))
        leads_enriched_rejected = int(existing_state.get("leads_enriched_rejected", 0))
        start_batch = int(existing_state.get("last_completed_batch_index", -1)) + 1
        for item in existing_state.get("inflight_tasks") or []:
            if isinstance(item, dict) and item.get("task_id"):
                resume_inflight.append(InflightBatch.from_state(item))
        run_state = existing_state
        run_state["status"] = "running"
        run_state["config_fingerprint"] = fingerprint
        if not run_state.get("geo_phase"):
            run_state["geo_phase"] = "pass"
        if run_state.get("skip_places") is None:
            run_state["skip_places"] = 0
        run_state["push_to_instantly"] = push_to_instantly
        if run_state.get("reload_round") is None:
            run_state["reload_round"] = 0
        if run_state.get("reload_round_pushed_start") is None:
            run_state["reload_round_pushed_start"] = instantly_pushed
        if leads_saved > int(run_state.get("leads_saved", 0) or 0):
            run_state["leads_saved"] = leads_saved
        save_scrape_state(run_state, path=_active.scrape_state)
        progress = instantly_pushed if target_uses_checkpoint_push(mode) else leads_saved
        log_cb(
            f"Resuming geo={geo_phase}, pass {query_pass + 1}, batch {start_batch + 1}, "
            f"skip={skip_places} ({progress}/{target} {mode})."
        )
    elif resume:
        if leads_saved == 0:
            raise SystemExit("Nothing to resume — no scrape state or CSV leads found.")
        run_state = new_scrape_state(
            config,
            preset=preset,
            push_to_instantly=push_to_instantly,
            queries_total=len(pass0_queries),
            batches_total=0,
            leads_saved=leads_saved,
            instantly_pushed=0,
            query_pass=initial_query_pass(config),
            last_completed_batch_index=-1,
        )
        save_scrape_state(run_state, path=_active.scrape_state)
        log_cb(f"Resuming from CSV without checkpoint ({leads_saved} leads in CSV).")
    else:
        run_state = new_scrape_state(
            config,
            preset=preset,
            push_to_instantly=push_to_instantly,
            queries_total=len(pass0_queries),
            batches_total=0,
            leads_saved=leads_saved,
            instantly_pushed=0,
            query_pass=initial_query_pass(config),
            last_completed_batch_index=-1,
        )
        save_scrape_state(run_state, path=_active.scrape_state)
        start_pass = initial_query_pass(config)
        if start_pass > 0:
            log_cb(
                f"Starting engine — target {target} ({mode}), "
                f"query pass {start_pass + 1}/{max_query_passes(config) + 1}."
            )
        else:
            log_cb(f"Starting engine — target {target} ({mode}).")

    if instantly_enabled and leads_saved > 0:
        instantly_pushed, _backlog_delta = await _push_csv_backlog_if_needed(
            config,
            workspace_emails=workspace_emails,
            csv_path=paths.csv,
            state_path=paths.scrape_state,
            log_cb=log_cb,
            instantly_pushed=instantly_pushed,
            run_state=run_state,
            cache_path=paths.workspace_cache,
        )
        if run_state is not None and _backlog_delta > 0:
            run_state["instantly_pushed"] = instantly_pushed
            save_scrape_state(run_state, path=_active.scrape_state)

    pending_scraped: list[dict[str, str]] = []
    pending_instantly: list[dict[str, str]] = []
    push_every = max(int(config.get("INSTANTLY_PUSH_EVERY", 100)), 1)
    enrich_enabled = enrich_cfg["enabled"]
    enrich_batch_size = enrich_cfg["batch_size"]
    out_client = OutscraperClient(config["OUTSCRAPER_API_KEY"])
    slot_total = query_planner.estimate_query_count(config)
    total_queries = slot_total
    total_batches = 0
    if run_state is not None:
        prev_version = int(run_state.get("version") or 0)
        if prev_version < 4:
            query_planner.write_planner_to_run(run_state, {})
            run_state["inflight_tasks"] = []
            log_cb("Migrated scrape checkpoint to planner v4 (skip/limit geo).")
        run_state["version"] = 4
        run_state["queries_total"] = slot_total
        save_scrape_state(run_state, path=_active.scrape_state)

    planner = query_planner.QueryPlanner.from_config(config, run_state)
    log_cb(
        f"Query planner — {planner.total_slots()} slot(s), "
        f"batch {settings.batch_size}, concurrency {settings.concurrency}, "
        f"limit/query {settings.limit_per_query} (SDK wait)."
    )

    if target_uses_live_list(mode) and config and instantly_pushed >= target:
        _live_pre = fetch_instantly_live(config, use_cache=True)
        if _live_pre is not None and _live_pre < target:
            log_cb(
                f"Instantly live below target (checkpoint {instantly_pushed}, "
                f"live {_live_pre}/{target}) — continuing Outscraper"
            )

    try:
        if instantly_enabled:
            log_cb(f"Instantly push enabled — flush every {push_every} enriched lead(s)")

        metric_cb(leads_saved, leads_enriched_valid, instantly_pushed)

        (
            leads_saved,
            leads_enriched_valid,
            leads_enriched_rejected,
            instantly_pushed,
            planner_exhausted,
        ) = await _run_planner_scrape(
            client=out_client,
            planner=planner,
            config=config,
            settings=settings,
            target=target,
            target_mode=mode,
            run_state=run_state,
            seen_domain=seen_domain,
            seen_em=seen_em,
            leads_saved=leads_saved,
            leads_enriched_valid=leads_enriched_valid,
            leads_enriched_rejected=leads_enriched_rejected,
            pending_scraped=pending_scraped,
            pending_instantly=pending_instantly,
            instantly_enabled=instantly_enabled,
            push_every=push_every,
            enrich_enabled=enrich_enabled,
            enrich_batch_size=enrich_batch_size,
            log_cb=log_cb,
            progress_cb=progress_cb,
            metric_cb=metric_cb,
            instantly_pushed=instantly_pushed,
            preset=preset,
            out_dir=paths.out_dir,
        )
        summary["geo_reload_exhausted"] = planner_exhausted
        if run_state is not None and planner_exhausted:
            run_state["geo_reload_exhausted"] = True
            save_scrape_state(run_state, path=_active.scrape_state)
        total_queries = slot_total
        total_batches = int((run_state or {}).get("batches_total", 0) or 0)

    finally:
        await out_client.aclose()

    await _flush_pending_lead_rows_async()

    if (enrich_enabled or bool(config.get("INGESTER_ENABLED", False))) and pending_scraped:
        label = "ingester" if config.get("INGESTER_ENABLED") else "enrich"
        log_cb(f"Final {label} flush — {len(pending_scraped)} scraped lead(s) remaining")
        (
            leads_enriched_valid,
            leads_enriched_rejected,
            instantly_pushed,
        ) = await _maybe_enrich_and_push(
            config=config,
            pending_scraped=pending_scraped,
            pending_instantly=pending_instantly,
            instantly_enabled=instantly_enabled,
            push_every=push_every,
            enrich_batch_size=enrich_batch_size,
            enrich_enabled=enrich_enabled,
            log_cb=log_cb,
            progress_cb=progress_cb,
            metric_cb=metric_cb,
            target=target,
            target_mode=mode,
            leads_saved=leads_saved,
            leads_enriched_valid=leads_enriched_valid,
            leads_enriched_rejected=leads_enriched_rejected,
            instantly_pushed=instantly_pushed,
            batches_total=total_batches,
            last_completed=-1,
            force_enrich=True,
        )

    if (
        not enrich_enabled
        and not bool(config.get("INGESTER_ENABLED", False))
        and pending_scraped
        and bool(config.get("PAPPERS_ENABLED", False))
    ):
        log_cb(f"Final SIRET flush — {len(pending_scraped)} scraped lead(s) remaining")
        (
            leads_enriched_valid,
            leads_enriched_rejected,
            instantly_pushed,
        ) = await _maybe_enrich_and_push(
            config=config,
            pending_scraped=pending_scraped,
            pending_instantly=pending_instantly,
            instantly_enabled=instantly_enabled,
            push_every=push_every,
            enrich_batch_size=enrich_batch_size,
            enrich_enabled=False,
            log_cb=log_cb,
            progress_cb=progress_cb,
            metric_cb=metric_cb,
            target=target,
            target_mode=mode,
            leads_saved=leads_saved,
            leads_enriched_valid=leads_enriched_valid,
            leads_enriched_rejected=leads_enriched_rejected,
            instantly_pushed=instantly_pushed,
            batches_total=total_batches,
            last_completed=-1,
            force_enrich=True,
        )

    if instantly_enabled and pending_instantly:
        flush_stats = await _flush_instantly_buffer(
            pending_instantly,
            config,
            log_cb=log_cb,
            label="final remainder",
        )
        instantly_pushed += flush_stats["pushed"]
        instantly_skipped += flush_stats["skipped_duplicate"]
        metric_cb(leads_saved, leads_enriched_valid, instantly_pushed)
        log_cb(
            f"Instantly final flush — pushed: {instantly_pushed}/{target}, "
            f"skipped (duplicate): {instantly_skipped}"
        )

    summary["leads_saved"] = leads_saved
    summary["leads_enriched_valid"] = leads_enriched_valid
    summary["leads_enriched_rejected"] = leads_enriched_rejected
    summary["instantly_pushed"] = instantly_pushed
    summary["instantly_skipped_duplicate"] = instantly_skipped
    summary["queries_total"] = total_queries
    summary["batches_total"] = total_batches

    target_reached = _is_target_reached(
        target=target,
        target_mode=mode,
        leads_saved=leads_saved,
        instantly_pushed=instantly_pushed,
        config=config,
    )
    _live_end = (
        fetch_instantly_live(config, use_cache=True)
        if target_uses_live_list(mode) and config
        else None
    )
    _progress_val = target_progress_value(
        mode,
        instantly_pushed=instantly_pushed,
        leads_saved=leads_saved,
        instantly_live=_live_end,
    )
    progress_cb(min(_progress_val / target, 1.0) if target else 1.0)

    if run_state is not None:
        run_state["instantly_skipped_duplicate"] = instantly_skipped
        run_state["leads_enriched_valid"] = leads_enriched_valid
        run_state["leads_enriched_rejected"] = leads_enriched_rejected
        if target_reached:
            mark_scrape_completed(
                run_state,
                leads_saved=leads_saved,
                leads_enriched_valid=leads_enriched_valid,
                leads_enriched_rejected=leads_enriched_rejected,
                instantly_pushed=instantly_pushed,
                path=paths.scrape_state,
            )
            log_cb(
                f"Pipeline complete. Instantly pushed: {instantly_pushed}/{target} "
                f"(scraped: {leads_saved}, enriched valid: {leads_enriched_valid})."
            )
        elif run_state.get("inflight_tasks"):
            run_state["leads_saved"] = leads_saved
            run_state["instantly_pushed"] = instantly_pushed
            run_state["status"] = "running"
            save_scrape_state(run_state, path=_active.scrape_state)
            log_cb(
                f"Pipeline paused. Instantly: {instantly_pushed}/{target}, "
                f"scraped: {leads_saved}, enriched valid: {leads_enriched_valid} (resume to continue)."
            )
        else:
            mark_scrape_incomplete(
                run_state,
                leads_saved=leads_saved,
                leads_enriched_valid=leads_enriched_valid,
                leads_enriched_rejected=leads_enriched_rejected,
                instantly_pushed=instantly_pushed,
                path=paths.scrape_state,
            )
            log_cb(
                f"Query space exhausted — Instantly: {instantly_pushed}/{target}, "
                f"scraped: {leads_saved}, enriched valid: {leads_enriched_valid}. "
                f"Expand keywords/locations or relax enrich keywords."
            )
    else:
        log_cb(
            f"Pipeline complete. Scraped: {leads_saved}, "
            f"enriched valid: {leads_enriched_valid}, Instantly: {instantly_pushed}."
        )

    _sync_mev_emails_sidecar(log_cb=log_cb)
    return summary


async def run_filter_audit(
    config: dict,
    log_cb: Callable[[str], None],
    *,
    batches: int = 1,
    preset: str = "biggy_agency",
) -> dict[str, Any]:
    """Fetch N Outscraper batches and write filter_audit.csv without saving leads."""
    if not config.get("OUTSCRAPER_API_KEY"):
        raise SystemExit("OUTSCRAPER_API_KEY is required for filter-audit")

    paths = activate_output_paths(preset)
    settings = outscraper_settings(config)

    if os.path.isfile(paths.filter_audit):
        os.remove(paths.filter_audit)

    queries = build_queries(config)
    all_batches = chunk_batches(queries, settings.batch_size)
    batch_count = min(max(batches, 1), len(all_batches))

    log_cb(
        f"Filter audit — {batch_count} batch(es), batch size {settings.batch_size}, "
        f"scrape gates (email, website, dedup)"
    )
    out_client = OutscraperClient(config["OUTSCRAPER_API_KEY"])
    seen_em: set[str] = set()
    seen_domain: set[str] = set()
    accepted = 0
    rejected = 0

    try:
        for idx in range(batch_count):
            batch = all_batches[idx]
            log_cb(f"Sending audit batch {idx + 1}/{batch_count} to Outscraper (SDK)...")
            results = await out_client.google_maps_search_batch(
                batch,
                settings.limit_per_query,
                filters=outscraper_filters(config) or None,
                language=outscraper_request_language(config),
                enrichment=outscraper_enrichment(config) or None,
                preset=preset,
                out_dir=paths.out_dir,
                timeout_s=settings.poll_timeout_s,
            )
            if not results:
                detail = getattr(out_client, "last_error", None) or "unknown error"
                log_cb(f"Batch {idx + 1} returned no results ({detail}).")
                continue

            for query_result in results:
                b_list = query_result if isinstance(query_result, list) else [query_result]
                for b in b_list:
                    if not b or not isinstance(b, dict):
                        continue
                    row, audit = _process_business(
                        b, config, seen_domain=seen_domain, seen_em=seen_em
                    )
                    if audit:
                        _append_filter_audit_row(audit)
                        if audit["Verdict"] == "accepted":
                            accepted += 1
                            if row:
                                seen_domain.add(
                                    _company_dedup_key(row["Website"], row["Email"])
                                )
                                seen_em.add(row["Email"])
                        else:
                            rejected += 1
    finally:
        await out_client.aclose()

    total = accepted + rejected
    rate = (accepted / total * 100) if total else 0.0
    log_cb(
        f"Filter audit complete — {accepted} accepted, {rejected} rejected "
        f"({rate:.1f}% acceptance) → {paths.filter_audit}"
    )
    return {
        "batches_run": batch_count,
        "accepted": accepted,
        "rejected": rejected,
        "total": total,
        "acceptance_rate": rate,
        "audit_path": paths.filter_audit,
    }


async def backfill_taxonomy_push(
    config: dict,
    *,
    csv_path: str,
    state_path: str,
    log_cb: Callable[[str], None],
    preset: str = "biggy_agency",
    batch_size: int = 100,
    dry_run: bool = False,
) -> dict[str, int]:
    """Re-filter saved CSV rows with taxonomy only, then push to Instantly."""
    from instantly_client import push_leads_to_list
    from scrape_state import load_scrape_state, save_scrape_state
    from taxonomy_gate import matches_taxonomy_csv_row, taxonomy_excluded_keywords

    if not os.path.isfile(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)
    if df.empty or "Email" not in df.columns:
        return {
            "csv_rows": 0,
            "taxonomy_pass": 0,
            "taxonomy_reject": 0,
            "attempted": 0,
            "pushed": 0,
            "skipped_duplicate": 0,
            "failed": 0,
        }

    included = list(config.get("TAXONOMY_INCLUDED_KEYWORDS") or [])
    excluded = taxonomy_excluded_keywords(config)
    taxonomy_enabled = bool(config.get("TAXONOMY_GATE_ENABLED"))

    valid_rows: list[dict[str, str]] = []
    taxonomy_reject = 0
    for _, series in df.iterrows():
        row = {str(k): ("" if pd.isna(v) else str(v)) for k, v in series.items()}
        email = str(row.get("Email") or "").strip().lower()
        if not email or "@" not in email:
            taxonomy_reject += 1
            continue
        if taxonomy_enabled:
            ok, _matched = matches_taxonomy_csv_row(row, included, excluded or None)
            if not ok:
                taxonomy_reject += 1
                continue
        valid_rows.append(row)

    log_cb(
        f"Taxonomy backfill — {len(df)} CSV row(s), {len(valid_rows)} pass taxonomy, "
        f"{taxonomy_reject} rejected"
    )

    if dry_run or not valid_rows:
        return {
            "csv_rows": len(df),
            "taxonomy_pass": len(valid_rows),
            "taxonomy_reject": taxonomy_reject,
            "attempted": 0,
            "pushed": 0,
            "skipped_duplicate": 0,
            "failed": 0,
        }

    api_key = str(config.get("INSTANTLY_API_KEY") or "").strip()
    list_id = str(config.get("INSTANTLY_LIST_ID") or "").strip()
    if not api_key or not list_id:
        raise SystemExit("INSTANTLY_API_KEY and INSTANTLY_LIST_ID required for taxonomy backfill")

    attempted = 0
    pushed = 0
    skipped = 0
    failed = 0
    chunk = max(int(batch_size), 1)

    for offset in range(0, len(valid_rows), chunk):
        batch = valid_rows[offset : offset + chunk]
        log_cb(f"Instantly backfill batch {offset // chunk + 1} — {len(batch)} lead(s)")
        stats = await push_leads_to_list(
            api_key,
            list_id,
            batch,
            skip_if_in_campaign=bool(config.get("INSTANTLY_SKIP_IF_IN_CAMPAIGN", True)),
            skip_if_in_list=bool(config.get("INSTANTLY_SKIP_IF_IN_LIST", True)),
            log_cb=log_cb,
        )
        attempted += stats["attempted"]
        pushed += stats["pushed"]
        skipped += stats["skipped_duplicate"]
        failed += stats["failed"]

    state = load_scrape_state(state_path) or {}
    prev_pushed = int(state.get("instantly_pushed", 0) or 0)
    state["instantly_pushed"] = prev_pushed + pushed
    state["instantly_skipped_duplicate"] = int(state.get("instantly_skipped_duplicate", 0) or 0) + skipped
    state["push_to_instantly"] = True
    state["leads_saved"] = max(int(state.get("leads_saved", 0) or 0), len(df))
    state["leads_enriched_valid"] = len(valid_rows)
    state["leads_enriched_rejected"] = taxonomy_reject
    save_scrape_state(state, path=state_path)

    log_cb(
        f"Taxonomy backfill done — pushed {pushed}, skipped duplicate {skipped}, "
        f"failed {failed} (checkpoint {state['instantly_pushed']})"
    )

    return {
        "csv_rows": len(df),
        "taxonomy_pass": len(valid_rows),
        "taxonomy_reject": taxonomy_reject,
        "attempted": attempted,
        "pushed": pushed,
        "skipped_duplicate": skipped,
        "failed": failed,
    }


def _load_email_recovery_queue(path: str) -> list[dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


def _dedupe_recovery_by_website(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        website = _normalize_web(str(row.get("website") or ""))
        if not website or website in seen:
            continue
        seen.add(website)
        unique.append({**row, "website": website})
    return unique


def _email_from_recovery_result(item: dict[str, Any]) -> str:
    for key in ("email", "Email"):
        value = item.get(key)
        if isinstance(value, str) and "@" in value:
            return value.strip().lower()
    emails = item.get("emails")
    if isinstance(emails, list):
        for entry in emails:
            if isinstance(entry, str) and "@" in entry:
                return entry.strip().lower()
            if isinstance(entry, dict):
                value = entry.get("value") or entry.get("email") or ""
                if isinstance(value, str) and "@" in value:
                    return value.strip().lower()
    for idx in range(1, 10):
        value = item.get(f"email_{idx}")
        if isinstance(value, str) and "@" in value:
            return value.strip().lower()
    return ""


def _website_from_recovery_result(item: dict[str, Any], fallback: str) -> str:
    for key in ("query", "domain", "website", "site", "url"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_web(value)
    return fallback


async def run_email_recovery(
    config: dict,
    *,
    log_cb: Callable[[str], None],
    preset: str = "",
    batch_size: int = 25,
    push_to_instantly: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Recover emails for queued domains via Outscraper emails-and-contacts."""
    paths = activate_output_paths(preset or "biggy_agency")
    queued = _load_email_recovery_queue(paths.email_recovery)
    unique = _dedupe_recovery_by_website(queued)
    summary: dict[str, Any] = {
        "queued": len(queued),
        "unique_domains": len(unique),
        "recovered": 0,
        "accepted": 0,
        "pushed": 0,
        "skipped_duplicate": 0,
        "failed": 0,
        "dry_run": dry_run,
    }
    if not unique:
        log_cb("Email recovery — queue empty.")
        return summary

    if not bool(config.get("OUTSCRAPER_EMAIL_RECOVERY_ENABLED", True)):
        log_cb("Email recovery disabled (OUTSCRAPER_EMAIL_RECOVERY_ENABLED=false).")
        return summary

    push_to_instantly = _apply_uncleaned_push_policy(push_to_instantly, log_cb)

    api_key = str(config.get("OUTSCRAPER_API_KEY") or "").strip()
    if not api_key:
        raise SystemExit("OUTSCRAPER_API_KEY required for email recovery")

    from outscraper_client import OutscraperClient as SdkOutscraperClient

    client = SdkOutscraperClient(api_key)
    activate_output_paths(preset or "biggy_agency")
    _reset_lead_save_buffer()
    if not dry_run:
        from shared.central_leads import probe_leads_table

        probe_leads_table()
        await _retry_unpersisted_leads()
    seen_em, seen_domain = _load_seen_from_csv()

    pending_instantly: list[dict[str, str]] = []
    accepted_rows: list[dict[str, str]] = []
    chunk = max(int(batch_size), 1)

    log_cb(
        f"Email recovery — {len(unique)} unique domain(s) "
        f"(from {len(queued)} queued row(s)), batch_size={chunk}"
    )

    for offset in range(0, len(unique), chunk):
        batch = unique[offset : offset + chunk]
        domains = [str(row.get("website") or "") for row in batch]
        log_cb(f"Recovering emails batch {offset // chunk + 1} — {len(domains)} domain(s)")
        if dry_run:
            continue
        results = await client.emails_and_contacts(domains)
        by_domain: dict[str, dict[str, Any]] = {}
        for item in results:
            if not isinstance(item, dict):
                continue
            domain = _website_from_recovery_result(item, "")
            if domain:
                by_domain[domain] = item

        for queued_row in batch:
            website = str(queued_row.get("website") or "")
            recovered = by_domain.get(website) or by_domain.get(_normalize_web(website))
            if not recovered:
                # Try fuzzy match: any result whose domain is contained in website
                for domain, item in by_domain.items():
                    if domain and (domain in website or website in domain):
                        recovered = item
                        break
            if not recovered:
                continue
            email = _email_from_recovery_result(recovered)
            if not email:
                continue
            summary["recovered"] += 1
            business = {
                "name": queued_row.get("name") or queued_row.get("company") or "",
                "site": website,
                "website": website,
                "email": email,
                "type": queued_row.get("type") or "",
                "category": queued_row.get("category") or "",
                "subtypes": queued_row.get("subtypes"),
                "city": queued_row.get("city") or "",
                "phone": queued_row.get("phone") or "",
            }
            # Avoid re-queuing into the sidecar while processing recovery results.
            gate_config = {**config, "OUTSCRAPER_EMAIL_RECOVERY_ENABLED": False}
            row, audit = _process_business(
                business,
                gate_config,
                seen_domain=seen_domain,
                seen_em=seen_em,
            )
            if audit and audit.get("Verdict") == "accepted" and row:
                summary["accepted"] += 1
                seen_em.add(row["Email"])
                seen_domain.add(_company_dedup_key(row["Website"], row["Email"]))
                await _queue_lead_row_async(row)
                accepted_rows.append(row)
                if push_to_instantly:
                    pending_instantly.append(row)

        if push_to_instantly and pending_instantly and not dry_run:
            flush_stats = await _flush_instantly_buffer(
                pending_instantly,
                config,
                log_cb=log_cb,
                label=f"email recovery batch {offset // chunk + 1}",
            )
            summary["pushed"] += int(flush_stats.get("pushed", 0) or 0)
            summary["skipped_duplicate"] += int(
                flush_stats.get("skipped_duplicate", 0) or 0
            )
            summary["failed"] += int(flush_stats.get("failed", 0) or 0)

    if push_to_instantly and pending_instantly and not dry_run:
        flush_stats = await _flush_instantly_buffer(
            pending_instantly,
            config,
            log_cb=log_cb,
            label="email recovery final",
        )
        summary["pushed"] += int(flush_stats.get("pushed", 0) or 0)
        summary["skipped_duplicate"] += int(flush_stats.get("skipped_duplicate", 0) or 0)
        summary["failed"] += int(flush_stats.get("failed", 0) or 0)

    if not dry_run:
        await _flush_pending_lead_rows_async()

    if not dry_run and unique:
        # Clear sidecar after a successful recovery pass
        with open(paths.email_recovery, "w", encoding="utf-8") as handle:
            handle.write("")
        log_cb(f"Email recovery queue cleared — {paths.email_recovery}")

    log_cb(
        f"Email recovery done — recovered={summary['recovered']}, "
        f"accepted={summary['accepted']}, pushed={summary['pushed']}, "
        f"skipped_duplicate={summary['skipped_duplicate']}"
    )
    return summary
