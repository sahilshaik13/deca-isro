#!/usr/bin/env python3
"""Fetch public datasets used by the current DECA data lake (sequential, low RAM)."""

import argparse
import subprocess
import sys

from _paths import REPO_ROOT, SCRIPTS_DIR

PYTHON = sys.executable


def run(script: str, label: str, extra: list[str] | None = None) -> None:
    cmd = [PYTHON, str(SCRIPTS_DIR / script), *(extra or [])]
    print(f"\n{'=' * 60}\n▶ {label}\n{'=' * 60}")
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch public inputs for DECA (matches data/raw/public inventory)"
    )
    parser.add_argument("--skip-bgp-parse", action="store_true", help="Skip MRT → rates parse")
    parser.add_argument(
        "--skip-atlas-full",
        action="store_true",
        help="Skip Atlas historical pull (baseline snapshot only)",
    )
    parser.add_argument(
        "--atlas-chunk-minutes",
        type=int,
        default=15,
        help="Atlas historical chunk size",
    )
    args = parser.parse_args()

    run("routeviews.py", "RouteViews BGP MRT updates")
    run("riperis.py", "RIPE RIS BGP MRT updates")
    run("bgpstream.py", "BGP routing labels (IODA BGP)")
    run("ioda.py", "IODA ASN outage labels")

    if args.skip_atlas_full:
        run("ripe_atlas.py", "RIPE Atlas latest snapshot")
    else:
        run(
            "ripe_atlas.py",
            "RIPE Atlas historical (stream + sample downstream)",
            [
                "--full",
                "--chunk-minutes",
                str(args.atlas_chunk_minutes),
                "--resume",
            ],
        )

    if not args.skip_bgp_parse:
        run("parse_bgp.py", "Parse BGP MRT → minute rates", ["--resume"])

    print(
        "\n✅ Public fetch complete.\n"
        "Next (manual / separate):\n"
        "  • MAWI: browse samplepoint-F HTML → hand-write data/raw/public/mawi_sample.csv\n"
        "  • Cisco: python scripts/cisco_scraper.py\n"
        "  • Lab:   python scripts/deca_fault_campaign.py\n"
        "  • Unify: python scripts/rebuild_unified.py\n"
        "See docs/DATA_GEN.md for the full recipe."
    )


if __name__ == "__main__":
    main()
