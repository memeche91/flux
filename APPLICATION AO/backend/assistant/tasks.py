"""Indexation en tâche de fond (une seule à la fois ; relancée si des données arrivent entre-temps)."""
import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from . import ollama
from .indexation import calculer_plongements, synchroniser
from .models import EtatIndexation

logger = logging.getLogger(__name__)
DUREE_MAX = timedelta(hours=3)


def _prendre_la_main() -> bool:
    EtatIndexation.courant()
    with transaction.atomic():
        etat = EtatIndexation.objects.select_for_update().get(pk=1)
        perime = etat.debut is not None and timezone.now() - etat.debut > DUREE_MAX
        if etat.en_cours and not perime:
            etat.relancer = True
            etat.save(update_fields=["relancer"])
            return False
        etat.en_cours, etat.relancer = True, False
        etat.total = etat.faits = 0
        etat.message, etat.debut, etat.fin = "Préparation de l'index…", timezone.now(), None
        etat.save()
        return True


@shared_task
def indexer_assistant() -> None:
    if not _prendre_la_main():
        return
    while True:
        try:
            a_calculer = synchroniser()
            EtatIndexation.objects.filter(pk=1).update(total=len(a_calculer), faits=0, message="Lecture de vos documents par l'IA…")
            calculer_plongements(a_calculer, lambda faits: EtatIndexation.objects.filter(pk=1).update(faits=faits))
            message = "Index à jour."
        except ollama.OllamaIndisponible as erreur:
            message = f"Indexation interrompue : {erreur}"
        except Exception as erreur:  # noqa: BLE001
            logger.exception("Indexation de l'assistant impossible")
            message = f"Indexation interrompue ({erreur.__class__.__name__})."
        with transaction.atomic():
            etat = EtatIndexation.objects.select_for_update().get(pk=1)
            if etat.relancer and message == "Index à jour.":
                etat.relancer = False
                etat.save(update_fields=["relancer"])
                continue
            etat.en_cours, etat.relancer, etat.message, etat.fin = False, False, message, timezone.now()
            etat.save()
            return


def planifier_indexation() -> None:
    """Après l'analyse d'un document : met l'index à jour si le moteur d'IA est présent."""
    from django.conf import settings

    if settings.IA_INDEXATION_AUTO and ollama.version() is not None:
        transaction.on_commit(indexer_assistant.delay)
