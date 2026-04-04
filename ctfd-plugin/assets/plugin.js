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

  var SERVICE_CATEGORIES = ["web", "pwn", "misc", "crypto", "forensics", "reversing", "osint"];

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
    container.style.cssText = "margin-bottom:12px;padding:10px;border:1px solid #444;border-radius:6px;background:rgba(255,255,255,0.05);";

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

    // null means challenge has no instance yet → treat as fresh
    var status = challenge ? challenge.status : "fresh";
    currentStatus = status;

    container.innerHTML = "";

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
      btn.onclick = handleStart;
      container.appendChild(badge);
      container.appendChild(btn);
    } else if (status === "running") {
      badge.textContent = "Running";
      badge.style.background = "#28a745";
      btn.textContent = "\u23F9 Stop Instance";
      btn.className += " btn-danger";
      btn.onclick = handleStop;
      container.appendChild(badge);
      container.appendChild(btn);

      if (challenge && challenge.url) {
        if (challenge.url.startsWith("nc ")) {
          // TCP challenge: show copyable command, not a link
          var code = document.createElement("code");
          code.textContent = challenge.url;
          code.style.cssText = "margin-left:8px;padding:2px 6px;background:rgba(0,0,0,0.3);border-radius:4px;font-size:0.9em;user-select:all;cursor:text;";
          container.appendChild(code);
        } else {
          var urlLink = document.createElement("a");
          urlLink.href = challenge.url;
          urlLink.target = "_blank";
          urlLink.rel = "noopener noreferrer";
          urlLink.textContent = challenge.url;
          urlLink.style.marginLeft = "8px";
          container.appendChild(urlLink);
        }
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
    badge.style.cssText = "margin-right:8px;padding:2px 8px;border-radius:4px;font-size:0.8em;background:#dc3545;color:#fff;";
    container.appendChild(badge);

    var btn = document.createElement("button");
    btn.className = "btn btn-sm btn-secondary";
    btn.disabled = true;
    btn.textContent = "Unavailable";
    btn.style.marginRight = "6px";
    container.appendChild(btn);

    var retryLink = document.createElement("a");
    retryLink.href = "#";
    retryLink.textContent = "Retry";
    retryLink.style.marginLeft = "4px";
    retryLink.onclick = function (e) {
      e.preventDefault();
      updateUI();
    };
    container.appendChild(retryLink);
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
        alert(data.detail || "Max 4 active instances reached. Stop one to continue.");
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

    if (info.name) {
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

  // ─── Bootstrap ──────────────────────────────────────────────────────────────

  function init() {
    console.log("[ctf-controller] Plugin loaded, team_id=" + TEAM_ID + ", admin=" + IS_ADMIN);
    watchChallengeModal();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
