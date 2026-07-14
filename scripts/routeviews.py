"""Download RouteViews BGP MRT update dumps into data/raw/public/."""
import requests

from _paths import PUBLIC_DIR

# The two target global operators
COLLECTORS = ["route-views2", "route-views.linx"]

# 5-day continuous window
DAYS = ["08", "09", "10", "11", "12"]
HOURS = ["0000", "0600", "1200", "1800"]

print("⏳ Starting 5-Day / 2-Operator download for RouteViews...")

for collector in COLLECTORS:
    print(f"\n🌍 Connecting to operator: {collector.upper()}")
    base_url = f"http://archive.routeviews.org/{collector}/bgpdata/2026.07/UPDATES"

    for day in DAYS:
        for hour in HOURS:
            filename = f"updates.202607{day}.{hour}.bz2"
            file_url = f"{base_url}/{filename}"

            save_name = f"{collector}_{filename}"
            save_path = PUBLIC_DIR / save_name

            if save_path.exists():
                print(f"  ⏭️ Already exists: {save_name}")
                continue

            print(f"  ⬇️ Downloading {save_name}...")
            try:
                response = requests.get(file_url, stream=True, timeout=30)
                response.raise_for_status()

                with open(save_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                print("  ✅ Saved")
            except Exception as e:
                print(f"  ❌ Failed to download {save_name}: {e}")

print("\n✨ RouteViews Multi-Operator download complete!")
