"""Portail des intervenants (entreprises, MOE associée, lecteurs) : accès par code, sans compte.

Ces routes sont les seules ouvertes sur l'adresse publique de la GED. Elles n'utilisent jamais
l'authentification du cabinet : un intervenant ne voit que ses documents.
"""
from __future__ import annotations

from ninja import Field, File, Form, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja.utils import check_csrf

from . import vues
from .acces import fermer_session, intervenant_par_code, noter_echec, ouvrir_session, session_intervenant, trop_de_tentatives
from .droits import acteur_intervenant
from .models import TypeEvenement
from .serialisation import droits_out, lot_court, referentiels
from .services import journaliser

router = Router(tags=["GED – portail des intervenants"], auth=session_intervenant)


class CodeAcces(Schema):
    code: str = Field(..., max_length=40)


def _espace_out(intervenant) -> dict:
    espace = intervenant.espace
    projet = espace.projet
    acteur = acteur_intervenant(intervenant)
    return {
        "projet": {"nom": projet.nom, "maitre_ouvrage": projet.maitre_ouvrage, "maitre_oeuvre": projet.maitre_oeuvre, "adresse_operation": projet.adresse_operation},
        "intervenant": {"nom": intervenant.nom, "profil": intervenant.profil, "profil_libelle": intervenant.get_profil_display(), "lots": [lot_court(l) for l in intervenant.lots.all()]},
        "message_accueil": espace.message_accueil,
        "delai_visa_jours": espace.delai_visa_jours,
        "droits": droits_out(acteur, espace),
        **referentiels(),
    }


@router.post("/ged/acces", auth=None)
def acces(request, donnees: CodeAcces):
    if check_csrf(request) is not None:
        raise HttpError(403, "Session expirée : rechargez la page puis saisissez de nouveau votre code.")
    if trop_de_tentatives(request):
        raise HttpError(429, "Trop de codes erronés : réessayez dans un quart d'heure.")
    intervenant = intervenant_par_code(donnees.code)
    if intervenant is None:
        noter_echec(request)
        raise HttpError(401, "Code d'accès inconnu, désactivé ou chantier clos.")
    ouvrir_session(request, intervenant)
    journaliser(intervenant.espace, TypeEvenement.CONNEXION, f"Connexion de {intervenant.nom}", acteur_intervenant(intervenant))
    return _espace_out(intervenant)


@router.post("/ged/portail/deconnexion", auth=None, response={204: None})
def deconnexion(request):
    if check_csrf(request) is not None:
        raise HttpError(403, "Session expirée.")
    fermer_session(request)
    return 204, None


@router.get("/ged/portail/espace")
def espace(request):
    return _espace_out(request.auth)


@router.get("/ged/portail/documents")
def documents(request):
    intervenant = request.auth
    return vues.lister(intervenant.espace, acteur_intervenant(intervenant))


@router.post("/ged/portail/documents", response={201: dict})
def deposer(
    request, fichier: File[UploadedFile], zone: Form[str], categorie: Form[str], lot_id: Form[int | None] = None,
    titre: Form[str] = "", reference: Form[str] = "", indice: Form[str] = "", objet: Form[str] = "", visa_requis: Form[bool] = False,
):
    intervenant = request.auth
    return 201, vues.deposer_formulaire(acteur_intervenant(intervenant), intervenant.espace, fichier, zone=zone, lot_id=lot_id, categorie=categorie,
                                        titre=titre, reference=reference, indice=indice, objet=objet, visa_requis=visa_requis)


@router.post("/ged/portail/documents/{document_id}/versions", response={201: dict})
def ajouter_indice(request, document_id: int, fichier: File[UploadedFile], indice: Form[str] = "", objet: Form[str] = "", visa_requis: Form[bool | None] = None):
    intervenant = request.auth
    return 201, vues.nouvel_indice_formulaire(acteur_intervenant(intervenant), intervenant.espace, document_id, fichier, indice=indice, objet=objet, visa_requis=visa_requis)


@router.post("/ged/portail/versions/{version_id}/visa")
def viser(request, version_id: int, statut: Form[str], commentaire: Form[str] = "", fichier: File[UploadedFile | None] = None):
    intervenant = request.auth
    return vues.viser_formulaire(acteur_intervenant(intervenant), intervenant.espace, version_id, statut=statut, commentaire=commentaire, fichier=fichier)


@router.get("/ged/portail/versions/{version_id}/fichier")
def fichier(request, version_id: int):
    intervenant = request.auth
    return vues.telecharger(acteur_intervenant(intervenant), intervenant.espace, version_id)


@router.get("/ged/portail/versions/{version_id}/visa")
def fichier_visa(request, version_id: int):
    intervenant = request.auth
    return vues.telecharger(acteur_intervenant(intervenant), intervenant.espace, version_id, visa=True)


@router.get("/ged/portail/journal")
def journal(request, page: int = 1):
    intervenant = request.auth
    return vues.journal(intervenant.espace, acteur_intervenant(intervenant), page)


@router.get("/ged/portail/registre.xlsx")
def registre(request):
    intervenant = request.auth
    return vues.registre_xlsx(intervenant.espace, acteur_intervenant(intervenant))

