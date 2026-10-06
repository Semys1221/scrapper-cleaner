"""Hôtels indépendants 3★+ (France) — hors chaînes nationales."""

from french_cities import FRENCH_EXPANSION_LOCATIONS, FRENCH_LOCATIONS

PRESET_ID = "hotels_independants"
PRESET_LABEL = "Hôtels indépendants (France)"

_LIST_ID = "ae610cce-3aff-46c0-bc46-d6098b3a0958"
_CAMPAIGN_ID = "4ab9bbff-c41a-4e66-bc48-cddfa8b8d4c4"
_SUBSEQUENCE_ID = ""

INSTANTLY_NAME = "Hôtel indépendant"
SCRAPE_QUEUE_RANK = 5

HOTELS_INDEPENDANTS_CONFIG = {
    "OUTSCRAPER_API_KEY": "",
    "INSTANTLY_API_KEY": "",
    "INSTANTLY_NAME": INSTANTLY_NAME,
    "SCRAPE_QUEUE_RANK": SCRAPE_QUEUE_RANK,
    "INSTANTLY_LIST_ID": _LIST_ID,
    "INSTANTLY_CAMPAIGN_ID": _CAMPAIGN_ID,
    "INSTANTLY_SUBSEQUENCE_ID": _SUBSEQUENCE_ID,
    "INSTANTLY_DEDUP_LIST_IDS": [_LIST_ID] if _LIST_ID else [],
    "INSTANTLY_DEDUP_CAMPAIGN_IDS": [_CAMPAIGN_ID] if _CAMPAIGN_ID else [],
    "INSTANTLY_SKIP_IF_IN_CAMPAIGN": True,
    "INSTANTLY_SKIP_IF_IN_LIST": True,
    "INSTANTLY_PUSH_EVERY": 25,
    "INSTANTLY_PROVISION_LINKS": False,
    "ENRICH_ENABLED": False,
    "INGESTER_ENABLED": True,
    "INGESTER_MIN_SCORE": 0.50,
    "INGESTER_BORDERLINE_MIN": 0.30,
    "INGESTER_CONCURRENCY": 12,
    "INGESTER_FETCH_TIMEOUT": 8.0,
    "INGESTER_SIGNAL_WEIGHTS": {
        "taxonomy": 0.35,
        "website": 0.35,
        "review": 0.20,
        "registry": 0.10,
    },
    "INGESTER_REVIEW_ICP_KEYWORDS": [
        "hôtel",
        "hotel",
        "chambre",
        "réservation",
        "reservation",
        "spa",
        "restaurant",
        "séjour",
    ],
    "INGESTER_REVIEW_ANTI_ICP_KEYWORDS": [
        "booking.com",
        "accor",
        "ibis",
        "mercure",
        "novotel",
        "best western",
        "campanile",
        "groupe hôtelier",
        "recrutement",
    ],
    "OUTSCRAPER_FILTERS": ["only_with_website", "operational_only"],
    "TAXONOMY_GATE_ENABLED": True,
    "TAXONOMY_INCLUDED_KEYWORDS": [
        "hôtel",
        "hotel",
        "boutique hotel",
        "hôtel-restaurant",
        "hotel restaurant",
        "auberge",
        "château hôtel",
        "resort",
    ],
    "TAXONOMY_EXCLUDED_KEYWORDS": [
        "auberge de jeunesse",
        "hostel",
        "camping",
        "gîte",
        "gite",
        "location saisonnière",
        "airbnb",
        "agence de voyage",
        "recrutement",
    ],
    "ENRICH_INCLUDED_KEYWORDS": [],
    "ENRICH_HARD_EXCLUDED_KEYWORDS": [],
    "ENRICH_SOFT_EXCLUDED_KEYWORDS": [],
    "OUTSCRAPER_BATCH_SIZE": 200,
    "OUTSCRAPER_CONCURRENCY": 2,
    "OUTSCRAPER_LIMIT_PER_QUERY": 400,
    "OUTSCRAPER_POLL_INITIAL_S": 45,
    "OUTSCRAPER_POLL_INTERVAL_S": 5,
    "OUTSCRAPER_POLL_SLOW_S": 10,
    "OUTSCRAPER_POLL_TIMEOUT_S": 600,
    "OUTSCRAPER_TOTAL_LIMIT_BUFFER": 8,
    "OUTSCRAPER_ENRICHMENT": ["leads_n_contacts"],
    "OUTSCRAPER_EMAIL_RECOVERY_ENABLED": True,
    "TARGET_LEADS": 3000,
    "TARGET_MODE": "instantly_pushed_run",
    "SERVICE_DEFAULT": "Hôtellerie",
    "SERVICE_RULES": [],
    "KEYWORDS": [
        "hôtel 3 étoiles",
        "hôtel 4 étoiles",
        "hôtel indépendant",
        "boutique hôtel",
    ],
    "EXPANSION_KEYWORDS": [
        "hotel independent",
        "hotel restaurant",
        "château hôtel",
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
        "booking.com",
    ],
    "PAPPERS_ENABLED": False,
    "NICHE_METADATA": {
        "angle": "Réduire commission Booking 15–18 % (saisonnalité / groupes)",
        "valeur_client": "Hôtel indépendant 3★ minimum",
        "effectif_cible": "établissements hors chaînes nationales",
        "priorite": 5,
    },
}

CONFIG = HOTELS_INDEPENDANTS_CONFIG
