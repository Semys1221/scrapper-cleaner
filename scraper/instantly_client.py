"""Instantly API v2 — lead list upload with native duplicate skip flags."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any, Callable, Iterator, Mapping

import httpx
import pandas as pd
import requests

INSTANTLY_API_BASE = "https://api.instantly.ai/api/v2"
PAGE_SIZE = 100
_MAX_RETRIES = 5
_BACKOFF_BASE = 2.0
_HTTP_TIMEOUT = (10, 60)
_BULK_BATCH_SIZE = 100


def _leads_read_timeout_s() -> int:
    raw = os.getenv("INSTANTLY_READ_TIMEOUT_S", "180")
    try:
        return max(int(raw), 30)
    except ValueError:
        return 180


_HTTP_TIMEOUT_LEADS_LIST = (10, _leads_read_timeout_s())

_LIB_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_CACHE_PATH = os.path.join(_LIB_DIR, "output", "workspace_emails.json")
WORKSPACE_CACHE_TTL_S = 6 * 3600
CSV_COLUMNS = [
    "Email",
    "Company",
    "Website",
    "Service",
    "Niche",
    "Subniche",
    "City",
    "Type",
    "Category",
    "Subtypes",
    "Siret",
    "Siren",
    "Effectif",
    "TrancheEffectif",
    "Naf",
    "FormeJuridique",
    "AnneeCreation",
    "ChiffreAffaires",
    "TailleEntreprise",
    "LeadScore",
    "RegistrySource",
    "RegistryFetchedAt",
]
_REQUIRED_CSV_COLUMNS = ["Email", "Company", "Website", "Service", "City"]


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _normalize_scope_ids(ids: list[str] | None) -> list[str]:
    if not ids:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for raw in ids:
        value = str(raw).strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return sorted(result)


def _read_email(lead: dict[str, Any]) -> str:
    email = lead.get("email")
    if isinstance(email, str) and "@" in email:
        return _normalize_email(email)
    payload = lead.get("payload")
    if isinstance(payload, dict):
        nested = payload.get("email")
        if isinstance(nested, str) and "@" in nested:
            return _normalize_email(nested)
    return ""


class InstantlyClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key.strip()
        self.session = requests.Session()

    def _fetch(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        attempt: int = 0,
        timeout: tuple[int, int] | None = None,
    ) -> Any:
        url = f"{INSTANTLY_API_BASE}{endpoint}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req_timeout = timeout or _HTTP_TIMEOUT

        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                json=body if body is not None else None,
                timeout=req_timeout,
            )
        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ) as exc:
            if attempt < _MAX_RETRIES:
                time.sleep(_BACKOFF_BASE**attempt)
                return self._fetch(
                    endpoint,
                    method=method,
                    body=body,
                    attempt=attempt + 1,
                    timeout=timeout,
                )
            raise RuntimeError(
                f"Instantly API request failed on {endpoint} after "
                f"{attempt + 1} attempt(s): {exc}"
            ) from exc

        text = response.text or ""
        data: Any = None
        if text:
            try:
                data = response.json()
            except ValueError:
                data = text

        if response.status_code == 429 and attempt < _MAX_RETRIES:
            retry_after = response.headers.get("Retry-After", "65")
            try:
                wait_s = int(retry_after)
            except ValueError:
                wait_s = 65
            time.sleep(max(wait_s, 1))
            return self._fetch(
                endpoint,
                method=method,
                body=body,
                attempt=attempt + 1,
                timeout=timeout,
            )

        if response.status_code >= 500 and attempt < _MAX_RETRIES:
            time.sleep(_BACKOFF_BASE**attempt)
            return self._fetch(
                endpoint,
                method=method,
                body=body,
                attempt=attempt + 1,
                timeout=timeout,
            )

        if not response.ok:
            detail = data if isinstance(data, str) else json.dumps(data)
            raise RuntimeError(
                f"Instantly API {response.status_code} on {endpoint}: {detail}"
            )

        return data

    def _paginate_lead_emails(
        self,
        scope: dict[str, str],
        *,
        on_progress: Callable[[int], None] | None = None,
        on_page: Callable[[set[str]], None] | None = None,
        max_pages: int = 500,
    ) -> set[str]:
        emails: set[str] = set()
        starting_after: str | None = None
        previous_cursor: str | None = None

        for _page in range(max_pages):
            body: dict[str, Any] = {**scope, "limit": PAGE_SIZE}
            if starting_after:
                body["starting_after"] = starting_after

            page = self._fetch(
                "/leads/list",
                method="POST",
                body=body,
                timeout=_HTTP_TIMEOUT_LEADS_LIST,
            )
            items = page.get("items") or []
            if not items:
                break

            for item in items:
                email = _read_email(item)
                if email:
                    emails.add(email)

            if on_progress:
                on_progress(len(emails))
            if on_page:
                on_page(set(emails))

            next_cursor = page.get("next_starting_after")
            if not next_cursor:
                last_email = _read_email(items[-1])
                next_cursor = last_email or items[-1].get("id")

            if len(items) < PAGE_SIZE or not next_cursor:
                break

            next_cursor = str(next_cursor)
            if next_cursor == previous_cursor:
                break

            previous_cursor = next_cursor
            starting_after = next_cursor

        return emails

    def fetch_dedup_emails(
        self,
        list_ids: list[str],
        campaign_ids: list[str],
        *,
        on_progress: Callable[[int], None] | None = None,
        on_page: Callable[[set[str]], None] | None = None,
        on_scope_complete: Callable[[str], None] | None = None,
        initial_emails: set[str] | None = None,
        skip_scopes: set[str] | None = None,
    ) -> set[str]:
        """Return emails from configured Instantly lists and campaigns."""
        emails: set[str] = set(initial_emails or [])
        skip = set(skip_scopes or [])

        def _checkpoint(scope_emails: set[str]) -> None:
            combined = set(emails)
            combined.update(scope_emails)
            if on_progress:
                on_progress(len(combined))
            if on_page:
                on_page(combined)

        for list_id in list_ids:
            scope_key = f"list:{list_id}"
            if scope_key in skip:
                continue
            scoped = self._paginate_lead_emails(
                {"list_id": list_id},
                on_page=_checkpoint,
            )
            emails.update(scoped)
            if on_scope_complete:
                on_scope_complete(scope_key)
            _checkpoint(set())

        for campaign_id in campaign_ids:
            scope_key = f"campaign:{campaign_id}"
            if scope_key in skip:
                continue
            scoped = self._paginate_lead_emails(
                {"campaign": campaign_id},
                on_page=_checkpoint,
            )
            emails.update(scoped)
            if on_scope_complete:
                on_scope_complete(scope_key)
            _checkpoint(set())

        if on_progress:
            on_progress(len(emails))
        return emails

    def list_all_lead_lists(self) -> list[dict[str, Any]]:
        return self._paginate_collection("/lead-lists")

    def list_all_campaigns(self) -> list[dict[str, Any]]:
        return self._paginate_collection("/campaigns")

    def create_lead_list(self, name: str) -> dict[str, Any]:
        data = self._fetch("/lead-lists", method="POST", body={"name": name})
        if not isinstance(data, dict) or not data.get("id"):
            raise RuntimeError(f"Instantly create lead list returned no id: {data!r}")
        return data

    def create_campaign(self, name: str) -> dict[str, Any]:
        data = self._fetch(
            "/campaigns",
            method="POST",
            body={
                "name": name,
                "campaign_schedule": DEFAULT_CAMPAIGN_SCHEDULE,
            },
        )
        if not isinstance(data, dict) or not data.get("id"):
            raise RuntimeError(f"Instantly create campaign returned no id: {data!r}")
        return data

    def _paginate_collection(self, base: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        starting_after: str | None = None
        previous: str | None = None
        for _ in range(200):
            path = f"{base}?limit={PAGE_SIZE}"
            if starting_after:
                path += f"&starting_after={starting_after}"
            page = self._fetch(path, method="GET")
            page_items = page.get("items") or [] if isinstance(page, dict) else []
            items.extend(item for item in page_items if isinstance(item, dict))
            next_cursor = page.get("next_starting_after") if isinstance(page, dict) else None
            if not next_cursor and page_items:
                next_cursor = page_items[-1].get("id")
            if not next_cursor or len(page_items) < PAGE_SIZE:
                break
            next_cursor = str(next_cursor)
            if next_cursor == previous:
                break
            previous = next_cursor
            starting_after = next_cursor
        return items


DEFAULT_CAMPAIGN_SCHEDULE = {
    "schedules": [
        {
            "name": "Weekdays Paris",
            "timing": {"from": "09:00", "to": "17:00"},
            "days": {
                "0": True,
                "1": True,
                "2": True,
                "3": True,
                "4": True,
                "5": False,
                "6": False,
            },
            "timezone": "Africa/Ceuta",
        }
    ]
}


def instantly_resource_name(label: str) -> str:
    """Short Instantly list/campaign name (no Hercule prefix)."""
    clean = (label or "").strip() or "Untitled"
    for prefix in ("Hercule —", "Hercule - ", "hercule —", "hercule - "):
        if clean.lower().startswith(prefix.lower()):
            clean = clean[len(prefix) :].strip()
    if clean.endswith("(France)"):
        clean = clean[: -len("(France)")].strip()
    return clean or "Untitled"


def instantly_name_from_config(config: Mapping[str, Any] | None, label: str) -> str:
    explicit = str((config or {}).get("INSTANTLY_NAME") or "").strip()
    if explicit:
        return explicit
    return instantly_resource_name(label)


def _match_by_name(items: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    needle = name.strip().lower()
    for item in items:
        if str(item.get("name") or "").strip().lower() == needle:
            return item
    return None


def ensure_lead_list(api_key: str, name: str) -> dict[str, Any]:
    client = InstantlyClient(api_key)
    existing = _match_by_name(client.list_all_lead_lists(), name)
    if existing:
        return existing
    return client.create_lead_list(name)


def copy_campaign_settings(
    api_key: str,
    target_campaign_id: str,
    template_campaign_id: str,
    *,
    copy_sequences: bool = True,
) -> dict[str, Any]:
    """Copy schedule (and optionally sequences) from an existing campaign."""
    template = get_campaign(api_key, template_campaign_id)
    if not template:
        raise RuntimeError(f"Template campaign not found: {template_campaign_id}")
    body: dict[str, Any] = {}
    schedule = template.get("campaign_schedule")
    if schedule:
        body["campaign_schedule"] = schedule
    if copy_sequences and template.get("sequences"):
        body["sequences"] = template["sequences"]
    if not body:
        return {}
    client = InstantlyClient(api_key)
    data = client._fetch(
        f"/campaigns/{target_campaign_id.strip()}",
        method="PATCH",
        body=body,
    )
    return data if isinstance(data, dict) else {}


def ensure_campaign(
    api_key: str,
    name: str,
    *,
    template_campaign_id: str = "",
) -> dict[str, Any]:
    client = InstantlyClient(api_key)
    existing = _match_by_name(client.list_all_campaigns(), name)
    if existing:
        campaign = existing
    else:
        campaign = client.create_campaign(name)
    campaign_id = str(campaign.get("id") or "").strip()
    template_id = str(template_campaign_id or "").strip()
    if campaign_id and template_id:
        if not campaign_has_sequence_emails(api_key, campaign_id, min_steps=1):
            copy_campaign_settings(api_key, campaign_id, template_id)
        elif not existing:
            copy_campaign_settings(api_key, campaign_id, template_id, copy_sequences=False)
    return campaign


def sync_lead_list_name(api_key: str, list_id: str, name: str) -> None:
    needle = name.strip()
    if not list_id or not needle:
        return
    client = InstantlyClient(api_key)
    client._fetch(
        f"/lead-lists/{list_id.strip()}",
        method="PATCH",
        body={"name": needle},
    )


def sync_campaign_name(api_key: str, campaign_id: str, name: str) -> None:
    needle = name.strip()
    if not campaign_id or not needle:
        return
    client = InstantlyClient(api_key)
    client._fetch(
        f"/campaigns/{campaign_id.strip()}",
        method="PATCH",
        body={"name": needle},
    )


DEFAULT_INTERESTED_CONDITIONS: dict[str, Any] = {"crm_status": [1]}


def _normalize_subsequence_conditions(
    conditions: dict[str, Any] | None,
) -> dict[str, tuple[str, ...]]:
    raw = conditions if conditions else DEFAULT_INTERESTED_CONDITIONS
    normalized: dict[str, tuple[str, ...]] = {}
    for key, value in sorted(raw.items()):
        key_str = str(key)
        if isinstance(value, list):
            normalized[key_str] = tuple(sorted(str(item) for item in value))
        else:
            normalized[key_str] = (str(value),)
    return normalized


def subsequence_conditions_equal(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> bool:
    """True when ``left`` matches all trigger keys in ``right``.

    Instantly stores default empty fields (``lead_activity``, ``reply_contains``) that we
    omit on create — compare only the keys we care about, not full dict equality.
    """
    if not isinstance(left, dict):
        return False
    target = right if right is not None else DEFAULT_INTERESTED_CONDITIONS
    left_norm = _normalize_subsequence_conditions(left)
    right_norm = _normalize_subsequence_conditions(target)
    return all(left_norm.get(key) == vals for key, vals in right_norm.items())


def find_subsequence(
    items: list[dict[str, Any]],
    *,
    name: str = "",
    conditions: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Match by name first, then by trigger conditions (Instantly allows one per condition set)."""
    needle = name.strip().lower()
    if needle:
        for item in items:
            if str(item.get("name") or "").strip().lower() == needle:
                return item
    target = conditions if conditions is not None else DEFAULT_INTERESTED_CONDITIONS
    for item in items:
        if subsequence_conditions_equal(item.get("conditions"), target):
            return item
    return None


def list_subsequences(api_key: str, campaign_id: str) -> list[dict[str, Any]]:
    client = InstantlyClient(api_key)
    suffix = f"?parent_campaign={campaign_id.strip()}&limit=100"
    page = client._fetch(f"/subsequences{suffix}", method="GET")
    return page.get("items") or [] if isinstance(page, dict) else []


def build_email_sequence_steps(
    emails: list[dict[str, str]],
    *,
    default_delay_days: int = 3,
) -> list[dict[str, Any]]:
    """Build Instantly sequence steps from [{subject, body}, ...]."""
    steps: list[dict[str, Any]] = []
    for idx, email in enumerate(emails):
        subject = str(email.get("subject") or "").strip()
        body = str(email.get("body") or "").strip()
        if not subject or not body:
            raise ValueError(f"Email step {idx + 1} needs subject and body")
        step: dict[str, Any] = {
            "type": "email",
            "delay": 0 if idx == 0 else default_delay_days,
            "variants": [{"subject": subject, "body": body}],
        }
        if idx == 0:
            step["pre_delay"] = 0
            step["pre_delay_unit"] = "minutes"
        steps.append(step)
    return steps


def patch_campaign_sequences(
    api_key: str,
    campaign_id: str,
    emails: list[dict[str, str]],
    *,
    default_delay_days: int = 3,
) -> dict[str, Any]:
    """PATCH campaign with cold-email sequence steps (stays draft until activated)."""
    client = InstantlyClient(api_key)
    steps = build_email_sequence_steps(emails, default_delay_days=default_delay_days)
    body = {"sequences": [{"steps": steps}]}
    data = client._fetch(
        f"/campaigns/{campaign_id.strip()}",
        method="PATCH",
        body=body,
    )
    if not isinstance(data, dict):
        raise RuntimeError(f"Instantly patch campaign returned unexpected payload: {data!r}")
    return data


def get_campaign(api_key: str, campaign_id: str) -> dict[str, Any]:
    client = InstantlyClient(api_key)
    data = client._fetch(f"/campaigns/{campaign_id.strip()}", method="GET")
    return data if isinstance(data, dict) else {}


def campaign_has_sequence_emails(api_key: str, campaign_id: str, min_steps: int = 2) -> bool:
    data = get_campaign(api_key, campaign_id)
    sequences = data.get("sequences") or []
    if not sequences or not isinstance(sequences, list):
        return False
    steps = sequences[0].get("steps") if isinstance(sequences[0], dict) else []
    if not isinstance(steps, list):
        return False
    count = 0
    for step in steps:
        if not isinstance(step, dict) or step.get("type") != "email":
            continue
        variants = step.get("variants") or []
        if variants and str(variants[0].get("body") or "").strip():
            count += 1
    return count >= min_steps


def create_subsequence(
    api_key: str,
    *,
    parent_campaign_id: str,
    name: str,
    emails: list[dict[str, str]] | None = None,
    conditions: dict[str, Any] | None = None,
    default_delay_days: int = 1,
) -> dict[str, Any]:
    client = InstantlyClient(api_key)
    if emails:
        steps = build_email_sequence_steps(emails, default_delay_days=default_delay_days)
    else:
        steps = build_email_sequence_steps(
            [{"subject": "Suite à votre intérêt", "body": "Bonjour,<br/><br/>Merci pour votre intérêt."}]
        )
    body: dict[str, Any] = {
        "parent_campaign": parent_campaign_id.strip(),
        "name": name,
        "conditions": conditions or DEFAULT_INTERESTED_CONDITIONS,
        "subsequence_schedule": DEFAULT_CAMPAIGN_SCHEDULE,
        "sequences": [{"steps": steps}],
    }
    data = client._fetch("/subsequences", method="POST", body=body)
    if not isinstance(data, dict) or not data.get("id"):
        raise RuntimeError(f"Instantly create subsequence returned no id: {data!r}")
    return data


def patch_subsequence_sequences(
    api_key: str,
    subsequence_id: str,
    emails: list[dict[str, str]],
    *,
    default_delay_days: int = 1,
) -> dict[str, Any]:
    client = InstantlyClient(api_key)
    steps = build_email_sequence_steps(emails, default_delay_days=default_delay_days)
    body = {"sequences": [{"steps": steps}]}
    data = client._fetch(
        f"/subsequences/{subsequence_id.strip()}",
        method="PATCH",
        body=body,
    )
    if not isinstance(data, dict):
        raise RuntimeError(f"Instantly patch subsequence returned unexpected payload: {data!r}")
    return data


def ensure_subsequence(
    api_key: str,
    *,
    parent_campaign_id: str,
    name: str = "Interested bypass",
    conditions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_conditions = conditions if conditions is not None else DEFAULT_INTERESTED_CONDITIONS
    existing_items = list_subsequences(api_key, parent_campaign_id)
    match = find_subsequence(existing_items, name=name, conditions=target_conditions)
    if match:
        return match
    try:
        return create_subsequence(
            api_key,
            parent_campaign_id=parent_campaign_id,
            name=name,
            conditions=target_conditions,
        )
    except RuntimeError as exc:
        if "same trigger conditions" not in str(exc).lower():
            raise
        refreshed = list_subsequences(api_key, parent_campaign_id)
        match = find_subsequence(refreshed, conditions=target_conditions)
        if match:
            return match
        if len(refreshed) == 1:
            return refreshed[0]
        raise


def ensure_subsequence_sequences(
    api_key: str,
    *,
    parent_campaign_id: str,
    name: str,
    emails: list[dict[str, str]],
    conditions: dict[str, Any] | None = None,
    default_delay_days: int = 1,
) -> dict[str, Any]:
    """Find or create Interested subsequence, then PATCH E1–E3 steps."""
    sub = ensure_subsequence(
        api_key,
        parent_campaign_id=parent_campaign_id,
        name=name,
        conditions=conditions,
    )
    sub_id = str(sub.get("id") or "").strip()
    if not sub_id:
        raise RuntimeError(f"Instantly subsequence has no id: {sub!r}")
    patched = patch_subsequence_sequences(
        api_key,
        sub_id,
        emails,
        default_delay_days=default_delay_days,
    )
    if isinstance(patched, dict) and patched.get("id"):
        return patched
    return {**sub, "id": sub_id}


def list_all_lead_lists(api_key: str) -> list[dict[str, Any]]:
    return InstantlyClient(api_key).list_all_lead_lists()


def list_all_campaigns(api_key: str) -> list[dict[str, Any]]:
    return InstantlyClient(api_key).list_all_campaigns()


def delete_lead_list(api_key: str, list_id: str) -> None:
    client = InstantlyClient(api_key)
    try:
        client._fetch(f"/lead-lists/{list_id.strip()}", method="DELETE")
    except RuntimeError as exc:
        if "404" not in str(exc):
            raise


def delete_campaign(api_key: str, campaign_id: str) -> None:
    client = InstantlyClient(api_key)
    try:
        client._fetch(f"/campaigns/{campaign_id.strip()}", method="DELETE")
    except RuntimeError as exc:
        if "404" not in str(exc):
            raise


def load_workspace_email_cache(
    *,
    list_ids: list[str] | None = None,
    campaign_ids: list[str] | None = None,
    max_age_s: int = WORKSPACE_CACHE_TTL_S,
    cache_path: str | None = None,
    allow_partial: bool = False,
) -> set[str] | None:
    entry = load_workspace_cache_entry(
        list_ids=list_ids,
        campaign_ids=campaign_ids,
        max_age_s=max_age_s,
        cache_path=cache_path,
        allow_partial=allow_partial,
    )
    if entry is None:
        return None
    if not allow_partial and not entry.get("complete"):
        return None
    if allow_partial and entry.get("complete"):
        return None
    emails = entry.get("emails")
    return set(emails) if isinstance(emails, set) else None


def load_workspace_cache_entry(
    *,
    list_ids: list[str] | None = None,
    campaign_ids: list[str] | None = None,
    max_age_s: int = WORKSPACE_CACHE_TTL_S,
    cache_path: str | None = None,
    allow_partial: bool = False,
) -> dict[str, Any] | None:
    path = cache_path or WORKSPACE_CACHE_PATH
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        saved_at = float(data.get("saved_at", 0))
        if saved_at <= 0 or time.time() - saved_at > max_age_s:
            return None
        complete = bool(data.get("complete", False))
        if complete and allow_partial:
            return None
        if not complete and not allow_partial:
            return None
        cached_lists = _normalize_scope_ids(data.get("list_ids"))
        cached_campaigns = _normalize_scope_ids(data.get("campaign_ids"))
        if cached_lists != _normalize_scope_ids(list_ids):
            return None
        if cached_campaigns != _normalize_scope_ids(campaign_ids):
            return None
        raw = data.get("emails") or []
        emails = {str(email).strip().lower() for email in raw if "@" in str(email)}
        completed_scopes = [
            str(scope).strip()
            for scope in (data.get("completed_scopes") or [])
            if str(scope).strip()
        ]
        return {
            "emails": emails,
            "complete": complete,
            "completed_scopes": completed_scopes,
        }
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def save_workspace_email_cache(
    emails: set[str],
    *,
    list_ids: list[str] | None = None,
    campaign_ids: list[str] | None = None,
    complete: bool = True,
    completed_scopes: list[str] | None = None,
    cache_path: str | None = None,
) -> None:
    path = cache_path or WORKSPACE_CACHE_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "saved_at": time.time(),
        "count": len(emails),
        "list_ids": _normalize_scope_ids(list_ids),
        "campaign_ids": _normalize_scope_ids(campaign_ids),
        "emails": sorted(emails),
        "complete": complete,
        "completed_scopes": _normalize_scope_ids(completed_scopes or []),
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)


def clear_workspace_email_cache(*, cache_path: str | None = None) -> None:
    path = cache_path or WORKSPACE_CACHE_PATH
    if os.path.isfile(path):
        os.remove(path)


def fetch_workspace_emails(
    api_key: str,
    *,
    list_ids: list[str] | None = None,
    campaign_ids: list[str] | None = None,
    on_progress: Callable[[int], None] | None = None,
    use_cache: bool = True,
    cache_path: str | None = None,
    log_cb: Callable[[str], None] | None = None,
) -> set[str]:
    norm_lists = _normalize_scope_ids(list_ids)
    norm_campaigns = _normalize_scope_ids(campaign_ids)

    if not norm_lists and not norm_campaigns:
        if log_cb:
            log_cb(
                "Instantly dedup: no INSTANTLY_DEDUP_* IDs configured — skipping local dedup."
            )
        return set()

    initial_emails: set[str] = set()
    completed_scopes: list[str] = []

    if use_cache:
        cached = load_workspace_email_cache(
            list_ids=norm_lists,
            campaign_ids=norm_campaigns,
            cache_path=cache_path,
        )
        if cached is not None:
            if on_progress:
                on_progress(len(cached))
            return cached

        partial = load_workspace_cache_entry(
            list_ids=norm_lists,
            campaign_ids=norm_campaigns,
            cache_path=cache_path,
            allow_partial=True,
        )
        if partial is not None:
            initial_emails = set(partial.get("emails") or set())
            completed_scopes = list(partial.get("completed_scopes") or [])
            if log_cb:
                log_cb(
                    f"Instantly dedup: resuming partial cache — "
                    f"{len(initial_emails)} email(s), "
                    f"{len(completed_scopes)} scope(s) already done"
                )
            if on_progress and initial_emails:
                on_progress(len(initial_emails))

    completed_scope_set = set(completed_scopes)

    def _checkpoint(emails: set[str]) -> None:
        save_workspace_email_cache(
            emails,
            list_ids=norm_lists,
            campaign_ids=norm_campaigns,
            complete=False,
            completed_scopes=completed_scopes,
            cache_path=cache_path,
        )

    def _scope_complete(scope_key: str) -> None:
        if scope_key not in completed_scopes:
            completed_scopes.append(scope_key)

    client = InstantlyClient(api_key)
    emails = client.fetch_dedup_emails(
        norm_lists,
        norm_campaigns,
        on_progress=on_progress,
        on_page=_checkpoint,
        on_scope_complete=_scope_complete,
        initial_emails=initial_emails,
        skip_scopes=completed_scope_set,
    )
    save_workspace_email_cache(
        emails,
        list_ids=norm_lists,
        campaign_ids=norm_campaigns,
        complete=True,
        completed_scopes=completed_scopes,
        cache_path=cache_path,
    )
    return emails


def _read_job_id(data: Any) -> str | None:
    if isinstance(data, dict):
        job_id = data.get("id")
        if isinstance(job_id, str) and job_id.strip():
            return job_id.strip()
    return None


def has_leads_in_list(api_key: str, list_id: str) -> bool:
    return _has_any_leads(InstantlyClient(api_key), {"list_id": list_id.strip()})


def has_leads_in_campaign(api_key: str, campaign_id: str) -> bool:
    return _has_any_leads(InstantlyClient(api_key), {"campaign": campaign_id.strip()})


def _has_any_leads(client: InstantlyClient, scope: dict[str, str]) -> bool:
    body: dict[str, Any] = {**scope, "limit": 1}
    page = client._fetch(
        "/leads/list",
        method="POST",
        body=body,
        timeout=_HTTP_TIMEOUT_LEADS_LIST,
    )
    items = page.get("items") or [] if isinstance(page, dict) else []
    return bool(items)


def _count_leads(client: InstantlyClient, scope: dict[str, str]) -> int:
    return sum(len(items) for items in _iter_lead_pages(client, scope))


def _iter_lead_pages(
    client: InstantlyClient, scope: dict[str, str]
) -> Iterator[list[dict[str, Any]]]:
    starting_after: str | None = None
    previous_cursor: str | None = None

    for _page in range(500):
        body: dict[str, Any] = {**scope, "limit": PAGE_SIZE}
        if starting_after:
            body["starting_after"] = starting_after

        page = client._fetch(
            "/leads/list",
            method="POST",
            body=body,
            timeout=_HTTP_TIMEOUT_LEADS_LIST,
        )
        items = page.get("items") or []
        if not items:
            break

        yield items
        next_cursor = page.get("next_starting_after")
        if not next_cursor:
            last_email = _read_email(items[-1])
            next_cursor = last_email or items[-1].get("id")

        if len(items) < PAGE_SIZE or not next_cursor:
            break

        next_cursor = str(next_cursor)
        if next_cursor == previous_cursor:
            break
        previous_cursor = next_cursor
        starting_after = next_cursor


def count_leads_in_list(api_key: str, list_id: str) -> int:
    return _count_leads(InstantlyClient(api_key), {"list_id": list_id.strip()})


def count_leads_in_campaign(api_key: str, campaign_id: str) -> int:
    return _count_leads(InstantlyClient(api_key), {"campaign": campaign_id.strip()})


def count_unique_emails_in_list_and_campaign(
    api_key: str, list_id: str, campaign_id: str
) -> int:
    """Distinct emails across list + campaign (provisioned leads move list → campaign)."""
    client = InstantlyClient(api_key)
    emails: set[str] = set()
    for scope in ({"list_id": list_id.strip()}, {"campaign": campaign_id.strip()}):
        for items in _iter_lead_pages(client, scope):
            for item in items:
                email = _read_email(item)
                if email:
                    emails.add(email)
    return len(emails)


def wait_for_background_job(
    api_key: str,
    job_id: str,
    *,
    poll_s: float = 3.0,
    timeout_s: float = 3600.0,
) -> None:
    client = InstantlyClient(api_key)
    started = time.time()
    while True:
        job = client._fetch(f"/background-jobs/{job_id}", method="GET")
        status = (job.get("status") or "").lower() if isinstance(job, dict) else ""
        if status == "success":
            return
        if status in ("failed", "cancelled"):
            raise RuntimeError(f"Background job {job_id} ended with status {status}")
        if time.time() - started > timeout_s:
            raise RuntimeError(f"Background job {job_id} timed out after {timeout_s}s")
        time.sleep(poll_s)


def bulk_delete_leads(
    api_key: str,
    *,
    list_id: str | None = None,
    campaign_id: str | None = None,
) -> str | None:
    payload: dict[str, str] = {}
    if list_id:
        payload["list_id"] = list_id.strip()
    if campaign_id:
        payload["campaign_id"] = campaign_id.strip()
    if not payload:
        raise ValueError("list_id or campaign_id required for bulk delete")

    client = InstantlyClient(api_key)
    result = client._fetch("/leads", method="DELETE", body=payload)
    return _read_job_id(result)


def _purge_leads(
    api_key: str,
    *,
    list_id: str | None = None,
    campaign_id: str | None = None,
    log_cb: Callable[[str], None] | None = None,
) -> int:
    label = f"list {list_id}" if list_id else f"campaign {campaign_id}"
    deleted_total = 0
    max_passes = 500

    for pass_num in range(1, max_passes + 1):
        before = (
            count_leads_in_list(api_key, list_id)
            if list_id
            else count_leads_in_campaign(api_key, campaign_id or "")
        )
        if before == 0:
            return deleted_total

        if log_cb:
            log_cb(f"Purge pass {pass_num}: {before} lead(s) remaining in {label}")

        job_id = bulk_delete_leads(
            api_key,
            list_id=list_id,
            campaign_id=campaign_id,
        )
        if job_id:
            wait_for_background_job(api_key, job_id)
        else:
            time.sleep(2)

        after = (
            count_leads_in_list(api_key, list_id)
            if list_id
            else count_leads_in_campaign(api_key, campaign_id or "")
        )
        deleted_total += max(before - after, 0)
        if after == 0:
            return deleted_total
        if after >= before:
            raise RuntimeError(
                f"Purge stalled for {label}: {before} before, {after} after pass {pass_num}"
            )
        time.sleep(0.8)

    remaining = (
        count_leads_in_list(api_key, list_id)
        if list_id
        else count_leads_in_campaign(api_key, campaign_id or "")
    )
    if remaining > 0:
        raise RuntimeError(f"{label} still has {remaining} leads after {max_passes} purge passes")
    return deleted_total


def purge_leads_from_list(
    api_key: str,
    list_id: str,
    *,
    log_cb: Callable[[str], None] | None = None,
) -> int:
    return _purge_leads(api_key, list_id=list_id, log_cb=log_cb)


def purge_leads_from_campaign(
    api_key: str,
    campaign_id: str,
    *,
    log_cb: Callable[[str], None] | None = None,
) -> int:
    return _purge_leads(api_key, campaign_id=campaign_id, log_cb=log_cb)


def get_remediation_counts(
    api_key: str,
    list_id: str,
    campaign_id: str,
) -> dict[str, int]:
    return {
        "list_leads": count_leads_in_list(api_key, list_id),
        "campaign_leads": count_leads_in_campaign(api_key, campaign_id),
    }


def csv_push_stats(csv_path: str) -> dict[str, int]:
    """Count valid CSV emails ready to push (Instantly handles duplicate skip)."""
    if not os.path.isfile(csv_path):
        return {"total": 0, "pending": 0}
    df = pd.read_csv(csv_path)
    if df.empty or "Email" not in df.columns:
        return {"total": 0, "pending": 0}
    emails = {
        _normalize_email(str(row))
        for row in df["Email"].dropna()
        if "@" in str(row)
    }
    total = len(emails)
    return {"total": total, "pending": total}


def _lead_payload(row: dict[str, str], list_id: str) -> dict[str, Any]:
    """Instantly lead body. Only core fields plus phone/category/status."""
    from shared.central_leads import (
        category_for_preset,
        core_instantly_custom_variables,
        normalize_phone,
    )

    company = (row.get("Company") or "").strip()
    first_name = (row.get("FirstName") or "").strip() or (company.split()[0] if company else "")
    last_name = (row.get("LastName") or "").strip()
    phone = normalize_phone(row.get("Phone") or row.get("phone"))
    preset = (row.get("Preset") or "").strip()
    category = (row.get("LeadCategory") or "").strip()
    if not category and preset:
        category = category_for_preset(preset)
    custom_variables = core_instantly_custom_variables(
        {},
        phone=phone,
        category=category,
        status="uncleaned",
    )
    payload: dict[str, Any] = {
        "email": row["Email"],
        "first_name": first_name,
        "last_name": last_name,
        "company_name": company,
        "website": row.get("Website") or "",
        "list_id": list_id,
    }
    if phone:
        payload["phone"] = phone
    if custom_variables:
        payload["custom_variables"] = custom_variables
    return payload


def _parse_add_response(data: Any, batch_size: int) -> dict[str, int]:
    if not isinstance(data, dict):
        return {
            "pushed": 0,
            "skipped_duplicate": 0,
            "failed": batch_size,
        }
    pushed = int(data.get("leads_uploaded") or 0)
    skipped = int(data.get("skipped_count") or 0)
    failed = max(batch_size - pushed - skipped, 0)
    return {
        "pushed": pushed,
        "skipped_duplicate": skipped,
        "failed": failed,
    }


async def _upload_batch(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    list_id: str,
    batch: list[dict[str, Any]],
    skip_if_in_campaign: bool = True,
    skip_if_in_list: bool = True,
    log_cb: Callable[[str], None] | None = None,
    max_attempts: int = 3,
) -> dict[str, int]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    batch_size = len(batch)
    last_stats = {"pushed": 0, "skipped_duplicate": 0, "failed": batch_size}

    for attempt in range(1, max_attempts + 1):
        try:
            response = await client.post(
                f"{INSTANTLY_API_BASE}/leads/add",
                headers=headers,
                json={
                    "list_id": list_id.strip(),
                    "leads": batch,
                    "skip_if_in_campaign": skip_if_in_campaign,
                    "skip_if_in_list": skip_if_in_list,
                },
            )
            if response.status_code in (200, 201):
                data = response.json() if response.text else {}
                stats = _parse_add_response(data, batch_size)
                last_stats = stats
                if stats["failed"] <= 0 or attempt >= max_attempts:
                    if log_cb:
                        log_cb(
                            f"Instantly batch: {stats['pushed']} uploaded, "
                            f"{stats['skipped_duplicate']} skipped (duplicate)"
                            + (f", {stats['failed']} failed" if stats["failed"] else "")
                        )
                    return stats
                if log_cb:
                    log_cb(
                        f"Instantly batch partial fail ({stats['failed']}/{batch_size}) "
                        f"— retry {attempt}/{max_attempts}"
                    )
                await asyncio.sleep(_BACKOFF_BASE**attempt)
                continue
            if log_cb:
                log_cb(
                    f"Instantly batch failed ({response.status_code}): "
                    f"{response.text[:200]}"
                )
        except Exception as exc:
            if log_cb:
                log_cb(f"Instantly batch error: {exc}")
        if attempt < max_attempts:
            await asyncio.sleep(_BACKOFF_BASE**attempt)

    return last_stats


async def push_leads_to_list(
    api_key: str,
    list_id: str,
    leads: list[dict[str, str]],
    *,
    skip_if_in_campaign: bool = True,
    skip_if_in_list: bool = True,
    log_cb: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Upload leads to a list; Instantly skips duplicates via skip_if_in_* flags."""
    if not api_key or not list_id or not leads:
        return {
            "attempted": 0,
            "pushed": 0,
            "skipped_duplicate": 0,
            "failed": 0,
        }

    to_upload: list[dict[str, Any]] = []
    for row in leads:
        email = _normalize_email(row.get("Email", ""))
        if not email or "@" not in email:
            continue
        to_upload.append(_lead_payload({**row, "Email": email}, list_id))

    attempted = len(to_upload)
    if log_cb:
        log_cb(f"Instantly upload: {attempted} candidate(s)")

    if not to_upload:
        return {
            "attempted": 0,
            "pushed": 0,
            "skipped_duplicate": 0,
            "failed": 0,
        }

    batches = [
        to_upload[start : start + _BULK_BATCH_SIZE]
        for start in range(0, len(to_upload), _BULK_BATCH_SIZE)
    ]

    pushed = 0
    skipped = 0
    failed = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        results = await asyncio.gather(
            *[
                _upload_batch(
                    client,
                    api_key=api_key,
                    list_id=list_id,
                    batch=batch,
                    skip_if_in_campaign=skip_if_in_campaign,
                    skip_if_in_list=skip_if_in_list,
                    log_cb=log_cb,
                )
                for batch in batches
            ]
        )

    for stats in results:
        pushed += stats["pushed"]
        skipped += stats["skipped_duplicate"]
        failed += stats["failed"]

    if log_cb:
        log_cb(
            f"Instantly done: {pushed} uploaded, "
            f"{skipped} skipped (duplicate), {failed} failed"
        )

    return {
        "attempted": attempted,
        "pushed": pushed,
        "skipped_duplicate": skipped,
        "failed": failed,
    }


async def push_csv_to_instantly(
    csv_path: str,
    api_key: str,
    list_id: str,
    *,
    log_cb: Callable[[str], None] | None = None,
    provision_config: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Push all valid CSV rows to Instantly (native duplicate skip, no local state)."""
    if not os.path.isfile(csv_path):
        if log_cb:
            log_cb(f"CSV not found: {csv_path}")
        return {
            "attempted": 0,
            "pushed": 0,
            "skipped_duplicate": 0,
            "failed": 0,
        }

    df = pd.read_csv(csv_path)
    missing = [c for c in _REQUIRED_CSV_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV missing columns: {', '.join(missing)}")

    rows: list[dict[str, str]] = []
    for _, row in df.iterrows():
        email = _normalize_email(str(row.get("Email", "")))
        if not email or "@" not in email:
            continue
        rows.append(
            {
                "Email": email,
                "Company": str(row.get("Company", "") or "").strip(),
                "Website": str(row.get("Website", "") or "").strip(),
                "Service": str(row.get("Service", "") or "").strip(),
                "Niche": str(row.get("Niche", "") or "").strip(),
                "Subniche": str(row.get("Subniche", "") or "").strip(),
                "City": str(row.get("City", "") or "").strip(),
                "Type": str(row.get("Type", "") or "").strip(),
                "Category": str(row.get("Category", "") or "").strip(),
                "Subtypes": str(row.get("Subtypes", "") or "").strip(),
            }
        )

    if log_cb:
        log_cb(f"CSV: {len(df)} row(s), {len(rows)} to push")

    if not rows:
        return {
            "attempted": 0,
            "pushed": 0,
            "skipped_duplicate": 0,
            "failed": 0,
        }

    push_stats = await push_leads_to_list(api_key, list_id, rows, log_cb=log_cb)

    if (
        provision_config
        and provision_config.get("INSTANTLY_PROVISION_LINKS")
        and int(push_stats.get("pushed") or 0) > 0
    ):
        batch_emails = [
            str(row.get("Email") or "").strip().lower()
            for row in rows
            if "@" in str(row.get("Email") or "")
        ]
        if batch_emails:
            from link_provision_client import provision_leads_after_push

            await provision_leads_after_push(
                batch_emails,
                config=provision_config,
                log_cb=log_cb or (lambda _message: None),
            )

    _repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    from shared.mev_export import sync_mev_csv_from_leads_csv

    mev_count = sync_mev_csv_from_leads_csv(csv_path)
    if log_cb and mev_count:
        log_cb(f"MEV export: {mev_count} email(s) → mev_emails.csv")

    return push_stats
