import os
from flask import Flask, render_template
from config import config_by_name
from routes import chat_bp, main_bp, repository_bp


def create_app(config_name=None):
    """
    Application factory pattern for CodeLens AI.
    Configures and creates the Flask application instance.
    """
    if config_name is None:
        config_name = os.getenv("FLASK_ENV", "development")

    app = Flask(__name__)
    config_obj = config_by_name.get(config_name, config_by_name["default"])
    app.config.from_object(config_obj)

    # Register Route Blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(repository_bp)
    app.register_blueprint(chat_bp)

    # Error Handlers
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("base.html", error_message="404 - Page Not Found"), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template("base.html", error_message="500 - Internal Server Error"), 500

    return app


app = create_app()

if __name__ == "__main__":
    host = app.config.get("HOST", "127.0.0.1")
    port = app.config.get("PORT", 5000)
    debug = app.config.get("DEBUG", True)

    print("==================================================")
    print(" CodeLens AI - Phase 1 Foundation Server")
    print(f" URL: http://{host}:{port}/")
    print(f" Debug mode: {'Enabled' if debug else 'Disabled'}")
    print("==================================================")

    app.run(host=host, port=port, debug=debug)
