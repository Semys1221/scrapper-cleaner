"""Outscraper phone enrichment: payload checks, idempotency, cost."""

from __future__ import annotations

import json
from pathlib import Path

from shared.central_leads import STATUS_CLEANED, InMemoryLeadsStore
from shared.phone_enrichment import (
    PhonePayloadError,
    cli_main,
    enrich_cleaned_leads,
    estimate_cost,
    log_has_errors,
    run_from_store,
    validate_contacts_payload,
    validate_phones_enricher_payload,
)

FIXTURE = Path(__file__).parent / "fixtures" / "cleaned_leads.json"


class FakeLookup:
    def __init__(self) -> None:
        self.contact_calls: list[list[str]] = []
        self.verify_calls: list[list[str]] = []

    def emails_and_contacts(self, domains: list[str]) -> dict:
        self.contact_calls.append(list(domains))
        return {
            "status": "Success",
            "data": [
                {
                    "query": domain,
                    "domain": domain,
                    "phone_1": "+33 1 84 80 12 34",
                    "emails": [{"value": f"contact@{domain}"}],
                }
                for domain in domains
            ],
        }

    def phones_enricher(self, phones: list[str]) -> dict:
        self.verify_calls.append(list(phones))
        return {
            "status": "Success",
            "data": [
                {"query": phone, "carrier_name": "ORANGE", "carrier_type": "mobile"}
                for phone in phones
            ],
        }


def _lead(**overrides: object) -> dict:
    base = {
        "id": "row-1",
        "email": "jean@dupont.fr",
        "first_name": "Jean",
        "last_name": "Dupont",
        "company": "Dupont Plomberie",
        "website": "https://www.dupont.fr/contact",
        "phone": "",
        "category": "PLOMBIER",
        "status": STATUS_CLEANED,
        "phone_enriched_at": None,
        "phone_enrichment_status": None,
    }
    base.update(overrides)
    return base


def test_cost_per_1000_leads() -> None:
    cost = estimate_cost(1000, verify=True, hit_rate=1.0)
    assert cost["retrieval_usd"] == 3.0
    assert cost["verification_usd"] == 5.0
    assert cost["total_usd"] == 8.0
    assert estimate_cost(1000, verify=False)["total_usd"] == 3.0


def test_rejects_failed_contacts_payload() -> None:
    try:
        validate_contacts_payload({"status": "Failure", "errorMessage": "bad key"})
    except PhonePayloadError as exc:
        assert "bad key" in str(exc)
    else:
        raise AssertionError("expected PhonePayloadError")
    validate_phones_enricher_payload(
        {"status": "Success", "data": [{"query": "+33100000000", "carrier_type": "mobile"}]}
    )


def test_enrichment_is_idempotent_and_logs_have_no_errors() -> None:
    lookup = FakeLookup()
    first = enrich_cleaned_leads([_lead()], lookup, verify=True)
    assert first.verified == 1
    assert first.updated[0]["phone"] == "+33184801234"
    assert first.updated[0]["phone_enrichment_status"] == "enriched"
    assert first.updated[0]["phone_enriched_at"]
    assert log_has_errors(first.logs) == []
    assert lookup.contact_calls == [["dupont.fr"]]
    assert lookup.verify_calls == [["+33184801234"]]

    second = enrich_cleaned_leads(first.updated, lookup, verify=True)
    assert second.eligible == 0
    assert second.skipped_already_enriched == 1
    assert lookup.contact_calls == [["dupont.fr"]]
    assert log_has_errors(second.logs) == []


def test_invalid_carrier_does_not_store_phone() -> None:
    class InvalidLookup(FakeLookup):
        def phones_enricher(self, phones: list[str]) -> dict:
            return {
                "status": "Success",
                "data": [{"query": phone, "carrier_type": "invalid"} for phone in phones],
            }

    result = enrich_cleaned_leads([_lead()], InvalidLookup(), verify=True)
    assert result.invalid == 1
    assert result.updated[0]["phone"] == ""
    assert result.updated[0]["phone_enrichment_status"] == "invalid"
    assert result.updated[0]["phone_enriched_at"]


def test_store_execute_skips_enriched_rows() -> None:
    store = InMemoryLeadsStore()
    store.rows["jean@dupont.fr"] = _lead()
    lookup = FakeLookup()
    first = run_from_store(
        execute=True,
        limit=10,
        category="PLOMBIER",
        verify=True,
        lookup=lookup,
        store=store,
    )
    assert first.verified == 1
    second = run_from_store(
        execute=True,
        limit=10,
        category="PLOMBIER",
        verify=True,
        lookup=lookup,
        store=store,
    )
    assert second.eligible == 0
    assert lookup.contact_calls == [["dupont.fr"]]


def test_fixture_dry_run_prints_cost_without_errors(capsys) -> None:
    code = cli_main(["--fixture", str(FIXTURE), "--preset", "plombier"])
    captured = capsys.readouterr()
    assert code == 0
    assert "No Outscraper request was sent" in captured.out
    assert "ERROR" not in captured.out
    assert "Traceback" not in captured.out
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload[0]["category"] == "PLOMBIER"
