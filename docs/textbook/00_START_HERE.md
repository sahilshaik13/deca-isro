# The DECA Textbook

## Read this page first

Welcome. This is not a normal technical document. It is written like a
textbook — the kind you would read in school — because the goal is that
**anyone**, even someone who has never touched a computer network or a
machine learning model before, can read this from front to back and
understand what DECA is, what it does, why every single piece exists, and
why we built it the way we did.

We will use very simple words. When we must use a hard word (and in
networking and machine learning, there are a lot of hard words), we will
stop and explain it the moment it shows up, using a real-life comparison
you already know — like traffic on a road, a doctor checking a patient, or
a smoke detector in a kitchen.

This book also tells the truth about the project, including the parts that
went wrong before they went right, and the parts that are still not
perfect today. A textbook that only shows the good parts is not honest,
and it is not as useful for learning. So we kept the failures in, on
purpose, in a chapter called **"Risen from the Fallen."**

---

## Who this book is for

- A teammate who is joining the project and has never seen any of the code.
- A judge, reviewer, or professor who wants to understand the *why*, not
  just read a results table.
- A future version of ourselves, six months from now, who forgot why we
  made a certain decision.
- Anyone — including, deliberately, someone as young as a 5th grader —
  who is simply curious what "DECA" means and why it matters.

You do not need to know anything about networks or machine learning before
reading this. Every term is defined the first time it is used, and there
are two full glossary chapters (Chapter 1 and Chapter 2) you can jump to
at any time if you forget what a word means.

---

## What DECA actually is, in one paragraph

DECA stands for **Distributed Enterprise Connectivity Anomaly** (framework).
In plain words: DECA is a computer program that watches a company's
computer network the way a security guard watches security cameras. Most
of the time, nothing bad is happening — the guard just watches quietly.
But the moment something bad starts to happen (a break-in, a fire, a
flood), the guard notices right away and raises an alarm, and can even
say **what kind** of bad thing is happening, so the right people can be
sent to fix the right problem. DECA does the same job, but for a computer
network instead of a building — and the "bad things" it watches for are
four specific kinds of network problems that we will explain in detail in
Chapter 3.

We built and tested DECA on our own small physical lab (three tiny
computers called Raspberry Pis, wired together to imitate a real company
network), with the eventual goal of handing this system over to **ISRO**
(the Indian Space Research Organisation) so it can help protect *their*
real network.

---

## Table of contents

| # | Chapter | What it covers |
| --- | --- | --- |
| 1 | [Networking Glossary](01_glossary_networking.md) | Every network-related word used anywhere in this project, explained one at a time, in order, in plain English |
| 2 | [Machine Learning Glossary](02_glossary_machine_learning.md) | Every ML/statistics word used anywhere in this project, explained the same way |
| 3 | [The Four Faults We Detect](03_the_four_faults.md) | What `congestion_breach`, `tunnel_degradation`, `bgp_route_flap`, and `vrf_leakage` actually are, in real network terms, with analogies |
| 4 | [The Lab Setup](04_the_lab_setup.md) | The physical hardware, the three stations, how they are wired and addressed, and how we watch them |
| 5 | [The Data Pipeline](05_data_pipeline.md) | Where the numbers DECA learns from actually come from, and how they get turned into something a computer can learn from |
| 6 | [The Model Architecture](06_model_architecture.md) | How the "brain" of DECA is actually built — the parts, why each part exists, and how they work together |
| 7 | [Risen from the Fallen](07_risen_from_the_fallen.md) | The full story of everything that went wrong, in the order it happened, and exactly how each problem was found and fixed |
| 8 | [Tier by Tier History](08_tier_by_tier_history.md) | A walk through every major improvement we made, one at a time, in the order we made them, with the numbers before and after each one |
| 9 | [Verification and Trust](09_verification_and_trust.md) | How we test whether DECA is telling the truth, including a real detective story about checking our own work |
| 10 | [Portability to ISRO](10_portability_to_isro.md) | What it would take to move DECA from our lab onto ISRO's real network |
| 11 | [Current Open Problems](11_current_open_problems.md) | An honest list of what is still not perfect today |
| 12 | [Appendix: Every Results Table](12_appendix_results_tables.md) | All the numbers, gathered in one place, for quick reference |

---

## How to read this book

- **If you have zero background:** read Chapters 1 and 2 first (the
  glossaries). They are long on purpose — they are meant to be a real
  foundation, not a quick skim. Then read the rest in order, 3 through 12.
- **If you already know networking or machine learning:** skip straight
  to Chapter 3. Come back to the glossaries only when you hit a word you
  don't recognize — every hard word in every later chapter is written
  in *italics* the first time it appears in that chapter, as a signal
  that it's explained in the glossary.
- **If you just want the "so what happened" story:** read Chapter 7
  (*Risen from the Fallen*) on its own. It is written to stand alone.
- **If you are a judge or reviewer and want the numbers fast:** go
  straight to Chapter 12.

---

## A promise about honesty

Every number in this book is a real number, taken from real files in this
repository, not invented for the sake of a good story. Every "we made a
mistake" story in Chapter 7 is a real mistake, with a link to the exact
document that proves it happened. Where something is *still* broken or
*still* uncertain, Chapter 11 says so directly, in plain words, instead of
hiding it behind technical language. This is intentional. A system that
is honest about its own weak points is more trustworthy than one that
claims to be perfect — and being trustworthy is the entire point of a
network alarm system.
