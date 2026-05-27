# Research: CTFd Branding & UI Polish

## 1. Bootstrap 5 CSS Variable Scoping with `data-bs-theme`

**Decision**: Use `[data-bs-theme="dark"]` attribute selector as the root of all token overrides. Platform is dark-only — light mode removed, theme toggle hidden.

**Rationale**: Bootstrap 5.3+ introduced native color mode support. It reads CSS custom properties (`--bs-body-bg`, `--bs-body-color`, `--bs-primary`, etc.) from the element carrying `data-bs-theme`. By placing our overrides on the dark selector we get zero-specificity-conflict theming. The theme toggle is hidden via `.theme-switch { display: none !important; }` to enforce dark-only.

**Key Bootstrap 5 variables to override**:

| Bootstrap Variable | Maps to Token | Dark Value |
|---|---|---|
| `--bs-body-bg` | Background | `#020511` |
| `--bs-body-color` | Foreground/Text | `#D6DFEC` |
| `--bs-card-bg` | Card | `#0A1120` |
| `--bs-primary` | Primary | `#397BE9` |
| `--bs-primary-rgb` | Primary (RGB) | `57, 123, 233` |
| `--bs-secondary-bg` | Secondary | `#111B2E` |
| `--bs-tertiary-bg` | Muted | `#0E1624` |
| `--bs-secondary-color` | Muted Foreground | `#7E90AE` |
| `--bs-border-color` | Border/Input | `#1A2538` |
| `--bs-danger` | Destructive | `#861118` |
| `--bs-success` | Running status | `#1A7F4E` |
| `--bs-font-sans-serif` | Body font | `'Inter', system-ui, sans-serif` |

**Alternatives considered**: Overriding Bootstrap via `_variables.scss` recompile — rejected because CTFd ships pre-compiled Bootstrap and we cannot modify CTFd source.

---

## 2. How CTFd Implements Dark/Light Mode

**Decision**: CTFd sets `data-bs-theme` on `<html>` when the user toggles theme from their account settings. No JavaScript intervention required from the plugin side — the attribute is already managed by CTFd.

**Rationale**: CTFd's `core-beta` theme (and recent versions of the `core` theme) use Bootstrap 5's native color mode. The toggle writes to a user preference stored in CTFd's session, and on each page load the theme is applied server-side as an attribute on `<html>`. This means:
- Our CSS selectors activate automatically on load
- Theme switches trigger a full page reload in CTFd (not a client-side toggle)

**Implication for dark-only**: The theme toggle is hidden, so no logo swap is needed. The plugin inserts `logo-dark.png` on DOM load.

---

## 3. CTFd Plugin Static Asset Serving

**Decision**: Serve `style.css` and logo files via the plugin's existing Flask Blueprint static directory. Inject `<link>` tags via the `load(app)` function in `__init__.py`.

**Rationale**: The existing plugin Blueprint is already configured with a `static_folder` pointing to `ctfd-plugin/assets/`. Files placed there are accessible at `/plugins/<plugin_name>/static/<filename>`. CTFd does not expose a `register_stylesheet()` API like it does for scripts, so we inject `<link>` tags directly in `load(app)` using Flask's `after_request` hook or by calling `app.jinja_env.globals`.

**Correct injection pattern** (avoids after_request HTML injection, which is fragile):
```python
# In load(app):
from flask import url_for
@app.context_processor
def inject_plugin_assets():
    return dict(plugin_css_url=url_for('ctfd_plugin_name.static', filename='style.css'))
```
Then reference in a base template — but since we cannot modify CTFd templates, the practical approach is:
```python
@app.after_request
def inject_stylesheet(response):
    if response.content_type.startswith('text/html'):
        link = f'<link rel="stylesheet" href="{css_url}">'
        response.data = response.data.replace(b'</head>', f'{link}</head>'.encode())
    return response
```
This is safe and already used by other CTFd plugins for CSS injection.

---

## 4. Google Fonts Injection

**Decision**: Inject two `<link>` tags in `after_request`: a `preconnect` to `fonts.googleapis.com` and the CSS2 font import URL for Inter + JetBrains Mono.

**Font URLs**:
```
https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap
```

**Fallback stacks** (for offline/restricted environments):
- Sans-serif: `'Inter', system-ui, -apple-system, sans-serif`
- Monospace: `'JetBrains Mono', 'Cascadia Code', 'Fira Mono', monospace`

**Alternatives considered**: Self-hosting fonts via DOCR/Spaces — rejected for Phase 8 (adds deployment complexity). Can be revisited if Google Fonts CDN is blocked in the event venue.

---

## 5. Preventing Flash of Unstyled Content (FOUC)

**Decision**: Inject `<link rel="stylesheet">` in `</head>` (blocking) rather than appending to `</body>`. CSS in `<head>` is render-blocking by design — this is the correct behavior to prevent FOUC.

**Rationale**: If the stylesheet loads after initial paint, participants see the unstyled Bootstrap default briefly. By injecting into `</head>`, the browser waits for `style.css` before first paint. The file is small (~3–5 KB) so blocking cost is negligible.

---

## 6. Logo Injection (Dark-Only)

**Decision**: Insert `logo-dark.png` into the navbar on DOM load. No MutationObserver needed — the platform is dark-only (theme toggle hidden).

```javascript
// On DOMContentLoaded: insert logo into .navbar-brand
const logo = document.createElement('img');
logo.src = LOGO_DARK_URL;
logo.className = 'ctf-logo';
navbarBrand.prepend(logo);
```

**Note**: The MutationObserver for theme swapping was removed when light mode support was dropped.
