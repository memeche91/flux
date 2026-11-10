"""Portail des intervenants (entreprises, MOE associée, maître d'ouvrage, CT, CSPS, OPC) : accès
par code, sans compte.

Ces routes sont les seules ouvertes sur l'adresse publique de la GED. Elles n'utilisent jamais
l'authentification du cabinet : un intervenant ne voit que ce que ses droits permettent.
"""
from __future__ import annotations

import datetime
from typing import Literal

from ninja import Field, File, Form, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja.utils import check_csrf

from django.middleware.csrf import get_token

from . import vues
from .acces import CLE_SESSION, acces_par_code, adresse_ip, fermer_session, ip_bloquee, navigateur, noter_echec, ouvrir_session, session_intervenant
from .droits import acteur_acces
from .models import Frequence, TypeEvenement
from .serialisation import droits_out, lot_court, referentiels
from .services import journaliser

class Routes:
    """Routes enregistrées une fois, montées sur deux API : celle du cabinet (réseau local) et celle
    du processus public de la GED (adresse Internet), qui ne sert que ces routes."""

    def __init__(self):
        self.liste = []

    def _ajouter(self, methode):
        def decorateur_chemin(chemin, **options):
            def decorateur(vue):
                self.liste.append((methode, chemin, options, vue))
                return vue
            return decorateur
        return decorateur_chemin

    def __getattr__(self, methode):
        if methode in ("get", "post", "patch", "delete", "put"):
            return self._ajouter(methode)
        raise AttributeError(methode)


routes = Routes()


def construire_router() -> Router:
    router = Router(tags=["GED – portail des intervenants"], auth=session_intervenant)
    for methode, chemin, options, vue in routes.liste:
        getattr(router, methode)(chemin, **options)(vue)
    return router


class CodeAcces(Schema):
    code: str = Field(..., max_length=40)
    memoriser: bool = False


class Preferences(Schema):
    frequence: Frequence


def _acteur(request):
    """Personne connectée (son accès personnel) et sa société."""
    return acteur_acces(request.auth, adresse_ip(request), navigateur(request))


def _espace(request):
    return request.auth.intervenant.espace


def _espace_out(acces, acteur) -> dict:
    intervenant = acces.intervenant
    espace = intervenant.espace
    projet = espace.projet
    return {
        "projet": {"nom": projet.nom, "maitre_ouvrage": projet.maitre_ouvrage, "maitre_oeuvre": projet.maitre_oeuvre, "adresse_operation": projet.adresse_operation},
        "intervenant": {"nom": intervenant.nom, "profil": intervenant.profil, "profil_libelle": intervenant.get_profil_display(), "lots": [lot_court(l) for l in intervenant.lots.all()]},
        "personne": {"nom": acces.nom, "email": acces.email, "frequence": acces.frequence},
        "statut_espace": espace.statut, "statut_libelle": espace.get_statut_display(),
        "message_accueil": espace.message_accueil,
        "delai_visa_jours": espace.delai_visa_jours,
        "droits": droits_out(acteur, espace),
        "frequences": [{"code": f.value, "libelle": f.label} for f in Frequence],
        **referentiels(),
    }


@routes.get("/ged/portail/csrf", auth=None)
def jeton_csrf(request):
    """Jeton CSRF du portail (le cookie peut porter un autre nom sur l'adresse publique)."""
    return {"csrftoken": get_token(request)}


@routes.post("/ged/acces", auth=None)
def acces(request, donnees: CodeAcces):
    if check_csrf(request) is not None:
        raise HttpError(403, "Session expirée : rechargez la page puis saisissez de nouveau votre code.")
    acces_trouve, message = acces_par_code(donnees.code)
    if acces_trouve is None:
        noter_echec(request)
        if ip_bloquee(request):
            raise HttpError(429, "Trop de codes erronés depuis votre connexion : réessayez dans un quart d'heure.")
        raise HttpError(401, message)
    ouvrir_session(request, acces_trouve, donnees.memoriser)
    acteur = acteur_acces(acces_trouve, adresse_ip(request), navigateur(request))
    journaliser(acces_trouve.intervenant.espace, TypeEvenement.CONNEXION, f"Connexion de {acteur.nom}", acteur)
    return _espace_out(acces_trouve, acteur)


@routes.post("/ged/portail/deconnexion", auth=None, response={204: None})
def deconnexion(request):
    # Sans session ouverte, rien à fermer : réponse immédiate, sans lire le corps de la requête
    # (le contrôle CSRF lirait tout un envoi multipart).
    if request.session.get(CLE_SESSION) and check_csrf(request) is not None:
        raise HttpError(403, "Session expirée.")
    fermer_session(request)
    return 204, None


@routes.patch("/ged/portail/preferences")
def preferences(request, donnees: Preferences):
    acces_courant = request.auth
    acces_courant.frequence = donnees.frequence
    acces_courant.save(update_fields=["frequence"])
    return _espace_out(acces_courant, _acteur(request))


@routes.get("/ged/portail/espace")
def espace(request):
    return _espace_out(request.auth, _acteur(request))


@routes.get("/ged/portail/documents")
def documents(request):
    return vues.lister(_espace(request), _acteur(request))


@routes.post("/ged/portail/documents", response={201: dict})
def deposer(
    request, fichier: File[UploadedFile], zone: Form[str], categorie: Form[str], lot_id: Form[int | None] = None,
    titre: Form[str] = "", reference: Form[str] = "", reference_emetteur: Form[str] = "", indice: Form[str] = "", objet: Form[str] = "",
    diffusion: Form[str] = "", date_indice: Form[datetime.date | None] = None, depot: Form[str] = "",
    sources: File[list[UploadedFile]] = None,
):
    return 201, vues.deposer_formulaire(_acteur(request), _espace(request), fichier, zone=zone, lot_id=lot_id, categorie=categorie,
                                        titre=titre, reference=reference, reference_emetteur=reference_emetteur, indice=indice, objet=objet,
                                        diffusion=diffusion, date_indice=date_indice, sources=sources, depot=depot)


@routes.post("/ged/portail/documents/{document_id}/versions", response={201: dict})
def ajouter_indice(request, document_id: int, fichier: File[UploadedFile], indice: Form[str] = "", objet: Form[str] = "",
                   diffusion: Form[str] = "", date_indice: Form[datetime.date | None] = None, depot: Form[str] = "",
                   sources: File[list[UploadedFile]] = None, forcer: Form[str] = ""):
    return 201, vues.nouvel_indice_formulaire(_acteur(request), _espace(request), document_id, fichier, indice=indice, objet=objet,
                                              diffusion=diffusion, date_indice=date_indice, sources=sources, depot=depot)


@routes.post("/ged/portail/versions/{version_id}/avis")
def donner_avis(request, version_id: int, avis: Form[str], observations: Form[str] = "", fichier: File[UploadedFile | None] = None):
    return vues.avis_formulaire(_acteur(request), _espace(request), version_id, avis=avis, observations=observations, fichier=fichier)


@routes.post("/ged/portail/versions/{version_id}/lecture")
def accuser_lecture(request, version_id: int):
    return vues.accuser_lecture_vue(_acteur(request), _espace(request), version_id)


@routes.get("/ged/portail/versions/{version_id}/{quoi}")
def fichier(request, version_id: int, quoi: Literal["fichier", "annote", "fiche"]):
    return vues.telecharger(_acteur(request), _espace(request), version_id, quoi=quoi)


@routes.get("/ged/portail/sources/{source_id}")
def fichier_source(request, source_id: int):
    return vues.telecharger_source(_acteur(request), _espace(request), source_id)


@routes.get("/ged/portail/avis/{avis_id}/fichier")
def fichier_avis(request, avis_id: int):
    return vues.telecharger_avis(_acteur(request), _espace(request), avis_id)


@routes.get("/ged/portail/journal")
def journal(request, page: int = 1):
    return vues.journal(_espace(request), _acteur(request), page)


@routes.get("/ged/portail/registre.xlsx")
def registre(request):
    return vues.registre_xlsx(_espace(request), _acteur(request))



router = construire_router()
