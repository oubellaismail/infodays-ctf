/**
 * CTFd Controller Plugin - client-side challenge instance management
 *
 * Config injected by __init__.py (after_request) as window.CTF_CONTROLLER:
 *   { team_id, url, key }
 *
 * Reads challenge ID and category from the open challenge modal via CTFd's
 * DOM structure. Hooks in via MutationObserver watching for the challenge window.
 */

(function () {
  var cfg = window.CTF_CONTROLLER;
  if (!cfg) return;
  if (!cfg.team_id || cfg.team_id === "null" || cfg.team_id === null) return;

  var TEAM_ID = String(cfg.team_id);
  var CONTROLLER_URL = cfg.url;
  var CONTROLLER_KEY = cfg.key;

  var SERVICE_CATEGORIES = ["web", "pwn", "misc"];

  // Per-challenge state (reset when modal opens)
  var currentChallengeId = null;
  var currentStatus = null;
  var refreshTimer = null;

  // ─── CTFd API helpers ───────────────────────────────────────────────────────

  function ctfdFetch(path) {
    return fetch(path, {
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
      credentials: "same-origin",
    });
  }

  function getCsrfToken() {
    var meta = document.querySelector("meta[name='csrf-token']");
    return meta ? meta.content : "";
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

  // ─── Controller API helpers ─────────────────────────────────────────────────

  async function fetchStatus() {
    try {
      var resp = await fetch(CONTROLLER_URL + "/status/" + TEAM_ID, {
        headers: { "X-Controller-Key": CONTROLLER_KEY },
      });
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
    container.style.marginBottom = "10px";

    // Insert before challenge description in the modal
    var descEl =
      document.querySelector(".challenge-container .challenge-desc") ||
      document.querySelector("#challenge-id-description") ||
      document.querySelector(".modal-body");

    if (descEl) {
      descEl.insertBefore(container, descEl.firstChild);
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
    badge.style.marginRight = "8px";
    badge.style.padding = "2px 8px";
    badge.style.borderRadius = "4px";
    badge.style.fontSize = "0.8em";

    var btn = document.createElement("button");
    btn.style.marginRight = "6px";
    btn.className = "btn btn-sm";

    if (status === "fresh" || status === "suspended") {
      badge.textContent = status === "fresh" ? "Fresh" : "Suspended";
      badge.style.background = "#6c757d";
      badge.style.color = "#fff";
      btn.textContent = "▶ Start Instance";
      btn.className += " btn-primary";
      btn.onclick = handleStart;
      container.appendChild(badge);
      container.appendChild(btn);
    } else if (status === "running") {
      badge.textContent = "Running";
      badge.style.background = "#28a745";
      badge.style.color = "#fff";
      btn.textContent = "⏹ Stop Instance";
      btn.className += " btn-danger";
      btn.onclick = handleStop;
      container.appendChild(badge);
      container.appendChild(btn);

      if (challenge && challenge.url) {
        var urlLink = document.createElement("a");
        urlLink.href = challenge.url;
        urlLink.target = "_blank";
        urlLink.rel = "noopener noreferrer";
        urlLink.textContent = challenge.url;
        container.appendChild(urlLink);

        var note = document.createElement("small");
        note.textContent = " (starting, may take ~30 seconds if just activated)";
        note.style.color = "#6c757d";
        container.appendChild(note);
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
    badge.textContent = "Unknown";
    badge.style.cssText = "margin-right:8px;padding:2px 8px;border-radius:4px;font-size:0.8em;background:#6c757d;color:#fff;";
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
      btn.textContent = currentStatus === "running" ? "Stopping…" : "Starting…";
    }
  }

  // ─── Button handlers ────────────────────────────────────────────────────────

  async function handleStart() {
    setButtonLoading(true);
    try {
      var resp = await fetch(CONTROLLER_URL + "/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Controller-Key": CONTROLLER_KEY },
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
        activated_at: new Date().toISOString(),
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
      var resp = await fetch(CONTROLLER_URL + "/deactivate", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Controller-Key": CONTROLLER_KEY },
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
        activated_at: null,
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

  // ─── Challenge modal hooking ─────────────────────────────────────────────────

  async function onChallengeOpen(challengeId) {
    stopPolling();
    currentChallengeId = null;
    currentStatus = null;

    // Remove any existing UI container
    var old = document.getElementById("ctf-controller-ui");
    if (old) old.remove();

    // Fetch challenge category from CTFd API
    var info = await fetchChallengeInfo(challengeId);
    if (!info) return;

    var category = (info.category || "").toLowerCase();
    if (!SERVICE_CATEGORIES.includes(category)) return;

    currentChallengeId = info.id ? String(info.id) : null;

    // CTFd challenge IDs in manifests use the challenge name slug, not numeric ID.
    // The manifest challenge_id (e.g., "web-sqli") must match what bulk_spawn used.
    // Use the challenge name to derive manifest ID: lowercase hyphenated.
    // Fallback: use numeric ID as string if no name-based slug is available.
    // The status endpoint matches on challenge label set by bulk_spawn.
    // We need the manifest ID, not the CTFd numeric ID.
    // Use CTFd challenge name to look up: matching is done server-side via label selector.
    // Pass the CTFd numeric ID and let the status response match by label.
    // Note: bulk_spawn sets label challenge={manifest_id}, e.g., "web-sqli".
    // The manifest_id is the id field from challenges/manifests/*.yaml.
    // We store it in the description or use a convention: category + "-" + name slug.
    // For now, we read the manifest ID from the challenge type field if CTFd exposes it.
    // Best approach: store manifest_id in CTFd challenge description as hidden metadata,
    // or use a consistent naming convention. For this event, we use the challenge name
    // converted to a slug as the manifest ID.
    if (info.name) {
      currentChallengeId = info.name.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "");
    }

    if (!currentChallengeId) return;

    updateUI();
    startPolling();
  }

  function watchChallengeModal() {
    // CTFd challenge modals are created dynamically. Watch for:
    // - CTFd 3.x: Bootstrap modal #challenge-window shown
    // - CTFd 3.5+: Modal visibility changes on #challenge-window or similar
    var observer = new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i++) {
        var mutation = mutations[i];

        // Watch for class changes (Bootstrap adding 'show' to modal)
        if (mutation.type === "attributes" && mutation.attributeName === "class") {
          var el = mutation.target;
          if (el.id === "challenge-window" || el.classList.contains("modal")) {
            if (el.classList.contains("show")) {
              // Modal opened — find challenge ID
              var cidEl =
                el.querySelector("[data-challenge-id]") ||
                el.querySelector("[data-cid]") ||
                el.querySelector("form[data-challenge-id]");
              var cid = cidEl ? (cidEl.dataset.challengeId || cidEl.dataset.cid) : null;
              if (cid) onChallengeOpen(cid);
            } else {
              // Modal closed
              stopPolling();
            }
          }
        }
      }
    });

    observer.observe(document.body, { attributes: true, subtree: true, attributeFilter: ["class"] });

    // Also hook into CTFd's JS event system if available
    if (window.CTFd && window.CTFd.ui) {
      // CTFd 3.5+ event hooks (if available)
      try {
        document.addEventListener("challenge-load", function (e) {
          if (e.detail && e.detail.id) onChallengeOpen(e.detail.id);
        });
      } catch (e) {}
    }
  }

  // ─── Bootstrap ──────────────────────────────────────────────────────────────

  function init() {
    watchChallengeModal();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
