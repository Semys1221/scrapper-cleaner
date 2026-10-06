"""Outscraper phone enrichment: payload checks, idempotency, cost."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.central_leads import STATUS_CLEANED, InMemoryLeadsStore
from shared.phone_enrichment import (
    ERROR,
    PhonePayloadError,
    cli_main,
    enrich_cleaned_leads,
    estimate_cost,
    log_has_errors,
    needs_phone_enrichment,
    resolve_fixture_path,
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

    lead = _lead()
    store = InMemoryLeadsStore()
    store.rows[lead["email"]] = dict(lead)
    result = enrich_cleaned_leads(
        [lead],
        InvalidLookup(),
        verify=True,
        on_batch=store.save_phone_enrichment,
    )
    assert result.invalid == 1
    assert result.updated[0]["phone"] == ""
    assert result.updated[0]["phone_enrichment_status"] == "invalid"
    assert result.updated[0]["phone_enriched_at"]
    assert store.rows[lead["email"]]["phone"] == ""


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


def test_outage_leaves_existing_phone_intact_and_retryable() -> None:
    lead = _lead(phone="+33601020304")
    store = InMemoryLeadsStore()
    store.rows[lead["email"]] = dict(lead)

    class Down:
        def emails_and_contacts(self, domains: list[str]) -> dict:
            raise RuntimeError("outscraper down")

        def phones_enricher(self, phones: list[str]) -> dict:
            raise RuntimeError("outscraper down")

    try:
        enrich_cleaned_leads(
            [lead],
            Down(),
            verify=True,
            on_batch=store.save_phone_enrichment,
        )
    except RuntimeError as exc:
        assert "outscraper down" in str(exc)
    else:
        raise AssertionError("expected the outage to raise")
    saved = store.rows["jean@dupont.fr"]
    assert saved["phone"] == "+33601020304"
    assert not saved.get("phone_enriched_at")
    assert saved["phone_enrichment_status"] == ERROR
    assert needs_phone_enrichment(saved)


def test_existing_phone_is_never_cleared() -> None:
    lead = _lead(phone="+33601020304")

    class InvalidLookup(FakeLookup):
        def phones_enricher(self, phones: list[str]) -> dict:
            return {
                "status": "Success",
                "data": [{"query": phone, "carrier_type": "invalid"} for phone in phones],
            }

    result = enrich_cleaned_leads([lead], InvalidLookup(), verify=True)
    assert result.invalid == 1
    assert result.updated[0]["phone"] == "+33601020304"
    assert result.updated[0]["phone_enrichment_status"] == "invalid"

    store = InMemoryLeadsStore()
    store.rows[lead["email"]] = dict(lead)
    store.save_phone_enrichment(
        [
            {
                **lead,
                "phone": "",
                "phone_enrichment_status": "invalid",
                "phone_enriched_at": "2026-10-06T00:00:00+00:00",
            }
        ]
    )
    assert store.rows[lead["email"]]["phone"] == "+33601020304"


def test_paid_batch_is_persisted_before_later_outage(monkeypatch) -> None:
    monkeypatch.setenv("OUTSCRAPER_PHONE_BATCH_SIZE", "1")
    first = _lead(id="row-1", email="jean@dupont.fr", website="https://dupont.fr", phone="")
    second = _lead(id="row-2", email="anne@second.fr", website="https://second.fr", phone="")
    store = InMemoryLeadsStore()
    store.rows[first["email"]] = dict(first)
    store.rows[second["email"]] = dict(second)

    class Flaky(FakeLookup):
        def emails_and_contacts(self, domains: list[str]) -> dict:
            self.contact_calls.append(list(domains))
            if "second.fr" in domains:
                raise RuntimeError("outscraper down")
            return super().emails_and_contacts(domains)

    try:
        enrich_cleaned_leads(
            [first, second],
            Flaky(),
            verify=True,
            on_batch=store.save_phone_enrichment,
        )
    except RuntimeError as exc:
        assert "outscraper down" in str(exc)
    else:
        raise AssertionError("expected the second batch to raise")

    saved_first = store.rows["jean@dupont.fr"]
    assert saved_first["phone"] == "+33184801234"
    assert saved_first["phone_enriched_at"]
    saved_second = store.rows["anne@second.fr"]
    assert saved_second["phone"] == ""
    assert not saved_second.get("phone_enriched_at")
    assert saved_second["phone_enrichment_status"] == ERROR
    assert needs_phone_enrichment(saved_second)


def test_small_estimate_keeps_fractional_cents(capsys) -> None:
    code = cli_main(["--fixture", str(FIXTURE), "--preset", "plombier", "--limit", "1"])
    captured = capsys.readouterr()
    assert code == 0
    assert "estimated $0.008 per" in captured.out


def test_limit_applies_to_fixture(tmp_path, capsys) -> None:
    leads = [
        {
            "email": f"user{index}@ex.fr",
            "website": f"https://user{index}.fr",
            "category": "PLOMBIER",
            "status": "cleaned",
            "phone": "",
        }
        for index in range(3)
    ]
    path = tmp_path / "leads.json"
    path.write_text(json.dumps(leads), encoding="utf-8")
    code = cli_main(["--fixture", str(path), "--limit", "2"])
    captured = capsys.readouterr()
    assert code == 0
    assert "Dry-run fixture — 2 lead(s)" in captured.out


def test_execute_refuses_when_estimate_exceeds_cap() -> None:
    with pytest.raises(SystemExit, match="exceeds --max-cost-usd"):
        cli_main(
            [
                "--fixture",
                str(FIXTURE),
                "--preset",
                "plombier",
                "--execute",
                "--max-cost-usd",
                "0",
            ]
        )


def test_fixture_preset_filters_by_category(capsys) -> None:
    code = cli_main(["--fixture", str(FIXTURE), "--preset", "avocats"])
    captured = capsys.readouterr()
    assert code == 0
    assert "Dry-run fixture — 0 lead(s)" in captured.out


def test_fixture_path_resolves_from_repo_root(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    resolved = resolve_fixture_path("shared/tests/fixtures/cleaned_leads.json")
    assert resolved.endswith("shared/tests/fixtures/cleaned_leads.json")
    assert cli_main(["--fixture", "shared/tests/fixtures/cleaned_leads.json", "--preset", "plombier"]) == 0


def test_fixture_dry_run_prints_cost_without_errors(capsys) -> None:
    code = cli_main(["--fixture", str(FIXTURE), "--preset", "plombier"])
    captured = capsys.readouterr()
    assert code == 0
    assert "No Outscraper request was sent" in captured.out
    assert "ERROR" not in captured.out
    assert "Traceback" not in captured.out
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload[0]["category"] == "PLOMBIER"
