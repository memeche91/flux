"""API du DCE : contrôle, documents joints, dossiers .zip, entreprises consultées et envois."""
from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Literal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Field, File, Form, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from entreprises.models import Entreprise
from projets.models import LotProjet, Projet

from .assemblage import plan, racine
from .controle import controler
from .envois import envoyer_courriel, message_entreprise, message_moa, personnaliser
from .models import (
    CategoriePieceJointe,
    ConsultationEntreprise,
    DossierDCE,
    Envoi,
    ModeEnvoi,
    PieceJointe,
    StatutConsultation,
    StatutDossier,
    StatutEnvoi,
    TypeEnvoi,
)
from .tasks import envoyer_aux_entreprises, generer_dossier, marquer_consultees

router = Router(tags=["DCE"])

EXTENSIONS_JOINTES = {".pdf", ".dwg", ".dxf", ".ifc", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".doc", ".docx", ".xls", ".xlsx", ".odt", ".ods", ".zip", ".txt", ".csv", ".pptx"}


# --- Schémas -------------------------------------------------------------------------


class PieceJointeOut(Schema):
    id: int
    categorie: str
    categorie_libelle: str
    lot_id: int | None
    lot: str | None
    titre: str
    nom_original: str
    taille: int


class DossierOut(Schema):
    id: int
    indice: str
    entreprise: str | None
    lots: list[str]
    avec_word: bool
    statut: str
    message: str
    taille: int
    nb_fichiers: int
    contenu: list[dict]
    cree_le: datetime.datetime


class ConsultationOut(Schema):
    id: int
    lot_id: int
    entreprise_id: int
    entreprise: str
    email: str
    statut: str
    statut_libelle: str
    consultee_le: datetime.date | None
    commentaire: str


class EnvoiOut(Schema):
    id: int
    type_envoi: str
    entreprise: str | None
    destinataires: str
    objet: str
    message: str
    mode: str
    statut: str
    statut_libelle: str
    erreur: str
    piece_jointe: bool
    dossier_id: int | None
    envoye_le: datetime.datetime | None
    cree_le: datetime.datetime


class EtatDCE(Schema):
    type_marche: str
    indice: str
    email_actif: bool
    piece_jointe_max_mo: int
    controle: list[dict]
    pieces_jointes: list[PieceJointeOut]
    dossiers: list[DossierOut]
    consultations: list[ConsultationOut]
    envois: list[EnvoiOut]


class DemandeDossier(Schema):
    indice: str = Field(..., min_length=1, max_length=10)
    avec_word: bool = False


class ModificationPieceJointe(Schema):
    titre: str | None = Field(None, min_length=1, max_length=255)
    categorie: CategoriePieceJointe | None = None
    lot_id: int | None = None


class AjoutConsultation(Schema):
    lot_id: int
    entreprise_ids: list[int] = Field(..., min_length=1)


class ModificationConsultation(Schema):
    statut: StatutConsultation | None = None
    commentaire: str | None = Field(None, max_length=500)


class EnvoiMoa(Schema):
    dossier_id: int
    destinataires: str = Field(..., min_length=3, max_length=1000)
    objet: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1, max_length=20000)
    mode: ModeEnvoi = ModeEnvoi.EMAIL


class EnvoiEntreprises(Schema):
    entreprise_ids: list[int] = Field(..., min_length=1)
    objet: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1, max_length=20000)
    indice: str = Field("A", min_length=1, max_length=10)
    avec_word: bool = False
    mode: ModeEnvoi = ModeEnvoi.EMAIL


# --- Sorties ----------------------------------------------------------------------------


def _piece_jointe(j: PieceJointe) -> dict:
    return {
        "id": j.pk, "categorie": j.categorie, "categorie_libelle": j.get_categorie_display(), "lot_id": j.lot_id,
        "lot": f"Lot {j.lot.code} – {j.lot.intitule}" if j.lot else None, "titre": j.titre, "nom_original": j.nom_original, "taille": j.taille,
    }


def _dossier(d: DossierDCE) -> dict:
    return {
        "id": d.pk, "indice": d.indice, "entreprise": d.entreprise.raison_sociale if d.entreprise else None,
        "lots": [f"{l.code}" for l in d.lots.all()], "avec_word": d.avec_word, "statut": d.statut, "message": d.message,
        "taille": d.taille, "nb_fichiers": len(d.contenu), "contenu": d.contenu, "cree_le": d.cree_le,
    }


def _consultation(c: ConsultationEntreprise) -> dict:
    contact = next(iter(c.entreprise.contacts.all()), None)
    return {
        "id": c.pk, "lot_id": c.lot_id, "entreprise_id": c.entreprise_id, "entreprise": c.entreprise.raison_sociale,
        "email": c.entreprise.email or (contact.email if contact else ""), "statut": c.statut, "statut_libelle": c.get_statut_display(),
        "consultee_le": c.consultee_le, "commentaire": c.commentaire,
    }


def _envoi(e: Envoi) -> dict:
    return {
        "id": e.pk, "type_envoi": e.type_envoi, "entreprise": e.entreprise.raison_sociale if e.entreprise else None,
        "destinataires": e.destinataires, "objet": e.objet, "message": e.message, "mode": e.mode, "statut": e.statut,
        "statut_libelle": e.get_statut_display(), "erreur": e.erreur, "piece_jointe": e.piece_jointe, "dossier_id": e.dossier_id,
        "envoye_le": e.envoye_le, "cree_le": e.cree_le,
    }


def _projet(projet_id: int) -> Projet:
    return get_object_or_404(Projet, pk=projet_id)


def _destinataires(texte: str) -> str:
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    adresses = [a.strip() for a in re.split(r"[,;\s]+", texte) if a.strip()]
    if not adresses:
        raise HttpError(400, "Indiquez au moins une adresse e-mail.")
    for adresse in adresses:
        try:
            validate_email(adresse)
        except ValidationError:
            raise HttpError(400, f"Adresse e-mail invalide : « {adresse} ».") from None
    return ", ".join(adresses)


def _email_entreprise(entreprise: Entreprise) -> str:
    if entreprise.email:
        return entreprise.email
    contact = entreprise.contacts.exclude(email="").first()
    return contact.email if contact else ""


# --- État du DCE ---------------------------------------------------------------------


@router.get("/projets/{projet_id}/dce", response=EtatDCE)
def etat(request, projet_id: int):
    projet = _projet(projet_id)
    return {
        "type_marche": projet.type_marche,
        "indice": projet.indice,
        "email_actif": settings.EMAIL_ACTIF,
        "piece_jointe_max_mo": settings.EMAIL_PIECE_JOINTE_MAX_MO,
        "controle": controler(projet),
        "pieces_jointes": [_piece_jointe(j) for j in projet.pieces_jointes.select_related("lot")],
        "dossiers": [_dossier(d) for d in projet.dossiers_dce.select_related("entreprise").prefetch_related("lots")[:50]],
        "consultations": [_consultation(c) for c in projet.consultations_entreprises.select_related("entreprise", "lot").prefetch_related("entreprise__contacts")],
        "envois": [_envoi(e) for e in projet.envois_dce.select_related("entreprise")[:200]],
    }


@router.get("/projets/{projet_id}/dce/apercu")
def apercu(request, projet_id: int, avec_word: bool = False, indice: str = "A"):
    """Arborescence prévue du DCE complet (sans produire les fichiers)."""
    projet = _projet(projet_id)
    fichiers = plan(projet, avec_word=avec_word)
    tete = ["00 - Bordereau des pièces.pdf"]
    return {"racine": racine(projet, indice[:10] or "A"), "fichiers": tete + [f.chemin for f in fichiers]}


@router.get("/projets/{projet_id}/dce/messages")
def messages_types(request, projet_id: int, indice: str = "A"):
    projet = _projet(projet_id)
    objet_moa, texte_moa = message_moa(projet, indice[:10] or "A")
    objet_entreprise, texte_entreprise = message_entreprise(projet)
    return {"moa": {"objet": objet_moa, "message": texte_moa}, "entreprise": {"objet": objet_entreprise, "message": texte_entreprise}}


# --- Documents joints ----------------------------------------------------------------


@router.post("/projets/{projet_id}/dce/pieces-jointes", response={201: PieceJointeOut})
def ajouter_piece_jointe(
    request,
    projet_id: int,
    fichier: File[UploadedFile],
    categorie: Form[CategoriePieceJointe] = CategoriePieceJointe.PLANS,
    lot_id: Form[int | None] = None,
    titre: Form[str] = "",
):
    projet = _projet(projet_id)
    extension = Path(fichier.name or "").suffix.lower()
    if extension not in EXTENSIONS_JOINTES:
        raise HttpError(400, f"Format « {extension or 'inconnu'} » non accepté. Formats possibles : {', '.join(sorted(EXTENSIONS_JOINTES))}.")
    if fichier.size > settings.TAILLE_MAX_FICHIER_MO * 1024 * 1024:
        raise HttpError(400, f"Fichier trop volumineux (maximum {settings.TAILLE_MAX_FICHIER_MO} Mo).")
    if fichier.size == 0:
        raise HttpError(400, "Le fichier est vide.")
    lot = get_object_or_404(LotProjet, pk=lot_id, projet=projet) if lot_id else None
    titre = " ".join((titre or Path(fichier.name or "Document").stem).split())[:255] or "Document"
    jointe = PieceJointe(projet=projet, categorie=categorie, lot=lot, titre=titre, nom_original=(fichier.name or "document")[:255], taille=fichier.size)
    jointe.fichier.save(fichier.name or f"document{extension}", fichier, save=False)
    jointe.save()
    return 201, _piece_jointe(jointe)


@router.patch("/dce/pieces-jointes/{jointe_id}", response=PieceJointeOut)
def modifier_piece_jointe(request, jointe_id: int, donnees: ModificationPieceJointe):
    jointe = get_object_or_404(PieceJointe.objects.select_related("lot"), pk=jointe_id)
    champs = donnees.model_dump(exclude_unset=True)
    if champs.get("titre"):
        jointe.titre = " ".join(champs["titre"].split())[:255] or jointe.titre
    if champs.get("categorie"):
        jointe.categorie = champs["categorie"]
    if "lot_id" in champs:
        jointe.lot = get_object_or_404(LotProjet, pk=champs["lot_id"], projet_id=jointe.projet_id) if champs["lot_id"] else None
    jointe.save()
    return _piece_jointe(jointe)


@router.delete("/dce/pieces-jointes/{jointe_id}", response={204: None})
def supprimer_piece_jointe(request, jointe_id: int):
    jointe = get_object_or_404(PieceJointe, pk=jointe_id)
    jointe.fichier.delete(save=False)
    jointe.delete()
    return 204, None


# --- Dossiers .zip -------------------------------------------------------------------


@router.post("/projets/{projet_id}/dce/dossiers", response={202: DossierOut})
def generer(request, projet_id: int, donnees: DemandeDossier):
    projet = _projet(projet_id)
    if not projet.lots.exists():
        raise HttpError(400, "Ajoutez au moins un lot avant de générer le DCE.")
    if projet.dossiers_dce.filter(statut=StatutDossier.EN_COURS, entreprise__isnull=True).exists():
        raise HttpError(409, "Un DCE est déjà en préparation : patientez quelques instants.")
    indice = re.sub(r"[^\w-]", "", donnees.indice)[:10] or "A"
    dossier = DossierDCE.objects.create(projet=projet, indice=indice, avec_word=donnees.avec_word, cree_par=request.auth)
    transaction.on_commit(lambda: generer_dossier.delay(dossier.pk))
    return 202, _dossier(dossier)


@router.get("/dce/dossiers/{dossier_id}/telecharger")
def telecharger(request, dossier_id: int):
    dossier = get_object_or_404(DossierDCE, pk=dossier_id, statut=StatutDossier.PRET)
    if not dossier.fichier:
        raise HttpError(404, "Fichier introuvable.")
    return FileResponse(dossier.fichier.open("rb"), as_attachment=True, filename=dossier.nom or "DCE.zip", content_type="application/zip")


@router.delete("/dce/dossiers/{dossier_id}", response={204: None})
def supprimer_dossier(request, dossier_id: int):
    dossier = get_object_or_404(DossierDCE, pk=dossier_id)
    if dossier.statut == StatutDossier.EN_COURS:
        raise HttpError(409, "Ce dossier est en cours de préparation.")
    if dossier.fichier:
        dossier.fichier.delete(save=False)
    dossier.delete()
    return 204, None


# --- Entreprises consultées ----------------------------------------------------------


@router.get("/projets/{projet_id}/dce/suggestions")
def suggestions(request, projet_id: int, lot_id: int):
    """Entreprises actives de l'annuaire pour ce lot (spécialité), pas encore consultées."""
    lot = get_object_or_404(LotProjet, pk=lot_id, projet_id=projet_id)
    deja = ConsultationEntreprise.objects.filter(lot=lot).values_list("entreprise_id", flat=True)
    entreprises = Entreprise.objects.filter(actif=True).exclude(pk__in=deja)
    if lot.lot_id:
        entreprises = entreprises.filter(lots=lot.lot_id)
    else:
        return []
    return [{"id": e.pk, "raison_sociale": e.raison_sociale, "ville": e.ville, "email": _email_entreprise(e)} for e in entreprises.prefetch_related("contacts")[:100]]


@router.post("/projets/{projet_id}/dce/consultations", response={201: list[ConsultationOut]})
def ajouter_consultations(request, projet_id: int, donnees: AjoutConsultation):
    projet = _projet(projet_id)
    lot = get_object_or_404(LotProjet, pk=donnees.lot_id, projet=projet)
    entreprises = list(Entreprise.objects.filter(pk__in=donnees.entreprise_ids))
    if len(entreprises) != len(set(donnees.entreprise_ids)):
        raise HttpError(400, "Une des entreprises choisies n'existe pas.")
    crees = []
    for entreprise in entreprises:
        try:
            with transaction.atomic():
                crees.append(ConsultationEntreprise.objects.create(projet=projet, lot=lot, entreprise=entreprise))
        except IntegrityError:
            continue  # déjà consultée pour ce lot
    return 201, [_consultation(c) for c in ConsultationEntreprise.objects.filter(pk__in=[c.pk for c in crees]).select_related("entreprise").prefetch_related("entreprise__contacts")]


@router.patch("/dce/consultations/{consultation_id}", response=ConsultationOut)
def modifier_consultation(request, consultation_id: int, donnees: ModificationConsultation):
    consultation = get_object_or_404(ConsultationEntreprise.objects.select_related("entreprise"), pk=consultation_id)
    champs = donnees.model_dump(exclude_unset=True)
    if champs.get("statut"):
        consultation.statut = champs["statut"]
        if consultation.statut != StatutConsultation.A_CONSULTER and not consultation.consultee_le:
            consultation.consultee_le = timezone.localdate()
    if "commentaire" in champs:
        consultation.commentaire = (champs["commentaire"] or "").strip()
    consultation.save()
    return _consultation(consultation)


@router.delete("/dce/consultations/{consultation_id}", response={204: None})
def supprimer_consultation(request, consultation_id: int):
    consultation = get_object_or_404(ConsultationEntreprise, pk=consultation_id)
    if consultation.statut != StatutConsultation.A_CONSULTER:
        raise HttpError(409, "Cette entreprise a déjà été consultée : changez plutôt son statut (« S'est excusée »…).")
    consultation.delete()
    return 204, None


# --- Envois ----------------------------------------------------------------------------


@router.post("/projets/{projet_id}/dce/envois/moa", response={201: EnvoiOut})
def envoyer_moa(request, projet_id: int, donnees: EnvoiMoa):
    projet = _projet(projet_id)
    dossier = get_object_or_404(DossierDCE, pk=donnees.dossier_id, projet=projet, statut=StatutDossier.PRET, entreprise__isnull=True)
    mode = donnees.mode if settings.EMAIL_ACTIF else ModeEnvoi.MANUEL
    envoi = Envoi.objects.create(
        projet=projet, type_envoi=TypeEnvoi.MOA, dossier=dossier, destinataires=_destinataires(donnees.destinataires),
        objet=donnees.objet.strip(), message=donnees.message.strip(), mode=mode, cree_par=request.auth,
        statut=StatutEnvoi.PREPARATION if mode == ModeEnvoi.EMAIL else StatutEnvoi.A_ENVOYER,
    )
    if mode == ModeEnvoi.EMAIL:
        envoyer_courriel(envoi, dossier)
    return 201, _envoi(envoi)


@router.post("/projets/{projet_id}/dce/envois/entreprises", response={202: list[EnvoiOut]})
def envoyer_entreprises(request, projet_id: int, donnees: EnvoiEntreprises):
    projet = _projet(projet_id)
    mode = donnees.mode if settings.EMAIL_ACTIF else ModeEnvoi.MANUEL
    entreprises = list(Entreprise.objects.filter(pk__in=donnees.entreprise_ids).prefetch_related("contacts"))
    if len(entreprises) != len(set(donnees.entreprise_ids)):
        raise HttpError(400, "Une des entreprises choisies n'existe pas.")
    envois = []
    with transaction.atomic():
        for entreprise in entreprises:
            lots = [c.lot for c in ConsultationEntreprise.objects.filter(projet=projet, entreprise=entreprise).select_related("lot")]
            if not lots:
                raise HttpError(400, f"{entreprise.raison_sociale} n'est consultée pour aucun lot de ce projet.")
            adresse = _email_entreprise(entreprise)
            if mode == ModeEnvoi.EMAIL and not adresse:
                raise HttpError(400, f"{entreprise.raison_sociale} n'a pas d'adresse e-mail dans l'annuaire.")
            envois.append(Envoi.objects.create(
                projet=projet, type_envoi=TypeEnvoi.ENTREPRISE, entreprise=entreprise, destinataires=adresse or "—",
                objet=personnaliser(donnees.objet.strip(), entreprise, lots), message=personnaliser(donnees.message.strip(), entreprise, lots),
                mode=mode, cree_par=request.auth,
            ))
    identifiants = [e.pk for e in envois]
    indice = re.sub(r"[^\w-]", "", donnees.indice)[:10] or "A"
    transaction.on_commit(lambda: envoyer_aux_entreprises.delay(identifiants, indice, donnees.avec_word))
    return 202, [_envoi(e) for e in envois]


@router.post("/dce/envois/{envoi_id}/envoye", response=EnvoiOut)
def marquer_envoye(request, envoi_id: int):
    """Envoi fait par l'utilisateur lui-même (sans messagerie configurée, ou dossier trop lourd)."""
    envoi = get_object_or_404(Envoi.objects.select_related("entreprise"), pk=envoi_id)
    if envoi.statut not in (StatutEnvoi.A_ENVOYER, StatutEnvoi.ERREUR):
        raise HttpError(409, "Cet envoi n'est pas en attente.")
    envoi.statut, envoi.envoye_le = StatutEnvoi.ENVOYE, timezone.now()
    envoi.save(update_fields=["statut", "envoye_le"])
    marquer_consultees(envoi)
    return _envoi(envoi)
