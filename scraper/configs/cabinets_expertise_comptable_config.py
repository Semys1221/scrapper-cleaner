"""Cabinets expertise comptable (France) scraper preset — static rules; secrets come from config_loader."""

from french_cities import FRENCH_EXPANSION_LOCATIONS, FRENCH_LOCATIONS

PRESET_ID = "cabinets_expertise_comptable"
PRESET_LABEL = "Cabinets expertise comptable (France)"

_LIST_ID = "edfd3090-6306-4f71-bd83-01192b06666c"
_CAMPAIGN_ID = "5591a068-75f9-4826-8564-4dc2acc74bd4"
_SUBSEQUENCE_ID = "7105ed91-f2b7-4316-96c9-76a3c374cd6e"

CABINETS_EXPERTISE_COMPTABLE_CONFIG = {
    "OUTSCRAPER_API_KEY": "",
    "INSTANTLY_API_KEY": "",
    "INSTANTLY_LIST_ID": _LIST_ID,
    "INSTANTLY_CAMPAIGN_ID": _CAMPAIGN_ID,
    "INSTANTLY_SUBSEQUENCE_ID": _SUBSEQUENCE_ID,
    "INSTANTLY_DEDUP_LIST_IDS": [_LIST_ID],
    "INSTANTLY_DEDUP_CAMPAIGN_IDS": [],
    "INSTANTLY_SKIP_IF_IN_CAMPAIGN": False,
    "INSTANTLY_SKIP_IF_IN_LIST": False,
    "INSTANTLY_PUSH_EVERY": 25,
    "ENRICH_ENABLED": False,
    "ENRICH_BATCH_SIZE": 100,
    "ENRICH_CONCURRENCY": 40,
    "ENRICH_TIMEOUT_MS": 6000,
    "ENRICH_INCLUDED_KEYWORDS": [
        "expert comptable",
        "expert-comptable",
        "expertise comptable",
        "comptabilité",
        "cabinet comptable",
        "comptables",
        "bilan",
        "liasse fiscale",
        "fiscalité",
        "commissaire aux comptes",
    ],
    "ENRICH_HARD_EXCLUDED_KEYWORDS": [
        "dougs",
        "pennylane",
        "indy",
        "fiducial",
        "in extenso",
        "centre de gestion",
        "aga",
        "kpmg",
        "deloitte",
        "ey",
        "pwc",
        "pricewaterhousecoopers",
    ],
    "ENRICH_SOFT_EXCLUDED_KEYWORDS": [],
    "OUTSCRAPER_BATCH_SIZE": 200,
    "OUTSCRAPER_CONCURRENCY": 8,
    "OUTSCRAPER_LIMIT_PER_QUERY": 50,
    "OUTSCRAPER_POLL_INITIAL_S": 15,
    "OUTSCRAPER_POLL_INTERVAL_S": 5,
    "OUTSCRAPER_POLL_SLOW_S": 10,
    "OUTSCRAPER_POLL_TIMEOUT_S": 600,
    "OUTSCRAPER_TOTAL_LIMIT_BUFFER": 8,
    "TARGET_LEADS": 3000,
    "TARGET_MODE": "instantly_pushed",
    "SCRAPE_START_QUERY_PASS": 1,
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
    "PAPPERS_MIN_EMPLOYEES": 0,
    "PAPPERS_MIN_SCORE": 45,
    "PAPPERS_SCORING_ENABLED": True,
    "PAPPERS_ON_UNKNOWN": "accept",
    "PAPPERS_CONCURRENCY": 50,
    "PAPPERS_NAF_PREFIXES": [],
    "SIRENE_INDEX_ENABLED": True,
    "SIRENE_INDEX_PATH": "data/sirene.db",
    "REGISTRY_DEEP_ENRICH": True,
    "REJECT_HOLDINGS": False,
    "NICHE_METADATA": {
        "angle": "Lead gen pour cabinets d'expertise comptable",
        "valeur_client": "Prise de RDV avec des cabinets EC indépendants",
        "effectif_cible": "3+ salariés",
    },
}

CONFIG = CABINETS_EXPERTISE_COMPTABLE_CONFIG
