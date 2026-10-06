"""Unit tests for Instantly cleaned marking."""

from __future__ import annotations

import pandas as pd

from instantly_client import InstantlyClient
from instantly_mark_cleaned import custom_variables_patch_for_row, mark_cleaned_leads_in_instantly


def test_custom_variables_patch_for_row_sets_cleaned_valid() -> None:
    row = pd.Series(
        {
            "email": "a@example.com",
            "phone": "+33 6 12 34 56 78",
            "category": "PLOMBIER",
            "custom_variables": {"city": "Paris", "siret": "123", "note": "x", "phone": "0102030405"},
        }
    )
    patch = custom_variables_patch_for_row(row)
    assert patch == {
        "cleaned": "valid",
        "status": "cleaned",
        "category": "PLOMBIER",
        "phone": "+33612345678",
    }


def test_mark_cleaned_leads_uses_instantly_lead_id(monkeypatch) -> None:
    df = pd.DataFrame(
        [
            {
                "instantly_lead_id": "lead-abc",
                "email": "a@example.com",
                "custom_variables": {},
            }
        ]
    )
    captured: list[tuple[str, dict[str, str]]] = []

    class FakeClient:
        def patch_leads_custom_variables_parallel(self, items, on_progress=None):
            captured.extend(items)
            return {"patched": len(items), "failed": 0, "errors": []}

    monkeypatch.setattr(
        "instantly_mark_cleaned._get_client",
        lambda: FakeClient(),
    )

    stats = mark_cleaned_leads_in_instantly(df)
    assert stats["patched"] == 1
    assert captured[0][0] == "lead-abc"
    assert captured[0][1]["cleaned"] == "valid"


def test_custom_variable_update_keeps_existing_city_and_siret() -> None:
    class Fake(InstantlyClient):
        def __init__(self) -> None:
            self.sent: dict | None = None

        def get_lead(self, lead_id: str) -> dict:
            return {
                "id": lead_id,
                "payload": {"city": "Paris"},
                "custom_variables": {"siret": "123", "phone": "0102030405"},
            }

        def patch_lead_custom_variables(self, lead_id: str, custom_variables: dict) -> None:
            self.sent = custom_variables

    client = Fake()
    merged = client.merge_lead_custom_variables(
        "lead-abc",
        {"phone": "+33612345678", "status": "cleaned", "cleaned": "valid", "category": "PLOMBIER"},
    )
    assert merged["city"] == "Paris"
    assert merged["siret"] == "123"
    assert merged["phone"] == "+33612345678"
    assert merged["cleaned"] == "valid"
    assert client.sent == merged
