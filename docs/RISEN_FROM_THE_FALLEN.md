# Risen from the Fallen

**What this document is:** the whole DECA fault-detection story, stripped of jargon, for anyone who wants the plain-language version before (or instead of) the technical write-ups. Five problems' worth of "the model was wrong, here's how we found out, here's what we did about it" — in the order they were actually hit, ending in the one change that fixed the deepest problem and, as a side effect, made the model portable to a network it's never seen.

For the technical detail behind any of the eight beats below: [`DECA_ROI_TIERS.md`](DECA_ROI_TIERS.md) (the full tier-by-tier escalation with numbers), [`TIER5_VRF_ROUTE_COUNT.md`](TIER5_VRF_ROUTE_COUNT.md) (the phantom-VRF bug in full), [`ISRO_PORTABILITY.md`](ISRO_PORTABILITY.md) (why point 8 is also the portability story).

---

**1. The model cried wolf too much.**
Early on, even when the network was completely healthy, the model kept raising alarms — about **21 false alarms in one clean hour**. That's the "boy who cried wolf" problem: if it screams "fault!" every three minutes when nothing's wrong, a real network operator stops trusting it entirely, even when it's right. This was the very first thing you had to fix, because a jumpy model is worse than no model.

**2. It couldn't tell a "close call" from a real fault.**
You tested it with fake near-misses — brief blips that look like the start of a fault but abort before anything actually breaks. The model kept treating those blips as real faults too. Like a smoke detector going off every time you make toast.

**3. Fixing #1 and #2 came at a cost — it got a little too cautious.**
Once you taught the model to stay calm during fake-outs, it also got slightly less sensitive to real faults — it missed one genuine VRF leak it would've caught before. This is a very normal trade-off in ML (tighten the net to catch fewer wrong fish, and you sometimes let a real one slip through too) — not a bug, just physics of the problem.

**4. Three fault types kept getting confused with each other.**
Tunnel problems, VRF leaks, and congestion all *look* similar to the model in their first few seconds — like three different illnesses that all start with a fever. It would often name the wrong one at first, then correct itself a bit later.

**5. When two faults happened at the same time, the quieter one got drowned out.**
If a loud fault (like tunnel congestion) and a quiet fault (VRF leak) happened simultaneously on the network, the model's attention got hijacked by the loud one and it missed the quiet one entirely — like trying to hear a whisper next to a jackhammer.

**6. A silent data bug meant your "VRF leak" training data wasn't real for a long time.**
This was the sneaky one: your fault-injection script was targeting a VRF name (`ADMIN`) that didn't actually exist on the routers — it should've been `vrf-admin`. So every "VRF leak" fault you'd ever generated was a no-op at the network level; the model was only ever learning from a side-effect (network slowdown), not the actual leak. You caught this, fixed the exact command, and confirmed a real leak now shows up as a real signal.

**7. Throwing more training data at the weak spots stopped working.**
After fixing #6, you tried the obvious next move — generate more labeled examples of the faults the model was bad at (VRF, then BGP). It helped a little each time, but hit a wall: one fault class would improve while another got worse, like squeezing a balloon.

**8. The real root cause: the model was measuring things in absolute numbers, not "normal for this network."**
This was the actual breakthrough. Instead of teaching the model more examples, you changed *what it looks at* — instead of "traffic is at 80 Mbps," it now looks at "traffic is 3x higher than this specific network's own normal." That one change fixed the balloon-squeezing problem (both weak classes improved together) and is also *why the model can move to ISRO's network at all* — a number like "80 Mbps" means nothing on a different network, but "3x your own normal" always means the same thing.

---

**In one sentence for a judge:** the model went from "raises too many false alarms and gets confused between similar faults" → to "reliably quiet when healthy, mostly correct on real faults, and — because of how the final fix works — portable to a network it's never seen."
