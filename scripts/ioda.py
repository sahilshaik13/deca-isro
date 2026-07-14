"""IODA ASN outage labels → data/raw/public/ioda_outage_labels.csv."""

import argparse
from datetime import datetime, timezone

import pandas as pd
import requests

from _paths import PUBLIC_DIR
from ioda_client import fetch_outage_events

start_dt = datetime(2026, 7, 8, 0, 0, 0, tzinfo=timezone.utc)
end_dt = datetime(2026, 7, 13, 0, 0, 0, tzinfo=timezone.utc)


def fetch_ioda_outages(
    *,
    entity_type: str = "asn",
    datasource: str | None = "bgp",
    start: datetime = start_dt,
    end: datetime = end_dt,
) -> None:
    """Fetch all ASN-labeled outage events (paginated)."""
    print(f"⏳ IODA outages entityType={entity_type} datasource={datasource or 'all'}")
    print(f"   Window: {start.date()} → {end.date()}")

    try:
        events = fetch_outage_events(start, end, entity_type=entity_type, datasource=datasource)
    except requests.exceptions.RequestException as exc:
        print(f"  ❌ API request failed: {exc}")
        return

    if not events:
        print("  ⚠️ No events returned for this window/filter.")
        return

    records = []
    for event in events:
        location = event.get("location", "")
        asn = location.split("/")[-1] if "/" in location else ""
        if entity_type == "asn" and not asn.isdigit():
            continue
        records.append(
            {
                "entity_code": asn or location,
                "entity_name": event.get("location_name", ""),
                "entity_type": entity_type,
                "start_time": datetime.fromtimestamp(event["start"], tz=timezone.utc).isoformat(),
                "duration_sec": event.get("duration"),
                "datasource": event.get("datasource"),
                "method": event.get("method"),
                "score": event.get("score"),
                "outage_condition": "outage" if event.get("status") == 0 else "degraded",
            }
        )

    df = pd.DataFrame(records)
    save_path = PUBLIC_DIR / "ioda_outage_labels.csv"
    df.to_csv(save_path, index=False)
    print(f"✨ Saved {len(df)} ASN-labeled events → {save_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IODA ASN outage labels (full paginated fetch)")
    parser.add_argument("--start", default="2026-07-08")
    parser.add_argument("--end", default="2026-07-13")
    args = parser.parse_args()
    fetch_ioda_outages(
        start=datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc),
        end=datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc),
    )
