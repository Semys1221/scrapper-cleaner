"""Website signal — HTML text extraction + ICP keyword scoring (no HTTP)."""

from __future__ import annotations

import re
from typing import Any

import trafilatura
from selectolax.lexbor import LexborHTMLParser

from lead_ingester.models import SignalResult


def extract_text(html: str) -> str:
    """Return clean prose from HTML. Uses trafilatura; falls back to selectolax."""
    if not html:
        return ""
    text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        favor_recall=True,
    )
    if text is None or len(text) < 100:
        try:
            tree = LexborHTMLParser(html)
            body = tree.body
            fallback = body.text(separator=" ", strip=True) if body is not None else ""
            if len(fallback) > len(text or ""):
                text = fallback
        except Exception:
            pass
    return (text or "").lower()


def _find_keywords(text: str, keywords: list[str]) -> list[str]:
    found: list[str] = []
    for kw in keywords:
        word = str(kw).strip().lower()
        if not word:
            continue
        if re.search(r"\b" + re.escape(word) + r"\b", text):
            found.append(kw)
    return found


def score_website(
    html: str | None,
    config: dict[str, Any],
    fetch_error: str | None = None,
) -> SignalResult:
    """Score a lead from raw HTML. ``html=None`` means site not fetched → neutral."""
    if html is None:
        return SignalResult(score=0.5, error=fetch_error or "no_html")

    text = extract_text(html)
    if len(text) < 50:
        return SignalResult(
            score=0.5,
            error="insufficient_text",
            detail={"text_len": len(text)},
        )

    included = list(config.get("ENRICH_INCLUDED_KEYWORDS") or [])
    hard_excluded = list(config.get("ENRICH_HARD_EXCLUDED_KEYWORDS") or [])
    soft_excluded = list(config.get("ENRICH_SOFT_EXCLUDED_KEYWORDS") or [])
    # Legacy single list → treat as hard
    if not hard_excluded and not soft_excluded:
        legacy = list(config.get("ENRICH_EXCLUDED_KEYWORDS") or [])
        if legacy:
            hard_excluded = legacy

    hard_matches = _find_keywords(text, hard_excluded)
    if hard_matches:
        return SignalResult(
            score=0.0,
            hard_reject=True,
            matched_exclude=hard_matches,
            detail={"text_len": len(text)},
        )

    inc_matches = _find_keywords(text, included)
    soft_matches = _find_keywords(text, soft_excluded)

    score = 0.5
    if len(inc_matches) >= 1:
        score += 0.3
    if len(inc_matches) >= 3:
        score += 0.2
    if len(soft_matches) >= 2:
        score -= 0.3
    score = max(0.0, min(1.0, score))

    return SignalResult(
        score=score,
        matched_include=inc_matches,
        matched_exclude=soft_matches,
        detail={"text_len": len(text)},
    )
