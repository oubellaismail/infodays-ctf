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
   - Container has dark card background (dark mode) or white (light mode)
   - Status badge uses `.ctf-badge` class (inspect element — no inline style)
   - Start button uses Bootstrap primary blue
4. Start an instance → confirm badge turns green (`.ctf-badge--running`)
5. Confirm instance URL renders in JetBrains Mono
6. For a TCP challenge: confirm nc command renders in `.ctf-nc-command` with monospace font
7. Open a crypto/forensics challenge → confirm no instance panel injected

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
