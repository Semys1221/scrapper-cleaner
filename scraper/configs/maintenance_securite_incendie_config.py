"""Maintenance sécurité incendie tertiaire (France) scraper preset — static rules; secrets come from config_loader."""

from french_cities import FRENCH_EXPANSION_LOCATIONS, FRENCH_LOCATIONS

PRESET_ID = "maintenance_securite_incendie"
PRESET_LABEL = "Maintenance sécurité incendie tertiaire (France)"

_LIST_ID = ""
_CAMPAIGN_ID = ""
_SUBSEQUENCE_ID = ""

MAINTENANCE_SECURITE_INCENDIE_CONFIG = {
    "OUTSCRAPER_API_KEY": "",
    "INSTANTLY_API_KEY": "",
    "INSTANTLY_LIST_ID": _LIST_ID,
    "INSTANTLY_CAMPAIGN_ID": _CAMPAIGN_ID,
    "INSTANTLY_SUBSEQUENCE_ID": _SUBSEQUENCE_ID,
    "INSTANTLY_DEDUP_LIST_IDS": [_LIST_ID],
    "INSTANTLY_DEDUP_CAMPAIGN_IDS": [_CAMPAIGN_ID],
    "INSTANTLY_PUSH_EVERY": 100,
    "ENRICH_ENABLED": False,
    "ENRICH_BATCH_SIZE": 50,
    "ENRICH_CONCURRENCY": 20,
    "ENRICH_TIMEOUT_MS": 10000,
    "ENRICH_INCLUDED_KEYWORDS": [
        "sécurité incendie",
        "système de sécurité incendie",
        "extincteur",
        "désenfumage",
        "ria",
    ],
    "ENRICH_HARD_EXCLUDED_KEYWORDS": [
        "particulier",
        "maison",
        "alarme",
        "vidéosurveillance",
        "ssiap",
        "apave",
        "socotec",
        "veritas",
        "vinci facilities",
    ],
    "ENRICH_SOFT_EXCLUDED_KEYWORDS": [],
    "OUTSCRAPER_BATCH_SIZE": 200,
    "OUTSCRAPER_CONCURRENCY": 6,
    "OUTSCRAPER_LIMIT_PER_QUERY": 30,
    "OUTSCRAPER_POLL_INITIAL_S": 45,
    "OUTSCRAPER_POLL_INTERVAL_S": 5,
    "OUTSCRAPER_POLL_SLOW_S": 10,
    "OUTSCRAPER_POLL_TIMEOUT_S": 600,
    "OUTSCRAPER_TOTAL_LIMIT_BUFFER": 8,
    "TARGET_LEADS": 3000,
    "TARGET_MODE": "instantly_pushed",
    "SERVICE_DEFAULT": "Sécurité incendie",
    "SERVICE_RULES": [],
    "KEYWORDS": [
        "sécurité incendie",
        "maintenance SSI",
        "extincteur tertiaire",
        "désenfumage",
        "RIA incendie",
    ],
    "EXPANSION_KEYWORDS": [
        "maintenance extincteur",
        "système sécurité incendie",
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
    "PAPPERS_MIN_EMPLOYEES": 3,
    "PAPPERS_MIN_SCORE": 55,
    "PAPPERS_SCORING_ENABLED": True,
    "PAPPERS_ON_UNKNOWN": "reject",
    "PAPPERS_CONCURRENCY": 50,
    "PAPPERS_NAF_PREFIXES": [],
    "SIRENE_INDEX_ENABLED": True,
    "SIRENE_INDEX_PATH": "data/sirene.db",
    "REGISTRY_DEEP_ENRICH": False,
    "REJECT_HOLDINGS": True,
    "NICHE_METADATA": {
        "angle": "Lead gen pour maintenance sécurité incendie tertiaire",
        "valeur_client": "Prise de RDV avec des PME SSI / extincteurs / désenfumage",
        "effectif_cible": "3+ salariés",
    },
}

CONFIG = MAINTENANCE_SECURITE_INCENDIE_CONFIG
