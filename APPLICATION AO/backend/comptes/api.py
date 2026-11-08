from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.utils import check_csrf

router = Router(tags=["Authentification"])


class ConnexionIn(Schema):
    identifiant: str
    mot_de_passe: str


class UtilisateurOut(Schema):
    id: int
    identifiant: str
    nom_complet: str
    role: str
    role_libelle: str
    est_administrateur: bool

    @staticmethod
    def resolve_identifiant(obj):
        return obj.username

    @staticmethod
    def resolve_nom_complet(obj):
        return obj.get_full_name() or obj.username

    @staticmethod
    def resolve_role(obj):
        return "ADMIN" if obj.est_administrateur else obj.role

    @staticmethod
    def resolve_role_libelle(obj):
        return "Administrateur" if obj.est_administrateur else obj.get_role_display()


class CsrfOut(Schema):
    csrftoken: str


@router.get("/csrf", auth=None, response=CsrfOut)
def jeton_csrf(request):
    """Dépose le cookie CSRF nécessaire aux requêtes POST/PATCH/DELETE."""
    return {"csrftoken": get_token(request)}


@router.post("/connexion", auth=None, response=UtilisateurOut)
def connexion(request, donnees: ConnexionIn):
    # La connexion est publique mais reste protégée contre les requêtes forgées.
    if check_csrf(request) is not None:
        raise HttpError(403, "Session expirée : rechargez la page puis reconnectez-vous.")
    utilisateur = authenticate(
        request, username=donnees.identifiant.strip(), password=donnees.mot_de_passe
    )
    if utilisateur is None:
        raise HttpError(401, "Identifiant ou mot de passe incorrect.")
    if not utilisateur.acces_bureau_etudes:
        raise HttpError(403, "Ce compte n'a pas accès à l'espace du cabinet.")
    login(request, utilisateur)
    return utilisateur


@router.post("/deconnexion", response={204: None})
def deconnexion(request):
    logout(request)
    return 204, None


@router.get("/moi", response=UtilisateurOut)
def moi(request):
    return request.auth
