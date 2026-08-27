# Rain fade — primary path getting slower

**What it is:** The preferred satellite-style path (GRE) is getting slower, like weather fade. The backup path (eth0) usually stays fine.

**Keywords for search:** rain_fade, physical_path_degradation, tunnel_degradation, 1A, 1B, 1C, latency_gre_ms, gre-te-core, Q1 TTI, TT&C 25 ms, operator brief, Approve backup

## Plain English (for Copilot)
- Mission traffic prefers GRE through the core.
- Delay on GRE climbs toward the critical timing limit (**25 ms**).
- **1A** = early slowdown. **1B** = close to the limit. **1C** = at/over the limit.
- Q1 estimates **minutes left** before that 25 ms limit.
- Tell the operator: glance at GRE latency, then **Approve backup** to move to eth0.

## Good Copilot lines
- "Primary path is slowing — about N minutes left before the timing limit."
- "Backup (eth0) still looks healthy; Approve moves mission traffic there."
- "Do not wait for a full outage — Approve while time remains."

## What to look at
- GRE latency rising; eth0 still near normal → rain fade, not CPU.
- If GRE **and** eth0 are both bad with high CPU → use the CPU runbook instead.

## What to do
1. Confirm Decide shows rising GRE latency and a time-to-impact.
2. **Approve backup** to move mission traffic to eth0 before the 25 ms breach.
3. Keep the steer until GRE is healthy again, then clear the override.

## Do not
- Wait for a full outage before Approving.
- Dump model ids or raw Prom traces into the operator brief.
- Wait for Copilot/RAG text before Approving — the Decide math card is enough.
- Mention inject scripts, NetEM, or lab demos in operator-facing text.
