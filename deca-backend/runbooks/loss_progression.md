# Packet loss climbing on the primary path

**What it is:** More packets are being dropped on the preferred GRE path. Mission data can stall or retransmit.

**Keywords:** loss_progression, tunnel_degradation, 4A, 4B, loss_gre_pct, Payload 2%, netem loss

## Plain English
- Live symptom: path loss climbing on preferred underlay.
- Payload service limit is about **2%** loss.
- **4A** = moderate loss. **4B** = at or past the breach band.
- Q1 estimates time left before the loss limit.

## What to look at
- `loss_gre_pct` rising on GRE.
- Latency may also move; CPU should not be the main story.

## What to do
1. Confirm Decide / telemetry show rising GRE loss.
2. **Approve backup** before loss stays above the service limit.
3. After loss recovers, clear residual underlay overrides and restore preferred path.
   4. Clear the override after GRE loss is healthy again.

## Do not
- Wait until users already see a hard outage.
