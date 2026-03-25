"""
CTFd Controller Plugin - manages team challenge instances.

Provides UI for starting/stopping challenge pods and displays their status.
Injects config globals via after_request; plugin.js hooks into CTFd's challenge events.
"""

from flask import Blueprint, request as flask_request
from flask_login import current_user


def load(app):
    """Load the CTFd plugin."""
    # Register Flask blueprint for static asset serving
    blueprint = Blueprint(
        "controller_plugin",
        __name__,
        static_folder="assets",
        static_url_path="/plugins/controller-plugin/assets",
    )
    app.register_blueprint(blueprint)

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

    @app.after_request
    def inject_controller_script(response):
        """Inject controller config and plugin script into every HTML page."""
        if not response.content_type.startswith("text/html"):
            return response

        # Skip API and static routes
        if flask_request.path.startswith(("/api/", "/themes/", "/plugins/")):
            return response

        # Read config from DB (cached by SQLAlchemy session)
        try:
            from CTFd.models import Configs

            url_config = Configs.query.filter_by(key="CONTROLLER_URL").first()
            key_config = Configs.query.filter_by(key="X_CONTROLLER_KEY").first()
            controller_url = url_config.value if url_config else ""
            controller_key = key_config.value if key_config else ""
        except Exception:
            return response

        # Get team_id from current user (0/null if not logged in or no team)
        team_id = "null"
        try:
            if current_user.is_authenticated:
                tid = getattr(current_user, "team_id", None)
                team_id = str(tid) if tid is not None else "null"
        except Exception:
            pass

        config_snippet = f"""
<script>
window.CTF_CONTROLLER = {{
  "team_id": {team_id},
  "url": "{controller_url}",
  "key": "{controller_key}"
}};
</script>
<script src="/plugins/controller-plugin/assets/plugin.js"></script>
"""
        html = response.get_data(as_text=True)
        if "</body>" in html:
            response.set_data(html.replace("</body>", config_snippet + "\n</body>", 1))

        return response
