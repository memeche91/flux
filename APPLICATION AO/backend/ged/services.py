"""Opérations de la GED : dépôt, nouvel indice, avis, visa, accusé de lecture, annulation, journal.

Toutes passent par ici, qu'elles viennent du cabinet ou du portail des intervenants, pour que
les droits, les indices, les échéances et le journal soient appliqués de la même façon.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone
from ninja.errors import HttpError

from .calendrier import echeance
from .categories import CONFIDENTIELLES, PAR_CODE
from .droits import (
    Acteur,
    categorie_valide,
    peut_accuser_lecture,
    peut_ajouter_indice,
    peut_deposer,
    peut_donner_avis,
    peut_viser,
    peut_voir,
    role_avis,
)
from .indices import cle, indice_suivant, indice_valide, normaliser_indice, superieur
from .models import (
    AccuseLecture,
    Avis,
    AvisVersion,
    Diffusion,
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
VISAS_EMIS = {StatutVisa.VSO, StatutVisa.VAO, StatutVisa.REF, StatutVisa.HM}
# Le Commun est lu par tous : une pièce chiffrée (OS, avenant, devis, situation, DC4) n'y a pas sa place.
MESSAGE_CONFIDENTIELLE_COMMUN = "Une pièce confidentielle (OS, avenant, devis, situation, sous-traitance) se classe dans le lot concerné, pas dans le Commun."


# --- Journal ---------------------------------------------------------------------------------

def journaliser(espace: EspaceChantier, type_: str, description: str, acteur: Acteur | None = None, *, document=None, version=None,
                notifier=False, depot: str = "") -> Evenement:
    evenement = Evenement.objects.create(
        espace=espace, type=type_, description=description[:1000], document=document, version=version,
        intervenant=acteur.intervenant if acteur else None, acces=acteur.acces if acteur else None,
        utilisateur=acteur.utilisateur if acteur else None, acteur=(acteur.nom if acteur else "Application")[:255],
        adresse_ip=(acteur.adresse_ip or None) if acteur else None, navigateur=acteur.navigateur if acteur else "",
        a_notifier=notifier and espace.notifications, depot=(depot or "")[:36],
    )
    if evenement.a_notifier:
        from .tasks import planifier_notifications

        planifier_notifications(espace.pk)
    return evenement


# --- Contrôles ---------------------------------------------------------------------------------

def verifier_actif(espace: EspaceChantier) -> None:
    if espace.statut == StatutEspace.CLOS:
        raise HttpError(409, "L'espace de ce chantier est clos.")


def verifier_fichier(fichier, espace: EspaceChantier | None = None) -> str:
    extension = Path(fichier.name or "").suffix.lower()
    if extension not in EXTENSIONS:
        raise HttpError(400, f"Format « {extension or 'inconnu'} » refusé. Formats acceptés : {', '.join(sorted(EXTENSIONS))}.")
    if fichier.size > settings.TAILLE_MAX_FICHIER_MO * 1024 * 1024:
        raise HttpError(400, f"Fichier trop volumineux (maximum {settings.TAILLE_MAX_FICHIER_MO} Mo).")
    if not fichier.size:
        raise HttpError(400, "Fichier vide.")
    if espace is not None:
        _verifier_place(espace, fichier.size)
    return extension


def _verifier_place(espace: EspaceChantier, taille: int) -> None:
    """Espace disque : un dépôt ne doit jamais remplir le disque du PC (PostgreSQL et Docker s'arrêteraient)."""
    import shutil

    try:
        libre = shutil.disk_usage(settings.MEDIA_ROOT).free
    except OSError:
        return
    if libre - taille < settings.GED_DISQUE_LIBRE_MIN_GO * 1024 ** 3:
        raise HttpError(507, "Espace disque insuffisant sur le serveur : contactez la maîtrise d'œuvre.")


def _empreinte(fichier) -> str:
    somme = hashlib.sha256()
    for morceau in fichier.chunks():
        somme.update(morceau)
    fichier.seek(0)
    return somme.hexdigest()


def reference_proposee(espace: EspaceChantier, zone: str, lot, categorie: str) -> str:
    prefixe = lot.code if zone == Zone.LOT and lot is not None else ("MOE" if zone == Zone.MOE else "COM")
    base = f"{prefixe}-{categorie}-"
    numeros = [int(r[len(base):]) for r in Document.objects.filter(espace=espace, reference__startswith=base).values_list("reference", flat=True) if r[len(base):].isdigit()]
    return f"{base}{(max(numeros) + 1) if numeros else 1:03d}"


def _verifier_indice(indice: str) -> str:
    if not indice_valide(indice):
        raise HttpError(400, "Indice invalide : une à trois lettres (A, B… AA) ou un nombre (0, 1, 2…).")
    return indice


def _diffusion(acteur: Acteur, categorie: str, demandee: str | None, precedente: Version | None = None) -> str:
    """Les documents techniques d'une entreprise sont toujours soumis au visa ; la maîtrise d'œuvre choisit."""
    if acteur.maitrise_oeuvre:
        if demandee in Diffusion.values:
            return demandee
        return precedente.diffusion if precedente is not None else Diffusion.POUR_INFO
    return Diffusion.POUR_VISA if PAR_CODE[categorie].visa else Diffusion.POUR_INFO


def _creer_version(acteur: Acteur, document: Document, fichier, indice: str, objet: str, diffusion: str, date_indice=None) -> Version:
    maintenant = timezone.now()
    somme = _empreinte(fichier)
    # Doublon cherché dans le même lot, la même zone et la même catégorie (le document lui-même compris) :
    # une même fiche fabricant reste déposable par un autre lot, ou en DOE après la FT.
    deja = Version.objects.filter(
        document__espace=document.espace, document__zone=document.zone, document__lot=document.lot, document__categorie=document.categorie, empreinte=somme,
    ).select_related("document__espace", "document__lot").first()
    if deja is not None:
        if not peut_voir(acteur, deja.document):
            raise HttpError(409, "Ce fichier est déjà présent dans l'espace : contactez la maîtrise d'œuvre.")
        raise HttpError(409, f"Ce fichier a déjà été déposé le {timezone.localtime(deja.deposee_le):%d/%m/%Y} ({deja.document.reference} indice {deja.indice}).")
    version = Version(
        document=document, indice=indice, date_indice=date_indice, nom_original=(fichier.name or "document")[:255], taille=fichier.size,
        empreinte=somme, objet=(objet or "").strip()[:500], deposee_par_intervenant=acteur.intervenant, deposee_par_acces=acteur.acces,
        deposee_par_utilisateur=acteur.utilisateur, deposee_par_nom=acteur.nom[:255], deposee_le=maintenant, diffusion=diffusion,
    )
    if diffusion == Diffusion.POUR_VISA:
        version.visa = StatutVisa.EN_ATTENTE
        version.echeance_visa = echeance(timezone.localdate(maintenant), document.espace.delai_visa_jours)
    version.fichier.save(fichier.name or "document", fichier, save=False)
    version.save()
    return version


def _ajouter_sources(version: Version, sources) -> None:
    """Fichiers sources joints à l'indice (DWG, IFC, XLSX…) : le fichier de référence reste celui visé."""
    from .models import FichierSource

    for source in sources or ():
        verifier_fichier(source, version.document.espace)
        objet = FichierSource(version=version, nom_original=(source.name or "source")[:255], taille=source.size, empreinte=_empreinte(source))
        objet.fichier.save(source.name or "source", source, save=False)
        objet.save()


def _verifier_reference_pdf(acteur: Acteur, categorie: str, fichier) -> None:
    if not acteur.maitrise_oeuvre and PAR_CODE[categorie].visa and Path(fichier.name or "").suffix.lower() != ".pdf":
        raise HttpError(400, "Un document soumis au visa se dépose en PDF ; joignez le DWG ou le fichier modifiable comme fichier source.")


def _recepisse(version: Version) -> None:
    if version.deposee_par_acces_id:
        from .tasks import envoyer_recepisse

        transaction.on_commit(lambda: envoyer_recepisse.delay(version.pk))


# --- Opérations -------------------------------------------------------------------------------

def deposer(acteur: Acteur, espace: EspaceChantier, *, zone: str, lot, categorie: str, titre: str, fichier, reference: str = "",
            reference_emetteur: str = "", indice: str = "", objet: str = "", diffusion: str | None = None, date_indice=None,
            depot: str = "", sources=()) -> tuple[Document, Version]:
    verifier_actif(espace)
    if not categorie_valide(categorie):
        raise HttpError(400, "Catégorie inconnue.")
    if zone == Zone.COMMUN and categorie in CONFIDENTIELLES:
        raise HttpError(400, MESSAGE_CONFIDENTIELLE_COMMUN)
    if zone == Zone.LOT and lot is None:
        raise HttpError(400, "Indiquez le lot du document.")
    if zone != Zone.LOT:
        lot = None
    if not peut_deposer(acteur, espace, zone, lot.pk if lot else None, categorie):
        raise HttpError(403, "Vous ne pouvez pas déposer ce type de document à cet endroit.")
    verifier_fichier(fichier, espace)
    for source in sources or ():
        verifier_fichier(source, espace)  # avant toute écriture : pas de fichier orphelin si une source est refusée
    _verifier_reference_pdf(acteur, categorie, fichier)
    titre = (titre or Path(fichier.name or "document").stem).strip()[:255]
    indice = _verifier_indice(normaliser_indice(indice or "") or "A")
    diffusion = _diffusion(acteur, categorie, diffusion)
    if not acteur.maitrise_oeuvre:
        # Référence attribuée par l'application (le n° du cartouche va dans « n° émetteur ») :
        # une entreprise ne peut ni réserver ni sonder les références des autres lots ou de la MOE.
        reference = ""
    for _essai in range(5):
        reference_finale = (reference or "").strip()[:60] or reference_proposee(espace, zone, lot, categorie)
        try:
            with transaction.atomic():
                document = Document.objects.create(
                    espace=espace, zone=zone, lot=lot, categorie=categorie, reference=reference_finale, titre=titre,
                    reference_emetteur=(reference_emetteur or "").strip()[:80],
                    auteur_intervenant=acteur.intervenant, auteur_utilisateur=acteur.utilisateur, auteur_nom=acteur.nom[:255],
                )
                version = _creer_version(acteur, document, fichier, indice, objet, diffusion, date_indice)
                _ajouter_sources(version, sources)
                journaliser(espace, TypeEvenement.DEPOT, f"{document.reference} – {document.titre} (indice {indice})", acteur, document=document, version=version, notifier=True, depot=depot)
                _recepisse(version)
            return document, version
        except IntegrityError:
            if reference:
                raise HttpError(409, f"La référence « {reference_finale} » existe déjà dans cet espace.") from None
    raise HttpError(409, "Référence déjà utilisée : réessayez.")


def derniere_version(document: Document) -> Version | None:
    return document.versions.order_by("-deposee_le", "-id").first()


def nouvel_indice(acteur: Acteur, document: Document, *, fichier, indice: str = "", objet: str = "", diffusion: str | None = None, date_indice=None,
                  depot: str = "", forcer: str = "", sources=()) -> Version:
    verifier_actif(document.espace)
    if not peut_ajouter_indice(acteur, document):
        raise HttpError(403, "Vous ne pouvez pas ajouter d'indice à ce document.")
    verifier_fichier(fichier, document.espace)
    for source in sources or ():
        verifier_fichier(source, document.espace)  # avant toute écriture : pas de fichier orphelin si une source est refusée
    _verifier_reference_pdf(acteur, document.categorie, fichier)
    with transaction.atomic():
        # FOR NO KEY UPDATE : sérialise les indices d'un même document sans bloquer les contrôles de clé
        # étrangère (FOR KEY SHARE) d'un visa en cours, ce qui évite l'interblocage sous PostgreSQL.
        document = Document.objects.select_for_update(of=("self",), no_key=True).select_related("espace__projet", "lot").get(pk=document.pk)  # indices distincts
        precedente = derniere_version(document)  # dernier dépôt : diffusion reprise
        # « Jamais en arrière » : par rapport au plus haut indice, pas au dernier dépôt (un indice forcé peut être inférieur).
        plus_haut = max(document.versions.all(), key=lambda v: cle(v.indice), default=None)
        indice = _verifier_indice(normaliser_indice(indice) or indice_suivant(plus_haut.indice if plus_haut else None))
        if document.versions.filter(indice=indice).exists():
            raise HttpError(400, f"L'indice {indice} existe déjà pour ce document.")
        if plus_haut is not None and not superieur(indice, plus_haut.indice):
            if not (acteur.cabinet and forcer.strip()):
                raise HttpError(400, f"L'indice doit suivre l'indice {plus_haut.indice} (par exemple {indice_suivant(plus_haut.indice)}).")
        version = _creer_version(acteur, document, fichier, indice, objet, _diffusion(acteur, document.categorie, diffusion, precedente), date_indice)
        if plus_haut is not None and not superieur(indice, plus_haut.indice):
            # Indice hors séquence accepté par le cabinet seulement, motif journalisé.
            version.indice_force = forcer.strip()[:300]
            version.save(update_fields=["indice_force"])
            journaliser(document.espace, TypeEvenement.MODIFICATION, f"{document.reference} : indice {indice} accepté hors séquence ({version.indice_force})", acteur, document=document, version=version)
        _ajouter_sources(version, sources)
        # L'indice précédent qui attendait encore son visa ne sera plus visé : remplacé avant visa.
        Version.objects.filter(document=document, visa=StatutVisa.EN_ATTENTE).exclude(pk=version.pk).update(visa=StatutVisa.REMPLACE)
        journaliser(document.espace, TypeEvenement.INDICE, f"{document.reference} – {document.titre} : indice {indice}" + (f" ({version.objet})" if version.objet else ""), acteur, document=document, version=version, notifier=True, depot=depot)
        _recepisse(version)
    return version


def donner_avis(acteur: Acteur, version: Version, *, avis: str, observations: str = "", fichier=None) -> AvisVersion:
    verifier_actif(version.document.espace)
    if not peut_donner_avis(acteur, version):
        raise HttpError(403, "Vous ne pouvez pas donner d'avis sur cet indice (il n'est pas, ou plus, en attente de visa).")
    if avis not in Avis.values:
        raise HttpError(400, "Avis inconnu.")
    avis_version = AvisVersion(
        version=version, role=role_avis(acteur), avis=avis, observations=(observations or "").strip()[:4000],
        intervenant=acteur.intervenant, acces=acteur.acces, auteur_nom=acteur.nom[:255],
    )
    if fichier is not None:
        verifier_fichier(fichier, version.document.espace)
        avis_version.nom_original = (fichier.name or "avis")[:255]
        avis_version.fichier.save(fichier.name or "avis", fichier, save=False)
    avis_version.save()
    document = version.document
    journaliser(document.espace, TypeEvenement.AVIS, f"{document.reference} indice {version.indice} : avis {avis_version.get_role_display().lower()} – {avis_version.get_avis_display().lower()}", acteur, document=document, version=version, notifier=True)
    return avis_version


def viser(acteur: Acteur, version: Version, *, statut: str, commentaire: str = "", fichier=None, nouvel_indice_attendu: bool | None = None) -> Version:
    document = version.document
    verifier_actif(document.espace)
    if not peut_viser(acteur):
        raise HttpError(403, "Le visa est émis par la maîtrise d'œuvre du cabinet.")
    if statut not in VISAS_EMIS:
        raise HttpError(400, "Avis de visa inconnu : VSO, VAO, REF ou HM.")
    if version.diffusion != Diffusion.POUR_VISA:
        raise HttpError(400, "Cet indice n'a pas été transmis pour visa.")
    if version.visa == StatutVisa.REMPLACE:
        raise HttpError(400, "Cet indice a été remplacé par un indice plus récent : visez le dernier.")
    if fichier is not None:
        verifier_fichier(fichier, document.espace)
    with transaction.atomic():
        version = Version.objects.select_for_update(of=("self",)).select_related("document__espace__projet", "document__lot").get(pk=version.pk)
        if version.visa != StatutVisa.EN_ATTENTE:
            # Visé ou remplacé entre l'ouverture du formulaire et l'envoi : le premier visa fait foi.
            raise HttpError(409, "Cet indice a déjà été visé ou remplacé : rechargez la page.")
        version.visa, version.visa_commentaire = statut, (commentaire or "").strip()[:4000]
        version.vise_par_nom, version.vise_le = acteur.nom[:255], timezone.now()
        version.nouvel_indice_attendu = True if statut == StatutVisa.REF else (statut == StatutVisa.VAO if nouvel_indice_attendu is None else nouvel_indice_attendu)
        contenu = fiche_visa_pdf(version)  # avant toute suppression : un échec ne fait rien perdre
        if fichier is not None:
            if version.visa_fichier:
                version.visa_fichier.delete(save=False)
            version.visa_nom_original = (fichier.name or "visa")[:255]
            version.visa_fichier.save(fichier.name or "visa", fichier, save=False)
        if version.fiche_visa:
            version.fiche_visa.delete(save=False)
        version.fiche_visa.save(f"Fiche de visa {document.reference} indice {version.indice}.pdf", ContentFile(contenu), save=False)
        version.save()
        libelle = StatutVisa(statut).label
        journaliser(document.espace, TypeEvenement.VISA, f"{document.reference} indice {version.indice} : {libelle}" + (f" – {version.visa_commentaire[:300]}" if version.visa_commentaire else ""), acteur, document=document, version=version, notifier=True)
    return version


def accuser_lecture(acteur: Acteur, version: Version) -> AccuseLecture:
    if not peut_accuser_lecture(acteur, version):
        raise HttpError(403, "Aucun accusé de lecture n'est demandé pour ce document.")
    accuse, cree = AccuseLecture.objects.get_or_create(version=version, intervenant=acteur.intervenant, defaults={"acces": acteur.acces, "nom_declare": acteur.nom[:255]})
    if cree:
        document = version.document
        journaliser(document.espace, TypeEvenement.LECTURE, f"{document.reference} indice {version.indice} : pris connaissance", acteur, document=document, version=version, notifier=True)
    return accuse


def annuler(acteur: Acteur, document: Document, motif: str) -> Document:
    verifier_actif(document.espace)
    if not acteur.cabinet:
        raise HttpError(403, "Seul le cabinet peut annuler un document.")
    document.annule, document.motif_annulation = True, (motif or "").strip()[:500]
    document.save(update_fields=["annule", "motif_annulation"])
    journaliser(document.espace, TypeEvenement.ANNULATION, f"{document.reference} – {document.titre} annulé" + (f" : {document.motif_annulation}" if document.motif_annulation else ""), acteur, document=document, notifier=True)
    return document


def retablir(acteur: Acteur, document: Document) -> Document:
    verifier_actif(document.espace)
    if not acteur.cabinet:
        raise HttpError(403, "Seul le cabinet peut rétablir un document.")
    document.annule, document.motif_annulation = False, ""
    document.save(update_fields=["annule", "motif_annulation"])
    journaliser(document.espace, TypeEvenement.MODIFICATION, f"{document.reference} – {document.titre} rétabli", acteur, document=document)
    return document


# --- Fiche de visa -----------------------------------------------------------------------------

def fiche_visa_pdf(version: Version) -> bytes:
    from django.template.loader import render_to_string
    from weasyprint import HTML

    from projets.exports.document import POLICES_PDF

    document = version.document
    projet = document.espace.projet
    contexte = {
        "projet": projet, "document": document, "version": version, "categorie": PAR_CODE[document.categorie].libelle,
        "observations": [l.strip() for l in version.visa_commentaire.splitlines() if l.strip()],
        "avis": list(version.avis.all()), "depose_le": timezone.localtime(version.deposee_le), "vise_le": timezone.localtime(version.vise_le),
        "police": POLICES_PDF.get(projet.police, POLICES_PDF["Arial"]), "couleur_titres": projet.couleur_titres, "couleur_tableaux": projet.couleur_tableaux,
    }
    return HTML(string=render_to_string("ged/fiche_visa.html", contexte)).write_pdf()
