"""Tâche de sauvegarde (planifiée chaque nuit à SAUVEGARDE_HEURE, ou demandée depuis l'application)."""
import logging

from celery import shared_task
from celery.signals import worker_ready
from django.utils import timezone

from .models import Sauvegarde, StatutSauvegarde
from .postgres import ErreurSauvegarde
from .services import DUREE_MAX, lancer, liberer_interrompues

logger = logging.getLogger(__name__)
DUREE_SECONDES = int(DUREE_MAX.total_seconds())


@shared_task(time_limit=DUREE_SECONDES, soft_time_limit=DUREE_SECONDES - 120)
def sauvegarder(sauvegarde_id: int | None = None, declenchee_par: str = "planification") -> None:
    try:
        sauvegarde = lancer(declenchee_par, sauvegarde_id)
    except ErreurSauvegarde as exc:  # base injoignable : impossible même de poser le verrou
        logger.error("Sauvegarde impossible : %s", exc)
        if sauvegarde_id is not None:
            try:
                Sauvegarde.objects.filter(pk=sauvegarde_id, statut=StatutSauvegarde.EN_COURS).update(
                    statut=StatutSauvegarde.ECHEC, fin=timezone.now(), message=f"Sauvegarde impossible : {exc}")
            except Exception:  # noqa: BLE001
                logger.exception("Sauvegarde %s non mise à jour", sauvegarde_id)
        return
    if sauvegarde is None:
        logger.info("Sauvegarde non lancée : une autre est déjà en cours ou attend son tour.")


@worker_ready.connect
def _sauvegardes_interrompues(sender=None, **_):
    """Au démarrage du worker, aucune sauvegarde ne peut tourner : celles « en cours » ont été interrompues."""
    if sender is not None and "voix@" in getattr(sender, "hostname", ""):
        return  # le worker « voix » ne fait pas de sauvegarde
    try:
        liberer_interrompues()
    except Exception:  # noqa: BLE001 - base pas encore prête
        logger.warning("Nettoyage des sauvegardes interrompues impossible au démarrage", exc_info=True)
