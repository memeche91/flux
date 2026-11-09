"""Tâches de fond de la GED : notifications groupées, récépissés, récapitulatif du matin."""
import datetime
import logging

from celery import shared_task
from celery.signals import worker_ready
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .archivage import liberer_archives_interrompues
from .models import EspaceChantier, Evenement, Frequence, StatutEspace, TypeEvenement, Version
from .notifications import EVENEMENTS_INTERNES, envoyer, message_recepisse, messages_nouveautes, messages_quotidiens

logger = logging.getLogger(__name__)
DELAI_REGROUPEMENT = 600  # secondes sans nouvel événement avant l'envoi : un dépôt de 15 plans en 4G = un courriel
ATTENTE_MAX = datetime.timedelta(minutes=30)  # au-delà, on envoie même si l'activité continue
CLE_RECAPITULATIF = "ged:recapitulatif:dernier"
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
        en_attente = Evenement.objects.select_for_update(skip_locked=True, of=("self",)).filter(espace=espace, a_notifier=True, notifie_le__isnull=True)
        evenements = list(en_attente.select_related("document__lot", "version__document", "utilisateur").order_by("date", "id"))
        if not evenements:
            return
        dernier = max(e.date for e in evenements)
        premier = min(e.date for e in evenements)
        maintenant = timezone.now()
        if (not settings.CELERY_TASK_ALWAYS_EAGER and maintenant - dernier < datetime.timedelta(seconds=DELAI_REGROUPEMENT - 5)
                and maintenant - premier < ATTENTE_MAX):
            # Dépôt encore en cours : on attend le calme pour envoyer un seul courriel (30 minutes au plus).
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
    """Chaque matin ouvré : récapitulatif pour les intervenants qui l'ont choisi, visas à rendre, OS à lire.

    Il couvre la période depuis le précédent récapitulatif (le week-end compris le lundi).
    """
    if not settings.EMAIL_ACTIF:
        return
    maintenant = timezone.now()
    depuis = cache.get(CLE_RECAPITULATIF) or maintenant - datetime.timedelta(days=3 if timezone.localdate().weekday() == 0 else 1)
    depuis = max(depuis, maintenant - datetime.timedelta(days=7))  # messagerie longtemps coupée : pas d'historique entier
    paquets = []
    for espace in EspaceChantier.objects.filter(statut__in=[StatutEspace.OUVERT, StatutEspace.RECEPTION], notifications=True).select_related("projet"):
        try:
            evenements = list(
                espace.evenements.filter(date__gte=depuis, date__lt=maintenant, type__in=TYPES_NOTIFIES).exclude(type__in=EVENEMENTS_INTERNES)
                .select_related("document__lot", "version__document", "utilisateur").order_by("date", "id")
            )
            paquets += messages_nouveautes(espace, evenements, Frequence.QUOTIDIENNE)
            paquets += [(message, [], None) for message in messages_quotidiens(espace)]
        except Exception:  # noqa: BLE001
            logger.exception("Récapitulatif quotidien de la GED %s non préparé", espace.pk)
    # Un seul envoi pour tous les chantiers : le débit limité s'applique à l'ensemble.
    try:
        envoyer(paquets)
    except Exception:  # noqa: BLE001 - messagerie injoignable : la période sera reprise demain
        logger.exception("Récapitulatif quotidien de la GED non envoyé")
        return
    cache.set(CLE_RECAPITULATIF, maintenant, None)


@shared_task
def relancer_notifications() -> None:
    """Toutes les 15 minutes : nouvel essai des notifications restées en attente (messagerie indisponible…)."""
    limite = timezone.now() - datetime.timedelta(minutes=5)
    # order_by() : sans lui, le tri par défaut (date, id) entre dans le DISTINCT (une tâche par événement).
    en_attente = Evenement.objects.filter(a_notifier=True, notifie_le__isnull=True, date__lt=limite)
    for espace_id in en_attente.order_by().values_list("espace_id", flat=True).distinct():
        notifier_espace.delay(espace_id)


@shared_task
def alerter_essais(total: int, ip_fiable: bool = False) -> None:
    """Beaucoup de codes erronés en une heure : la maîtrise d'œuvre est prévenue (sans blocage général).

    ip_fiable vient du service public (GED_IP_FIABLE n'est pas transmis au worker).
    """
    from django.core.mail import EmailMessage

    adresses = sorted({a for e in EspaceChantier.objects.filter(statut__in=[StatutEspace.OUVERT, StatutEspace.RECEPTION]) for a in e.liste_emails_moe()})
    if not (settings.EMAIL_ACTIF and adresses):
        logger.warning("GED : %s codes d'accès erronés en une heure", total)
        return
    journal = (
        "Le journal des accès (donnees/journaux) indique les adresses concernées." if ip_fiable else
        "Sur l'adresse IP fixe, Docker Desktop ne transmet pas l'adresse des visiteurs : le journal ne permet pas de les identifier ; "
        "remplacez les codes concernés si vous soupçonnez une fuite."
    )
    texte = (
        f"Bonjour,\n\n{total} codes d'accès erronés ont été saisis sur la GED en moins d'une heure.\n"
        "Il peut s'agir d'erreurs de saisie répétées ou d'une tentative de deviner un code. Les codes justes restent acceptés.\n"
        f"{journal}\n\nD’Aplomb"
    )
    EmailMessage("GED : nombreux codes d'accès erronés", texte, settings.DEFAULT_FROM_EMAIL, adresses).send(fail_silently=True)


@worker_ready.connect
def _archives_interrompues(sender=None, **_):
    """Au démarrage du worker : aucune archive ne peut être en préparation (tâche perdue à l'arrêt)."""
    if sender is not None and "voix@" in getattr(sender, "hostname", ""):
        return  # le worker « voix » ne produit pas d'archives
    try:
        liberer_archives_interrompues()
    except Exception:  # noqa: BLE001 - base ou dossier d'archives pas encore prêts
        logger.warning("Nettoyage des archives interrompues impossible au démarrage", exc_info=True)
