"""Write path for the central Supabase ``leads`` table.

The table itself is owned by hercule.dev (Lists tab, lifecycle after ``cleaned``).
This module does not create it. Scraped rows land as ``uncleaned``. The cleaner
moves them to ``cleaned``. Only cleaned leads are pushed to Instantly.

Category values are one ASCII word in capitals (``PLOMBIER``).
Identity is the normalized email (``lower(trim(email))``), matching hercule.dev
``db/migrations/026_leads.sql``. A second scrape of the same person does not
create another row and does not change status or a category that is already set.
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol

LEADS_TABLE = "leads"

STATUS_UNCLEANED = "uncleaned"
STATUS_CLEANED = "cleaned"
STATUS_IN_CAMPAIGN = "in_campaign"
STATUS_INSTANTLY_LISTED = "instantly_listed"

LEAD_STATUSES = (
    STATUS_UNCLEANED,
    STATUS_CLEANED,
    STATUS_IN_CAMPAIGN,
    STATUS_INSTANTLY_LISTED,
)

STATUS_RANK = {status: index for index, status in enumerate(LEAD_STATUSES)}

# Instantly custom variables this pipeline is allowed to send.
INSTANTLY_CUSTOM_ALLOWLIST = ("phone", "category", "status", "cleaned")

CATEGORY_RE = re.compile(r"^[A-Z]{2,32}$")

# Preset id -> one-word category. Unknown presets fall back to the last token.
PRESET_CATEGORY: dict[str, str] = {
    "agences_ecommerce": "ECOMMERCE",
    "agences_growth_outbound": "GROWTH",
    "agences_immobilieres": "IMMOBILIER",
    "architectes_dplg": "ARCHITECTE",
    "auto_ecoles": "AUTOECOLE",
    "avocats": "AVOCAT",
    "boutiques_ecommerce": "ECOMMERCE",
    "btp_pme": "BTP",
    "cabinets_conseil_pme": "CONSEIL",
    "cabinets_conseiller_financier": "FINANCE",
    "cabinets_expertise_comptable": "COMPTABLE",
    "cabinets_expertise_comptable_fresh_geo": "COMPTABLE",
    "centres_dentaires_independants": "DENTISTE",
    "chirurgiens_dentistes": "DENTISTE",
    "chirurgiens_plasticiens": "CHIRURGIEN",
    "conseillers_gestion_patrimoine": "PATRIMOINE",
    "courtiers_credit_immobilier": "COURTIER",
    "courtiers_prevoyance_b2b": "COURTIER",
    "daf_partage": "DAF",
    "dentistes_cabinet_groupe": "DENTISTE",
    "hotels_independants": "HOTEL",
    "infogerance_it_pme": "INFOGERANCE",
    "installateurs_pac_rge": "PAC",
    "jum_advisory": "CONSEIL",
    "kinesitherapeutes": "KINE",
    "maintenance_securite_incendie": "SECURITE",
    "medecine_esthetique": "ESTHETIQUE",
    "medecins_generalistes": "MEDECIN",
    "notaires": "NOTAIRE",
    "organismes_formation_qualiopi": "FORMATION",
    "paysagistes": "PAYSAGISTE",
    "plombier": "PLOMBIER",
    "plombiers": "PLOMBIER",
    "restaurants_independants": "RESTAURANT",
    "runbook_test": "COMPTABLE",
    "terrassement_vrd": "TERRASSEMENT",
    "veterinaires": "VETERINAIRE",
    "_adhoc": "ADHOC",
}

# On conflict, only these empty fields are filled. Existing values stay.
_FILL_IF_EMPTY = ("first_name", "last_name", "company", "website", "phone")


def uncleaned_instantly_push_allowed() -> bool:
    """Uncleaned leads stay in Supabase unless this legacy escape hatch is on."""
    raw = os.getenv("HERCULE_ALLOW_UNCLEANED_INSTANTLY_PUSH", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def leads_table_name() -> str:
    return os.getenv("HERCULE_LEADS_TABLE", LEADS_TABLE).strip() or LEADS_TABLE


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def category_for_preset(preset: str) -> str:
    key = (preset or "").strip().lower()
    if key in PRESET_CATEGORY:
        value = PRESET_CATEGORY[key]
    else:
        token = key.split("_")[-1] if key else ""
        ascii_token = unicodedata.normalize("NFKD", token).encode("ascii", "ignore").decode("ascii")
        value = "".join(ch for ch in ascii_token if ch.isalpha()).upper()
    if not CATEGORY_RE.fullmatch(value):
        raise ValueError(
            f"category for preset {preset!r} must be one A-Z word, got {value!r}"
        )
    return value


def normalize_phone(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    digits_only = re.sub(r"\D", "", text)
    if len(digits_only) < 8:
        return ""
    if text.startswith("+") or text.startswith("00"):
        if text.startswith("00"):
            return "+" + digits_only[2:]
        return "+" + digits_only
    return digits_only


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_email(value: Any) -> str:
    """``lower(trim(email))``, the unique key on ``public.leads``."""
    return _text(value).lower()


def scraped_row_to_lead(row: dict[str, Any], *, preset: str) -> dict[str, Any]:
    """Map a scraper CSV row onto the central leads contract."""
    email = normalize_email(row.get("Email") or row.get("email"))
    if "@" not in email:
        raise ValueError("scraped lead is missing an email")
    now = utc_now()
    return {
        "email": email,
        "first_name": _text(row.get("FirstName") or row.get("first_name")),
        "last_name": _text(row.get("LastName") or row.get("last_name")),
        "company": _text(row.get("Company") or row.get("company") or row.get("company_name")),
        "website": _text(row.get("Website") or row.get("website")),
        "phone": normalize_phone(row.get("Phone") or row.get("phone")),
        "category": category_for_preset(preset),
        "status": STATUS_UNCLEANED,
        "source": "outscraper",
        "source_id": _text(row.get("PlaceId") or row.get("source_id") or row.get("place_id")),
        "instantly_lead_id": None,
        "instantly_list_id": None,
        "list_id": None,
        "created_at": now,
        "updated_at": now,
        "cleaned_at": None,
        "phone_enriched_at": None,
        "phone_enrichment_status": None,
    }


def instantly_item_to_lead(item: dict[str, Any], *, category: str) -> dict[str, Any] | None:
    """Map an Instantly lead payload onto an uncleaned central row."""
    if not CATEGORY_RE.fullmatch(category):
        raise ValueError(f"category must be one A-Z word, got {category!r}")
    email = normalize_email(item.get("email"))
    if "@" not in email:
        return None
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    now = utc_now()
    return {
        "email": email,
        "first_name": _text(item.get("first_name")),
        "last_name": _text(item.get("last_name")),
        "company": _text(item.get("company_name") or payload.get("companyName")),
        "website": _text(item.get("website") or payload.get("website")),
        "phone": normalize_phone(item.get("phone") or payload.get("phone")),
        "category": category,
        "status": STATUS_UNCLEANED,
        "source": "instantly",
        "source_id": _text(item.get("id")),
        "instantly_lead_id": _text(item.get("id")) or None,
        "instantly_list_id": None,
        "list_id": None,
        "created_at": now,
        "updated_at": now,
        "cleaned_at": None,
        "phone_enriched_at": None,
        "phone_enrichment_status": None,
    }


def merge_uncleaned(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Patch for a lead that already exists under the same normalized email.

    Status is left untouched (never downgraded). Category is kept unless it is
    null or blank. Phone, website, names, and company are filled only when the
    stored value is empty.
    """
    patch: dict[str, Any] = {}
    if not _text(existing.get("category")) and _text(incoming.get("category")):
        patch["category"] = incoming["category"]
    for key in _FILL_IF_EMPTY:
        if _text(existing.get(key)):
            continue
        incoming_value = incoming.get(key)
        if not _text(incoming_value):
            continue
        patch[key] = incoming_value
    if patch:
        patch["updated_at"] = utc_now()
    return patch


def core_instantly_custom_variables(
    existing: dict[str, Any] | None = None,
    *,
    phone: str = "",
    category: str = "",
    status: str = "",
    cleaned: str = "",
) -> dict[str, str]:
    """Keep only core Instantly custom variables."""
    source: dict[str, Any] = dict(existing or {})
    if phone:
        source["phone"] = phone
    if category:
        source["category"] = category
    if status:
        source["status"] = status
    if cleaned:
        source["cleaned"] = cleaned
    out: dict[str, str] = {}
    for key in INSTANTLY_CUSTOM_ALLOWLIST:
        value = source.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if key == "category" and not CATEGORY_RE.fullmatch(text):
            continue
        out[key] = text
    return out


class LeadsStore(Protocol):
    def upsert_uncleaned(self, leads: list[dict[str, Any]]) -> dict[str, int]: ...

    def mark_cleaned(self, emails: Iterable[str]) -> dict[str, int]: ...

    def list_phone_candidates(
        self, *, limit: int, category: str | None = None
    ) -> list[dict[str, Any]]: ...

    def save_phone_enrichment(self, leads: list[dict[str, Any]]) -> dict[str, int]: ...


class InMemoryLeadsStore:
    """Fixture store keyed by normalized email."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def upsert_uncleaned(self, leads: list[dict[str, Any]]) -> dict[str, int]:
        inserted = 0
        updated = 0
        skipped = 0
        for lead in leads:
            email = normalize_email(lead.get("email"))
            if "@" not in email:
                skipped += 1
                continue
            stored = {**lead, "email": email}
            existing = self.rows.get(email)
            if existing is None:
                self._seq += 1
                self.rows[email] = {**stored, "id": f"mem-{self._seq}"}
                inserted += 1
                continue
            patch = merge_uncleaned(existing, stored)
            if not patch:
                skipped += 1
                continue
            existing.update(patch)
            updated += 1
        return {"inserted": inserted, "updated": updated, "skipped": skipped}

    def mark_cleaned(self, emails: Iterable[str]) -> dict[str, int]:
        wanted = {normalize_email(email) for email in emails if "@" in normalize_email(email)}
        updated = 0
        now = utc_now()
        for row in self.rows.values():
            if row["email"] in wanted and row.get("status") == STATUS_UNCLEANED:
                row["status"] = STATUS_CLEANED
                row["cleaned_at"] = now
                row["updated_at"] = now
                updated += 1
        return {"updated": updated}

    def list_phone_candidates(
        self, *, limit: int, category: str | None = None
    ) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for row in self.rows.values():
            if row.get("status") != STATUS_CLEANED:
                continue
            if row.get("phone_enriched_at"):
                continue
            if category and row.get("category") != category:
                continue
            found.append(dict(row))
            if len(found) >= limit:
                break
        return found

    def save_phone_enrichment(self, leads: list[dict[str, Any]]) -> dict[str, int]:
        updated = 0
        for lead in leads:
            email = normalize_email(lead.get("email"))
            existing = self.rows.get(email)
            if existing is None:
                continue
            for field in (
                "phone",
                "phone_enriched_at",
                "phone_enrichment_status",
                "updated_at",
            ):
                if field in lead:
                    existing[field] = lead[field]
            updated += 1
        return {"updated": updated}


class SupabaseLeadsStore:
    def __init__(self, client: Any, table: str) -> None:
        self.client = client
        self.table = table

    def upsert_uncleaned(self, leads: list[dict[str, Any]]) -> dict[str, int]:
        inserted = 0
        updated = 0
        skipped = 0
        prepared: list[dict[str, Any]] = []
        for lead in leads:
            email = normalize_email(lead.get("email"))
            if "@" not in email:
                skipped += 1
                continue
            prepared.append({**lead, "email": email})
        emails = sorted({lead["email"] for lead in prepared})
        existing_rows = self._select_emails(emails)
        by_email = {normalize_email(row.get("email")): row for row in existing_rows}
        pending_insert: dict[str, dict[str, Any]] = {}
        for lead in prepared:
            email = lead["email"]
            existing = by_email.get(email)
            if existing is None and email in pending_insert:
                patch = merge_uncleaned(pending_insert[email], lead)
                if patch:
                    pending_insert[email].update(patch)
                continue
            if existing is None:
                pending_insert[email] = {k: v for k, v in lead.items() if k != "id"}
                continue
            patch = merge_uncleaned(existing, lead)
            if not patch:
                skipped += 1
                continue
            (
                self.client.table(self.table)
                .update(patch)
                .eq("id", existing["id"])
                .execute()
            )
            existing.update(patch)
            updated += 1
        if pending_insert:
            self.client.table(self.table).insert(list(pending_insert.values())).execute()
            inserted += len(pending_insert)
        return {"inserted": inserted, "updated": updated, "skipped": skipped}

    def mark_cleaned(self, emails: Iterable[str]) -> dict[str, int]:
        wanted = {normalize_email(email) for email in emails if "@" in normalize_email(email)}
        if not wanted:
            return {"updated": 0}
        now = utc_now()
        patch = {
            "status": STATUS_CLEANED,
            "cleaned_at": now,
            "updated_at": now,
        }
        updated = 0
        for row in self._select_emails(sorted(wanted)):
            if normalize_email(row.get("email")) not in wanted:
                continue
            if row.get("status") != STATUS_UNCLEANED or not row.get("id"):
                continue
            self.client.table(self.table).update(patch).eq("id", row["id"]).execute()
            updated += 1
        return {"updated": updated}

    def list_phone_candidates(
        self, *, limit: int, category: str | None = None
    ) -> list[dict[str, Any]]:
        query = (
            self.client.table(self.table)
            .select("*")
            .eq("status", STATUS_CLEANED)
            .is_("phone_enriched_at", "null")
            .limit(max(int(limit), 0))
        )
        if category:
            query = query.eq("category", category)
        response = query.execute()
        data = response.data or []
        return [row for row in data if isinstance(row, dict)]

    def save_phone_enrichment(self, leads: list[dict[str, Any]]) -> dict[str, int]:
        updated = 0
        for lead in leads:
            lead_id = lead.get("id")
            if not lead_id:
                continue
            patch = {
                "phone": lead.get("phone") or "",
                "phone_enriched_at": lead.get("phone_enriched_at"),
                "phone_enrichment_status": lead.get("phone_enrichment_status"),
                "updated_at": lead.get("updated_at") or utc_now(),
            }
            self.client.table(self.table).update(patch).eq("id", lead_id).execute()
            updated += 1
        return {"updated": updated}

    def _select_emails(self, emails: list[str]) -> list[dict[str, Any]]:
        if not emails:
            return []
        # Case-insensitive match so a row stored as Jean@x.fr collides with jean@x.fr.
        # The table unique key is lower(trim(email)) (hercule.dev 026_leads.sql).
        clauses = ",".join(
            'email.ilike."' + email.replace('"', '""') + '"' for email in emails
        )
        response = self.client.table(self.table).select("*").or_(clauses).execute()
        data = response.data or []
        return [row for row in data if isinstance(row, dict)]


def supabase_store_from_env() -> SupabaseLeadsStore | None:
    url = os.getenv("SUPABASE_URL", "").strip() or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        return None
    from supabase import create_client

    return SupabaseLeadsStore(create_client(url, key), leads_table_name())


def persist_scraped_lead(
    row: dict[str, Any],
    *,
    preset: str,
    store: LeadsStore | None = None,
) -> dict[str, int]:
    """Upsert one scraped lead as uncleaned. No-op when Supabase is not configured."""
    lead = scraped_row_to_lead(row, preset=preset)
    target = store if store is not None else supabase_store_from_env()
    if target is None:
        return {"inserted": 0, "updated": 0, "skipped": 0}
    return target.upsert_uncleaned([lead])


def mark_emails_cleaned(
    emails: Iterable[str],
    *,
    store: LeadsStore | None = None,
) -> dict[str, int]:
    target = store if store is not None else supabase_store_from_env()
    if target is None:
        return {"updated": 0}
    return target.mark_cleaned(emails)
