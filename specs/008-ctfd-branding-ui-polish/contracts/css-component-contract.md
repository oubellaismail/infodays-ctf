# CSS Component Contract: CTFd Branding & UI Polish

This contract defines the CSS class names emitted by `plugin.js` and the custom properties defined in `style.css`. Both files must stay in sync with this contract.

---

## CSS Custom Properties (defined in `style.css`)

### Dark Mode — `[data-bs-theme="dark"]`

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
  --bs-success:           #1A7F4E;
  --bs-font-sans-serif:   'Inter', system-ui, -apple-system, sans-serif;
  --ctf-brand-accent:     #E84B2A;
  --ctf-badge-running-bg: #1A7F4E;
  --ctf-badge-muted-bg:   #162235;
  --ctf-badge-error-bg:   #861118;
  --ctf-ui-bg:            rgba(255, 255, 255, 0.04);
  --ctf-ui-border:        #192230;
}
```

### Light Mode — `[data-bs-theme="light"]`

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
  --bs-success:           #15803D;
  --bs-font-sans-serif:   'Inter', system-ui, -apple-system, sans-serif;
  --ctf-brand-accent:     #E84B2A;
  --ctf-badge-running-bg: #15803D;
  --ctf-badge-muted-bg:   #DDE6F5;
  --ctf-badge-error-bg:   #B91C1C;
  --ctf-ui-bg:            rgba(0, 0, 0, 0.03);
  --ctf-ui-border:        #C4CDD9;
}
```

---

## CSS Class Contract (emitted by `plugin.js`)

### Instance Manager Container

| Class | Element | Rules |
|-------|---------|-------|
| `.ctf-controller-ui` | `<div>` wrapper | `background: var(--ctf-ui-bg); border: 1px solid var(--ctf-ui-border); border-radius: 4px; padding: 10px; margin-bottom: 12px;` |

### Status Badges

| Class | State | Rules |
|-------|-------|-------|
| `.ctf-badge` | Base | `display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em; color: #fff;` |
| `.ctf-badge--running` | Running | `background: var(--ctf-badge-running-bg);` |
| `.ctf-badge--suspended` | Suspended | `background: var(--ctf-badge-muted-bg); color: var(--bs-secondary-color);` |
| `.ctf-badge--fresh` | Not started | `background: var(--ctf-badge-muted-bg); color: var(--bs-secondary-color);` |
| `.ctf-badge--error` | Error | `background: var(--ctf-badge-error-bg);` |

### Instance Connection Info

| Class | Element | Rules |
|-------|---------|-------|
| `.ctf-instance-url` | `<a>` | `font-family: 'JetBrains Mono', monospace; font-size: 0.9em; word-break: break-all;` |
| `.ctf-nc-command` | `<code>` | `font-family: 'JetBrains Mono', monospace; font-size: 0.9em; background: var(--bs-tertiary-bg); padding: 2px 6px; border-radius: 3px; user-select: all; display: inline-block;` |

### Logo

| Class | Element | Rules |
|-------|---------|-------|
| `.ctf-logo` | `<img>` injected into `.navbar-brand` | `height: 32px; width: auto; margin-right: 8px;` |

---

## Global Typography (applied on `body` / `:root` in `style.css`)

```css
body {
  font-family: var(--bs-font-sans-serif);
  font-size: 14px;
  line-height: 1.5;
}

code, pre, kbd, samp,
.ctf-nc-command,
.ctf-instance-url {
  font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Mono', monospace;
}
```

---

## Invariants

- `plugin.js` MUST NOT contain any hex color values, `rgba()`, or `rgb()` color expressions.
- All color values MUST come from CSS custom properties defined in `style.css`.
- New CSS classes added to `plugin.js` MUST be documented in this contract first.
- The `--ctf-*` namespace is reserved for plugin-specific variables; `--bs-*` overrides Bootstrap only.
