"""
CTFd Controller Plugin - manages team challenge instances.

Provides UI for starting/stopping challenge pods and displays their status.
Proxies browser requests to the cluster-internal controller API.
Uses CTFd's register_script() for reliable script injection.

Also registers a custom 'team' flag type that:
  - Derives the expected flag on the fly from the submitting team's ID + CTF_MASTER_SECRET
  - Detects cross-team flag submission (cheating) and logs it to the `cheaters` table
  - Makes it cryptographically impossible to score points using another team's flag
"""

from flask import Blueprint, request as flask_request, jsonify, Response, make_response, send_file
import urllib.request
import urllib.error
import json
import hmac as _hmac
import hashlib
import os
import io
import zipfile
from datetime import datetime


# ── Helpers ──────────────────────────────────────────────────────────────────

def _derive(team_id, challenge_manifest_id, master_secret):
    """Return the derived flag string for a given team + challenge."""
    message = f"{team_id}:{challenge_manifest_id}".encode()
    digest = _hmac.new(
        master_secret.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()[:32]
    return f"infodays{{{digest}}}"


def _log_cheater(submitting_team_id, submitting_user_id, submitted_flag, owner_team_id, challenge_manifest_id):
    """Insert a row into the cheaters table. Never raises."""
    try:
        from CTFd.models import db
        from sqlalchemy import text
        db.session.execute(
            text("""
                INSERT INTO cheaters
                    (submitting_team_id, submitting_user_id, submitted_flag, owner_team_id, challenge_manifest_id, submitted_at)
                VALUES
                    (:sub_tid, :sub_uid, :flag, :own_tid, :chal, :ts)
            """),
            {
                "sub_tid": submitting_team_id,
                "sub_uid": submitting_user_id,
                "flag":    submitted_flag,
                "own_tid": owner_team_id,
                "chal":    challenge_manifest_id,
                "ts":      datetime.utcnow(),
            },
        )
        db.session.commit()
    except Exception:
        pass  # Never let cheating detection crash flag validation


# ── Team-bound flag type ─────────────────────────────────────────────────────

class CTFdTeamFlag:
    """
    Flag type that validates against the submitting team's derived flag.

    Stored in CTFd flags table as:
        type    = "team"
        content = "team-derived"   (unused placeholder)
        data    = challenge manifest ID  e.g. "pwn-bof"

    One flag row per challenge — no per-team rows needed.

    On wrong submission:
        - Checks if the flag belongs to any other team (O(n) HMAC checks, n=50 → fast)
        - If yes → logs to `cheaters` table and returns False
        - If no  → returns False silently (just a wrong guess)
    """
    name = "team"
    templates = {
        "create": "/plugins/flags/assets/static/create.html",
        "update": "/plugins/flags/assets/static/edit.html",
    }

    @staticmethod
    def compare(chal_key_obj, provided):
        from CTFd.utils.user import get_current_team, get_current_user

        team = get_current_team()
        if team is None:
            return False

        user = get_current_user()
        user_id = user.id if user else None

        challenge_manifest_id = chal_key_obj.data or ""
        master_secret = os.environ.get("CTF_MASTER_SECRET", "")
        if not master_secret or not challenge_manifest_id:
            return False

        # ── Check submitting team's own flag ──────────────────────────────────
        expected = _derive(team.id, challenge_manifest_id, master_secret)
        if _hmac.compare_digest(expected, provided):
            return True

        # ── Wrong flag — check if it belongs to another team (cheating) ───────
        try:
            from CTFd.models import Teams
            all_teams = Teams.query.filter(Teams.id != team.id).all()
            for other in all_teams:
                candidate = _derive(other.id, challenge_manifest_id, master_secret)
                if _hmac.compare_digest(candidate, provided):
                    _log_cheater(team.id, user_id, provided, other.id, challenge_manifest_id)
                    break
        except Exception:
            pass  # Never crash flag validation due to cheating detection

        return False


# ── Plugin entry point ───────────────────────────────────────────────────────

def load(app):
    """Load the CTFd plugin."""
    from CTFd.utils.plugins import register_script

    # Extend session cookie to all subdomains so nginx auth_request on
    # *.challenges.infodays.net forwards a valid CTFd session cookie.
    app.config["SESSION_COOKIE_DOMAIN"] = ".infodays.net"

    # ── Branding: inject stylesheet + Google Fonts ─────────────────────────
    GOOGLE_FONTS_PRECONNECT = '<link rel="preconnect" href="https://fonts.googleapis.com">'
    GOOGLE_FONTS_PRECONNECT2 = '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    GOOGLE_FONTS_URL = (
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=Inter:wght@400;500;600;700'
        '&family=JetBrains+Mono:wght@400;500'
        '&display=swap" media="print" onload="this.media=\'all\'">'
    )
    BRAND_CSS_LINK = (
        '<link rel="stylesheet" href="/plugins/controller-plugin/assets/style.css">'
    )
    GOOGLE_FONTS_NOSCRIPT = (
        '<noscript><link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=Inter:wght@400;500;600;700'
        '&family=JetBrains+Mono:wght@400;500'
        '&display=swap"></noscript>'
    )
    INJECT_TAGS = "\n".join([
        GOOGLE_FONTS_PRECONNECT,
        GOOGLE_FONTS_PRECONNECT2,
        GOOGLE_FONTS_URL,
        GOOGLE_FONTS_NOSCRIPT,
        BRAND_CSS_LINK,
    ])

    @app.after_request
    def inject_brand_assets(response):
        if response.content_type and response.content_type.startswith("text/html"):
            data = response.get_data(as_text=True)
            if "</head>" in data:
                response.set_data(data.replace("</head>", INJECT_TAGS + "\n</head>", 1))
        return response

    blueprint = Blueprint(
        "controller_plugin",
        __name__,
        static_folder="assets",
        static_url_path="/plugins/controller-plugin/assets",
    )

    # ── Dynamic config endpoint ───────────────────────────────────────────────

    @blueprint.route("/controller-plugin/config.js")
    def controller_config_js():
        team_id = "null"
        is_admin = "false"
        try:
            from CTFd.utils.user import get_current_user
            user = get_current_user()
            if user:
                tid = getattr(user, "team_id", None)
                team_id = str(tid) if tid is not None else "null"
                if getattr(user, "type", "") == "admin":
                    is_admin = "true"
        except Exception:
            pass

        js = "window.CTF_CONTROLLER = {{ team_id: {}, is_admin: {} }};".format(
            team_id, is_admin
        )
        resp = make_response(js)
        resp.headers["Content-Type"] = "application/javascript"
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

    # ── Proxy routes ──────────────────────────────────────────────────────────

    def _get_controller_config():
        from CTFd.models import Configs
        url_cfg = Configs.query.filter_by(key="CONTROLLER_URL").first()
        key_cfg = Configs.query.filter_by(key="X_CONTROLLER_KEY").first()
        return (
            url_cfg.value if url_cfg else "http://controller-api.ctfd.svc.cluster.local",
            key_cfg.value if key_cfg else "",
        )

    def _proxy(method, path, data=None):
        base_url, api_key = _get_controller_config()
        url = base_url.rstrip("/") + path
        headers = {"X-Controller-Key": api_key, "Content-Type": "application/json"}
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            return Response(resp.read(), status=resp.status, content_type="application/json")
        except urllib.error.HTTPError as e:
            return Response(e.read(), status=e.code, content_type="application/json")
        except Exception as e:
            return jsonify({"error": str(e)}), 502

    def _check_authed():
        try:
            from CTFd.utils.decorators import authed
            return authed()
        except Exception:
            return False

    def _check_admin():
        try:
            from CTFd.utils.user import get_current_user
            user = get_current_user()
            return user and getattr(user, "type", "") == "admin"
        except Exception:
            return False

    @blueprint.route("/controller-proxy/status/<team_id>")
    def proxy_status(team_id):
        if not _check_authed():
            return jsonify({"error": "unauthorized"}), 401
        return _proxy("GET", "/status/" + team_id)

    @blueprint.route("/controller-proxy/activate", methods=["POST"])
    def proxy_activate():
        if not _check_authed():
            return jsonify({"error": "unauthorized"}), 401
        data = flask_request.get_json(silent=True) or {}
        return _proxy("POST", "/activate", data)

    @blueprint.route("/controller-proxy/deactivate", methods=["POST"])
    def proxy_deactivate():
        if not _check_authed():
            return jsonify({"error": "unauthorized"}), 401
        data = flask_request.get_json(silent=True) or {}
        return _proxy("POST", "/deactivate", data)

    # ── Per-team static challenge download ───────────────────────────────────

    @blueprint.route("/download/<challenge_manifest_id>")
    def download_static(challenge_manifest_id):
        """
        Serve a per-team zip for static/file-download challenges.

        Fetches the pre-generated zip from the static-files-server:
          1. /{challenge_id}/{team_id}.zip  — per-team artifact (flag baked in)
          2. /{challenge_id}/default.zip    — fallback for hardcoded-flag challenges

        Auth: requires logged-in user with a team.
        """
        import re
        import urllib.request as _ureq
        from CTFd.utils.user import get_current_user, get_current_team

        if not re.match(r'^[a-z0-9-]+$', challenge_manifest_id):
            return jsonify({"error": "invalid challenge id"}), 400

        user = get_current_user()
        if not user:
            return jsonify({"error": "unauthorized"}), 401

        team = get_current_team()
        if not team:
            return jsonify({"error": "no team"}), 403

        STATIC_FILES_URL = os.environ.get(
            "STATIC_FILES_URL",
            "http://static-files.ctfd.svc.cluster.local",
        )

        # Try per-team zip first, fall back to default.zip
        candidates = [
            f"{STATIC_FILES_URL}/{challenge_manifest_id}/{team.id}.zip",
            f"{STATIC_FILES_URL}/{challenge_manifest_id}/default.zip",
        ]

        zip_data = None
        for url in candidates:
            try:
                with _ureq.urlopen(url, timeout=10) as resp:
                    if resp.status == 200:
                        zip_data = resp.read()
                        break
            except Exception:
                continue

        if not zip_data:
            return jsonify({"error": "challenge files not available"}), 404

        buf = io.BytesIO(zip_data)
        buf.seek(0)
        return send_file(
            buf,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{challenge_manifest_id}.zip",
        )

    # ── Challenge isolation: nginx auth_request endpoint ─────────────────────

    @blueprint.route("/team-verify")
    def team_verify():
        """
        Called server-side by nginx auth_request before routing to a challenge pod.
        Verifies the logged-in team owns the requested challenge instance.

        nginx passes the original $host via ?host=<value>.
        Host format: team-<id>-<challenge>.challenges.infodays.net

        Returns 200 (allow), 401 (not logged in → redirect to login), 403 (wrong team).
        """
        from CTFd.utils.user import get_current_user, get_current_team

        user = get_current_user()
        if not user:
            return "", 401

        # Admins can access any challenge instance
        if getattr(user, "type", "") == "admin":
            return "", 200

        host = flask_request.args.get("host", "")
        subdomain = host.split(".")[0]        # "team-1-web-sqli"
        parts = subdomain.split("-")          # ["team", "1", "web", "sqli"]

        if len(parts) < 2 or parts[0] != "team":
            return "", 403

        try:
            challenge_team_id = int(parts[1])
        except ValueError:
            return "", 403

        team = get_current_team()
        if not team:
            return "", 401

        if team.id == challenge_team_id:
            return "", 200
        return "", 403

    # ── Cheaters admin endpoint ───────────────────────────────────────────────

    @blueprint.route("/admin/cheaters")
    def admin_cheaters():
        if not _check_admin():
            return jsonify({"error": "admin only"}), 403
        try:
            from CTFd.models import db, Teams
            from sqlalchemy import text
            rows = db.session.execute(
                text("""
                    SELECT
                        c.id,
                        st.name  AS submitting_team,
                        c.submitting_team_id,
                        su.name  AS submitting_user,
                        c.submitting_user_id,
                        c.submitted_flag,
                        ot.name  AS owner_team,
                        c.owner_team_id,
                        c.challenge_manifest_id,
                        c.submitted_at
                    FROM cheaters c
                    LEFT JOIN teams st ON st.id = c.submitting_team_id
                    LEFT JOIN users su ON su.id = c.submitting_user_id
                    LEFT JOIN teams ot ON ot.id = c.owner_team_id
                    ORDER BY c.submitted_at DESC
                """)
            ).fetchall()
            return jsonify([
                {
                    "id":                    r.id,
                    "submitting_team":        r.submitting_team,
                    "submitting_team_id":     r.submitting_team_id,
                    "submitting_user":        r.submitting_user,
                    "submitting_user_id":     r.submitting_user_id,
                    "submitted_flag":         r.submitted_flag,
                    "owner_team":             r.owner_team,
                    "owner_team_id":          r.owner_team_id,
                    "challenge":              r.challenge_manifest_id,
                    "submitted_at":           str(r.submitted_at),
                }
                for r in rows
            ])
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    app.register_blueprint(blueprint)

    # ── Register custom 'team' flag type ─────────────────────────────────────
    from CTFd.plugins.flags import FLAG_CLASSES
    FLAG_CLASSES["team"] = CTFdTeamFlag

    # ── Register scripts ──────────────────────────────────────────────────────
    register_script("/controller-plugin/config.js")
    register_script("/plugins/controller-plugin/assets/plugin.js")

    # ── Initialize DB ─────────────────────────────────────────────────────────
    with app.app_context():
        from CTFd.models import Configs, db
        from sqlalchemy import text

        # Create cheaters table if it doesn't exist.
        # Wrapped in try/except because ProxySQL may route DDL to the read
        # replica, which rejects writes.  The table is created by whichever
        # pod reaches the primary first; subsequent pods can safely skip.
        try:
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS cheaters (
                    id                    INT AUTO_INCREMENT PRIMARY KEY,
                    submitting_team_id    INT         NOT NULL,
                    submitting_user_id    INT             NULL,
                    submitted_flag        TEXT        NOT NULL,
                    owner_team_id         INT         NOT NULL,
                    challenge_manifest_id VARCHAR(255) NOT NULL,
                    submitted_at          DATETIME    NOT NULL,
                    INDEX idx_submitting (submitting_team_id),
                    INDEX idx_user       (submitting_user_id),
                    INDEX idx_owner      (owner_team_id)
                )
            """))
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.warning("cheaters table CREATE skipped (likely read-replica routing) — table should already exist")

        if not Configs.query.filter_by(key="CONTROLLER_URL").first():
            db.session.add(
                Configs(key="CONTROLLER_URL", value="http://controller-api.ctfd.svc.cluster.local")
            )
            db.session.commit()

        if not Configs.query.filter_by(key="X_CONTROLLER_KEY").first():
            app.logger.error(
                "X_CONTROLLER_KEY not found in database — "
                "run setup-ctfd.sh or set it manually in /admin/config before the event"
            )
