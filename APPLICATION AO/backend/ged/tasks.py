"""Tâches de fond de la GED : notifications groupées, récépissés, récapitulatif du matin."""
import datetime
import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import get_connection
from django.db import transaction
from django.utils import timezone

from .models import EspaceChantier, Evenement, Frequence, StatutEspace, TypeEvenement, Version
from .notifications import EVENEMENTS_INTERNES, envoyer, message_recepisse, messages_nouveautes, messages_quotidiens

logger = logging.getLogger(__name__)
DELAI_REGROUPEMENT = 600  # secondes sans nouvel événement avant l'envoi : un dépôt de 15 plans en 4G = un courriel
TYPES_NOTIFIES = [TypeEvenement.DEPOT, TypeEvenement.INDICE, TypeEvenement.VISA, TypeEvenement.ANNULATION]


def planifier_notifications(espace_id: int) -> None:
    transaction.on_commit(lambda: notifier_espace.apply_async((espace_id,), countdown=DELAI_REGROUPEMENT))


def _messagerie(espace: EspaceChantier) -> bool:
    return settings.EMAIL_ACTIF and espace.notifications


@shared_task
def notifier_espace(espace_id: int) -> None:
    espace = EspaceChantier.objects.select_related("projet").filter(pk=espace_id).first()
    if espace is None:
        return
    with transaction.atomic():
        en_attente = Evenement.objects.select_for_update(skip_locked=True).filter(espace=espace, a_notifier=True, notifie_le__isnull=True)
        evenements = list(en_attente.select_related("document__lot", "version__document", "utilisateur").order_by("date", "id"))
        if not evenements:
            return
        dernier = max(e.date for e in evenements)
        if not settings.CELERY_TASK_ALWAYS_EAGER and timezone.now() - dernier < datetime.timedelta(seconds=DELAI_REGROUPEMENT - 5):
            # Dépôt encore en cours : on attend le calme pour envoyer un seul courriel.
            transaction.on_commit(lambda: notifier_espace.apply_async((espace_id,), countdown=DELAI_REGROUPEMENT))
            return
        identifiants = [e.pk for e in evenements]
        if not _messagerie(espace):
            Evenement.objects.filter(pk__in=identifiants).update(a_notifier=False)
            return
        try:
            envoyes = envoyer(messages_nouveautes(espace, evenements, Frequence.IMMEDIATE))
        except Exception:  # noqa: BLE001 - messagerie injoignable : nouvel essai au prochain événement
            logger.exception("Notifications de la GED %s non envoyées", espace_id)
            return
        Evenement.objects.filter(pk__in=identifiants).update(a_notifier=False, notifie_le=timezone.now())
        logger.info("GED %s : %s courriel(s) envoyé(s)", espace_id, envoyes)


@shared_task
def envoyer_recepisse(version_id: int) -> None:
    version = Version.objects.select_related("document__espace__projet", "document__lot", "deposee_par_intervenant").filter(pk=version_id).first()
    if version is None or not settings.EMAIL_ACTIF:
        return
    message = message_recepisse(version)
    if message is not None:
        try:
            message.send()
        except Exception:  # noqa: BLE001
            logger.exception("Récépissé du dépôt %s non envoyé", version_id)


@shared_task
def recapitulatif_quotidien() -> None:
    """Chaque matin : récapitulatif pour les intervenants qui l'ont choisi, visas à rendre, OS à lire."""
    if not settings.EMAIL_ACTIF:
        return
    depuis = timezone.now() - datetime.timedelta(days=1)
    for espace in EspaceChantier.objects.filter(statut__in=[StatutEspace.OUVERT, StatutEspace.RECEPTION], notifications=True).select_related("projet"):
        try:
            evenements = list(
                espace.evenements.filter(date__gte=depuis, type__in=TYPES_NOTIFIES).exclude(type__in=EVENEMENTS_INTERNES)
                .select_related("document__lot", "version__document", "utilisateur").order_by("date", "id")
            )
            envoyer(messages_nouveautes(espace, evenements, Frequence.QUOTIDIENNE))
            with get_connection() as connexion:
                connexion.send_messages(messages_quotidiens(espace))
        except Exception:  # noqa: BLE001
            logger.exception("Récapitulatif quotidien de la GED %s non envoyé", espace.pk)


@shared_task
def relancer_notifications() -> None:
    """Toutes les 15 minutes : nouvel essai des notifications restées en attente (messagerie indisponible…)."""
    limite = timezone.now() - datetime.timedelta(minutes=5)
    for espace_id in Evenement.objects.filter(a_notifier=True, notifie_le__isnull=True, date__lt=limite).values_list("espace_id", flat=True).distinct():
        notifier_espace.delay(espace_id)


@shared_task
def alerter_essais(total: int) -> None:
    """Beaucoup de codes erronés en une heure : la maîtrise d'œuvre est prévenue (sans blocage général)."""
    from django.core.mail import EmailMessage

    adresses = sorted({a for e in EspaceChantier.objects.filter(statut__in=[StatutEspace.OUVERT, StatutEspace.RECEPTION]) for a in e.liste_emails_moe()})
    if not (settings.EMAIL_ACTIF and adresses):
        logger.warning("GED : %s codes d'accès erronés en une heure", total)
        return
    texte = (
        f"Bonjour,\n\n{total} codes d'accès erronés ont été saisis sur la GED en moins d'une heure.\n"
        "Il peut s'agir d'erreurs de saisie répétées ou d'une tentative de deviner un code. Les codes justes restent acceptés.\n"
        "Le journal des accès (donnees/journaux) indique les adresses concernées.\n\nApplication AO"
    )
    EmailMessage("GED : nombreux codes d'accès erronés", texte, settings.DEFAULT_FROM_EMAIL, adresses).send(fail_silently=True)
