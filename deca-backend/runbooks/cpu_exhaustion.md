# CPU / crypto stress — router overloaded

**What it is:** The PE router is burning CPU (encryption / forwarding). Traffic slows even if the underlay wires are fine.

**Keywords:** cpu_stress, crypto_cpu_exhaustion, congestion_breach, 2A, 2B, cpu_usage_user, stress-ng, station1

## Plain English
- Lab inject runs `stress-ng` (or a CPU burn) on station1.
- Watch **cpu_usage_user** (not only system CPU).
- Both GRE and eth0 can look bad — that is a clue it is CPU, not rain fade.
- Severity **2A** = moderate, **2B** = severe / act soon.

## What to look at
- High `cpu_usage_user` on station1.
- Latency up on more than one path.
- BGP counters usually quiet (unless CPU starves routing).

## What to do
1. If it is a demo inject: clear it  
   `bash scripts/inject_cpu_stress.sh --clear --host station1`
2. If Decide shows a short time-to-impact: **Approve backup**.
3. After CPU and latency recover, clear the human override.

## Do not
- Treat this as rain fade when eth0 is just as bad as GRE.
