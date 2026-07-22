# Chapter 3 — The Four Faults We Detect

## Why only four?

DECA does not try to catch every possible thing that could ever go wrong
on a network — that would be an endless, unbounded list. Instead, we
deliberately picked **four** specific, well-known, industry-standard
problem categories that happen on exactly the kind of network DECA
watches (a company network built the modern way, with private routing
segments and encrypted site-to-site tunnels — see Chapter 1 for all the
vocabulary). These four are not made up for our lab; they are the
textbook failure categories that any real network engineer working on
this kind of network would recognize immediately.

This chapter walks through each one, slowly, using plain words, then
shows the exact "fingerprint" (the pattern of measurements) each one
leaves behind — which is the whole reason DECA can tell them apart at
all.

The fifth possible answer, always available, is simply **`healthy`** —
"nothing is wrong." Every one of DECA's decisions is really a choice
between these five options.

---

## Fault 1 — `congestion_breach`

### What it is, in plain words

Imagine a single-lane road that normally carries a comfortable number of
cars. Now imagine a lot more cars suddenly try to use that same road at
once — more than it was ever built to comfortably handle. Traffic slows
to a crawl, cars start backing up in a long line, and some drivers get so
stuck that they simply give up and turn around (in networking terms:
their data gets dropped).

That is congestion. A "breach" is the moment this congestion crosses a
serious line — not just "a little busier than usual," but genuinely
overloaded, to the point where the network can no longer serve traffic
properly.

### How we cause it on purpose, in our lab

We use a tool called `tbf` (Token Bucket Filter — see Chapter 1) to put a
hard ceiling on how much traffic a specific link is allowed to carry.
Then we use a separate tool called `iperf3` to generate a stream of
traffic that tries to push *past* that ceiling. The mismatch between "how
much traffic wants to get through" and "how much the link will actually
allow" is what creates real, measurable congestion.

### What it looks like in the numbers (the "fingerprint")

- **Throughput** (`ifInOctets`/`ifOutOctets`, Chapter 1) rises, then hits
  a flat ceiling — it physically cannot go any higher because the `tbf`
  cap won't allow it.
- **Packet loss** rises, because packets that can't fit through the
  narrowed pipe get dropped.
- **Jitter** rises somewhat too, because packets are queuing up and
  waiting, and that wait time becomes less predictable.
- Crucially, this all tends to happen **before** the hard breach fully
  lands — the build-up itself has a shape (rising, then flattening under
  a ceiling) that DECA's "slope" and "acceleration" features (Chapter 2)
  are specifically designed to notice early.

### How well DECA detects it

This is one of the two "easier" faults for DECA (the other being
`tunnel_degradation`). Its fingerprint is loud and clear — a strong rise
in traffic, hitting an obvious ceiling, combined with rising loss. In our
very first measured results, `congestion_breach` scored an F1 of **0.89**
— high recall (0.94) and reasonably high precision (0.84).

---

## Fault 2 — `tunnel_degradation`

### What it is, in plain words

Recall from Chapter 1 that a "tunnel" is a secure, wrapped path (using
IPsec) that carries traffic between two sites. A tunnel doesn't have to
go fully offline to be a problem — it can just slowly get *worse*. Think
of a phone call that hasn't dropped, but has become so crackly, delayed,
and glitchy that a normal conversation is becoming genuinely difficult,
even though technically the call is "still connected."

That is tunnel degradation: the tunnel is up, packets are still getting
through, but the *quality* of that path — how much delay, how bouncy that
delay is, how many packets get lost along the way — has quietly gotten
much worse.

### How we cause it on purpose, in our lab

We use `netem` (network emulation, Chapter 1) to deliberately add fake
delay, fake jitter, and fake packet loss directly onto the tunnel's
traffic — essentially simulating "bad weather" on that specific path on
purpose, on a schedule we control.

### What it looks like in the numbers (the "fingerprint")

- **Latency** (`latency_ms`) climbs.
- **Jitter** (`jitter_ms`) climbs, often the strongest and clearest
  signal of the three.
- **Packet loss** (`packet_loss_pct`) climbs too.
- Unlike congestion, **throughput doesn't necessarily hit a hard ceiling**
  — the traffic volume itself might look fairly normal; it's the *quality*
  of delivery that's degraded, not necessarily the *quantity*. This is
  the key distinguishing clue that separates this fault from
  `congestion_breach` in the model's eyes.

### How well DECA detects it

This is DECA's other "easy" fault. In our first measured results,
`tunnel_degradation` scored an F1 of **0.81** (precision 0.75, recall
0.88).

---

## Fault 3 — `bgp_route_flap`

### What it is, in plain words

Recall from Chapter 1 that BGP is the protocol routers use to share
routing information with each other, and that a "flap" is when something
(a route, or a whole session) keeps rapidly going up, then down, then up
again, instead of settling into one stable state — like a light switch
someone keeps flicking on and off.

A BGP route flap means the routing conversation between two routers is
becoming unstable and chattering constantly — resending information over
and over, when it should mostly just be quiet and settled.

### How we cause it on purpose, in our lab

We repeatedly issue a command (`vtysh -c "clear bgp ... soft"`) that
forces a BGP session to refresh its routing information, again and again,
mimicking the kind of chatty instability a real flap would cause.

### The story behind this fault — a genuinely important lesson

This particular fault has the single most interesting and instructive
history of all four, and it is told in complete detail in Chapter 7
(mistake #9). In short: for a long time, our *detector* for this fault
was built around a completely fabricated number — we were literally
writing a made-up value into a spreadsheet rather than reading a real
measurement from the router — because Prometheus had no real BGP-related
measurement being scraped at all at the time. Once we discovered this and
built a real exporter to read the router's *actual* internal counter
(specifically, `routeRefreshSent` and `routeRefreshRecv` — real numbers
that genuinely move every time we issue our flap-simulating command),
DECA's ability to detect this fault improved substantially. This is a
genuinely important lesson: a system that has learned from a fake signal
can look fine on paper for a long time before anyone realizes the
underlying data was never real to begin with.

### What it looks like in the numbers (the "fingerprint")

- **`bgp_update_rate`** (in the earlier, fabricated-signal era) spikes
  briefly, in short bursts, more than it smoothly ramps.
- **`bgp_flap_count`** (the newer, real exporter) climbs directly and
  reliably every time a real flap-inducing command is issued —
  confirmed live, end-to-end, through the full monitoring pipeline.
- This fault tends to be **spiky and short-scale** rather than a smooth,
  slow ramp — which is part of why it's historically been one of the two
  harder faults for DECA to learn (the "2-minute" short rolling window,
  Chapter 2, matters more here than the "10-minute" long window).

### How well DECA detects it

This has been the single most-worked-on fault in the whole project's
history. In our very first measured results, its F1 was only **0.42**
(precision just 0.31, though recall was already 0.68). Chapter 8 tells
the full, numbers-by-numbers story of the long climb from there,
eventually reaching an F1 of **0.48** after the real exporter and
baseline-relative feature work (and continuing to climb further in later
rounds).

---

## Fault 4 — `vrf_leakage`

### What it is, in plain words

Recall from Chapter 1 that a VRF is like a separate, locked "company
floor" inside one shared office building (router) — traffic that belongs
to one VRF should never be visible to, or reachable from, a different
VRF. A "leak" is when a route that should have stayed locked inside one
VRF's private routing table accidentally gets copied into a different
VRF's table, breaking that wall of separation.

This is, in real-world terms, one of the most serious kinds of network
misconfiguration — it's a security and privacy failure, not just a
performance one. Traffic that was supposed to be walled off from another
department, customer, or system suddenly becomes reachable from the
wrong place.

### How we cause it on purpose, in our lab

We manipulate a setting called a Route Target (Chapter 1) so that routes
belonging to our main `vrf-mission` VRF get improperly imported into a
separate VRF (`vrf-admin`) that should never have received them. We also
add a light, deliberate `netem` ramp on the affected station, because a
"pure" leak — just the routing table change, with no accompanying traffic
shape — turned out to leave very little visible telemetry footprint on
its own (explained further below).

### The story behind this fault — a genuinely important lesson

Like `bgp_route_flap`, this fault also has a serious history told in full
in Chapter 7 (mistake #6). For a long time, our fault-injection script
was accidentally targeting a VRF name, `ADMIN`, that did not actually
exist anywhere on the real routers — the real VRF was named `vrf-admin`
(note the lowercase and the hyphen). Every single "VRF leak" our lab
generated during that period never actually leaked a real route at the
network level — it was a no-op, silently failing every time. The model
was only ever learning from the accompanying, secondary `netem` traffic
ramp, not from an actual leak. This was found and fixed, and afterward,
we specifically re-verified live that a real leak now shows up as a real
signal — watching the actual BGP route count inside the wrong VRF's table
go from `0 → 4` the instant we injected the (now correctly-targeted)
leak, and back down to `4 → 0` the instant we reverted it.

### What it looks like in the numbers (the "fingerprint")

- **`vrf_route_count`** (the number of routes present inside the
  `vrf-admin` VRF's own routing/BGP table) rises directly from the real
  leak — this is our clearest, most direct "smoking gun" signal, and it
  did not exist at all until we built it specifically for this purpose
  (see Chapter 5 and `docs/TIER5_VRF_ROUTE_COUNT.md` for the full,
  detailed build story).
- Beyond that direct signal, this fault is otherwise genuinely **subtle**
  — it doesn't necessarily cause the loud, obvious congestion-style ramp
  the other faults do. Symptoms tend to show up as odd, slightly
  asymmetric loss or latency without a classic congestion shape, and can
  look "almost healthy" for longer before finally becoming clearly wrong.

### How well DECA detects it

This has historically been DECA's hardest fault, alongside
`bgp_route_flap`. In our very first measured results, its F1 was only
**0.52** (precision 0.43, recall 0.65). Chapter 8 tells the detailed
story of its long climb — 0.47 → 0.59 → 0.63 → 0.65 → 0.75 — across
several rounds of dedicated data campaigns and, eventually, the
baseline-relative feature breakthrough.

---

## Side-by-side comparison

| Fault | What's actually breaking | Loudest signal | Subtlest signal | Historical difficulty |
| --- | --- | --- | --- | --- |
| `congestion_breach` | Too much traffic for the link's real capacity | Throughput hits a hard ceiling | — | Easy |
| `tunnel_degradation` | Path quality (delay/loss) getting worse, not necessarily volume | Jitter + latency + loss climbing together | Traffic volume may look almost normal | Easy |
| `bgp_route_flap` | Routing control-plane instability, sessions constantly refreshing | Bursty, spiky short-scale signal | Was, for a long time, invisible entirely (fabricated feature) | Hard |
| `vrf_leakage` | Wrong VRF boundary crossed; traffic reachable where it shouldn't be | Direct route-count rise in the wrong VRF | Otherwise very quiet — no loud congestion-style ramp | Hard |

---

## Why the two "hard" faults were hard — a pattern worth remembering

Notice something important: the two easiest faults for DECA
(`congestion_breach`, `tunnel_degradation`) are both faults that
naturally produce a **loud, physical traffic-shape signature** — a lot
of octets, jitter, and loss numbers all visibly moving together. The two
hardest faults (`bgp_route_flap`, `vrf_leakage`) are both faults that are
fundamentally about the network's **control plane and configuration** —
routing decisions and VRF boundaries — which don't necessarily create a
big, loud change in raw traffic volume at all.

This is not a coincidence, and it's the reason both hard faults needed
dedicated, purpose-built protocol-level features (`bgp_flap_count`,
`vrf_route_count`) before DECA could really learn to see them clearly —
a story told in full in Chapters 7 and 8. It is also, honestly, a very
believable and typical pattern in real network operations: quiet,
control-plane misconfigurations are often exactly the kind of problem
that goes unnoticed the longest in a real company's network, precisely
because they don't create the kind of obvious, loud symptoms a busy
traffic dashboard would immediately flag — which is exactly why a system
like DECA, built to notice them anyway, is valuable.

---

## Where each fault could show up on a real network like ISRO's

None of these four faults are specific to our toy lab — they are the
standard failure categories for any organization using an MPLS/VPN-style
private network with BGP and VRF segmentation, which is a very common
design pattern for larger organizations with multiple sites (see Chapter
10 for the full portability discussion). A ground station losing
efficient bandwidth to a control center under heavy load looks like
`congestion_breach`. A satellite downlink's dedicated encrypted path
slowly degrading in quality looks like `tunnel_degradation`. Two data
centers' routing sessions becoming chatty and unstable looks like
`bgp_route_flap`. A misconfigured segmentation boundary letting one
mission's traffic bleed into another mission's network segment looks
like `vrf_leakage` — arguably the single highest-stakes failure mode on
this whole list for an organization handling sensitive, separated
missions.

---

## Continue

Now that you know exactly *what* DECA is looking for, Chapter 4 shows you
*where* it's looking — the physical lab, wired together to make all four
of these faults possible to safely create and study. Continue to
[Chapter 4 — The Lab Setup](04_the_lab_setup.md).
