"""Traitements communs aux routes du cabinet et du portail des intervenants."""
from __future__ import annotations

import io

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.http import content_disposition_header
from ninja.errors import HttpError

from projets.exports.document import nom_de_fichier
from projets.fichiers import reponse_fichier_sure

from .droits import Acteur, peut_voir
from .models import AvisVersion, Document, EspaceChantier, StatutVisa, TypeEvenement, Version, Zone
from .serialisation import EN_VIGUEUR, document_out, documents_visibles, evenement_out, nom_telechargement, statuts_des_versions
from .services import accuser_lecture, deposer, donner_avis, journaliser, nouvel_indice, viser

EVENEMENTS_VISIBLES_INTERVENANTS = [TypeEvenement.DEPOT, TypeEvenement.INDICE, TypeEvenement.VISA, TypeEvenement.ANNULATION, TypeEvenement.MODIFICATION]


def _document_frais(document_id: int, acteur: Acteur) -> dict:
    return document_out(
        Document.objects.select_related("lot", "espace__projet").prefetch_related("versions__avis", "versions__accuses__intervenant", "versions__sources").get(pk=document_id),
        acteur,
    )


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
                       reference: str, reference_emetteur: str, indice: str, objet: str, diffusion: str | None, date_indice,
                       sources=(), depot: str = "") -> dict:
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
                          reference_emetteur=reference_emetteur, indice=indice, objet=objet, diffusion=diffusion or None, date_indice=date_indice,
                          sources=sources or (), depot=depot)
    return _document_frais(document.pk, acteur)


def nouvel_indice_formulaire(acteur: Acteur, espace: EspaceChantier, document_id: int, fichier, *, indice: str, objet: str, diffusion: str | None, date_indice,
                             sources=(), depot: str = "", forcer: str = "") -> dict:
    document = document_visible(acteur, espace, document_id)
    nouvel_indice(acteur, document, fichier=fichier, indice=indice, objet=objet, diffusion=diffusion or None, date_indice=date_indice,
                  sources=sources or (), depot=depot, forcer=forcer)
    return _document_frais(document.pk, acteur)


def viser_formulaire(acteur: Acteur, espace: EspaceChantier, version_id: int, *, statut: str, commentaire: str, fichier, nouvel_indice_attendu: bool | None) -> dict:
    version = version_visible(acteur, espace, version_id)
    viser(acteur, version, statut=statut, commentaire=commentaire, fichier=fichier, nouvel_indice_attendu=nouvel_indice_attendu)
    return _document_frais(version.document_id, acteur)


def avis_formulaire(acteur: Acteur, espace: EspaceChantier, version_id: int, *, avis: str, observations: str, fichier) -> dict:
    version = version_visible(acteur, espace, version_id)
    donner_avis(acteur, version, avis=avis, observations=observations, fichier=fichier)
    return _document_frais(version.document_id, acteur)


def accuser_lecture_vue(acteur: Acteur, espace: EspaceChantier, version_id: int) -> dict:
    version = version_visible(acteur, espace, version_id)
    accuser_lecture(acteur, version)
    return _document_frais(version.document_id, acteur)


def reponse_fichier(champ, nom: str):
    return reponse_fichier_sure(champ, nom)


def telecharger(acteur: Acteur, espace: EspaceChantier, version_id: int, *, quoi: str = "fichier"):
    """quoi : fichier (indice), annote (plan annoté du visa), fiche (fiche de visa PDF)."""
    version = version_visible(acteur, espace, version_id)
    document = version.document
    if quoi == "annote":
        if version.visa in (StatutVisa.EN_ATTENTE, StatutVisa.SANS_OBJET):
            raise HttpError(404, "Aucun visa émis.")
        return reponse_fichier(version.visa_fichier, version.visa_nom_original or "visa")
    if quoi == "fiche":
        return reponse_fichier(version.fiche_visa, f"Fiche de visa {document.reference} indice {version.indice}.pdf")
    statut = statuts_des_versions(list(document.versions.all())).get(version.pk, EN_VIGUEUR)
    if not acteur.cabinet:
        # Trace de la remise du document à l'intervenant (preuve de diffusion).
        journaliser(espace, TypeEvenement.TELECHARGEMENT, f"{document.reference} indice {version.indice}", acteur, document=document, version=version)
    return reponse_fichier(version.fichier, nom_telechargement(document, version, statut))


def telecharger_source(acteur: Acteur, espace: EspaceChantier, source_id: int):
    from .models import FichierSource

    source = get_object_or_404(FichierSource.objects.select_related("version__document__espace"), pk=source_id, version__document__espace=espace)
    if not peut_voir(acteur, source.version.document):
        raise HttpError(404, "Fichier introuvable.")
    return reponse_fichier(source.fichier, source.nom_original)


def telecharger_avis(acteur: Acteur, espace: EspaceChantier, avis_id: int):
    avis = get_object_or_404(AvisVersion.objects.select_related("version__document__espace"), pk=avis_id, version__document__espace=espace)
    from .droits import voit_avis

    if not peut_voir(acteur, avis.version.document) or not voit_avis(acteur, avis.version):
        raise HttpError(404, "Avis introuvable.")
    return reponse_fichier(avis.fichier, avis.nom_original or "avis")


def journal(espace: EspaceChantier, acteur: Acteur, page: int = 1, par_page: int = 50) -> dict:
    evenements = espace.evenements.select_related("document")
    if not acteur.cabinet:
        visibles = documents_visibles(espace, acteur).values("pk")
        evenements = evenements.filter(type__in=EVENEMENTS_VISIBLES_INTERVENANTS, document__in=visibles)
    total = evenements.count()
    page = max(1, page)
    return {"total": total, "resultats": [evenement_out(e, acteur.cabinet) for e in evenements[(page - 1) * par_page:page * par_page]]}


def registre_xlsx(espace: EspaceChantier, acteur: Acteur) -> HttpResponse:
    """Registre des documents : un document par bloc, tous ses indices, leurs visas et échéances."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    from .serialisation import LIBELLES_STATUTS

    classeur = Workbook()
    feuille = classeur.active
    feuille.title = "Registre"
    projet = espace.projet
    feuille.append([f"{projet.nom} – registre des documents du chantier au {timezone.localdate():%d/%m/%Y}"])
    feuille["A1"].font = Font(bold=True, size=13)
    entetes = ["Zone", "Lot", "Catégorie", "Référence", "N° émetteur", "Titre", "Indice", "Déposé le", "Déposé par", "Objet de la modification",
               "Diffusion", "Échéance de visa", "Visa", "Visé le", "Retard (jours)", "Observations du visa", "État"]
    feuille.append([])
    feuille.append(entetes)
    couleur = projet.couleur_tableaux.lstrip("#").upper()
    for cellule in feuille[3]:
        cellule.font = Font(bold=True)
        cellule.fill = PatternFill("solid", start_color=couleur, end_color=couleur)
    aujourd_hui = timezone.localdate()
    for document in documents_visibles(espace, acteur):
        versions = sorted(document.versions.all(), key=lambda v: (v.deposee_le, v.pk), reverse=True)
        statuts = statuts_des_versions(versions)
        for v in versions:
            # Retard : jusqu'au visa, ou jusqu'à aujourd'hui pour un indice qui attend encore son visa
            # (jamais pour un indice remplacé avant visa ni pour un document annulé).
            if v.vise_le:
                fin = timezone.localdate(v.vise_le)
            elif v.visa == StatutVisa.EN_ATTENTE and not document.annule:
                fin = aujourd_hui
            else:
                fin = None
            retard = (fin - v.echeance_visa).days if fin and v.echeance_visa and fin > v.echeance_visa else ""
            feuille.append([
                document.get_zone_display(), document.lot.code if document.lot else "", document.get_categorie_display(), document.reference,
                document.reference_emetteur, document.titre, v.indice, timezone.localtime(v.deposee_le).strftime("%d/%m/%Y %H:%M"), v.deposee_par_nom,
                v.objet, v.get_diffusion_display(), v.echeance_visa.strftime("%d/%m/%Y") if v.echeance_visa else "",
                v.get_visa_display() if v.visa else "", timezone.localtime(v.vise_le).strftime("%d/%m/%Y") if v.vise_le else "", retard,
                v.visa_commentaire, "Annulé" if document.annule else LIBELLES_STATUTS[statuts[v.pk]],
            ])
            for cellule in feuille[feuille.max_row]:
                if cellule.data_type == "f":
                    cellule.data_type = "s"  # texte saisi (« =… ») : écrit tel quel, jamais en formule Excel
                if statuts[v.pk] == EN_VIGUEUR:
                    cellule.font = Font(bold=True)
    for colonne, largeur in zip("ABCDEFGHIJKLMNOPQ", (12, 6, 26, 15, 16, 40, 7, 16, 24, 32, 16, 12, 22, 11, 9, 40, 11)):
        feuille.column_dimensions[colonne].width = largeur
    feuille.freeze_panes = "A4"
    flux = io.BytesIO()
    classeur.save(flux)
    reponse = HttpResponse(flux.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    reponse["Content-Disposition"] = content_disposition_header(True, nom_de_fichier(f"Registre des documents - {projet.nom}", "xlsx"))
    return reponse
