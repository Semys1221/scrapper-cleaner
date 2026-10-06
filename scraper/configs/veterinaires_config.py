"""Vétérinaires (France) — Outscraper taxonomy gate, JUM link provision."""

from french_cities import FRENCH_EXPANSION_LOCATIONS, FRENCH_LOCATIONS

PRESET_ID = "veterinaires"
PRESET_LABEL = "Vétérinaires (France)"

_LIST_ID = "29a1ca36-9964-4ee8-bc20-7a8c840af21d"
_CAMPAIGN_ID = "7300a1ce-9e55-4bfa-92fd-d25361a22a59"
_SUBSEQUENCE_ID = ""

# Existing JUM lists for cross-dedup
_RESTAURANT_LIST_ID = "8ad641e7-3456-42df-9281-2c11f97df1c5"
_BTP_LIST_ID = "d4bc89f7-b271-4ed7-9539-4ac968bfb7c9"
_DENTISTE_LIST_ID = "c4eb10d7-2285-4fc3-aa06-3230d2498d8e"
_MEDECIN_LIST_ID = "7e3b619f-9823-4d64-bc50-31f01bb08e6d"
_KINE_LIST_ID = "2a45b863-c705-4116-acec-31f49857bbbb"
_AVOCAT_LIST_ID = "d4993823-d593-4839-8d67-48aa32782998"
_ARCHITECTE_LIST_ID = "44b49536-aa48-4acd-9d3b-117e331d41f3"
_VETERINAIRE_LIST_ID = "29a1ca36-9964-4ee8-bc20-7a8c840af21d"

VETERINAIRES_CONFIG = {
    "OUTSCRAPER_API_KEY": "",
    "INSTANTLY_API_KEY": "",
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
    "INSTANTLY_DEDUP_CAMPAIGN_IDS": [],
    "INSTANTLY_SKIP_IF_IN_CAMPAIGN": True,
    "INSTANTLY_SKIP_IF_IN_LIST": True,
    "INSTANTLY_PUSH_EVERY": 25,
    "INSTANTLY_BACKLOG_PUSH_MIN": 25,
    "INSTANTLY_PROVISION_LINKS": True,
    "LINK_PROVISION_CATEGORY": "jum",
    "ENRICH_ENABLED": False,
    "WEBSITE_REQUIRED": False,
    "OUTSCRAPER_FILTERS": ["operational_only"],
    "TAXONOMY_GATE_ENABLED": True,
    "TAXONOMY_MATCH_MODE": "taxonomy_only",
    "TAXONOMY_INCLUDED_KEYWORDS": [
        "vétérinaire",
        "veterinaire",
        "clinique vétérinaire",
        "clinique veterinaire",
        "cabinet vétérinaire",
        "cabinet veterinaire",
        "veterinary clinic",
        "veterinarian",
        "vet clinic",
    ],
    "TAXONOMY_EXCLUDED_KEYWORDS": [
        "animalerie",
        "toilettage",
        "toiletteur",
        "laboratoire",
        "élevage",
        "elevage",
        "chenil",
        "pension animale",
        "mutuelle",
        "assurance",
        "recrutement",
        "logiciel",
        "école",
        "ecole",
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
            "vétérinaire",
            "clinique vétérinaire",
            "cabinet vétérinaire",
            "veterinaire",
        ],
        [
            "veterinary clinic",
            "veterinarian",
            "vet clinic",
            "clinique veterinaire",
        ],
        [
            "vétérinaire libéral",
            "cabinet veterinaire",
            "vétérinaire animaux",
            "docteur vétérinaire",
        ],
        [
            "clinique vétérinaire indépendante",
            "vétérinaire de campagne",
            "vétérinaire rural",
            "cabinet vétérinaire indépendant",
        ],
    ],
    "SERVICE_DEFAULT": "Médecine vétérinaire",
    "SERVICE_RULES": [],
    "KEYWORDS": [
        "vétérinaire",
        "clinique vétérinaire",
        "cabinet vétérinaire",
        "veterinaire",
    ],
    "EXPANSION_KEYWORDS": [
        "veterinary clinic",
        "veterinarian",
        "vet clinic",
        "clinique veterinaire",
        "cabinet veterinaire",
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
        "angle": "Lead gen pour vétérinaires libéraux (JUM Advisory)",
        "valeur_client": "Prise de RDV étude fiscale DGFiP / AMF — cotisations, taxe 30–41 %",
        "effectif_cible": "cabinets / cliniques indépendants",
    },
}

CONFIG = VETERINAIRES_CONFIG
