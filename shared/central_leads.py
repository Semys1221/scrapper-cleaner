"""Write path for the central Supabase ``leads`` table.

The table itself is owned by hercule.dev (Lists tab, lifecycle after ``cleaned``).
This module does not create it. Scraped rows land as ``uncleaned``. The cleaner
moves them to ``cleaned``. Only cleaned leads are pushed to Instantly.

Category values are one ASCII word in capitals (``PLOMBIER``). Identity is the
generated column ``email_normalized`` (``lower(btrim(email))``) from hercule.dev
``db/migrations/026_leads.sql``. This writer stores the normalized email and
does not write ``email_normalized``. A second scrape of the same person does
not create another row, does not downgrade status, and does not replace a
category or payload key that is already set.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol

logger = logging.getLogger(__name__)

LEADS_TABLE = "leads"

# PostgREST on_conflict=email_normalized. The upsert RPC uses
# ON CONFLICT (email_normalized). The column is generated; do not write it.
LEADS_CONFLICT_TARGET = "email_normalized"
LEADS_UPSERT_RPC = "leads_upsert_uncleaned"

# Scraped rows record that this pipeline set the initial status.
# The cleaner sets status_source to manual when it moves a row to cleaned.
STATUS_SOURCE_LIST_PAYLOAD = "list_payload"
STATUS_SOURCE_MANUAL = "manual"
SOURCE_SCRAPE = "scrape"
SOURCE_INSTANTLY_IMPORT = "instantly_import"
SOURCE_NAME_OUTSCRAPER = "outscraper"

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

# Preset id -> one-word category. Names that hercule already uses are taken
# from its niche_mappings. New niches (PLOMBIER, and a few presets with no
# hercule equivalent) stay as their own A-Z word.
# conseillers_gestion_patrimoine is CIF: hercule has no PATRIMOINE category.
# kinesitherapeutes is PARAMEDICAL, the hercule bucket for that profession.
PRESET_CATEGORY: dict[str, str] = {
    "agences_ecommerce": "ECOMMERCE",
    "agences_growth_outbound": "GROWTH",
    "agences_immobilieres": "IMMOBILIER",
    "architectes_dplg": "ARCHITECTURE",
    "auto_ecoles": "AUTOECOLE",
    "avocats": "AVOCAT",
    "boutiques_ecommerce": "ECOMMERCE",
    "btp_pme": "BTP",
    "cabinets_conseil_pme": "CONSEIL",
    "cabinets_conseiller_financier": "CIF",
    "cabinets_expertise_comptable": "COMPTABLE",
    "cabinets_expertise_comptable_fresh_geo": "COMPTABLE",
    "centres_dentaires_independants": "DENTISTE",
    "chirurgiens_dentistes": "DENTISTE",
    "chirurgiens_plasticiens": "CHIRURGIEN",
    "conseillers_gestion_patrimoine": "CIF",
    "courtiers_credit_immobilier": "COURTIER",
    "courtiers_prevoyance_b2b": "COURTIER",
    "daf_partage": "DAF",
    "dentistes_cabinet_groupe": "DENTISTE",
    "hotels_independants": "HOTEL",
    "infogerance_it_pme": "INFOGERANCE",
    "installateurs_pac_rge": "CLIM",
    "jum_advisory": "CONSEIL",
    "kinesitherapeutes": "PARAMEDICAL",
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

# Registry and Google fields that are not columns on public.leads.
_PAYLOAD_FIELDS = (
    ("City", "city"),
    ("Service", "service"),
    ("Niche", "niche"),
    ("Subniche", "subniche"),
    ("Type", "type"),
    ("Category", "google_category"),
    ("Subtypes", "subtypes"),
    ("Siret", "siret"),
    ("Siren", "siren"),
    ("Effectif", "effectif"),
    ("TrancheEffectif", "tranche_effectif"),
    ("Naf", "naf"),
    ("FormeJuridique", "forme_juridique"),
    ("AnneeCreation", "annee_creation"),
    ("ChiffreAffaires", "chiffre_affaires"),
    ("TailleEntreprise", "taille_entreprise"),
    ("LeadScore", "lead_score"),
    ("RegistrySource", "registry_source"),
    ("RegistryFetchedAt", "registry_fetched_at"),
)

# On conflict, only these empty fields are filled. Existing values stay.
_FILL_IF_EMPTY = (
    "first_name",
    "last_name",
    "company",
    "website",
    "phone",
    "job_title",
    "niche_slug",
    "source_name",
    "source_id",
)


class InstantlyUncleanedPushError(RuntimeError):
    """An Instantly upload was attempted for leads that are not cleaned."""


def uncleaned_instantly_push_allowed() -> bool:
    """Uncleaned leads stay in Supabase unless this legacy escape hatch is on."""
    raw = os.getenv("HERCULE_ALLOW_UNCLEANED_INSTANTLY_PUSH", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def refuse_uncleaned_instantly_push(*, cleaned: bool = False) -> None:
    """Every Instantly upload calls this. Cleaned pushes pass; uncleaned ones raise."""
    if cleaned or uncleaned_instantly_push_allowed():
        return
    raise InstantlyUncleanedPushError(
        "Refusing to push uncleaned leads to Instantly. "
        "Clean them first (status=cleaned), or set HERCULE_ALLOW_UNCLEANED_INSTANTLY_PUSH=1."
    )


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
    """``lower(btrim(email))``, stored in ``email`` and generated as ``email_normalized``."""
    return _text(value).lower()


def payload_from_row(row: dict[str, Any]) -> dict[str, str]:
    """Extra scraped attributes for ``leads.payload``. Empty values are omitted."""
    payload: dict[str, str] = {}
    for source_key, dest_key in _PAYLOAD_FIELDS:
        value = _text(row.get(source_key)) or _text(row.get(dest_key))
        if value:
            payload[dest_key] = value
    extra = row.get("payload")
    if isinstance(extra, dict):
        for key, value in extra.items():
            text = _text(value)
            if text and str(key) not in payload:
                payload[str(key)] = text
    return payload


def merge_payload(existing: Any, incoming: Any) -> dict[str, Any]:
    """Fill missing payload keys. A key that already has a value is kept."""
    base = dict(existing) if isinstance(existing, dict) else {}
    extra = incoming if isinstance(incoming, dict) else {}
    for key, value in extra.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        current = base.get(key)
        if current is None or (isinstance(current, str) and not current.strip()):
            base[str(key)] = value
    return base


def _niche_slug(preset: str) -> str:
    slug = (preset or "").strip().lower()
    return slug[:64]


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
        "job_title": _text(row.get("JobTitle") or row.get("job_title")),
        "category": category_for_preset(preset),
        "niche_slug": _niche_slug(preset),
        "source_name": SOURCE_NAME_OUTSCRAPER,
        "source": SOURCE_SCRAPE,
        "source_id": _text(row.get("PlaceId") or row.get("source_id") or row.get("place_id")),
        "status": STATUS_UNCLEANED,
        "status_source": STATUS_SOURCE_LIST_PAYLOAD,
        "instantly_lead_id": None,
        "instantly_list_id": None,
        "list_id": None,
        "payload": payload_from_row(row),
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
    raw_payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    now = utc_now()
    payload = payload_from_row(raw_payload)
    return {
        "email": email,
        "first_name": _text(item.get("first_name")),
        "last_name": _text(item.get("last_name")),
        "company": _text(item.get("company_name") or raw_payload.get("companyName")),
        "website": _text(item.get("website") or raw_payload.get("website")),
        "phone": normalize_phone(item.get("phone") or raw_payload.get("phone")),
        "job_title": _text(item.get("job_title") or raw_payload.get("jobTitle")),
        "category": category,
        "niche_slug": "",
        "source_name": "instantly",
        "source": SOURCE_INSTANTLY_IMPORT,
        "source_id": _text(item.get("id")),
        "status": STATUS_UNCLEANED,
        "status_source": STATUS_SOURCE_LIST_PAYLOAD,
        "instantly_lead_id": _text(item.get("id")) or None,
        "instantly_list_id": None,
        "list_id": None,
        "payload": payload,
        "created_at": now,
        "updated_at": now,
        "cleaned_at": None,
        "phone_enriched_at": None,
        "phone_enrichment_status": None,
    }


def merge_uncleaned(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Patch for a lead that already exists under the same normalized email.

    Status is left untouched here. The SQL upsert uses ``lead_status_rank`` so
    a higher status can replace a lower one and a lower one cannot. Category is
    kept unless it is null or blank. Phone, website, names, company, job title,
    niche, and source name are filled only when the stored value is empty.
    Payload keys already set are kept.
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
    merged = merge_payload(existing.get("payload"), incoming.get("payload"))
    if merged and merged != (existing.get("payload") or {}):
        patch["payload"] = merged
    if patch:
        patch["updated_at"] = utc_now()
    return patch


def _collapse_leads_by_email(
    leads: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """One row per normalized email so ON CONFLICT does not see the same row twice."""
    skipped = 0
    pending: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for lead in leads:
        email = normalize_email(lead.get("email"))
        if "@" not in email:
            skipped += 1
            continue
        stored = {key: value for key, value in lead.items() if key != "id"}
        stored["email"] = email
        current = pending.get(email)
        if current is None:
            pending[email] = stored
            order.append(email)
            continue
        patch = merge_uncleaned(current, stored)
        if patch:
            current.update(patch)
    return [pending[email] for email in order], skipped


def probe_leads_table(store: LeadsStore | None = None) -> None:
    """Fail at startup when Supabase is configured but the leads table is missing.

    Per-row writes still raise on their own. This only runs when credentials exist.
    """
    target = store if store is not None else supabase_store_from_env()
    if not isinstance(target, SupabaseLeadsStore):
        return
    try:
        target.client.table(target.table).select("email").limit(1).execute()
    except Exception as exc:
        logger.error("Central leads table %s is not readable: %s", target.table, exc)
        raise


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
                row["status_source"] = STATUS_SOURCE_MANUAL
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
            new_phone = normalize_phone(lead.get("phone"))
            if lead.get("clear_unverified_phone"):
                existing["phone"] = ""
            elif new_phone:
                existing["phone"] = new_phone
            status = lead.get("phone_enrichment_status")
            if status:
                existing["phone_enrichment_status"] = status
            enriched_at = lead.get("phone_enriched_at")
            if enriched_at:
                existing["phone_enriched_at"] = enriched_at
            if lead.get("updated_at"):
                existing["updated_at"] = lead["updated_at"]
            updated += 1
        return {"updated": updated}


class SupabaseLeadsStore:
    def __init__(self, client: Any, table: str) -> None:
        self.client = client
        self.table = table

    def upsert_uncleaned(self, leads: list[dict[str, Any]]) -> dict[str, int]:
        """One INSERT ... ON CONFLICT via leads_upsert_uncleaned. No read-then-write."""
        collapsed, skipped = _collapse_leads_by_email(leads)
        if not collapsed:
            return {"inserted": 0, "updated": 0, "skipped": skipped}
        response = self.client.rpc(
            LEADS_UPSERT_RPC,
            {
                "p_rows": collapsed,
                "p_conflict_target": LEADS_CONFLICT_TARGET,
                "p_table": self.table,
            },
        ).execute()
        data = response.data
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            raise RuntimeError(f"{LEADS_UPSERT_RPC} returned {data!r}")
        inserted = int(data.get("inserted") or 0)
        updated = int(data.get("updated") or 0)
        skipped += max(len(collapsed) - inserted - updated, 0)
        return {"inserted": inserted, "updated": updated, "skipped": skipped}

    def mark_cleaned(self, emails: Iterable[str]) -> dict[str, int]:
        wanted = sorted(
            {normalize_email(email) for email in emails if "@" in normalize_email(email)}
        )
        if not wanted:
            return {"updated": 0}
        now = utc_now()
        # Exact equality on the generated email_normalized column.
        response = (
            self.client.table(self.table)
            .update(
                {
                    "status": STATUS_CLEANED,
                    "status_source": STATUS_SOURCE_MANUAL,
                    "cleaned_at": now,
                    "updated_at": now,
                }
            )
            .in_("email_normalized", wanted)
            .eq("status", STATUS_UNCLEANED)
            .execute()
        )
        data = response.data or []
        return {"updated": len(data) if isinstance(data, list) else 0}

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
            patch: dict[str, Any] = {
                "updated_at": lead.get("updated_at") or utc_now(),
            }
            new_phone = normalize_phone(lead.get("phone"))
            if lead.get("clear_unverified_phone"):
                patch["phone"] = ""
            elif new_phone:
                patch["phone"] = new_phone
            status = lead.get("phone_enrichment_status")
            if status:
                patch["phone_enrichment_status"] = status
            enriched_at = lead.get("phone_enriched_at")
            if enriched_at:
                patch["phone_enriched_at"] = enriched_at
            self.client.table(self.table).update(patch).eq("id", lead_id).execute()
            updated += 1
        return {"updated": updated}


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
