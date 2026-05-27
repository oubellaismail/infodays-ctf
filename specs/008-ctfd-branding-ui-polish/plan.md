# Implementation Plan: CTFd Branding & UI Polish

**Branch**: `008-ctfd-branding-ui-polish` | **Date**: 2026-04-04 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/008-ctfd-branding-ui-polish/spec.md`

## Summary

Apply the Infodays brand identity to the CTFd platform entirely through the existing CTFd plugin injection point — no CTFd source modifications. Three files change: a new `style.css` introduces CSS custom property overrides for the dark palette mapped to Bootstrap 5 variables (dark-only — light mode removed, theme toggle hidden); `plugin.js` is refactored to replace all inline `style` assignments with CSS class names; `__init__.py` is updated to inject the stylesheet and Google Fonts CDN link. The plugin injects `logo-dark.png` into the navbar on DOM load. Design decisions are fully pre-defined in `.impeccable.md` and `specs/design/colors.md`.

---

## Technical Context

**Language/Version**: CSS3, Vanilla JavaScript (ES5/ES6), Python 3.11+ (Flask/CTFd plugin)
**Primary Dependencies**: Bootstrap 5 (bundled with CTFd), Google Fonts CDN (Inter + JetBrains Mono), CTFd Blueprint static serving
**Storage**: N/A — no persistent data involved
**Testing**: Manual visual inspection in browser (dark mode only); existing CTFd acceptance tests (`infra/tests/validate-ctfd.sh`) must continue to pass
**Target Platform**: CTFd Flask app (DOKS pod, `ctfd` namespace); plugin assets served via Blueprint static route
**Project Type**: Frontend CSS/JS injection via CTFd plugin
**Performance Goals**: Zero flash of unstyled content on page load
**Constraints**: No build step, no npm, no bundler; vanilla JS only; all changes through plugin injection point; must not modify CTFd source files
**Scale/Scope**: Affects all CTFd pages globally (~10 page types); 1 custom UI component (instance manager panel)

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|-----------|------|--------|
| **I. Flag Integrity** | No changes to flag derivation, storage, or submission logic | PASS — CSS/JS styling only; no flag logic touched |
| **II. Security-First Pod Isolation** | No changes to NetworkPolicy, PodSecurityStandards, or container configs | PASS — no infra changes |
| **III. Pod Lifecycle Discipline** | No changes to activation, deactivation, or daemon logic | PASS — instance panel UI refactored; behavior unchanged |
| **IV. DigitalOcean-Exclusive** | No new cloud services or providers introduced | PASS — Google Fonts CDN is a browser-side font load, not infrastructure |
| **V. Resource & Cost Discipline** | No new K8s resources, no pod resource changes | PASS — static file addition only |
| **CTFd Plugin Constraints** | Plugin MUST NOT alter flag validation, scoring, or other categories | PASS — adds CSS classes and logo injection; zero logic changes |
| **v1 Scope Boundaries** | No monitoring, no new services, no per-player instances | PASS — frontend only |

**Gate result: PASS — no violations. Proceed to Phase 0.**

---

## Project Structure

### Documentation (this feature)

```text
specs/008-ctfd-branding-ui-polish/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── css-component-contract.md
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
ctfd-plugin/
├── __init__.py          # Updated: inject style.css link + Google Fonts CDN link
└── assets/
    ├── style.css        # NEW: CSS custom properties (dark-only), Bootstrap overrides, component classes
    ├── plugin.js        # Updated: inline styles → CSS classes; logo injection + MutationObserver
    ├── logo-dark.png    # Already in place — glowing white wordmark
    └── logo-light.png   # Already in place — solid wordmark

specs/design/            # Read-only reference (already complete)
├── colors.md
├── logo-dark.png
└── logo-light.png

.impeccable.md           # Read-only reference (already complete)
```

**Structure Decision**: Single plugin directory — no new directories or services. All changes are additive within the existing `ctfd-plugin/` structure. `style.css` is the only new file; `plugin.js` and `__init__.py` are updated in place.

---

## Complexity Tracking

> No constitution violations — table not required.

---

## Phase 0: Research

*See `research.md` for full findings.*

Key questions resolved:
1. How does CTFd serve static assets from a plugin Blueprint?
2. How does Bootstrap 5 `data-bs-theme` CSS variable scoping work?
3. How does CTFd implement dark/light mode switching?
4. How do we inject a `<link>` stylesheet via the CTFd plugin API?
5. What Bootstrap 5 CSS variables map to which design tokens?

---

## Phase 1: Design & Contracts

### CSS Architecture

The entire theming is achieved via a single CSS file (`style.css`) with a dark-only theme block:

```css
[data-bs-theme="dark"]  { /* dark token overrides */ }
.theme-switch { display: none !important; } /* hide CTFd theme toggle */
```

Bootstrap 5 reads `--bs-body-bg`, `--bs-body-color`, `--bs-primary`, etc. from the nearest ancestor with `data-bs-theme`. Our overrides replace the defaults with the Infodays dark palette. Light mode is not supported — the theme toggle is hidden via CSS.

### Component Class Strategy

`plugin.js` emits semantic class names only. All visual rules live in `style.css`:

| Class | Purpose |
|-------|---------|
| `.ctf-controller-ui` | Instance manager container |
| `.ctf-badge` | Base status badge |
| `.ctf-badge--running` | Running state (success green) |
| `.ctf-badge--suspended` | Suspended state (muted) |
| `.ctf-badge--fresh` | Not started state (muted) |
| `.ctf-badge--error` | Error state (destructive) |
| `.ctf-instance-url` | HTTP instance link |
| `.ctf-nc-command` | TCP nc command block (monospace) |
| `.ctf-logo` | Navbar logo element |

### Logo Injection Strategy

- `plugin.js` handles logo injection:
  1. On DOM load: inserts `<img class="ctf-logo">` into CTFd's `.navbar-brand`
  2. Sets `src` to `logo-dark.png` (dark-only platform — no theme swapping needed)

### Font Injection Strategy

`__init__.py` injects two `<link>` tags in `load(app)`:
1. Google Fonts preconnect for performance
2. Google Fonts CSS2 import for Inter (wght 400–700) + JetBrains Mono (wght 400–500)

`style.css` sets `--bs-font-sans-serif: 'Inter', system-ui, sans-serif` and `font-family: 'JetBrains Mono', monospace` for `.ctf-nc-command` and all monospace code elements.

*See `contracts/css-component-contract.md` for full class/variable specifications.*
*See `data-model.md` for entity definitions.*
*See `quickstart.md` for local testing instructions.*
