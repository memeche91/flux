"""API des sauvegardes : état (cabinet) et lancement immédiat (administrateur)."""
import logging

from django.db import transaction
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from .models import Sauvegarde, StatutSauvegarde
from .services import DUREE_MAX, etat, liberer_interrompues

logger = logging.getLogger(__name__)
router = Router(tags=["Sauvegardes"])


@router.get("/sauvegardes/etat")
def etat_sauvegardes(request):
    """Dernière sauvegarde, dernière réussie, destination et alerte éventuelle (MOE et administrateur)."""
    return etat()


@router.post("/sauvegardes", response={202: dict})
def lancer_sauvegarde(request):
    """Lance une sauvegarde maintenant (administrateur) ; sans effet si une sauvegarde est déjà en cours."""
    from .tasks import sauvegarder

    if not request.auth.est_administrateur:
        raise HttpError(403, "Seul l’administrateur peut lancer une sauvegarde.")
    liberer_interrompues(DUREE_MAX)
    with transaction.atomic():
        if Sauvegarde.objects.select_for_update().filter(statut=StatutSauvegarde.EN_COURS).exists():
            return 202, etat()
        nom = request.auth.get_full_name() or request.auth.get_username()
        sauvegarde = Sauvegarde.objects.create(declenchee_par=nom[:150])

    def mettre_en_file():
        try:
            sauvegarder.delay(sauvegarde.pk, nom)
        except Exception:  # noqa: BLE001 - service de tâches injoignable : la sauvegarde ne reste pas « en cours »
            logger.exception("Sauvegarde %s non mise en file", sauvegarde.pk)
            Sauvegarde.objects.filter(pk=sauvegarde.pk, statut=StatutSauvegarde.EN_COURS).update(
                statut=StatutSauvegarde.ECHEC, fin=timezone.now(),
                message="Sauvegarde non lancée : le service des tâches de fond ne répond pas. Redémarrez l’application puis réessayez.")

    transaction.on_commit(mettre_en_file)
    return 202, etat()
