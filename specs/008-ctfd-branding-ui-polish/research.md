# Research: CTFd Branding & UI Polish

## 1. Bootstrap 5 CSS Variable Scoping with `data-bs-theme`

**Decision**: Use `[data-bs-theme="dark"]` and `[data-bs-theme="light"]` attribute selectors as the root of all token overrides.

**Rationale**: Bootstrap 5.3+ introduced native color mode support. It reads CSS custom properties (`--bs-body-bg`, `--bs-body-color`, `--bs-primary`, etc.) from the element carrying `data-bs-theme`. By placing our overrides on these same selectors we get zero-specificity-conflict theming — no `!important` needed. All Bootstrap components inherit from the root element automatically.

**Key Bootstrap 5 variables to override**:

| Bootstrap Variable | Maps to Token | Dark Value | Light Value |
|---|---|---|---|
| `--bs-body-bg` | Background | `#020511` | `#F2F5FC` |
| `--bs-body-color` | Foreground/Text | `#D6DFEC` | `#0A1628` |
| `--bs-card-bg` | Card | `#070D1A` | `#FFFFFF` |
| `--bs-primary` | Primary | `#397BE9` | `#2563EB` |
| `--bs-primary-rgb` | Primary (RGB) | `57, 123, 233` | `37, 99, 235` |
| `--bs-secondary-bg` | Secondary | `#162235` | `#DDE6F5` |
| `--bs-tertiary-bg` | Muted | `#0E1624` | `#EBF0F8` |
| `--bs-secondary-color` | Muted Foreground | `#7E90AE` | `#4A5E78` |
| `--bs-border-color` | Border/Input | `#192230` | `#C4CDD9` |
| `--bs-danger` | Destructive | `#861118` | `#B91C1C` |
| `--bs-success` | Running status | `#1A7F4E` | `#15803D` |
| `--bs-font-sans-serif` | Body font | `'Inter', system-ui, sans-serif` | same |

**Alternatives considered**: Overriding Bootstrap via `_variables.scss` recompile — rejected because CTFd ships pre-compiled Bootstrap and we cannot modify CTFd source.

---

## 2. How CTFd Implements Dark/Light Mode

**Decision**: CTFd sets `data-bs-theme` on `<html>` when the user toggles theme from their account settings. No JavaScript intervention required from the plugin side — the attribute is already managed by CTFd.

**Rationale**: CTFd's `core-beta` theme (and recent versions of the `core` theme) use Bootstrap 5's native color mode. The toggle writes to a user preference stored in CTFd's session, and on each page load the theme is applied server-side as an attribute on `<html>`. This means:
- Our CSS selectors activate automatically on load
- Theme switches trigger a full page reload in CTFd (not a client-side toggle)

**Implication for logo swap**: Because CTFd's theme switch causes a full page reload, the MutationObserver for logo swapping is a progressive enhancement — useful if CTFd ever adopts client-side switching, but the primary mechanism is simply reading `data-bs-theme` on `DOMContentLoaded` and setting the correct logo `src` once.

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

## 6. MutationObserver for Logo Theme Swap

**Decision**: Observe `<html>` for `data-bs-theme` attribute changes using `MutationObserver`. On change, update logo `src` to the appropriate variant.

```javascript
const observer = new MutationObserver(() => {
  const theme = document.documentElement.getAttribute('data-bs-theme');
  logo.src = theme === 'light' ? LOGO_LIGHT_URL : LOGO_DARK_URL;
});
observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-bs-theme'] });
```

**On initial load**: Read `data-bs-theme` once on `DOMContentLoaded` and set logo `src` before attaching the observer.

**Note**: Since CTFd currently reloads on theme switch, the observer fires after reload — initial load handling is the primary path. Observer provides future-proofing for client-side switching.
