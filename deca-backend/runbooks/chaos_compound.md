# Compound faults — more than one problem at once

**What it is:** Two impairments stacked (example: rain fade + CPU). Graphs look messy; protect timing first.

**Keywords:** chaos_compound, compound, rain+cpu, multiple TTI heads, Approve

## Plain English
- More than one signal can be red at the same time.
- Still **Approve backup** if time-to-impact is short.
- After the path is safe, clear residual impairments one by one.

## What to do
1. Steer / Approve for TT&C protection first.
2. Then clear residual CPU / path impairment / BGP leftovers once GRE is healthy.
3. Do not chase every metric before protecting the mission path.
