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
import threading
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


# ── Multi-flag challenge type ─────────────────────────────────────────────────

# Thread-local used to signal partial-progress returns in attempt() so that
# fail() can suppress the Fails-table insert for those cases.
_mf_tls = threading.local()


def _register_multi_flag_model():
    """Register a SQLAlchemy polymorphic subclass for multi_flag challenges.

    CTFd's Challenges model uses type as a polymorphic discriminator.
    Without a registered subclass, SQLAlchemy emits a warning when loading
    challenges with type='multi_flag' and may not refresh them correctly.
    This creates a minimal mapped subclass that satisfies the ORM.
    """
    try:
        from CTFd.models import Challenges, db
        # Check if already registered to avoid duplicate mapper error on hot-reload
        if "multi_flag" not in Challenges.__mapper__.polymorphic_map:
            class MultiFlagChallengeModel(Challenges):
                __mapper_args__ = {"polymorphic_identity": "multi_flag"}
            # Keep reference so the class isn't GC'd
            _register_multi_flag_model._model = MultiFlagChallengeModel
    except Exception:
        pass  # Non-fatal — challenge still works via raw SQL


class MultiFlagChallenge:
    """
    Custom CTFd challenge type for challenges with multiple independent flags.

    Each flag (component) has its own scoring params (initial/minimum/decay).
    Points are awarded incrementally via CTFd Awards as each component is found.
    A Solves row is only inserted when ALL components are found.

    Component data is stored in two plugin-managed tables:
        multi_flag_components  — per-challenge component definitions
        multi_flag_solves      — per-team per-component solve records
    """

    id = "multi_flag"
    name = "multi_flag"
    templates = {
        "create": "/plugins/challenges/assets/create.html",
        "update": "/plugins/challenges/assets/update.html",
        "view":   "/plugins/challenges/assets/view.html",
    }
    scripts = {
        "create": "/plugins/challenges/assets/create.js",
        "update": "/plugins/challenges/assets/update.js",
        "view":   "/plugins/challenges/assets/view.js",
    }

    @classmethod
    def attempt(cls, challenge, request):
        from CTFd.utils.user import get_current_user, get_current_team
        from CTFd.models import Awards, db
        from sqlalchemy import text

        provided = (request.json or {}).get("submission", "").strip()
        team = get_current_team()
        user = get_current_user()
        if not team or not user:
            return (False, "No team")

        master_secret = os.environ.get("CTF_MASTER_SECRET", "")
        if not master_secret:
            return (False, "Server configuration error")

        # Load all components for this challenge
        components = db.session.execute(
            text("SELECT component_id, env_var, initial, minimum, decay, "
                 "COALESCE(static_flag, '') "
                 "FROM multi_flag_components WHERE challenge_id = :cid "
                 "ORDER BY component_id"),
            {"cid": challenge.id}
        ).fetchall()

        if not components:
            return (False, "Challenge not configured — contact admin")

        # Load this team's already-found components
        solved_set = {row[0] for row in db.session.execute(
            text("SELECT component_id FROM multi_flag_solves "
                 "WHERE challenge_id = :cid AND team_id = :tid"),
            {"cid": challenge.id, "tid": team.id}
        ).fetchall()}

        total = len(components)

        for comp in components:
            comp_id, env_var, initial, minimum, decay, static_flag = comp
            if static_flag:
                # File-based challenge: validate against pre-generated exact flag
                if provided != static_flag:
                    continue
            else:
                # Service challenge: validate against HMAC-derived flag
                expected = _derive(team.id, comp_id, master_secret)
                if not _hmac.compare_digest(expected, provided):
                    continue

            # Matched this component
            if comp_id in solved_set:
                _mf_tls.is_progress = True
                return (False, "You already found this flag!")

            # How many teams have already found this component (for decay calculation)
            solve_count = db.session.execute(
                text("SELECT COUNT(*) FROM multi_flag_solves WHERE component_id = :cid"),
                {"cid": comp_id}
            ).scalar() or 0

            # Decayed score: linear from initial → minimum over decay solves
            pts = max(minimum, initial - (initial - minimum) * solve_count // max(decay, 1))

            # Record the solve
            db.session.execute(
                text("INSERT INTO multi_flag_solves "
                     "(challenge_id, team_id, component_id, awarded_at) "
                     "VALUES (:chid, :tid, :cmpid, NOW())"),
                {"chid": challenge.id, "tid": team.id, "cmpid": comp_id}
            )

            # Grant an Award for the component points
            db.session.add(Awards(
                user_id=user.id,
                team_id=team.id,
                name=f"{challenge.name} [{comp_id}]",
                description="multi_flag component",
                value=pts,
                category=challenge.category,
                icon="flag",
            ))
            db.session.commit()

            new_solved_count = len(solved_set) + 1
            if new_solved_count == total:
                # All flags found — solve() will be called to insert Solves row
                return (True, f"All {total} flags found! Challenge complete!")

            _mf_tls.is_progress = True
            return (False, f"Flag found! {new_solved_count}/{total} complete. +{pts} pts")

        # Cheating detection for HMAC-derived components (not static_flag)
        try:
            from CTFd.models import Teams
            all_teams = Teams.query.filter(Teams.id != team.id).all()
            for other in all_teams:
                hmac_components = db.session.execute(
                    text("SELECT component_id FROM multi_flag_components "
                         "WHERE challenge_id = :cid "
                         "AND (static_flag IS NULL OR static_flag = '')"),
                    {"cid": challenge.id}
                ).fetchall()
                for (cmp_id,) in hmac_components:
                    candidate = _derive(other.id, cmp_id, master_secret)
                    if _hmac.compare_digest(candidate, provided):
                        user_obj = get_current_user()
                        _log_cheater(team.id, user_obj.id if user_obj else None,
                                     provided, other.id, cmp_id)
                        break
        except Exception:
            pass

        return (False, "Incorrect")

    @classmethod
    def solve(cls, user, team, challenge, request):
        """Insert a Solves row with value=0 (marks challenge fully complete)."""
        from CTFd.models import Solves, db
        solve = Solves(
            user_id=user.id,
            team_id=team.id if team else None,
            challenge_id=challenge.id,
            ip=request.remote_addr,
            provided=(request.json or {}).get("submission", ""),
        )
        db.session.add(solve)
        db.session.commit()

    @classmethod
    def fail(cls, user, team, challenge, request):
        """Suppress Fails-table insertion for partial-progress responses."""
        if getattr(_mf_tls, "is_progress", False):
            _mf_tls.is_progress = False
            return
        # True wrong guess — call base implementation
        try:
            from CTFd.plugins.challenges import BaseChallenge
            BaseChallenge.fail(user, team, challenge, request)
        except Exception:
            pass

    @classmethod
    def read(cls, challenge):
        """Serialize challenge for API responses."""
        data = {
            "id": challenge.id,
            "name": challenge.name,
            "value": challenge.value,
            "description": challenge.description,
            "category": challenge.category,
            "state": challenge.state,
            "max_attempts": challenge.max_attempts,
            "type": challenge.type,
            "type_data": {
                "id": cls.id,
                "name": cls.name,
                "templates": cls.templates,
                "scripts": cls.scripts,
            },
        }
        return data

    @classmethod
    def update(cls, challenge, request):
        data = request.form or request.get_json()
        for attr in ("name", "description", "value", "category", "state", "max_attempts"):
            if attr in data:
                setattr(challenge, attr, data[attr])
        from CTFd.models import db
        db.session.commit()
        return challenge

    @classmethod
    def delete(cls, challenge):
        from CTFd.models import db
        from sqlalchemy import text
        db.session.execute(
            text("DELETE FROM multi_flag_components WHERE challenge_id = :cid"),
            {"cid": challenge.id}
        )
        db.session.execute(
            text("DELETE FROM multi_flag_solves WHERE challenge_id = :cid"),
            {"cid": challenge.id}
        )
        db.session.delete(challenge)
        db.session.commit()

    @classmethod
    def create(cls, request):
        from CTFd.models import Challenges, db
        data = request.form or request.get_json()
        challenge = Challenges(
            name=data["name"],
            description=data.get("description", ""),
            value=int(data.get("value", data.get("initial", 500))),
            category=data.get("category", ""),
            state=data.get("state", "visible"),
            max_attempts=data.get("max_attempts", 0),
            type="multi_flag",
        )
        db.session.add(challenge)
        db.session.commit()
        return challenge


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

        Fetches {challenge_id}/{team_id}.zip from the static-files-server.
        Files contain the challenge artifacts with flags already baked in by
        generate-static-artifacts.py — no flag injection happens here.

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

        # Serve per-team zip: {challenge_id}/{team_id}.zip
        files_url = f"{STATIC_FILES_URL}/{challenge_manifest_id}/{team.id}.zip"
        try:
            with _ureq.urlopen(files_url, timeout=10) as resp:
                if resp.status != 200:
                    return jsonify({"error": "challenge files not available"}), 404
                zip_data = resp.read()
        except Exception:
            return jsonify({"error": "challenge files not available"}), 404

        return send_file(
            io.BytesIO(zip_data),
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

    # ── Multi-flag progress endpoint ──────────────────────────────────────────

    @blueprint.route("/api/plugin/multi-flag-progress/<int:challenge_id>")
    def multi_flag_progress(challenge_id):
        """
        Returns per-team progress for a multi_flag challenge.
        Any authenticated user can query their own progress.
        """
        if not _check_authed():
            return jsonify({"error": "unauthorized"}), 401

        try:
            from CTFd.utils.user import get_current_team
            from CTFd.models import db
            from sqlalchemy import text

            team = get_current_team()
            team_id = team.id if team else None

            components = db.session.execute(
                text("SELECT component_id, initial, minimum, decay "
                     "FROM multi_flag_components WHERE challenge_id = :cid "
                     "ORDER BY component_id"),
                {"cid": challenge_id}
            ).fetchall()

            total = len(components)
            found_ids = set()
            points_earned = 0

            if team_id:
                rows = db.session.execute(
                    text("SELECT component_id FROM multi_flag_solves "
                         "WHERE challenge_id = :cid AND team_id = :tid"),
                    {"cid": challenge_id, "tid": team_id}
                ).fetchall()
                found_ids = {r[0] for r in rows}

                # Sum points earned across all found components for this team
                if found_ids and components:
                    parent_prefix = components[0][0].rsplit("-", 1)[0]
                    award_total = db.session.execute(
                        text("SELECT COALESCE(SUM(value),0) FROM awards "
                             "WHERE team_id = :tid AND description = 'multi_flag component' "
                             "AND name LIKE :pattern"),
                        {"tid": team_id, "pattern": f"% [{parent_prefix}-%]"}
                    ).scalar() or 0
                    points_earned = int(award_total)

            return jsonify({
                "total": total,
                "found": len(found_ids),
                "complete": len(found_ids) == total and total > 0,
                "points_earned": points_earned,
                "components": [
                    {"component_id": row[0], "found": row[0] in found_ids}
                    for row in components
                ],
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── Multi-flag component registration endpoint ─────────────────────────────

    @blueprint.route("/api/plugin/multi-flag-register", methods=["POST"])
    def multi_flag_register():
        """
        Register component scoring params for a multi_flag challenge.
        Called by import_flags.py after challenge creation.
        Auth: CTFd admin API token in Authorization header.
        Body: {challenge_id: int, components: [{component_id, env_var, initial, minimum, decay, flag?}]}
        """
        # Validate admin token
        auth = flask_request.headers.get("Authorization", "")
        if not auth.startswith("Token "):
            return jsonify({"error": "unauthorized"}), 401
        token_value = auth[6:].strip()

        try:
            from CTFd.models import db, Tokens, Users
            tok = Tokens.query.filter_by(value=token_value).first()
            if not tok:
                return jsonify({"error": "invalid token"}), 401
            user = Users.query.get(tok.user_id)
            if not user or user.type != "admin":
                return jsonify({"error": "admin only"}), 403
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        body = flask_request.get_json(silent=True) or {}
        challenge_id = body.get("challenge_id")
        components = body.get("components", [])

        if not challenge_id or not components:
            return jsonify({"error": "challenge_id and components required"}), 400

        try:
            from CTFd.models import db
            from sqlalchemy import text

            upserted = 0
            for comp in components:
                static_flag = comp.get("flag") or comp.get("static_flag") or None
                db.session.execute(
                    text("""
                        INSERT INTO multi_flag_components
                            (challenge_id, component_id, env_var, initial, minimum, decay,
                             static_flag)
                        VALUES
                            (:cid, :comp_id, :env, :initial, :minimum, :decay, :sflag)
                        ON DUPLICATE KEY UPDATE
                            env_var     = VALUES(env_var),
                            initial     = VALUES(initial),
                            minimum     = VALUES(minimum),
                            decay       = VALUES(decay),
                            static_flag = VALUES(static_flag)
                    """),
                    {
                        "cid":     challenge_id,
                        "comp_id": comp["component_id"],
                        "env":     comp.get("env_var", ""),
                        "initial": int(comp.get("initial", 500)),
                        "minimum": int(comp.get("minimum", 50)),
                        "decay":   int(comp.get("decay", 25)),
                        "sflag":   static_flag,
                    }
                )
                upserted += 1
            db.session.commit()
            return jsonify({"message": f"Registered {upserted} components for challenge {challenge_id}"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

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

    # ── Register custom flag + challenge types ────────────────────────────────
    from CTFd.plugins.flags import FLAG_CLASSES
    FLAG_CLASSES["team"] = CTFdTeamFlag

    from CTFd.plugins.challenges import CHALLENGE_CLASSES
    CHALLENGE_CLASSES["multi_flag"] = MultiFlagChallenge
    _register_multi_flag_model()

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
                CREATE TABLE IF NOT EXISTS multi_flag_components (
                    id           INT AUTO_INCREMENT PRIMARY KEY,
                    challenge_id INT          NOT NULL,
                    component_id VARCHAR(255) NOT NULL,
                    env_var      VARCHAR(50)  NOT NULL DEFAULT '',
                    initial      INT          NOT NULL DEFAULT 500,
                    minimum      INT          NOT NULL DEFAULT 50,
                    decay        INT          NOT NULL DEFAULT 25,
                    static_flag  VARCHAR(255) DEFAULT NULL,
                    UNIQUE KEY uq_cc (challenge_id, component_id)
                )
            """))
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.warning("multi_flag_components table CREATE skipped (likely read-replica routing)")

        # Add static_flag column to existing deployments that pre-date this column.
        try:
            db.session.execute(text(
                "ALTER TABLE multi_flag_components "
                "ADD COLUMN IF NOT EXISTS static_flag VARCHAR(255) DEFAULT NULL"
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()  # Column already exists or routing issue — safe to ignore

        try:
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS multi_flag_solves (
                    id           INT AUTO_INCREMENT PRIMARY KEY,
                    challenge_id INT          NOT NULL,
                    team_id      INT          NOT NULL,
                    component_id VARCHAR(255) NOT NULL,
                    awarded_at   DATETIME     NOT NULL,
                    UNIQUE KEY uq_tc (team_id, component_id),
                    INDEX idx_challenge_team (challenge_id, team_id)
                )
            """))
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.warning("multi_flag_solves table CREATE skipped (likely read-replica routing)")

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
