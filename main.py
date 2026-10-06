"""Lead scraper CLI — multi-preset Outscraper pipeline."""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_SCRAPER_DIR = os.path.join(_REPO_ROOT, "scraper")
for _path in (_SCRAPER_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)
os.chdir(_SCRAPER_DIR)

import asyncio
import json
import subprocess
from datetime import datetime, timezone

import typer

from config_loader import DEFAULT_PRESET, PRESETS, load_config
from instantly_client import (
    get_remediation_counts,
    purge_leads_from_campaign,
    purge_leads_from_list,
    push_csv_to_instantly,
)
from audit_filter import run_audit
from core_logic import (
    backfill_taxonomy_push,
    clear_local_leads,
    output_paths,
    run_email_recovery,
    run_filter_audit,
    run_scraper_pipeline,
)
from scrape_state import detect_recoverable_run, load_scrape_state, target_mode, target_progress_value

app = typer.Typer(help="Streamlit Scraper CLI")

from bootstrap.cli import app as bootstrap_app  # noqa: E402

app.add_typer(bootstrap_app, name="bootstrap")

PresetOption = typer.Option(
    DEFAULT_PRESET,
    "--preset",
    help=f"Bootstrap preset ({', '.join(sorted(PRESETS))})",
)


def _validate_preset(preset: str) -> str:
    if preset not in PRESETS:
        raise typer.BadParameter(
            f"Unknown preset {preset!r}. Available: {', '.join(sorted(PRESETS))}"
        )
    return preset


def _log(msg: str) -> None:
    typer.echo(f"[LOG] {msg}")


def _progress(prog: float) -> None:
    pass


def _metrics(scraped: int, enriched: int, pushed: int) -> None:
    typer.secho(
        f"   -> Scraped: {scraped} | Enriched valid: {enriched} | Instantly: {pushed} pushed",
        fg=typer.colors.CYAN,
    )


def _metrics_throttled(scraped: int, enriched: int, pushed: int) -> None:
    """Limit journal spam during long enrich batches."""
    import time

    if not hasattr(_metrics_throttled, "_last_ts"):
        _metrics_throttled._last_ts = 0.0  # type: ignore[attr-defined]
        _metrics_throttled._last_scraped = -1  # type: ignore[attr-defined]
    now = time.time()
    last_ts = float(_metrics_throttled._last_ts)  # type: ignore[attr-defined]
    last_scraped = int(_metrics_throttled._last_scraped)  # type: ignore[attr-defined]
    if scraped - last_scraped >= 25 or now - last_ts >= 10.0:
        _metrics(scraped, enriched, pushed)
        _metrics_throttled._last_ts = now  # type: ignore[attr-defined]
        _metrics_throttled._last_scraped = scraped  # type: ignore[attr-defined]


@app.command()
def ui() -> None:
    """Launch the Streamlit web interface."""
    typer.secho("Launching web dashboard...", fg=typer.colors.GREEN)
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", "app.py"],
        cwd=_SCRAPER_DIR,
        check=False,
    )


@app.command("dry-run")
def dry_run_cmd(
    preset: str = PresetOption,
) -> None:
    """Validate config and print query plan without calling Outscraper."""
    preset = _validate_preset(preset)
    config = load_config(preset, require_keys=False)
    summary = asyncio.run(
        run_scraper_pipeline(
            config,
            log_cb=_log,
            progress_cb=_progress,
            metric_cb=_metrics,
            dry_run=True,
            preset=preset,
        )
    )
    typer.secho(
        f"Dry-run OK [{preset}] — {summary['queries_total']} queries, "
        f"{summary['batches_total']} batches (size {summary['batch_size']}, "
        f"concurrency {summary['concurrency']}), target {summary['target']}",
        fg=typer.colors.GREEN,
    )


@app.command("filter-audit")
def filter_audit_cmd(
    batches: int = typer.Option(1, help="Number of Outscraper batches to audit"),
    preset: str = PresetOption,
) -> None:
    """Run scrape gate audit on N Outscraper batches and write filter_audit.csv."""
    preset = _validate_preset(preset)
    config = load_config(preset)
    summary = asyncio.run(
        run_filter_audit(config, log_cb=_log, batches=batches, preset=preset)
    )
    typer.secho(
        f"Audit done — {summary['accepted']} accepted / {summary['rejected']} rejected "
        f"({summary['acceptance_rate']:.1f}%) → {summary['audit_path']}",
        fg=typer.colors.GREEN,
    )


@app.command("audit-filter")
def audit_filter_cmd(
    preset: str = PresetOption,
    out_dir: str = typer.Option(
        "",
        "--out-dir",
        help="Override output directory (default: output/{preset})",
    ),
    json_out: bool = typer.Option(False, "--json", help="Write audit_filter_report.json"),
) -> None:
    """Analyze filter_audit.csv — reason breakdown and taxonomy bucket report."""
    preset = _validate_preset(preset)
    try:
        report = run_audit(
            preset,
            out_dir=out_dir.strip() or None,
            write_review=True,
            write_json=json_out,
        )
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(report["text"])
    if report.get("borderline_rows"):
        typer.secho(
            f"Borderline review → {report['review_csv_path']}",
            fg=typer.colors.GREEN,
        )


@app.command()
def remediate(
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--execute",
        help="Dry-run counts only, or execute purge + re-scrape + push",
    ),
    target: int = typer.Option(
        None,
        help="Target leads for re-scrape (default: config TARGET_LEADS)",
    ),
    preset: str = PresetOption,
) -> None:
    """Purge Instantly list+campaign, re-scrape with website enrich filter, re-upload qualified leads."""
    preset = _validate_preset(preset)
    paths = output_paths(preset)
    remediation_report_path = os.path.join(paths.out_dir, "remediation_report.json")
    config = load_config(preset)
    list_id = config.get("INSTANTLY_LIST_ID", "").strip()
    campaign_id = config.get("INSTANTLY_CAMPAIGN_ID", "").strip()
    api_key = config.get("INSTANTLY_API_KEY", "").strip()

    if not api_key or not list_id or not campaign_id:
        raise typer.BadParameter(
            "INSTANTLY_API_KEY, INSTANTLY_LIST_ID, and INSTANTLY_CAMPAIGN_ID are required"
        )

    counts = get_remediation_counts(api_key, list_id, campaign_id)
    _log(
        f"Instantly scope — list {list_id}: {counts['list_leads']} lead(s), "
        f"campaign {campaign_id}: {counts['campaign_leads']} lead(s)"
    )

    scrape_target = target if target is not None else int(config["TARGET_LEADS"])
    _log(f"Re-scrape target: {scrape_target} qualified leads")

    if dry_run:
        typer.secho(
            "Dry-run — no purge or scrape. Run with --execute to apply remediation.",
            fg=typer.colors.YELLOW,
        )
        report = {
            "mode": "dry_run",
            "preset": preset,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "instantly": counts,
            "scrape_target": scrape_target,
            "list_id": list_id,
            "campaign_id": campaign_id,
        }
        os.makedirs(paths.out_dir, exist_ok=True)
        with open(remediation_report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        _log(f"Report written → {remediation_report_path}")
        return

    typer.secho("Executing remediation...", fg=typer.colors.MAGENTA)
    purge_leads_from_list(api_key, list_id, log_cb=_log)
    purge_leads_from_campaign(api_key, campaign_id, log_cb=_log)

    if os.path.isfile(paths.filter_audit):
        os.remove(paths.filter_audit)
        _log(f"Cleared {paths.filter_audit}")

    config["TARGET_LEADS"] = scrape_target
    summary = asyncio.run(
        run_scraper_pipeline(
            config,
            log_cb=_log,
            progress_cb=_progress,
            metric_cb=_metrics,
            dry_run=False,
            push_to_instantly=True,
            reset=True,
            preset=preset,
        )
    )

    report = {
        "mode": "execute",
        "preset": preset,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "instantly_before": counts,
        "instantly_after": get_remediation_counts(api_key, list_id, campaign_id),
        "scrape": summary,
        "list_id": list_id,
        "campaign_id": campaign_id,
    }
    with open(remediation_report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    typer.secho(
        f"Remediation complete — {summary['leads_saved']} scraped, "
        f"{summary.get('leads_enriched_valid', 0)} enriched valid, "
        f"{summary.get('instantly_pushed', 0)} pushed to Instantly",
        fg=typer.colors.GREEN,
    )
    _log(f"Report → {remediation_report_path}")


@app.command("clear-leads")
def clear_leads_cmd(
    preset: str = PresetOption,
) -> None:
    """Cancel Outscraper jobs and delete local CSV + scrape state."""
    preset = _validate_preset(preset)
    config = load_config(preset, require_keys=False)
    result = asyncio.run(
        clear_local_leads(
            cancel_remote=True,
            api_key=config.get("OUTSCRAPER_API_KEY", ""),
            log_cb=_log,
            preset=preset,
        )
    )
    if not result["csv_cleared"] and not result["state_cleared"]:
        typer.secho("Nothing to clear — no local leads or scrape state found.", fg=typer.colors.YELLOW)
        return
    typer.secho(
        f"Cleared {result['leads_removed']} lead(s) from CSV"
        + (" and scrape state" if result["state_cleared"] else "")
        + f"; cancelled {result['outscraper_cancelled']} Outscraper job(s).",
        fg=typer.colors.GREEN,
    )


@app.command()
def scrape(
    target: int = typer.Option(100, help="Number of leads to scrape"),
    reset: bool = typer.Option(False, help="Clear CSV and scrape state before scraping"),
    resume: bool = typer.Option(
        False,
        help="Continue an interrupted scrape from the last checkpoint",
    ),
    push_instantly: bool = typer.Option(
        False,
        "--push-instantly",
        help="Upload leads to Instantly list after each batch (native duplicate skip)",
    ),
    preset: str = PresetOption,
) -> None:
    """Run the scraper headlessly in the terminal."""
    preset = _validate_preset(preset)
    paths = output_paths(preset)

    if reset and resume:
        raise typer.BadParameter("Use either --reset or --resume, not both.")

    config = load_config(preset)
    from shared.central_leads import uncleaned_instantly_push_allowed

    if push_instantly and not uncleaned_instantly_push_allowed():
        _log("Instantly push withheld — uncleaned leads stay in Supabase (status=uncleaned).")
        push_instantly = False
    if push_instantly:
        from bootstrap.validators import require_instantly_list_for_scrape_push

        try:
            require_instantly_list_for_scrape_push(config, preset_id=preset)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    if resume and target == 100:
        from scrape_state import load_scrape_state

        saved = load_scrape_state(paths.scrape_state)
        if saved and saved.get("target"):
            target = int(saved["target"])
            _log(f"Resume — using saved target {target}")
    config["TARGET_LEADS"] = target

    if resume:
        recovery = detect_recoverable_run(
            config,
            paths.csv,
            state_path=paths.scrape_state,
        )
        if not recovery.can_resume:
            detail = recovery.message or "No resumable scrape found."
            raise typer.BadParameter(detail)
        _log(
            f"Resuming — {recovery.leads_saved}/{recovery.target} leads, "
            f"batch {recovery.last_completed_batch_index + 2}/{recovery.batches_total}"
        )
        if recovery.push_to_instantly and not push_instantly:
            push_instantly = True
            _log("Auto-push enabled from saved run.")

    typer.secho(
        f"Starting headless scrape [{preset}] (target={target}, push_instantly={push_instantly}, "
        f"resume={resume})...",
        fg=typer.colors.MAGENTA,
    )
    summary = asyncio.run(
        run_scraper_pipeline(
            config,
            log_cb=_log,
            progress_cb=_progress,
            metric_cb=_metrics,
            dry_run=False,
            push_to_instantly=push_instantly,
            resume=resume,
            reset=reset,
            preset=preset,
        )
    )
    msg = (
        f"Done — {summary['leads_saved']} scraped, "
        f"{summary.get('leads_enriched_valid', 0)} enriched valid → {paths.csv}"
    )
    if push_instantly:
        msg += (
            f" | Instantly pushed {summary.get('instantly_pushed', 0)}, "
            f"skipped {summary.get('instantly_skipped_duplicate', 0)} duplicate(s)"
        )
    typer.secho(msg, fg=typer.colors.GREEN)


@app.command("worker-loop")
def worker_loop_cmd(
    preset: str = PresetOption,
    target: int = typer.Option(0, help="Target leads (0 = use config or checkpoint)"),
    push_instantly: bool = typer.Option(
        True,
        "--push-instantly/--no-push-instantly",
        help="Push enriched leads to Instantly",
    ),
    sleep_s: int = typer.Option(30, help="Seconds between scrape iterations"),
) -> None:
    """Run scrape/resume in a loop until target progress reaches goal."""
    import time

    from scrape_metrics import fetch_instantly_live, touch_worker_heartbeat
    from scrape_state import count_csv_leads, load_scrape_state

    preset = _validate_preset(preset)
    paths = output_paths(preset)
    config = load_config(preset)
    from shared.central_leads import uncleaned_instantly_push_allowed

    if push_instantly and not uncleaned_instantly_push_allowed():
        _log("Instantly push withheld — uncleaned leads stay in Supabase (status=uncleaned).")
        push_instantly = False
    if push_instantly:
        from bootstrap.validators import require_instantly_list_for_scrape_push

        try:
            require_instantly_list_for_scrape_push(config, preset_id=preset)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    if target > 0:
        config["TARGET_LEADS"] = target
    elif os.path.isfile(paths.scrape_state):
        saved = load_scrape_state(paths.scrape_state)
        if saved and saved.get("target"):
            config["TARGET_LEADS"] = int(saved["target"])

    goal = int(config["TARGET_LEADS"])
    mode = target_mode(config)
    _log(f"Worker loop start — preset={preset}, target={goal}, mode={mode}")

    def _loop_progress() -> int:
        state = (
            load_scrape_state(paths.scrape_state)
            if os.path.isfile(paths.scrape_state)
            else None
        )
        pushed = int(state.get("instantly_pushed", 0)) if state else 0
        live = fetch_instantly_live(config, use_cache=True)
        saved = count_csv_leads(paths.csv)
        return target_progress_value(
            mode,
            instantly_pushed=pushed,
            leads_saved=saved,
            instantly_live=live,
        )

    while True:
        touch_worker_heartbeat(paths.out_dir, preset=preset, status="running")
        progress = _loop_progress()
        if progress >= goal:
            touch_worker_heartbeat(paths.out_dir, preset=preset, status="complete")
            _log(f"Target reached — progress {progress}/{goal} ({mode}).")
            break

        recovery = detect_recoverable_run(
            config,
            paths.csv,
            state_path=paths.scrape_state,
        )
        should_resume = recovery.has_leftover_work or recovery.can_resume
        live = fetch_instantly_live(config, use_cache=True)
        state_before = (
            load_scrape_state(paths.scrape_state)
            if os.path.isfile(paths.scrape_state)
            else None
        )
        pushed_before = int(state_before.get("instantly_pushed", 0)) if state_before else 0


        planner_exhausted = bool(state_before and state_before.get("geo_reload_exhausted"))
        if planner_exhausted and progress < goal:
            idle_sleep = min(max(sleep_s * 10, 300), 900)
            touch_worker_heartbeat(paths.out_dir, preset=preset, status="blocked")
            _log(
                f"Query planner exhausted — backing off {idle_sleep}s "
                f"(progress={progress}/{goal})."
            )
            time.sleep(idle_sleep)
            continue

        _log(
            f"Scrape iteration — resume={should_resume}, "
            f"progress={progress}, live={live if live is not None else '?'}, "
            f"checkpoint={recovery.instantly_pushed}"
        )
        try:
            summary = asyncio.run(
                run_scraper_pipeline(
                    config,
                    log_cb=_log,
                    progress_cb=_progress,
                    metric_cb=_metrics_throttled,
                    push_to_instantly=push_instantly,
                    resume=should_resume,
                    preset=preset,
                )
            )
        except SystemExit as exc:
            touch_worker_heartbeat(paths.out_dir, preset=preset, status="blocked")
            _log(f"Worker blocked — {exc}")
            time.sleep(min(max(sleep_s, 10), 60))
            continue

        progress_after = _loop_progress()
        state_after = (
            load_scrape_state(paths.scrape_state)
            if os.path.isfile(paths.scrape_state)
            else None
        )
        pushed_after = int(state_after.get("instantly_pushed", 0)) if state_after else 0
        pushed_delta = pushed_after - pushed_before
        live_after = fetch_instantly_live(config, use_cache=True)
        _log(
            f"Iteration done — checkpoint pushed {int(summary.get('instantly_pushed', 0))}, "
            f"delta={pushed_delta}, progress={progress_after}, "
            f"live={live_after if live_after is not None else '?'}"
        )
        if progress_after >= goal:
            touch_worker_heartbeat(paths.out_dir, preset=preset, status="complete")
            break
        geo_reload_exhausted = bool(summary.get("geo_reload_exhausted")) or bool(
            state_after and state_after.get("geo_reload_exhausted")
        )
        if geo_reload_exhausted and progress_after <= progress and pushed_delta <= 0:
            idle_sleep = min(max(sleep_s * 10, 300), 900)
            _log(f"Geo reload exhausted — backing off {idle_sleep}s before next check.")
            if sleep_s > 0:
                time.sleep(idle_sleep)
            continue
        if progress_after <= progress and pushed_delta <= 0:
            _log("No progress this iteration — retrying immediately (geo continuation).")
            continue
        if sleep_s > 0:
            time.sleep(sleep_s)


@app.command("heal")
def heal_cmd(
    preset: str = PresetOption,
    stale_minutes: int = typer.Option(3, help="Heartbeat stale threshold (minutes)"),
) -> None:
    """Watchdog — restart systemd worker when stalled and under target."""
    import subprocess

    from scrape_metrics import (
        append_cron_event,
        fetch_instantly_live,
        heartbeat_age_seconds,
        load_worker_heartbeat,
    )

    preset = _validate_preset(preset)
    paths = output_paths(preset)
    config = load_config(preset, require_keys=False)
    goal = int(config.get("TARGET_LEADS", 0))
    service = os.getenv("VPS_SCRAPER_SERVICE", "hercule-scraper").strip()
    recovery = detect_recoverable_run(
        config,
        paths.csv,
        state_path=paths.scrape_state,
    )
    progress_before = recovery.headline_progress
    live_before = fetch_instantly_live(config, use_cache=False)
    heartbeat = load_worker_heartbeat(paths.out_dir)
    age = heartbeat_age_seconds(heartbeat)

    if progress_before >= goal > 0:
        append_cron_event(
            paths.out_dir,
            {
                "action": "noop_at_target",
                "progress": progress_before,
                "live": live_before,
                "target": goal,
            },
        )
        _log(f"Heal noop — at target (progress {progress_before}/{goal}).")
        return

    active = (
        subprocess.run(
            ["systemctl", "is-active", service],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        == "active"
    )

    if not active:
        _log(f"Heal — starting inactive worker {service}.")
        subprocess.run(["systemctl", "start", service], check=False)
        append_cron_event(
            paths.out_dir,
            {
                "action": "heal_start",
                "service": service,
                "progress": progress_before,
                "target": goal,
            },
        )
        return

    if age is not None and age < stale_minutes * 60:
        append_cron_event(
            paths.out_dir,
            {"action": "noop_healthy", "heartbeat_age_s": age},
        )
        _log(f"Heal noop — worker healthy ({int(age)}s ago).")
        return

    _log(f"Heal — restarting stale worker {service} (heartbeat {int(age or 0)}s).")
    subprocess.run(["systemctl", "restart", service], check=False)
    append_cron_event(
        paths.out_dir,
        {
            "action": "heal_restart",
            "service": service,
            "heartbeat_age_s": age,
            "progress_before": progress_before,
            "live_before": live_before,
            "target": goal,
        },
    )


@app.command("enrich-csv")
def enrich_csv_cmd(
    preset: str = PresetOption,
    csv_path: str = typer.Option("", help="CSV with Website column to enrich"),
    output: str = typer.Option("", help="Output CSV path (default: overwrite input)"),
) -> None:
    """Run HTTP website keyword check on an existing CSV."""
    import pandas as pd

    preset = _validate_preset(preset)
    paths = output_paths(preset)
    resolved_csv = csv_path or paths.csv

    from website_verifier import enrich_leads

    if not os.path.isfile(resolved_csv):
        raise typer.BadParameter(f"CSV not found: {resolved_csv}")

    config = load_config(preset, require_keys=False)
    df = pd.read_csv(resolved_csv)
    rows = df.to_dict(orient="records")
    _log(f"Enriching {len(rows)} row(s) from {resolved_csv}…")

    valid, rejected = asyncio.run(
        enrich_leads(
            [{str(k): ("" if pd.isna(v) else str(v)) for k, v in row.items()} for row in rows],
            url_column="Website",
            included=list(config.get("ENRICH_INCLUDED_KEYWORDS") or []),
            hard_excluded=list(config.get("ENRICH_HARD_EXCLUDED_KEYWORDS") or []),
            soft_excluded=list(config.get("ENRICH_SOFT_EXCLUDED_KEYWORDS") or []),
            max_concurrent=max(int(config.get("ENRICH_CONCURRENCY", 10)), 1),
            goto_timeout_ms=max(int(config.get("ENRICH_TIMEOUT_MS", 15000)), 1000),
            service_config={
                "SERVICE_DEFAULT": config.get("SERVICE_DEFAULT", ""),
                "SERVICE_RULES": list(config.get("SERVICE_RULES") or []),
            },
            siret_config=config if bool(config.get("PAPPERS_ENABLED", False)) else None,
            log_cb=_log,
        )
    )

    out_path = output or resolved_csv
    valid_df = pd.DataFrame(valid)
    valid_df.to_csv(out_path, index=False)

    if rejected:
        audit_path = paths.enrich_audit
        os.makedirs(os.path.dirname(audit_path), exist_ok=True)
        pd.DataFrame(rejected).to_csv(audit_path, index=False)
        _log(f"Rejected rows written → {audit_path}")

    typer.secho(
        f"Enrich done — {len(valid)} valid, {len(rejected)} rejected → {out_path}",
        fg=typer.colors.GREEN,
    )


@app.command("registry-push")
def registry_push_cmd(
    preset: str = PresetOption,
    csv_path: str = typer.Option("", help="CSV to validate (default: preset output CSV)"),
    limit: int = typer.Option(0, help="Max rows to process (0 = all)"),
    batch_size: int = typer.Option(0, help="Registry batch size (0 = config PAPPERS_BATCH_SIZE)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate only — do not push to Instantly"),
) -> None:
    """Fast-path: re-validate saved CSV through SIRENE registry gate and push to Instantly.

    Skips website enrich — uses PAPPERS_FAST_MODE + on_unknown from preset config.
    Use after switching from slow enrich config to taxonomy+registry fast path.
    """
    import pandas as pd

    from company_registry import validate_leads
    from instantly_client import push_leads_to_list
    from scrape_state import load_scrape_state, save_scrape_state

    preset = _validate_preset(preset)
    paths = output_paths(preset)
    config = load_config(preset)
    resolved_csv = csv_path or paths.csv

    if not os.path.isfile(resolved_csv):
        raise typer.BadParameter(f"CSV not found: {resolved_csv}")
    if not bool(config.get("PAPPERS_ENABLED", False)):
        raise typer.BadParameter("PAPPERS_ENABLED must be true for registry-push")

    df = pd.read_csv(resolved_csv)
    if df.empty:
        raise typer.BadParameter(f"CSV is empty: {resolved_csv}")

    rows = [
        {str(k): ("" if pd.isna(v) else str(v)) for k, v in row.items()}
        for row in df.to_dict(orient="records")
    ]
    if limit > 0:
        rows = rows[:limit]

    reg_batch = batch_size or max(int(config.get("PAPPERS_BATCH_SIZE", 100)), 1)
    _log(
        f"Registry-push — {len(rows)} row(s), batch {reg_batch}, "
        f"fast_mode={config.get('PAPPERS_FAST_MODE')}, "
        f"on_unknown={config.get('PAPPERS_ON_UNKNOWN')}"
    )

    valid_total: list[dict[str, str]] = []
    rejected_total = 0
    started = datetime.now(timezone.utc)

    for offset in range(0, len(rows), reg_batch):
        chunk = rows[offset : offset + reg_batch]
        _log(f"Registry batch {offset // reg_batch + 1} — {len(chunk)} lead(s)...")
        valid, rejected = asyncio.run(validate_leads(chunk, config, log_cb=_log))
        valid_total.extend(valid)
        rejected_total += len(rejected)
        _log(
            f"  → {len(valid)} valid, {len(rejected)} rejected "
            f"(running totals: {len(valid_total)} valid / {rejected_total} rejected)"
        )

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    rate = len(rows) / max(elapsed, 0.01)
    _log(f"Registry validation done in {elapsed:.1f}s ({rate:.1f} leads/s)")

    if dry_run:
        typer.secho(
            f"Dry-run — {len(valid_total)} valid, {rejected_total} rejected "
            f"(not pushed to Instantly)",
            fg=typer.colors.YELLOW,
        )
        return

    if not valid_total:
        typer.secho("No valid leads to push.", fg=typer.colors.RED)
        raise typer.Exit(1)

    api_key = config.get("INSTANTLY_API_KEY", "").strip()
    list_id = config.get("INSTANTLY_LIST_ID", "").strip()
    if not api_key or not list_id:
        raise typer.BadParameter("INSTANTLY_API_KEY and INSTANTLY_LIST_ID required to push")

    push_stats = asyncio.run(
        push_leads_to_list(
            api_key,
            list_id,
            valid_total,
            skip_if_in_campaign=bool(config.get("INSTANTLY_SKIP_IF_IN_CAMPAIGN", True)),
            skip_if_in_list=bool(config.get("INSTANTLY_SKIP_IF_IN_LIST", True)),
            log_cb=_log,
        )
    )

    state = load_scrape_state(paths.scrape_state) or {}
    prev_pushed = int(state.get("instantly_pushed", 0) or 0)
    state["instantly_pushed"] = prev_pushed + push_stats["pushed"]
    state["leads_enriched_valid"] = int(state.get("leads_enriched_valid", 0) or 0) + len(valid_total)
    state["leads_enriched_rejected"] = rejected_total
    save_scrape_state(state, path=paths.scrape_state)

    typer.secho(
        f"Registry-push complete — {len(valid_total)} valid, {rejected_total} rejected, "
        f"{push_stats['pushed']} pushed to Instantly "
        f"({push_stats['skipped_duplicate']} duplicate skip)",
        fg=typer.colors.GREEN,
    )


@app.command("taxonomy-push")
def taxonomy_push_cmd(
    preset: str = PresetOption,
    csv_path: str = typer.Option("", help="CSV to backfill (default: preset output CSV)"),
    batch_size: int = typer.Option(100, help="Instantly upload batch size"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Taxonomy filter only — no Instantly upload"),
) -> None:
    """Re-filter saved CSV with taxonomy gate only, then push to Instantly."""
    preset = _validate_preset(preset)
    paths = output_paths(preset)
    config = load_config(preset)
    resolved_csv = csv_path or paths.csv

    summary = asyncio.run(
        backfill_taxonomy_push(
            config,
            csv_path=resolved_csv,
            state_path=paths.scrape_state,
            log_cb=_log,
            preset=preset,
            batch_size=batch_size,
            dry_run=dry_run,
        )
    )
    msg = (
        f"Taxonomy backfill [{preset}] — {summary['taxonomy_pass']}/{summary['csv_rows']} pass, "
        f"{summary['pushed']} pushed, {summary['skipped_duplicate']} duplicate skip"
    )
    if summary.get("failed"):
        msg += f", {summary['failed']} failed"
    typer.secho(msg, fg=typer.colors.GREEN if summary.get("pushed") else typer.colors.YELLOW)


@app.command("recover-emails")
def recover_emails_cmd(
    preset: str = PresetOption,
    batch_size: int = typer.Option(25, help="Domains per Outscraper emails-and-contacts call"),
    push_instantly: bool = typer.Option(
        True,
        "--push-instantly/--no-push-instantly",
        help="Push accepted recovered leads to Instantly",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="List queue size without API calls"),
) -> None:
    """Recover emails for queued no-email businesses via Outscraper emails-and-contacts."""
    preset = _validate_preset(preset)
    config = load_config(preset, require_keys=not dry_run)
    summary = asyncio.run(
        run_email_recovery(
            config,
            log_cb=_log,
            preset=preset,
            batch_size=batch_size,
            push_to_instantly=push_instantly,
            dry_run=dry_run,
        )
    )
    typer.secho(
        f"Email recovery [{preset}] — queued={summary['queued']} "
        f"unique={summary['unique_domains']} recovered={summary['recovered']} "
        f"accepted={summary['accepted']} pushed={summary['pushed']} "
        f"skipped_duplicate={summary['skipped_duplicate']}",
        fg=typer.colors.GREEN,
    )


@app.command("enrich-phones")
def enrich_phones_cmd(
    execute: bool = typer.Option(
        False,
        "--execute",
        help="Call Outscraper and write phones. Omit to print the cost estimate only.",
    ),
    limit: int = typer.Option(1000, help="Maximum cleaned leads to consider."),
    preset: str = typer.Option("", help="Preset id mapped to a one-word category."),
    fixture: str = typer.Option("", help="JSON fixture of cleaned leads. Skips the production table."),
    verify: bool = typer.Option(True, "--verify/--no-verify"),
) -> None:
    """Retrieve verified phone numbers for cleaned leads. Does not run unless --execute."""
    from shared.phone_enrichment import cli_main

    argv = ["--limit", str(limit)]
    if execute:
        argv.append("--execute")
    if preset:
        argv.extend(["--preset", preset])
    if fixture:
        argv.extend(["--fixture", fixture])
    if not verify:
        argv.append("--no-verify")
    raise typer.Exit(cli_main(argv))


@app.command("push-instantly")
def push_instantly_cmd(
    preset: str = PresetOption,
) -> None:
    """Push CSV rows to Instantly (native duplicate skip via skip_if_in_campaign/list)."""
    from shared.central_leads import uncleaned_instantly_push_allowed

    if not uncleaned_instantly_push_allowed():
        raise typer.BadParameter(
            "Refusing to push uncleaned leads to Instantly. "
            "Clean them first (status=cleaned), or set HERCULE_ALLOW_UNCLEANED_INSTANTLY_PUSH=1."
        )
    preset = _validate_preset(preset)
    paths = output_paths(preset)
    config = load_config(preset)
    if not os.path.isfile(paths.csv):
        raise typer.BadParameter(f"CSV not found: {paths.csv}")

    summary = asyncio.run(
        push_csv_to_instantly(
            paths.csv,
            config["INSTANTLY_API_KEY"],
            config["INSTANTLY_LIST_ID"],
            log_cb=_log,
            provision_config=config,
        )
    )
    typer.secho(
        f"Uploaded {summary['pushed']} lead(s) — "
        f"{summary['skipped_duplicate']} skipped by Instantly (duplicate)"
        + (f", {summary['failed']} failed" if summary["failed"] else ""),
        fg=typer.colors.GREEN,
    )


@app.command("sirene-build")
def sirene_build_cmd(
    check: bool = typer.Option(False, "--check", help="Only verify index presence/age"),
    dest: str = typer.Option("", "--dest", help="Override SQLite output path"),
    max_rows: int = typer.Option(0, "--max-rows", help="Limit rows (0 = full import)"),
    url: str = typer.Option("", "--url", help="Override StockEtablissement download URL"),
) -> None:
    """Download INSEE StockEtablissement and build local SIRENE SQLite index."""
    from company_registry.sirene_build import build_index, check_index, sirene_db_path

    path = dest or sirene_db_path()
    if check:
        status = check_index(path)
        if not status.get("exists"):
            typer.secho(f"SIRENE index missing at {path}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(
            f"SIRENE index OK — {status['rows']:,} rows, age {status.get('age_days')} day(s)",
            fg=typer.colors.GREEN,
        )
        return

    _log(f"Building SIRENE index at {path}…")
    result = build_index(
        dest_path=path,
        log_cb=_log,
        max_rows=max_rows if max_rows > 0 else None,
        source_url=url or None,
    )
    typer.secho(f"SIRENE index built → {result}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
