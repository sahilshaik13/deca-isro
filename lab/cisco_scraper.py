import time
import csv
import re
from datetime import datetime, timezone
from netmiko import ConnectHandler

# Your working Cisco Sandbox credentials
cisco_device = {
    'device_type': 'cisco_ios',
    'host':   '10.10.20.48',
    'username': 'developer',
    'password': 'C1sco12345',
}

csv_path = './data/raw/public/cisco_sandbox_sample.csv'

print("🔌 Connecting to Cisco Cat8000v...")
try:
    net_connect = ConnectHandler(**cisco_device)
    print("✅ Connected! Scraping traffic data every 15 seconds.")
    print(f"📁 Saving to {csv_path}")
    print("⏳ Let this run for 30 to 45 minutes, then press Ctrl+C to stop.")
    
    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'metric', 'value']) # Matches your DECA format
        
        while True:
            # Pull the interface stats
            output = net_connect.send_command("show interfaces GigabitEthernet1")
            now = datetime.now(timezone.utc).isoformat()
            
            # Extract Input and Output bytes using Regex
            in_match = re.search(r'(\d+) packets input,\s+(\d+)\s+bytes', output)
            out_match = re.search(r'(\d+) packets output,\s+(\d+)\s+bytes', output)
            
            if in_match:
                writer.writerow([now, 'ifInOctets', in_match.group(2)])
            if out_match:
                writer.writerow([now, 'ifOutOctets', out_match.group(2)])
            
            f.flush() # Force save to disk immediately
            time.sleep(15) # Wait 15 seconds before the next pull

except KeyboardInterrupt:
    print("\n🛑 Scraping stopped by user. CSV is saved and ready for the ML pipeline!")
    net_connect.disconnect()
except Exception as e:
    print(f"\n❌ An error occurred: {e}")
