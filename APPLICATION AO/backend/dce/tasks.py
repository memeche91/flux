"""Tâches de fond : production des dossiers .zip et envoi aux entreprises."""
import logging

from celery import shared_task
from celery.signals import worker_ready
from django.core.files import File
from django.db import transaction
from django.utils import timezone

from .assemblage import DocumentManquant, nom_zip, produire_dossier
from .envois import envoyer_courriel
from .models import ConsultationEntreprise, DossierDCE, Envoi, ModeEnvoi, StatutConsultation, StatutDossier, StatutEnvoi

logger = logging.getLogger(__name__)


def produire(dossier: DossierDCE, lettre: str = "", lots=None) -> None:
    """Produit le .zip. Sans `lots` : DCE complet (dossier sans entreprise uniquement)."""
    if lots is None and dossier.entreprise_id is None:
        lots = list(dossier.lots.order_by("ordre", "code")) or None
    try:
        chemin, contenu = produire_dossier(
            dossier.projet, dossier.indice, lots=lots, avec_word=dossier.avec_word, entreprise=dossier.entreprise, lettre=lettre
        )
    except DocumentManquant as erreur:
        dossier.statut, dossier.message = StatutDossier.ERREUR, str(erreur)[:500]
        dossier.save(update_fields=["statut", "message"])
        return
    except Exception as erreur:  # noqa: BLE001
        logger.exception("Production du DCE impossible")
        dossier.statut, dossier.message = StatutDossier.ERREUR, f"Production impossible ({erreur.__class__.__name__}). Relancez la génération."[:500]
        dossier.save(update_fields=["statut", "message"])
        return
    try:
        dossier.nom = nom_zip(dossier.projet, dossier.indice, dossier.entreprise)
        with chemin.open("rb") as flux:
            dossier.fichier.save(dossier.nom, File(flux), save=False)
        dossier.taille, dossier.contenu, dossier.statut, dossier.message = chemin.stat().st_size, contenu, StatutDossier.PRET, ""
        dossier.save()
    finally:
        chemin.unlink(missing_ok=True)


@shared_task(time_limit=30 * 60, soft_time_limit=28 * 60)
def generer_dossier(dossier_id: int) -> None:
    dossier = DossierDCE.objects.select_related("projet", "entreprise").filter(pk=dossier_id).first()
    if dossier is not None:
        produire(dossier)


@shared_task(time_limit=60 * 60, soft_time_limit=58 * 60)
def envoyer_aux_entreprises(envoi_ids: list[int], indice: str, avec_word: bool) -> None:
    """Pour chaque envoi : dossier limité aux lots retenus à la demande (marché privé), courriel, historique."""
    for envoi in Envoi.objects.filter(pk__in=envoi_ids, statut=StatutEnvoi.PREPARATION).select_related("projet", "entreprise"):
        projet, entreprise = envoi.projet, envoi.entreprise
        lots = list(envoi.lots.order_by("ordre", "code"))
        try:
            if not lots:
                raise ValueError("Cette entreprise n'est plus consultée pour aucun lot du projet.")
            dossier = None
            if projet.type_marche == "PRIVE":
                dossier = DossierDCE.objects.create(projet=projet, indice=indice, entreprise=entreprise, avec_word=avec_word, cree_par=envoi.cree_par)
                dossier.lots.set(lots)
                produire(dossier, lettre=envoi.message, lots=lots)
                if dossier.statut != StatutDossier.PRET:
                    raise ValueError(dossier.message)
                envoi.dossier = dossier
                envoi.save(update_fields=["dossier"])
            if envoi.mode == ModeEnvoi.EMAIL:
                envoyer_courriel(envoi, dossier)
            else:
                envoi.statut = StatutEnvoi.A_ENVOYER
                envoi.save(update_fields=["statut"])
        except ValueError as erreur:
            envoi.statut, envoi.erreur = StatutEnvoi.ERREUR, str(erreur)[:500]
            envoi.save(update_fields=["statut", "erreur"])
            continue
        except Exception as erreur:  # noqa: BLE001
            logger.exception("Envoi du DCE impossible")
            envoi.statut, envoi.erreur = StatutEnvoi.ERREUR, f"Préparation impossible ({erreur.__class__.__name__}). Renvoyez-lui le DCE."[:500]
            envoi.save(update_fields=["statut", "erreur"])
            continue
        if envoi.statut == StatutEnvoi.ENVOYE:
            marquer_consultees(envoi)


INTERROMPU_DOSSIER = "Préparation interrompue (application redémarrée). Relancez la génération."
INTERROMPU_ENVOI = "Préparation interrompue (application redémarrée). Renvoyez-lui le DCE."


def liberer_taches_perdues(age_minimum=None) -> None:
    """Dossiers ou envois restés « en préparation » : leur tâche a été perdue."""
    dossiers = DossierDCE.objects.filter(statut=StatutDossier.EN_COURS)
    envois = Envoi.objects.filter(statut=StatutEnvoi.PREPARATION)
    if age_minimum is not None:
        dossiers = dossiers.filter(cree_le__lt=timezone.now() - age_minimum[0])
        envois = envois.filter(cree_le__lt=timezone.now() - age_minimum[1])
    dossiers.update(statut=StatutDossier.ERREUR, message=INTERROMPU_DOSSIER)
    envois.update(statut=StatutEnvoi.ERREUR, erreur=INTERROMPU_ENVOI)


@worker_ready.connect
def _apres_redemarrage(sender=None, **_):
    if sender is not None and "voix@" in getattr(sender, "hostname", ""):
        return
    try:
        liberer_taches_perdues()
    except Exception:  # noqa: BLE001 - base pas encore prête
        logger.warning("Nettoyage des tâches du DCE impossible au démarrage", exc_info=True)


def marquer_consultees(envoi: Envoi) -> None:
    """Après l'envoi : les lots de l'entreprise passent à « Consultée » (historique de l'annuaire)."""
    if envoi.entreprise_id is None:
        return
    with transaction.atomic():
        for consultation in ConsultationEntreprise.objects.filter(projet=envoi.projet_id, entreprise=envoi.entreprise_id):
            if consultation.statut == StatutConsultation.A_CONSULTER:
                consultation.statut = StatutConsultation.CONSULTEE
            consultation.consultee_le = consultation.consultee_le or timezone.localdate()
            consultation.save(update_fields=["statut", "consultee_le"])


