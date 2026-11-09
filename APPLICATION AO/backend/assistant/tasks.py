"""Tâches de fond de l'assistant.

Indexation : une seule à la fois, par tranches (chaque tranche est une tâche courte
qui relance la suivante), avec un signe de vie à chaque lot : une indexation
interrompue (worker redémarré, PC éteint) est reprise au lieu de rester bloquée.

Voix : transcription et synthèse s'exécutent dans le service « voix » (un seul
processus), pour ne charger Whisper et Piper qu'une fois en mémoire.
"""
import base64
import logging
import tempfile
from pathlib import Path

from celery import shared_task
from celery.signals import worker_ready
from django.db import transaction
from django.utils import timezone

from . import ollama, voix
from .indexation import calculer_plongements, synchroniser
from .models import EtatIndexation

logger = logging.getLogger(__name__)
PASSAGES_PAR_TRANCHE = 400
INDEX_A_JOUR = "Index à jour."


def _prendre_la_main() -> bool:
    EtatIndexation.courant()
    with transaction.atomic():
        etat = EtatIndexation.objects.select_for_update().get(pk=1)
        if etat.en_cours and not etat.perime():
            etat.relancer = True
            etat.save(update_fields=["relancer"])
            return False
        maintenant = timezone.now()
        etat.en_cours, etat.relancer = True, False
        etat.total = etat.faits = 0
        etat.message, etat.debut, etat.battement, etat.fin = "Préparation de l'index…", maintenant, maintenant, None
        etat.save()
        return True


def _liberer(message: str) -> bool:
    """Rend la main ; renvoie True s'il faut relancer (données arrivées pendant l'indexation)."""
    with transaction.atomic():
        etat = EtatIndexation.objects.select_for_update().get(pk=1)
        if etat.relancer and message == INDEX_A_JOUR:
            etat.relancer = False
            etat.battement = timezone.now()
            etat.save(update_fields=["relancer", "battement"])
            return True
        etat.en_cours, etat.relancer, etat.message, etat.fin = False, False, message, timezone.now()
        etat.save()
        return False


@shared_task(time_limit=50 * 60, soft_time_limit=45 * 60)
def indexer_assistant(suite: bool = False) -> None:
    if not suite and not _prendre_la_main():
        return
    try:
        restants = synchroniser()
        etat = EtatIndexation.courant()
        if not suite or etat.total < len(restants):
            etat.total, etat.faits = len(restants), 0
        else:
            etat.faits = etat.total - len(restants)
        etat.message, etat.battement = "Lecture de vos documents par l'IA…", timezone.now()
        etat.save(update_fields=["total", "faits", "message", "battement"])

        base = etat.faits
        tranche = restants[:PASSAGES_PAR_TRANCHE]
        calculer_plongements(
            tranche,
            lambda faits: EtatIndexation.objects.filter(pk=1).update(faits=base + faits, battement=timezone.now()),
        )
        if len(restants) > len(tranche):
            indexer_assistant.delay(suite=True)
            return
        message = INDEX_A_JOUR
    except ollama.OllamaIndisponible as erreur:
        message = f"Indexation interrompue : {erreur}"
    except Exception as erreur:  # noqa: BLE001 - y compris la limite de temps douce
        logger.exception("Indexation de l'assistant impossible")
        message = f"Indexation interrompue ({erreur.__class__.__name__}). Cliquez sur « Mettre à jour l'index » pour reprendre."
    if _liberer(message):
        indexer_assistant.delay(suite=True)


@worker_ready.connect
def _reprendre_apres_redemarrage(sender=None, **_):
    """Au démarrage du worker principal, une indexation laissée « en cours » est reprise."""
    if sender is not None and "voix@" in getattr(sender, "hostname", ""):
        return
    try:
        if EtatIndexation.objects.filter(pk=1, en_cours=True).update(en_cours=False):
            indexer_assistant.delay()
    except Exception:  # noqa: BLE001 - base pas encore prête
        logger.warning("Reprise de l'indexation impossible au démarrage du worker", exc_info=True)


def planifier_indexation() -> None:
    """Après l'analyse d'un document ou un changement de modèle : met l'index à jour si l'IA est présente."""
    from django.conf import settings

    if settings.IA_INDEXATION_AUTO and ollama.version() is not None:
        transaction.on_commit(indexer_assistant.delay)


@shared_task(ignore_result=False, time_limit=10 * 60)
def transcrire_audio(contenu: str, suffixe: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=suffixe) as fichier:
        fichier.write(base64.b64decode(contenu))
        fichier.flush()
        return voix.transcrire(Path(fichier.name))


@shared_task(ignore_result=False, time_limit=10 * 60)
def synthetiser_texte(texte: str) -> str:
    return base64.b64encode(voix.synthetiser(texte)).decode("ascii")
