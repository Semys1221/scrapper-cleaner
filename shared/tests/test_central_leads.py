"""Central leads contract: category, status, and idempotent upsert."""

from __future__ import annotations

import re

from shared.central_leads import (
    STATUS_CLEANED,
    STATUS_IN_CAMPAIGN,
    STATUS_UNCLEANED,
    InMemoryLeadsStore,
    SupabaseLeadsStore,
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
    stored = store.rows["a@ex.fr"]
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
    assert store.rows["a@ex.fr"]["status"] == STATUS_CLEANED
    assert mark_emails_cleaned(["a@ex.fr"], store=store)["updated"] == 0


def test_merge_fills_blank_phone_without_downgrade() -> None:
    patch = merge_uncleaned(
        {
            "status": STATUS_CLEANED,
            "phone": "",
            "website": "https://a.fr",
            "company": "",
            "category": "PLOMBIER",
            "phone_enriched_at": None,
        },
        {
            "phone": "+33100000000",
            "website": "https://other.fr",
            "company": "X",
            "category": "AVOCAT",
            "status": STATUS_UNCLEANED,
        },
    )
    assert patch["phone"] == "+33100000000"
    assert patch["company"] == "X"
    assert "status" not in patch
    assert "website" not in patch
    assert "category" not in patch


def test_duplicate_email_keeps_category_and_fills_empty_fields() -> None:
    store = InMemoryLeadsStore()
    first = scraped_row_to_lead(
        {
            "Email": "  Jean@Dupont.fr ",
            "Company": "Dupont",
            "Website": "dupont.fr",
            "FirstName": "Jean",
        },
        preset="plombier",
    )
    second = scraped_row_to_lead(
        {
            "Email": "jean@dupont.fr",
            "Company": "Other Co",
            "Website": "",
            "Phone": "0612345678",
            "LastName": "Dupont",
            "FirstName": "Jacques",
        },
        preset="avocats",
    )
    stats = store.upsert_uncleaned([first, second])
    assert stats["inserted"] == 1
    assert stats["updated"] == 1
    assert len(store.rows) == 1
    row = store.rows["jean@dupont.fr"]
    assert row["email"] == "jean@dupont.fr"
    assert row["category"] == "PLOMBIER"
    assert row["status"] == STATUS_UNCLEANED
    assert row["company"] == "Dupont"
    assert row["website"] == "dupont.fr"
    assert row["first_name"] == "Jean"
    assert row["last_name"] == "Dupont"
    assert row["phone"] == "0612345678"

    row["status"] = STATUS_CLEANED
    third = scraped_row_to_lead(
        {"Email": "JEAN@dupont.fr", "Company": "Overwrite", "Phone": "0699999999"},
        preset="notaires",
    )
    assert store.upsert_uncleaned([third])["skipped"] == 1
    assert row["status"] == STATUS_CLEANED
    assert row["category"] == "PLOMBIER"
    assert row["company"] == "Dupont"
    assert row["phone"] == "0612345678"

    row["category"] = None
    store.upsert_uncleaned([third])
    assert row["category"] == "NOTAIRE"
    assert row["status"] == STATUS_CLEANED


class _Result:
    def __init__(self, data: list) -> None:
        self.data = data


class _Query:
    def __init__(self, client: "_Client", op: str, payload: object = None) -> None:
        self.client = client
        self.op = op
        self.payload = payload
        self._or = ""
        self._eq: dict[str, object] = {}

    def select(self, *_args: object, **_kwargs: object) -> "_Query":
        self.op = "select"
        return self

    def insert(self, rows: list) -> "_Query":
        self.op = "insert"
        self.payload = rows
        return self

    def update(self, patch: dict) -> "_Query":
        self.op = "update"
        self.payload = patch
        return self

    def or_(self, clauses: str) -> "_Query":
        self._or = clauses
        return self

    def eq(self, key: str, value: object) -> "_Query":
        self._eq[key] = value
        return self

    def execute(self) -> _Result:
        if self.op == "select":
            wanted = {
                email.lower()
                for email in re.findall(r'email\.ilike\."((?:[^"]|"")*)"', self._or)
            }
            return _Result(
                [row for row in self.client.rows if str(row["email"]).strip().lower() in wanted]
            )
        if self.op == "insert":
            assert isinstance(self.payload, list)
            for row in self.payload:
                stored = dict(row)
                stored.setdefault("id", f"sb-{len(self.client.rows) + 1}")
                self.client.rows.append(stored)
            return _Result(list(self.payload))
        if self.op == "update":
            assert isinstance(self.payload, dict)
            matched = [
                row for row in self.client.rows if row.get("id") == self._eq.get("id")
            ]
            for row in matched:
                row.update(self.payload)
            return _Result(matched)
        raise AssertionError(self.op)


class _Client:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def table(self, name: str) -> _Query:
        assert name == "leads"
        return _Query(self, "pending")


def test_supabase_upsert_collapses_duplicate_normalized_email() -> None:
    client = _Client()
    client.rows.append(
        {
            "id": "existing",
            "email": "Jean@Dupont.fr",
            "first_name": "",
            "last_name": "Dupont",
            "company": "Dupont",
            "website": "dupont.fr",
            "phone": "",
            "category": "PLOMBIER",
            "status": STATUS_IN_CAMPAIGN,
        }
    )
    store = SupabaseLeadsStore(client, "leads")
    incoming = scraped_row_to_lead(
        {
            "Email": " jean@dupont.fr ",
            "Company": "Other",
            "Website": "other.fr",
            "Phone": "0612345678",
            "FirstName": "Jean",
            "LastName": "Martin",
        },
        preset="avocats",
    )
    same_batch = scraped_row_to_lead(
        {"Email": "JEAN@DUPONT.FR", "Company": "Third", "Phone": "0699999999"},
        preset="notaires",
    )
    stats = store.upsert_uncleaned([incoming, same_batch])
    assert stats == {"inserted": 0, "updated": 1, "skipped": 1}
    assert len(client.rows) == 1
    row = client.rows[0]
    assert row["status"] == STATUS_IN_CAMPAIGN
    assert row["category"] == "PLOMBIER"
    assert row["company"] == "Dupont"
    assert row["website"] == "dupont.fr"
    assert row["last_name"] == "Dupont"
    assert row["first_name"] == "Jean"
    assert row["phone"] == "0612345678"


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
