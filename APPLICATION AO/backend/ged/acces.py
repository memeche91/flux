"""Accès des intervenants par code (sans compte) : génération, vérification, session, limitation.

Le code (12 caractères parmi 31, environ 59 bits) n'est jamais conservé en clair : seule son
empreinte HMAC-SHA256 (clé secrète de l'application) l'est. Il est affiché une seule fois ;
le régénérer révoque l'ancien et ferme les sessions ouvertes avec lui.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from ninja.security.apikey import APIKeyCookie

from .models import Intervenant, StatutEspace

ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # sans 0/O, 1/I/L
LONGUEUR = 12
CLE_SESSION = "ged_intervenant"
CLE_SESSION_CODE = "ged_code"
DUREE_SESSION = 8 * 60 * 60
ECHECS_MAX = 10
FENETRE_ECHECS = 15 * 60


def generer_code() -> str:
    brut = "".join(secrets.choice(ALPHABET) for _ in range(LONGUEUR))
    return "-".join(brut[i:i + 4] for i in range(0, LONGUEUR, 4))


def normaliser_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def empreinte(code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), normaliser_code(code).encode(), hashlib.sha256).hexdigest()


def attribuer_code(intervenant: Intervenant) -> str:
    """Nouveau code (l'ancien ne fonctionne plus). Renvoie le code en clair, à remettre une seule fois."""
    code = generer_code()
    intervenant.code_empreinte = empreinte(code)
    intervenant.code_fin = normaliser_code(code)[-4:]
    intervenant.code_genere_le = timezone.now()
    intervenant.save(update_fields=["code_empreinte", "code_fin", "code_genere_le"])
    return code


def intervenant_par_code(code: str) -> Intervenant | None:
    if len(normaliser_code(code)) != LONGUEUR:
        return None
    return (
        Intervenant.objects.select_related("espace__projet")
        .filter(code_empreinte=empreinte(code), actif=True, espace__statut=StatutEspace.OUVERT)
        .first()
    )


def adresse_ip(request) -> str:
    transmis = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (transmis.split(",")[0].strip() if transmis else "") or request.META.get("REMOTE_ADDR", "inconnue")


def _cle_echecs(ip: str) -> str:
    return f"ged:echecs:{hashlib.sha256(ip.encode()).hexdigest()[:24]}"


def trop_de_tentatives(request) -> bool:
    return (cache.get(_cle_echecs(adresse_ip(request))) or 0) >= ECHECS_MAX


def noter_echec(request) -> None:
    cle = _cle_echecs(adresse_ip(request))
    cache.add(cle, 0, FENETRE_ECHECS)
    try:
        cache.incr(cle)
    except ValueError:
        cache.set(cle, 1, FENETRE_ECHECS)


def ouvrir_session(request, intervenant: Intervenant) -> None:
    request.session.cycle_key()  # pas de fixation de session
    request.session[CLE_SESSION] = intervenant.pk
    request.session[CLE_SESSION_CODE] = intervenant.code_empreinte[:16]
    request.session.set_expiry(DUREE_SESSION)
    Intervenant.objects.filter(pk=intervenant.pk).update(dernier_acces=timezone.now())


def fermer_session(request) -> None:
    for cle in (CLE_SESSION, CLE_SESSION_CODE):
        request.session.pop(cle, None)


class SessionIntervenant(APIKeyCookie):
    """Session ouverte avec un code d'accès : intervenant actif, code inchangé, espace ouvert."""

    param_name: str = settings.SESSION_COOKIE_NAME

    def authenticate(self, request, key):
        identifiant = request.session.get(CLE_SESSION)
        if not identifiant:
            return None
        intervenant = (
            Intervenant.objects.select_related("espace__projet", "entreprise")
            .filter(pk=identifiant, actif=True, espace__statut=StatutEspace.OUVERT)
            .first()
        )
        if intervenant is None or not intervenant.code_empreinte or intervenant.code_empreinte[:16] != request.session.get(CLE_SESSION_CODE):
            return None
        return intervenant


session_intervenant = SessionIntervenant()
