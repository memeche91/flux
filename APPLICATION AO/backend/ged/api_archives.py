"""API de clôture : archives du projet, téléchargement, copie confirmée, purge programmée."""
from __future__ import annotations

import logging

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from projets.fichiers import reponse_fichier_sure
from projets.models import Projet

from .archivage import (
    DELAI_PURGE,
    DUREE_MAX_PREPARATION,
    bilan_projet,
    chemin_archive,
    espace_libre_archives,
    liberer_archives_interrompues,
    motif_refus_purge,
    produire_archive,
    purger,
)
from .models import ProjetArchive, StatutArchive

logger = logging.getLogger(__name__)
router = Router(tags=["Clôture et archives"])


class PurgeIn(Schema):
    maintenant: bool = False


def archive_out(a: ProjetArchive) -> dict:
    present = bool(a.nom_fichier) and chemin_archive(a).exists()
    return {
        "id": a.pk, "projet_id": a.projet_id, "nom_projet": a.nom_projet, "statut": a.statut, "statut_libelle": a.get_statut_display(),
        "message": a.message, "nom_fichier": a.nom_fichier, "taille": a.taille, "empreinte": a.empreinte, "nb_fichiers": a.nb_fichiers,
        "cree_le": a.cree_le, "terminee_le": a.terminee_le, "telechargee_le": a.telechargee_le, "copie_confirmee_le": a.copie_confirmee_le,
        "purge_prevue_le": a.purge_prevue_le, "fichiers_purges_le": a.fichiers_purges_le, "octets_liberes": a.octets_liberes,
        "date_reception": a.date_reception, "conserver_jusqu_au": a.conserver_jusqu_au, "fichier_present": present,
        "dossier": str(settings.DOSSIER_ARCHIVES_AFFICHE),
    }


@router.get("/projets/{projet_id}/archives")
def etat(request, projet_id: int):
    projet = get_object_or_404(Projet, pk=projet_id)
    liberer_archives_interrompues(DUREE_MAX_PREPARATION)  # sinon l'écran attend sans fin
    try:
        libre = espace_libre_archives()
    except OSError:
        libre = None
    return {
        "archives": [archive_out(a) for a in ProjetArchive.objects.filter(projet=projet)],
        "bilan": bilan_projet(projet), "espace_libre": libre, "delai_purge_jours": DELAI_PURGE.days,
        "est_administrateur": request.auth.est_administrateur,
    }


@router.post("/projets/{projet_id}/archives", response={201: dict})
def archiver(request, projet_id: int):
    from django.db import transaction

    projet = get_object_or_404(Projet, pk=projet_id)
    # Archive « en préparation » depuis plus longtemps que la tâche ne peut durer : elle a été interrompue.
    liberer_archives_interrompues(DUREE_MAX_PREPARATION)
    if ProjetArchive.objects.filter(projet=projet, statut=StatutArchive.EN_COURS).exists():
        raise HttpError(409, "Une archive est déjà en préparation.")
    archive = ProjetArchive.objects.create(projet=projet, nom_projet=projet.nom, numero_projet=projet.numero, demandee_par=request.auth)

    def lancer():
        try:
            produire_archive.delay(archive.pk)
        except Exception:  # noqa: BLE001 - service de tâches injoignable : l'archive ne reste pas bloquée
            logger.exception("Archive %s non mise en file", archive.pk)
            ProjetArchive.objects.filter(pk=archive.pk, statut=StatutArchive.EN_COURS).update(
                statut=StatutArchive.ERREUR, message="Préparation impossible (service de tâches indisponible) : relancez l'archive.")

    transaction.on_commit(lancer)
    return 201, archive_out(archive)


@router.get("/archives")
def toutes(request):
    """Toutes les archives, y compris celles des projets purgés."""
    return [archive_out(a) for a in ProjetArchive.objects.all()]


def _archive(archive_id: int) -> ProjetArchive:
    return get_object_or_404(ProjetArchive.objects.select_related("projet"), pk=archive_id)


@router.get("/archives/{archive_id}/telecharger")
def telecharger(request, archive_id: int):
    archive = _archive(archive_id)
    if archive.statut != StatutArchive.VERIFIEE or not chemin_archive(archive).exists():
        raise HttpError(404, "Archive indisponible.")

    class Champ:  # fichier hors du stockage des médias (dossier d'archives monté depuis le PC)
        def __init__(self, chemin):
            self.chemin = chemin

        def __bool__(self):
            return True

        def open(self, mode="rb"):
            return self.chemin.open(mode)

    ProjetArchive.objects.filter(pk=archive.pk).update(telechargee_le=timezone.now())
    return reponse_fichier_sure(Champ(chemin_archive(archive)), archive.nom_fichier, telecharger=True, type_impose="application/zip")


@router.post("/archives/{archive_id}/copie-confirmee")
def copie_confirmee(request, archive_id: int):
    archive = _archive(archive_id)
    if archive.statut != StatutArchive.VERIFIEE:
        raise HttpError(400, "L'archive n'est pas prête.")
    archive.copie_confirmee_le = timezone.now()
    archive.save(update_fields=["copie_confirmee_le"])
    return archive_out(archive)


@router.post("/archives/{archive_id}/purge")
def programmer_purge(request, archive_id: int, donnees: PurgeIn):
    archive = _archive(archive_id)
    if archive.projet is None or archive.fichiers_purges_le:
        raise HttpError(400, "Les fichiers de ce projet ont déjà été purgés.")
    if archive.statut != StatutArchive.VERIFIEE or not chemin_archive(archive).exists():
        raise HttpError(400, "Il faut d'abord une archive vérifiée, présente dans le dossier d'archives.")
    if not (archive.telechargee_le or archive.copie_confirmee_le):
        raise HttpError(400, "Téléchargez l'archive ou confirmez que vous l'avez copiée hors de ce PC avant de purger les fichiers.")
    motif = motif_refus_purge(archive)
    if motif:
        raise HttpError(409, motif)
    if donnees.maintenant:
        if not request.auth.est_administrateur:
            raise HttpError(403, "Seul un administrateur peut purger sans le délai de 30 jours.")
        purger(archive)
    else:
        archive.purge_prevue_le = timezone.now() + DELAI_PURGE
        archive.save(update_fields=["purge_prevue_le"])
    return archive_out(_archive(archive_id))


@router.delete("/archives/{archive_id}/purge")
def annuler_purge(request, archive_id: int):
    archive = _archive(archive_id)
    archive.purge_prevue_le = None
    archive.save(update_fields=["purge_prevue_le"])
    return archive_out(archive)


@router.delete("/archives/{archive_id}", response={204: None})
def supprimer(request, archive_id: int):
    """Supprime l'archive de l'application et du dossier d'archives (à faire après l'avoir copiée ailleurs)."""
    liberer_archives_interrompues(DUREE_MAX_PREPARATION)
    archive = _archive(archive_id)
    if archive.statut == StatutArchive.EN_COURS:
        raise HttpError(409, "Archive en préparation.")
    if archive.projet_id and archive.fichiers_purges_le:
        raise HttpError(409, "C'est la seule copie des fichiers purgés du projet : conservez-la.")
    if archive.nom_fichier:
        chemin_archive(archive).unlink(missing_ok=True)
    archive.delete()
    return 204, None
