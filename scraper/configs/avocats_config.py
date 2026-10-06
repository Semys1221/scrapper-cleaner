"""Avocats (France) — Outscraper taxonomy gate, page réservation avocats-affaires."""

from french_cities import FRENCH_EXPANSION_LOCATIONS, FRENCH_LOCATIONS

PRESET_ID = "avocats"
PRESET_LABEL = "Avocats (France)"

INSTANTLY_NAME = "Avocat d'affaires"
SCRAPE_QUEUE_RANK = 8

_LIST_ID = "0010fd68-8e7a-4624-bb65-6216b260bf2c"
_CAMPAIGN_ID = "8c3aee0c-5eeb-4c5c-9a6a-a9c79b4b936c"
_SUBSEQUENCE_ID = ""

# Existing JUM lists for cross-dedup
_RESTAURANT_LIST_ID = "8ad641e7-3456-42df-9281-2c11f97df1c5"
_BTP_LIST_ID = "d4bc89f7-b271-4ed7-9539-4ac968bfb7c9"
_DENTISTE_LIST_ID = "c4eb10d7-2285-4fc3-aa06-3230d2498d8e"
_MEDECIN_LIST_ID = "7e3b619f-9823-4d64-bc50-31f01bb08e6d"
_KINE_LIST_ID = "2a45b863-c705-4116-acec-31f49857bbbb"
_AVOCAT_LIST_ID = "0010fd68-8e7a-4624-bb65-6216b260bf2c"
_ARCHITECTE_LIST_ID = "44b49536-aa48-4acd-9d3b-117e331d41f3"
_VETERINAIRE_LIST_ID = "29a1ca36-9964-4ee8-bc20-7a8c840af21d"

AVOCATS_CONFIG = {
    "OUTSCRAPER_API_KEY": "",
    "INSTANTLY_API_KEY": "",
    "INSTANTLY_NAME": INSTANTLY_NAME,
    "SCRAPE_QUEUE_RANK": SCRAPE_QUEUE_RANK,
    "INSTANTLY_LIST_ID": _LIST_ID,
    "INSTANTLY_CAMPAIGN_ID": _CAMPAIGN_ID,
    "INSTANTLY_SUBSEQUENCE_ID": _SUBSEQUENCE_ID,
    "INSTANTLY_DEDUP_LIST_IDS": [
        _LIST_ID,
        _RESTAURANT_LIST_ID,
        _BTP_LIST_ID,
        _DENTISTE_LIST_ID,
        _MEDECIN_LIST_ID,
        _KINE_LIST_ID,
        _AVOCAT_LIST_ID,
        _ARCHITECTE_LIST_ID,
        _VETERINAIRE_LIST_ID,
    ],
    "INSTANTLY_DEDUP_CAMPAIGN_IDS": [_CAMPAIGN_ID],
    "INSTANTLY_SKIP_IF_IN_CAMPAIGN": True,
    "INSTANTLY_SKIP_IF_IN_LIST": True,
    "INSTANTLY_PUSH_EVERY": 25,
    "INSTANTLY_BACKLOG_PUSH_MIN": 25,
    "INSTANTLY_PROVISION_LINKS": True,
    # provision-leads moves provisioned list leads into the campaign
    "INSTANTLY_ATTACH_TO_CAMPAIGN": True,
    "LINK_PROVISION_CATEGORY": "jum",
    "LINK_PROVISION_SEGMENT": "avocat",
    "LINK_PROVISION_RESERVATION_PAGE": "avocats-affaires",
    "ENRICH_ENABLED": False,
    "WEBSITE_REQUIRED": False,
    "OUTSCRAPER_FILTERS": ["operational_only"],
    "TAXONOMY_GATE_ENABLED": True,
    "TAXONOMY_MATCH_MODE": "taxonomy_only",
    "TAXONOMY_INCLUDED_KEYWORDS": [
        "avocat",
        "avocate",
        "cabinet d'avocats",
        "cabinet d avocats",
        "cabinet avocat",
        "lawyer",
        "attorney",
        "law firm",
        "barreau",
    ],
    "TAXONOMY_EXCLUDED_KEYWORDS": [
        "huissier",
        "notaire",
        "greffe",
        "tribunal",
        "cour d'appel",
        "recrutement",
        "assurance",
        "mutuelle",
        "logiciel juridique",
        "école",
        "ecole",
        "université",
        "universite",
    ],
    "ENRICH_INCLUDED_KEYWORDS": [],
    "ENRICH_HARD_EXCLUDED_KEYWORDS": [],
    "ENRICH_SOFT_EXCLUDED_KEYWORDS": [],
    "OUTSCRAPER_BATCH_SIZE": 40,
    "OUTSCRAPER_CONCURRENCY": 16,
    "OUTSCRAPER_LIMIT_PER_QUERY": 200,
    "OUTSCRAPER_POLL_INITIAL_S": 10,
    "OUTSCRAPER_POLL_INTERVAL_S": 5,
    "OUTSCRAPER_POLL_SLOW_S": 10,
    "OUTSCRAPER_POLL_TIMEOUT_S": 600,
    "OUTSCRAPER_TOTAL_LIMIT_BUFFER": 12,
    "OUTSCRAPER_ENRICHMENT": ["leads_n_contacts"],
    "OUTSCRAPER_EMAIL_RECOVERY_ENABLED": True,
    "TARGET_LEADS": 3000,
    "TARGET_MODE": "instantly_pushed",
    "SCRAPE_START_QUERY_PASS": 0,
    "SCRAPE_SKIP_PHASE_ENABLED": False,
    "SCRAPE_SKIP_SATURATION_TO_DEPARTMENT": True,
    "DUPLICATE_GEO_ADVANCE_RATE": 0.50,
    "SCRAPE_RELOAD_ENABLED": True,
    "SCRAPE_RELOAD_MAX_ROUNDS": 8,
    "SCRAPE_RELOAD_START_GEO_PHASE": "pass",
    "SCRAPE_RELOAD_START_QUERY_PASS": 0,
    "SCRAPE_CONTINUOUS_MODE": True,
    "SCRAPE_CONTINUOUS_MAX_ZERO_CYCLES": 3,
    "CONTINUOUS_KEYWORD_ROTATIONS": [
        [
            "avocat",
            "cabinet d'avocats",
            "avocate",
            "cabinet avocat",
        ],
        [
            "lawyer",
            "attorney",
            "law firm",
            "avocat barreau",
        ],
        [
            "avocat libéral",
            "cabinet avocats",
            "avocat indépendant",
            "étude d'avocat",
        ],
        [
            "avocat droit",
            "cabinet juridique",
            "avocat conseil",
            "avocate barreau",
        ],
    ],
    "SERVICE_DEFAULT": "Avocat",
    "SERVICE_RULES": [],
    "KEYWORDS": [
        "avocat",
        "avocat d'affaires",
        "cabinet d'avocats",
        "avocate",
        "cabinet avocat",
    ],
    "EXPANSION_KEYWORDS": [
        "lawyer",
        "attorney",
        "law firm",
        "avocat barreau",
        "cabinet avocats",
    ],
    "LOCATIONS": FRENCH_LOCATIONS,
    "EXPANSION_LOCATIONS": FRENCH_EXPANSION_LOCATIONS,
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
        "angle": "Cabinet structuré — associés décident ensemble, cycle de vente long",
        "valeur_client": "Prise de RDV étude fiscale DGFiP / AMF — cotisations, taxe 30–41 %",
        "effectif_cible": "cabinets d'avocats structurés",
        "priorite": 8,
    },
}

CONFIG = AVOCATS_CONFIG
