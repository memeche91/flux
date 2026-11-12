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
# Sauvegarde planifiée, ou rattrapée au démarrage d'un PC éteint la nuit, alors que la base de données n'est pas
# encore prête : nouvel essai chaque minute pendant une demi-heure, plutôt que d'attendre la nuit suivante.
NOUVEAUX_ESSAIS = 30
DELAI_NOUVEL_ESSAI = 60


@shared_task(bind=True, time_limit=DUREE_SECONDES, soft_time_limit=DUREE_SECONDES - 120)
def sauvegarder(self, sauvegarde_id: int | None = None, declenchee_par: str = "planification") -> None:
    try:
        sauvegarde = lancer(declenchee_par, sauvegarde_id)
    except ErreurSauvegarde as exc:  # base injoignable : impossible même de poser le verrou
        requete = self.request
        if (sauvegarde_id is None and not requete.called_directly and not requete.is_eager
                and requete.retries < NOUVEAUX_ESSAIS):
            logger.warning("Sauvegarde planifiée reportée d'une minute (essai %s sur %s) : %s",
                           requete.retries + 1, NOUVEAUX_ESSAIS + 1, exc)
            raise self.retry(countdown=DELAI_NOUVEL_ESSAI, max_retries=NOUVEAUX_ESSAIS) from exc
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
