"""Réglages du processus public de la GED (service « ged » en mode Internet).

Cookies sécurisés (HTTPS) au nom réservé à l'hôte, seul l'hôte public accepté, seules les routes
du portail montées. Le processus interne du cabinet garde ses réglages (HTTP sur le réseau local).
"""
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403
from .settings import GED_URL_PUBLIQUE

ROOT_URLCONF = "config.urls_ged"
_publique = urlsplit(GED_URL_PUBLIQUE)
if _publique.scheme != "https" or not _publique.hostname or _publique.path or _publique.query or _publique.fragment:
    raise ImproperlyConfigured("GED_URL_PUBLIQUE doit être une adresse https://nom sans chemin (par exemple https://ged.cabinet.fr).")
ALLOWED_HOSTS = [_publique.hostname]
CSRF_TRUSTED_ORIGINS = [f"https://{_publique.netloc}"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_NAME = "__Host-ged-session"
CSRF_COOKIE_NAME = "__Host-ged-csrf"
SECURE_CONTENT_TYPE_NOSNIFF = True

# Envoi (POST, PATCH…) sans session ouverte avec un code : refusé avant toute lecture du corps.
MIDDLEWARE = list(MIDDLEWARE)  # noqa: F405
MIDDLEWARE.insert(MIDDLEWARE.index("django.contrib.sessions.middleware.SessionMiddleware") + 1, "ged.protection.EnvoiSansSessionRefuse")
