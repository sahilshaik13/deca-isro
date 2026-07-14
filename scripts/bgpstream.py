"""BGP routing event labels with ASN context (full paginated IODA BGP outages)."""

import argparse
from datetime import datetime, timezone

import pandas as pd

from _paths import PUBLIC_DIR
from ioda_client import fetch_outage_events


def events_to_df(events: list[dict]) -> pd.DataFrame:
    rows = []
    for event in events:
        location = event.get("location", "")
        asn = location.split("/")[-1] if "/" in location else location.replace("asn/", "")
        rows.append(
            {
                "asn": asn,
                "asn_name": event.get("location_name", ""),
                "start_time": datetime.fromtimestamp(event["start"], tz=timezone.utc).isoformat(),
                "duration_sec": event.get("duration"),
                "datasource": event.get("datasource", "bgp"),
                "method": event.get("method"),
                "score": event.get("score"),
                "event_type": "bgp_outage",
                "source": "ioda_bgp",
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="BGP ASN outage labels (full IODA fetch)")
    parser.add_argument("--start", default="2026-07-08", help="UTC start date YYYY-MM-DD")
    parser.add_argument("--end", default="2026-07-13", help="UTC end date YYYY-MM-DD")
    args = parser.parse_args()

    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)

    print(f"⏳ IODA BGP ASN outages (full) {start.date()} → {end.date()}")
    events = fetch_outage_events(start, end, entity_type="asn", datasource="bgp")
    df = events_to_df(events)
    out = PUBLIC_DIR / "bgp_routing_labels.csv"
    df.to_csv(out, index=False)
    print(f"✨ Saved {out} ({len(df)} rows, {df['asn'].nunique()} unique ASNs)")


if __name__ == "__main__":
    main()
