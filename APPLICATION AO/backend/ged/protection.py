"""Processus public de la GED : aucun corps de requête lu sans session ouverte avec un code.

Django ne lit le corps d'une requête que lorsqu'une vue (ou le contrôle CSRF) le demande. Ce
middleware répond avant : un inconnu ne peut ni occuper un fil du serveur avec un envoi lent, ni
écrire un fichier temporaire de 1 Go dans le conteneur. Seules la saisie du code et la déconnexion
acceptent un corps sans session ; Caddy le limite à 16 Ko et le reçoit en entier avant de le
transmettre (Caddyfile, site public).
"""
from __future__ import annotations

from django.http import JsonResponse

from .acces import session_intervenant

METHODES_SANS_CORPS = frozenset({"GET", "HEAD", "OPTIONS"})
ROUTES_SANS_SESSION = frozenset({"/api/ged/acces", "/api/ged/portail/deconnexion"})


class EnvoiSansSessionRefuse:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.method not in METHODES_SANS_CORPS
            and request.path not in ROUTES_SANS_SESSION
            and session_intervenant.authenticate(request, None) is None
        ):
            # Même réponse que Django Ninja pour une session absente ou expirée.
            return JsonResponse({"detail": "Unauthorized"}, status=401)
        return self.get_response(request)
