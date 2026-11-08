"""Authentification de l'API : session Django + jeton CSRF, réservée au cabinet."""
from ninja.security import SessionAuth


class SessionBureauEtudes(SessionAuth):
    """Accepte uniquement les comptes Administrateur et Maîtrise d'œuvre.

    Les comptes Entreprise n'ont pas accès aux outils internes ; ils
    utiliseront l'espace GED (étape 4).
    """

    def authenticate(self, request, key):
        utilisateur = super().authenticate(request, key)
        if utilisateur is not None and getattr(utilisateur, "acces_bureau_etudes", False):
            return utilisateur
        return None


session_bureau_etudes = SessionBureauEtudes()
