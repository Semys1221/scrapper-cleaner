"""Disk-backed scrape run state for resume after interruption."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from paths import output_paths as _output_paths


def scrape_state_path(preset: str = "avocats") -> str:
    return _output_paths(preset).scrape_state


SCRAPE_STATE_PATH = scrape_state_path("avocats")

STATE_VERSION = 4
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_INCOMPLETE = "incomplete"
STATUS_ARCHIVED = "archived"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def target_mode(config: dict) -> str:
    return str(config.get("TARGET_MODE") or "csv_saved").strip()


CHECKPOINT_PUSH_MODES = frozenset({"instantly_pushed", "instantly_pushed_run"})
LIVE_LIST_TARGET_MODES = frozenset({"instantly_pushed"})
VALID_TARGET_MODES = frozenset({"csv_saved", "instantly_pushed", "instantly_pushed_run"})


def uncleaned_instantly_push_allowed() -> bool:
    """False unless HERCULE_ALLOW_UNCLEANED_INSTANTLY_PUSH is set.

    Uncleaned leads stay in Supabase. Progress then counts saved leads instead
    of the Instantly list size.
    """
    raw = os.getenv("HERCULE_ALLOW_UNCLEANED_INSTANTLY_PUSH", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def target_uses_live_list(mode: str) -> bool:
    return mode in LIVE_LIST_TARGET_MODES


def target_uses_checkpoint_push(mode: str) -> bool:
    return mode in CHECKPOINT_PUSH_MODES


def is_instantly_push_mode(mode: str) -> bool:
    return mode in CHECKPOINT_PUSH_MODES


def target_progress_value(
    mode: str,
    *,
    instantly_pushed: int = 0,
    leads_saved: int = 0,
    instantly_live: int | None = None,
) -> int:
    if mode in CHECKPOINT_PUSH_MODES and uncleaned_instantly_push_allowed():
        if target_uses_live_list(mode) and instantly_live is not None:
            return instantly_live
        return instantly_pushed
    return leads_saved


def is_target_reached(
    *,
    target: int,
    mode: str,
    leads_saved: int,
    instantly_pushed: int,
    config: dict | None = None,
    instantly_live: int | None = None,
) -> bool:
    """Whether the scrape run should stop (same semantics as worker-loop progress).

    For ``instantly_pushed``, worker progress uses the Instantly live list count when
    available. The checkpoint ``instantly_pushed`` can exceed ``target`` (e.g. partial
    pushes before 429 defer, list purges) without meaning the live list hit the goal.
    When checkpoint is at or near target, completion requires ``instantly_live >= target``.
    If live is unavailable, falls back to checkpoint >= target.
    """
    if target <= 0:
        return True
    if target_uses_live_list(mode) and config and uncleaned_instantly_push_allowed():
        checkpoint_met = instantly_pushed >= target
        near_target = instantly_pushed >= target - 50 or instantly_pushed >= int(
            target * 0.95
        )
        if checkpoint_met or near_target:
            live = instantly_live
            if live is None:
                from scrape_metrics import fetch_instantly_live

                live = fetch_instantly_live(config, use_cache=True)
            if live is not None:
                return live >= target
            return checkpoint_met
        return False
    return target_progress_value(
        mode,
        instantly_pushed=instantly_pushed,
        leads_saved=leads_saved,
        instantly_live=instantly_live,
    ) >= target


def build_config_identity_fingerprint(config: dict) -> str:
    """Identity hash for resume — keywords, gates, taxonomy (excludes tuning/speed knobs)."""
    parts = [
        "|".join(sorted(config.get("KEYWORDS", []))),
        "|".join(sorted(config.get("EXPANSION_KEYWORDS", []))),
        "|".join(sorted(config.get("LOCATIONS", []))),
        "|".join(sorted(config.get("EXPANSION_LOCATIONS", []))),
        "|".join(sorted(config.get("EXCLUDE_DOMAINS", []))),
        str(config.get("ENRICH_ENABLED", "")),
        "|".join(sorted(config.get("ENRICH_INCLUDED_KEYWORDS", []))),
        "|".join(sorted(config.get("ENRICH_HARD_EXCLUDED_KEYWORDS", []))),
        "|".join(sorted(config.get("ENRICH_SOFT_EXCLUDED_KEYWORDS", []))),
        str(config.get("TAXONOMY_GATE_ENABLED", "")),
        "|".join(sorted(config.get("TAXONOMY_INCLUDED_KEYWORDS", []))),
        str(config.get("SERVICE_DEFAULT", "")),
        "|".join(
            f"{rule.get('label', '')}:{','.join(sorted(rule.get('keywords') or []))}"
            for rule in (config.get("SERVICE_RULES") or [])
            if isinstance(rule, dict)
        ),
        target_mode(config),
        str(config.get("PAPPERS_ENABLED", "")),
        str(config.get("PAPPERS_MIN_EMPLOYEES", "")),
        str(config.get("PAPPERS_MAX_EMPLOYEES", "")),
        str(config.get("PAPPERS_MIN_SCORE", "")),
        str(config.get("PAPPERS_SCORING_ENABLED", "")),
        str(config.get("PAPPERS_ON_UNKNOWN", "")),
        str(config.get("PAPPERS_FAST_MODE", "")),
        str(config.get("SIRENE_INDEX_ENABLED", "")),
        str(config.get("REGISTRY_DEEP_ENRICH", "")),
        str(config.get("REJECT_HOLDINGS", "")),
        "|".join(sorted(str(item) for item in (config.get("PAPPERS_NAF_PREFIXES") or []))),
        "|".join(sorted(config.get("TAXONOMY_HARD_EXCLUDED_KEYWORDS") or [])),
    ]
    payload = "\n".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_config_fingerprint(config: dict) -> str:
    """Resume fingerprint — tuning knobs (concurrency, poll, batch) intentionally excluded."""
    return build_config_identity_fingerprint(config)


def build_config_legacy_fingerprint(config: dict) -> str:
    """Pre-overnight-fix fingerprint (includes tuning keys) for resume migration."""
    parts = [
        "|".join(sorted(config.get("KEYWORDS", []))),
        "|".join(sorted(config.get("EXPANSION_KEYWORDS", []))),
        "|".join(sorted(config.get("LOCATIONS", []))),
        "|".join(sorted(config.get("EXPANSION_LOCATIONS", []))),
        "|".join(sorted(config.get("EXCLUDE_DOMAINS", []))),
        str(config.get("ENRICH_ENABLED", "")),
        str(config.get("ENRICH_BATCH_SIZE", "")),
        str(config.get("ENRICH_CONCURRENCY", "")),
        str(config.get("ENRICH_TIMEOUT_MS", "")),
        "|".join(sorted(config.get("ENRICH_INCLUDED_KEYWORDS", []))),
        "|".join(sorted(config.get("ENRICH_HARD_EXCLUDED_KEYWORDS", []))),
        "|".join(sorted(config.get("ENRICH_SOFT_EXCLUDED_KEYWORDS", []))),
        str(config.get("TAXONOMY_GATE_ENABLED", "")),
        "|".join(sorted(config.get("TAXONOMY_INCLUDED_KEYWORDS", []))),
        str(config.get("SERVICE_DEFAULT", "")),
        "|".join(
            f"{rule.get('label', '')}:{','.join(sorted(rule.get('keywords') or []))}"
            for rule in (config.get("SERVICE_RULES") or [])
            if isinstance(rule, dict)
        ),
        str(config.get("OUTSCRAPER_BATCH_SIZE", "")),
        target_mode(config),
        str(config.get("PAPPERS_ENABLED", "")),
        str(config.get("PAPPERS_MIN_EMPLOYEES", "")),
        str(config.get("PAPPERS_MAX_EMPLOYEES", "")),
        str(config.get("PAPPERS_MIN_SCORE", "")),
        str(config.get("PAPPERS_SCORING_ENABLED", "")),
        str(config.get("PAPPERS_ON_UNKNOWN", "")),
        str(config.get("SIRENE_INDEX_ENABLED", "")),
        str(config.get("REGISTRY_DEEP_ENRICH", "")),
        str(config.get("REJECT_HOLDINGS", "")),
        str(config.get("SCRAPE_START_QUERY_PASS", "")),
        "|".join(sorted(str(item) for item in (config.get("PAPPERS_NAF_PREFIXES") or []))),
    ]
    payload = "\n".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def config_fingerprint_compatible(saved: str | None, config: dict) -> bool:
    if not saved:
        return True
    current = build_config_fingerprint(config)
    if saved == current:
        return True
    return saved == build_config_legacy_fingerprint(config)


def apply_pipeline_config_migration(
    run_state: dict[str, Any],
    config: dict,
    *,
    log_cb: Any = None,
) -> bool:
    """Reset geo/reload flags when pipeline identity changes (e.g. enrich off, on_unknown accept).

    Returns True when migration was applied.
    """
    import query_planner

    current_identity = build_config_identity_fingerprint(config)
    saved_identity = str(run_state.get("config_identity_fingerprint") or "")

    if saved_identity and saved_identity == current_identity:
        return False

    run_state["config_identity_fingerprint"] = current_identity
    run_state["config_fingerprint"] = build_config_fingerprint(config)
    run_state.pop("geo_reload_exhausted", None)
    run_state["reload_round"] = 0
    run_state["reload_round_pushed_start"] = int(run_state.get("instantly_pushed", 0) or 0)
    run_state.pop("geo_phase", None)
    run_state.pop("query_pass", None)
    run_state.pop("skip_places", None)
    query_planner.write_planner_to_run(run_state, {})
    run_state["last_completed_batch_index"] = -1
    run_state["last_submitted_batch_index"] = -1
    run_state["inflight_tasks"] = []
    run_state["status"] = STATUS_INCOMPLETE
    run_state["version"] = STATE_VERSION

    if log_cb:
        if saved_identity:
            log_cb(
                "Pipeline config changed — geo state reset "
                f"(enrich={config.get('ENRICH_ENABLED')}, "
                f"on_unknown={config.get('PAPPERS_ON_UNKNOWN')}, "
                f"fast_mode={config.get('PAPPERS_FAST_MODE')})."
            )
            if int(run_state.get("leads_saved", 0) or 0) > 0:
                log_cb(
                    "Existing CSV dedup is still active — run with reset=True for a "
                    "clean scrape, or `registry-push` to re-validate saved leads."
                )
        else:
            log_cb("Pipeline identity fingerprint stored for future migrations.")

    _clear_stale_registry_caches(config, preset=str(run_state.get("preset") or ""))

    return bool(saved_identity)


def _clear_stale_registry_caches(config: dict, *, preset: str = "") -> None:
    """Remove legacy unversioned siret_cache.json after policy-versioned caches."""
    try:
        from company_registry.validate import _cache_path_for_config

        preset_id = preset or str(config.get("PRESET_ID") or "")
        if not preset_id:
            return
        config = {**config, "PRESET_ID": preset_id}
        current = _cache_path_for_config(config)
        out_dir = os.path.dirname(current)
        if not os.path.isdir(out_dir):
            return
        for name in os.listdir(out_dir):
            if not name.startswith("siret_cache") or not name.endswith(".json"):
                continue
            path = os.path.join(out_dir, name)
            if path != current and os.path.isfile(path):
                os.remove(path)
    except OSError:
        pass


def count_csv_leads(csv_path: str) -> int:
    if not os.path.isfile(csv_path):
        return 0
    try:
        df = pd.read_csv(csv_path)
        if df.empty or "Email" not in df.columns:
            return 0
        return int(
            df["Email"]
            .dropna()
            .astype(str)
            .str.contains("@", regex=False)
            .sum()
        )
    except (OSError, pd.errors.EmptyDataError, ValueError):
        return 0


def ui_target_progress(
    config: dict,
    state: dict[str, Any] | None,
    *,
    instantly_live: int | None = None,
) -> tuple[int, int, bool]:
    """Return (progress, target, at_target) from manifest config + scrape_state."""
    target = int(config.get("TARGET_LEADS", 0))
    mode = target_mode(config)
    leads_saved = int(state.get("leads_saved", 0)) if state else 0
    instantly_pushed = int(state.get("instantly_pushed", 0)) if state else 0
    progress = target_progress_value(
        mode,
        instantly_pushed=instantly_pushed,
        leads_saved=leads_saved,
        instantly_live=instantly_live,
    )
    at_target = progress >= target > 0
    return progress, target, at_target


def load_scrape_state(path: str = SCRAPE_STATE_PATH) -> dict[str, Any] | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


def save_scrape_state(state: dict[str, Any], path: str = SCRAPE_STATE_PATH) -> None:
    state["last_updated"] = _utc_now()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def clear_scrape_state(path: str = SCRAPE_STATE_PATH) -> None:
    if os.path.isfile(path):
        os.remove(path)


def mark_scrape_completed(
    state: dict[str, Any],
    *,
    leads_saved: int,
    leads_enriched_valid: int = 0,
    leads_enriched_rejected: int = 0,
    instantly_pushed: int = 0,
    path: str = SCRAPE_STATE_PATH,
) -> None:
    state["status"] = STATUS_COMPLETED
    state["leads_saved"] = leads_saved
    state["leads_enriched_valid"] = leads_enriched_valid
    state["leads_enriched_rejected"] = leads_enriched_rejected
    state["instantly_pushed"] = instantly_pushed
    save_scrape_state(state, path)


def mark_scrape_incomplete(
    state: dict[str, Any],
    *,
    leads_saved: int,
    leads_enriched_valid: int = 0,
    leads_enriched_rejected: int = 0,
    instantly_pushed: int = 0,
    path: str = SCRAPE_STATE_PATH,
) -> None:
    state["status"] = STATUS_INCOMPLETE
    state["leads_saved"] = leads_saved
    state["leads_enriched_valid"] = leads_enriched_valid
    state["leads_enriched_rejected"] = leads_enriched_rejected
    state["instantly_pushed"] = instantly_pushed
    save_scrape_state(state, path)


def new_scrape_state(
    config: dict,
    *,
    preset: str = "biggy_agency",
    push_to_instantly: bool = False,
    queries_total: int,
    batches_total: int,
    leads_saved: int = 0,
    leads_enriched_valid: int = 0,
    leads_enriched_rejected: int = 0,
    instantly_pushed: int = 0,
    query_pass: int = 0,
    geo_phase: str = "pass",
    skip_places: int = 0,
    planner: dict[str, Any] | None = None,
    last_completed_batch_index: int = -1,
    last_submitted_batch_index: int = -1,
    inflight_tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    return {
        "version": STATE_VERSION,
        "status": STATUS_RUNNING,
        "preset": preset,
        "config_fingerprint": build_config_fingerprint(config),
        "config_identity_fingerprint": build_config_identity_fingerprint(config),
        "target": int(config["TARGET_LEADS"]),
        "target_mode": target_mode(config),
        "push_to_instantly": push_to_instantly,
        "queries_total": queries_total,
        "batches_total": batches_total,
        "query_pass": query_pass,
        "geo_phase": geo_phase,
        "skip_places": skip_places,
        "planner": planner or {},
        "last_completed_batch_index": last_completed_batch_index,
        "last_submitted_batch_index": last_submitted_batch_index,
        "inflight_tasks": inflight_tasks or [],
        "leads_saved": leads_saved,
        "leads_enriched_valid": leads_enriched_valid,
        "leads_enriched_rejected": leads_enriched_rejected,
        "instantly_pushed": instantly_pushed,
        "instantly_skipped_duplicate": 0,
        "places_requested_total": 0,
        "spend_usd_total": 0.0,
        "spend_usd_today": 0.0,
        "spend_utc_day": "",
        "email_recovery_spend_usd": 0.0,
        "reload_round": 0,
        "reload_round_pushed_start": instantly_pushed,
        "started_at": now,
        "last_updated": now,
    }


def _inflight_count(state: dict[str, Any] | None) -> int:
    if not state:
        return 0
    tasks = state.get("inflight_tasks") or []
    return sum(
        1 for item in tasks if isinstance(item, dict) and item.get("task_id")
    )


def _progress_value(state: dict[str, Any] | None, config: dict, csv_path: str) -> int:
    mode = target_mode(config)
    instantly_pushed = int(state.get("instantly_pushed", 0)) if state else 0
    return target_progress_value(
        mode,
        instantly_pushed=instantly_pushed,
        leads_saved=count_csv_leads(csv_path),
    )


@dataclass
class RecoverableRun:
    """Scrape recovery snapshot for UI/CLI."""

    has_leftover_work: bool = False
    can_resume: bool = False
    leads_saved: int = 0
    leads_enriched_valid: int = 0
    leads_enriched_rejected: int = 0
    instantly_pushed: int = 0
    target: int = 0
    target_mode: str = "csv_saved"
    batches_total: int = 0
    query_pass: int = 0
    last_completed_batch_index: int = -1
    pending_push: int = 0
    push_to_instantly: bool = False
    last_updated: str = ""
    has_checkpoint: bool = False
    config_mismatch: bool = False
    inflight_count: int = 0
    instantly_live: int | None = None
    message: str = ""

    @property
    def progress(self) -> int:
        if target_uses_checkpoint_push(self.target_mode):
            return self.instantly_pushed
        return self.leads_saved

    @property
    def headline_progress(self) -> int:
        """Best progress for UI: Instantly live when available, else checkpoint."""
        return target_progress_value(
            self.target_mode,
            instantly_pushed=self.instantly_pushed,
            leads_saved=self.leads_saved,
            instantly_live=self.instantly_live,
        )

    @property
    def is_recoverable(self) -> bool:
        """Backward-compatible alias for can_resume."""
        return self.can_resume


def detect_recoverable_run(
    config: dict,
    csv_path: str,
    *,
    state_path: str = SCRAPE_STATE_PATH,
) -> RecoverableRun:
    from instantly_client import csv_push_stats

    leads_saved = count_csv_leads(csv_path)
    target = int(config.get("TARGET_LEADS", 0))
    mode = target_mode(config)
    push_stats = csv_push_stats(csv_path)
    pending_push = push_stats["pending"]
    fingerprint = build_config_fingerprint(config)
    state = load_scrape_state(state_path)
    inflight_count = _inflight_count(state)
    instantly_pushed = int(state.get("instantly_pushed", 0)) if state else 0
    leads_enriched_valid = int(state.get("leads_enriched_valid", 0)) if state else 0
    leads_enriched_rejected = int(state.get("leads_enriched_rejected", 0)) if state else 0
    instantly_live: int | None = None
    if target_uses_live_list(mode):
        from scrape_metrics import fetch_instantly_live

        instantly_live = fetch_instantly_live(config)
    progress = target_progress_value(
        mode,
        instantly_pushed=instantly_pushed,
        leads_saved=leads_saved,
        instantly_live=instantly_live,
    )

    if progress >= target > 0:
        if state and state.get("status") not in (STATUS_COMPLETED, STATUS_INCOMPLETE):
            mark_scrape_completed(
                state,
                leads_saved=leads_saved,
                instantly_pushed=instantly_pushed,
                path=state_path,
            )
        if leads_saved > 0 or inflight_count > 0 or instantly_pushed > 0 or (instantly_live or 0) > 0:
            return RecoverableRun(
                has_leftover_work=True,
                can_resume=False,
                leads_saved=leads_saved,
                leads_enriched_valid=leads_enriched_valid,
                leads_enriched_rejected=leads_enriched_rejected,
                instantly_pushed=instantly_pushed,
                instantly_live=instantly_live,
                target=target,
                target_mode=mode,
                inflight_count=inflight_count,
                pending_push=pending_push,
                message="Target reached on Instantly — scrape complete.",
            )
        return RecoverableRun(
            leads_saved=leads_saved,
            leads_enriched_valid=leads_enriched_valid,
            leads_enriched_rejected=leads_enriched_rejected,
            instantly_pushed=instantly_pushed,
            target=target,
            target_mode=mode,
        )

    config_mismatch = bool(
        state
        and state.get("config_fingerprint")
        and not config_fingerprint_compatible(str(state["config_fingerprint"]), config)
    )

    recorded_spend = False
    if state is not None:
        try:
            recorded_spend = float(state.get("spend_usd_total") or 0) > 0 or int(
                state.get("places_requested_total") or 0
            ) > 0
        except (TypeError, ValueError):
            recorded_spend = False
    # Spend is part of the leftover. A later scrape or worker-loop iteration
    # must resume this state instead of opening a fresh one at $0.
    has_leftover_work = (
        leads_saved > 0
        or inflight_count > 0
        or instantly_pushed > 0
        or recorded_spend
        or (state is not None and state.get("status") == STATUS_RUNNING)
    )

    if not has_leftover_work:
        return RecoverableRun(
            leads_saved=0,
            target=target,
            target_mode=mode,
        )

    if config_mismatch:
        return RecoverableRun(
            has_leftover_work=True,
            can_resume=True,
            leads_saved=leads_saved,
            leads_enriched_valid=leads_enriched_valid,
            leads_enriched_rejected=leads_enriched_rejected,
            instantly_pushed=instantly_pushed,
            instantly_live=instantly_live,
            target=target,
            target_mode=mode,
            batches_total=int(state.get("batches_total", 0)) if state else 0,
            query_pass=int(state.get("query_pass", 0)) if state else 0,
            last_completed_batch_index=int(state.get("last_completed_batch_index", -1))
            if state
            else -1,
            pending_push=pending_push,
            push_to_instantly=bool(state.get("push_to_instantly", False)) if state else False,
            last_updated=str(state.get("last_updated", "")) if state else "",
            has_checkpoint=int(state.get("last_completed_batch_index", -1)) >= 0 if state else False,
            inflight_count=inflight_count,
            config_mismatch=True,
            message=(
                "Config fingerprint changed — soft-resuming with migrated checkpoint "
                "(wipe local only if keywords/locations/gates changed intentionally)."
            ),
        )

    if state:
        status = str(state.get("status") or "")
        if status in (STATUS_COMPLETED, STATUS_INCOMPLETE):
            saved_target = int(state.get("target", target))
            saved_mode = str(state.get("target_mode", mode))
            live_progress = target_progress_value(
                saved_mode,
                instantly_pushed=int(state.get("instantly_pushed", 0)),
                leads_saved=leads_saved,
                instantly_live=instantly_live,
            )
            under_target = live_progress < saved_target
            if under_target or inflight_count > 0:
                return RecoverableRun(
                    has_leftover_work=True,
                    can_resume=True,
                    leads_saved=leads_saved,
                    leads_enriched_valid=leads_enriched_valid,
                    leads_enriched_rejected=leads_enriched_rejected,
                    instantly_pushed=instantly_pushed,
                    instantly_live=instantly_live,
                    target=saved_target,
                    target_mode=saved_mode,
                    batches_total=int(state.get("batches_total", 0)),
                    query_pass=int(state.get("query_pass", 0)),
                    last_completed_batch_index=int(state.get("last_completed_batch_index", -1)),
                    pending_push=pending_push,
                    push_to_instantly=bool(state.get("push_to_instantly", False)),
                    last_updated=str(state.get("last_updated", "")),
                    has_checkpoint=int(state.get("last_completed_batch_index", -1)) >= 0,
                    inflight_count=inflight_count,
                    message=(
                        f"{inflight_count} Outscraper job(s) still in flight."
                        if inflight_count
                        else (
                            "Under target — continue to resume scraping and city expansion."
                            if status == STATUS_INCOMPLETE
                            else "Continue scraping toward target."
                        )
                    ),
                )
            return RecoverableRun(
                has_leftover_work=True,
                can_resume=False,
                leads_saved=leads_saved,
                leads_enriched_valid=leads_enriched_valid,
                leads_enriched_rejected=leads_enriched_rejected,
                instantly_pushed=instantly_pushed,
                instantly_live=instantly_live,
                target=saved_target,
                target_mode=saved_mode,
                inflight_count=inflight_count,
                pending_push=pending_push,
                message="Run finished at target — wipe local data only if starting a new campaign.",
            )

        batches_total = int(state.get("batches_total", 0))
        last_batch = int(state.get("last_completed_batch_index", -1))
        saved_target = int(state.get("target", target))
        saved_mode = str(state.get("target_mode", mode))
        live_progress = target_progress_value(
            saved_mode,
            instantly_pushed=int(state.get("instantly_pushed", 0)),
            leads_saved=leads_saved,
            instantly_live=instantly_live,
        )
        return RecoverableRun(
            has_leftover_work=True,
            can_resume=live_progress < saved_target or inflight_count > 0,
            leads_saved=leads_saved,
            leads_enriched_valid=leads_enriched_valid,
            leads_enriched_rejected=leads_enriched_rejected,
            instantly_pushed=instantly_pushed,
            instantly_live=instantly_live,
            target=saved_target,
            target_mode=saved_mode,
            batches_total=batches_total,
            query_pass=int(state.get("query_pass", 0)),
            last_completed_batch_index=last_batch,
            pending_push=pending_push,
            push_to_instantly=bool(state.get("push_to_instantly", False)),
            last_updated=str(state.get("last_updated", "")),
            has_checkpoint=last_batch >= 0,
            inflight_count=inflight_count,
            message=(
                "No batch checkpoint yet — continue may re-fetch early batches "
                "(CSV dedup prevents duplicate rows)."
                if last_batch < 0
                else (
                    f"{inflight_count} Outscraper job(s) still in flight."
                    if inflight_count
                    else ""
                )
            ),
        )

    queries_total = len(config.get("KEYWORDS", [])) * len(config.get("LOCATIONS", []))
    batch_size = max(int(config.get("OUTSCRAPER_BATCH_SIZE", 500)), 1)
    batches_total = (queries_total + batch_size - 1) // batch_size if queries_total else 0
    return RecoverableRun(
        has_leftover_work=True,
        can_resume=True,
        leads_saved=leads_saved,
        leads_enriched_valid=leads_enriched_valid,
        leads_enriched_rejected=leads_enriched_rejected,
        instantly_pushed=instantly_pushed,
        target=target,
        target_mode=mode,
        batches_total=batches_total,
        last_completed_batch_index=-1,
        pending_push=pending_push,
        push_to_instantly=False,
        has_checkpoint=False,
        message=(
            "Interrupted run detected from CSV (no checkpoint file). "
            "Continue may re-fetch early batches — duplicates are skipped in CSV."
        ),
    )
