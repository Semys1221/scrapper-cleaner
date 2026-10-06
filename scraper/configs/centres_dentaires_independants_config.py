"""Centres dentaires indépendants (France) — hors réseaux / franchises."""

from french_cities import FRENCH_EXPANSION_LOCATIONS, FRENCH_LOCATIONS

PRESET_ID = "centres_dentaires_independants"
PRESET_LABEL = "Centres dentaires indépendants (France)"

_LIST_ID = "9219adfa-e1e8-4f95-8003-a4bd9dbddabc"
_CAMPAIGN_ID = "9503c784-3a7d-40e0-b58a-e1877cab45f5"
_SUBSEQUENCE_ID = ""

INSTANTLY_NAME = "Centre dentaire indépendant"
SCRAPE_QUEUE_RANK = 4

CENTRES_DENTAIRES_INDEPENDANTS_CONFIG = {
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
    "INGESTER_MIN_SCORE": 0.55,
    "INGESTER_BORDERLINE_MIN": 0.35,
    "INGESTER_CONCURRENCY": 12,
    "INGESTER_FETCH_TIMEOUT": 8.0,
    "INGESTER_SIGNAL_WEIGHTS": {
        "taxonomy": 0.30,
        "website": 0.35,
        "review": 0.25,
        "registry": 0.10,
    },
    "INGESTER_REVIEW_ICP_KEYWORDS": [
        "implant",
        "implantologie",
        "cabinet",
        "centre dentaire",
        "soins",
        "urgence",
    ],
    "INGESTER_REVIEW_ANTI_ICP_KEYWORDS": [
        "dentego",
        "réseau",
        "reseau",
        "franchise",
        "groupe",
        "siège",
        "siege",
        "adental",
        "mutualiste",
        "recrutement",
    ],
    "OUTSCRAPER_FILTERS": ["only_with_website", "operational_only"],
    "TAXONOMY_GATE_ENABLED": True,
    "TAXONOMY_INCLUDED_KEYWORDS": [
        "centre dentaire",
        "cabinet dentaire",
        "chirurgien-dentiste",
        "chirurgien dentiste",
        "dentiste",
        "soins dentaires",
        "implantologie",
        "dental clinic",
    ],
    "TAXONOMY_EXCLUDED_KEYWORDS": [
        "dentego",
        "adental",
        "centre mutualiste",
        "réseau",
        "reseau",
        "franchise",
        "groupe dentaire",
        "laboratoire de prothèse",
        "prothésiste",
        "logiciel dentaire",
        "recrutement",
    ],
    "ENRICH_INCLUDED_KEYWORDS": [],
    "ENRICH_HARD_EXCLUDED_KEYWORDS": [],
    "ENRICH_SOFT_EXCLUDED_KEYWORDS": [],
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
    "SERVICE_DEFAULT": "Centre dentaire",
    "SERVICE_RULES": [],
    "KEYWORDS": [
        "centre dentaire",
        "cabinet dentaire",
        "implant dentaire",
    ],
    "EXPANSION_KEYWORDS": [
        "chirurgien dentiste",
        "implantologie",
        "soins dentaires",
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
        "dentego.fr",
    ],
    "PAPPERS_ENABLED": False,
    "NICHE_METADATA": {
        "angle": "Implant 1–2,5 k€ ; budget marketing disponible",
        "valeur_client": "Centre dentaire indépendant (pas de réseau / siège)",
        "effectif_cible": "structures locales hors franchise",
        "priorite": 4,
    },
}

CONFIG = CENTRES_DENTAIRES_INDEPENDANTS_CONFIG
