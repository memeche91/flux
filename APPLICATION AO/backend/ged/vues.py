"""Traitements communs aux routes du cabinet et du portail des intervenants."""
from __future__ import annotations

import io
from pathlib import Path

from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.http import content_disposition_header
from ninja.errors import HttpError

from .droits import Acteur, peut_voir
from .models import Document, EspaceChantier, StatutVisa, TypeEvenement, Version, Zone
from .serialisation import document_out, documents_visibles, evenement_out
from .services import deposer, journaliser, nouvel_indice, viser

AFFICHABLES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
EVENEMENTS_VISIBLES_INTERVENANTS = [TypeEvenement.DEPOT, TypeEvenement.INDICE, TypeEvenement.VISA, TypeEvenement.ANNULATION, TypeEvenement.MODIFICATION]


def lister(espace: EspaceChantier, acteur: Acteur) -> list[dict]:
    return [document_out(d, acteur) for d in documents_visibles(espace, acteur)]


def document_visible(acteur: Acteur, espace: EspaceChantier, document_id: int) -> Document:
    document = get_object_or_404(Document.objects.select_related("lot", "espace__projet"), pk=document_id, espace=espace)
    if not peut_voir(acteur, document):
        raise HttpError(404, "Document introuvable.")
    return document


def version_visible(acteur: Acteur, espace: EspaceChantier, version_id: int) -> Version:
    version = get_object_or_404(Version.objects.select_related("document__lot", "document__espace__projet"), pk=version_id, document__espace=espace)
    if not peut_voir(acteur, version.document):
        raise HttpError(404, "Document introuvable.")
    return version


def deposer_formulaire(acteur: Acteur, espace: EspaceChantier, fichier, *, zone: str, lot_id: int | None, categorie: str, titre: str,
                       reference: str, indice: str, objet: str, visa_requis: bool | None) -> dict:
    if zone not in Zone.values:
        raise HttpError(400, "Zone inconnue.")
    lot = None
    if zone == Zone.LOT:
        if not lot_id:
            raise HttpError(400, "Indiquez le lot du document.")
        lot = espace.projet.lots.filter(pk=lot_id).first()
        if lot is None:
            raise HttpError(400, "Lot inconnu pour ce chantier.")
    document, _ = deposer(acteur, espace, zone=zone, lot=lot, categorie=categorie, titre=titre, fichier=fichier, reference=reference,
                          indice=indice, objet=objet, visa_requis=visa_requis)
    return document_out(Document.objects.select_related("lot", "espace").prefetch_related("versions").get(pk=document.pk), acteur)


def nouvel_indice_formulaire(acteur: Acteur, espace: EspaceChantier, document_id: int, fichier, *, indice: str, objet: str, visa_requis: bool | None) -> dict:
    document = document_visible(acteur, espace, document_id)
    nouvel_indice(acteur, document, fichier=fichier, indice=indice, objet=objet, visa_requis=visa_requis)
    return document_out(Document.objects.select_related("lot", "espace").prefetch_related("versions").get(pk=document.pk), acteur)


def viser_formulaire(acteur: Acteur, espace: EspaceChantier, version_id: int, *, statut: str, commentaire: str, fichier) -> dict:
    version = version_visible(acteur, espace, version_id)
    viser(acteur, version, statut=statut, commentaire=commentaire, fichier=fichier)
    return document_out(Document.objects.select_related("lot", "espace").prefetch_related("versions").get(pk=version.document_id), acteur)


def reponse_fichier(champ, nom: str):
    if not champ:
        raise HttpError(404, "Aucun fichier.")
    try:
        flux = champ.open("rb")
    except FileNotFoundError:
        raise HttpError(404, "Fichier introuvable sur le disque.") from None
    extension = Path(nom).suffix.lower()
    if extension in AFFICHABLES:
        reponse = FileResponse(flux, content_type=AFFICHABLES[extension], as_attachment=False, filename=nom)
        if extension != ".pdf":
            reponse["Content-Security-Policy"] = "sandbox"
    else:
        # Tout autre format est téléchargé, jamais affiché par le navigateur.
        reponse = FileResponse(flux, content_type="application/octet-stream", as_attachment=True, filename=nom)
    reponse["X-Content-Type-Options"] = "nosniff"
    return reponse


def telecharger(acteur: Acteur, espace: EspaceChantier, version_id: int, *, visa: bool = False):
    version = version_visible(acteur, espace, version_id)
    if visa:
        return reponse_fichier(version.visa_fichier, version.visa_nom_original or "visa")
    if not acteur.cabinet:
        # Trace de la remise du document à l'intervenant (preuve de diffusion).
        journaliser(espace, TypeEvenement.TELECHARGEMENT, f"{version.document.reference} indice {version.indice}", acteur, document=version.document, version=version)
    return reponse_fichier(version.fichier, version.nom_original)


def journal(espace: EspaceChantier, acteur: Acteur, page: int = 1, par_page: int = 50) -> dict:
    evenements = espace.evenements.select_related("document")
    if not acteur.cabinet:
        visibles = documents_visibles(espace, acteur).values("pk")
        evenements = evenements.filter(type__in=EVENEMENTS_VISIBLES_INTERVENANTS, document__in=visibles)
    total = evenements.count()
    page = max(1, page)
    return {"total": total, "resultats": [evenement_out(e) for e in evenements[(page - 1) * par_page:page * par_page]]}


def registre_xlsx(espace: EspaceChantier, acteur: Acteur) -> HttpResponse:
    """Registre des documents : un document par bloc, tous ses indices et leurs visas."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    classeur = Workbook()
    feuille = classeur.active
    feuille.title = "Registre"
    projet = espace.projet
    feuille.append([f"{projet.nom} – registre des documents du chantier au {timezone.localdate().strftime('%d/%m/%Y')}"])
    feuille["A1"].font = Font(bold=True, size=13)
    entetes = ["Zone", "Lot", "Catégorie", "Référence", "Titre", "Indice", "Déposé le", "Déposé par", "Objet de la modification", "Visa", "Visé le", "Observations du visa", "État"]
    feuille.append([])
    feuille.append(entetes)
    couleur = projet.couleur_tableaux.lstrip("#").upper()
    for cellule in feuille[3]:
        cellule.font = Font(bold=True)
        cellule.fill = PatternFill("solid", start_color=couleur, end_color=couleur)
    for document in documents_visibles(espace, acteur):
        versions = sorted(document.versions.all(), key=lambda v: (v.deposee_le, v.pk), reverse=True)
        for rang, v in enumerate(versions):
            feuille.append([
                document.get_zone_display(), document.lot.code if document.lot else "", document.get_categorie_display(), document.reference,
                document.titre, v.indice, timezone.localtime(v.deposee_le).strftime("%d/%m/%Y %H:%M"), v.deposee_par_nom, v.objet,
                v.get_visa_display() if v.visa != StatutVisa.SANS_OBJET else "", timezone.localtime(v.vise_le).strftime("%d/%m/%Y") if v.vise_le else "",
                v.visa_commentaire, "Annulé" if document.annule else ("En vigueur" if rang == 0 else "Remplacé"),
            ])
            if rang == 0:
                for cellule in feuille[feuille.max_row]:
                    cellule.font = Font(bold=True)
    for colonne, largeur in zip("ABCDEFGHIJKLM", (12, 6, 22, 16, 44, 7, 16, 24, 36, 22, 11, 40, 11)):
        feuille.column_dimensions[colonne].width = largeur
    feuille.freeze_panes = "A4"
    flux = io.BytesIO()
    classeur.save(flux)
    reponse = HttpResponse(flux.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    from projets.exports.document import nom_de_fichier

    reponse["Content-Disposition"] = content_disposition_header(True, nom_de_fichier(f"Registre des documents - {projet.nom}", "xlsx"))
    return reponse
