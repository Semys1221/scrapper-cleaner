"""Shared Instantly API v2 client (CRM, streamlit_clean, etc.)."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ROOT_ENV = _REPO_ROOT / ".env"

if _ROOT_ENV.is_file():
    load_dotenv(_ROOT_ENV)
load_dotenv()

INSTANTLY_API_BASE = "https://api.instantly.ai/api/v2"
PAGE_SIZE = 100
MAX_RETRIES = 5
_HTTP_TIMEOUT = (10, 60)
_BULK_BATCH_SIZE = 1000
_BULK_DELETE_LIMIT = 10000


def get_api_key() -> str:
    return os.getenv("INSTANTLY_API_KEY", "").strip()


def _instantly_custom_value(value: Any) -> Any | None:
    """Keep scalar custom-variable values. Instantly rejects objects and arrays."""
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


class InstantlyClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session = requests.Session()

    def _fetch(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        attempt: int = 0,
    ) -> Any:
        url = f"{INSTANTLY_API_BASE}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        response = self.session.request(
            method,
            url,
            headers=headers,
            json=body,
            timeout=_HTTP_TIMEOUT,
        )

        text = response.text or ""
        data: Any = None
        if text:
            try:
                data = response.json()
            except ValueError:
                data = text

        if response.status_code == 429 and attempt < MAX_RETRIES:
            retry_after = response.headers.get("Retry-After", "65")
            try:
                wait_s = int(retry_after)
            except ValueError:
                wait_s = 65
            time.sleep(max(wait_s, 1))
            return self._fetch(endpoint, method=method, body=body, attempt=attempt + 1)

        if not response.ok:
            detail = data if isinstance(data, str) else json.dumps(data)
            raise RuntimeError(
                f"Instantly API {response.status_code} on {endpoint}: {detail}"
            )

        return data

    def get_lead_list(self, list_id: str) -> dict[str, Any]:
        return self._fetch(f"/lead-lists/{list_id}")

    def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        return self._fetch(f"/campaigns/{campaign_id}")

    def _paginate_items(self, build_path: Callable[[str | None], str]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        starting_after: str | None = None

        while True:
            page = self._fetch(build_path(starting_after), method="GET")
            page_items = page.get("items") or []
            items.extend(page_items)

            next_cursor = page.get("next_starting_after")
            if not next_cursor and page_items:
                next_cursor = page_items[-1].get("id")

            if not next_cursor or len(page_items) < PAGE_SIZE:
                break

            starting_after = str(next_cursor)

        return items

    def list_all_lead_lists(self) -> list[dict[str, Any]]:
        return self._paginate_items(
            lambda starting_after: self._build_collection_path("/lead-lists", starting_after)
        )

    def list_all_campaigns(self) -> list[dict[str, Any]]:
        return self._paginate_items(
            lambda starting_after: self._build_collection_path("/campaigns", starting_after)
        )

    @staticmethod
    def _build_collection_path(base: str, starting_after: str | None) -> str:
        params = f"limit={PAGE_SIZE}"
        if starting_after:
            params += f"&starting_after={starting_after}"
        return f"{base}?{params}"

    def count_leads_in_list(self, list_id: str) -> int:
        return self._count_leads(list_id=list_id)

    def count_leads_in_campaign(self, campaign_id: str) -> int:
        return self._count_leads(campaign=campaign_id.strip())

    def _count_leads(self, **scope: str) -> int:
        total = 0
        starting_after: str | None = None
        previous_cursor: str | None = None
        expected_campaign = scope.get("campaign")

        while True:
            body: dict[str, Any] = {**scope, "limit": PAGE_SIZE}
            if starting_after:
                body["starting_after"] = starting_after

            try:
                page = self._fetch("/leads/list", method="POST", body=body)
            except RuntimeError as exc:
                if "404" in str(exc):
                    return 0
                raise

            items = page.get("items") or []
            if not items:
                break

            if expected_campaign:
                total += sum(
                    1
                    for item in items
                    if not item.get("campaign")
                    or str(item.get("campaign")) == expected_campaign
                )
            else:
                total += len(items)

            next_cursor = page.get("next_starting_after")
            if not next_cursor:
                next_cursor = items[-1].get("id")
            if not next_cursor or len(items) < PAGE_SIZE:
                break
            next_cursor = str(next_cursor)
            if next_cursor == previous_cursor:
                break
            previous_cursor = next_cursor
            starting_after = next_cursor

        return total

    def _paginate_leads_list(
        self,
        *,
        scope: dict[str, str],
        max_leads: int | None = None,
        max_pages: int = 10000,
        on_progress: Callable[[int, int], None] | None = None,
        expected_campaign: str | None = None,
    ) -> list[dict[str, Any]]:
        leads: list[dict[str, Any]] = []
        starting_after: str | None = None
        previous_cursor: str | None = None
        pages_fetched = 0
        campaign_id = (expected_campaign or scope.get("campaign") or "").strip()

        while pages_fetched < max_pages:
            body: dict[str, Any] = {**scope, "limit": PAGE_SIZE}
            if starting_after:
                body["starting_after"] = starting_after

            try:
                page = self._fetch("/leads/list", method="POST", body=body)
            except RuntimeError as exc:
                if "404" in str(exc):
                    return leads
                raise

            items = page.get("items") or []
            if not items:
                break

            pages_fetched += 1

            for item in items:
                if campaign_id:
                    item_campaign = item.get("campaign")
                    if item_campaign and str(item_campaign) != campaign_id:
                        continue
                leads.append(item)
                if on_progress:
                    on_progress(len(leads), pages_fetched)
                if max_leads is not None and len(leads) >= max_leads:
                    return leads

            next_cursor = page.get("next_starting_after")
            if not next_cursor:
                next_cursor = items[-1].get("id")
            if not next_cursor or len(items) < PAGE_SIZE:
                break
            next_cursor = str(next_cursor)
            if next_cursor == previous_cursor:
                break
            previous_cursor = next_cursor
            starting_after = next_cursor

        return leads

    def fetch_leads_from_campaign(
        self,
        campaign_id: str,
        *,
        max_leads: int | None = 500,
        max_pages: int = 100,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[dict[str, Any]]:
        cid = campaign_id.strip()
        return self._paginate_leads_list(
            scope={"campaign": cid},
            max_leads=max_leads,
            max_pages=max_pages,
            on_progress=on_progress,
            expected_campaign=cid,
        )

    def fetch_leads_from_list(
        self,
        list_id: str,
        max_leads: int | None = None,
        on_progress: Callable[[int], None] | None = None,
    ) -> list[dict[str, Any]]:
        def _progress(count: int, _pages: int) -> None:
            if on_progress:
                on_progress(count)

        return self._paginate_leads_list(
            scope={"list_id": list_id.strip()},
            max_leads=max_leads,
            on_progress=_progress if on_progress else None,
        )

    def get_lead(self, lead_id: str) -> dict[str, Any]:
        data = self._fetch(f"/leads/{lead_id.strip()}")
        return data if isinstance(data, dict) else {}

    def find_lead_by_email(self, lead_email: str) -> dict[str, Any] | None:
        normalized = lead_email.strip().lower()
        if not normalized or "@" not in normalized:
            return None

        searched = self._fetch(
            "/leads/list",
            method="POST",
            body={"contacts": [normalized], "limit": 20},
        )
        items = searched.get("items") or [] if isinstance(searched, dict) else []
        for item in items:
            email = str(item.get("email") or "").strip().lower()
            if email == normalized:
                return item
        return None

    def find_lead_by_email_in_campaign(
        self,
        campaign_id: str,
        lead_email: str,
        *,
        search_only: bool = False,
    ) -> dict[str, Any] | None:
        normalized = lead_email.strip().lower()
        campaign = campaign_id.strip()

        searched = self._fetch(
            "/leads/list",
            method="POST",
            body={"campaign": campaign, "search": normalized, "limit": 20},
        )
        items = searched.get("items") or [] if isinstance(searched, dict) else []
        for item in items:
            email = str(item.get("email") or "").strip().lower()
            if email == normalized:
                return item

        if search_only:
            return None

        starting_after: str | None = None
        while True:
            body: dict[str, Any] = {"campaign": campaign, "limit": 100}
            if starting_after:
                body["starting_after"] = starting_after
            page = self._fetch("/leads/list", method="POST", body=body)
            page_items = page.get("items") or [] if isinstance(page, dict) else []
            for item in page_items:
                email = str(item.get("email") or "").strip().lower()
                if email == normalized:
                    return item
            next_cursor = page.get("next_starting_after") if isinstance(page, dict) else None
            if not next_cursor and page_items:
                next_cursor = page_items[-1].get("id")
            if not next_cursor or len(page_items) < 100:
                break
            starting_after = str(next_cursor)
        return None

    @staticmethod
    def lead_custom_variables(lead: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        payload = lead.get("payload")
        if isinstance(payload, dict):
            merged.update(payload)
        custom = lead.get("custom_variables")
        if isinstance(custom, dict):
            merged.update(custom)
        return merged

    def patch_lead_custom_variables(
        self,
        lead_id: str,
        custom_variables: dict[str, Any],
    ) -> None:
        self._fetch(
            f"/leads/{lead_id.strip()}",
            method="PATCH",
            body={"custom_variables": custom_variables},
        )

    def merge_lead_custom_variables(
        self,
        lead_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """PATCH custom_variables without wiping keys already stored on the lead.

        Instantly's PATCH /api/v2/leads/{id} replaces the whole custom_variables
        object (it is not a key merge). Read the lead first, overlay the update,
        and send the combined map so values such as city and siret stay.
        """
        lead = self.get_lead(lead_id)
        merged: dict[str, Any] = {}
        for source in (lead.get("payload"), lead.get("custom_variables")):
            if not isinstance(source, dict):
                continue
            for key, value in source.items():
                coerced = _instantly_custom_value(value)
                if coerced is None:
                    continue
                merged[str(key)] = coerced
        for key, value in updates.items():
            coerced = _instantly_custom_value(value)
            if coerced is None:
                continue
            merged[str(key)] = coerced
        self.patch_lead_custom_variables(lead_id, merged)
        return merged

    def replace_lead_custom_variables(
        self,
        lead_id: str,
        custom_variables: dict[str, str],
    ) -> None:
        """Backward-compatible name. Merges into the lead instead of wiping it."""
        self.merge_lead_custom_variables(lead_id, custom_variables)

    def patch_leads_custom_variables_parallel(
        self,
        items: list[tuple[str, dict[str, str]]],
        *,
        max_workers: int = 8,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]:
        """PATCH custom_variables for many leads concurrently (1 HTTP call each)."""
        if not items:
            return {"patched": 0, "failed": 0, "errors": []}

        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        api_key = self.api_key
        workers = max(1, min(max_workers, len(items), 16))
        patched = 0
        failed = 0
        errors: list[str] = []
        lock = threading.Lock()
        completed = 0
        total = len(items)

        def _patch_one(item: tuple[str, dict[str, str]]) -> None:
            lead_id, custom_variables = item
            worker = InstantlyClient(api_key)
            worker.merge_lead_custom_variables(lead_id, custom_variables)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_patch_one, item): item for item in items}
            for future in as_completed(futures):
                lead_id, _ = futures[future]
                try:
                    future.result()
                    with lock:
                        patched += 1
                except Exception as exc:
                    with lock:
                        failed += 1
                        errors.append(f"Instantly PATCH failed for {lead_id}: {exc}")
                with lock:
                    completed += 1
                    if on_progress:
                        on_progress(completed, total)

        return {"patched": patched, "failed": failed, "errors": errors}

    def push_leads_batch(
        self,
        *,
        campaign_id: str,
        leads: list[dict[str, Any]],
        cleaned: bool = False,
    ) -> dict[str, int]:
        if not leads:
            return {"pushed": 0, "skipped_duplicate": 0, "failed": 0}
        from shared.central_leads import refuse_uncleaned_instantly_push

        refuse_uncleaned_instantly_push(cleaned=cleaned)

        data = self._fetch(
            "/leads/add",
            method="POST",
            body={
                "campaign_id": campaign_id.strip(),
                "leads": leads,
                # Leads cleaned from an Instantly list still exist in that list;
                # workspace-level skip would block the entire push to campaign.
                "skip_if_in_workspace": False,
                "skip_if_in_campaign": True,
                "skip_if_in_list": False,
            },
        )

        if not isinstance(data, dict):
            return {"pushed": 0, "skipped_duplicate": 0, "failed": len(leads)}

        pushed = int(data.get("leads_uploaded") or 0)
        skipped = int(data.get("skipped_count") or 0)
        failed = max(len(leads) - pushed - skipped, 0)
        return {"pushed": pushed, "skipped_duplicate": skipped, "failed": failed}

    def push_leads_to_campaign(
        self,
        *,
        campaign_id: str,
        leads: list[dict[str, Any]],
        cleaned: bool = False,
    ) -> dict[str, int]:
        """CRM-compatible batch push (list of lead dicts)."""
        return self.push_leads_batch(campaign_id=campaign_id, leads=leads, cleaned=cleaned)

    def fetch_unibox_replies(self, *, max_items: int = 200) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        starting_after: str | None = None
        seen: set[str] = set()

        while len(items) < max_items:
            params = f"email_type=received&limit={PAGE_SIZE}"
            if starting_after:
                params += f"&starting_after={starting_after}"
            try:
                page = self._fetch(f"/emails?{params}", method="GET")
            except RuntimeError:
                break
            page_items = page.get("items") or [] if isinstance(page, dict) else []
            if not page_items:
                break
            for item in page_items:
                email = _read_str(item.get("lead")) or ""
                if not email:
                    email = _read_str(item.get("from_address_email")) or ""
                key = email.lower() if email else str(item.get("id") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                items.append(
                    {
                        "id": item.get("id"),
                        "email": email.lower() if email else "",
                        "subject": item.get("subject"),
                        "timestamp": item.get("timestamp_email")
                        or item.get("timestamp_created"),
                    }
                )
                if len(items) >= max_items:
                    break
            next_cursor = page.get("next_starting_after") or page_items[-1].get("id")
            if not next_cursor or len(page_items) < PAGE_SIZE:
                break
            starting_after = str(next_cursor)

        return items

    def list_campaign_emails(
        self,
        *,
        campaign_id: str,
        email_type: str,
        max_items: int = 500,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        starting_after: str | None = None
        campaign = campaign_id.strip()

        while len(items) < max_items:
            params = f"campaign_id={campaign}&email_type={email_type}&limit={PAGE_SIZE}"
            if starting_after:
                params += f"&starting_after={starting_after}"
            try:
                page = self._fetch(f"/emails?{params}", method="GET")
            except RuntimeError:
                break
            page_items = page.get("items") or [] if isinstance(page, dict) else []
            if not page_items:
                break
            items.extend(page_items)
            if len(items) >= max_items:
                items = items[:max_items]
                break
            next_cursor = page.get("next_starting_after") if isinstance(page, dict) else None
            if not next_cursor:
                next_cursor = page_items[-1].get("id")
            if not next_cursor or len(page_items) < PAGE_SIZE:
                break
            starting_after = str(next_cursor)

        return items

    def list_emails(
        self,
        *,
        search: str | None = None,
        campaign_id: str | None = None,
        email_type: str | None = None,
        latest_of_thread: bool = False,
        preview_only: bool | None = None,
        sort_order: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        params = [f"limit={limit}"]
        if search:
            params.append(f"search={search}")
        if campaign_id:
            params.append(f"campaign_id={campaign_id.strip()}")
        if email_type:
            params.append(f"email_type={email_type}")
        if latest_of_thread:
            params.append("latest_of_thread=true")
        if preview_only is not None:
            params.append(f"preview_only={'true' if preview_only else 'false'}")
        if sort_order:
            params.append(f"sort_order={sort_order}")
        page = self._fetch(f"/emails?{'&'.join(params)}", method="GET")
        return page.get("items") or [] if isinstance(page, dict) else []

    def list_campaign_latest_threads(
        self,
        *,
        campaign_id: str,
        max_items: int = 200,
        preview_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Paginate latest message per thread for a campaign (Unibox pending scan)."""
        items: list[dict[str, Any]] = []
        starting_after: str | None = None
        campaign = campaign_id.strip()

        while len(items) < max_items:
            params = [
                f"campaign_id={campaign}",
                "latest_of_thread=true",
                f"limit={PAGE_SIZE}",
                "sort_order=desc",
            ]
            if preview_only:
                params.append("preview_only=true")
            if starting_after:
                params.append(f"starting_after={starting_after}")
            try:
                page = self._fetch(f"/emails?{'&'.join(params)}", method="GET")
            except RuntimeError:
                break
            page_items = page.get("items") or [] if isinstance(page, dict) else []
            if not page_items:
                break
            items.extend(page_items)
            if len(items) >= max_items:
                items = items[:max_items]
                break
            next_cursor = page.get("next_starting_after") if isinstance(page, dict) else None
            if not next_cursor:
                next_cursor = page_items[-1].get("id")
            if not next_cursor or len(page_items) < PAGE_SIZE:
                break
            starting_after = str(next_cursor)

        return items

    def get_email(self, email_id: str) -> dict[str, Any] | None:
        try:
            data = self._fetch(f"/emails/{email_id.strip()}", method="GET")
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def reply_to_email(
        self,
        *,
        eaccount: str,
        reply_to_uuid: str,
        subject: str,
        html: str,
    ) -> Any:
        return self._fetch(
            "/emails/reply",
            method="POST",
            body={
                "eaccount": eaccount.strip(),
                "reply_to_uuid": reply_to_uuid.strip(),
                "subject": subject,
                "body": {"html": html},
            },
        )

    def remove_lead_from_subsequence(self, lead_id: str) -> Any:
        return self._fetch(
            "/leads/subsequence/remove",
            method="POST",
            body={"id": lead_id.strip()},
        )

    def update_interest_status(
        self,
        *,
        lead_email: str,
        interest_value: int | None,
        campaign_id: str | None = None,
        disable_auto_interest: bool = False,
    ) -> Any:
        body: dict[str, Any] = {
            "lead_email": lead_email.strip(),
            "interest_value": interest_value,
        }
        if campaign_id:
            body["campaign_id"] = campaign_id.strip()
        if disable_auto_interest:
            body["disable_auto_interest"] = True
        return self._fetch("/leads/update-interest-status", method="POST", body=body)

    def list_webhooks(self) -> list[dict[str, Any]]:
        return self._paginate_items(
            lambda starting_after: self._build_collection_path("/webhooks", starting_after)
        )

    def create_webhook(
        self,
        *,
        target_hook_url: str,
        event_type: str,
        name: str | None = None,
        campaign: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "target_hook_url": target_hook_url.strip(),
            "event_type": event_type,
        }
        if name:
            body["name"] = name
        if campaign:
            body["campaign"] = campaign.strip()
        if headers:
            body["headers"] = headers
        data = self._fetch("/webhooks", method="POST", body=body)
        return data if isinstance(data, dict) else {}

    def patch_webhook(
        self,
        webhook_id: str,
        *,
        headers: dict[str, str] | None = None,
        name: str | None = None,
        target_hook_url: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if headers is not None:
            body["headers"] = headers
        if name is not None:
            body["name"] = name
        if target_hook_url is not None:
            body["target_hook_url"] = target_hook_url.strip()
        if not body:
            raise ValueError("patch_webhook requires at least one field")
        data = self._fetch(f"/webhooks/{webhook_id.strip()}", method="PATCH", body=body)
        return data if isinstance(data, dict) else {}

    def resume_webhook(self, webhook_id: str) -> dict[str, Any]:
        data = self._fetch(f"/webhooks/{webhook_id.strip()}/resume", method="POST")
        return data if isinstance(data, dict) else {}

    def delete_webhook(self, webhook_id: str) -> None:
        self._fetch(f"/webhooks/{webhook_id.strip()}", method="DELETE")

    def list_subsequences(self, campaign_id: str | None = None) -> list[dict[str, Any]]:
        suffix = f"?parent_campaign={campaign_id.strip()}&limit=100" if campaign_id else "?limit=100"
        page = self._fetch(f"/subsequences{suffix}", method="GET")
        return page.get("items") or [] if isinstance(page, dict) else []

    def list_leads_by_interest_filter(
        self,
        *,
        campaign_id: str,
        interest_filter: str,
        max_leads: int = 500,
    ) -> list[dict[str, Any]]:
        leads: list[dict[str, Any]] = []
        starting_after: str | None = None

        while len(leads) < max_leads:
            body: dict[str, Any] = {
                "campaign": campaign_id.strip(),
                "filter": interest_filter,
                "limit": min(100, max_leads - len(leads)),
            }
            if starting_after:
                body["starting_after"] = starting_after

            page = self._fetch("/leads/list", method="POST", body=body)
            items = page.get("items") or [] if isinstance(page, dict) else []
            if not items:
                break

            leads.extend(items)
            if len(leads) >= max_leads:
                break

            next_cursor = page.get("next_starting_after") if isinstance(page, dict) else None
            if not next_cursor and items:
                next_cursor = items[-1].get("id")
            if not next_cursor or len(items) < body["limit"]:
                break
            starting_after = str(next_cursor)

        return leads[:max_leads]


def lead_custom_var(lead: dict[str, Any], key: str) -> str | None:
    """Read Instantly lead custom variable from payload or top-level fields."""
    candidates: list[dict[str, Any]] = []
    payload = lead.get("payload")
    if isinstance(payload, dict):
        candidates.append(payload)
    custom = lead.get("custom_variables")
    if isinstance(custom, dict):
        candidates.append(custom)

    for source in candidates:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    top = lead.get(key)
    if isinstance(top, str) and top.strip():
        return top.strip()
    return None


FILTER_LEAD_INTERESTED = "FILTER_LEAD_INTERESTED"
FILTER_LEAD_NOT_INTERESTED = "FILTER_LEAD_NOT_INTERESTED"
FILTER_LEAD_NO_SHOW = "FILTER_LEAD_NO_SHOW"

_client: InstantlyClient | None = None


def _get_client() -> InstantlyClient:
    global _client
    api_key = get_api_key()
    if not api_key:
        raise ValueError("INSTANTLY_API_KEY is not set")
    if _client is None or _client.api_key != api_key:
        _client = InstantlyClient(api_key)
    return _client


def get_lead_list(list_id: str) -> dict[str, Any]:
    return _get_client().get_lead_list(list_id.strip())


def get_campaign(campaign_id: str) -> dict[str, Any]:
    return _get_client().get_campaign(campaign_id.strip())


def list_all_lead_lists() -> list[dict[str, Any]]:
    return _get_client().list_all_lead_lists()


def list_all_campaigns() -> list[dict[str, Any]]:
    return _get_client().list_all_campaigns()


def format_resource_label(name: str | None, resource_id: str) -> str:
    display_name = (name or "").strip() or "(unnamed)"
    short_id = resource_id[:8]
    return f"{display_name} ({short_id}…)"


def count_leads_in_list(list_id: str) -> int:
    return _get_client().count_leads_in_list(list_id.strip())


def count_leads_in_campaign(campaign_id: str) -> int:
    return _get_client().count_leads_in_campaign(campaign_id.strip())


def _read_job_id(data: Any) -> str | None:
    if isinstance(data, dict):
        job_id = data.get("id")
        if isinstance(job_id, str) and job_id.strip():
            return job_id.strip()
    return None


def _read_delete_count(data: Any) -> int | None:
    if isinstance(data, dict):
        count = data.get("count")
        if isinstance(count, int):
            return count
    return None


@dataclass(frozen=True)
class BulkDeleteResult:
    job_id: str | None = None
    count: int | None = None


def wait_for_background_job(
    job_id: str,
    *,
    poll_s: float = 3.0,
    timeout_s: float = 3600.0,
    log_cb: Callable[[str], None] | None = None,
) -> None:
    client = _get_client()
    started = time.time()
    last_progress: int | None = None
    while True:
        job = client._fetch(
            f"/background-jobs/{job_id}?data_fields=success_count,total_to_process",
            method="GET",
        )
        status = (job.get("status") or "").lower() if isinstance(job, dict) else ""
        if log_cb and isinstance(job, dict):
            data = job.get("data") or {}
            progress = job.get("progress")
            success_count = data.get("success_count") if isinstance(data, dict) else None
            total_to_process = data.get("total_to_process") if isinstance(data, dict) else None
            if isinstance(progress, (int, float)) and int(progress) != last_progress:
                last_progress = int(progress)
                detail = f"{success_count}/{total_to_process}" if success_count is not None else ""
                suffix = f" ({detail})" if detail else ""
                log_cb(f"Background job {job_id}: {last_progress}%{suffix}")
        if status == "success":
            return
        if status in ("failed", "cancelled"):
            raise RuntimeError(f"Background job {job_id} ended with status {status}")
        if time.time() - started > timeout_s:
            raise RuntimeError(f"Background job {job_id} timed out after {timeout_s}s")
        time.sleep(poll_s)


def bulk_delete_leads(
    *,
    list_id: str | None = None,
    campaign_id: str | None = None,
    limit: int | None = _BULK_DELETE_LIMIT,
) -> BulkDeleteResult:
    payload: dict[str, Any] = {}
    if list_id:
        payload["list_id"] = list_id.strip()
    if campaign_id:
        payload["campaign_id"] = campaign_id.strip()
    if not payload:
        raise ValueError("list_id or campaign_id required for bulk delete")
    if limit is not None:
        payload["limit"] = limit

    result = _get_client()._fetch("/leads", method="DELETE", body=payload)
    return BulkDeleteResult(
        job_id=_read_job_id(result),
        count=_read_delete_count(result),
    )


def _purge_leads(
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
            count_leads_in_list(list_id or "")
            if list_id
            else count_leads_in_campaign(campaign_id or "")
        )
        if before == 0:
            return deleted_total

        if log_cb:
            log_cb(
                f"Purge pass {pass_num}: deleting up to {_BULK_DELETE_LIMIT} of "
                f"{before} lead(s) in {label}"
            )

        delete_result = bulk_delete_leads(
            list_id=list_id,
            campaign_id=campaign_id,
            limit=_BULK_DELETE_LIMIT,
        )
        if delete_result.job_id:
            wait_for_background_job(delete_result.job_id, log_cb=log_cb)
        elif delete_result.count is None:
            time.sleep(2)

        after = (
            count_leads_in_list(list_id or "")
            if list_id
            else count_leads_in_campaign(campaign_id or "")
        )
        pass_deleted = max(before - after, 0)
        if pass_deleted == 0 and delete_result.count is not None:
            pass_deleted = delete_result.count
        deleted_total += pass_deleted

        if log_cb:
            log_cb(
                f"Purge pass {pass_num}: removed {pass_deleted} lead(s), "
                f"{after} remaining in {label}"
            )

        if after == 0:
            return deleted_total
        if after >= before:
            raise RuntimeError(
                f"Purge stalled for {label}: {before} before, {after} after pass {pass_num}"
            )
        time.sleep(0.8)

    remaining = (
        count_leads_in_list(list_id or "")
        if list_id
        else count_leads_in_campaign(campaign_id or "")
    )
    if remaining > 0:
        raise RuntimeError(f"{label} still has {remaining} leads after {max_passes} purge passes")
    return deleted_total


def purge_leads_from_list(
    list_id: str,
    *,
    log_cb: Callable[[str], None] | None = None,
) -> int:
    return _purge_leads(list_id=list_id.strip(), log_cb=log_cb)


def fetch_leads_from_list(
    list_id: str,
    max_leads: int | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> list[dict[str, Any]]:
    return _get_client().fetch_leads_from_list(
        list_id.strip(),
        max_leads=max_leads,
        on_progress=on_progress,
    )


def fetch_leads_from_campaign(
    campaign_id: str,
    *,
    max_leads: int | None = 500,
    max_pages: int = 100,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    return _get_client().fetch_leads_from_campaign(
        campaign_id.strip(),
        max_leads=max_leads,
        max_pages=max_pages,
        on_progress=on_progress,
    )


def _read_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def _lead_to_row(lead: dict[str, Any]) -> dict[str, Any]:
    payload = lead.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}

    custom_variables: dict[str, Any] = {}
    for key, value in payload.items():
        if key in {
            "email",
            "first_name",
            "last_name",
            "company_name",
            "website",
            "phone",
            "personalization",
        }:
            continue
        if value is not None:
            custom_variables[str(key)] = value

    return {
        "instantly_lead_id": _read_str(lead.get("id")),
        "email": _read_str(lead.get("email")) or "",
        "first_name": _read_str(lead.get("first_name")),
        "last_name": _read_str(lead.get("last_name")),
        "company_name": _read_str(lead.get("company_name"))
        or _read_str(payload.get("companyName"))
        or _read_str(payload.get("Company Name")),
        "website": _read_str(lead.get("website")) or _read_str(payload.get("website")),
        "phone": _read_str(lead.get("phone")) or _read_str(payload.get("phone")),
        "personalization": _read_str(lead.get("personalization")),
        "custom_variables": custom_variables,
    }


def leads_to_dataframe(leads: list[dict[str, Any]]) -> pd.DataFrame:
    if not leads:
        return pd.DataFrame(
            columns=[
                "instantly_lead_id",
                "email",
                "first_name",
                "last_name",
                "company_name",
                "website",
                "phone",
                "personalization",
                "custom_variables",
            ]
        )

    rows = [_lead_to_row(lead) for lead in leads]
    df = pd.DataFrame(rows)
    df["custom_variables"] = df["custom_variables"].apply(
        lambda value: value if isinstance(value, dict) else {}
    )
    return df


def lead_to_row(lead: dict[str, Any]) -> dict[str, Any]:
    """CRM-compatible lead row (5 columns)."""
    payload = lead.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}

    email = _read_str(lead.get("email")) or _read_str(payload.get("email")) or ""

    return {
        "instantly_lead_id": _read_str(lead.get("id")),
        "email": email,
        "first_name": _read_str(lead.get("first_name")),
        "company_name": _read_str(lead.get("company_name"))
        or _read_str(payload.get("companyName")),
        "website": _read_str(lead.get("website")) or _read_str(payload.get("website")),
    }


def crm_leads_to_dataframe(leads: list[dict[str, Any]]) -> pd.DataFrame:
    columns = ["instantly_lead_id", "email", "first_name", "company_name", "website"]
    if not leads:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame([lead_to_row(lead) for lead in leads])


def _row_to_bulk_lead(row: pd.Series) -> dict[str, Any]:
    lead: dict[str, Any] = {"email": str(row.get("email", "")).strip()}

    for field in ("first_name", "last_name", "company_name", "website", "phone", "personalization"):
        value = row.get(field)
        if pd.notna(value) and str(value).strip():
            lead[field] = str(value).strip()

    from shared.central_leads import core_instantly_custom_variables, normalize_phone

    phone = normalize_phone(row.get("phone") if "phone" in row.index else row.get("Phone"))
    if phone:
        lead["phone"] = phone

    custom_variables = row.get("custom_variables")
    if isinstance(custom_variables, str) and custom_variables.strip():
        try:
            custom_variables = json.loads(custom_variables)
        except json.JSONDecodeError:
            custom_variables = {}
    if not isinstance(custom_variables, dict):
        custom_variables = {}
    category = ""
    if "category" in row.index and pd.notna(row.get("category")):
        category = str(row.get("category") or "").strip()
    coerced = core_instantly_custom_variables(
        custom_variables,
        phone=phone,
        category=category,
        status="cleaned",
        cleaned="valid",
    )
    if coerced:
        lead["custom_variables"] = coerced

    return lead


def _parse_add_response(data: Any, batch_size: int) -> dict[str, int]:
    if not isinstance(data, dict):
        return {
            "pushed": 0,
            "skipped_duplicate": 0,
            "failed": batch_size,
        }
    uploaded = int(data.get("leads_uploaded") or 0)
    skipped = int(data.get("skipped_count") or 0)
    failed = max(batch_size - uploaded - skipped, 0)
    return {
        "pushed": uploaded,
        "skipped_duplicate": skipped,
        "failed": failed,
    }


def push_leads_to_campaign(
    campaign_id: str,
    rows: pd.DataFrame,
    *,
    dry_run: bool = False,
    on_progress: Callable[[str, float], None] | None = None,
) -> dict[str, int]:
    empty_stats = {
        "attempted": len(rows),
        "batches": 0,
        "pushed": 0,
        "skipped_duplicate": 0,
        "failed": 0,
    }
    if dry_run or rows.empty:
        return empty_stats

    from shared.central_leads import refuse_uncleaned_instantly_push

    refuse_uncleaned_instantly_push(cleaned=True)

    client = _get_client()
    attempted = len(rows)
    pushed = 0
    skipped_duplicate = 0
    failed = 0
    batches = 0

    records = rows.to_dict(orient="records")
    for start in range(0, len(records), _BULK_BATCH_SIZE):
        batch_records = records[start : start + _BULK_BATCH_SIZE]
        batch_leads = [_row_to_bulk_lead(pd.Series(record)) for record in batch_records]
        batch_leads = [lead for lead in batch_leads if lead.get("email")]

        if not batch_leads:
            continue

        batch_size = len(batch_leads)
        # #region agent log
        try:
            from streamlit_clean.agent_debug_log import agent_debug_log

            agent_debug_log(
                "shared/instantly_client.py:push_leads_to_campaign",
                "push_batch_start",
                {
                    "batch_index": batches + 1,
                    "batch_size": batch_size,
                    "offset": start,
                    "total_records": len(records),
                },
                "A",
            )
        except Exception:
            pass
        # #endregion
        try:
            response = client._fetch(
                "/leads/add",
                method="POST",
                body={
                    "campaign_id": campaign_id.strip(),
                    "leads": batch_leads,
                    "skip_if_in_workspace": False,
                    "skip_if_in_campaign": True,
                    "skip_if_in_list": False,
                },
            )
        except RuntimeError as exc:
            # #region agent log
            try:
                from streamlit_clean.agent_debug_log import agent_debug_log

                agent_debug_log(
                    "shared/instantly_client.py:push_leads_to_campaign",
                    "push_batch_error",
                    {"batch_index": batches + 1, "error": str(exc)[:500]},
                    "A",
                )
            except Exception:
                pass
            # #endregion
            raise
        stats = _parse_add_response(response, batch_size)
        batches += 1
        pushed += stats["pushed"]
        skipped_duplicate += stats["skipped_duplicate"]
        failed += stats["failed"]
        # #region agent log
        try:
            from streamlit_clean.agent_debug_log import agent_debug_log

            agent_debug_log(
                "shared/instantly_client.py:push_leads_to_campaign",
                "push_batch_ok",
                {
                    "batch_index": batches,
                    "pushed": pushed,
                    "skipped_duplicate": skipped_duplicate,
                    "failed": failed,
                    "batch_stats": stats,
                },
                "A",
            )
        except Exception:
            pass
        # #endregion

        if on_progress:
            on_progress(
                f"Pushed batch {batches} ({pushed} uploaded, "
                f"{skipped_duplicate} skipped duplicate, {failed} failed / {attempted})",
                (pushed + skipped_duplicate + failed) / attempted,
            )

    return {
        "attempted": attempted,
        "batches": batches,
        "pushed": pushed,
        "skipped_duplicate": skipped_duplicate,
        "failed": failed,
    }
