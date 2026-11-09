"""Opérations de la GED : dépôt, nouvel indice, visa, annulation, journal.

Toutes passent par ici, qu'elles viennent du cabinet ou du portail des intervenants, pour que
les droits, les indices et le journal soient appliqués de la même façon.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from ninja.errors import HttpError

from .droits import Acteur, peut_ajouter_indice, peut_deposer, peut_viser
from .indices import indice_suivant, indice_valide, normaliser_indice, superieur
from .models import (
    CATEGORIES_A_VISER,
    SIGLES_CATEGORIES,
    Categorie,
    Document,
    EspaceChantier,
    Evenement,
    StatutEspace,
    StatutVisa,
    TypeEvenement,
    Version,
    Zone,
)

# Formats acceptés : plans (PDF, DWG, IFC…), bureautique, images, archives. Pas d'exécutables
# ni de pages web (HTML, SVG), qui pourraient exécuter du code à l'ouverture.
EXTENSIONS = {
    ".pdf", ".dwg", ".dxf", ".dwf", ".ifc", ".rvt", ".skp", ".bcf",
    ".doc", ".docx", ".odt", ".rtf", ".txt", ".xls", ".xlsx", ".xlsm", ".ods", ".csv", ".ppt", ".pptx", ".odp", ".mpp",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".tif", ".tiff", ".bmp",
    ".zip", ".7z", ".rar", ".msg", ".eml",
}


def _maitrise_oeuvre(acteur: Acteur) -> bool:
    return acteur.cabinet or acteur.profil == "MOE_EXTERNE"


def journaliser(espace: EspaceChantier, type_: str, description: str, acteur: Acteur | None = None, *, document=None, version=None, notifier=False) -> Evenement:
    evenement = Evenement.objects.create(
        espace=espace, type=type_, description=description[:1000], document=document, version=version,
        intervenant=acteur.intervenant if acteur else None, acteur=(acteur.nom if acteur else "Application")[:255],
        a_notifier=notifier and espace.notifications,
    )
    if evenement.a_notifier:
        from .tasks import planifier_notifications

        planifier_notifications(espace.pk)
    return evenement


def verifier_ouvert(espace: EspaceChantier) -> None:
    if espace.statut != StatutEspace.OUVERT:
        raise HttpError(409, "L'espace de ce chantier est clos.")


def verifier_fichier(fichier) -> str:
    extension = Path(fichier.name or "").suffix.lower()
    if extension not in EXTENSIONS:
        raise HttpError(400, f"Format « {extension or 'inconnu'} » refusé. Formats acceptés : {', '.join(sorted(EXTENSIONS))}.")
    if fichier.size > settings.TAILLE_MAX_FICHIER_MO * 1024 * 1024:
        raise HttpError(400, f"Fichier trop volumineux (maximum {settings.TAILLE_MAX_FICHIER_MO} Mo).")
    return extension


def _empreinte(fichier) -> str:
    somme = hashlib.sha256()
    for morceau in fichier.chunks():
        somme.update(morceau)
    fichier.seek(0)
    return somme.hexdigest()


def reference_proposee(espace: EspaceChantier, zone: str, lot, categorie: str) -> str:
    prefixe = lot.code if zone == Zone.LOT and lot is not None else ("MOE" if zone == Zone.MOE else "COM")
    base = f"{prefixe}-{SIGLES_CATEGORIES.get(categorie, 'DOC')}-"
    numeros = [int(r[len(base):]) for r in Document.objects.filter(espace=espace, reference__startswith=base).values_list("reference", flat=True) if r[len(base):].isdigit()]
    return f"{base}{(max(numeros) + 1) if numeros else 1:03d}"


def _indice_initial(indice: str | None) -> str:
    indice = normaliser_indice(indice or "") or "A"
    if not indice_valide(indice):
        raise HttpError(400, "Indice invalide : une à trois lettres (A, B… AA) ou un nombre (0, 1, 2…).")
    return indice


def deposer(acteur: Acteur, espace: EspaceChantier, *, zone: str, lot, categorie: str, titre: str, fichier, reference: str = "",
            indice: str = "", objet: str = "", visa_requis: bool | None = None) -> tuple[Document, Version]:
    verifier_ouvert(espace)
    if zone == Zone.LOT and lot is None:
        raise HttpError(400, "Indiquez le lot du document.")
    if zone != Zone.LOT:
        lot = None
    if not peut_deposer(acteur, zone, lot.pk if lot else None):
        raise HttpError(403, "Vous ne pouvez pas déposer de document à cet endroit.")
    if categorie not in Categorie.values:
        raise HttpError(400, "Catégorie inconnue.")
    verifier_fichier(fichier)
    titre = (titre or Path(fichier.name or "document").stem).strip()[:255]
    indice = _indice_initial(indice)
    if _maitrise_oeuvre(acteur):
        visa_requis = bool(visa_requis)
    else:
        # Plans, documents d'exécution, fiches et notes d'une entreprise : soumis au visa.
        visa_requis = categorie in CATEGORIES_A_VISER
    for _essai in range(3):
        reference_finale = (reference or "").strip()[:60] or reference_proposee(espace, zone, lot, categorie)
        try:
            with transaction.atomic():
                document = Document.objects.create(
                    espace=espace, zone=zone, lot=lot, categorie=categorie, reference=reference_finale, titre=titre,
                    auteur_intervenant=acteur.intervenant, auteur_utilisateur=acteur.utilisateur, auteur_nom=acteur.nom[:255],
                )
                version = _creer_version(acteur, document, fichier, indice, objet, visa_requis)
                journaliser(espace, TypeEvenement.DEPOT, f"{document.reference} – {document.titre} (indice {indice})", acteur, document=document, version=version, notifier=True)
            return document, version
        except IntegrityError:
            if reference:
                raise HttpError(409, f"La référence « {reference_finale} » existe déjà dans cet espace.") from None
    raise HttpError(409, "Référence déjà utilisée : réessayez.")


def _creer_version(acteur: Acteur, document: Document, fichier, indice: str, objet: str, visa_requis: bool) -> Version:
    version = Version(
        document=document, indice=indice, nom_original=(fichier.name or "document")[:255], taille=fichier.size, empreinte=_empreinte(fichier),
        objet=(objet or "").strip()[:500], deposee_par_intervenant=acteur.intervenant, deposee_par_utilisateur=acteur.utilisateur,
        deposee_par_nom=acteur.nom[:255], visa=StatutVisa.EN_ATTENTE if visa_requis else StatutVisa.SANS_OBJET,
    )
    version.fichier.save(fichier.name or "document", fichier, save=False)
    version.save()
    return version


def derniere_version(document: Document) -> Version | None:
    return document.versions.order_by("-deposee_le", "-id").first()


def nouvel_indice(acteur: Acteur, document: Document, *, fichier, indice: str = "", objet: str = "", visa_requis: bool | None = None) -> Version:
    verifier_ouvert(document.espace)
    if not peut_ajouter_indice(acteur, document):
        raise HttpError(403, "Vous ne pouvez pas ajouter d'indice à ce document.")
    verifier_fichier(fichier)
    with transaction.atomic():
        document = Document.objects.select_for_update().get(pk=document.pk)  # deux dépôts simultanés : indices distincts
        precedente = derniere_version(document)
        indice = normaliser_indice(indice) or indice_suivant(precedente.indice if precedente else None)
        if not indice_valide(indice):
            raise HttpError(400, "Indice invalide : une à trois lettres (A, B… AA) ou un nombre (0, 1, 2…).")
        if precedente is not None and not superieur(indice, precedente.indice):
            raise HttpError(400, f"L'indice doit suivre l'indice {precedente.indice} (par exemple {indice_suivant(precedente.indice)}).")
        if visa_requis is None or not _maitrise_oeuvre(acteur):
            # Un document soumis au visa le reste à chaque nouvel indice.
            visa_requis = (precedente is not None and precedente.visa != StatutVisa.SANS_OBJET) or (
                not _maitrise_oeuvre(acteur) and document.categorie in CATEGORIES_A_VISER
            )
        version = _creer_version(acteur, document, fichier, indice, objet, visa_requis)
        journaliser(document.espace, TypeEvenement.INDICE, f"{document.reference} – {document.titre} : indice {indice}" + (f" ({version.objet})" if version.objet else ""), acteur, document=document, version=version, notifier=True)
    return version


def viser(acteur: Acteur, version: Version, *, statut: str, commentaire: str = "", fichier=None) -> Version:
    document = version.document
    verifier_ouvert(document.espace)
    if not peut_viser(acteur):
        raise HttpError(403, "Seule la maîtrise d'œuvre peut viser un document.")
    if statut not in StatutVisa.values:
        raise HttpError(400, "Avis de visa inconnu.")
    if fichier is not None:
        verifier_fichier(fichier)
    with transaction.atomic():
        version = Version.objects.select_for_update().get(pk=version.pk)
        version.visa, version.visa_commentaire = statut, (commentaire or "").strip()[:4000]
        version.vise_par_nom, version.vise_le = acteur.nom[:255], timezone.now()
        if fichier is not None:
            if version.visa_fichier:
                version.visa_fichier.delete(save=False)
            version.visa_nom_original = (fichier.name or "visa")[:255]
            version.visa_fichier.save(fichier.name or "visa", fichier, save=False)
        version.save()
        libelle = StatutVisa(statut).label
        journaliser(document.espace, TypeEvenement.VISA, f"{document.reference} indice {version.indice} : {libelle}" + (f" – {version.visa_commentaire[:300]}" if version.visa_commentaire else ""), acteur, document=document, version=version, notifier=statut != StatutVisa.EN_ATTENTE)
    return version


def annuler(acteur: Acteur, document: Document, motif: str) -> Document:
    verifier_ouvert(document.espace)
    if not acteur.cabinet:
        raise HttpError(403, "Seul le cabinet peut annuler un document.")
    document.annule, document.motif_annulation = True, (motif or "").strip()[:500]
    document.save(update_fields=["annule", "motif_annulation"])
    journaliser(document.espace, TypeEvenement.ANNULATION, f"{document.reference} – {document.titre} annulé" + (f" : {document.motif_annulation}" if document.motif_annulation else ""), acteur, document=document, notifier=True)
    return document


def retablir(acteur: Acteur, document: Document) -> Document:
    verifier_ouvert(document.espace)
    if not acteur.cabinet:
        raise HttpError(403, "Seul le cabinet peut rétablir un document.")
    document.annule, document.motif_annulation = False, ""
    document.save(update_fields=["annule", "motif_annulation"])
    journaliser(document.espace, TypeEvenement.MODIFICATION, f"{document.reference} – {document.titre} rétabli", acteur, document=document)
    return document
