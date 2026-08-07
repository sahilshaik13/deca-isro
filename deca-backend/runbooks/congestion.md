# Congestion / overload

**What it is:** The path or router cannot keep up — queues fill, delay rises, mission traffic is at risk.

**Keywords:** congestion_breach, cpu_stress, util, HTB, Approve backup

## Plain English
- Can come from CPU overload or too much traffic toward a rate limit.
- Decide class is often `congestion_breach`.
- Fix urgency from the **time-to-impact**, not only the class name.

## What to do
1. Check CPU vs util vs latency graphs.
2. If CPU inject: clear stress script.
3. If Decide is hot: **Approve backup**.
4. After recovery, clear the human override.
