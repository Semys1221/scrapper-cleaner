"""Cabinets expertise comptable (France) — sole VPS scraper: postal + INSEE communes, taxonomy gate."""

from french_insee_communes import FRENCH_INSEE_COMMUNES
from french_postal_locations import FRENCH_POSTAL_LOCATIONS

PRESET_ID = "cabinets_expertise_comptable_fresh_geo"
PRESET_LABEL = "Cabinets expertise comptable (France)"

INSTANTLY_NAME = "Expert-comptable"
SCRAPE_QUEUE_RANK = 6

_LIST_ID = "bfb0fc90-ec59-4d49-b266-3891f59d3ea8"
_LEGACY_LIST_ID = "edfd3090-6306-4f71-bd83-01192b06666c"
_TEMP_LIST_ID = "ca3e72d4-5a43-4399-a89b-566095e69c25"
_CAMPAIGN_ID = "5591a068-75f9-4826-8564-4dc2acc74bd4"
# Hercule bypass (instantly_bypass_templates) is the sole Interested E1–E3 path; no Instantly native subsequence.
_SUBSEQUENCE_ID = ""

CABINETS_EXPERTISE_COMPTABLE_FRESH_GEO_CONFIG = {
    "OUTSCRAPER_API_KEY": "",
    "INSTANTLY_API_KEY": "",
    "INSTANTLY_NAME": INSTANTLY_NAME,
    "SCRAPE_QUEUE_RANK": SCRAPE_QUEUE_RANK,
    "INSTANTLY_LIST_ID": _LIST_ID,
    "INSTANTLY_CAMPAIGN_ID": _CAMPAIGN_ID,
    "INSTANTLY_SUBSEQUENCE_ID": _SUBSEQUENCE_ID,
    "INSTANTLY_DEDUP_LIST_IDS": [_LIST_ID, _LEGACY_LIST_ID, _TEMP_LIST_ID],
    "INSTANTLY_DEDUP_CAMPAIGN_IDS": [_CAMPAIGN_ID],
    "INSTANTLY_SKIP_IF_IN_CAMPAIGN": False,
    "INSTANTLY_SKIP_IF_IN_LIST": True,
    "INSTANTLY_PUSH_EVERY": 50,
    "INSTANTLY_PROVISION_LINKS": True,
    # provision-leads moves provisioned list leads into the campaign
    "INSTANTLY_ATTACH_TO_CAMPAIGN": True,
    "LINK_PROVISION_CATEGORY": "comptable",
    "LINK_PROVISION_RESERVATION_PAGE": "dec",
    "ENRICH_ENABLED": False,
    "OUTSCRAPER_FILTERS": ["only_with_website", "operational_only"],
    "ENRICH_INCLUDED_KEYWORDS": [],
    "ENRICH_HARD_EXCLUDED_KEYWORDS": [],
    "ENRICH_SOFT_EXCLUDED_KEYWORDS": [],
    "TAXONOMY_GATE_ENABLED": True,
    "TAXONOMY_INCLUDED_KEYWORDS": [
        "expert-comptable",
        "expert comptable",
        "expertise comptable",
        "cabinet d'expertise comptable",
        "cabinet comptable",
        "accounting firm",
        "chartered accountant",
        "comptable",
        "tax advisor",
        "tax preparation service",
        "financial auditor",
        "payroll service",
        "auditor",
    ],
    "OUTSCRAPER_BATCH_SIZE": 200,
    "OUTSCRAPER_CONCURRENCY": 16,
    "OUTSCRAPER_LIMIT_PER_QUERY": 50,
    "OUTSCRAPER_POLL_INITIAL_S": 10,
    "OUTSCRAPER_POLL_INTERVAL_S": 5,
    "OUTSCRAPER_POLL_SLOW_S": 10,
    "OUTSCRAPER_POLL_TIMEOUT_S": 300,
    "OUTSCRAPER_TOTAL_LIMIT_BUFFER": 8,
    "OUTSCRAPER_ENRICHMENT": ["leads_n_contacts"],
    "OUTSCRAPER_EMAIL_RECOVERY_ENABLED": True,
    "TARGET_LEADS": 3000,
    "TARGET_MODE": "instantly_pushed_run",
    "SCRAPE_START_QUERY_PASS": 0,
    "DUPLICATE_GEO_ADVANCE_RATE": 0.30,
    "SCRAPE_SKIP_PHASE_ENABLED": False,
    "SCRAPE_DEPARTMENT_PHASE_ENABLED": False,
    "SCRAPE_RELOAD_ENABLED": True,
    "SCRAPE_RELOAD_MAX_ROUNDS": 4,
    "SCRAPE_RELOAD_START_GEO_PHASE": "pass",
    "SCRAPE_RELOAD_START_QUERY_PASS": 0,
    "SERVICE_DEFAULT": "Expertise comptable",
    "SERVICE_RULES": [],
    "KEYWORDS": [
        "expert comptable",
        "cabinet expertise comptable",
        "cabinet d'expertise comptable",
    ],
    "EXPANSION_KEYWORDS": [
        "expert-comptable",
        "commissaire aux comptes",
    ],
    "LOCATIONS": FRENCH_POSTAL_LOCATIONS,
    "EXPANSION_LOCATIONS": [],
    "COMMUNE_POOL": FRENCH_INSEE_COMMUNES,
    "EXCLUDE_DOMAINS": [
        "duckduckgo.com",
        "google.com",
        "google.fr",
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "youtube.com",
        "pinterest.com",
        "tiktok.com",
        "societe.com",
        "pagesjaunes.fr",
    ],
    "PAPPERS_ENABLED": False,
    "NICHE_METADATA": {
        "angle": "Réforme facture électronique ; meilleure cible long terme (prudents, comparent)",
        "valeur_client": "Prise de RDV cabinets EC — éviter pic charge jan–mai pour relances",
        "effectif_cible": "3+ salariés (qualif à la réponse)",
        "priorite": 6,
    },
}

CONFIG = CABINETS_EXPERTISE_COMPTABLE_FRESH_GEO_CONFIG
