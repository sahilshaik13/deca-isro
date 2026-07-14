"""Shared IODA API client with pagination."""

from datetime import datetime, timezone

import requests

IODA_BASE = "https://api.ioda.inetintel.cc.gatech.edu/v2"


def fetch_outage_events(
    start: datetime,
    end: datetime,
    *,
    entity_type: str = "asn",
    datasource: str | None = "bgp",
    page_size: int = 5000,
) -> list[dict]:
    """Fetch all outage events in window (paginated)."""
    all_events: list[dict] = []
    page = 1
    while True:
        params = {
            "from": int(start.timestamp()),
            "until": int(end.timestamp()),
            "entityType": entity_type,
            "limit": page_size,
            "page": page,
        }
        if datasource:
            params["datasource"] = datasource
        resp = requests.get(f"{IODA_BASE}/outages/events", params=params, timeout=120)
        resp.raise_for_status()
        events = resp.json().get("data", [])
        if not events:
            break
        all_events.extend(events)
        if len(events) < page_size:
            break
        page += 1
    return all_events
