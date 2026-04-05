# Quickstart: CTFd Branding & UI Polish

## Prerequisites

- CTFd running (Phase 2 complete) — either locally via `docker compose` or deployed on DOKS
- CTFd plugin installed (Phase 3 complete) — `ctfd-plugin/` mounted or copied into CTFd's plugins directory
- Access to `https://ctfd.infodays.net` (or local equivalent)

## Local Testing (Docker)

The fastest way to test visual changes is against a local CTFd instance:

```bash
# From repo root — start a minimal CTFd stack
docker run -d \
  --name ctfd-test \
  -p 8000:8000 \
  -e DATABASE_URL=sqlite:////tmp/ctfd.db \
  -v $(pwd)/ctfd-plugin:/opt/CTFd/CTFd/plugins/ctfd_plugin \
  ctfd/ctfd:latest

# Open in browser
open http://localhost:8000
```

After code changes to `style.css` or `plugin.js`, hard-refresh the browser (`Cmd+Shift+R` / `Ctrl+Shift+R`) — no container restart needed (files are volume-mounted).

## Verifying Dark Mode (default)

1. Load any CTFd page
2. Open browser DevTools → Elements
3. Confirm `<html data-bs-theme="dark">` is set
4. Confirm `body` computed `background-color` matches `#020511`
5. Confirm `body` computed `color` matches `#D6DFEC`
6. Confirm Infodays logo visible in navbar
7. Confirm body font is Inter (DevTools → Computed → font-family)
8. Confirm background shows logo-inspired SVG pattern tile (triangles, L-brackets, squares)
9. Confirm radial glow spotlights visible (blue from top, warm accent bottom-left)
10. Confirm SVG noise texture overlay at low opacity

## Verifying Light Mode

1. Log in → Account Settings → Theme → Light
2. Confirm page reloads with `<html data-bs-theme="light">`
3. Confirm `body` background is `#F2F5FC`
4. Confirm logo swaps to `logo-light.png`
5. Confirm no dark values visible (no near-black backgrounds in light mode)

## Verifying the Challenge Instance Panel

1. Log in as a team account
2. Open a web, pwn, or misc challenge modal
3. Confirm the instance manager panel renders:
   - Two-row layout: badge + button on top, connection info below
   - Blue left accent border on the panel
   - Status badge uses `.ctf-badge` class (inspect element — no inline style)
   - Start button uses Bootstrap primary blue
4. Start an instance → confirm badge shows "Running" with pulse-glow animation
5. Confirm instance URL renders in JetBrains Mono in a dark connection row with "OPEN" label
6. For a TCP challenge: confirm nc command renders with "CONNECT" label in `.ctf-nc-command`
7. Open a crypto/forensics challenge → confirm no instance panel injected
8. Start 5 instances → confirm inline warning banner (not browser alert) appears with dismiss button
9. Return to challenges board → confirm running instances show blue left border + pulsing dot indicator

## Verifying Board Instance Indicators

1. Start one or more challenge instances
2. Navigate to the challenges board page
3. Confirm running challenges have a blue left border accent
4. Confirm a small pulsing blue dot appears in the top-right corner of running challenge cards
5. Stop an instance → confirm the card reverts to default styling (may take up to 20s poll)
6. Open browser console → confirm `[ctf-controller] challenge buttons detected, starting board polling`

## Verifying Hero Banner

1. Navigate to challenges page
2. Confirm hero/jumbotron has:
   - Scan lines (faint horizontal stripes)
   - Logo-inspired pattern (triangles + L-brackets)
   - Animated gradient sweep (blue light scanning across, 6s cycle)
   - Blue gradient accent line at the bottom edge
   - Heading text with subtle blue text-shadow glow

## Verifying Navbar Glassmorphism

1. Scroll on any page with enough content
2. Confirm navbar background is translucent with blur effect (`backdrop-filter: blur(12px)`)
3. Content should be visible (blurred) behind the navbar

## Verifying Card Hover Glow

1. Hover over any card element (challenge modal, scoreboard cards)
2. Confirm border transitions to blue and a soft blue box-shadow glow appears

## Verifying Zero Inline Colors in plugin.js

```bash
# Should return zero matches
grep -E 'style\.(color|background|border)' ctfd-plugin/assets/plugin.js
grep -E '#[0-9a-fA-F]{3,6}' ctfd-plugin/assets/plugin.js
grep -E 'rgba?\(' ctfd-plugin/assets/plugin.js
```

## Verifying Existing Functionality (Regression)

```bash
# Run CTFd acceptance tests (must all pass after branding changes)
bash infra/tests/validate-ctfd.sh
```

Manual regression checks:
- Submit a correct flag → score increases correctly
- Submit a wrong flag → "Incorrect" message appears
- View scoreboard → teams visible, ordered correctly
- Admin panel → accessible, no console errors

## Checking Font Loading

Open browser DevTools → Network → filter by "fonts"
- Confirm `Inter` loaded from `fonts.gstatic.com`
- Confirm `JetBrains Mono` loaded from `fonts.gstatic.com`
- Simulate offline: DevTools → Network → Offline → reload
- Confirm page still readable with system font fallbacks
