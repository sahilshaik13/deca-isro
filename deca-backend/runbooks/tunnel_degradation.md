# Primary path degrading (tunnel / underlay)

**What it is:** Preferred path quality is getting worse (delay, jitter, or loss). Often rain fade or loss ramp in this lab.

**Keywords:** tunnel_degradation, rain_fade, loss_progression, gre, eth0, Approve backup

## Plain English
- Preferred path = GRE. Backup = eth0 (skips the core).
- If only GRE is bad → physical / loss style fault.
- If everything is bad with high CPU → CPU runbook.

## What to do
1. Compare GRE vs eth0 on the left-hand graphs.
2. Read Decide time-to-impact.
3. **Approve backup** before the service limit is crossed.
4. Clear lab NetEM if needed (`inject_rain_fade.sh --clear` or `inject_loss_progression.sh --clear`).
