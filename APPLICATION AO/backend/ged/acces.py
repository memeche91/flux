"""Accès personnels par code (sans compte) : code, session, adresse IP, essais erronés.

- Le code (12 caractères parmi 31, environ 59 bits) est tiré au hasard et affiché une seule fois ;
  la base n'en garde que l'empreinte HMAC-SHA256 (clé secrète de l'application).
- Un nouveau code (invitation renvoyée, fuite, départ d'un salarié) révoque l'ancien et ferme les
  sessions ouvertes avec lui ; les collègues, qui ont leur propre code, ne sont pas touchés.
- La session dure 8 heures (30 jours si la personne fait mémoriser l'appareil), durée absolue,
  et elle est revérifiée à chaque requête : accès et intervenant actifs, code inchangé, espace actif.
- Un code juste est toujours accepté. Les essais erronés sont comptés (jamais d'attente dans la
  requête, qui occuperait un fil du serveur) et, au-delà d'un seuil, la maîtrise d'œuvre est
  alertée ; une adresse IP n'est bloquée que si elle est fiable (transmise par Caddy depuis
  l'adresse publique).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from ninja.security.apikey import APIKeyCookie

from .models import Acces, StatutEspace

logger = logging.getLogger("ged.acces")
ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # sans 0/O, 1/I/L
LONGUEUR = 12
CLE_SESSION = "ged_acces"
CLE_SESSION_CODE = "ged_code"
DUREE_SESSION = 8 * 60 * 60
DUREE_MEMORISEE = 30 * 24 * 60 * 60
ECHECS_PAR_IP = 10
FENETRE = 15 * 60
SEUIL_ALERTE = 50  # essais erronés par heure, toutes adresses confondues
MESSAGE_REFUS = "Code inconnu ou plus valide, ou espace du chantier clos : vérifiez la saisie ou demandez votre code à la maîtrise d'œuvre."
ESPACES_ACTIFS = [StatutEspace.OUVERT, StatutEspace.RECEPTION]


def generer_code() -> str:
    brut = "".join(secrets.choice(ALPHABET) for _ in range(LONGUEUR))
    return "-".join(brut[i:i + 4] for i in range(0, LONGUEUR, 4))


def normaliser_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def empreinte(code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"ged:{normaliser_code(code)}".encode(), hashlib.sha256).hexdigest()


def nouveau_code(acces: Acces) -> str:
    """Attribue un nouveau code (sans enregistrer) et le renvoie en clair, à remettre une seule fois."""
    code = generer_code()
    acces.code_empreinte = empreinte(code)
    acces.code_fin = normaliser_code(code)[-4:]
    acces.code_genere_le = timezone.now()
    return code


def acces_par_code(code: str) -> tuple[Acces | None, str]:
    """(accès, message d'erreur) ; un seul message pour un code inconnu, révoqué ou un espace clos."""
    if len(normaliser_code(code)) != LONGUEUR:
        return None, "Code d'accès incomplet : il compte 12 caractères (par exemple K7QM-2XPA-9RTD)."
    acces = (
        Acces.objects.select_related("intervenant__espace__projet")
        .filter(code_empreinte=empreinte(code), actif=True, intervenant__actif=True, intervenant__espace__statut__in=ESPACES_ACTIFS)
        .first()
    )
    return (acces, "") if acces is not None else (None, MESSAGE_REFUS)


# --- Adresse IP et essais erronés ---------------------------------------------------------------

def adresse_ip(request) -> str:
    """Adresse transmise par Caddy (X-Ip-Client, fiable sur l'adresse publique), sinon celle du relais."""
    return (request.META.get("HTTP_X_IP_CLIENT") or request.META.get("REMOTE_ADDR") or "").strip()[:45]


def navigateur(request) -> str:
    return (request.META.get("HTTP_USER_AGENT") or "")[:300]


def _cle(ip: str) -> str:
    return f"ged:echecs:{hashlib.sha256(ip.encode()).hexdigest()[:24]}"


def _incrementer(cle: str, duree: int) -> int:
    cache.add(cle, 0, duree)
    try:
        return cache.incr(cle)
    except ValueError:
        cache.set(cle, 1, duree)
        return 1


def ip_bloquee(request) -> bool:
    ip = request.META.get("HTTP_X_IP_CLIENT")
    if not ip or not settings.GED_IP_FIABLE:
        return False  # adresse non fiable (relais Docker, tunnel) : jamais de blocage commun à tous
    return (cache.get(_cle(ip)) or 0) >= ECHECS_PAR_IP


def noter_echec(request) -> None:
    ip = adresse_ip(request)
    logger.warning("Code GED erroné depuis %s (%s)", ip, navigateur(request))
    _incrementer(_cle(ip), FENETRE)
    total = _incrementer("ged:echecs:total", 3600)
    if total >= SEUIL_ALERTE and cache.add("ged:alerte-envoyee", 1, 3600):
        from .tasks import alerter_essais

        alerter_essais.delay(total, settings.GED_IP_FIABLE)  # le worker ne connaît pas GED_IP_FIABLE


# --- Session --------------------------------------------------------------------------------------

def ouvrir_session(request, acces: Acces, memoriser: bool = False) -> None:
    # Session repartie de zéro : jamais mélangée avec une session du cabinet.
    request.session.flush()
    request.session[CLE_SESSION] = acces.pk
    request.session[CLE_SESSION_CODE] = acces.code_empreinte[:16]
    request.session.set_expiry(DUREE_MEMORISEE if memoriser else DUREE_SESSION)
    Acces.objects.filter(pk=acces.pk).update(dernier_acces=timezone.now())


def fermer_session(request) -> None:
    request.session.flush()


class SessionIntervenant(APIKeyCookie):
    """Session ouverte avec un code : accès et intervenant actifs, code inchangé, espace actif."""

    param_name: str = settings.SESSION_COOKIE_NAME

    def authenticate(self, request, key):
        identifiant = request.session.get(CLE_SESSION)
        if not identifiant:
            return None
        acces = (
            Acces.objects.select_related("intervenant__espace__projet", "intervenant__entreprise")
            .filter(pk=identifiant, actif=True, intervenant__actif=True, intervenant__espace__statut__in=ESPACES_ACTIFS)
            .first()
        )
        if acces is None or acces.code_empreinte[:16] != request.session.get(CLE_SESSION_CODE):
            return None
        return acces


session_intervenant = SessionIntervenant()
