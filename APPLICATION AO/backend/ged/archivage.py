"""Clôture d'un projet : archive complète, vérifiée, puis purge différée des fichiers.

L'archive « Archive <projet> - <date>.zip » est écrite dans le dossier d'archives du cabinet
(DOSSIER_ARCHIVES, monté depuis le PC) et téléchargeable depuis l'application :

    Lisez-moi.txt
    01 Pieces ecrites/   RC, CCAP, actes d'engagement, CCTP, DPGF (Word et PDF)
    02 DCE/              dossiers .zip générés
    03 Offres/Lot 08/    offres reçues, rapport ACT (Word, PDF), comparatif Excel
    04 GED/Lot 08/EXE/08-EXE-003_C_VSO_Facade nord.pdf  (+ fiche de visa, sources)
           .../Indices anterieurs/…
           Registre des documents.xlsx (liens vers chaque fichier), Journal.csv (sans adresses IP)

Elle n'est « prête » qu'après vérification : relecture complète du .zip et contrôle du SHA-256
de chaque indice de la GED. La purge ne supprime que les fichiers (le projet, les prix reçus,
l'historique de l'annuaire et le registre de la GED restent) ; elle est programmée à 30 jours,
annulable, et exige que l'archive ait été téléchargée ou copiée hors du PC. Elle est refusée
(et annulée si elle était programmée) quand un fichier a été déposé ou modifié depuis l'archive,
ou quand une archive vérifiée plus récente existe.
"""
from __future__ import annotations

import csv
import datetime
import hashlib
import io
import logging
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from dce.assemblage import nom_lot, nom_sur
from projets.models import Projet

from .models import AvisVersion, Document, EspaceChantier, FichierSource, ProjetArchive, StatutArchive, StatutEspace, Version, Zone
from .serialisation import EN_VIGUEUR, LIBELLES_STATUTS, statuts_des_versions

logger = logging.getLogger(__name__)
LONGUEUR_CHEMIN_MAX = 150
DELAI_PURGE = datetime.timedelta(days=30)
DUREE_MAX_PREPARATION = datetime.timedelta(hours=4)  # au-delà, la tâche a été tuée : archive interrompue
INTERROMPUE = "Préparation interrompue (arrêt du PC ou de l'application) : relancez l'archive."


@dataclass
class Entree:
    chemin: str
    source: Path | None = None
    produire: object = None  # callable -> bytes
    empreinte: str = ""  # SHA-256 attendu (indices de la GED)


# --- Inventaire ---------------------------------------------------------------------------------

def _chemin(champ) -> Path | None:
    try:
        return Path(champ.path) if champ else None
    except (ValueError, NotImplementedError):
        return None


def fichiers_du_projet(projet: Projet) -> list[Path]:
    """Tous les fichiers stockés pour le projet (ce que la purge libère)."""
    from dce.models import DossierDCE, PieceJointe
    from offres.models import Offre

    chemins: list[Path | None] = []
    chemins += [_chemin(j.fichier) for j in PieceJointe.objects.filter(projet=projet)]
    chemins += [_chemin(d.fichier) for d in DossierDCE.objects.filter(projet=projet)]
    chemins += [_chemin(o.fichier) for o in Offre.objects.filter(projet=projet)]
    for v in Version.objects.filter(document__espace__projet=projet):
        chemins += [_chemin(v.fichier), _chemin(v.visa_fichier), _chemin(v.fiche_visa)]
    chemins += [_chemin(s.fichier) for s in FichierSource.objects.filter(version__document__espace__projet=projet)]
    chemins += [_chemin(a.fichier) for a in AvisVersion.objects.filter(version__document__espace__projet=projet)]
    return [c for c in chemins if c is not None and c.exists()]


def taille_projet(projet: Projet) -> int:
    return sum(c.stat().st_size for c in fichiers_du_projet(projet))


def espace_libre_archives() -> int:
    dossier = Path(settings.DOSSIER_ARCHIVES)
    dossier.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(dossier).free


# --- Plan de l'archive -----------------------------------------------------------------------------

def _court(texte: str, longueur: int = 40) -> str:
    return nom_sur(texte, longueur)


def _plan_pieces(projet: Projet) -> list[Entree]:
    from dce.assemblage import plan

    entrees = []
    for fichier in plan(projet, avec_word=True):
        if fichier.source is not None:
            continue  # documents joints : rangés dans « 02 DCE »
        entrees.append(Entree(f"01 Pieces ecrites/{fichier.chemin.split('/', 1)[-1]}", produire=fichier.produire))
    return entrees


def _plan_dce(projet: Projet) -> list[Entree]:
    from dce.models import DossierDCE, StatutDossier

    entrees = []
    for dossier in DossierDCE.objects.filter(projet=projet, statut=StatutDossier.PRET).select_related("entreprise"):
        source = _chemin(dossier.fichier)
        if source is not None and source.exists():
            entrees.append(Entree(f"02 DCE/{_court(dossier.nom or source.name, 70)}", source=source))
    from dce.models import PieceJointe

    for jointe in PieceJointe.objects.filter(projet=projet).select_related("lot"):
        source = _chemin(jointe.fichier)
        if source is not None and source.exists():
            dossier = nom_lot(jointe.lot) if jointe.lot else "Commun"
            entrees.append(Entree(f"02 DCE/Documents joints/{dossier}/{_court(jointe.nom_original, 60)}", source=source))
    return entrees


def _plan_offres(projet: Projet) -> list[Entree]:
    from offres.comparatif import comparatif_xlsx
    from offres.models import Offre
    from offres.rapport import document_rapport
    from projets.exports.cctp_docx import exporter_docx
    from projets.exports.pdf import exporter_pdf

    entrees = []
    offres = list(Offre.objects.filter(projet=projet).select_related("entreprise", "lot"))
    for offre in offres:
        source = _chemin(offre.fichier)
        if source is not None and source.exists():
            entrees.append(Entree(f"03 Offres/{nom_lot(offre.lot)}/{_court(offre.nom, 30)} - {_court(offre.nom_original, 50)}", source=source))
    if offres:
        lots = list(projet.lots.order_by("ordre", "code"))
        entrees += [
            Entree("03 Offres/Rapport d'analyse des offres (ACT).docx", produire=lambda: exporter_docx(document_rapport(projet))),
            Entree("03 Offres/Rapport d'analyse des offres (ACT).pdf", produire=lambda: exporter_pdf(document_rapport(projet))),
            Entree("03 Offres/Comparatif des offres.xlsx", produire=lambda: comparatif_xlsx(lots)),
        ]
    return entrees


def _dossier_document(document: Document) -> str:
    zone = nom_lot(document.lot) if document.zone == Zone.LOT and document.lot else ("MOE" if document.zone == Zone.MOE else "Commun")
    return f"04 GED/{zone}/{document.categorie}"


def _nom_version(document: Document, version: Version, longueur: int) -> str:
    extension = Path(version.nom_original).suffix.lower()
    visa = f"_{version.visa}" if version.visa in ("VSO", "VAO", "REF", "HM") else ""
    # Référence, indice et visa toujours entiers (noms distincts) : seul le titre est raccourci.
    prefixe = nom_sur(f"{document.reference}_{version.indice}{visa}", 60)
    reste = max(0, longueur - len(prefixe) - 1)
    return f"{prefixe}{f'_{_court(document.titre, reste)}' if reste >= 4 else ''}{extension}"


def _plan_ged(projet: Projet, longueur: int) -> tuple[list[Entree], list[dict]]:
    """Entrées de la GED et lignes du registre (avec le chemin de chaque fichier dans l'archive)."""
    espace = EspaceChantier.objects.filter(projet=projet).first()
    if espace is None:
        return [], []
    entrees, registre = [], []
    documents = Document.objects.filter(espace=espace).select_related("lot").prefetch_related("versions__sources", "versions__avis")
    for document in documents:
        versions = sorted(document.versions.all(), key=lambda v: (v.deposee_le, v.pk), reverse=True)
        statuts = statuts_des_versions(versions)
        base = _dossier_document(document)
        for v in versions:
            dossier = base if statuts[v.pk] == EN_VIGUEUR or v is versions[0] else f"{base}/Indices anterieurs"
            nom = _nom_version(document, v, longueur)
            chemin = f"{dossier}/{nom}"
            source = _chemin(v.fichier)
            entree = None
            if source is not None and source.exists():
                entree = Entree(chemin, source=source, empreinte=v.empreinte)
                entrees.append(entree)
            for champ, suffixe in ((v.fiche_visa, "fiche de visa.pdf"), (v.visa_fichier, f"annote{Path(v.visa_nom_original).suffix.lower()}")):
                annexe = _chemin(champ)
                if annexe is not None and annexe.exists():
                    entrees.append(Entree(f"{dossier}/{Path(nom).stem} - {suffixe}", source=annexe))
            for s in v.sources.all():
                fichier_source = _chemin(s.fichier)
                if fichier_source is not None and fichier_source.exists():
                    entrees.append(Entree(f"{dossier}/{Path(nom).stem}{Path(s.nom_original).suffix.lower()}", source=fichier_source, empreinte=s.empreinte))
            for a in v.avis.all():
                fichier_avis = _chemin(a.fichier)
                if fichier_avis is not None and fichier_avis.exists():
                    entrees.append(Entree(f"{dossier}/{Path(nom).stem} - avis {a.role}{Path(a.nom_original).suffix.lower()}", source=fichier_avis))
            # L'entrée (et non son chemin) : le chemin est lu après la numérotation des doublons.
            registre.append({"document": document, "version": v, "statut": statuts[v.pk], "entree": entree})
    return entrees, registre


def _registre_xlsx(projet: Projet, registre: list[dict]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    classeur = Workbook()
    feuille = classeur.active
    feuille.title = "Registre"
    feuille.append([f"{projet.nom} – registre des documents du chantier (archive du {timezone.localdate():%d/%m/%Y})"])
    feuille["A1"].font = Font(bold=True, size=13)
    feuille.append([])
    feuille.append(["Zone", "Lot", "Catégorie", "Référence", "N° émetteur", "Titre", "Indice", "Déposé le", "Déposé par", "Objet",
                    "Visa", "Visé le", "Observations du visa", "État", "Fichier dans l'archive"])
    for cellule in feuille[3]:
        cellule.font = Font(bold=True)
    for ligne in registre:
        d, v = ligne["document"], ligne["version"]
        chemin = ligne["entree"].chemin if ligne["entree"] is not None else ""
        feuille.append([
            d.get_zone_display(), d.lot.code if d.lot else "", d.get_categorie_display(), d.reference, d.reference_emetteur, d.titre, v.indice,
            timezone.localtime(v.deposee_le).strftime("%d/%m/%Y %H:%M"), v.deposee_par_nom, v.objet, v.get_visa_display() if v.visa else "",
            timezone.localtime(v.vise_le).strftime("%d/%m/%Y") if v.vise_le else "", v.visa_commentaire,
            "Annulé" if d.annule else LIBELLES_STATUTS[ligne["statut"]], chemin or "(fichier absent)",
        ])
        for cellule in feuille[feuille.max_row]:
            if cellule.data_type == "f":
                cellule.data_type = "s"  # « =… » saisi par un intervenant : texte, jamais une formule
        if chemin:
            cellule = feuille.cell(feuille.max_row, 15)
            cellule.hyperlink = "../" + chemin  # le registre est dans « 04 GED »
            cellule.font = Font(color="1F4E8C", underline="single")
    for colonne, largeur in zip("ABCDEFGHIJKLMNO", (12, 6, 26, 15, 16, 40, 7, 16, 24, 30, 22, 11, 40, 16, 60)):
        feuille.column_dimensions[colonne].width = largeur
    flux = io.BytesIO()
    classeur.save(flux)
    return flux.getvalue()


def _journal_csv(projet: Projet) -> bytes:
    """Journal complet de la GED, sans adresses IP (données personnelles, archive conservée 10 ans)."""
    espace = EspaceChantier.objects.filter(projet=projet).first()
    flux = io.StringIO()
    ecriture = csv.writer(flux, delimiter=";")
    ecriture.writerow(["Date", "Type", "Acteur", "Description"])
    if espace is not None:
        for e in espace.evenements.order_by("date", "id"):
            ecriture.writerow([timezone.localtime(e.date).strftime("%d/%m/%Y %H:%M:%S"), e.get_type_display(), e.acteur, e.description])
    return ("﻿" + flux.getvalue()).encode("utf-8")


def _lisez_moi(projet: Projet, archive: ProjetArchive) -> bytes:
    lignes = [
        f"ARCHIVE DU PROJET « {projet.nom} »" + (f" (n° {projet.numero})" if projet.numero else ""),
        f"Produite le {timezone.localtime():%d/%m/%Y à %H:%M} par D’Aplomb.",
        "",
        "01 Pieces ecrites : RC, CCAP, actes d'engagement, CCTP et DPGF (Word et PDF).",
        "02 DCE : dossiers de consultation générés et documents joints.",
        "03 Offres : offres reçues, rapport d'analyse des offres (ACT), comparatif Excel.",
        "04 GED : documents du chantier par zone, lot et catégorie ; l'indice à utiliser est à la racine",
        "         de chaque catégorie, les indices antérieurs dans « Indices anterieurs ».",
        "         « Registre des documents.xlsx » liste tous les indices, visas et dates, avec un lien vers chaque fichier.",
        "         « Journal.csv » retrace toutes les opérations (sans adresses IP).",
        "",
    ]
    if archive.date_reception:
        lignes.append(f"Réception des travaux : {archive.date_reception:%d/%m/%Y}.")
    if archive.conserver_jusqu_au:
        lignes.append(f"À conserver au moins jusqu'au {archive.conserver_jusqu_au:%d/%m/%Y} (responsabilité décennale, art. 1792-4-1 du code civil).")
    lignes += ["", "Conservez une copie de cette archive hors du PC qui héberge l'application (serveur du cabinet, disque externe)."]
    return "\r\n".join(lignes).encode("utf-8")


def _plan(projet: Projet, archive: ProjetArchive) -> list[Entree]:
    entrees = [Entree("Lisez-moi.txt", produire=lambda: _lisez_moi(projet, archive))]
    entrees += _plan_pieces(projet) + _plan_dce(projet) + _plan_offres(projet)
    racine = len(f"Archive {nom_sur(projet.nom, 40)} - 0000-00-00/")
    for longueur in (40, 30, 22, 16):
        ged, registre = _plan_ged(projet, longueur)
        if max((racine + len(e.chemin) for e in ged), default=0) <= LONGUEUR_CHEMIN_MAX:
            break
    entrees += ged
    if registre:
        entrees += [
            Entree("04 GED/Registre des documents.xlsx", produire=lambda: _registre_xlsx(projet, registre)),
            Entree("04 GED/Journal.csv", produire=lambda: _journal_csv(projet)),
        ]
    # Noms en double (même titre…) : suffixe numéroté.
    vus: dict[str, int] = {}
    for entree in entrees:
        cle = entree.chemin.lower()
        if cle in vus:
            vus[cle] += 1
            chemin = Path(entree.chemin)
            entree.chemin = f"{chemin.parent.as_posix()}/{chemin.stem} ({vus[cle]}){chemin.suffix}"
        else:
            vus[cle] = 1
    return entrees


# --- Production et vérification ---------------------------------------------------------------------

def _sha256_fichier(chemin: Path) -> str:
    somme = hashlib.sha256()
    with chemin.open("rb") as flux:
        for morceau in iter(lambda: flux.read(1024 * 1024), b""):
            somme.update(morceau)
    return somme.hexdigest()


def _verifier(destination: Path, entrees: list[Entree]) -> None:
    with zipfile.ZipFile(destination) as archive:
        mauvais = archive.testzip()
        if mauvais is not None:
            raise ValueError(f"fichier illisible dans l'archive : {mauvais}")
        noms = set(archive.namelist())
        manquants = [e.chemin for e in entrees if e.chemin not in noms]
        if manquants:
            raise ValueError(f"{len(manquants)} fichier(s) absent(s) de l'archive")
        for entree in entrees:
            if entree.empreinte:
                somme = hashlib.sha256()
                with archive.open(entree.chemin) as flux:
                    for morceau in iter(lambda: flux.read(1024 * 1024), b""):
                        somme.update(morceau)
                if somme.hexdigest() != entree.empreinte:
                    raise ValueError(f"empreinte différente pour {entree.chemin} (fichier modifié sur le disque ?)")


def produire(archive: ProjetArchive) -> None:
    projet = archive.projet
    espace = EspaceChantier.objects.filter(projet=projet).first()
    if espace is not None and espace.date_reception:
        archive.date_reception = espace.date_reception
    debut_conservation = archive.date_reception or timezone.localdate()
    try:
        archive.conserver_jusqu_au = debut_conservation.replace(year=debut_conservation.year + 10)
    except ValueError:  # 29 février
        archive.conserver_jusqu_au = debut_conservation.replace(year=debut_conservation.year + 10, day=28)
    taille = taille_projet(projet)
    if espace_libre_archives() < 1.2 * taille + 50 * 1024 * 1024:
        raise ValueError("espace libre insuffisant dans le dossier d'archives")
    entrees = _plan(projet, archive)
    dossier = Path(settings.DOSSIER_ARCHIVES)
    nom = f"Archive {nom_sur(projet.nom, 40)} - {timezone.localdate():%Y-%m-%d}.zip"
    destination = dossier / nom
    rang = 2
    while destination.exists():
        destination = dossier / f"{Path(nom).stem} ({rang}).zip"
        rang += 1
    temporaire = destination.with_suffix(".zip.partiel")
    try:
        with zipfile.ZipFile(temporaire, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zip_archive:
            for entree in entrees:
                if entree.source is not None:
                    zip_archive.write(entree.source, entree.chemin)
                else:
                    zip_archive.writestr(entree.chemin, entree.produire())
        _verifier(temporaire, entrees)
        temporaire.replace(destination)
    except Exception:
        temporaire.unlink(missing_ok=True)
        raise
    archive.nom_fichier = destination.name
    archive.taille = destination.stat().st_size
    archive.empreinte = _sha256_fichier(destination)
    archive.nb_fichiers = len(entrees)
    archive.statut = StatutArchive.VERIFIEE
    archive.terminee_le = timezone.now()
    archive.message = ""
    archive.save()


@shared_task(time_limit=int(DUREE_MAX_PREPARATION.total_seconds()), soft_time_limit=int(DUREE_MAX_PREPARATION.total_seconds()) - 60)
def produire_archive(archive_id: int) -> None:
    archive = ProjetArchive.objects.select_related("projet").filter(pk=archive_id, statut=StatutArchive.EN_COURS).first()
    if archive is None or archive.projet is None:
        return
    try:
        produire(archive)
    except Exception as erreur:  # noqa: BLE001
        logger.exception("Archive %s non produite", archive_id)
        ProjetArchive.objects.filter(pk=archive_id).update(statut=StatutArchive.ERREUR, message=f"Archive non produite : {erreur}"[:500])


def chemin_archive(archive: ProjetArchive) -> Path:
    return Path(settings.DOSSIER_ARCHIVES) / archive.nom_fichier


def liberer_archives_interrompues(age_minimum: datetime.timedelta | None = None) -> None:
    """Archives restées « en préparation » alors que leur tâche est perdue (worker arrêté ou tué) :
    passées en erreur, et leur .zip.partiel effacé. Sans âge minimum : toutes (démarrage du worker)."""
    archives = ProjetArchive.objects.filter(statut=StatutArchive.EN_COURS)
    limite = timezone.now() - age_minimum if age_minimum is not None else None
    if limite is not None:
        archives = archives.filter(cree_le__lt=limite)
    archives.update(statut=StatutArchive.ERREUR, message=INTERROMPUE)
    for partiel in Path(settings.DOSSIER_ARCHIVES).glob("*.zip.partiel"):
        try:
            # Une archive en cours écrit sans cesse son .zip.partiel : seul un fichier ancien est abandonné.
            if limite is None or partiel.stat().st_mtime < limite.timestamp():
                partiel.unlink(missing_ok=True)
        except OSError:
            logger.warning("Fichier %s non supprimé", partiel, exc_info=True)


# --- Purge ---------------------------------------------------------------------------------------------

def motif_refus_purge(archive: ProjetArchive) -> str:
    """Purge refusée si un fichier a été ajouté ou modifié depuis l'archive (il n'est dans aucun .zip)
    ou si une archive vérifiée plus récente existe ; renvoie le motif, ou "" si la purge est possible."""
    from dce.models import DossierDCE, PieceJointe
    from offres.models import Offre

    projet, depuis = archive.projet, archive.cree_le
    if ProjetArchive.objects.filter(projet=projet, statut=StatutArchive.VERIFIEE, cree_le__gt=depuis).exists():
        return "Une archive plus récente existe : programmez la purge depuis celle-ci."
    nouveau = (
        Version.objects.filter(document__espace__projet=projet).filter(Q(deposee_le__gt=depuis) | Q(vise_le__gt=depuis)).exists()
        or AvisVersion.objects.filter(version__document__espace__projet=projet, date__gt=depuis).exists()
        or Offre.objects.filter(projet=projet, modifie_le__gt=depuis).exists()
        or PieceJointe.objects.filter(projet=projet, ajoute_le__gt=depuis).exists()
        or DossierDCE.objects.filter(projet=projet, cree_le__gt=depuis).exists()
    )
    return "Nouveaux documents depuis l'archive : refaites une archive avant de purger." if nouveau else ""


def purger(archive: ProjetArchive) -> int:
    """Supprime les fichiers du projet (pas ses données) ; renvoie le nombre d'octets libérés."""
    from dce.models import DossierDCE, PieceJointe
    from offres.models import Offre

    projet = archive.projet
    if projet is None:
        return 0
    motif = motif_refus_purge(archive)
    if motif:
        # Purge annulée : les documents récents seraient perdus (ou l'archive n'est pas la dernière).
        ProjetArchive.objects.filter(pk=archive.pk).update(purge_prevue_le=None, message=motif)
        archive.purge_prevue_le, archive.message = None, motif
        logger.warning("Purge de l'archive %s refusée : %s", archive.pk, motif)
        return 0
    octets = taille_projet(projet)
    noms: list[tuple] = []

    def noter(champ):
        if champ and champ.name:
            noms.append((champ.storage, champ.name))

    with transaction.atomic():
        for v in Version.objects.filter(document__espace__projet=projet):
            for champ in (v.fichier, v.visa_fichier, v.fiche_visa):
                noter(champ)
        Version.objects.filter(document__espace__projet=projet).update(fichier="", visa_fichier="", fiche_visa="")
        for s in FichierSource.objects.filter(version__document__espace__projet=projet):
            noter(s.fichier)
        FichierSource.objects.filter(version__document__espace__projet=projet).delete()
        for a in AvisVersion.objects.filter(version__document__espace__projet=projet):
            noter(a.fichier)
        AvisVersion.objects.filter(version__document__espace__projet=projet).update(fichier="")
        for o in Offre.objects.filter(projet=projet):
            noter(o.fichier)
        Offre.objects.filter(projet=projet).update(fichier="")
        for j in PieceJointe.objects.filter(projet=projet):
            noter(j.fichier)
        for d in DossierDCE.objects.filter(projet=projet):
            noter(d.fichier)
        # Les fiches supprimées ci-dessous n'ont plus de fichier à effacer par les signaux.
        PieceJointe.objects.filter(projet=projet).update(fichier="")
        DossierDCE.objects.filter(projet=projet).update(fichier="")
        PieceJointe.objects.filter(projet=projet).delete()
        DossierDCE.objects.filter(projet=projet).delete()
        espace = EspaceChantier.objects.filter(projet=projet).first()
        if espace is not None:
            espace.statut = StatutEspace.CLOS
            espace.save(update_fields=["statut"])
            espace.intervenants.update(actif=False)
        archive.fichiers_purges_le = timezone.now()
        archive.purge_prevue_le = None
        archive.octets_liberes = octets
        archive.save(update_fields=["fichiers_purges_le", "purge_prevue_le", "octets_liberes"])
        transaction.on_commit(lambda: [stockage.delete(nom) for stockage, nom in noms])
    return octets


@shared_task
def purges_programmees() -> None:
    for archive in ProjetArchive.objects.filter(purge_prevue_le__lte=timezone.now(), fichiers_purges_le__isnull=True, statut=StatutArchive.VERIFIEE).select_related("projet"):
        if archive.projet is None or not (archive.telechargee_le or archive.copie_confirmee_le) or not chemin_archive(archive).exists():
            continue
        try:
            purger(archive)
        except Exception:  # noqa: BLE001
            logger.exception("Purge de l'archive %s impossible", archive.pk)


def bilan_projet(projet: Projet) -> dict:
    """Ce que la purge libère et ce que la suppression totale ferait perdre."""
    from dce.models import ConsultationEntreprise
    from offres.models import LigneOffre, Offre

    return {
        "octets": taille_projet(projet),
        "offres": Offre.objects.filter(projet=projet).count(),
        "prix_recus": LigneOffre.objects.filter(offre__projet=projet).exclude(prix_unitaire=None).count(),
        "entreprises": Offre.objects.filter(projet=projet).values("entreprise").distinct().count(),
        "consultations": ConsultationEntreprise.objects.filter(projet=projet).count(),
        "documents_ged": Document.objects.filter(espace__projet=projet).count(),
        "indices_ged": Version.objects.filter(document__espace__projet=projet).count(),
    }
