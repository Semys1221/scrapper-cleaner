"""Phone enrichment for cleaned leads via Outscraper.

Retrieval uses ``GET /emails-and-contacts`` (phones published on the cleaned
website). Verification uses ``GET /phones-enricher`` (carrier name and type).
A lead is skipped when ``phone_enriched_at`` is already set.

Published medium-tier prices (after the monthly free quota):
- emails-and-contacts: $3 per 1,000 domains (free for the first 500 domains)
- phones-enricher: $5 per 1,000 numbers (free for the first 25 numbers)

Budget **$8 per 1,000 leads** when every lead needs a website lookup and yields
one number that is then verified. Leads that already have a phone only pay the
$5 verification. Disabling verification (``--no-verify``) caps retrieval at $3.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from shared.central_leads import (
    STATUS_CLEANED,
    category_for_preset,
    normalize_phone,
    supabase_store_from_env,
    utc_now,
)

logger = logging.getLogger(__name__)

# Medium tier, free quota already consumed. See module docstring.
RETRIEVAL_USD_PER_1000 = 3.0
VERIFICATION_USD_PER_1000 = 5.0

ENRICHED = "enriched"
NOT_FOUND = "not_found"
INVALID = "invalid"
ERROR = "error"
SKIPPED = "skipped"

_ERROR_STATUS = {"failure", "error", "failed"}


class PhonePayloadError(ValueError):
    """Outscraper response is missing the fields this step requires."""


class PhoneLookup(Protocol):
    def emails_and_contacts(self, domains: list[str]) -> Any: ...

    def phones_enricher(self, phones: list[str]) -> Any: ...


@dataclass
class EnrichmentResult:
    eligible: int = 0
    skipped_already_enriched: int = 0
    retrieved: int = 0
    verified: int = 0
    not_found: int = 0
    invalid: int = 0
    updated: list[dict[str, Any]] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "skipped_already_enriched": self.skipped_already_enriched,
            "retrieved": self.retrieved,
            "verified": self.verified,
            "not_found": self.not_found,
            "invalid": self.invalid,
            "updated": len(self.updated),
        }


def estimate_cost(lead_count: int, *, verify: bool = True, hit_rate: float = 1.0) -> dict[str, float]:
    """USD estimate for ``lead_count`` cleaned leads at published medium-tier rates."""
    count = max(int(lead_count), 0)
    rate = min(max(float(hit_rate), 0.0), 1.0)
    retrieval = round(count * RETRIEVAL_USD_PER_1000 / 1000.0, 4)
    verification = round(count * rate * VERIFICATION_USD_PER_1000 / 1000.0, 4) if verify else 0.0
    return {
        "leads": float(count),
        "retrieval_usd": retrieval,
        "verification_usd": verification,
        "total_usd": round(retrieval + verification, 4),
    }


def needs_phone_enrichment(lead: dict[str, Any]) -> bool:
    if lead.get("phone_enriched_at"):
        return False
    status = str(lead.get("phone_enrichment_status") or "").strip().lower()
    if status in {ENRICHED, NOT_FOUND, INVALID}:
        return False
    return str(lead.get("status") or STATUS_CLEANED) == STATUS_CLEANED


def website_domain(website: str) -> str:
    raw = (website or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    host = urlparse(raw).netloc.lower().split("@")[-1]
    if host.startswith("www."):
        host = host[4:]
    return host.split(":")[0]


def _as_record_list(raw: Any, *, label: str) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        if raw.get("error") is True or str(raw.get("status") or "").strip().lower() in _ERROR_STATUS:
            message = raw.get("errorMessage") or raw.get("error") or raw.get("status")
            raise PhonePayloadError(f"{label} failed: {message}")
        data = raw.get("data")
        if data is None and ("query" in raw or "domain" in raw):
            data = [raw]
        if not isinstance(data, list):
            raise PhonePayloadError(f"{label} payload is missing a data list")
        raw = data
    if not isinstance(raw, list):
        raise PhonePayloadError(f"{label} payload must be a list or a status/data object")
    records: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise PhonePayloadError(f"{label} item is not an object")
        records.append(item)
    return records


def validate_contacts_payload(raw: Any) -> list[dict[str, Any]]:
    records = _as_record_list(raw, label="emails-and-contacts")
    for item in records:
        if not any(str(item.get(key) or "").strip() for key in ("query", "domain", "website")):
            raise PhonePayloadError("emails-and-contacts item is missing query/domain")
    return records


def validate_phones_enricher_payload(raw: Any) -> list[dict[str, Any]]:
    records = _as_record_list(raw, label="phones-enricher")
    for item in records:
        if not str(item.get("query") or "").strip():
            raise PhonePayloadError("phones-enricher item is missing query")
    return records


def _collect_phone_strings(value: Any, found: list[str]) -> None:
    if isinstance(value, str):
        found.append(value)
        return
    if isinstance(value, dict):
        for key in ("value", "phone", "number"):
            if value.get(key):
                found.append(str(value[key]))
        return
    if isinstance(value, list):
        for entry in value:
            _collect_phone_strings(entry, found)


def extract_phone_candidates(item: dict[str, Any]) -> list[str]:
    raw: list[str] = []
    for key in ("phone", "phone_number"):
        if item.get(key):
            raw.append(str(item[key]))
    _collect_phone_strings(item.get("phones"), raw)
    for index in range(1, 6):
        value = item.get(f"phone_{index}")
        if value:
            raw.append(str(value))
    contacts = item.get("contacts")
    if isinstance(contacts, list):
        for contact in contacts:
            if isinstance(contact, dict):
                _collect_phone_strings(contact.get("phones") or contact.get("phone"), raw)
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in raw:
        phone = normalize_phone(value)
        if phone and phone not in seen:
            seen.add(phone)
            cleaned.append(phone)
    return cleaned


def phone_is_verified(item: dict[str, Any]) -> bool:
    if item.get("error"):
        return False
    carrier_type = str(item.get("carrier_type") or "").strip().lower()
    carrier_name = str(item.get("carrier_name") or "").strip()
    if carrier_type in {"", "invalid", "unknown", "undeliverable"} and not carrier_name:
        return False
    if carrier_type in {"invalid", "undeliverable"}:
        return False
    return bool(carrier_type or carrier_name)


def _index_contacts(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in records:
        for key in ("query", "domain", "website"):
            domain = website_domain(str(item.get(key) or ""))
            if domain:
                indexed[domain] = item
    return indexed


def _index_verified(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in records:
        phone = normalize_phone(item.get("query"))
        if phone:
            indexed[phone] = item
    return indexed


def _batch_size() -> int:
    raw = os.getenv("OUTSCRAPER_PHONE_BATCH_SIZE", "100").strip() or "100"
    try:
        size = int(raw)
    except ValueError:
        size = 100
    return min(max(size, 1), 1000)


def _log(result: EnrichmentResult, message: str, log_cb: Callable[[str], None] | None) -> None:
    result.logs.append(message)
    if log_cb:
        log_cb(message)


def _finish(
    lead: dict[str, Any],
    *,
    phone: str,
    enrichment_status: str,
) -> dict[str, Any]:
    now = utc_now()
    return {
        **lead,
        "phone": phone,
        "phone_enrichment_status": enrichment_status,
        "phone_enriched_at": now,
        "updated_at": now,
    }


def _without_private(lead: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in lead.items()
        if not str(key).startswith("_") and key != "clear_unverified_phone"
    }


def _error_row(lead: dict[str, Any]) -> dict[str, Any]:
    """Outage marker. phone_enriched_at is omitted so the lead stays retryable."""
    row = _without_private(lead)
    row.pop("phone_enriched_at", None)
    row["phone_enrichment_status"] = ERROR
    row["updated_at"] = utc_now()
    return row


def enrich_cleaned_leads(
    leads: list[dict[str, Any]],
    lookup: PhoneLookup | None,
    *,
    verify: bool = True,
    log_cb: Callable[[str], None] | None = None,
    on_batch: Callable[[list[dict[str, Any]]], None] | None = None,
) -> EnrichmentResult:
    """Enrich cleaned leads. ``lookup`` is required only when a lead still needs a call.

    Each paid batch is handed to ``on_batch`` before the next Outscraper call.
    A client error is persisted as ``error`` without ``phone_enriched_at`` and re-raised.
    """
    result = EnrichmentResult()
    pending: list[dict[str, Any]] = []
    for lead in leads:
        if needs_phone_enrichment(lead):
            pending.append(dict(lead))
        else:
            result.skipped_already_enriched += 1
    result.eligible = len(pending)
    cost = estimate_cost(result.eligible, verify=verify)
    _log(
        result,
        (
            f"Phone enrichment — eligible={result.eligible} "
            f"skipped_already_enriched={result.skipped_already_enriched} "
            f"estimated_usd={cost['total_usd']}"
        ),
        log_cb,
    )
    if not pending:
        return result

    def _persist(rows: list[dict[str, Any]], *, final: bool) -> None:
        if on_batch and rows:
            on_batch(rows)
        if final:
            result.updated.extend(_without_private(row) for row in rows)

    def _fail(batch_leads: list[dict[str, Any]], exc: BaseException) -> None:
        errored = [_error_row(lead) for lead in batch_leads]
        for row in errored:
            message = f"ERROR phone enrichment outage for {row.get('email')}: {exc}"
            logger.error(message)
            _log(result, message, log_cb)
        _persist(errored, final=True)
        raise exc

    size = _batch_size()
    verify_queue: list[tuple[dict[str, Any], str]] = []
    no_call: list[dict[str, Any]] = []
    domain_leads: list[dict[str, Any]] = []

    for lead in pending:
        domain = website_domain(str(lead.get("website") or ""))
        existing_phone = normalize_phone(lead.get("phone"))
        if existing_phone and verify:
            verify_queue.append((lead, existing_phone))
            continue
        if existing_phone and not verify:
            result.verified += 1
            _persist([_finish(lead, phone=existing_phone, enrichment_status=ENRICHED)], final=True)
            continue
        if not domain:
            no_call.append(lead)
            continue
        lead["_enrich_domain"] = domain
        domain_leads.append(lead)

    if no_call:
        _log(result, f"Phone enrichment — {len(no_call)} lead(s) have no website and no phone.", log_cb)
        finished = [
            _finish(lead, phone=normalize_phone(lead.get("phone")), enrichment_status=NOT_FOUND)
            for lead in no_call
        ]
        result.not_found += len(finished)
        _persist(finished, final=True)

    def _verify_pairs(pairs: list[tuple[dict[str, Any], str]], *, label: str) -> None:
        if not pairs:
            return
        if lookup is None:
            raise PhonePayloadError("phone lookup client is required to verify numbers")
        phones: list[str] = []
        by_phone: dict[str, list[dict[str, Any]]] = {}
        for lead, phone in pairs:
            by_phone.setdefault(phone, []).append(lead)
            if phone not in phones:
                phones.append(phone)
        for offset in range(0, len(phones), size):
            batch = phones[offset : offset + size]
            batch_leads = [lead for phone in batch for lead in by_phone[phone]]
            _log(
                result,
                f"phones-enricher {label} batch {offset // size + 1} — {len(batch)} number(s).",
                log_cb,
            )
            try:
                records = validate_phones_enricher_payload(lookup.phones_enricher(batch))
            except Exception as exc:
                _fail(batch_leads, exc)
            verified_by_phone = _index_verified(records)
            finished: list[dict[str, Any]] = []
            for phone in batch:
                item = verified_by_phone.get(phone)
                for lead in by_phone[phone]:
                    if item and phone_is_verified(item):
                        result.verified += 1
                        finished.append(_finish(lead, phone=phone, enrichment_status=ENRICHED))
                    else:
                        result.invalid += 1
                        original = normalize_phone(lead.get("phone"))
                        row = _finish(lead, phone=original, enrichment_status=INVALID)
                        if not original:
                            row["clear_unverified_phone"] = True
                        finished.append(row)
            _persist(finished, final=True)

    _verify_pairs(verify_queue, label="existing")

    by_domain: dict[str, list[dict[str, Any]]] = {}
    domains: list[str] = []
    for lead in domain_leads:
        domain = str(lead["_enrich_domain"])
        if domain not in by_domain:
            domains.append(domain)
            by_domain[domain] = []
        by_domain[domain].append(lead)

    if domains and lookup is None:
        raise PhonePayloadError("phone lookup client is required to retrieve numbers")

    for offset in range(0, len(domains), size):
        batch = domains[offset : offset + size]
        batch_leads = [lead for domain in batch for lead in by_domain[domain]]
        _log(result, f"emails-and-contacts batch {offset // size + 1} — {len(batch)} domain(s).", log_cb)
        try:
            records = validate_contacts_payload(lookup.emails_and_contacts(batch))  # type: ignore[union-attr]
        except Exception as exc:
            _fail(batch_leads, exc)
        contacts_by_domain = _index_contacts(records)
        finished = []
        partials = []
        found_pairs: list[tuple[dict[str, Any], str]] = []
        for lead in batch_leads:
            domain = str(lead.pop("_enrich_domain", ""))
            item = contacts_by_domain.get(domain)
            candidates = extract_phone_candidates(item) if item else []
            if not candidates:
                result.not_found += 1
                finished.append(
                    _finish(lead, phone=normalize_phone(lead.get("phone")), enrichment_status=NOT_FOUND)
                )
                continue
            result.retrieved += 1
            if verify:
                partial = _without_private(lead)
                partial["phone"] = candidates[0]
                partial["updated_at"] = utc_now()
                partials.append(partial)
                found_pairs.append((lead, candidates[0]))
            else:
                result.verified += 1
                finished.append(_finish(lead, phone=candidates[0], enrichment_status=ENRICHED))
        _persist(partials, final=False)
        _persist(finished, final=True)
        _verify_pairs(found_pairs, label="retrieved")

    _log(
        result,
        (
            f"Phone enrichment done — verified={result.verified} "
            f"not_found={result.not_found} invalid={result.invalid}"
        ),
        log_cb,
    )
    return result


def log_has_errors(lines: list[str]) -> list[str]:
    pattern = re.compile(r"\b(ERROR|Traceback|CRITICAL)\b")
    return [line for line in lines if pattern.search(line)]


def run_from_store(
    *,
    execute: bool,
    limit: int,
    category: str | None,
    verify: bool,
    lookup: PhoneLookup | None,
    store: Any | None = None,
    log_cb: Callable[[str], None] | None = None,
) -> EnrichmentResult:
    target = store if store is not None else supabase_store_from_env()
    if target is None:
        result = EnrichmentResult()
        _log(result, "Phone enrichment skipped — Supabase is not configured.", log_cb)
        return result
    candidates = target.list_phone_candidates(limit=limit, category=category)
    if not execute:
        result = EnrichmentResult(eligible=sum(1 for lead in candidates if needs_phone_enrichment(lead)))
        cost = estimate_cost(result.eligible, verify=verify)
        _log(
            result,
            (
                f"Dry-run — {result.eligible} cleaned lead(s) would be enriched. "
                f"Estimated cost ${cost['total_usd']:.2f} "
                f"(retrieval ${cost['retrieval_usd']:.2f} + verification ${cost['verification_usd']:.2f}). "
                "No Outscraper request was sent."
            ),
            log_cb,
        )
        return result
    return enrich_cleaned_leads(
        candidates,
        lookup,
        verify=verify,
        log_cb=log_cb,
        on_batch=target.save_phone_enrichment,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enrich cleaned Supabase leads with verified Outscraper phone numbers."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Call Outscraper and write phones. Without this flag the command only estimates cost.",
    )
    parser.add_argument("--limit", type=int, default=1000, help="Maximum cleaned leads to consider.")
    parser.add_argument(
        "--preset",
        default="",
        help="Optional preset id. Mapped to a one-word category (example: plombier -> PLOMBIER).",
    )
    parser.add_argument(
        "--fixture",
        default="",
        help="JSON file of cleaned lead objects. Does not read the production table.",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Store the first phone from emails-and-contacts without phones-enricher.",
    )
    return parser


class SdkPhoneLookup:
    """Sync adapter around the async Outscraper client used by the scraper."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def emails_and_contacts(self, domains: list[str]) -> Any:
        import asyncio

        return asyncio.run(self.client.emails_and_contacts(domains))

    def phones_enricher(self, phones: list[str]) -> Any:
        import asyncio

        return asyncio.run(self.client.phones_enricher(phones))


def _sdk_lookup() -> SdkPhoneLookup:
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    scraper_dir = root / "scraper"
    for path in (str(scraper_dir), str(root)):
        if path not in sys.path:
            sys.path.insert(0, path)
    from outscraper_client import OutscraperClient

    return SdkPhoneLookup(OutscraperClient(os.environ["OUTSCRAPER_API_KEY"].strip()))


def resolve_fixture_path(path: str) -> str:
    """Resolve a fixture path from the original working directory or the repo root.

    ``main.py`` changes into ``scraper/`` before commands run, so a relative
    ``shared/tests/...`` path is not next to the process cwd.
    """
    if not path or os.path.isabs(path):
        return path
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    for base in (os.getcwd(), root):
        candidate = os.path.abspath(os.path.join(base, path))
        if os.path.isfile(candidate):
            return candidate
    return os.path.abspath(os.path.join(root, path))


def _filter_fixture_category(payload: list[Any], category: str | None) -> list[dict[str, Any]]:
    rows = [lead for lead in payload if isinstance(lead, dict)]
    if not category:
        return rows
    return [lead for lead in rows if str(lead.get("category") or "").strip() == category]


def cli_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logs: list[str] = []

    def _log(message: str) -> None:
        logs.append(message)
        print(message)

    try:
        category = category_for_preset(args.preset) if args.preset else None
        verify = not args.no_verify
        if args.fixture:
            fixture_path = resolve_fixture_path(args.fixture)
            with open(fixture_path, encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, list):
                raise SystemExit("fixture must be a JSON list of lead objects")
            leads = _filter_fixture_category(payload, category)
            if not args.execute:
                eligible = sum(1 for lead in leads if needs_phone_enrichment(lead))
                cost = estimate_cost(eligible, verify=verify)
                _log(
                    f"Dry-run fixture — {eligible} lead(s), estimated ${cost['total_usd']:.2f} "
                    "per the published medium-tier rate. No Outscraper request was sent."
                )
            else:
                api_key = os.getenv("OUTSCRAPER_API_KEY", "").strip()
                if not api_key:
                    raise SystemExit("OUTSCRAPER_API_KEY is required for --execute")
                enrich_cleaned_leads(leads, _sdk_lookup(), verify=verify, log_cb=_log)
        else:
            if args.execute and not os.getenv("OUTSCRAPER_API_KEY", "").strip():
                raise SystemExit("OUTSCRAPER_API_KEY is required for --execute")
            lookup = _sdk_lookup() if args.execute else None
            run_from_store(
                execute=args.execute,
                limit=args.limit,
                category=category,
                verify=verify,
                lookup=lookup,
                log_cb=_log,
            )
    except SystemExit:
        raise
    except Exception as exc:
        logger.error("phone enrichment failed: %s", exc)
        print(f"ERROR phone enrichment failed: {exc}")
        return 1
    errors = log_has_errors(logs)
    if errors:
        logger.error("phone enrichment log contained errors: %s", errors)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
