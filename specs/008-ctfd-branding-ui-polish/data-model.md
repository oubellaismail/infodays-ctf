# Data Model: CTFd Branding & UI Polish

No persistent data entities. This feature is purely presentational — it changes how existing data is displayed, not what data exists or how it is stored.

## Design Entities (non-persistent)

### Color Token

A named CSS custom property with a dark-mode value (dark-only platform).

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | CSS variable name, e.g. `--bs-body-bg` |
| `dark_value` | hex string | Value when `data-bs-theme="dark"` |
| `bootstrap_variable` | string | The Bootstrap 5 variable being overridden |

Full token set defined in `specs/design/colors.md`.

---

### Theme Mode

The platform is dark-only. The CTFd theme toggle is hidden via CSS.

| Value | Description | Logo Variant |
|-------|-------------|-------------|
| `dark` | Only mode. Near-black navy backgrounds. | `logo-dark.png` |

**State carrier**: `data-bs-theme="dark"` attribute on `<html>` element. Always dark — theme toggle hidden via `.theme-switch { display: none !important; }`.

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

The logo image file used on the dark-only platform.

| Variant | File | Background suitability |
|---------|------|----------------------|
| Dark mode logo | `ctfd-plugin/assets/logo-dark.png` | Dark backgrounds (glowing white wordmark) |

Served at: `/plugins/ctfd_plugin/static/logo-dark.png`

> **Note**: `logo-light.png` exists in the assets directory but is not used — the platform is dark-only.
