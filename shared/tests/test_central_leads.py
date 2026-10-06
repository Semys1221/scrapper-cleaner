"""Central leads contract: category, status, and idempotent upsert."""

from __future__ import annotations

from shared.central_leads import (
    STATUS_CLEANED,
    STATUS_IN_CAMPAIGN,
    STATUS_UNCLEANED,
    InMemoryLeadsStore,
    category_for_preset,
    core_instantly_custom_variables,
    mark_emails_cleaned,
    merge_uncleaned,
    scraped_row_to_lead,
)


def test_category_for_preset_is_one_word() -> None:
    assert category_for_preset("plombier") == "PLOMBIER"
    assert category_for_preset("avocats") == "AVOCAT"
    assert category_for_preset("cabinets_expertise_comptable") == "COMPTABLE"


def test_scraped_row_is_uncleaned() -> None:
    lead = scraped_row_to_lead(
        {
            "Email": "Jean@Dupont.fr",
            "Company": "Dupont Plomberie",
            "Website": "https://dupont.fr",
            "Phone": "+33 1 84 80 12 34",
            "PlaceId": "place-1",
            "FirstName": "Jean",
            "LastName": "Dupont",
        },
        preset="plombier",
    )
    assert lead["email"] == "jean@dupont.fr"
    assert lead["category"] == "PLOMBIER"
    assert lead["status"] == STATUS_UNCLEANED
    assert lead["phone"] == "+33184801234"
    assert lead["source"] == "outscraper"
    assert lead["source_id"] == "place-1"
    assert lead["list_id"] is None


def test_upsert_does_not_downgrade_status_or_enriched_phone() -> None:
    store = InMemoryLeadsStore()
    lead = scraped_row_to_lead(
        {"Email": "a@ex.fr", "Company": "A", "Website": "https://a.fr", "Phone": "0612345678"},
        preset="avocats",
    )
    assert store.upsert_uncleaned([lead])["inserted"] == 1
    stored = store.rows[("a@ex.fr", "AVOCAT")]
    stored["status"] = STATUS_IN_CAMPAIGN
    stored["phone"] = "+33600000000"
    stored["phone_enriched_at"] = "2026-10-06T00:00:00+00:00"
    again = scraped_row_to_lead(
        {"Email": "a@ex.fr", "Company": "Renamed", "Website": "https://a.fr", "Phone": "0699999999"},
        preset="avocats",
    )
    stats = store.upsert_uncleaned([again])
    assert stats["skipped"] == 1
    assert stored["status"] == STATUS_IN_CAMPAIGN
    assert stored["phone"] == "+33600000000"
    assert stored["company"] == "A"


def test_cleaner_marks_only_uncleaned_rows() -> None:
    store = InMemoryLeadsStore()
    lead = scraped_row_to_lead(
        {"Email": "a@ex.fr", "Company": "A", "Website": "https://a.fr"},
        preset="plombier",
    )
    store.upsert_uncleaned([lead])
    result = mark_emails_cleaned(["a@ex.fr"], store=store)
    assert result["updated"] == 1
    assert store.rows[("a@ex.fr", "PLOMBIER")]["status"] == STATUS_CLEANED
    assert mark_emails_cleaned(["a@ex.fr"], store=store)["updated"] == 0


def test_merge_fills_blank_phone_without_downgrade() -> None:
    patch = merge_uncleaned(
        {"status": STATUS_CLEANED, "phone": "", "website": "https://a.fr", "phone_enriched_at": None},
        {"phone": "+33100000000", "website": "https://other.fr", "company": "X"},
    )
    assert patch["phone"] == "+33100000000"
    assert "status" not in patch
    assert "company" not in patch


def test_instantly_custom_variables_drop_registry_fields() -> None:
    custom = core_instantly_custom_variables(
        {"siret": "123", "city": "Lyon", "naf": "43.22A", "category": "plumber"},
        phone="+33612345678",
        category="PLOMBIER",
        status="cleaned",
        cleaned="valid",
    )
    assert custom == {
        "phone": "+33612345678",
        "category": "PLOMBIER",
        "status": "cleaned",
        "cleaned": "valid",
    }
