# Feature Specification: CTFd Branding & UI Polish

**Feature Branch**: `008-ctfd-branding-ui-polish`
**Created**: 2026-04-04
**Status**: Draft
**Input**: User description: "Phase 8 — CTFd Branding & UI Polish: apply Infodays brand identity to the CTFd platform."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Branded Platform Experience (Priority: P1)

A student opens CTFd for the first time during the Infodays CTF event. Instead of the default Bootstrap blue-and-white interface, they see a dark navy-themed platform with the Infodays logo in the navigation bar and a visual identity that feels like a serious security competition. The look immediately communicates "this is a real CTF."

**Why this priority**: First impressions shape participant engagement. A branded platform signals professionalism and builds confidence. This is the highest-impact change — it either looks like Infodays or it doesn't.

**Independent Test**: Can be fully tested by loading the CTFd homepage and verifying the Infodays logo, dark navy background, and brand colors are visible without any other Phase 8 changes deployed.

**Acceptance Scenarios**:

1. **Given** a participant loads `https://ctfd.infodays.net`, **When** the page renders, **Then** the background is deep navy (`#020511`), body text is light blue-gray (`#D6DFEC`), and the Infodays logo is visible in the navigation bar.
2. **Given** the platform is dark-only, **When** a participant looks for a theme toggle, **Then** the toggle is hidden and the platform remains in dark mode.
3. **Given** a participant views any page, **When** they observe the typography, **Then** all UI text renders in Inter and all data output (flags, ports, IP addresses, nc commands) renders in JetBrains Mono.

---

### User Story 2 — Branded Challenge Instance Manager (Priority: P2)

A participant opens a web challenge modal and sees the Start/Stop instance panel styled to match the Infodays brand — not generic Bootstrap buttons and hardcoded gray boxes. Status badges are clearly readable with brand-consistent colors. The instance URL and nc command are displayed in monospace for easy copying.

**Why this priority**: The challenge instance manager is the most frequently used custom UI element — every participant interacts with it multiple times. It must feel cohesive with the rest of the platform.

**Independent Test**: Can be tested by opening any web, pwn, or misc challenge modal and verifying the instance panel renders with brand colors, the status badge uses the correct color state, and TCP commands display in monospace.

**Acceptance Scenarios**:

1. **Given** a participant opens a challenge modal with no active instance, **When** the panel renders, **Then** the status badge displays in muted gray and the Start button uses the primary blue (`#397BE9`).
2. **Given** a participant has an active running instance, **When** the status refreshes to "Running," **Then** the badge turns success green and the instance URL displays as a clickable link in JetBrains Mono.
3. **Given** a TCP challenge (pwn/misc) is running, **When** the participant views the connection info, **Then** the `nc <host> <port>` command displays in a monospace block styled to the dark card surface — easy to select and copy.
4. ~~Light mode scenario removed — platform is dark-only (theme toggle hidden).~~

---

### User Story 3 — Consistent Global Visual Identity (Priority: P3)

An admin or participant navigating the scoreboard, team pages, and challenge list observes that Bootstrap's default component styles (blue outlines, white backgrounds, default gray cards) have been replaced by the Infodays token set. The interface feels intentionally designed rather than scaffolded.

**Why this priority**: Consistent global styling completes the brand experience beyond the instance manager panel. Lower priority because it affects aesthetic coherence rather than core interaction flow.

**Independent Test**: Can be tested by navigating to the scoreboard and challenge list and verifying Bootstrap cards, tables, and buttons render in the Infodays token set rather than Bootstrap defaults.

**Acceptance Scenarios**:

1. **Given** a participant views the scoreboard, **When** the page renders, **Then** table rows use the brand card surface (`#070D1A`), borders use the brand border token (`#192230`), and no default Bootstrap blue or white backgrounds appear.
2. **Given** a participant clicks any primary action button (submit flag, join team), **When** the button renders, **Then** it uses the brand primary blue (`#397BE9`) rather than Bootstrap's default blue.

---

### Edge Cases

- What happens when the participant's browser cannot load Google Fonts (offline or network-restricted)? The platform must remain readable using system sans-serif and system monospace fallbacks.
- ~~Theme switching edge case removed — platform is dark-only (theme toggle hidden).~~
- What happens on file-based challenge categories (crypto, forensics, reversing, osint)? The plugin must not inject the instance manager UI into these challenge modals.
- What happens if a participant's browser forces a color scheme independently? The platform is dark-only — the theme toggle is hidden via CSS and only dark mode tokens are defined.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The platform MUST display the Infodays dark color palette by default on all pages, overriding Bootstrap 5 default colors via CSS custom property mapping.
- **FR-002**: The platform is dark-only. The theme toggle MUST be hidden via CSS. Light mode CSS variables are not defined.
- **FR-003**: The Infodays logo MUST appear in the CTFd navigation bar on all pages, displaying the dark-mode variant (`logo-dark.png`).
- **FR-004**: ~~Logo swap removed — platform is dark-only; only `logo-dark.png` is used.~~
- **FR-005**: All UI body text MUST render in Inter. All data outputs — flags, ports, IP addresses, nc commands, and code elements — MUST render in JetBrains Mono.
- **FR-006**: The challenge instance manager panel MUST use CSS class-based styling exclusively — zero hardcoded color values MUST remain in `plugin.js`.
- **FR-007**: Status badges MUST communicate instance state through both color and text label: Running (success green), Suspended (muted gray), Fresh/Not Started (muted gray), Error (destructive red).
- **FR-008**: The instance panel MUST display correctly in dark mode with no hardcoded values bleeding through.
- **FR-009**: The branding changes MUST NOT break any existing CTFd functionality: flag submission, scoreboard, team management, and admin pages MUST remain fully operational.
- **FR-010**: Font assets MUST load via Google Fonts CDN with system-font fallbacks for offline or restricted-network environments.
- **FR-011**: The instance manager UI MUST only appear on service-based challenges (web, pwn, misc) — it MUST NOT inject into crypto, forensics, reversing, or osint modals.

### Key Entities

- **Color Token**: A named design variable with a dark-mode hex value, mapped to a Bootstrap 5 CSS variable. Full set defined in `specs/design/colors.md`.
- **Theme Mode**: Dark-only. The `data-bs-theme="dark"` attribute is set on the page root. The theme toggle is hidden via `.theme-switch { display: none }`.
- **Logo Variant**: `logo-dark.png` only (for dark backgrounds), served as a static asset from the plugin Blueprint.
- **Instance Panel**: The custom UI block injected by the plugin into service challenge modals — contains the status badge, Start/Stop button, and instance URL or nc command display.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every page of the CTFd platform displays the Infodays dark palette by default — zero default Bootstrap blue or white backgrounds appear on any core page in dark mode.
- **SC-002**: ~~Theme switching removed — platform is dark-only (theme toggle hidden).~~
- **SC-003**: The Infodays logo is visible on 100% of CTFd pages in the navigation bar, displaying the correct variant for the active theme.
- **SC-004**: Zero hardcoded color values remain in `plugin.js` — all appearance is CSS-driven, verifiable by code review.
- **SC-005**: The challenge instance panel is visually consistent with the surrounding CTFd UI in dark mode — no element appears with a mismatched background or text color.
- **SC-006**: All existing CTFd functionality operates without errors after branding changes are applied — flag submission, scoreboard, and team pages produce zero new console errors.
- **SC-007**: Inter applies to all UI text and JetBrains Mono applies to all nc commands, flag strings, and port/IP displays — verifiable by visual inspection on the challenge modal.

## Assumptions

- CTFd's default theme uses Bootstrap 5 CSS variables and sets `data-bs-theme` on `<html>` — our overrides target this mechanism.
- Google Fonts CDN is accessible from participant browsers during the event. Fallback stacks handle the offline case.
- The plugin Blueprint's static asset path is accessible at a predictable URL route.
- No CTFd source files will be modified — all changes go through the plugin injection point only.
- The platform is dark-only — `logo-light.png` is not used in production.
- A brand-appropriate success green will be defined in the stylesheet for the "Running" status badge, replacing the current hardcoded `#28a745`.

## Dependencies

- Phase 3 complete — `ctfd-plugin/assets/plugin.js` and `ctfd-plugin/__init__.py` must exist.
- `specs/design/colors.md` — dark and light token palettes (complete).
- `ctfd-plugin/assets/logo-dark.png` and `logo-light.png` — in place (complete).
- `.impeccable.md` — design constitution with personality, typography, and principles (complete).
