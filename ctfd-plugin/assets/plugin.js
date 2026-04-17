/**
 * CTFd Controller Plugin - client-side challenge instance management
 *
 * Config injected by __init__.py (after_request) as window.CTF_CONTROLLER:
 *   { team_id, is_admin }
 *
 * All controller API calls go through the CTFd proxy (/controller-proxy/...)
 * so no cluster-internal URLs or API keys are exposed to the browser.
 */

(function () {

  // ─── Logo injection (runs for ALL visitors, including unauthenticated) ─────

  var LOGO_URL = "/plugins/controller-plugin/assets/logo-dark.png";

  function injectLogo() {
    var brand = document.querySelector(".navbar-brand");
    if (!brand) return;
    if (document.getElementById("ctf-brand-logo")) return;
    var img = document.createElement("img");
    img.id  = "ctf-brand-logo";
    img.className = "ctf-logo";
    img.src = LOGO_URL;
    img.alt = "Infodays CTF";
    img.width = 32;
    img.height = 32;
    // Remove the text next to the logo — logo only
    brand.textContent = "";
    brand.appendChild(img);
  }

  function forceDarkMode() {
    // Always enforce dark mode — toggle button hidden via CSS (.theme-switch)
    document.documentElement.setAttribute("data-bs-theme", "dark");
    // If anything tries to flip the theme, snap it back
    new MutationObserver(function() {
      if (document.documentElement.getAttribute("data-bs-theme") !== "dark") {
        document.documentElement.setAttribute("data-bs-theme", "dark");
      }
    }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-bs-theme"] });
  }

  function injectRulesLink() {
    var navList = document.querySelector(".navbar-nav");
    if (!navList) return;
    // Don't duplicate
    if (navList.querySelector('a[href="/rules"]')) return;
    var li = document.createElement("li");
    li.className = "nav-item";
    var a = document.createElement("a");
    a.className = "nav-link";
    a.href = "/rules";
    a.textContent = "Rules";
    li.appendChild(a);
    // Insert after the first nav item (usually Challenges)
    var firstItem = navList.querySelector(".nav-item");
    if (firstItem && firstItem.nextSibling) {
      navList.insertBefore(li, firstItem.nextSibling);
    } else {
      navList.appendChild(li);
    }
  }

  function initLogo() {
    forceDarkMode();
    injectLogo();
    injectRulesLink();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initLogo);
  } else {
    initLogo();
  }

  // ─── Controller UI (requires authenticated team) ──────────────────────────

  var cfg = window.CTF_CONTROLLER;
  if (!cfg) return;

  var IS_ADMIN = cfg.is_admin === true;
  // Admins have no team — default to team 1 for testing; normal users must have a team
  var TEAM_ID;
  if (cfg.team_id && cfg.team_id !== null) {
    TEAM_ID = String(cfg.team_id);
  } else if (IS_ADMIN) {
    TEAM_ID = "1";
  } else {
    return; // not logged in or no team
  }

  var SERVICE_CATEGORIES = ["web", "pwn", "misc", "crypto", "forensics", "reversing", "osint", "stego"];

  // Global instance state — tracks all running instances for board indicators
  var allInstanceStatuses = {}; // { challenge_id: { status, url } }
  var boardPollTimer = null;

  // Per-challenge state (reset when modal opens)
  var currentChallengeId = null;
  var currentStatus = null;
  var refreshTimer = null;

  // ─── CTFd API helpers ───────────────────────────────────────────────────────

  function getCsrfToken() {
    // CTFd 3.8.2 stores CSRF nonce in window.init.csrfNonce
    return (window.init && window.init.csrfNonce) ? window.init.csrfNonce : "";
  }

  function ctfdFetch(path, opts) {
    var defaults = {
      headers: { "Content-Type": "application/json", "CSRF-Token": getCsrfToken() },
      credentials: "same-origin",
    };
    if (opts) {
      defaults.method = opts.method || "GET";
      if (opts.body) defaults.body = opts.body;
    }
    return fetch(path, defaults);
  }

  // Fetch challenge details (id, category) from CTFd API
  async function fetchChallengeInfo(challengeId) {
    try {
      var resp = await ctfdFetch("/api/v1/challenges/" + challengeId);
      if (!resp.ok) return null;
      var data = await resp.json();
      return data.data || null;
    } catch (e) {
      return null;
    }
  }

  // ─── Controller proxy helpers (all requests go through CTFd) ──────────────

  async function fetchStatus() {
    try {
      var resp = await ctfdFetch("/controller-proxy/status/" + TEAM_ID);
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      var data = await resp.json();
      return (data.challenges || []).find(function (c) {
        return c.challenge_id === currentChallengeId;
      }) || null;
    } catch (err) {
      console.error("[ctf-controller] status fetch failed:", err);
      return undefined; // undefined = error, null = not found
    }
  }

  // ─── UI rendering ───────────────────────────────────────────────────────────

  function getOrCreateContainer() {
    var existing = document.getElementById("ctf-controller-ui");
    if (existing) return existing;

    var container = document.createElement("div");
    container.id = "ctf-controller-ui";
    container.className = "ctf-controller-ui";
    container.setAttribute("role", "status");
    container.setAttribute("aria-live", "polite");

    // Insert before challenge description in the modal
    var descEl =
      document.querySelector(".challenge-desc") ||
      document.querySelector(".modal-body");

    if (descEl) {
      descEl.parentNode.insertBefore(container, descEl);
    }
    return container;
  }

  function renderUI(challenge) {
    var container = getOrCreateContainer();
    if (!container) return;

    if (challenge === undefined) {
      renderUnknown(container);
      return;
    }

    // null means challenge is not managed by the controller (static/file
    // download challenges). Show a download button pointing to the plugin's
    // per-team zip endpoint.
    if (challenge === null) {
      container.innerHTML = "";
      if (currentChallengeId) {
        var dlRow = document.createElement("div");
        dlRow.className = "ctf-controller-row";

        var badge = document.createElement("span");
        badge.className = "ctf-badge ctf-badge--download";
        badge.textContent = "File Challenge";
        dlRow.appendChild(badge);

        var dlBtn = document.createElement("a");
        dlBtn.href = "/download/" + currentChallengeId;
        dlBtn.className = "btn btn-sm btn-primary";
        dlBtn.textContent = "\u2B07 Download Challenge";
        dlBtn.setAttribute("download", "");
        dlRow.appendChild(dlBtn);

        container.appendChild(dlRow);
      }
      return;
    }

    var status = challenge.status || "fresh";
    currentStatus = status;

    container.innerHTML = "";

    var badge = document.createElement("span");
    badge.className = "ctf-badge";

    var btn = document.createElement("button");
    btn.className = "btn btn-sm";

    // Top row: badge + action button
    var topRow = document.createElement("div");
    topRow.className = "ctf-controller-row";

    if (status === "fresh" || status === "suspended") {
      badge.textContent = status === "fresh" ? "Not Started" : "Stopped";
      badge.classList.add(status === "fresh" ? "ctf-badge--fresh" : "ctf-badge--suspended");
      btn.textContent = "\u25B6 Start Instance";
      btn.classList.add("btn-primary");
      btn.onclick = handleStart;
      topRow.appendChild(badge);
      topRow.appendChild(btn);
      container.appendChild(topRow);
    } else if (status === "running") {
      badge.textContent = "Running";
      badge.classList.add("ctf-badge--running");
      btn.textContent = "\u23F9 Stop Instance";
      btn.classList.add("btn-outline-danger");
      btn.onclick = handleStop;
      topRow.appendChild(badge);
      topRow.appendChild(btn);
      container.appendChild(topRow);

      if (challenge && challenge.url) {
        // Connection row: label + copyable value
        var connRow = document.createElement("div");
        connRow.className = "ctf-controller-conn";

        var label = document.createElement("span");
        label.className = "ctf-conn-label";

        if (challenge.url.startsWith("nc ")) {
          label.textContent = "Connect";
          var code = document.createElement("code");
          code.textContent = challenge.url;
          code.className = "ctf-nc-command";
          connRow.appendChild(label);
          connRow.appendChild(code);
        } else {
          label.textContent = "Open";
          var urlLink = document.createElement("a");
          urlLink.href = challenge.url;
          urlLink.target = "_blank";
          urlLink.rel = "noopener noreferrer";
          urlLink.textContent = challenge.url;
          urlLink.className = "ctf-instance-url";
          connRow.appendChild(label);
          connRow.appendChild(urlLink);
        }
        container.appendChild(connRow);
      }
    } else {
      renderUnknown(container);
    }
  }

  function renderUnknown(container) {
    if (!container) container = getOrCreateContainer();
    if (!container) return;

    container.innerHTML = "";

    var badge = document.createElement("span");
    badge.textContent = "Error";
    badge.className = "ctf-badge ctf-badge--error";
    container.appendChild(badge);

    var btn = document.createElement("button");
    btn.className = "btn btn-sm btn-secondary";
    btn.disabled = true;
    btn.textContent = "Unavailable";
    container.appendChild(btn);

    var retryLink = document.createElement("a");
    retryLink.href = "#";
    retryLink.textContent = "Retry";
    retryLink.className = "ctf-retry-link";
    retryLink.onclick = function (e) {
      e.preventDefault();
      updateUI();
    };
    container.appendChild(retryLink);
  }

  function showInlineWarning(message) {
    var container = document.getElementById("ctf-controller-ui");
    if (!container) return;

    // Remove any existing warning
    var old = container.querySelector(".ctf-inline-warning");
    if (old) old.remove();

    var warning = document.createElement("div");
    warning.className = "ctf-inline-warning";
    warning.setAttribute("role", "alert");

    var icon = document.createElement("span");
    icon.className = "ctf-warning-icon";
    icon.textContent = "\u26A0";
    icon.setAttribute("aria-hidden", "true");

    var text = document.createElement("span");
    text.textContent = message;

    var dismiss = document.createElement("button");
    dismiss.className = "ctf-warning-dismiss";
    dismiss.setAttribute("aria-label", "Dismiss warning");
    dismiss.textContent = "\u2715";
    dismiss.onclick = function () { warning.remove(); };

    warning.appendChild(icon);
    warning.appendChild(text);
    warning.appendChild(dismiss);

    // Insert at the top of the container (before the row)
    container.insertBefore(warning, container.firstChild);
  }

  function setButtonLoading(loading) {
    var btn = document.querySelector("#ctf-controller-ui button");
    if (!btn) return;
    btn.disabled = loading;
    if (loading) {
      btn.textContent = currentStatus === "running" ? "Stopping\u2026" : "Starting\u2026";
    }
  }

  // ─── Button handlers ────────────────────────────────────────────────────────

  async function handleStart() {
    setButtonLoading(true);
    try {
      var resp = await ctfdFetch("/controller-proxy/activate", {
        method: "POST",
        body: JSON.stringify({ team_id: TEAM_ID, challenge_id: currentChallengeId }),
      });
      var data = await resp.json();

      if (resp.status === 429) {
        showInlineWarning(data.detail || "Instance limit reached — you can run up to 4 at a time. Stop an active instance first.");
        setButtonLoading(false);
        return;
      }
      if (!resp.ok) {
        renderUnknown();
        setButtonLoading(false);
        return;
      }

      renderUI({
        challenge_id: currentChallengeId,
        status: "running",
        url: data.url,
      });
      setButtonLoading(false);
      // Update board indicators immediately
      allInstanceStatuses[currentChallengeId] = { status: "running", url: data.url };
      updateBoardIndicators();
    } catch (err) {
      console.error("[ctf-controller] start failed:", err);
      renderUnknown();
      setButtonLoading(false);
    }
  }

  async function handleStop() {
    setButtonLoading(true);
    try {
      var resp = await ctfdFetch("/controller-proxy/deactivate", {
        method: "POST",
        body: JSON.stringify({ team_id: TEAM_ID, challenge_id: currentChallengeId }),
      });

      if (!resp.ok) {
        renderUnknown();
        setButtonLoading(false);
        return;
      }

      renderUI({
        challenge_id: currentChallengeId,
        status: "suspended",
        url: null,
      });
      setButtonLoading(false);
      // Update board indicators immediately
      allInstanceStatuses[currentChallengeId] = { status: "suspended", url: null };
      updateBoardIndicators();
    } catch (err) {
      console.error("[ctf-controller] stop failed:", err);
      renderUnknown();
      setButtonLoading(false);
    }
  }

  // ─── Status polling ─────────────────────────────────────────────────────────

  async function updateUI() {
    var challenge = await fetchStatus();
    renderUI(challenge);
  }

  function startPolling() {
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(updateUI, 15000);
  }

  function stopPolling() {
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = null;
  }

  // ─── Challenge modal hooking (CTFd 3.8.2 — Bootstrap 5 modal events) ───────

  var openingId = null;

  async function onChallengeOpen(numericId) {
    numericId = String(numericId);
    if (openingId === numericId) return;
    openingId = numericId;

    stopPolling();
    currentChallengeId = null;
    currentStatus = null;

    var old = document.getElementById("ctf-controller-ui");
    if (old) old.remove();

    var info = await fetchChallengeInfo(numericId);
    if (openingId !== numericId) return;
    openingId = null;
    if (!info) {
      console.warn("[ctf-controller] fetchChallengeInfo returned null for", numericId);
      return;
    }

    var category = (info.category || "").toLowerCase();
    if (!SERVICE_CATEGORIES.includes(category)) {
      console.log("[ctf-controller] skipping non-service category:", category);
      return;
    }

    // Derive deployment ID from the CTFd flag's 'data' field (manifest entry ID).
    // This handles bundle manifests where the CTFd challenge name is e.g.
    // "Man City — View Source" but the deployment is "man-city".
    // The flag data field is e.g. "man-city-1" → strip trailing -N → "man-city".
    try {
      var flagResp = await ctfdFetch("/api/v1/flags?challenge_id=" + numericId + "&per_page=1");
      if (flagResp.ok) {
        var flagData = await flagResp.json();
        var teamFlag = (flagData.data || []).find(function (f) { return f.type === "team"; });
        if (teamFlag && teamFlag.data) {
          // Strip trailing bundle suffix (-1, -2, ...) to get deployment ID
          currentChallengeId = teamFlag.data.replace(/-\d+$/, "");
        }
      }
    } catch (e) { /* fall through to name-based slug */ }

    if (!currentChallengeId && info.name) {
      currentChallengeId = info.name.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "");
    }
    if (!currentChallengeId) return;

    console.log("[ctf-controller] challenge opened:", currentChallengeId);
    updateUI();
    startPolling();
  }

  function onModalClose() {
    stopPolling();
    openingId = null;
    currentChallengeId = null;
    var ui = document.getElementById("ctf-controller-ui");
    if (ui) ui.remove();
  }

  function watchChallengeModal() {
    // Use Bootstrap 5 native modal events on #challenge-window.
    // "shown.bs.modal" fires after the modal is fully visible and x-html content is rendered.
    // "hidden.bs.modal" fires when the modal closes.
    // These events bubble, so we listen on document for safety.

    document.addEventListener("shown.bs.modal", function (e) {
      var modal = e.target;
      if (modal.id !== "challenge-window") return;

      console.log("[ctf-controller] modal shown event fired");

      // Find challenge ID from the hidden input rendered by x-html
      var cidEl = modal.querySelector("#challenge-id");
      var cid = cidEl ? cidEl.value : null;

      if (!cid) {
        // Fallback: parse from URL hash (#ChallengeName-ID)
        var hash = decodeURIComponent(window.location.hash.slice(1));
        var m = hash.match(/-(\d+)$/);
        cid = m ? m[1] : null;
      }

      if (cid) {
        console.log("[ctf-controller] detected challenge id:", cid);
        onChallengeOpen(cid);
      }
    });

    document.addEventListener("hidden.bs.modal", function (e) {
      if (e.target.id === "challenge-window") {
        onModalClose();
      }
    });

    // Handle direct deep-link: page loaded with hash already set.
    // ChallengeBoard.init() in challenges.js auto-opens the modal if hash exists,
    // which will fire shown.bs.modal — no extra handling needed.
  }

  // ─── Board-level instance indicators ────────────────────────────────────────

  function slugify(name) {
    return name.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "");
  }

  function findChallengeButtons() {
    // CTFd renders challenge cards as .challenge-button elements with the challenge name as text
    return document.querySelectorAll(".challenge-button");
  }

  function updateBoardIndicators() {
    var buttons = findChallengeButtons();
    buttons.forEach(function (btn) {
      var name = (btn.textContent || "").trim();
      // Challenge buttons may contain points text — extract just the name
      // CTFd format: "Challenge Name\n100" — take first line
      var firstLine = name.split("\n")[0].trim();
      var slug = slugify(firstLine);

      // Remove all instance status classes
      btn.classList.remove("ctf-instance-active", "ctf-instance-stopped");

      var instance = allInstanceStatuses[slug];
      if (instance && instance.status === "running") {
        btn.classList.add("ctf-instance-active");
      } else if (instance && instance.status === "suspended") {
        btn.classList.add("ctf-instance-stopped");
      }
    });
  }

  async function fetchAllStatuses() {
    try {
      var resp = await ctfdFetch("/controller-proxy/status/" + TEAM_ID);
      if (!resp.ok) return;
      var data = await resp.json();
      allInstanceStatuses = {};
      (data.challenges || []).forEach(function (ch) {
        allInstanceStatuses[ch.challenge_id] = ch;
      });
      updateBoardIndicators();
    } catch (err) {
      console.error("[ctf-controller] board status fetch failed:", err);
    }
  }

  function startBoardPolling() {
    // CTFd renders challenge buttons dynamically via Alpine.js / AJAX —
    // they don't exist at DOMContentLoaded. Use MutationObserver to detect
    // when .challenge-button elements appear, then start polling.
    var alreadyStarted = false;

    function beginPolling() {
      if (alreadyStarted) return;
      alreadyStarted = true;
      console.log("[ctf-controller] challenge buttons detected, starting board polling");
      fetchAllStatuses();
      if (boardPollTimer) clearInterval(boardPollTimer);
      boardPollTimer = setInterval(fetchAllStatuses, 20000);
    }

    // Check immediately in case buttons are already rendered
    if (document.querySelector(".challenge-button")) {
      beginPolling();
      return;
    }

    // Watch for buttons to appear
    var observer = new MutationObserver(function () {
      if (document.querySelector(".challenge-button")) {
        observer.disconnect();
        beginPolling();
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });

    // Safety timeout — stop watching after 30s if never found (not on challenges page)
    setTimeout(function () { observer.disconnect(); }, 30000);
  }

  // ─── Bootstrap ──────────────────────────────────────────────────────────────

  function init() {
    console.log("[ctf-controller] Plugin loaded, team_id=" + TEAM_ID + ", admin=" + IS_ADMIN);
    watchChallengeModal();
    startBoardPolling();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
