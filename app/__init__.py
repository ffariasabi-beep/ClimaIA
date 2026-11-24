
import os

from flask import Flask

from app.config import Config
from app.extensions import db, login_manager, migrate, csrf, oauth, mail


def create_app():

    app = Flask(__name__)
    app.config.from_object(Config)

    if os.getenv("FLASK_ENV") == "production":
        Config.validate_production()

        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["REMEMBER_COOKIE_SECURE"] = True

    # Inicializar extensiones
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # Nuevas extensiones de autenticación
    oauth.init_app(app)
    mail.init_app(app)

    # Registrar modelos
    from app import models
    # Configurar autenticación con Google
    if app.config.get("GOOGLE_CLIENT_ID") and app.config.get("GOOGLE_CLIENT_SECRET"):
        oauth.register(
            name="google",
            client_id=app.config["GOOGLE_CLIENT_ID"],
            client_secret=app.config["GOOGLE_CLIENT_SECRET"],
            server_metadata_url=(
                "https://accounts.google.com/.well-known/openid-configuration"
            ),
            client_kwargs={
                "scope": "openid email profile"
            }
        )
    # Registrar rutas
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.investigations import investigations_bp
    from app.routes.api import api_bp
    from app.routes.territory import territory_bp
    from app.routes.research_center import research_center_bp

    # Registrar Blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(investigations_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(territory_bp)
    app.register_blueprint(research_center_bp)

    return app
