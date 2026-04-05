# Data Model: CTFd Branding & UI Polish

No persistent data entities. This feature is purely presentational — it changes how existing data is displayed, not what data exists or how it is stored.

## Design Entities (non-persistent)

### Color Token

A named CSS custom property with a dark-mode value and a light-mode value.

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | CSS variable name, e.g. `--bs-body-bg` |
| `dark_value` | hex string | Value when `data-bs-theme="dark"` |
| `light_value` | hex string | Value when `data-bs-theme="light"` |
| `bootstrap_variable` | string | The Bootstrap 5 variable being overridden |

Full token set defined in `specs/design/colors.md`.

---

### Theme Mode

The active color scheme for the platform. Controlled by CTFd; read by the plugin.

| Value | Description | Logo Variant |
|-------|-------------|-------------|
| `dark` | Default. Near-black navy backgrounds. | `logo-dark.png` |
| `light` | Light blue-gray backgrounds. | `logo-light.png` |

**State carrier**: `data-bs-theme` attribute on `<html>` element. Set by CTFd on page load from user preference. Changed by CTFd theme toggle (causes full page reload).

---

### Instance Panel State

The UI state of the challenge instance manager panel. Drives CSS class selection in `plugin.js`.

| State | CSS Class | Badge Color | Button |
|-------|-----------|-------------|--------|
| `fresh` | `.ctf-badge--fresh` | Muted (`#7E90AE`) | Start Instance |
| `suspended` | `.ctf-badge--suspended` | Muted (`#7E90AE`) | Start Instance |
| `running` | `.ctf-badge--running` | Success green | Stop Instance + URL |
| `error` | `.ctf-badge--error` | Destructive (`#861118`) | Retry link |
| `loading` | `.ctf-badge--loading` | Muted (animated) | Disabled button |

**State transitions** (unchanged from Phase 3 — this phase only changes visual representation):
```
fresh → loading → running
running → loading → suspended
running → error (on API failure)
```

---

### Logo Variant

The logo image file served based on active theme mode.

| Variant | File | Background suitability |
|---------|------|----------------------|
| Dark mode logo | `ctfd-plugin/assets/logo-dark.png` | Dark backgrounds (glowing white wordmark) |
| Light mode logo | `ctfd-plugin/assets/logo-light.png` | Light backgrounds (solid wordmark) |

Served at: `/plugins/ctfd_plugin/static/logo-{dark,light}.png`
