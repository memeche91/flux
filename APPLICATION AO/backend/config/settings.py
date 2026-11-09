"""Paramètres Django d'Application AO.

Toute la configuration sensible passe par des variables d'environnement
(fichier .env lu par Docker Compose). Sans PostgreSQL configuré, l'application
bascule sur SQLite : pratique pour le développement et les tests.
"""
import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env(nom, defaut=None):
    return os.environ.get(nom, defaut)


def env_bool(nom, defaut=False):
    valeur = os.environ.get(nom)
    if valeur is None:
        return defaut
    return valeur.strip().lower() in {"1", "true", "oui", "yes", "on"}


def env_liste(nom, defaut=""):
    return [element.strip() for element in env(nom, defaut).split(",") if element.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = env("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-uniquement-cle-non-secrete"
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY est vide : lancez installer.ps1 (il génère le fichier .env) "
            "ou renseignez une longue clé aléatoire dans .env."
        )

ALLOWED_HOSTS = env_liste("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_liste(
    "DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080"
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "comptes",
    "referentiel",
    "bibliotheque.apps.BibliothequeConfig",
    "articles",
    "projets",
    "assistant",
    "entreprises",
    "dce",
    "offres",
    "ged",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

if env("POSTGRES_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", "application_ao"),
            "USER": env("POSTGRES_USER", "application_ao"),
            "PASSWORD": env("POSTGRES_PASSWORD", ""),
            "HOST": env("POSTGRES_HOST"),
            "PORT": env("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "dev.sqlite3",
        }
    }

AUTH_USER_MODEL = "comptes.Utilisateur"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Les fichiers importés ne sont jamais servis publiquement : ils passent par
# une vue qui vérifie les droits de l'utilisateur.
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Taille maximale d'un fichier importé, en mégaoctets.
TAILLE_MAX_FICHIER_MO = int(env("TAILLE_MAX_FICHIER_MO", "200"))

# Lecture des documents : conversion des anciens formats (LibreOffice) et OCR (Tesseract).
LIBREOFFICE_BIN = env("LIBREOFFICE_BIN", "soffice")
TESSERACT_BIN = env("TESSERACT_BIN", "tesseract")
OCR_LANGUE = env("OCR_LANGUE", "fra")
OCR_PAGES_MAX = int(env("OCR_PAGES_MAX", "300"))
CONVERSION_DELAI_MAX = int(env("CONVERSION_DELAI_MAX", "180"))

# Sécurité des cookies : HTTPS activable quand la GED sera exposée sur Internet.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = env_bool("COOKIES_HTTPS", False)
CSRF_COOKIE_SECURE = env_bool("COOKIES_HTTPS", False)
SESSION_COOKIE_AGE = 60 * 60 * 10  # une journée de travail
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"

# Celery : sans Redis, les tâches s'exécutent immédiatement (développement, tests).
CELERY_BROKER_URL = env("REDIS_URL") or "memory://"
CELERY_TASK_ALWAYS_EAGER = not env("REDIS_URL")
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_IGNORE_RESULT = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TIME_LIMIT = 60 * 60  # OCR d'un gros document scanné
CELERY_RESULT_BACKEND = env("REDIS_URL") or None
CELERY_RESULT_EXPIRES = 60 * 60
# La voix (Whisper, Piper) tourne dans un seul processus dédié (service « voix ») :
# les modèles ne sont chargés qu'une fois en mémoire.
# Tâches planifiées (service worker lancé avec --beat) : récapitulatif du matin de la GED.
from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    "ged-recapitulatif-quotidien": {"task": "ged.tasks.recapitulatif_quotidien", "schedule": crontab(hour=7, minute=0, day_of_week="1-5")},
    "ged-relance-notifications": {"task": "ged.tasks.relancer_notifications", "schedule": crontab(minute="*/15")},
    "ged-purges-programmees": {"task": "ged.archivage.purges_programmees", "schedule": crontab(hour=3, minute=15)},
}
CELERY_TASK_ROUTES = {
    "assistant.tasks.transcrire_audio": {"queue": "voix"},
    "assistant.tasks.synthetiser_texte": {"queue": "voix"},
}

# Courriels (envoi du DCE, puis notifications de la GED) : la messagerie du cabinet, en SMTP.
# Sans réglage, l'application prépare les messages et vous les envoyez vous-même.
EMAIL_HOST = (env("EMAIL_HOST") or "").strip()
EMAIL_PORT = int(env("EMAIL_PORT") or "587")
EMAIL_HOST_USER = (env("EMAIL_HOST_USER") or "").strip()
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD") or ""
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = 60
DEFAULT_FROM_EMAIL = (env("DEFAULT_FROM_EMAIL") or "").strip() or EMAIL_HOST_USER or "application-ao@localhost"
if env("EMAIL_BACKEND"):
    EMAIL_BACKEND = env("EMAIL_BACKEND")
    EMAIL_FILE_PATH = env("EMAIL_FILE_PATH", str(MEDIA_ROOT / "courriels"))
EMAIL_ACTIF = bool(EMAIL_HOST or env("EMAIL_BACKEND"))
EMAIL_PIECE_JOINTE_MAX_MO = int(env("EMAIL_PIECE_JOINTE_MAX_MO") or "20")

# Cache partagé entre les processus (limitation des tentatives de code d'accès à la GED).
if env("REDIS_URL"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": env("REDIS_URL").rsplit("/", 1)[0] + "/1"}}

# GED de chantier : adresses utilisées dans les courriels. URL_APPLICATION : adresse du cabinet
# (réseau local) ; GED_URL_PUBLIQUE : adresse Internet donnée aux entreprises (https://ged.cabinet.fr).
URL_APPLICATION = (env("URL_APPLICATION") or f"http://localhost:{env('APP_PORT', '8080')}").strip()
GED_URL_PUBLIQUE = (env("GED_URL_PUBLIQUE") or "").strip()
# Adresse IP des visiteurs fiable (transmise par Caddy depuis l'adresse publique, tunnel ou IP fixe
# vérifiée) : seulement alors une adresse peut être bloquée après des codes erronés.
GED_IP_FIABLE = env_bool("GED_IP_FIABLE", False)
# Espace disque à garder libre (Go) : un dépôt qui l'entamerait est refusé.
GED_DISQUE_LIBRE_MIN_GO = int(env("GED_DISQUE_LIBRE_MIN_GO") or "5")
TESTS = len(sys.argv) > 1 and sys.argv[1] == "test"
# Dossier des archives de fin de chantier (monté depuis le PC ou le serveur du cabinet).
DOSSIER_ARCHIVES = Path(env("DOSSIER_ARCHIVES", str(MEDIA_ROOT / "archives")))
# Emplacement du dossier d'archives tel que le cabinet le voit sur le PC (affichage seulement).
DOSSIER_ARCHIVES_AFFICHE = env("DOSSIER_ARCHIVES_AFFICHE", "donnees\\archives")
# Assistant IA local (administrateur) : Ollama pour le texte, Whisper et Piper pour la voix.
# Tout tourne sur le poste ou le serveur du cabinet ; seuls les modèles sont téléchargés.
OLLAMA_URL = env("OLLAMA_URL", "http://localhost:11434").rstrip("/")
IA_MODELE = env("IA_MODELE", "qwen3.5:9b")
IA_MODELE_EMBEDDING = env("IA_MODELE_EMBEDDING", "bge-m3")
IA_CONTEXTE = int(env("IA_CONTEXTE", "8192"))
IA_WHISPER = env("IA_WHISPER", "large-v3-turbo")
IA_VOIX = env("IA_VOIX", "fr_FR-siwis-medium")
IA_DOSSIER_MODELES = Path(env("IA_DOSSIER_MODELES", str(BASE_DIR / "modeles-ia")))
# Sans Redis (développement, tests), l'indexation bloquerait la requête : elle se lance à la main.
IA_INDEXATION_AUTO = env_bool("IA_INDEXATION_AUTO", not CELERY_TASK_ALWAYS_EAGER)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    # La mise en page des PDF est très bavarde : seuls les avertissements sont gardés.
    "loggers": {
        "weasyprint": {"level": "WARNING"},
        "fontTools": {"level": "WARNING"},
        # Échanges avec le moteur d'IA local : une ligne par requête, inutile au quotidien.
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
    },
}
