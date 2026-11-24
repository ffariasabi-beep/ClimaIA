import os
from pathlib import Path
from dotenv import dotenv_values, load_dotenv

DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(DOTENV_PATH)
DOTENV_VALUES = dotenv_values(DOTENV_PATH)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "clave-solo-para-desarrollo")

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///climaia_dev.db"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
    }

    OPEN_METEO_ARCHIVE_URL = os.getenv(
        "OPEN_METEO_ARCHIVE_URL",
        "https://archive-api.open-meteo.com/v1/archive"
    )

    OPEN_METEO_GEOCODING_URL = os.getenv(
        "OPEN_METEO_GEOCODING_URL",
        "https://geocoding-api.open-meteo.com/v1/search"
    )

    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    GROQ_MODEL = os.getenv(
        "GROQ_MODEL",
        "qwen/qwen3.8-27b"
    )
    CLOUDFLARE_API_TOKEN = (
        os.getenv("CLOUDFLARE_API_TOKEN")
        or DOTENV_VALUES.get("CLOUDFLARE_API_TOKEN")
    )
    CLOUDFLARE_ACCOUNT_ID = (
        os.getenv("CLOUDFLARE_ACCOUNT_ID")
        or DOTENV_VALUES.get("CLOUDFLARE_ACCOUNT_ID")
    )
    CLOUDFLARE_AI_MODEL = os.getenv(
        "CLOUDFLARE_AI_MODEL",
        "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    )
    BIGDATACLOUD_API_KEY = os.getenv("BIGDATACLOUD_API_KEY")

    DEFAULT_CLIMATE_DATASET = os.getenv(
        "DEFAULT_CLIMATE_DATASET",
        "era5"
    )

    MAX_COMPARISON_RESULTS = int(
        os.getenv("MAX_COMPARISON_RESULTS", "20")
    )

    MAX_CONTENT_LENGTH = 10 * 1024 * 1024

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

        # Autenticación con Google
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

    # Verificación por correo electrónico
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_USERNAME")
    
    @staticmethod
    def validate_production():
        secret = os.getenv("SECRET_KEY", "")

        if not secret or secret == "clave-solo-para-desarrollo":
            raise RuntimeError(
                "Debés configurar una SECRET_KEY segura en producción."
            )