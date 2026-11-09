"""Tâches de fond de la GED : notifications groupées."""
import logging

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import EspaceChantier, Evenement
from .notifications import envoyer, messages_groupes

logger = logging.getLogger(__name__)
DELAI_REGROUPEMENT = 60  # secondes : un dépôt de plusieurs fichiers donne un seul courriel


def planifier_notifications(espace_id: int) -> None:
    transaction.on_commit(lambda: notifier_espace.apply_async((espace_id,), countdown=DELAI_REGROUPEMENT))


@shared_task
def notifier_espace(espace_id: int) -> None:
    espace = EspaceChantier.objects.select_related("projet").filter(pk=espace_id).first()
    if espace is None:
        return
    with transaction.atomic():
        en_attente = Evenement.objects.select_for_update(skip_locked=True).filter(espace=espace, a_notifier=True, notifie_le__isnull=True)
        evenements = list(en_attente.select_related("document__lot", "version").order_by("date", "id"))
        if not evenements:
            return
        if not (settings.EMAIL_ACTIF and espace.notifications):
            Evenement.objects.filter(pk__in=[e.pk for e in evenements]).update(a_notifier=False)
            return
        try:
            envoyes = envoyer(messages_groupes(espace, evenements))
        except Exception:  # noqa: BLE001 - messagerie indisponible : nouvel essai au prochain événement
            logger.exception("Notifications de la GED %s non envoyées", espace_id)
            return
        Evenement.objects.filter(pk__in=[e.pk for e in evenements]).update(a_notifier=False, notifie_le=timezone.now())
        logger.info("GED %s : %s courriel(s) envoyé(s)", espace_id, envoyes)
