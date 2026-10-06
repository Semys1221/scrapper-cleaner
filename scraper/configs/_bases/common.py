"""Settings shared across all B2B niche sub-niche presets."""

from french_cities import FRENCH_EXPANSION_LOCATIONS, FRENCH_LOCATIONS

EXCLUDE_DOMAINS = [
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
]

OUTSCRAPER_SETTINGS = {
    "OUTSCRAPER_BATCH_SIZE": 200,
    "OUTSCRAPER_CONCURRENCY": 2,
    "OUTSCRAPER_LIMIT_PER_QUERY": 400,
    "OUTSCRAPER_POLL_INITIAL_S": 45,
    "OUTSCRAPER_POLL_INTERVAL_S": 5,
    "OUTSCRAPER_POLL_SLOW_S": 10,
    "OUTSCRAPER_POLL_TIMEOUT_S": 600,
    "OUTSCRAPER_TOTAL_LIMIT_BUFFER": 8,
    "OUTSCRAPER_FILTERS": [],
    "OUTSCRAPER_ENRICHMENT": ["leads_n_contacts"],
}

ENRICH_SETTINGS = {
    "ENRICH_ENABLED": False,
    "ENRICH_BATCH_SIZE": 50,
    "ENRICH_CONCURRENCY": 20,
    "ENRICH_TIMEOUT_MS": 10000,
}

INGESTER_SETTINGS = {
    "INGESTER_ENABLED": False,
    "INGESTER_MIN_SCORE": 0.60,
    "INGESTER_BORDERLINE_MIN": 0.40,
    "INGESTER_SIGNAL_WEIGHTS": {
        "taxonomy": 0.20,
        "website": 0.40,
        "review": 0.25,
        "registry": 0.15,
    },
    "INGESTER_CONCURRENCY": 10,
    "INGESTER_FETCH_TIMEOUT": 8.0,
    "INGESTER_REVIEW_ICP_KEYWORDS": [
        "cabinet",
        "expert",
        "comptable",
        "mission",
        "client",
        "conseil",
        "bilan",
        "déclaration",
        "fiscalité",
    ],
    "INGESTER_REVIEW_ANTI_ICP_KEYWORDS": [
        "logiciel",
        "plateforme",
        "solution en ligne",
        "outil",
        "recrutement",
        "recruter",
        "chasseur de têtes",
        "immobilier",
        "assurance",
        "gestion de patrimoine",
    ],
}

TARGET_SETTINGS = {
    "TARGET_LEADS": 3_000,
    "TARGET_MODE": "instantly_pushed",
    "INSTANTLY_PUSH_EVERY": 100,
    "INSTANTLY_BACKLOG_PUSH_MIN": 100,
    "INSTANTLY_PROVISION_LINKS": False,
    "LINK_PROVISION_CATEGORY": "",
}

REGISTRY_SETTINGS = {
    "PAPPERS_ENABLED": False,
    "PAPPERS_MIN_EMPLOYEES": 3,
    "PAPPERS_MAX_EMPLOYEES": 0,
    "PAPPERS_MIN_SCORE": 55,
    "PAPPERS_SCORING_ENABLED": True,
    "PAPPERS_ON_UNKNOWN": "reject",
    "PAPPERS_CONCURRENCY": 50,
    "SIRENE_INDEX_ENABLED": True,
    "SIRENE_INDEX_PATH": "data/sirene.db",
    "REGISTRY_DEEP_ENRICH": False,
    "REJECT_HOLDINGS": True,
}

LOCATIONS = FRENCH_LOCATIONS
EXPANSION_LOCATIONS = FRENCH_EXPANSION_LOCATIONS
