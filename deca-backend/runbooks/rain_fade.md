# Rain fade — primary path getting slower

**What it is:** The preferred satellite-style path (GRE) is getting slower, like weather fade. The backup path (eth0) usually stays fine.

**Keywords for search:** rain_fade, physical_path_degradation, tunnel_degradation, 1A, 1B, 1C, latency_gre_ms, gre-te-core, Q1 TTI, TT&C 25 ms

## Plain English
- Mission traffic prefers GRE through the core.
- Delay on GRE climbs toward the critical timing limit (**25 ms**).
- The model (Q2) may call this **1A / 1B / 1C**.
- The time model (Q1) estimates how long until that 25 ms limit.

## What to look at
- GRE latency rising; eth0 still near normal → rain fade, not CPU.
- If GRE **and** eth0 are both bad with high CPU → use the CPU runbook instead.

## What to do
1. Confirm Decide shows rising GRE latency and a time-to-impact.
2. **Approve backup** to move mission traffic to eth0 before the 25 ms breach.
3. Keep the steer until GRE is healthy again, then clear the override.
4. If this was a lab inject: `bash scripts/inject_rain_fade.sh --clear --host station1`

## Do not
- Wait for a full outage before Approving.
- Wait for Copilot/RAG text before Approving — the Decide math card is enough.
