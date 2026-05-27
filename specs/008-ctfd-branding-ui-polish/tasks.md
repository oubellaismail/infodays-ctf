# Tasks: CTFd Branding & UI Polish

**Input**: Design documents from `specs/008-ctfd-branding-ui-polish/`
**Branch**: `008-ctfd-branding-ui-polish`

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no shared dependencies)
- **[Story]**: US1 / US2 / US3
- No test tasks — manual visual verification only (see `quickstart.md`)

---

## Phase 1: Setup

**Purpose**: Create the one new file this feature introduces.

- [x] T001 Create `ctfd-plugin/assets/style.css` with the following exact content as a starting skeleton — two empty theme blocks that all subsequent tasks will populate:

  ```css
  /* Infodays CTF — Brand Design System
   * Maps Infodays color tokens to Bootstrap 5 CSS variables.
   * Applied via data-bs-theme attribute set by CTFd on <html>.
   * Reference: specs/design/colors.md, .impeccable.md
   */

  /* ── Dark Mode (default) ──────────────────────────────────── */
  [data-bs-theme="dark"] {
  }

  /* ── Light Mode ───────────────────────────────────────────── */
  [data-bs-theme="light"] {
  }

  /* ── Global Typography ────────────────────────────────────── */

  /* ── Bootstrap Component Overrides ───────────────────────── */

  /* ── Instance Manager Panel ───────────────────────────────── */
  ```

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Populate the CSS token foundation that all three user stories depend on. Complete this phase before any other phase.

**⚠️ CRITICAL**: All subsequent phases depend on the CSS custom properties defined here.

- [x] T002 In `ctfd-plugin/assets/style.css`, fill the `[data-bs-theme="dark"]` block with these exact rules (replace the empty block):

  ```css
  [data-bs-theme="dark"] {
    --bs-body-bg:           #020511;
    --bs-body-color:        #D6DFEC;
    --bs-card-bg:           #070D1A;
    --bs-primary:           #397BE9;
    --bs-primary-rgb:       57, 123, 233;
    --bs-secondary-bg:      #162235;
    --bs-tertiary-bg:       #0E1624;
    --bs-secondary-color:   #7E90AE;
    --bs-border-color:      #192230;
    --bs-danger:            #861118;
    --bs-danger-rgb:        134, 17, 24;
    --bs-success:           #1A7F4E;
    --bs-success-rgb:       26, 127, 78;
    --bs-font-sans-serif:   'Inter', system-ui, -apple-system, sans-serif;
    --ctf-brand-accent:     #E84B2A;
    --ctf-badge-running-bg: #1A7F4E;
    --ctf-badge-muted-bg:   #162235;
    --ctf-badge-muted-color:#7E90AE;
    --ctf-badge-error-bg:   #861118;
    --ctf-ui-bg:            rgba(255, 255, 255, 0.04);
    --ctf-ui-border:        #192230;
  }
  ```

- [x] T003 [P] In `ctfd-plugin/assets/style.css`, fill the `[data-bs-theme="light"]` block with these exact rules (replace the empty block):

  ```css
  [data-bs-theme="light"] {
    --bs-body-bg:           #F2F5FC;
    --bs-body-color:        #0A1628;
    --bs-card-bg:           #FFFFFF;
    --bs-primary:           #2563EB;
    --bs-primary-rgb:       37, 99, 235;
    --bs-secondary-bg:      #DDE6F5;
    --bs-tertiary-bg:       #EBF0F8;
    --bs-secondary-color:   #4A5E78;
    --bs-border-color:      #C4CDD9;
    --bs-danger:            #B91C1C;
    --bs-danger-rgb:        185, 28, 28;
    --bs-success:           #15803D;
    --bs-success-rgb:       21, 128, 61;
    --bs-font-sans-serif:   'Inter', system-ui, -apple-system, sans-serif;
    --ctf-brand-accent:     #E84B2A;
    --ctf-badge-running-bg: #15803D;
    --ctf-badge-muted-bg:   #DDE6F5;
    --ctf-badge-muted-color:#4A5E78;
    --ctf-badge-error-bg:   #B91C1C;
    --ctf-ui-bg:            rgba(0, 0, 0, 0.03);
    --ctf-ui-border:        #C4CDD9;
  }
  ```

- [x] T004 In `ctfd-plugin/assets/style.css`, fill the `/* ── Global Typography ── */` section with these exact rules:

  ```css
  body {
    font-family: var(--bs-font-sans-serif);
    font-size: 14px;
    line-height: 1.5;
  }

  code, pre, kbd, samp {
    font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Mono', monospace;
  }
  ```

**Checkpoint**: `style.css` now has full token definitions for both modes and base typography. No visual changes yet — styles aren't injected.

---

## Phase 3: User Story 1 — Branded Platform Experience (Priority: P1) 🎯 MVP

**Goal**: Fonts, color palette, and Infodays logo appear on every CTFd page in both dark and light modes.

**Independent Test**: Load CTFd → confirm dark navy background, Inter font, and logo in navbar. Switch to light mode → confirm light palette and logo variant swap.

### Implementation for User Story 1

- [x] T005 [US1] In `ctfd-plugin/__init__.py`, add a CSS + font injection function. Locate the existing `load(app)` function (line 121). After the line `app.config["SESSION_COOKIE_DOMAIN"] = ".infodays.net"` (line 127), add this block:

  ```python
  # ── Branding: inject stylesheet + Google Fonts ─────────────────────────
  GOOGLE_FONTS_PRECONNECT = '<link rel="preconnect" href="https://fonts.googleapis.com">'
  GOOGLE_FONTS_PRECONNECT2 = '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
  GOOGLE_FONTS_URL = (
      '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
      'family=Inter:wght@400;500;600;700'
      '&family=JetBrains+Mono:wght@400;500'
      '&display=swap">'
  )
  BRAND_CSS_LINK = (
      '<link rel="stylesheet" href="/plugins/controller-plugin/assets/style.css">'
  )
  INJECT_TAGS = "\n".join([
      GOOGLE_FONTS_PRECONNECT,
      GOOGLE_FONTS_PRECONNECT2,
      GOOGLE_FONTS_URL,
      BRAND_CSS_LINK,
  ])

  @app.after_request
  def inject_brand_assets(response):
      if response.content_type and response.content_type.startswith("text/html"):
          data = response.get_data(as_text=True)
          if "</head>" in data:
              response.set_data(data.replace("</head>", INJECT_TAGS + "\n</head>", 1))
      return response
  ```

  > **Note**: The `@app.after_request` decorator must be inside the `load(app)` function body, as shown above. Place it before the `blueprint = Blueprint(...)` line so it registers early.

- [x] T006 [US1] In `ctfd-plugin/assets/plugin.js`, add logo injection inside the existing `init()` function (line 369). After the `console.log(...)` line (line 370) and before `watchChallengeModal()` (line 371), insert this block:

  ```javascript
  // ─── Logo injection ──────────────────────────────────────────────────────

  var LOGO_DARK_URL  = "/plugins/controller-plugin/assets/logo-dark.png";
  var LOGO_LIGHT_URL = "/plugins/controller-plugin/assets/logo-light.png";

  function getLogoSrc() {
    var theme = document.documentElement.getAttribute("data-bs-theme");
    return theme === "light" ? LOGO_LIGHT_URL : LOGO_DARK_URL;
  }

  function injectLogo() {
    var brand = document.querySelector(".navbar-brand");
    if (!brand) return;
    if (document.getElementById("ctf-brand-logo")) return; // already injected
    var img = document.createElement("img");
    img.id  = "ctf-brand-logo";
    img.className = "ctf-logo";
    img.src = getLogoSrc();
    img.alt = "Infodays CTF";
    brand.prepend(img);
  }

  function watchThemeForLogo() {
    var logo = document.getElementById("ctf-brand-logo");
    if (!logo) return;
    new MutationObserver(function() {
      logo.src = getLogoSrc();
    }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-bs-theme"] });
  }

  injectLogo();
  watchThemeForLogo();
  ```

- [x] T007 [US1] In `ctfd-plugin/assets/style.css`, add `.ctf-logo` rule inside the `/* ── Instance Manager Panel ── */` section:

  ```css
  .ctf-logo {
    height: 32px;
    width: auto;
    margin-right: 8px;
    vertical-align: middle;
  }
  ```

**Checkpoint**: Load CTFd → Infodays dark palette active, Inter font visible, logo in navbar. Light mode shows light palette and light logo. MVP complete.

---

## Phase 4: User Story 2 — Branded Challenge Instance Manager (Priority: P2)

**Goal**: The challenge instance manager panel in `plugin.js` uses zero inline color values — all appearance driven by CSS classes from `style.css`.

**Independent Test**: Open any web/pwn/misc challenge modal → inspect element on the status badge and container → confirm no `style` attribute with color values. Verify correct visual state in dark and light modes.

### Implementation for User Story 2

- [x] T008 [US2] In `ctfd-plugin/assets/style.css`, add all instance manager component rules inside the `/* ── Instance Manager Panel ── */` section (after `.ctf-logo`):

  ```css
  /* Container */
  .ctf-controller-ui {
    margin-bottom: 12px;
    padding: 10px;
    border: 1px solid var(--ctf-ui-border);
    border-radius: 4px;
    background: var(--ctf-ui-bg);
  }

  /* Status badges */
  .ctf-badge {
    display: inline-block;
    margin-right: 8px;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #fff;
  }

  .ctf-badge--running {
    background: var(--ctf-badge-running-bg);
  }

  .ctf-badge--suspended,
  .ctf-badge--fresh {
    background: var(--ctf-badge-muted-bg);
    color: var(--ctf-badge-muted-color);
  }

  .ctf-badge--error {
    background: var(--ctf-badge-error-bg);
  }

  /* Instance connection info */
  .ctf-nc-command {
    margin-left: 8px;
    padding: 2px 6px;
    background: var(--bs-tertiary-bg);
    border-radius: 3px;
    font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Mono', monospace;
    font-size: 0.9em;
    user-select: all;
    cursor: text;
    display: inline-block;
  }

  .ctf-instance-url {
    margin-left: 8px;
    font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Mono', monospace;
    font-size: 0.9em;
    word-break: break-all;
  }
  ```

- [x] T009 [US2] In `ctfd-plugin/assets/plugin.js`, replace the `getOrCreateContainer()` function body. Find this exact line (line 88):

  ```javascript
  container.style.cssText = "margin-bottom:12px;padding:10px;border:1px solid #444;border-radius:6px;background:rgba(255,255,255,0.05);";
  ```

  Replace it with:

  ```javascript
  container.className = "ctf-controller-ui";
  ```

- [x] T010 [US2] In `ctfd-plugin/assets/plugin.js`, replace the badge creation in the `fresh/suspended` branch of `renderUI()`. Find this exact block (lines 116–129 of the `fresh/suspended` branch):

  ```javascript
  var badge = document.createElement("span");
  badge.style.cssText = "margin-right:8px;padding:2px 8px;border-radius:4px;font-size:0.8em;color:#fff;";

  var btn = document.createElement("button");
  btn.style.marginRight = "6px";
  btn.className = "btn btn-sm";

  if (status === "fresh" || status === "suspended") {
    badge.textContent = status === "fresh" ? "Not Started" : "Stopped";
    badge.style.background = "#6c757d";
    btn.textContent = "\u25B6 Start Instance";
    btn.className += " btn-primary";
  ```

  Replace it with:

  ```javascript
  var badge = document.createElement("span");
  badge.className = "ctf-badge";

  var btn = document.createElement("button");
  btn.className = "btn btn-sm";

  if (status === "fresh" || status === "suspended") {
    badge.textContent = status === "fresh" ? "Not Started" : "Stopped";
    badge.classList.add(status === "fresh" ? "ctf-badge--fresh" : "ctf-badge--suspended");
    btn.textContent = "\u25B6 Start Instance";
    btn.classList.add("btn-primary");
  ```

- [x] T011 [US2] In `ctfd-plugin/assets/plugin.js`, replace the badge setup in the `running` branch of `renderUI()`. Find this exact block (inside the `} else if (status === "running") {` branch):

  ```javascript
    badge.textContent = "Running";
    badge.style.background = "#28a745";
    btn.textContent = "\u23F9 Stop Instance";
    btn.className += " btn-danger";
  ```

  Replace it with:

  ```javascript
    badge.textContent = "Running";
    badge.classList.add("ctf-badge--running");
    btn.textContent = "\u23F9 Stop Instance";
    btn.classList.add("btn-danger");
  ```

- [x] T012 [US2] In `ctfd-plugin/assets/plugin.js`, replace the TCP nc command inline style. Find this exact block (inside the `if (challenge.url.startsWith("nc "))` branch):

  ```javascript
    var code = document.createElement("code");
    code.textContent = challenge.url;
    code.style.cssText = "margin-left:8px;padding:2px 6px;background:rgba(0,0,0,0.3);border-radius:4px;font-size:0.9em;user-select:all;cursor:text;";
    container.appendChild(code);
  ```

  Replace it with:

  ```javascript
    var code = document.createElement("code");
    code.textContent = challenge.url;
    code.className = "ctf-nc-command";
    container.appendChild(code);
  ```

- [x] T013 [US2] In `ctfd-plugin/assets/plugin.js`, replace the HTTP instance URL inline style. Find this exact block (inside the `} else {` after the `nc ` check):

  ```javascript
    var urlLink = document.createElement("a");
    urlLink.href = challenge.url;
    urlLink.target = "_blank";
    urlLink.rel = "noopener noreferrer";
    urlLink.textContent = challenge.url;
    urlLink.style.marginLeft = "8px";
    container.appendChild(urlLink);
  ```

  Replace it with:

  ```javascript
    var urlLink = document.createElement("a");
    urlLink.href = challenge.url;
    urlLink.target = "_blank";
    urlLink.rel = "noopener noreferrer";
    urlLink.textContent = challenge.url;
    urlLink.className = "ctf-instance-url";
    container.appendChild(urlLink);
  ```

- [x] T014 [US2] In `ctfd-plugin/assets/plugin.js`, replace the error badge in `renderUnknown()`. Find this exact block:

  ```javascript
  var badge = document.createElement("span");
  badge.textContent = "Error";
  badge.style.cssText = "margin-right:8px;padding:2px 8px;border-radius:4px;font-size:0.8em;background:#dc3545;color:#fff;";
  container.appendChild(badge);

  var btn = document.createElement("button");
  btn.className = "btn btn-sm btn-secondary";
  btn.disabled = true;
  btn.textContent = "Unavailable";
  btn.style.marginRight = "6px";
  ```

  Replace it with:

  ```javascript
  var badge = document.createElement("span");
  badge.textContent = "Error";
  badge.className = "ctf-badge ctf-badge--error";
  container.appendChild(badge);

  var btn = document.createElement("button");
  btn.className = "btn btn-sm btn-secondary";
  btn.disabled = true;
  btn.textContent = "Unavailable";
  ```

  > The `btn.style.marginRight = "6px"` line should be deleted entirely — spacing is handled by Bootstrap's `btn-sm` and the adjacent `retryLink` margin.

**Checkpoint**: Open challenge modal in both dark and light modes → instance panel renders with brand colors, zero inline color values. Confirm by running: `grep -E '#[0-9a-fA-F]{3,6}|rgba?\(' ctfd-plugin/assets/plugin.js` — should return zero hex/color matches.

---

## Phase 5: User Story 3 — Consistent Global Visual Identity (Priority: P3)

**Goal**: Bootstrap default blue and white components (cards, tables, buttons, modals) are replaced with the Infodays token set across all CTFd pages.

**Independent Test**: View scoreboard and challenge list pages → confirm no Bootstrap default `#0d6efd` blue or plain white card backgrounds appear in dark mode.

### Implementation for User Story 3

- [x] T015 [US3] In `ctfd-plugin/assets/style.css`, add Bootstrap modal and card overrides inside the `/* ── Bootstrap Component Overrides ── */` section:

  ```css
  /* Modal */
  .modal-content {
    background-color: var(--bs-card-bg);
    border-color: var(--bs-border-color);
  }

  .modal-header,
  .modal-footer {
    border-color: var(--bs-border-color);
  }

  /* Cards */
  .card {
    background-color: var(--bs-card-bg);
    border-color: var(--bs-border-color);
  }

  .card-header,
  .card-footer {
    background-color: var(--bs-secondary-bg);
    border-color: var(--bs-border-color);
  }
  ```

- [x] T016 [US3] In `ctfd-plugin/assets/style.css`, add table and scoreboard overrides inside the `/* ── Bootstrap Component Overrides ── */` section (after card rules):

  ```css
  /* Tables (scoreboard) */
  .table {
    --bs-table-bg:          var(--bs-card-bg);
    --bs-table-border-color: var(--bs-border-color);
    --bs-table-striped-bg:  var(--bs-tertiary-bg);
    --bs-table-hover-bg:    var(--bs-secondary-bg);
    color: var(--bs-body-color);
  }

  /* Navbar */
  .navbar {
    background-color: var(--bs-card-bg) !important;
    border-bottom: 1px solid var(--bs-border-color);
  }

  /* Input fields */
  .form-control,
  .form-select {
    background-color: var(--bs-tertiary-bg);
    border-color: var(--bs-border-color);
    color: var(--bs-body-color);
  }

  .form-control:focus,
  .form-select:focus {
    background-color: var(--bs-tertiary-bg);
    border-color: var(--bs-primary);
    color: var(--bs-body-color);
    box-shadow: 0 0 0 0.2rem rgba(var(--bs-primary-rgb), 0.25);
  }
  ```

- [x] T017 [US3] In `ctfd-plugin/assets/style.css`, add primary button override inside the `/* ── Bootstrap Component Overrides ── */` section (after input rules):

  ```css
  /* Primary button — use brand blue, not Bootstrap default #0d6efd */
  .btn-primary {
    --bs-btn-bg:           var(--bs-primary);
    --bs-btn-border-color: var(--bs-primary);
    --bs-btn-hover-bg:     color-mix(in srgb, var(--bs-primary) 85%, black);
    --bs-btn-active-bg:    color-mix(in srgb, var(--bs-primary) 70%, black);
  }
  ```

**Checkpoint**: View scoreboard → navy card backgrounds, brand blue buttons. No default Bootstrap colors visible in dark mode.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Verify correctness across all changes and ensure nothing is broken.

- [x] T018 Run this command from repo root to confirm zero hardcoded color values remain in `plugin.js`. Expected output: no matches (empty).

  ```bash
  grep -n -E 'style\.(color|background|cssText|marginLeft|marginRight)\s*=' ctfd-plugin/assets/plugin.js
  grep -n -E '#[0-9a-fA-F]{3,6}' ctfd-plugin/assets/plugin.js
  grep -n -E 'rgba?\(' ctfd-plugin/assets/plugin.js
  ```

  If any matches are found: trace them to their task (T009–T014) and fix.

- [x] T019 [P] Manually verify US1 using the steps in `specs/008-ctfd-branding-ui-polish/quickstart.md` — sections "Verifying Dark Mode" and "Verifying Light Mode".

- [x] T020 [P] Manually verify US2 using the steps in `specs/008-ctfd-branding-ui-polish/quickstart.md` — section "Verifying the Challenge Instance Panel".

- [x] T021 Manually verify zero regressions using `specs/008-ctfd-branding-ui-polish/quickstart.md` — section "Verifying Existing Functionality". Flag submission, scoreboard, team pages must work without console errors.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1** (T001): No dependencies — start immediately
- **Phase 2** (T002–T004): Depends on T001 — BLOCKS all user story phases
- **Phase 3** (T005–T007): Depends on Phase 2 complete
- **Phase 4** (T008–T014): Depends on Phase 2 complete — can run in parallel with Phase 3
- **Phase 5** (T015–T017): Depends on Phase 2 complete — can run in parallel with Phases 3 & 4
- **Phase 6** (T018–T021): Depends on all phases complete

### Within Phase 2

- T002 and T003 are `[P]` — write dark and light blocks simultaneously (different content, same file section — complete one before starting the other to avoid conflicts)

### Parallel Opportunities

| Parallel Group | Tasks | When |
|---|---|---|
| Token blocks | T002, T003 | After T001 |
| US1 font injection + logo CSS | T005, T007 | After Phase 2 |
| All user story phases | Phase 3, 4, 5 | After Phase 2 (different files/sections) |
| Final verification | T019, T020 | After T018 |

---

## Parallel Example: Phases 3, 4, 5 (after Phase 2 complete)

```
Phase 3 (US1): T005 → T006 → T007
Phase 4 (US2): T008 → T009 → T010 → T011 → T012 → T013 → T014
Phase 5 (US3): T015 → T016 → T017
```

All three phases touch different sections — Phase 3 touches `__init__.py` + logo in `plugin.js`, Phase 4 touches rendering functions in `plugin.js`, Phase 5 adds rules to `style.css`. Sequential within each phase, parallel across phases.

---

## Implementation Strategy

### MVP First (User Story 1 Only — ~4 tasks)

1. T001 — Create `style.css` skeleton
2. T002, T003, T004 — Populate tokens + typography
3. T005, T006, T007 — Inject fonts, CSS, logo
4. **STOP and VALIDATE**: Is the platform branded? Dark palette active? Logo visible? Fonts correct?

### Full Delivery Order

1. Phase 1 → Phase 2 (foundation)
2. Phase 3 (branded platform — MVP)
3. Phase 4 (instance manager refactor)
4. Phase 5 (global Bootstrap overrides)
5. Phase 6 (verification)

---

## Notes

- All CSS variable names beginning with `--ctf-` are plugin-specific. All `--bs-` names override Bootstrap.
- `color-mix()` in T017 requires a modern browser (Chrome 111+, Firefox 113+). If browser support is a concern, replace with a hardcoded slightly-darker hex value.
- The `[P]` marker on T002/T003 means the content is independent, but they write to the same file — complete one fully before starting the other.
- After T014: `btn.style.marginRight = "6px"` should be deleted from `renderUnknown()`. The button's spacing comes from Bootstrap `btn-sm` padding and the adjacent retry link.
- Logo files are already in `ctfd-plugin/assets/` — no copy needed.
- The Blueprint name is `"controller_plugin"` and `static_url_path` is `"/plugins/controller-plugin/assets"`. The CSS URL in T005 and JS URL in T006 must match: `/plugins/controller-plugin/assets/style.css` and `/plugins/controller-plugin/assets/logo-*.png`.
