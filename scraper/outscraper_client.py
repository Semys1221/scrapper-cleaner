"""Async adapter around the official Outscraper Python SDK."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Protocol

import requests
from outscraper import OutscraperClient as _SdkClient

# One host. The SDK walks extra hosts on connection errors and would POST again.
_MAPS_API_ROOT = "https://api.app.outscraper.com"
_POLL_INTERVAL_S = 5.0


class OutscraperRequestError(RuntimeError):
    """Outscraper call failed. Callers must not treat this as an empty result."""


class _PollSettings(Protocol):
    poll_initial_s: float
    poll_interval_s: float
    poll_slow_s: float
    poll_timeout_s: float


class _PollableJob(Protocol):
    task_id: str
    submitted_at: float
    last_polled_at: float


def _normalize_archive_data(raw_data: Any) -> list:
    if raw_data is None:
        return []
    if not isinstance(raw_data, list):
        return [raw_data] if isinstance(raw_data, dict) else []
    return raw_data


def normalize_maps_search_payload(raw: Any) -> list:
    """Normalize SDK / archive payload to list[query_result] for _process_batch_results."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        data = raw.get("data")
        if data is not None:
            return normalize_maps_search_payload(data)
        return [raw]
    if not isinstance(raw, list):
        return []
    if not raw:
        return []
    first = raw[0]
    if isinstance(first, list):
        return raw
    if isinstance(first, dict):
        return [raw]
    return raw


def count_places_per_query(results: list, query_count: int) -> list[int]:
    """Return place counts aligned with query_count (one entry per query in batch)."""
    if query_count <= 0:
        return []
    if not results:
        return [0] * query_count
    if len(results) == query_count:
        counts: list[int] = []
        for item in results:
            if isinstance(item, list):
                counts.append(sum(1 for x in item if isinstance(x, dict)))
            elif isinstance(item, dict):
                counts.append(1)
            else:
                counts.append(0)
        return counts
    flat = 0
    for item in results:
        if isinstance(item, list):
            flat += sum(1 for x in item if isinstance(x, dict))
        elif isinstance(item, dict):
            flat += 1
    return [flat] + [0] * (query_count - 1)


class OutscraperClient:
    """Async wrapper for Outscraper Google Maps Search.

    A maps search is one paid POST. Timeouts and HTTP errors do not submit
    again: the request id is polled until Success or the deadline. A timed-out
    POST is still counted, because Outscraper may keep billing it server-side.
    """

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._sdk = _SdkClient(api_key=api_key)
        self.qps_delay = 0.05
        self.poll_interval_s = _POLL_INTERVAL_S
        self.last_error: str = ""
        self.paid_submits = 0
        self.places_submitted = 0

    def _api_headers(self) -> dict[str, str]:
        return {"X-API-KEY": self.api_key, "client": "Python SDK"}

    def _submit_maps_once(self, payload: dict[str, Any]) -> str:
        """POST /google-maps-search exactly once and return the request id.

        ``paid_submits`` / ``places_submitted`` increment before the socket
        call so a timeout still counts as spend.
        """
        queries = payload.get("query") or []
        if isinstance(queries, str):
            queries = [queries]
        limit = int(payload.get("limit") or 0)
        self.paid_submits += 1
        self.places_submitted += max(len(queries), 0) * max(limit, 0)
        body = dict(payload)
        body["async"] = True
        response = requests.post(
            f"{_MAPS_API_ROOT}/google-maps-search",
            headers=self._api_headers(),
            json=body,
            timeout=30,
        )
        if not (199 < response.status_code < 300):
            raise RuntimeError(f"Response status code: {response.status_code}")
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("unexpected submit payload")
        if data.get("error"):
            raise RuntimeError(str(data.get("errorMessage") or data.get("error")))
        task_id = data.get("id")
        if not task_id:
            raise RuntimeError("missing task id")
        return str(task_id)

    def _get_request(self, request_id: str) -> dict[str, Any]:
        """GET /requests/{id}. Callers may retry this; it does not bill again."""
        response = requests.get(
            f"{_MAPS_API_ROOT}/requests/{request_id}",
            headers=self._api_headers(),
            timeout=30,
        )
        if not (199 < response.status_code < 300):
            raise RuntimeError(f"Response status code: {response.status_code}")
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("unexpected archive payload")
        return data

    async def aclose(self) -> None:
        return None

    async def google_maps_search_batch(
        self,
        queries: list[str],
        limit: int,
        *,
        skip_places: int = 0,
        filters: list[str] | None = None,
        language: str = "fr",
        region: str = "FR",
        enrichment: list[str] | None = None,
        preset: str = "",
        out_dir: str = "",
        timeout_s: float = 600.0,
    ) -> list:
        """POST one Google Maps search, then poll its request id. Never re-POST."""
        cleaned = [str(q).strip() for q in queries if str(q).strip()]
        if not cleaned:
            return []

        payload: dict[str, Any] = {
            "query": cleaned,
            "limit": int(limit),
            "async": False,
            "dropDuplicates": True,
            "language": language,
            "region": region.strip().upper() or "FR",
        }
        enrich = [str(item).strip() for item in (enrichment or []) if str(item).strip()]
        if enrich:
            payload["enrichment"] = enrich
        else:
            payload["extractContacts"] = True
        if skip_places > 0:
            payload["skipPlaces"] = int(skip_places)
        if filters:
            payload["filters"] = filters
        payload["async"] = True

        heartbeat_task: asyncio.Task | None = None
        if out_dir and preset:

            async def _heartbeat_loop() -> None:
                from scrape_metrics import sleep_with_heartbeat

                while True:
                    await sleep_with_heartbeat(15.0, out_dir, preset=preset)

            heartbeat_task = asyncio.create_task(_heartbeat_loop())

        deadline = time.monotonic() + max(float(timeout_s), 0.0)
        try:
            try:
                request_id = await asyncio.to_thread(self._submit_maps_once, payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                return []

            while True:
                try:
                    archive = await asyncio.to_thread(self._get_request, request_id)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if time.monotonic() >= deadline:
                        self.last_error = f"Outscraper poll failed: {exc}"
                        return []
                    await asyncio.sleep(self.poll_interval_s)
                    continue
                status = str(archive.get("status") or "")
                if status == "Success":
                    self.last_error = ""
                    return normalize_maps_search_payload(archive.get("data"))
                if status and status != "Pending":
                    self.last_error = str(
                        archive.get("errorMessage")
                        or archive.get("error")
                        or status
                    )
                    return []
                if time.monotonic() >= deadline:
                    self.last_error = f"Outscraper poll timed out after {float(timeout_s):.0f}s"
                    return []
                await asyncio.sleep(self.poll_interval_s)
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
            await asyncio.sleep(self.qps_delay)

    async def send_async_tasks(
        self,
        queries: list[str],
        limit: int,
        *,
        total_limit: int | None = None,
        skip_places: int = 0,
        filters: list[str] | None = None,
        language: str = "fr",
        region: str = "FR",
        enrichment: list[str] | None = None,
    ) -> str | None:
        payload: dict[str, Any] = {
            "query": queries,
            "limit": limit,
            "async": True,
            "dropDuplicates": True,
            "language": language,
            "region": region.strip().upper() or "FR",
        }
        enrich = [str(item).strip() for item in (enrichment or []) if str(item).strip()]
        if enrich:
            payload["enrichment"] = enrich
        else:
            payload["extractContacts"] = True
        if total_limit is not None:
            payload["totalLimit"] = total_limit
        if skip_places > 0:
            payload["skipPlaces"] = skip_places
        if filters:
            payload["filters"] = filters
        payload["async"] = True

        try:
            task_id = await asyncio.to_thread(self._submit_maps_once, payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = str(exc)
            return None
        self.last_error = ""
        await asyncio.sleep(self.qps_delay)
        return task_id

    async def emails_and_contacts(self, domains: list[str]) -> list[dict[str, Any]]:
        """Crawl domains for emails via Outscraper emails-and-contacts endpoint."""
        cleaned = [str(d).strip() for d in domains if str(d).strip()]
        if not cleaned:
            return []

        def _call() -> Any:
            return self._sdk.emails_and_contacts(cleaned)

        try:
            result = await asyncio.to_thread(_call)
        except Exception as exc:
            self.last_error = str(exc)
            raise OutscraperRequestError(str(exc)) from exc

        if result is None:
            return []
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        if isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
            return [result]
        return []

    async def phones_enricher(self, phones: list[str]) -> list[dict[str, Any]]:
        """Validate numbers via Outscraper GET /phones-enricher (carrier name and type)."""
        cleaned = [str(phone).strip() for phone in phones if str(phone).strip()]
        if not cleaned:
            return []

        def _call() -> Any:
            return self._sdk.phones_enricher(cleaned)

        try:
            result = await asyncio.to_thread(_call)
        except Exception as exc:
            self.last_error = str(exc)
            raise OutscraperRequestError(str(exc)) from exc

        if result is None:
            return []
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        if isinstance(result, dict):
            if result.get("error") is True or str(result.get("status") or "").lower() in {
                "failure",
                "error",
                "failed",
            }:
                self.last_error = str(result.get("errorMessage") or result.get("error") or result.get("status"))
                return [result]
            data = result.get("data")
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
            return [result]
        return []

    async def check_task_status(self, task_id: str) -> list | None:
        def _fetch() -> dict[str, Any]:
            return self._sdk.get_request_archive(task_id)

        try:
            data = await asyncio.to_thread(_fetch)
        except Exception:
            return None

        try:
            status = data.get("status")
            if status == "Success":
                return _normalize_archive_data(data.get("data"))
            if status == "Pending":
                return None
            return []
        finally:
            await asyncio.sleep(self.qps_delay)

    async def cancel_task(self, task_id: str) -> bool:
        def _cancel() -> bool:
            try:
                response = self._sdk._transport.api_request(
                    "DELETE",
                    f"/requests/{task_id}",
                    use_handle_response=False,
                    wait_async=False,
                    async_request=False,
                )
                return 199 < response.status_code < 300
            except Exception:
                return False

        cancelled = await asyncio.to_thread(_cancel)
        if cancelled:
            await asyncio.sleep(self.qps_delay)
        return cancelled

    async def list_running_requests(self) -> list[str]:
        def _list() -> list[str]:
            try:
                data = self._sdk.get_requests_history(type="running", page_size=100)
            except Exception:
                return []
            items = data if isinstance(data, list) else data.get("data", [])
            ids: list[str] = []
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    ids.append(str(item["id"]))
            return ids

        return await asyncio.to_thread(_list)


def poll_interval_for_job(job: _PollableJob, settings: _PollSettings, now: float) -> float | None:
    elapsed = now - job.submitted_at
    if elapsed < settings.poll_initial_s:
        return None
    if elapsed >= settings.poll_timeout_s:
        return settings.poll_interval_s
    slow_after = 240.0
    interval = settings.poll_slow_s if elapsed >= slow_after else settings.poll_interval_s
    if job.last_polled_at and (now - job.last_polled_at) < interval:
        return None
    return interval


def seconds_until_next_poll(
    jobs: list[_PollableJob],
    settings: _PollSettings,
    now: float,
) -> float:
    if not jobs:
        return settings.poll_interval_s
    waits: list[float] = []
    for job in jobs:
        elapsed = now - job.submitted_at
        if elapsed >= settings.poll_timeout_s:
            continue
        if elapsed < settings.poll_initial_s:
            waits.append(settings.poll_initial_s - elapsed)
            continue
        slow_after = 240.0
        interval = settings.poll_slow_s if elapsed >= slow_after else settings.poll_interval_s
        if job.last_polled_at:
            since_poll = now - job.last_polled_at
            if since_poll < interval:
                waits.append(interval - since_poll)
        else:
            waits.append(0.0)
    return min(waits) if waits else settings.poll_interval_s


async def poll_once(
    client: OutscraperClient,
    job: _PollableJob,
    settings: _PollSettings,
) -> tuple[str, list | None]:
    """Poll a task once. Returns (status, results) where status is pending|success|failed."""
    now = time.time()
    elapsed = now - job.submitted_at
    if elapsed >= settings.poll_timeout_s:
        return "failed", []

    if poll_interval_for_job(job, settings, now) is None:
        return "pending", None

    job.last_polled_at = now
    results = await client.check_task_status(job.task_id)
    if results is None:
        return "pending", None
    return "success", results


async def poll_until_ready(
    client: OutscraperClient,
    job: _PollableJob,
    settings: _PollSettings,
    log_cb: Callable[[str], None],
    *,
    out_dir: str = "",
    preset: str = "",
) -> list | None:
    while True:
        status, results = await poll_once(client, job, settings)
        if status == "success":
            return results
        if status == "failed":
            log_cb(f"Task [{job.task_id}] timed out after {int(time.time() - job.submitted_at)}s.")
            return []
        wait_s = seconds_until_next_poll([job], settings, time.time())
        if out_dir and preset:
            from scrape_metrics import sleep_with_heartbeat

            await sleep_with_heartbeat(wait_s, out_dir, preset=preset)
        else:
            await asyncio.sleep(wait_s)
