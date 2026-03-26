"""
CTFd Controller Plugin - manages team challenge instances.

Provides UI for starting/stopping challenge pods and displays their status.
Proxies browser requests to the cluster-internal controller API.
Uses CTFd's register_script() for reliable script injection.
"""

from flask import Blueprint, request as flask_request, jsonify, Response, make_response
import urllib.request
import urllib.error
import json


def load(app):
    """Load the CTFd plugin."""
    from CTFd.utils.plugins import register_script

    blueprint = Blueprint(
        "controller_plugin",
        __name__,
        static_folder="assets",
        static_url_path="/plugins/controller-plugin/assets",
    )

    # ── Dynamic config endpoint (serves per-user JS config) ──────────────────

    @blueprint.route("/controller-plugin/config.js")
    def controller_config_js():
        """Serve per-user CTF_CONTROLLER config as JavaScript."""
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

    # ── Proxy routes: browser → CTFd → controller-api (cluster-internal) ─────

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

    app.register_blueprint(blueprint)

    # ── Register scripts via CTFd's native mechanism ({{ Plugins.scripts }}) ──
    # config.js serves dynamic per-user config; plugin.js has the UI logic.
    register_script("/controller-plugin/config.js")
    register_script("/plugins/controller-plugin/assets/plugin.js")

    # Initialize default config values on first load
    with app.app_context():
        from CTFd.models import Configs, db

        if not Configs.query.filter_by(key="CONTROLLER_URL").first():
            db.session.add(
                Configs(key="CONTROLLER_URL", value="http://controller-api.ctfd.svc.cluster.local")
            )
            db.session.commit()

        if not Configs.query.filter_by(key="X_CONTROLLER_KEY").first():
            db.session.add(Configs(key="X_CONTROLLER_KEY", value="CHANGE_ME"))
            db.session.commit()
