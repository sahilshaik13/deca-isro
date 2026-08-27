# CE SLA conflict — Bronze crowding Gold

**What it is:** A lower-priority site surges traffic and crowds a critical (Gold / TT&C) site on the shared link.

**Keywords:** ce_sla_conflict, policy_drift, 5B, 6A, 6B, ce-mauritius, ce-a, Bronze, Gold, rogue_ce, victim_ce, ToS 0x80, 0x88

## Plain English
- **Rogue site:** Mauritius — Bronze ~90% — surges bulk traffic.
- **Victim site:** NRSC / ce-a — Gold ~99.9% — light TT&C probe.
- This is a **priority / policy** story, not a hack.
- Decide should name rogue vs victim when the model raises.

## What to look at
- Rogue util climbing; shared path getting busy.
- Victim Gold traffic at risk of missing its availability target.

## What to do
1. Read Decide: who is rogue, who is victim.
2. **Approve** to protect the critical site (steer backup / contain surge).
3. Stop the lab surge:  
   4. Note which operator Approved (audit).

## Do not
- Let lower-priority traffic keep starving the mission class.
