
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from authlib.integrations.flask_client import OAuth
from flask_mail import Mail

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()

# Nuevas extensiones de autenticación
oauth = OAuth()
mail = Mail()

login_manager.login_view = "auth.login"
login_manager.login_message = "Iniciá sesión para continuar."
login_manager.login_message_category = "info"
