"""Outscraper query planner — keyword×location slots with skip/limit pagination."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAX_QUERIES_PER_REQUEST = 250

# Metropolitan + overseas (101 départements).
FRENCH_DEPARTEMENTS: tuple[str, ...] = (
    tuple(f"departement {i:02d}" for i in range(1, 20))
    + tuple(f"departement {i:02d}" for i in range(21, 96))
    + ("departement 2A", "departement 2B")
    + tuple(f"departement {code}" for code in ("971", "972", "973", "974", "976"))
)


@dataclass(frozen=True)
class PlannerSlot:
    slot_id: int
    keyword: str
    location: str
    tier: str


@dataclass
class SearchBatch:
    batch_index: int
    queries: list[str]
    skip_places: int
    slot_ids: list[int]


def format_query(keyword: str, location: str) -> str:
    kw = keyword.strip()
    loc = location.strip()
    if not kw or not loc:
        return ""
    return f"{kw} in {loc}, France"


def _unique_keywords(config: dict) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for source in (
        config.get("KEYWORDS") or [],
        config.get("EXPANSION_KEYWORDS") or [],
    ):
        for raw in source:
            kw = str(raw).strip()
            key = kw.lower()
            if kw and key not in seen:
                seen.add(key)
                ordered.append(kw)
    for rotation in config.get("CONTINUOUS_KEYWORD_ROTATIONS") or []:
        if not isinstance(rotation, list):
            continue
        for raw in rotation:
            kw = str(raw).strip()
            key = kw.lower()
            if kw and key not in seen:
                seen.add(key)
                ordered.append(kw)
    return ordered


def build_slots(config: dict) -> list[PlannerSlot]:
    keywords = _unique_keywords(config)
    if not keywords:
        return []

    slots: list[PlannerSlot] = []
    slot_id = 0

    def _add_tier(kws: list[str], locs: list[str], tier: str) -> None:
        nonlocal slot_id
        for kw in kws:
            for loc in locs:
                loc_s = str(loc).strip()
                if not loc_s:
                    continue
                slots.append(PlannerSlot(slot_id=slot_id, keyword=kw, location=loc_s, tier=tier))
                slot_id += 1

    _add_tier(keywords, list(config.get("LOCATIONS") or []), "city")
    expansion_kws = [k for k in (config.get("EXPANSION_KEYWORDS") or []) if str(k).strip()]
    expansion_locs = list(config.get("EXPANSION_LOCATIONS") or [])
    if expansion_kws and expansion_locs:
        _add_tier([str(k).strip() for k in expansion_kws], expansion_locs, "expansion")
    elif expansion_locs:
        _add_tier(keywords, expansion_locs, "expansion")

    if config.get("QUERY_PLANNER_USE_DEPARTMENTS", True):
        _add_tier(keywords, list(FRENCH_DEPARTEMENTS), "department")

    return slots


def planner_state_from_run(run_state: dict[str, Any] | None) -> dict[str, Any]:
    if not run_state:
        return {"slot_skips": {}, "exhausted_slots": [], "tier_phase": 0, "batch_seq": 0}
    if int(run_state.get("version") or 0) >= 4 and run_state.get("planner"):
        planner = run_state["planner"]
        if isinstance(planner, dict):
            return {
                "slot_skips": dict(planner.get("slot_skips") or {}),
                "exhausted_slots": list(planner.get("exhausted_slots") or []),
                "tier_phase": int(planner.get("tier_phase") or 0),
                "batch_seq": int(planner.get("batch_seq") or 0),
            }
    return {"slot_skips": {}, "exhausted_slots": [], "tier_phase": 0, "batch_seq": 0}


def write_planner_to_run(run_state: dict[str, Any], planner: dict[str, Any]) -> None:
    run_state["planner"] = {
        "slot_skips": dict(planner.get("slot_skips") or {}),
        "exhausted_slots": list(planner.get("exhausted_slots") or []),
        "tier_phase": int(planner.get("tier_phase") or 0),
        "batch_seq": int(planner.get("batch_seq") or 0),
    }


@dataclass
class QueryPlanner:
    config: dict
    slots: list[PlannerSlot] = field(default_factory=list)
    slot_skips: dict[str, int] = field(default_factory=dict)
    exhausted_slots: set[int] = field(default_factory=set)
    batch_seq: int = 0
    # slot_id -> skip issued and not yet recorded. Not persisted: a crash
    # or a failed batch leaves the cursor where it was so resume re-fetches.
    inflight: dict[int, int] = field(default_factory=dict)
    # (slot_id, issued skip) already applied. A duplicate result must not
    # advance the cursor a second time.
    recorded: set[tuple[int, int]] = field(default_factory=set)
    # Slots that failed in this process. Skipped until the next process so
    # the fill loop does not reissue them immediately. Not persisted.
    failed_this_run: set[int] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.slots:
            self.slots = build_slots(self.config)

    @classmethod
    def from_config(cls, config: dict, run_state: dict[str, Any] | None = None) -> QueryPlanner:
        saved = planner_state_from_run(run_state)
        exhausted = {int(x) for x in saved.get("exhausted_slots") or []}
        skips = {str(k): int(v) for k, v in (saved.get("slot_skips") or {}).items()}
        return cls(
            config=config,
            slots=build_slots(config),
            slot_skips=skips,
            exhausted_slots=exhausted,
            batch_seq=int(saved.get("batch_seq") or 0),
        )

    def total_slots(self) -> int:
        return len(self.slots)

    def exhausted(self) -> bool:
        return len(self.exhausted_slots) >= len(self.slots)

    def active_slots(self) -> list[PlannerSlot]:
        return [s for s in self.slots if s.slot_id not in self.exhausted_slots]

    def _issuable_slots(self) -> list[PlannerSlot]:
        return [
            slot
            for slot in self.active_slots()
            if slot.slot_id not in self.inflight and slot.slot_id not in self.failed_this_run
        ]

    def next_batch(self, batch_size: int) -> SearchBatch | None:
        if self.exhausted():
            return None
        size = min(max(int(batch_size), 1), MAX_QUERIES_PER_REQUEST)
        active = self._issuable_slots()
        if not active:
            return None

        by_skip: dict[int, list[PlannerSlot]] = {}
        for slot in active:
            skip = int(self.slot_skips.get(str(slot.slot_id), 0))
            by_skip.setdefault(skip, []).append(slot)

        min_skip = min(by_skip.keys())
        group = by_skip[min_skip][:size]
        queries: list[str] = []
        slot_ids: list[int] = []
        for slot in group:
            q = format_query(slot.keyword, slot.location)
            if not q:
                self.exhausted_slots.add(slot.slot_id)
                continue
            queries.append(q)
            slot_ids.append(slot.slot_id)
        if not queries:
            return None
        for slot_id in slot_ids:
            self.inflight[slot_id] = min_skip
        batch = SearchBatch(
            batch_index=self.batch_seq,
            queries=queries,
            skip_places=min_skip,
            slot_ids=slot_ids,
        )
        self.batch_seq += 1
        return batch

    def release_batch(self, batch: SearchBatch) -> None:
        """Drop an in-flight reservation without moving the cursor.

        The next ``next_batch`` (or a later process, since reservations are
        not persisted) issues the same ``(query, skip)`` again.
        """
        issued = int(batch.skip_places)
        for slot_id in batch.slot_ids:
            if self.inflight.get(slot_id) == issued:
                self.inflight.pop(slot_id, None)

    def abandon_batch(self, batch: SearchBatch) -> None:
        """Release a failed batch and skip it for the rest of this process.

        The cursor stays put. A new planner on resume does not see
        ``failed_this_run``, so it re-fetches the page. Holding the slot
        here stops the fill loop from issuing it again in a tight loop.
        """
        self.release_batch(batch)
        for slot_id in batch.slot_ids:
            if (int(slot_id), int(batch.skip_places)) in self.recorded:
                continue
            self.failed_this_run.add(int(slot_id))

    def record_batch_result(
        self,
        batch: SearchBatch,
        *,
        raw_places_per_query: list[int],
        limit_per_query: int,
    ) -> None:
        limit = max(int(limit_per_query), 1)
        issued = int(batch.skip_places)
        for index, slot_id in enumerate(batch.slot_ids):
            if self.inflight.get(slot_id) == issued:
                self.inflight.pop(slot_id, None)
            if index >= len(raw_places_per_query):
                continue
            raw = raw_places_per_query[index]
            key = (int(slot_id), issued)
            if key in self.recorded:
                continue
            self.recorded.add(key)
            self.failed_this_run.discard(int(slot_id))
            if raw >= limit:
                skip_key = str(slot_id)
                current = int(self.slot_skips.get(skip_key, 0))
                self.slot_skips[skip_key] = max(current, issued + limit)
            else:
                self.exhausted_slots.add(slot_id)

    def persist(self, run_state: dict[str, Any]) -> None:
        write_planner_to_run(
            run_state,
            {
                "slot_skips": self.slot_skips,
                "exhausted_slots": sorted(self.exhausted_slots),
                "batch_seq": self.batch_seq,
            },
        )


def estimate_query_count(config: dict) -> int:
    return len(build_slots(config))
