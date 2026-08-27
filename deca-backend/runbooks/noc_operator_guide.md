# NOC operator guide (simple)

**What this system does:** Watch the live network → predict time to a service limit → you Approve a backup path before the outage.

**Keywords:** NOC, Decide, Copilot, Approve, Q1, Q2, Q3, predictive, HITL

## Three panels
1. **Watch** — latency, loss, CPU, flaps, util graphs (Prom).
2. **Decide** — model card: class, confidence, minutes left, Approve backup.
3. **Copilot** — short operator briefing from model scores + runbooks (RAG). Does not replace Approve.

## Common live events
| What you see | In plain words | Typical class |
| --- | --- | --- |
| Rain fade | Preferred path getting slower | tunnel / physical |
| Loss climb | Packets dropping more | tunnel / loss |
| CPU stress | Router overloaded | congestion / CPU |
| BGP flap | Routes shaking | bgp_route_flap |
| CE SLA conflict | Bronze crowding Gold | policy_drift |

## Predictive vs reactive (one sentence)
Symptoms appear first (reactive detection). Forecasting **how long until the SLA** and Approving **before** breach is the predictive part.

## Always safe actions
1. Watch Live metrics for the rising symptom.
2. Wait for Decide (model scores).
3. Approve backup while ETA is still counting down under the limit.
4. Confirm path badge changes; Copilot can idle after steer.
5. If graphs stay bad after recovery, clear residual underlay overrides and re-check Prom.

## Copilot voice
Speak as a live NOC event. Never mention fault injection, NetEM, lab demos, or script names.
