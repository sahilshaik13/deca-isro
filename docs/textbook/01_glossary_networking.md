# Chapter 1 — Networking Glossary

## How to use this chapter

This chapter is a dictionary. Every word here is a real word used
somewhere in the DECA project. For every word you get four things:

1. **What it means**, in the simplest words possible.
2. **A real-life comparison** — something you already understand from
   everyday life.
3. **Where DECA uses it** — the exact place in this project.
4. **Why it matters** — why we could not skip this concept.

The words are grouped into sections that build on each other, like
chapters inside a chapter. Read it top to bottom the first time; after
that, use it as a lookup dictionary.

---

## Section 1.1 — The absolute basics: what is a network?

### Network

**What it means:** A network is just a group of computers (or computer-like
devices — phones, routers, sensors) that are connected so they can send
messages to each other.

**Real-life comparison:** Think of a group of friends who all have each
other's phone numbers. That group of friends *is* a network. A message
(a text) can travel from any friend to any other friend, sometimes
directly, sometimes by asking a friend-in-the-middle to pass it along.

**Where DECA uses it:** Our whole project watches over a small network:
three tiny computers (Raspberry Pis) plus a laptop, all wired together to
copy what a real company's computer network looks like.

**Why it matters:** Without a network, there is nothing to protect and
nothing for a fault to happen on. Everything else in this book assumes a
network already exists and is carrying real traffic.

---

### Packet

**What it means:** Computers don't send whole messages in one piece. They
chop a message into small pieces called **packets**, send each piece
separately (sometimes by different paths!), and the receiving computer
puts the pieces back together in the right order.

**Real-life comparison:** Imagine mailing a 300-page book to a friend, but
instead of one huge box, you mail each page in its own small envelope,
each envelope numbered "page 4 of 300," "page 5 of 300," and so on. Your
friend collects all the envelopes and puts the pages back in order.

**Where DECA uses it:** Every single number DECA looks at — how much
traffic passed, how much was lost, how bouncy the delay was — is really
just a summary of what happened to millions of these small packets over
a short window of time.

**Why it matters:** Almost every fault DECA detects shows up first as
something going wrong with packets: some get lost, some arrive late, some
arrive out of order, or a route in the network stops sending them the
right way.

---

### IP address

**What it means:** Every device on a network needs its own unique "address"
so other devices know exactly who to send a packet to — the same way
every house needs its own street address so the mail carrier knows where
to deliver a letter. An IP address usually looks like four numbers
separated by dots, for example `192.168.50.10`.

**Real-life comparison:** Exactly like a home address: "123 Main Street."
No two houses on the same street share the same address, or the mail
would get confused about where to go.

**Where DECA uses it:** Every station in our lab has its own IP address.
For example `station1` (one of our Raspberry Pis) is `192.168.50.10`,
`station2` is `192.168.50.20`, `station3` is `192.168.50.30`, and the
laptop that watches everything is `192.168.50.1`. These addresses show up
constantly in our scripts and documentation.

**Why it matters:** DECA needs to know exactly which device a piece of
telemetry (see **Telemetry**, Section 1.5) came from, and IP addresses
(or the hostnames that stand in for them) are how it keeps that straight.

---

### Subnet

**What it means:** A subnet is a smaller "neighborhood" carved out of a
bigger range of IP addresses, so that a group of related devices can be
grouped together and treated as one unit for routing purposes. You will
often see a subnet written like `192.168.50.0/24` — the `/24` is a
technical way of saying "the first 24 bits of the address are fixed, and
only the last part can change," which in this common case means 254
possible addresses in that neighborhood.

**Real-life comparison:** Like a single street inside a big city. "Main
Street" is a small piece of the whole city, and every house on Main
Street shares the first part of its address ("Main Street"), differing
only in house number.

**Where DECA uses it:** Our whole lab network lives on the subnet
`192.168.50.0/24` — every station and the laptop is a "house" on that one
street.

**Why it matters:** Grouping devices into subnets is how real company
networks are organized at scale, and it's part of what makes our small
lab a fair stand-in for a much bigger real network like ISRO's.

---

### Loopback address

**What it means:** A loopback address is a special IP address a device
uses to talk to *itself*, and — in routed networks — it is also often used
as that device's stable, permanent "identity" address for routing
protocols, separate from whichever physical cable it's plugged into.

**Real-life comparison:** Think of it as your legal name versus your
current home address. You might move houses (change your physical
network cable/port), but your name (loopback address) stays the same, so
people can always find "you" even if your street address changes.

**Where DECA uses it:** Each of our three stations has its own loopback
address used as its router identity: `station1` is `10.1.1.1`, `station2`
is `10.1.2.1`, `station3` is `10.1.3.1`. These loopback addresses are what
the routing protocols (see **BGP** and **OSPF** below) use to recognize
each station.

**Why it matters:** One of DECA's four faults, `bgp_route_flap`, is
specifically about instability with a routing session identified by a
loopback address (`10.1.3.1`) — so understanding loopback addresses is a
building block for understanding that fault.

---

### Hostname

**What it means:** A hostname is a friendly, human-readable name for a
device, used instead of remembering its numeric IP address. For example,
`station1` is a hostname; `192.168.50.10` is its IP address.

**Real-life comparison:** Like calling your friend "Alex" instead of
their government ID number. Both point to the same person, but the name
is much easier for humans to use and remember.

**Where DECA uses it:** Everywhere. Our scripts say `ssh station1`, not
`ssh 192.168.50.10`, because a small file called `~/.ssh/config` (see
**SSH**, Section 1.6) already knows which hostname maps to which IP
address.

**Why it matters:** We actually hit a real bug caused by hostnames — one
of our old scripts tried to talk to `s1`/`s2`/`s3`, hostnames that were
never actually set up, instead of the real `station1`/`station2`/
`station3`. See Chapter 7 for more "we made this mistake and fixed it"
stories, and the consolidated `lab/deca_ops.sh` script for the fix.

---

## Section 1.2 — Getting a packet from A to B: routing

### Router

**What it means:** A router is a device whose whole job is to look at
incoming packets and decide which direction to send them next, so they
eventually reach their destination.

**Real-life comparison:** Like a helpful person standing at a busy
intersection, looking at where each car wants to go, and pointing it down
the correct road.

**Where DECA uses it:** In our lab, each of our three Raspberry Pi
stations acts as a router — a piece of free software called **FRR** (see
Section 1.4) runs on each Pi and does the actual routing decision-making.

**Why it matters:** Nearly every fault DECA detects is, underneath, a
problem with routers making wrong decisions, or the paths between routers
getting overloaded or corrupted.

---

### Routing table

**What it means:** A routing table is a router's own private list of
"if a packet wants to go to address X, send it out this direction." A
router builds this table by talking to its neighbor routers.

**Real-life comparison:** Like a signpost at that same intersection, with
arrows saying "Downtown → left, Airport → right, Suburb → straight." The
router keeps its own personal signpost and updates it as roads open or
close.

**Where DECA uses it:** One of our four faults, `vrf_leakage`, is directly
about routes showing up in the *wrong* routing table — specifically the
wrong **VRF** (see Section 1.4) — where they should never have appeared.
We literally count how many routes are in a particular routing table as
one of our detection signals (`vrf_route_count`).

**Why it matters:** If a routing table has the wrong entries, packets can
be sent to the wrong place entirely, which is a serious security and
reliability problem in a real network.

---

### OSPF (Open Shortest Path First)

**What it means:** OSPF is a set of rules ("protocol") that routers use to
automatically discover their neighbors and figure out the shortest path
to every other point on the network, without a human manually typing in
every route.

**Real-life comparison:** Imagine every intersection worker in a city
constantly shouting to their neighboring intersections "here's what I can
see nearby," and using that shared shouting to automatically figure out
the fastest route across the whole city — without anyone drawing a paper
map by hand.

**Where DECA uses it:** Our three stations run OSPF to discover each
other automatically. Our health-check scripts specifically check for
"OSPF full adjacency," meaning two routers have fully agreed on the map.

**Why it matters:** OSPF is the foundation everything else (BGP, MPLS,
tunnels) is built on top of — if OSPF is broken, nothing above it works
either.

---

### BGP (Border Gateway Protocol)

**What it means:** BGP is a different, higher-level protocol used to share
routing information between bigger groups of routers, especially when
those groups belong to different organizations. It's the protocol that
holds together the entire global internet — every company's network
talks to every other company's network using BGP.

**Real-life comparison:** If OSPF is like intersection workers figuring
out streets within one city, BGP is like city mayors from *different
cities* agreeing on which highways connect their cities to each other, at
a much bigger scale.

**Where DECA uses it:** Our stations use BGP to exchange routes for
private/VPN traffic (see **VRF** and **VPN**). One of our four detected
faults, `bgp_route_flap`, is entirely about BGP sessions becoming unstable
— constantly resetting or "flapping" (going up and down) instead of
staying calm and steady.

**Why it matters:** A flapping BGP session can make parts of a network
disappear and reappear unpredictably, which is exactly the kind of
disruptive, hard-to-diagnose problem DECA exists to catch early.

---

### BGP neighbor / BGP session / BGP peer

**What it means:** Two routers that have agreed to share BGP routing
information with each other are called "neighbors" or "peers," and the
ongoing conversation between them is called a "session."

**Real-life comparison:** Like two neighboring countries that have signed
a treaty to constantly update each other about their road conditions.

**Where DECA uses it:** In our lab, `station1`'s BGP neighbor is
`10.1.3.1` (`station3`'s loopback address). Our health checks specifically
look for this neighbor being "established" (the treaty is active and
healthy).

**Why it matters:** The `bgp_route_flap` fault is measured by watching
exactly this relationship for signs of instability.

---

### Route flap

**What it means:** A "flap" is when a route (or a BGP session) rapidly
goes up, then down, then up again, over and over, instead of staying
stable. Constant flapping is disruptive because every flap forces routers
to recalculate paths.

**Real-life comparison:** Like a light switch someone keeps flicking on
and off rapidly instead of leaving it in one position — the lights never
settle, and anyone depending on steady light gets frustrated or confused.

**Where DECA uses it:** This is literally the name of one of our four
fault classes: `bgp_route_flap`. We simulate it in the lab by repeatedly
telling a router to "soft-clear" (refresh) its BGP session with a
neighbor, which forces route information to be resent, mimicking the kind
of chatty instability a real flap would cause.

**Why it matters:** In a real network, frequent flaps can be an early
warning sign of a failing device, a bad cable, or a misconfiguration —
catching it early (rather than after it causes an outage) is valuable.

---

### Route refresh

**What it means:** A route refresh is a specific BGP message that asks a
neighbor to resend its full set of routes, without fully breaking the
underlying connection. It's less disruptive than a full session reset,
but if it happens over and over, it's still a sign of instability.

**Real-life comparison:** Like repeatedly asking a librarian "can you say
that whole list of book titles again?" instead of walking out and
re-entering the library each time. It doesn't restart the whole
relationship, but doing it constantly is still a sign something's off.

**Where DECA uses it:** This is an important one because we found a real
mistake here (told in full in Chapter 7). Our simulated BGP flap fault
uses a command that triggers **route refreshes**, not full session resets.
We initially built a detector that watched for session resets
(`connectionsDropped`), which never moved, because that's the wrong
counter for what we were actually causing. Once we found this, we built
a new detector that watches the correct counter:
`routeRefreshSent`/`routeRefreshRecv` — and it worked immediately.

**Why it matters:** This is a perfect, real example of why you must
verify that your detector is actually looking at the right thing, rather
than assuming a plausible-sounding counter is the correct one.

---

### AS (Autonomous System) / AS number

**What it means:** An Autonomous System is a network (or group of
networks) under one organization's control, identified by a unique number
so that BGP can tell different organizations' networks apart.

**Real-life comparison:** Like a country's flag and ID code at the
United Nations — it lets every other country's diplomats (BGP routers)
know exactly which country (network) they're talking to.

**Where DECA uses it:** Our lab uses AS number `65001` for its internal
BGP setup (you'll see it in config commands like
`router bgp 65001 vrf vrf-mission`).

**Why it matters:** It's mostly plumbing you need for BGP to work at all
— but it also matters because one of our real bugs (Chapter 7, mistake
#6) involved a leftover, incorrectly-targeted BGP configuration stanza
under this AS number that had to be manually cleaned up.

---

### MPLS (Multiprotocol Label Switching)

**What it means:** MPLS is a technique that lets routers forward packets
using a short "label" stuck onto the packet, instead of looking at the
full destination address every single time. This makes forwarding faster
and lets a network carry many different customers' private traffic over
one shared set of routers, keeping each customer's traffic properly
separated.

**Real-life comparison:** Like a coat-check ticket at a restaurant. Instead
of the staff describing your exact coat ("navy blue wool coat with brass
buttons") every time, they just look at ticket number "42" and instantly
know which coat to grab.

**Where DECA uses it:** Our lab's whole design (a "CE-PE-CE" topology,
explained fully in Chapter 4) is deliberately built to copy how real
MPLS-based company networks work, because that's the industry-standard
way large organizations (very plausibly including ISRO) build private,
segmented networks.

**Why it matters:** All four of our fault classes are the standard,
real-world fault categories for exactly this kind of MPLS network — they
are not made-up problems specific to our toy lab.

---

### LDP (Label Distribution Protocol)

**What it means:** LDP is the protocol routers use to agree with each
other on which "labels" (see **MPLS** above) mean what, so that when one
router hands a packet with label "42" to the next router, that next
router also knows what label "42" means.

**Real-life comparison:** Like two neighboring coat-check restaurants
agreeing in advance "our ticket numbers won't clash, and here's how we'll
hand off a coat if a customer moves between our two restaurants."

**Where DECA uses it:** Our health-check scripts check that "LDP labels"
are "ACTIVE & POPULATED" on our routers — meaning the labels have been
successfully agreed upon and are ready to use.

**Why it matters:** If LDP fails, MPLS forwarding breaks even if the
basic routing (OSPF) is fine — it's one more layer that has to work for
the whole system to work, and one more thing our diagnostics specifically
check.

---

## Section 1.3 — Private, segmented, and encrypted traffic

### VRF (Virtual Routing and Forwarding)

**What it means:** A VRF is like a separate, isolated routing table living
inside the same physical router. A single router can have several VRFs
at once, each with its own private set of routes, and — critically —
traffic in one VRF is not supposed to be able to see or reach traffic in
a different VRF, even though it's the same physical hardware.

**Real-life comparison:** Imagine one large office building that is
actually split into several completely separate companies' offices, each
with its own locked front door, its own separate mail slots, and its own
separate phone directory — even though they all share the same building,
elevators, and electricity. A VRF is that "separate company's floor"
inside one shared router.

**Where DECA uses it:** This is central to our whole project. Our lab
uses a VRF called `vrf-mission` for the main "customer" traffic between
our simulated customer sites. We also (accidentally, then deliberately)
use a second VRF, `vrf-admin`, in our `vrf_leakage` fault simulation.

**Why it matters:** One of our four fault classes, `vrf_leakage`, is
*entirely* about a route incorrectly crossing from one VRF into another
— exactly like mail from Company A's floor accidentally getting delivered
to Company B's floor. This is a serious real-world security problem
(traffic that should be private becomes visible to the wrong party), and
detecting it is one of DECA's most important jobs.

---

### VRF leakage

**What it means:** VRF leakage is when a route (a path to reach some
destination) that should only exist inside one VRF's private routing
table accidentally gets copied ("leaked") into a *different* VRF's
routing table, letting traffic cross a boundary that was supposed to be
sealed.

**Real-life comparison:** Using the office-building comparison above:
imagine someone accidentally photocopies Company A's private client list
and slips it under Company B's door. Now Company B's employees can see
information they were never supposed to have access to.

**Where DECA uses it:** This is one of our four fault classes:
`vrf_leakage`. We deliberately trigger a controlled version of this in
our lab (using a setting called a Route Target — see below) so DECA can
learn what it looks like in the telemetry, then we test whether DECA can
catch it.

**Why it matters:** This fault was the subject of one of our biggest real
mistakes in the whole project (Chapter 7, mistake #6) — for a long time,
our "leak" simulation was accidentally targeting a VRF name that didn't
even exist on the real routers, so we were training the model on a fake
version of the problem. Fixing this was a major turning point.

---

### Route Target (RT)

**What it means:** A Route Target is a special tag attached to a route
that controls which VRFs are allowed to "import" (accept) that route. It's
the actual mechanism, under the hood, that either keeps VRFs properly
separated or — if misconfigured — causes a VRF leak.

**Real-life comparison:** Like a mailing label that says "Deliver only to
Company A's mail slot." If someone changes that label to also say
"...and also Company B's mail slot," now both companies get the mail —
that's the leak.

**Where DECA uses it:** Our `vrf_leakage` fault injector works by
manipulating Route Target settings so that routes that belong in
`vrf-mission` get improperly imported into (or exported to) the separate
VRF used for the fault simulation.

**Why it matters:** Understanding Route Targets is understanding the
actual mechanical cause of a VRF leak — it's not a vague "something broke,"
it's a specific, well-known misconfiguration category in real networks.

---

### VPN (Virtual Private Network)

**What it means:** A VPN is a way to make two (or more) separate physical
locations behave as if they're on one shared, private network — even
though their traffic is actually traveling over a public or shared
network in between.

**Real-life comparison:** Like a private, sealed tube running underground
between two office buildings across town, so an employee can walk from
one building to the other without ever stepping onto the public
sidewalk, even though the tube physically runs alongside public streets.

**Where DECA uses it:** Our lab's whole "CE-PE-CE" design (explained in
Chapter 4) simulates two customer sites connected by a VPN across a
shared provider network — exactly the setup a real company (or ISRO's
own regional sites) would use.

**Why it matters:** All four of DECA's fault classes are faults that can
happen to exactly this kind of VPN-carrying network — congestion, tunnel
problems, BGP flaps, and VRF leaks are the standard failure modes
operators of real VPN-based networks have to watch for.

---

### IPsec

**What it means:** IPsec is a specific technology used to build a secure,
encrypted tunnel (see **Tunnel** below) between two points on a network,
so that even if someone intercepted the traffic in the middle, they
couldn't read it.

**Real-life comparison:** Like that private underground tube from the VPN
example above, but now imagine the tube's walls are also made of a
special material that turns anyone's words into an unreadable secret code
the instant they enter the tube, and back into normal words only once
they reach the other end.

**Where DECA uses it:** Our two "customer edge" stations (`station1` and
`station2`) run an IPsec tunnel between them, named `deca-sdwan` in our
configuration, to carry the simulated customer traffic securely.

**Why it matters:** One of DECA's four fault classes, `tunnel_degradation`,
is about this exact kind of secure tunnel getting worse (more delay, more
lost packets) without fully breaking — a realistic and important problem
to catch early.

---

### Tunnel

**What it means:** In networking, a "tunnel" is a general term for any
technique that wraps one network connection inside another, so that
traffic can travel through (or across) a network it wouldn't normally fit
into or be allowed onto directly — often while also being encrypted (see
**IPsec**) or having its own separate routing behavior (see **MPLS**).

**Real-life comparison:** Like a train that gets loaded onto a ferry to
cross an ocean. The train doesn't change what it is; it's just being
carried, wrapped inside the ferry, for a specific stretch of its journey.

**Where DECA uses it:** Our lab's IPsec connection between `station1` and
`station2` is a tunnel. One of our four fault classes, `tunnel_degradation`,
happens when this tunnel's quality (delay, jitter, packet loss) gets
worse.

**Why it matters:** Tunnel problems are sneaky because the tunnel doesn't
necessarily go fully offline — it can just get gradually worse, which is
harder for a human to notice quickly but exactly the kind of gradual
change DECA's "rolling window" features (Chapter 2) are designed to
catch.

---

### Tunnel degradation

**What it means:** This is the specific name of one of DECA's four fault
classes: the tunnel (see above) is still "up" and technically working,
but its quality has gotten worse — more delay, more jitter, more dropped
packets — without a full, obvious outage.

**Real-life comparison:** Like a phone call that hasn't dropped, but has
gotten so crackly and delayed that a normal conversation is becoming
difficult, even though technically the call is "still connected."

**Where DECA uses it:** We simulate this in the lab by deliberately adding
artificial delay, jitter, and packet loss to the tunnel's traffic using a
tool called `netem` (Section 1.7), then teach DECA to recognize the
telemetry pattern this creates.

**Why it matters:** This is one of the two "easier" fault classes for
DECA to detect well (the other being `congestion_breach`) — its telemetry
signature (jitter, latency, and loss all rising together) is clear and
strong, unlike the sneakier `bgp_route_flap` and `vrf_leakage` faults.

---

## Section 1.4 — The router software we actually use

### FRR (Free Range Routing)

**What it means:** FRR is a free, open-source software package that turns
an ordinary computer (like our Raspberry Pis) into a real router capable
of running protocols like OSPF, BGP, and LDP.

**Real-life comparison:** Like installing a professional "traffic
director" training and rulebook onto an ordinary person, turning them
into a certified intersection traffic controller.

**Where DECA uses it:** FRR runs on all three of our Raspberry Pi
stations. Every routing decision, every BGP session, every VRF, and every
route we ever look at in this whole project passes through FRR.

**Why it matters:** FRR is the exact same category of software real
network equipment vendors build their commercial routers around — using
it makes our lab a much more honest, realistic stand-in for a real
company's routers than a toy simulation would be.

---

### vtysh

**What it means:** `vtysh` is the command-line tool used to talk directly
to FRR — to look at its current state (routes, BGP sessions, VRF tables)
or to change its configuration.

**Real-life comparison:** Like the walkie-talkie a supervisor uses to
directly ask a traffic controller "what's your current status?" or to
give them a new instruction.

**Where DECA uses it:** Constantly. Nearly every diagnostic script and
every fault-injection script in this project uses a `vtysh` command at
some point — for example, `vtysh -c "show bgp neighbor 10.1.3.1 json"` is
exactly how we discovered the real BGP route-refresh counters described
in Chapter 7.

**Why it matters:** `vtysh` is our direct window into "the actual truth"
of what the router is doing, which is why it was the tool we used, over
and over, to verify our assumptions and catch real bugs.

---

### CE (Customer Edge)

**What it means:** In a typical provider network design, "Customer Edge"
refers to the router (or virtual router) that sits at the very edge of a
customer's own site — the last hop before traffic leaves the customer's
control and enters the provider's shared network.

**Real-life comparison:** Like the front door of your own house — the
last point that's fully "yours" before you step out onto the shared
public street.

**Where DECA uses it:** Our lab has two simulated CE routers, called
`ce-a` and `ce-b`, implemented as **network namespaces** (see below)
living on `station1` and `station2`.

**Why it matters:** The CE-PE-CE design is the standard way real MPLS/VPN
networks are described and built, which is part of why our lab's fault
classes translate honestly to a real network like ISRO's.

---

### PE (Provider Edge)

**What it means:** "Provider Edge" is the router at the edge of the
*network provider's* side — the first router inside the shared provider
network that a customer's traffic reaches after leaving their own CE
router.

**Real-life comparison:** Continuing the house comparison: the PE is like
the nearest public mailbox or post office branch — the first point of the
shared public postal system your letter reaches after leaving your own
front door.

**Where DECA uses it:** `station1` and `station2` both act as PE routers
in our lab (each also hosting its own CE router as a network namespace,
described above).

**Why it matters:** PE routers are where most of the interesting action
happens — BGP, VRFs, MPLS labels, and tunnels are all things PE routers
handle, and correspondingly, most of DECA's fault classes are things that
happen at or because of PE routers.

---

### CORE

**What it means:** In our lab's specific naming, "CORE" refers to the
router in the middle of the network that doesn't directly connect to any
customer, but instead exists purely to relay traffic between the PE
routers.

**Real-life comparison:** Like a large central sorting hub in the postal
system that never talks to individual customers directly, but makes sure
mail correctly flows between different post office branches.

**Where DECA uses it:** `station3` plays this role in our lab. It's
sometimes called a "P router" (Provider core router) in general
networking terminology.

**Why it matters:** `station3`'s loopback address, `10.1.3.1`, is the BGP
neighbor address used throughout our `bgp_route_flap` fault simulation —
so understanding CORE's role explains *why* that particular address shows
up so often.

---

### Network namespace (netns)

**What it means:** A network namespace is a way for one single physical
computer to pretend it contains several completely separate, isolated
"mini-computers," each with its own network setup (its own IP addresses,
its own routing table), even though they're all really running on the
same physical hardware.

**Real-life comparison:** Like one large building that has been divided
by soundproof walls into several completely separate apartments, each
with its own front door, its own address, and its own mailbox — even
though it's structurally one building.

**Where DECA uses it:** Our simulated customer routers, `ce-a` (on
`station1`) and `ce-b` (on `station2`), are both network namespaces —
this is how we fit "customer router" and "provider router" onto the same
physical Raspberry Pi without them interfering with each other.

**Why it matters:** Without network namespaces, we would have needed
twice as many physical devices to build the same lab topology — this
Linux feature is what let us build a realistic multi-router network
cheaply, using only three small computers.

---

### Veth (virtual Ethernet pair)

**What it means:** A veth pair is two virtual network cables that are
permanently connected to each other at both ends — like a length of
Ethernet cable that exists purely in software, used to connect two
network namespaces (or a namespace to the main system) together.

**Real-life comparison:** Like a pretend telephone line strung between two
apartments inside that same divided building from the network namespace
example — it lets the two separate apartments (namespaces) talk to each
other even though there's no real physical wire between them.

**Where DECA uses it:** Every connection between a PE router (`station1`
or `station2`) and its simulated CE customer router (`ce-a` or `ce-b`) is
a veth pair, for example `veth-pe-cea` / `veth-cea-pe`.

**Why it matters:** This is a foundational plumbing piece that makes the
whole simulated customer-to-provider connection possible — without it,
the CE and PE "sides" inside one physical Pi couldn't talk to each other
at all.

---

## Section 1.5 — Measuring network health: the numbers DECA reads

### Telemetry

**What it means:** Telemetry is the general word for measurements
automatically collected from a distant device and sent somewhere else to
be watched or recorded — as opposed to a human manually walking over and
checking.

**Real-life comparison:** Like a fitness tracker on your wrist constantly
sending your heart rate to an app on your phone, without you needing to
manually check your own pulse every few minutes.

**Where DECA uses it:** This word describes almost everything DECA reads:
octets sent/received, jitter, packet loss, BGP update counts, VRF route
counts — all of it is telemetry, automatically collected from our
stations and delivered to our monitoring system.

**Why it matters:** DECA cannot work at all without a steady, reliable
stream of telemetry — it is the raw material every single feature and
every single prediction is built from.

---

### Throughput

**What it means:** Throughput is how much data actually gets through a
network connection in a given amount of time — usually measured in bits
or bytes per second.

**Real-life comparison:** Like how many cars actually make it across a
bridge per minute — not how many *want* to cross, but how many actually
do.

**Where DECA uses it:** We track throughput-related numbers like
`ifInOctets` and `ifOutOctets` (bytes seen going in/out of a network
interface) as core telemetry signals.

**Why it matters:** A drop or a suspicious rise in throughput is one of
the earliest signs of both `congestion_breach` and, in a subtler way,
`vrf_leakage` and `tunnel_degradation`.

---

### Octets

**What it means:** "Octets" is simply the formal networking word for
"bytes" (a byte is 8 bits, hence "oct-"). `ifInOctets` means "bytes
received on this interface"; `ifOutOctets` means "bytes sent."

**Real-life comparison:** Just a technical synonym, like how a doctor
says "myocardial infarction" instead of "heart attack" — same thing,
more formal word.

**Where DECA uses it:** `ifInOctets` and `ifOutOctets` are two of the core
metrics scraped from every station and fed into DECA's feature
engineering (Chapter 2 and Chapter 5).

**Why it matters:** These are two of the oldest, most basic, and most
reliable measurements in all of networking — nearly every router and
monitoring tool in the world can report them.

---

### Bandwidth

**What it means:** Bandwidth is the *maximum possible* throughput a
connection could carry — the size of the pipe, not how much water is
currently flowing through it.

**Real-life comparison:** The difference between a highway's total number
of lanes (bandwidth — the maximum capacity) and how many cars are
actually driving on it right now (throughput — the current usage).

**Where DECA uses it:** Our lab deliberately limits bandwidth on some
links (using a tool called `tbf`, Section 1.7) to simulate real-world
capacity limits and trigger the `congestion_breach` fault.

**Why it matters:** Congestion (our `congestion_breach` fault class)
specifically happens when throughput tries to exceed available bandwidth
— understanding the difference between the two words is key to
understanding that fault.

---

### Congestion

**What it means:** Congestion is what happens when more traffic is trying
to use a network connection than that connection has capacity (bandwidth)
for. When this happens, packets start to queue up, get delayed, or get
dropped entirely.

**Real-life comparison:** Exactly like rush-hour traffic on a highway —
when too many cars try to use a road at once, everyone slows down, and
some drivers may be forced to pull over entirely (dropped packets).

**Where DECA uses it:** This is one of DECA's four fault classes:
`congestion_breach`. We simulate it by artificially limiting how much
traffic a link can carry, then pushing more traffic than that limit
allows.

**Why it matters:** Congestion is one of the two "easier" faults for DECA
to detect (along with `tunnel_degradation`) because its telemetry
signature — throughput rising, then flattening at a ceiling, with loss and
delay increasing — is clear and strong.

---

### Congestion breach

**What it means:** This is the exact, formal name of the fault class in
our system: the moment traffic demand exceeds the available capacity of
a link hard enough that the network's normal behavior "breaches" (crosses
past) its healthy operating range.

**Where DECA uses it / why it matters:** See **Congestion** directly
above — this is simply the specific technical name used throughout our
code and documentation for that same real-world event.

---

### Latency

**What it means:** Latency is how long it takes a single packet to travel
from where it starts to where it's going — usually measured in
milliseconds (a millisecond is one thousandth of a second).

**Real-life comparison:** Like how long it takes for a shout across a
canyon to echo back — the time delay between "sending" and "arriving."

**Where DECA uses it:** Latency is one of the signals that rises during
`tunnel_degradation`.

**Why it matters:** Rising latency, especially combined with rising
jitter (below), is one of the clearest warning signs of a tunnel or
overall path quality problem.

---

### Jitter

**What it means:** Jitter is how *inconsistent* the latency is — not "how
slow is it," but "how much does the slowness vary from one packet to the
next." Low jitter means every packet takes about the same amount of time;
high jitter means some packets are fast and others are unpredictably
slow.

**Real-life comparison:** Imagine a bus that is supposed to arrive every
10 minutes. Low jitter is a bus that reliably comes every 10 minutes,
give or take a few seconds. High jitter is a bus that sometimes comes in
2 minutes and sometimes in 25 minutes — even if the *average* is still
about 10 minutes, the unpredictability itself is the problem.

**Where DECA uses it:** `jitter_ms` (jitter measured in milliseconds) is
one of DECA's core telemetry signals, and it is one of the strongest
signals for detecting `tunnel_degradation`.

**Why it matters:** High jitter is especially damaging for real-time
traffic like voice or video calls, where even small unpredictable delays
cause noticeable stutter — this is why it's such an important signal to
watch.

---

### Packet loss

**What it means:** Packet loss is the percentage of packets that are sent
but never arrive at all — they simply vanish somewhere along the way,
usually because a router along the path was too overloaded (see
**Congestion**) to hold onto them, or a link was too degraded to carry
them successfully.

**Real-life comparison:** Like mailing 100 letters and only 95 arriving —
the other 5 simply got lost in the postal system somewhere and are gone
for good (in most network setups, lost packets are not automatically
resent by the network itself).

**Where DECA uses it:** `packet_loss_pct` is one of DECA's core telemetry
signals, tracked alongside jitter and latency, and it rises during both
`congestion_breach` and `tunnel_degradation`.

**Why it matters:** Packet loss directly and immediately hurts the user
experience of whatever application is using the network — video calls
freeze, file transfers stall and retry, and web pages load slowly.

---

### PromQL query examples in this project

The following are the actual measurement queries ("PromQL," explained in
Section 1.5's later entries) DECA uses to pull specific numbers out of
its monitoring system. You don't need to memorize the syntax — just
notice that each one is asking for one specific, named number from one
specific station:

- `vrf_route_count_value{vrf="vrf-admin"}` — "how many routes are
  currently in the `vrf-admin` VRF's table?" — the core `vrf_leakage`
  detection signal.
- `bgp_flap_count_value{neighbor="10.1.3.1"}` — "how many route-refresh
  messages have been sent/received with this BGP neighbor?" — the core
  `bgp_route_flap` detection signal.

---

## Section 1.6 — How we remotely operate the lab

### SSH (Secure Shell)

**What it means:** SSH is a way to securely log into and control a distant
computer from your own computer, as if you were typing directly on its
keyboard, with all communication encrypted so no one else can see what
you're typing or what the distant computer sends back.

**Real-life comparison:** Like a secure, private phone line to a
technician sitting inside a distant building, letting you tell them
exactly what to type on their keyboard, with the conversation impossible
for anyone else to listen in on.

**Where DECA uses it:** Every single one of our fault-injection and
health-check scripts uses SSH to reach `station1`, `station2`, and
`station3` from the laptop that runs our experiments.

**Why it matters:** Without SSH, we would need to physically walk up to
each Raspberry Pi and type commands directly on it every single time —
SSH is what makes automated, repeatable experiments possible at all.

---

### sudo

**What it means:** `sudo` is a command that temporarily grants a regular
user special "administrator" powers to run a specific command that
normal users aren't allowed to run — usually after typing a password to
prove they're allowed to do this.

**Real-life comparison:** Like a regular employee asking a manager "can
you unlock this one specific supply closet for me?" — the employee
doesn't get a master key to everything, just permission for that one
task.

**Where DECA uses it:** Almost every command that changes something on a
router (adding a route, restarting a service, reading certain FRR state)
requires `sudo`. Our consolidated `lab/deca_ops.sh` script asks for this
password exactly once, then reuses it for every command that needs it.

**Why it matters:** This is a basic security principle — normal
day-to-day operations shouldn't have unlimited power by default, only
the specific power needed for the specific task, only when explicitly
requested.

---

### systemd / service / daemon

**What it means:** A "service" (also called a "daemon") is a program that
runs continuously in the background on a computer, rather than something
a person actively watches. `systemd` is the system on modern Linux
computers (like our Raspberry Pis) that starts, stops, and manages all
of these background services — including making sure they restart
automatically after a crash or reboot.

**Real-life comparison:** Like a building manager who makes sure the
heating system, the elevators, and the security cameras all turn on
automatically every morning and get restarted immediately if any of them
break down — without a human needing to walk over and flip a switch.

**Where DECA uses it:** FRR, Telegraf (below), our custom network
namespace setup, and our own "watchdog" self-healing script are all
`systemd` services on our stations.

**Why it matters:** This is what lets our lab recover automatically after
a power outage or reboot, without a human needing to manually restart
every piece by hand — a real, and quite important, piece of reliability
engineering.

---

## Section 1.7 — Tools we use to simulate and generate traffic

### netem

**What it means:** `netem` ("network emulation") is a Linux tool that can
deliberately add fake delay, jitter, or packet loss to a network
connection, on purpose, for testing.

**Real-life comparison:** Like a movie special-effects team deliberately
adding fake rain and wind to a scene, on a day that's actually perfectly
sunny, so they can test how actors and equipment react to bad weather —
without needing to wait for a real storm.

**Where DECA uses it:** We use `netem` to deliberately create the
`tunnel_degradation` fault (and to add a bit of realistic shape to the
`vrf_leakage` fault) by injecting artificial jitter, delay, and packet
loss.

**Why it matters:** Without a controlled way to create fake, repeatable
network problems, we would have to wait around for real faults to happen
naturally in order to collect any training data — which could take
months or years, and wouldn't be repeatable for testing.

---

### tbf (Token Bucket Filter)

**What it means:** `tbf` is a Linux tool that limits how much traffic can
pass through a connection per second, deliberately creating a bandwidth
ceiling.

**Real-life comparison:** Like a security guard at a venue's entrance who
only lets a fixed number of people through the door per minute, no
matter how many people are waiting outside — creating a deliberate
bottleneck.

**Where DECA uses it:** We use `tbf` to create the `congestion_breach`
fault, by capping a link's capacity below what our simulated traffic is
trying to push through it.

**Why it matters:** This is the specific tool that lets us reliably and
repeatably create real, physical network congestion in the lab, on
demand, for training data.

---

### iperf3

**What it means:** `iperf3` is a tool used to deliberately generate a
measurable, controllable stream of network traffic between two points —
useful for testing how much throughput a connection can actually carry.

**Real-life comparison:** Like a garden hose you turn on at a known, fixed
flow rate specifically so you can test how well a drainage pipe handles
that amount of water.

**Where DECA uses it:** We run `iperf3` between our simulated customer
routers (`ce-a` and `ce-b`) to generate realistic background traffic and
to help trigger the `congestion_breach` fault against our `tbf` bandwidth
cap.

**Why it matters:** Without deliberately generated traffic, our
`congestion_breach` simulation would have nothing to actually congest —
`iperf3` is the "cars on the highway" that create the traffic jam.

---

### ping

**What it means:** `ping` is a simple tool that sends a tiny test message
to another device and measures how long it takes to get a reply — a
basic "are you there, and how fast can you respond?" check.

**Real-life comparison:** Like shouting "hello?" into a canyon and timing
how long it takes for the echo to come back — a simple, universal way to
check "is anyone there, and roughly how far away are they?"

**Where DECA uses it:** Nearly every health check in this project ends
with a `ping` from `ce-a` to `ce-b`'s address (`10.100.2.1`) as the final
proof that the whole path — through the tunnel, through BGP, through the
VRF — is actually working end to end.

**Why it matters:** All the individual pieces (BGP, OSPF, VRF, IPsec)
could each individually report "healthy" while the full end-to-end path
is still broken — the final `ping` test is what confirms the *whole*
system actually works together, not just each piece in isolation.

---

## Section 1.8 — Monitoring: how DECA actually gets its numbers

### Telegraf

**What it means:** Telegraf is a small program that runs on a device
(like our Raspberry Pi stations) and continuously collects measurements
(telemetry, see Section 1.5), then makes those measurements available for
some other system to come and read.

**Real-life comparison:** Like a hotel's smart thermostat that
continuously measures the room temperature and makes that number
available on a small display — it doesn't decide anything by itself, it
just measures and reports.

**Where DECA uses it:** Telegraf runs on all three of our stations. It's
also what we extended, twice, to add brand-new custom measurements —
`vrf_route_count` and `bgp_flap_count` — that didn't exist before we
built them.

**Why it matters:** Telegraf is the very first link in the whole chain
that eventually feeds DECA's machine learning model — if Telegraf isn't
collecting a number, DECA has no way to ever learn from it.

---

### Prometheus

**What it means:** Prometheus is a monitoring system that regularly visits
("scrapes," see below) many different devices' Telegraf endpoints,
collects all their numbers, and stores them over time so they can be
looked up, graphed, or queried later — including "what was this number 20
minutes ago?"

**Real-life comparison:** Like a nurse's station in a hospital that
regularly walks around to every patient's room, reads their vital-sign
monitors, and writes every reading down in a shared chart — so a doctor
can later look back and see the whole history for any patient, not just
right now.

**Where DECA uses it:** Prometheus runs on our laptop and regularly visits
all three stations' Telegraf endpoints. Every single measurement DECA
ever trains on or reacts to live has passed through Prometheus first.

**Why it matters:** Without a central place to store and query
measurements over time, we couldn't ever ask "how did this number change
over the last 10 minutes," which is exactly the kind of question DECA's
"rolling window" features (Chapter 2) depend on being able to answer.

---

### Scrape / scraping

**What it means:** "Scraping" is the specific word for Prometheus's act of
visiting a Telegraf endpoint and pulling in its current measurements.
Prometheus does this on a regular schedule (in our lab, every 5 seconds).

**Real-life comparison:** That same nurse's regular walk around the
hospital, at a fixed schedule (say, every 15 minutes) — each individual
walk-and-check is one "scrape."

**Where DECA uses it:** Our whole system depends on scrapes happening
reliably every 5 seconds. When a scrape fails (for example, because
Telegraf crashed on a station), our health-check scripts specifically
detect and report this.

**Why it matters:** A missed scrape is a gap in DECA's vision — if
scraping breaks during a real fault, DECA might miss the fault entirely,
which is why our diagnostic tooling checks scrape health so carefully.

---

### PromQL (Prometheus Query Language)

**What it means:** PromQL is the specific language used to ask
Prometheus a question, like "what is the current value of this specific
measurement, on this specific station?"

**Real-life comparison:** Like a specific, structured way of asking that
nurse's station "show me patient #4's heart rate chart from the last
hour" instead of just vaguely saying "show me some numbers."

**Where DECA uses it:** Every metric DECA cares about is defined as a
specific PromQL query in our code, for example
`max by (host) (vrf_route_count_value{vrf="vrf-admin"})` — "give me the
`vrf_route_count_value` number, specifically for the `vrf-admin` VRF, one
value per station."

**Why it matters:** Getting a PromQL query exactly right matters a lot —
Chapter 7 tells the story of how a subtly wrong VRF name in a query (and
in the underlying fault simulation) caused a real, serious bug that went
undetected for a long time.

---

### Metric

**What it means:** A "metric" is the general word for any single, named
kind of measurement being tracked over time — for example, "packet loss
percentage" is a metric, and at any given moment it has one current
value.

**Real-life comparison:** Like "body temperature" being a specific kind
of vital sign a hospital tracks — the metric is the category
("temperature"), while a specific reading ("98.6°F, right now") is one
data point of that metric.

**Where DECA uses it:** `ifInOctets`, `ifOutOctets`, `jitter_ms`,
`packet_loss_pct`, `bgp_update_rate`, `vrf_route_count`, and
`bgp_flap_count` are the core metrics DECA is built around.

**Why it matters:** Every metric is a potential clue. DECA's whole job is
to look at how several metrics move together over time and decide what
kind of fault (if any) that combined movement represents.

---

### Time series

**What it means:** A time series is simply a metric's value recorded over
and over across time, forming a sequence — "at 10:00 it was 5, at 10:05
it was 8, at 10:10 it was 6," and so on.

**Real-life comparison:** Like a hospital's temperature chart for one
patient over a whole week — not just one number, but the whole shape of
how it changed over time.

**Where DECA uses it:** Everything DECA reads is fundamentally a time
series. Its most important trick (Chapter 2's "feature engineering") is
built entirely on looking at the *shape* of these time series — is a
number rising, falling, jumping suddenly, or staying flat — rather than
just looking at one single value in isolation.

**Why it matters:** A single number, by itself, often doesn't tell you
much (is 40 megabits per second "high" or "low"? It depends!). The
*shape* of the time series around that number — is it climbing fast? is
it wobbling more than usual? — is what actually distinguishes a healthy
network from a network with a developing fault.

---

## Section 1.9 — Time, logs, and small file formats you'll see

### UTC (Coordinated Universal Time)

**What it means:** UTC is a single, universal time standard that doesn't
change with time zones or seasons (no daylight saving adjustments) — it's
the same moment, everywhere in the world, at any given instant.

**Real-life comparison:** Like agreeing that everyone on a video call
from different countries will state the meeting time using one shared
reference clock (say, "London time, no daylight saving") instead of
everyone converting their own local time and potentially making mistakes.

**Where DECA uses it:** Every one of our scripts stamps its logs and
run-ids using UTC. This actually mattered a lot in a real investigation
(told in full in Chapter 9) — our lab computer *displays* local Indian
time (UTC+5:30) by default, and briefly comparing a UTC-based folder name
against local-time file information without converting between the two
created a confusing, misleading false alarm.

**Why it matters:** Mixing up time zones is a classic, easy-to-make
mistake that can make two events that actually happened in the right
order look like they happened in the wrong order (or vice versa) — which
matters a great deal when you're trying to prove that one event (like
promoting a new model) definitely happened *before* another event (like a
verification test).

---

### Log file

**What it means:** A log file is a plain text file that a running program
writes lines into over time, recording what it did and when, usually one
event per line.

**Real-life comparison:** Like a ship's captain's logbook — a running,
timestamped diary of everything that happened during a voyage, written
as it happens, so it can be reviewed later.

**Where DECA uses it:** Every campaign, every blind test, and every
diagnostic script writes a log file (for example `campaign_run.log`,
`chaos_run.log`, `operator_feed.log`). These logs are what let us
reconstruct, after the fact, exactly what happened and when.

**Why it matters:** Chapter 9 tells a story where reading the *exact*
timestamped content inside log files — not just looking at when a file
was last modified — was the only reliable way to prove a sequence of
events happened in the correct order.

---

### CSV (Comma-Separated Values)

**What it means:** CSV is one of the simplest possible file formats for
storing a table of data: each line is one row, and commas separate the
different columns within that row.

**Real-life comparison:** Like a simple spreadsheet written using only a
plain text notepad, where you separate each column's value with a comma
instead of drawing actual spreadsheet grid lines.

**Where DECA uses it:** `fault_injection_log.csv` (records exactly when
each fault was turned on/off), `network_telemetry.csv` (raw measurements),
and many other files throughout this project are CSVs.

**Why it matters:** CSV is simple, human-readable, and works with almost
every data tool in existence — a practical, no-fuss choice for
record-keeping.

---

### JSON (JavaScript Object Notation)

**What it means:** JSON is a common text format for storing more
structured, "nested" information than a simple table — for example, a
single settings file that has several named sections, each with its own
group of related settings.

**Real-life comparison:** Like a filled-out form with labeled sections and
sub-sections (Name: ___, Address: {Street: ___, City: ___}), rather than
one flat row of a spreadsheet.

**Where DECA uses it:** `decision_thresholds.json` (all of DECA's tunable
settings, explained fully in Chapter 6), `run_meta.json`, and
`manifest.json` are all JSON files.

**Why it matters:** JSON is what lets us keep DECA's important settings
(like decision thresholds) as a simple, readable, editable text file
instead of buried inside code — this is a big part of why we can
recalibrate DECA for a new network without rewriting any code (see
Chapter 10).

---

### Parquet

**What it means:** Parquet is a more advanced, compressed file format
(compared to CSV) for storing large tables of data efficiently, designed
for fast reading by data-analysis tools.

**Real-life comparison:** Like the difference between a large stack of
loose paper spreadsheets versus a professionally organized, compressed,
and indexed digital filing cabinet — both hold the same information, but
one is far more efficient to store and search through at large scale.

**Where DECA uses it:** `deca_unified_dataset.parquet` is the single most
important file in the whole project — it's the final, fully-processed
table of features that DECA's machine learning model actually learns
from.

**Why it matters:** Our training data grows into tens of thousands of
rows and over a hundred columns — a format built for handling that size
efficiently is a practical necessity, not just a preference.

---

## End of Chapter 1

You've now covered nearly every plain networking term used across this
whole project. Chapter 2 covers the second big vocabulary you need: the
words used to describe *how a computer learns* from all these
measurements. Continue to
[Chapter 2 — Machine Learning Glossary](02_glossary_machine_learning.md).
