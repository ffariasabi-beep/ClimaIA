
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session, current_app
)
from flask_login import login_user, logout_user, current_user
from email_validator import validate_email, EmailNotValidError
from sqlalchemy import or_, func
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Message

from app.extensions import db, oauth, mail
from app.models import User, PendingRegistration


auth_bp = Blueprint("auth", __name__)


def _safe_next_url(target):
    if not target:
        return None

    host_url = urlparse(request.host_url)
    redirect_url = urlparse(urljoin(request.host_url, target))

    if (
        redirect_url.scheme in ("http", "https")
        and host_url.netloc == redirect_url.netloc
    ):
        return target

    return None


def _google_client():
    return oauth.create_client("google")


def _send_verification_email(email, code):
    message = Message(
        subject="Verificación de tu cuenta - ClimaIA",
        recipients=[email],
        body=(
            f"Tu código de verificación de ClimaIA es: {code}\n\n"
            "Este código vence en 10 minutos.\n"
            "Si no solicitaste este registro, ignorá este correo."
        )
    )
    mail.send(message)


# --------------------------------------------------
# REGISTRO TRADICIONAL
# --------------------------------------------------

@auth_bp.route("/register", methods=["GET", "POST"])
def register():

    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
            flash(
                "El usuario debe tener entre 3 y 30 caracteres. "
                "Usá letras, números o guion bajo.",
                "error"
            )
            return render_template("register.html")

        try:
            validate_email(email, check_deliverability=False)
        except EmailNotValidError:
            flash("Ingresá un correo electrónico válido.", "error")
            return render_template("register.html")

        if len(password) < 12:
            flash("La contraseña debe tener al menos 12 caracteres.", "error")
            return render_template("register.html")

        if password != confirm_password:
            flash("Las contraseñas no coinciden.", "error")
            return render_template("register.html")

        existing_user = User.query.filter(
            or_(
                func.lower(User.username) == username.lower(),
                func.lower(User.email) == email
            )
        ).first()

        if existing_user:
            flash("Ese usuario o correo ya está registrado.", "error")
            return render_template("register.html")

        # Eliminar un registro pendiente anterior para ese correo.
        old_pending = PendingRegistration.query.filter_by(
            email=email
        ).first()

        if old_pending:
            db.session.delete(old_pending)
            db.session.commit()

        code = f"{secrets.randbelow(1000000):06d}"

        pending = PendingRegistration(
            username=username,
            email=email,
            phone=phone or None,
            password_hash=generate_password_hash(password),
            verification_code_hash=generate_password_hash(code),
            expires_at=(
                datetime.now(timezone.utc) + timedelta(minutes=10)
            ).replace(tzinfo=None)
        )

        try:
            db.session.add(pending)
            db.session.commit()

            _send_verification_email(email, code)

            session["pending_email"] = email

            flash(
                "Te enviamos un código de verificación a tu correo.",
                "success"
            )

            return redirect(url_for("auth.verify_email"))

        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                "Error al iniciar el registro o enviar el código."
            )
            flash(
                "No se pudo enviar el código. Revisá la configuración "
                "del correo e intentá nuevamente.",
                "error"
            )

    return render_template("register.html")


# --------------------------------------------------
# VERIFICACIÓN DEL CORREO
# --------------------------------------------------

@auth_bp.route("/verify-email", methods=["GET", "POST"])
def verify_email():

    email = session.get("pending_email")

    if not email:
        flash("No hay ningún registro pendiente de verificación.", "error")
        return redirect(url_for("auth.register"))

    pending = PendingRegistration.query.filter_by(
        email=email
    ).first()

    if not pending:
        session.pop("pending_email", None)
        flash("El registro pendiente ya no existe.", "error")
        return redirect(url_for("auth.register"))

    if request.method == "POST":

        code = request.form.get("code", "").strip()

        if not re.fullmatch(r"\d{6}", code):
            flash("Ingresá un código válido de seis dígitos.", "error")
            return render_template("verify_email.html")

        if not check_password_hash(
            pending.verification_code_hash,
            code
        ):
            flash("El código ingresado es incorrecto.", "error")
            return render_template("verify_email.html")

        if datetime.now(timezone.utc).replace(tzinfo=None) > pending.expires_at:
            db.session.delete(pending)
            db.session.commit()
            session.pop("pending_email", None)

            flash(
                "El código venció. Volvé a registrarte para recibir otro.",
                "error"
            )
            return redirect(url_for("auth.register"))

        existing = User.query.filter(
            or_(
                func.lower(User.username) == pending.username.lower(),
                func.lower(User.email) == pending.email.lower()
            )
        ).first()

        if existing:
            flash(
                "Ese usuario o correo ya está registrado.",
                "error"
            )
            return redirect(url_for("auth.register"))

        user = User(
            username=pending.username,
            email=pending.email,
            phone=pending.phone,
            role="researcher",
            email_verified=True
        )

        user.password_hash = pending.password_hash

        try:
            db.session.add(user)
            db.session.delete(pending)
            db.session.commit()

            session.pop("pending_email", None)

            login_user(user)

            flash("Tu cuenta fue verificada y creada correctamente.", "success")
            return redirect(url_for("main.dashboard"))

        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                "Error al finalizar el registro."
            )
            flash("No se pudo finalizar el registro.", "error")

    return render_template("verify_email.html")


# --------------------------------------------------
# INICIO DE SESIÓN TRADICIONAL
# --------------------------------------------------

@auth_bp.route("/login", methods=["GET", "POST"])
def login():

    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":

        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter(
            or_(
                func.lower(User.username) == identifier.lower(),
                func.lower(User.email) == identifier.lower()
            )
        ).first()

        if user and user.is_active and user.check_password(password):
            if not user.email_verified:
                flash("Primero tenés que verificar tu correo.", "error")
                return redirect(url_for("auth.login"))

            login_user(user)

            flash("Sesión iniciada correctamente.", "success")

            destination = _safe_next_url(
                request.args.get("next")
            )

            return redirect(
                destination or url_for("main.dashboard")
            )

        flash("Usuario, correo o contraseña incorrectos.", "error")

    return render_template("login.html")


# --------------------------------------------------
# INICIO DE SESIÓN CON GOOGLE
# --------------------------------------------------

@auth_bp.route("/google")
def google_login():

    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    google = _google_client()

    if not google:
        flash("El acceso con Google no está configurado.", "error")
        return redirect(url_for("auth.login"))

    redirect_uri = url_for(
        "auth.google_callback",
        _external=True
    )

    return google.authorize_redirect(redirect_uri)


@auth_bp.route("/google/callback")
def google_callback():

    try:
        google = _google_client()

        token = google.authorize_access_token()

        user_info = token.get("userinfo")

        if not user_info:
            user_info = google.userinfo()

        google_id = user_info.get("sub")
        email = (user_info.get("email") or "").strip().lower()
        email_verified = user_info.get("email_verified", False)

        if not google_id or not email or email_verified is not True:
            flash(
                "Google no pudo verificar tu identidad y correo.",
                "error"
            )
            return redirect(url_for("auth.login"))

        # Buscar primero por identificador de Google.
        user = User.query.filter_by(
            google_id=google_id
        ).first()

        if user:
            if not user.is_active:
                flash("Esta cuenta está desactivada.", "error")
                return redirect(url_for("auth.login"))

            login_user(user)
            flash("Sesión iniciada con Google.", "success")
            return redirect(url_for("main.dashboard"))

        # Si el correo ya existe, vincular la cuenta.
        user = User.query.filter(
            func.lower(User.email) == email
        ).first()

        if user:

            if not user.is_active:
                flash("Esta cuenta está desactivada.", "error")
                return redirect(url_for("auth.login"))

            if user.google_id and user.google_id != google_id:
                flash(
                    "Este correo ya está vinculado a otra cuenta de Google.",
                    "error"
                )
                return redirect(url_for("auth.login"))

            user.google_id = google_id
            user.email_verified = True

            db.session.commit()
            login_user(user)

            flash("Tu cuenta fue vinculada con Google.", "success")
            return redirect(url_for("main.dashboard"))

        # Cuenta nueva: solicitar nombre de usuario y teléfono.
        session["google_pending"] = {
            "google_id": google_id,
            "email": email
        }

        return redirect(url_for("auth.google_complete"))

    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error durante el acceso con Google.")
        flash("No se pudo iniciar sesión con Google.", "error")
        return redirect(url_for("auth.login"))


# --------------------------------------------------
# COMPLETAR PERFIL DE GOOGLE
# --------------------------------------------------

@auth_bp.route("/google/complete", methods=["GET", "POST"])
def google_complete():

    google_data = session.get("google_pending")

    if not google_data:
        flash("No hay una autenticación de Google pendiente.", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        phone = request.form.get("phone", "").strip()

        if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
            flash(
                "El usuario debe tener entre 3 y 30 caracteres.",
                "error"
            )
            return render_template("complete_google_profile.html")

        existing_username = User.query.filter(
            func.lower(User.username) == username.lower()
        ).first()

        if existing_username:
            flash("Ese nombre de usuario ya está ocupado.", "error")
            return render_template("complete_google_profile.html")

        # Comprobar nuevamente que el correo no haya sido registrado.
        existing_email = User.query.filter(
            func.lower(User.email) == google_data["email"]
        ).first()

        if existing_email:
            flash("Ese correo ya tiene una cuenta.", "error")
            return redirect(url_for("auth.login"))

        user = User(
            username=username,
            email=google_data["email"],
            phone=phone or None,
            google_id=google_data["google_id"],
            email_verified=True,
            role="researcher"
        )

        # Mantener password_hash obligatorio sin permitir
        # que esta contraseña aleatoria sea conocida por el usuario.
        user.set_password(secrets.token_urlsafe(48))

        try:
            db.session.add(user)
            db.session.commit()

            session.pop("google_pending", None)

            login_user(user)

            flash("Tu cuenta fue creada correctamente.", "success")
            return redirect(url_for("main.dashboard"))

        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                "Error al crear la cuenta de Google."
            )
            flash("No se pudo crear tu cuenta.", "error")

    return render_template("complete_google_profile.html")


# --------------------------------------------------
# CERRAR SESIÓN
# --------------------------------------------------

@auth_bp.route("/logout", methods=["POST"])
def logout():

    if current_user.is_authenticated:
        logout_user()
        flash("Cerraste tu sesión correctamente.", "success")

    return redirect(url_for("main.index"))
