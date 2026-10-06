"""Central leads contract: category, status, and idempotent upsert."""

from __future__ import annotations

from pathlib import Path

from shared.central_leads import (
    LEADS_CONFLICT_TARGET,
    LEADS_UPSERT_RPC,
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


def test_category_for_preset_matches_hercule_names() -> None:
    assert category_for_preset("plombier") == "PLOMBIER"
    assert category_for_preset("avocats") == "AVOCAT"
    assert category_for_preset("cabinets_expertise_comptable") == "COMPTABLE"
    assert category_for_preset("installateurs_pac_rge") == "CLIM"
    assert category_for_preset("cabinets_conseiller_financier") == "CIF"
    assert category_for_preset("architectes_dplg") == "ARCHITECTURE"
    assert category_for_preset("conseillers_gestion_patrimoine") == "CIF"
    assert category_for_preset("kinesitherapeutes") == "PARAMEDICAL"


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
            "City": "Lyon",
            "Siret": "12345678901234",
            "Naf": "43.22A",
        },
        preset="plombier",
    )
    assert lead["email"] == "jean@dupont.fr"
    assert "email_normalized" not in lead
    assert lead["category"] == "PLOMBIER"
    assert lead["niche_slug"] == "plombier"
    assert lead["status"] == STATUS_UNCLEANED
    assert lead["status_source"] == "list_payload"
    assert lead["phone"] == "+33184801234"
    assert lead["source"] == "scrape"
    assert lead["source_name"] == "outscraper"
    assert lead["source_id"] == "place-1"
    assert lead["list_id"] is None
    assert lead["payload"] == {
        "city": "Lyon",
        "siret": "12345678901234",
        "naf": "43.22A",
    }


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


class _RpcResult:
    def __init__(self, data: dict) -> None:
        self.data = data


class _RpcClient:
    def __init__(self, data: dict | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._data = data or {"inserted": 0, "updated": 2}

    def rpc(self, name: str, params: dict) -> "_RpcClient":
        self.calls.append((name, params))
        return self

    def execute(self) -> _RpcResult:
        return _RpcResult(self._data)


def test_payload_merge_keeps_existing_keys() -> None:
    patch = merge_uncleaned(
        {
            "status": STATUS_CLEANED,
            "category": "PLOMBIER",
            "company": "Dupont",
            "payload": {"city": "Lyon", "siret": "111"},
        },
        {
            "category": "AVOCAT",
            "company": "Other",
            "payload": {"city": "Paris", "naf": "43.22A", "siret": ""},
        },
    )
    assert "category" not in patch
    assert "company" not in patch
    assert "status" not in patch
    assert patch["payload"]["city"] == "Lyon"
    assert patch["payload"]["siret"] == "111"
    assert patch["payload"]["naf"] == "43.22A"


def test_upsert_sql_matches_email_normalized_contract() -> None:
    sql_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "proposed"
        / "027b_leads_upsert_uncleaned.sql"
    )
    sql = sql_path.read_text(encoding="utf-8")
    assert "DO NOT APPLY" in sql
    assert "ON CONFLICT (email_normalized)" in sql
    assert "lead_status_rank(EXCLUDED.status)" in sql
    assert "jsonb_object_agg" in sql
    insert_list = sql.split("INSERT INTO", 1)[1].split("SELECT", 1)[0]
    assert "email_normalized" not in insert_list
    for column in ("first_name", "last_name", "company", "website", "phone"):
        assert f"NULLIF(btrim(%1$I.{column}), '')" in sql
    assert LEADS_CONFLICT_TARGET == "email_normalized"


def test_supabase_upsert_is_one_conflict_call() -> None:
    client = _RpcClient()
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
    wildcard = scraped_row_to_lead(
        {"Email": " A_B%@ex.fr ", "Company": "Wild"},
        preset="plombier",
    )
    stats = store.upsert_uncleaned([incoming, same_batch, wildcard, {"email": "not-an-email"}])
    assert stats["skipped"] == 1
    assert len(client.calls) == 1
    name, params = client.calls[0]
    assert name == LEADS_UPSERT_RPC
    assert params["p_conflict_target"] == LEADS_CONFLICT_TARGET
    assert params["p_table"] == "leads"
    emails = [row["email"] for row in params["p_rows"]]
    assert emails == ["jean@dupont.fr", "a_b%@ex.fr"]
    first = params["p_rows"][0]
    assert first["category"] == "AVOCAT"
    assert first["company"] == "Other"
    assert first["phone"] == "0612345678"
    assert first["last_name"] == "Martin"
    assert first["source"] == "scrape"
    assert "email_normalized" not in first
    assert "ilike" not in str(params)


class _ExactQuery:
    def __init__(self) -> None:
        self.filters: list[tuple[str, object]] = []

    def update(self, patch: dict) -> "_ExactQuery":
        self.patch = patch
        return self

    def in_(self, key: str, values: list) -> "_ExactQuery":
        self.filters.append((key, list(values)))
        return self

    def eq(self, key: str, value: object) -> "_ExactQuery":
        self.filters.append((key, value))
        return self

    def execute(self) -> _RpcResult:
        return _RpcResult({"unused": True})

    def __getattr__(self, name: str):
        raise AssertionError(f"unexpected query method {name}")


class _ExactClient:
    def __init__(self) -> None:
        self.query = _ExactQuery()

    def table(self, name: str) -> _ExactQuery:
        assert name == "leads"
        return self.query


def test_mark_cleaned_uses_exact_normalized_email() -> None:
    client = _ExactClient()
    store = SupabaseLeadsStore(client, "leads")

    def execute() -> object:
        return type("R", (), {"data": [{"id": "1"}, {"id": "2"}]})()

    client.query.execute = execute  # type: ignore[method-assign]
    stats = store.mark_cleaned([" Jean@Dupont.fr ", "not-an-email", "a_b%@ex.fr"])
    assert stats == {"updated": 2}
    assert client.query.filters[0] == ("email_normalized", ["a_b%@ex.fr", "jean@dupont.fr"])
    assert ("status", STATUS_UNCLEANED) in client.query.filters
    assert client.query.patch["status_source"] == "manual"
    assert client.query.patch["status"] == STATUS_CLEANED


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
