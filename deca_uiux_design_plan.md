# DECA NOC Dashboard — UI/UX Design Plan

> **Purpose:** This document is the single source of truth for the DECA orchestrator frontend.
> Every new page, component, or feature MUST follow these rules to maintain visual and architectural consistency.

---

## 1. Design Philosophy

DECA is a **mission-critical Network Operations Center** tool — not a marketing site. The design reflects that:

| Principle | What it means in practice |
|---|---|
| **Density over decoration** | Maximize useful data per pixel. No hero images, no large empty spaces. |
| **Signal clarity** | Color is *reserved for information*, never decoration. Only 3 semantic colors: accent (copper), ok (green), warn (red). |
| **Dark ops** | Permanently dark. Never add a light-mode toggle — the surface simulates a real NOC terminal. |
| **Structured hierarchy** | Typography scale is strict. Section labels, titles, subtitles, mono data, micro labels — each has one size and weight. Don't improvise. |
| **Calm until urgent** | Animations only appear on alerts/anomalies. Idle state is visually quiet. |

---

## 2. Design Tokens (CSS Custom Properties)

All design decisions live in CSS variables defined in [`globals.css`](file:///c:/Users/ADMIN/Documents/deca-isro/deca-frontend/app/globals.css) under `:root`.
**Never hardcode hex values in components.** Always reference a token.

### Color Tokens

```css
:root {
  /* Surfaces */
  --deca-bg:      #070b10;                    /* Page background — near-black deep navy */
  --deca-panel:   rgba(12, 18, 26, 0.88);     /* Glassmorphism panel fill */
  --deca-panel-2: #101820;                    /* Opaque secondary panel fill */
  --deca-line:    #2a3848;                    /* Borders, dividers, separators */

  /* Text */
  --deca-ink:     #e8eef4;                    /* Primary text — off-white */
  --deca-mute:    #8a9aab;                    /* Secondary / label text — slate-blue */

  /* Semantic accents */
  --deca-accent:  #c4a35a;                    /* Copper — active state, brand, CTAs */
  --deca-ok:      #3dba8a;                    /* Green — healthy, success, online */
  --deca-warn:    #e85d4c;                    /* Red — anomaly, alert, offline, danger */
}
```

### Layout Dimension Tokens

```css
:root {
  --rail-w:     56px;    /* Icon rail width */
  --sidebar-w:  268px;   /* Control sidebar width */
  --alert-w:    340px;   /* Alert rail (right panel) width */
  --topbar-h:   52px;    /* Top bar height */
}
```

> [!IMPORTANT]
> These dimension tokens must be used in any new zone you add to the shell. Do not hardcode widths.

---

## 3. Typography System

Fonts are loaded in [`layout.tsx`](file:///c:/Users/ADMIN/Documents/deca-isro/deca-frontend/app/layout.tsx) via Next.js Google Fonts.

### Typefaces

| Role | Font | CSS Variable | Use For |
|---|---|---|---|
| **Display** | Space Grotesk | `--font-display` | Section titles, brand mark, data values, h1–h3 |
| **Monospace** | IBM Plex Mono | `--font-mono` | All data readouts, status text, timestamps, code, labels |

The `<body>` default is **IBM Plex Mono** — this means all base text is monospace. Display font is applied explicitly where needed.

### Type Scale (strict — do not add new sizes)

| Token class | Size | Weight | Font | Usage |
|---|---|---|---|---|
| Brand mark | `1.1rem` | 700 | Display | Top bar DECA logo |
| Section title | `1.05rem` | 600 | Display | Panel section headings |
| Sidebar title | `0.88rem` | 600 | Display | Sidebar section headers |
| Body / alert class | `0.85–0.95rem` | 400 | Display | Alert headlines, sim messages |
| Status / body | `0.78–0.82rem` | 400 | Mono | Status pills, general body |
| Field data | `0.76–0.78rem` | 400 | Mono | Metric values, `dd` elements |
| Meta / fine | `0.68–0.72rem` | 400 | Mono | Source line, timestamps |
| **Label** | `0.6rem` | 600 | Mono | ALL caps section labels (`FABRIC`, `TRAFFIC`, etc.) |
| Micro | `0.56–0.62rem` | 400 | Mono | `dt` elements, tag badges |

> [!NOTE]
> Labels are always `0.6rem`, `font-weight: 600`, `letter-spacing: 0.16em`, `text-transform: uppercase`. This is the `.deca-sidebar-label` / `.deca-label` class. Use it consistently everywhere.

---

## 4. Layout Architecture — 4-Zone App Shell

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           TOP BAR  (52px)                                │
│  [DECA brand] │  [Title + Eyebrow]  [Run selector]  │  [Status pills]   │
├────────┬──────────────────┬────────────────────────────┬─────────────────┤
│        │                  │                            │                 │
│  ICON  │  CONTROL         │   MAIN CONTENT             │  ALERT RAIL     │
│  RAIL  │  SIDEBAR         │   (flex-1)                 │  (Decide)       │
│  56px  │  268px           │                            │  340px          │
│        │  FabricSelect    │   FleetStrip (cards grid)  │                 │
│  Nav   │  TrafficButtons  │   TopologyMap (SVG)        │  AlertRail      │
│  icons │  FaultButtons    │   MissionClasses (QoS)     │  (Approve /     │
│        │  SimControl      │   TelemetryGrid (charts)   │   Reject)       │
│        │                  │                            │                 │
├────────┴──────────────────┴────────────────────────────┴─────────────────┤
│                    TERMINAL DRAWER  (fixed bottom, min(38vh, 360px))      │
└──────────────────────────────────────────────────────────────────────────┘
```

### Zone CSS Classes

| Zone | Class | File |
|---|---|---|
| Outer wrapper | `.deca-shell` | `globals.css` |
| Top bar | `.deca-topbar` | `globals.css` + `Header.tsx` |
| Body row | `.deca-body` | `globals.css` + `page.tsx` |
| Icon rail | `.deca-rail` | `globals.css` + `page.tsx` |
| Control sidebar | `.deca-sidebar` + `.deca-sidebar-section` | `globals.css` + `page.tsx` |
| Main content | `.deca-main` | `globals.css` + `page.tsx` |
| Alert rail | `.deca-aside` + `.deca-aside-head` + `.deca-aside-body` | `globals.css` + `page.tsx` |
| Terminal | `.deca-term-drawer` | `globals.css` + `TerminalDrawer.tsx` |

### Adding a New Zone / Panel

> [!IMPORTANT]
> If you need to add a new zone, follow this checklist:
> 1. Add dimension to `:root` as a `--deca-*` CSS variable
> 2. Create a `.deca-<zonename>` class in `globals.css`
> 3. Use `border: 1px solid var(--deca-line)` for dividers
> 4. Use `overflow-y: auto` + the custom scrollbar snippet for scrollable zones
> 5. Wire it into `page.tsx` inside `.deca-body`

---

## 5. Component Catalog

### 5.1 Top Bar — `Header.tsx`

**Structure:**
```
[Brand: Satellite icon + DECA wordmark] | [Title / Eyebrow + Run selector] | [Status pills + meta]
```

**Rules:**
- Height is fixed at `var(--topbar-h)` = 52px. Never make it taller.
- Run selector max-width: `260px`
- Prometheus pill uses `.deca-status-pill.is-ok` or `.is-warn`
- Anomaly pill only renders when `isAnomalyMode === true`
- Source meta uses `.deca-hero-fine` — truncated with ellipsis

---

### 5.2 Icon Rail — inline in `page.tsx`

**Rules:**
- Width: `var(--rail-w)` = 56px, always centered icons
- Buttons: `.deca-rail-btn` — 38×38px, border-radius: 8px
- Active state: `.is-active` → copper tint background + copper icon color
- Alert badge: `.deca-rail-badge` — 8px red dot, top-right of button
- Divider: `.deca-rail-divider` — 24px wide, 1px height
- Settings button uses `marginTop: auto` divider to push it to bottom

---

### 5.3 Control Sidebar — Components inside `deca-sidebar-section`

Each sidebar section contains one component. **All sidebar components must follow this internal structure:**

```tsx
<>
  {/* Header row */}
  <div className="deca-sidebar-head">
    <span className="deca-sidebar-label">SECTION NAME</span>
    <InlineActionButton />   {/* optional */}
  </div>

  {/* Optional blurb */}
  <p className="deca-sidebar-sub">…</p>

  {/* Chip grid for options */}
  <div className="deca-chip-grid">
    <button className="deca-btn-primary | deca-btn-ghost">…</button>
  </div>

  {/* Status line */}
  <p className="deca-sidebar-status">…</p>
</>
```

**Sidebar component files:**

| Component | File | Section label |
|---|---|---|
| FabricSelect | [`FabricSelect.tsx`](file:///c:/Users/ADMIN/Documents/deca-isro/deca-frontend/components/noc/FabricSelect.tsx) | `FABRIC` |
| TrafficButtons | [`TrafficButtons.tsx`](file:///c:/Users/ADMIN/Documents/deca-isro/deca-frontend/components/noc/TrafficButtons.tsx) | `TRAFFIC` |
| FaultButtons | [`FaultButtons.tsx`](file:///c:/Users/ADMIN/Documents/deca-isro/deca-frontend/components/noc/FaultButtons.tsx) | `FAULTS` |
| SimulationControl | [`SimulationControl.tsx`](file:///c:/Users/ADMIN/Documents/deca-isro/deca-frontend/components/noc/SimulationControl.tsx) | `LAB TIMELINE` |

> [!NOTE]
> Sidebar components do NOT use `.deca-panel`. They render directly inside `.deca-sidebar-section` which already has `border-bottom: 1px solid var(--deca-line)` and `padding: 0.85rem 0.9rem`.

---

### 5.4 Fleet Strip — `FleetStrip.tsx`

Site cards grid with left-accent status bar. Each `article.deca-fleet-site` carries a `tone-*` modifier.

**Tone system:**
```
.tone-ok   → border-left-color: var(--deca-ok)    → also applies to .deca-dot.tone-ok
.tone-warn → border-left-color: var(--deca-warn)
.tone-mute → border-left-color: var(--deca-line)
```

**Card anatomy:**
```
[Dot · Site Name · Mission class badge]
[Role line]
─────────────────────────────────────
[State | Conf | ETA/RTT]
[Host list]
```

**Grid breakpoints:** 1 col → 2 col (520px) → 3 col (900px) → 5 col (1200px)

---

### 5.5 Panel Cards — `.deca-panel`

Used for: TopologyMap, MissionClasses, TelemetryGrid, AlertRail cards.

```css
.deca-panel {
  background: rgba(12, 18, 26, 0.75);   /* glassmorphism fill */
  border: 1px solid var(--deca-line);
  border-radius: 8px;
  backdrop-filter: blur(8px);
  /* ::before pseudo adds inner highlight gradient */
}
```

**Always pair with `.deca-panel-head`** for the title row:
```tsx
<div className="deca-panel-head">
  <div>
    <h2 className="deca-section-title">Title</h2>
    <p className="deca-section-sub">Subtitle</p>
  </div>
  <div>{/* action buttons */}</div>
</div>
```

---

### 5.6 Alert Rail — `AlertRail.tsx`

Lives inside `.deca-aside` with a sticky `.deca-aside-head`.

**Alert card anatomy:**
```
border-left: 3px solid var(--deca-warn)   ← always red left bar
[Alert class name · event badge]
[Meta grid: 3-col dl — Alert ID / Fabric / Score]
[Concerns box — highlighted bullet list]
[Approve / Reject buttons]
```

**Count badge rules:**
- `.deca-aside-count` → red border/bg when `actionableCount > 0`
- `.deca-aside-count.is-clear` → green border/bg when 0 alerts

---

### 5.7 Simulation Phase Stepper — in `SimulationControl.tsx`

Horizontal connected bar — **not** a grid tile layout.

```
[P0 Init] [P1 Clear] [P2 Payload] [P3 Steer] [P4 AI] [P5 Recover] [P6 Teardown]
```

- `.is-done` → green tint background
- `.is-active` → copper tint background
- Idle → `.deca-mute` text, transparent bg

---

## 6. Button System

Three semantic button classes — **never use ad-hoc Tailwind for buttons**:

| Class | When to use | Visual |
|---|---|---|
| `.deca-btn-primary` | Main CTA, active/selected fabric/profile | Solid copper fill, dark text, weight 600 |
| `.deca-btn-ghost` | Secondary actions, inactive options | Transparent, border only, copper on hover |
| `.deca-btn-danger` | Destructive actions (future use) | Red tint border + fill |

**All buttons share:**
- `border-radius: 5px`
- `font-size: 0.68rem`, `letter-spacing: 0.05em`, `text-transform: uppercase`
- `transition: transform 0.1s` → `translateY(-1px)` on hover (lift effect)
- `disabled` → `opacity: 0.4`, `cursor: not-allowed`

**Sidebar buttons** use smaller overrides: `font-size: 0.66rem`, `padding: 0.35rem 0.6rem`

---

## 7. Input System

Only one input class: `.deca-input`

```css
.deca-input {
  background: rgba(7, 11, 16, 0.85);
  border: 1px solid var(--deca-line);
  border-radius: 5px;
  color: var(--deca-ink);
  /* focus: copper border + 2px copper glow ring */
}
```

Used for: run selector `<select>`. Apply consistently to any future `<input>`, `<select>`, `<textarea>`.

---

## 8. Status & Semantic Indicators

### Status Pills — `.deca-status-pill`

```
.is-ok   → green border + green text + green background tint
.is-warn → red border + red text + red background tint + pulse animation
```

Used in: top bar (Prometheus, Anomaly), fleet cards, alert rail count badge.

### Dot Indicators — `.deca-dot`

```
.tone-ok   → solid green + green glow box-shadow
.tone-warn → solid red + red glow + pulse animation
.tone-mute → solid slate, no glow
```

### Semantic Color Rule

> [!CAUTION]
> **Color is reserved for meaning only:**
> - 🟡 **Copper** (`--deca-accent`) → brand, active selection, CTAs, interactive focus, phase active
> - 🟢 **Green** (`--deca-ok`) → healthy, online, approved, success, done phases
> - 🔴 **Red** (`--deca-warn`) → anomaly, offline, alert, rejected, HITL waiting
> - ⬜ **Mute** (`--deca-mute`) → labels, secondary text, idle states, borders
>
> Never use copper for warnings or green for non-success states.

---

## 9. Animation System

All `@keyframes` are defined globally in `globals.css`. **No animation CSS in component files.**

| Keyframe | Duration | Applied to | Purpose |
|---|---|---|---|
| `deca-pulse-border` | 2.2s | `.is-warn` pills, `.is-wait` sim | Opacity fade pulse |
| `deca-pulse-dot` | 1.8–2s | `.tone-warn` dots, `.deca-rail-badge` | Scale + opacity pulse |
| `deca-sweep` | 14s | Hero background veil | Background shimmer |
| `deca-link` | 3.5s | `.deca-link-pulse` topology | Link opacity breathe |
| `deca-node` | varies | Topology node pulse | Scale breathe |
| `live-blink` | 1.2s | Event list warn dots | Fast warn blink |

**Rule:** Animations ONLY play for `tone-warn` / `is-warn` / `is-wait` states. OK and idle states are always static.

---

## 10. Scrollbar Styling

Every scrollable zone gets this 3-rule pattern:

```css
.deca-zone::-webkit-scrollbar       { width: 4px; }
.deca-zone::-webkit-scrollbar-track { background: transparent; }
.deca-zone::-webkit-scrollbar-thumb { background: var(--deca-line); border-radius: 2px; }
```

Currently applied to: `.deca-sidebar`, `.deca-main`, `.deca-aside`.
Apply the same pattern to any new scrollable container.

---

## 11. Glassmorphism Recipe

```css
/* The standard DECA glass panel */
background: rgba(12, 18, 26, 0.75);
border: 1px solid var(--deca-line);
border-radius: 8px;
backdrop-filter: blur(8px);
-webkit-backdrop-filter: blur(8px);

/* Inner highlight via ::before */
content: '';
position: absolute;
inset: 0;
background: linear-gradient(135deg, rgba(255,255,255,0.018) 0%, transparent 55%);
pointer-events: none;
border-radius: 8px;
```

All `.deca-panel` cards apply this automatically. The topbar and terminal drawer use a darker variant (`rgba(7,11,16,0.92–0.97)`) with `blur(12px)`.

---

## 12. Responsive Breakpoints

| Viewport | Layout Behavior |
|---|---|
| `≥ 1200px` | Full 4-zone: rail (56px) + sidebar (268px) + main (flex-1) + aside (340px) |
| `≤ 1200px` | Alert rail narrows to 300px |
| `≤ 1024px` | Alert rail hidden entirely; sidebar narrows to 240px |
| `≤ 768px` | Rail hidden; sidebar becomes full-width horizontal strip (max-height: 260px); body stacks vertically |

> [!WARNING]
> The Terminal Drawer is `position: fixed` bottom — always visible at all breakpoints. Never make it scroll with page content or give it `position: relative`.

---

## 13. CSS Class Naming Convention

All DECA-specific classes use the `deca-` prefix. **Never use bare Tailwind utilities for structural elements** — only for minor one-off tweaks.

### Pattern
```
deca-{zone}              → layout zones  (shell, topbar, rail, sidebar, main, aside)
deca-{zone}-{element}    → child parts   (topbar-brand, sidebar-section, aside-head)
deca-{component}         → shared UI     (panel, dot, label, input, btn-*)
deca-{state}             → modifiers     (is-ok, is-warn, is-active, is-done, tone-*)
```

### State Modifiers Quick Reference
```
.is-ok       → healthy / online / success
.is-warn     → alert / anomaly / error / offline
.is-active   → currently selected / running
.is-done     → completed phase
.is-wait     → HITL gate: waiting for human Approve/Reject
.is-clear    → alert count is zero (aside count badge)
.tone-ok     → semantic green on dots / fleet cards
.tone-warn   → semantic red on dots / fleet cards
.tone-mute   → neutral slate on dots / fleet cards
```

---

## 14. Project File Map

```
deca-frontend/
│
├── app/
│   ├── globals.css              ← ALL design tokens, layout, component CSS
│   ├── layout.tsx               ← Font loading (Space Grotesk + IBM Plex Mono)
│   └── page.tsx                 ← 4-zone shell: Header + rail + sidebar + main + aside
│
└── components/noc/
    │
    ├── [TOP BAR]
    │   └── Header.tsx           ← Compact 52px top bar
    │
    ├── [SIDEBAR — control panels]
    │   ├── FabricSelect.tsx     ← Fabric toggle chip grid
    │   ├── TrafficButtons.tsx   ← ToS traffic profile chips
    │   ├── FaultButtons.tsx     ← Fault injection chips
    │   └── SimulationControl.tsx← Phase stepper + run controls
    │
    ├── [MAIN CONTENT]
    │   ├── FleetStrip.tsx       ← Site status card grid
    │   ├── TopologyMap.tsx      ← SVG network topology diagram
    │   ├── MissionClasses.tsx   ← QoS path table + policy notes
    │   └── TelemetryGrid.tsx    ← Metric charts + history
    │
    ├── [ALERT RAIL — right aside]
    │   └── AlertRail.tsx        ← Alert cards + Approve / Reject
    │
    └── [TERMINAL — fixed bottom]
        ├── TerminalDrawer.tsx   ← Drawer shell + tab bar
        ├── XtermPane.tsx        ← xterm.js terminal pane
        └── CopilotTerminal.tsx  ← AI copilot terminal pane
```

---

## 15. Rules for Future Frontend Work

> [!IMPORTANT]
> **Checklist before shipping any new UI element:**

1. **Token-first** → Reference `--deca-*` CSS variables. Never hardcode hex colors.
2. **Type scale** → Pick the nearest size from the scale table in §3. Do not invent new `font-size` values.
3. **Button classes** → Use `.deca-btn-primary`, `.deca-btn-ghost`, or `.deca-btn-danger` only. Do not add custom button styles.
4. **Sidebar pattern** → New sidebar sections MUST use `deca-sidebar-head / deca-sidebar-sub / deca-chip-grid / deca-sidebar-status`.
5. **Panel pattern** → New main-area panels MUST use `.deca-panel` + `.deca-panel-head` + `.deca-section-title`.
6. **Semantic color** → Copper = active/brand, green = ok, red = warn, mute = secondary. No decorative color.
7. **Animate warnings only** → Add `@keyframes` to `globals.css`, not to components. Never animate idle/OK states.
8. **Always dark** → The `dark` class on `<html>` is permanent. Do not add light-mode CSS.
9. **Zone dimensions in tokens** → New layout zones need a CSS variable in `:root`.
10. **Test responsive** → Always verify at 768px, 1024px, and 1280px after any layout change.

---

## 16. Color Quick Reference

| Token | Hex | Purpose |
|---|---|---|
| `--deca-bg` | `#070b10` | Page background |
| `--deca-panel` | `rgba(12,18,26,0.88)` | Glassmorphism panel fill |
| `--deca-panel-2` | `#101820` | Opaque secondary panel |
| `--deca-line` | `#2a3848` | All borders & dividers |
| `--deca-ink` | `#e8eef4` | Primary text |
| `--deca-mute` | `#8a9aab` | Labels & secondary text |
| `--deca-accent` | `#c4a35a` | Copper — active / brand |
| `--deca-ok` | `#3dba8a` | Green — healthy / success |
| `--deca-warn` | `#e85d4c` | Red — alert / anomaly |
