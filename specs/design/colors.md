# Infodays CTF — Color Palette

## Dark Mode (default)

| Token | Hex | Usage |
|-------|-----|-------|
| Background | `#020511` | Page background |
| Card | `#070D1A` | Card surfaces |
| Popover | `#050B18` | Popovers, dropdowns |
| Primary | `#397BE9` | Primary actions, links, highlights |
| Primary Foreground | `#FFFFFF` | Text on primary |
| Secondary | `#162235` | Secondary surfaces |
| Secondary Foreground | `#C6CEDB` | Text on secondary |
| Muted | `#0E1624` | Muted backgrounds |
| Muted Foreground | `#7E90AE` | Placeholder text, secondary labels |
| Accent | `#132139` | Hover states, accent surfaces |
| Accent Foreground | `#E7EFFC` | Text on accent |
| Foreground / Text | `#D6DFEC` | Body text |
| Border / Input | `#192230` | Borders, input outlines |
| Destructive | `#861118` | Errors, delete actions |

## Light Mode

| Token | Hex | Usage |
|-------|-----|-------|
| Background | `#F2F5FC` | Page background |
| Card | `#FFFFFF` | Card surfaces |
| Popover | `#F8FAFD` | Popovers, dropdowns |
| Primary | `#2563EB` | Primary actions, links, highlights (darkened from `#397BE9` for AA contrast on white — 5.1:1 ✓) |
| Primary Foreground | `#FFFFFF` | Text on primary |
| Secondary | `#DDE6F5` | Secondary surfaces |
| Secondary Foreground | `#1E3048` | Text on secondary |
| Muted | `#EBF0F8` | Muted backgrounds |
| Muted Foreground | `#4A5E78` | Placeholder text, secondary labels |
| Accent | `#E0EAF7` | Hover states, accent surfaces |
| Accent Foreground | `#0D1B2E` | Text on accent |
| Foreground / Text | `#0A1628` | Body text |
| Border / Input | `#C4CDD9` | Borders, input outlines |
| Destructive | `#B91C1C` | Errors, delete actions |

## Brand Accent (both modes)

| Token | Hex | Usage |
|-------|-----|-------|
| Logo Chevron | `#E84B2A` | Orange-red chevron marks in the logo — consider adding as a UI accent token |

## Notes

- Dark mode is the default. Light mode uses the same blue-navy hue family at inverted lightness.
- Primary differs between modes: `#397BE9` (dark) vs `#2563EB` (light) — same family, light mode version darkened for WCAG AA compliance.
- The light logo (`logo-light.png`) currently uses deep purple (`~#4B0FCC`) which does not match the blue primary. Blue is the canonical brand primary — the light logo may need updating.
- Logo chevron orange (`#E84B2A`) is not in either token set. Add as `--color-brand-accent` if used in UI.
- CSS implementation: use `data-bs-theme="dark|light"` on `<html>` with Bootstrap 5 CSS variables mapped to these tokens.
