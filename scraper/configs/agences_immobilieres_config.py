"""Agences immobilières (France) — Outscraper taxonomy gate."""

from french_cities import FRENCH_EXPANSION_LOCATIONS, FRENCH_LOCATIONS

PRESET_ID = "agences_immobilieres"
PRESET_LABEL = "Agences immobilières (France)"

INSTANTLY_NAME = "Agence immobilière"
SCRAPE_QUEUE_RANK = 3

_LIST_ID = "9c4e4fd5-e825-4ded-b7a9-9fc68361758a"
_CAMPAIGN_ID = "93c2e56f-4088-4495-94da-7891153e3947"
_SUBSEQUENCE_ID = ""

AGENCES_IMMOBILIERES_CONFIG = {
    "OUTSCRAPER_API_KEY": "",
    "INSTANTLY_API_KEY": "",
    "INSTANTLY_NAME": INSTANTLY_NAME,
    "SCRAPE_QUEUE_RANK": SCRAPE_QUEUE_RANK,
    "INSTANTLY_LIST_ID": _LIST_ID,
    "INSTANTLY_CAMPAIGN_ID": _CAMPAIGN_ID,
    "INSTANTLY_SUBSEQUENCE_ID": _SUBSEQUENCE_ID,
    "INSTANTLY_DEDUP_LIST_IDS": [_LIST_ID] if _LIST_ID else [],
    "INSTANTLY_DEDUP_CAMPAIGN_IDS": [_CAMPAIGN_ID] if _CAMPAIGN_ID else [],
    "INSTANTLY_SKIP_IF_IN_CAMPAIGN": False,
    "INSTANTLY_SKIP_IF_IN_LIST": False,
    "INSTANTLY_PUSH_EVERY": 25,
    "INSTANTLY_PROVISION_LINKS": True,
    # provision-leads moves provisioned list leads into the campaign
    "INSTANTLY_ATTACH_TO_CAMPAIGN": True,
    "LINK_PROVISION_CATEGORY": "cif",
    "LINK_PROVISION_RESERVATION_PAGE": "agences-immobilieres",
    "ENRICH_ENABLED": False,
    "INGESTER_ENABLED": True,
    "INGESTER_MIN_SCORE": 0.55,
    "INGESTER_BORDERLINE_MIN": 0.35,
    "INGESTER_CONCURRENCY": 12,
    "INGESTER_FETCH_TIMEOUT": 8.0,
    "INGESTER_SIGNAL_WEIGHTS": {
        "taxonomy": 0.35,
        "website": 0.30,
        "review": 0.20,
        "registry": 0.15,
    },
    "INGESTER_REVIEW_ICP_KEYWORDS": [
        "immobilier",
        "vente",
        "achat",
        "estimation",
        "mandat",
        "appartement",
        "maison",
        "location",
    ],
    "INGESTER_REVIEW_ANTI_ICP_KEYWORDS": [
        "logiciel",
        "plateforme",
        "recrutement",
        "formation",
        "mandataire seul",
        "micro-agence",
        "débutant",
        "debutant",
    ],
    "OUTSCRAPER_FILTERS": ["only_with_website", "operational_only"],
    "TAXONOMY_GATE_ENABLED": True,
    "TAXONOMY_INCLUDED_KEYWORDS": [
        "agence immobilière",
        "agence immobiliere",
        "agent immobilier",
        "agent immobilier indépendant",
        "mandataire immobilier",
        "real estate agency",
        "real estate agent",
        "immobilier",
        "transaction immobilière",
    ],
    "TAXONOMY_EXCLUDED_KEYWORDS": [
        "promoteur immobilier",
        "constructeur immobilier",
        "notaire",
        "syndic",
        "syndic de copropriété",
        "agence de publicité",
        "agence de marketing",
        "location de matériel",
        "administration",
        "recrutement",
    ],
    "ENRICH_INCLUDED_KEYWORDS": [
        "immobilier",
        "agence immobilière",
        "agent immobilier",
        "mandataire",
    ],
    "ENRICH_HARD_EXCLUDED_KEYWORDS": [
        "promoteur",
        "notaire",
        "syndic",
        "logiciel",
        "recrutement",
    ],
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
    "TARGET_MODE": "instantly_pushed",
    "SERVICE_DEFAULT": "Agence immobilière",
    "SERVICE_RULES": [],
    "KEYWORDS": [
        "agence immobilière",
        "agent immobilier",
        "mandataire immobilier",
    ],
    "EXPANSION_KEYWORDS": [
        "agence immobiliere",
        "immobilier",
        "real estate agency",
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
        "angle": "Mandat ~8–10 k€ commission ; habituées au marketing payant",
        "valeur_client": "Prise de RDV mandats vente / estimation — viser agences >300 k€ CA",
        "effectif_cible": "agences structurées (éviter <300 k€ CA, décrochent vite)",
        "priorite": 3,
    },
}

CONFIG = AGENCES_IMMOBILIERES_CONFIG
