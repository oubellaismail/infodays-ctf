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


def _parse_flag_data(raw):
    """
    Parse a Flags.data value.

    Regular team-flag rows store a plain string (the manifest id):
        data = "web-sqli"  →  ("web-sqli", 0, "web-sqli")

    Lab sub-flag rows store JSON with sub_id / points / deployment_id:
        data = '{"sub_id": "mancity-user", "points": 100, "deployment_id": "lab-mancity"}'
               → ("mancity-user", 100, "lab-mancity")

    Returns (sub_id, points, deployment_id). Falls back to the raw string on parse failure.
    """
    if not raw:
        return "", 0, ""
    if isinstance(raw, str) and raw.lstrip().startswith("{"):
        try:
            obj = json.loads(raw)
            return (
                obj.get("sub_id", "") or "",
                int(obj.get("points", 0) or 0),
                obj.get("deployment_id", "") or "",
            )
        except Exception:
            pass
    return raw, 0, raw


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

        # Parse flag data — supports both plain-string (regular challenges)
        # and JSON (lab sub-flags). Only the sub_id is needed for HMAC.
        sub_id, _points, _dep = _parse_flag_data(chal_key_obj.data or "")
        master_secret = os.environ.get("CTF_MASTER_SECRET", "")
        if not master_secret or not sub_id:
            return False

        # ── Check submitting team's own flag ──────────────────────────────────
        expected = _derive(team.id, sub_id, master_secret)
        if _hmac.compare_digest(expected, provided):
            return True

        # ── Wrong flag — check if it belongs to another team (cheating) ───────
        try:
            from CTFd.models import Teams
            all_teams = Teams.query.filter(Teams.id != team.id).all()
            for other in all_teams:
                candidate = _derive(other.id, sub_id, master_secret)
                if _hmac.compare_digest(candidate, provided):
                    _log_cheater(team.id, user_id, provided, other.id, sub_id)
                    break
        except Exception:
            pass  # Never crash flag validation due to cheating detection

        return False


# ── Lab challenge type (HTB-style, per-flag point accumulation) ──────────────
#
# One CTFd challenge card → N flag rows (each with JSON-encoded sub_id + points).
# Submitting any correct sub-flag awards its points via the native CTFd Award
# model, which adds directly to the team's score. The challenge is only
# marked "Solved" (Solves row) once every sub-flag has been captured.
#
# lab_solves table: (team_id, sub_id) — idempotency, prevents double-awarding
# on a re-submission of the same flag. Also drives the per-team progress UI.

def _lab_progress_rows(team_id):
    """Return set of captured sub_ids for a given team. Safe against DB failures."""
    try:
        from CTFd.models import db
        from sqlalchemy import text
        rows = db.session.execute(
            text("SELECT sub_id FROM lab_solves WHERE team_id = :tid"),
            {"tid": team_id},
        ).fetchall()
        return {r.sub_id for r in rows}
    except Exception:
        return set()


def _lab_insert_solve(team_id, user_id, challenge_id, sub_id, points):
    """
    Insert an idempotent lab_solves row.

    Returns True only when THIS call actually inserted a new row — False if
    the UNIQUE (team_id, sub_id) constraint already had a matching row. This
    prevents concurrent submissions from both awarding points: the second
    INSERT IGNORE silently no-ops and we return False, skipping the Award.
    """
    from CTFd.models import db
    from sqlalchemy import text
    try:
        result = db.session.execute(
            text("""
                INSERT IGNORE INTO lab_solves
                    (team_id, user_id, challenge_id, sub_id, points, solved_at)
                VALUES
                    (:tid, :uid, :cid, :sid, :pts, :ts)
            """),
            {
                "tid": team_id,
                "uid": user_id,
                "cid": challenge_id,
                "sid": sub_id,
                "pts": int(points),
                "ts": datetime.utcnow(),
            },
        )
        db.session.commit()
        # MySQL returns rowcount=1 for inserted, 0 for ignored duplicate.
        return (result.rowcount or 0) > 0
    except Exception:
        db.session.rollback()
        return False


def _build_lab_challenge_class():
    """
    Factory: build the LabChallenge class at plugin load time so we can import
    CTFd modules safely inside app context.
    """
    from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge
    from CTFd.models import db, Challenges, Flags, Solves, Awards
    from CTFd.utils.user import get_current_team, get_current_user
    from flask import g as flask_g

    def _get_ip(request):
        return request.headers.get("X-Forwarded-For", request.remote_addr or "")

    class LabChallenge(BaseChallenge):
        """
        HTB-style lab challenge: one CTFd card, multiple flags, accumulating points.

        attempt() iterates all team-flag rows for the challenge and checks each
        against the submission. On a match, solve() records the capture and
        awards the sub-flag's points via the Awards table. The standard Solves
        row is only written once every sub-flag has been captured.
        """
        id = "lab"
        name = "lab"
        # Reuse CTFd's built-in standard challenge admin templates. Labs are
        # created via the /api/v1/challenges endpoint in deploy-challenge.sh,
        # not via the admin UI, so these are fallbacks for editing only.
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
        challenge_model = Challenges

        @classmethod
        def read(cls, challenge):
            """
            Return the challenge dict rendered in the modal.

            Adds two lab-specific fields:
              - lab: true
              - lab_flags: [{sub_id, points, captured}] for the current team
              - lab_total_points: sum of sub-flag points
              - lab_earned_points: sum already awarded to the current team
            """
            # Compute lab totals up front so we can expose them as the card's
            # displayed `value`. The DB keeps challenge.value=0 so Solves
            # rows contribute 0 — all scoring flows through per-sub-flag
            # Awards. Overriding `value` here is purely a display shim.
            entries = []
            total = 0
            earned = 0
            try:
                team = get_current_team()
                captured = _lab_progress_rows(team.id) if team else set()
                flags = Flags.query.filter_by(challenge_id=challenge.id, type="team").all()
                for f in flags:
                    sub_id, pts, _dep = _parse_flag_data(f.data or "")
                    if not sub_id:
                        continue
                    is_cap = sub_id in captured
                    entries.append({
                        "sub_id":   sub_id,
                        "points":   pts,
                        "captured": is_cap,
                    })
                    total += pts
                    if is_cap:
                        earned += pts
            except Exception:
                pass

            data = {
                "id":          challenge.id,
                "name":        challenge.name,
                # Display the total across all sub-flags on the card.
                # DB value stays 0 for scoring correctness — see deploy-challenge.sh.
                "value":       total if total > 0 else challenge.value,
                "description": challenge.description,
                "category":    challenge.category,
                "state":       challenge.state,
                "max_attempts": challenge.max_attempts,
                "type":        challenge.type,
                "type_data":   {
                    "id":        cls.id,
                    "name":      cls.name,
                    "templates": cls.templates,
                    "scripts":   cls.scripts,
                },
                "lab":                True,
                "lab_flags":          entries,
                "lab_total_points":   total,
                "lab_earned_points":  earned,
            }
            return data

        @classmethod
        def attempt(cls, challenge, request):
            """
            Check the submission against every team-flag row for this challenge.

            Return values match BaseChallenge contract: (bool, str). On True,
            CTFd core calls solve() and records a "correct" Submission. On a
            repeat capture we return False to avoid inflating the Solves count
            and to display a clear "already captured" message to the player.
            """
            data = request.form or request.get_json() or {}
            submission = (data.get("submission") or "").strip()
            if not submission:
                return False, "Missing flag"

            team = get_current_team()
            if team is None:
                return False, "Must be on a team"

            user = get_current_user()
            user_id = user.id if user else None

            master_secret = os.environ.get("CTF_MASTER_SECRET", "")
            if not master_secret:
                return False, "Challenge unavailable"

            flags = Flags.query.filter_by(challenge_id=challenge.id, type="team").all()
            already_captured = _lab_progress_rows(team.id)

            matched_sub_id = None
            matched_points = 0

            for f in flags:
                sub_id, pts, _dep = _parse_flag_data(f.data or "")
                if not sub_id:
                    continue
                expected = _derive(team.id, sub_id, master_secret)
                if _hmac.compare_digest(expected, submission):
                    matched_sub_id = sub_id
                    matched_points = pts
                    break

            if matched_sub_id is None:
                # Cheater check — did the submission match another team's sub-flag?
                try:
                    from CTFd.models import Teams
                    others = Teams.query.filter(Teams.id != team.id).all()
                    for f in flags:
                        sub_id, _pts, _dep = _parse_flag_data(f.data or "")
                        if not sub_id:
                            continue
                        for other in others:
                            candidate = _derive(other.id, sub_id, master_secret)
                            if _hmac.compare_digest(candidate, submission):
                                _log_cheater(team.id, user_id, submission, other.id, sub_id)
                                return False, "Incorrect"
                except Exception:
                    pass
                return False, "Incorrect"

            if matched_sub_id in already_captured:
                # Returning False avoids double-awarding points and keeps the
                # Submissions table free of spurious "correct" rows.
                return False, "You've already captured this flag"

            # Stash the match on flask.g so solve() can read it without
            # redoing the HMAC loop. flask.g is request-scoped and safe.
            flask_g._lab_match = {
                "sub_id": matched_sub_id,
                "points": matched_points,
                "total_flags": len(flags),
            }
            return True, f"Flag captured — +{matched_points} points"

        @classmethod
        def solve(cls, user, team, challenge, request):
            """
            Called by CTFd core after attempt() returns True. Records:
              - lab_solves row (idempotent) — drives progress UI
              - Award row — adds points to team score immediately
              - Solves row — only when every sub-flag is now captured (marks card "Solved")
              - Submission row — standard "correct" record for activity feed
            """
            match = getattr(flask_g, "_lab_match", None) or {}
            sub_id = match.get("sub_id", "")
            points = int(match.get("points", 0))
            total_flags = int(match.get("total_flags", 0))

            if not sub_id:
                return

            submission = (
                (request.form or request.get_json() or {}).get("submission") or ""
            )

            inserted = _lab_insert_solve(
                team_id=team.id,
                user_id=user.id if user else None,
                challenge_id=challenge.id,
                sub_id=sub_id,
                points=points,
            )
            if not inserted:
                return

            try:
                # 1. Award the sub-flag's points — directly added to team score.
                award = Awards(
                    user_id=user.id if user else None,
                    team_id=team.id,
                    name=f"{challenge.name}: {sub_id}",
                    description=f"Lab sub-flag: {sub_id}",
                    value=points,
                    category=challenge.category,
                )
                db.session.add(award)

                # 2. On the final capture, insert a native Solves row so the
                #    challenge card flips to "Solved" and the team appears on
                #    the challenge's solver list. challenge.value is set to 0
                #    by deploy-challenge.sh for labs, so Solves adds no extra
                #    points — all scoring flows through Awards.
                captured_now = _lab_progress_rows(team.id)
                if total_flags > 0 and len(captured_now) >= total_flags:
                    existing = Solves.query.filter_by(
                        team_id=team.id, challenge_id=challenge.id
                    ).first()
                    if not existing:
                        final_solve = Solves(
                            user_id=user.id if user else None,
                            team_id=team.id,
                            challenge_id=challenge.id,
                            ip=_get_ip(request),
                            provided=submission,
                        )
                        db.session.add(final_solve)

                db.session.commit()
            except Exception:
                db.session.rollback()

    CHALLENGE_CLASSES["lab"] = LabChallenge
    return LabChallenge


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

    # ── Lab progress endpoint (per-team, per-challenge) ──────────────────────

    @blueprint.route("/controller-plugin/lab-progress/<int:challenge_id>")
    def lab_progress(challenge_id):
        """
        Return lab progress for the current team on a given CTFd challenge.

        Response:
          {
            "total_flags": 4, "total_points": 700,
            "captured_flags": 2, "earned_points": 300,
            "flags": [ {"sub_id": "...", "points": 100, "captured": true}, ... ]
          }

        Used by plugin.js to render the progress panel inside the challenge modal
        and the total/earned pts badge on the board card.
        """
        if not _check_authed():
            return jsonify({"error": "unauthorized"}), 401

        try:
            from CTFd.models import Challenges, Flags
            from CTFd.utils.user import get_current_team

            challenge = Challenges.query.filter_by(id=challenge_id).first()
            if not challenge or challenge.type != "lab":
                return jsonify({"error": "not a lab challenge"}), 404

            team = get_current_team()
            if not team:
                return jsonify({"error": "no team"}), 403

            captured = _lab_progress_rows(team.id)
            flags = Flags.query.filter_by(challenge_id=challenge_id, type="team").all()

            entries = []
            total_points = 0
            earned_points = 0
            captured_flags = 0
            for f in flags:
                sub_id, pts, _dep = _parse_flag_data(f.data or "")
                if not sub_id:
                    continue
                is_cap = sub_id in captured
                entries.append({"sub_id": sub_id, "points": pts, "captured": is_cap})
                total_points += pts
                if is_cap:
                    earned_points += pts
                    captured_flags += 1

            return jsonify({
                "challenge_id":    challenge_id,
                "total_flags":     len(entries),
                "captured_flags":  captured_flags,
                "total_points":    total_points,
                "earned_points":   earned_points,
                "flags":           entries,
            })
        except Exception as e:
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

    # ── Register custom 'team' flag type ─────────────────────────────────────
    from CTFd.plugins.flags import FLAG_CLASSES
    FLAG_CLASSES["team"] = CTFdTeamFlag

    # ── Register custom 'lab' challenge type (HTB-style accumulating points) ─
    _build_lab_challenge_class()

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

        # lab_solves: per-team, per-sub-flag idempotency + progress UI source
        try:
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS lab_solves (
                    id           INT AUTO_INCREMENT PRIMARY KEY,
                    team_id      INT          NOT NULL,
                    user_id      INT              NULL,
                    challenge_id INT          NOT NULL,
                    sub_id       VARCHAR(255) NOT NULL,
                    points       INT          NOT NULL DEFAULT 0,
                    solved_at    DATETIME     NOT NULL,
                    UNIQUE KEY uq_team_sub (team_id, sub_id),
                    INDEX idx_team      (team_id),
                    INDEX idx_challenge (challenge_id)
                )
            """))
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.warning("lab_solves table CREATE skipped (likely read-replica routing) — table should already exist")

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
