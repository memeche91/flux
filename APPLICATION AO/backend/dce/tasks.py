"""Tâches de fond : production des dossiers .zip et envoi aux entreprises."""
import logging

from celery import shared_task
from django.core.files import File
from django.db import transaction
from django.utils import timezone

from .assemblage import produire_dossier, racine
from .envois import envoyer_courriel
from .models import ConsultationEntreprise, DossierDCE, Envoi, ModeEnvoi, StatutConsultation, StatutDossier, StatutEnvoi

logger = logging.getLogger(__name__)


def produire(dossier: DossierDCE, lettre: str = "") -> None:
    lots = list(dossier.lots.order_by("ordre", "code")) or None
    try:
        chemin, contenu = produire_dossier(
            dossier.projet, dossier.indice, lots=lots, avec_word=dossier.avec_word, entreprise=dossier.entreprise, lettre=lettre
        )
    except Exception as erreur:  # noqa: BLE001
        logger.exception("Production du DCE impossible")
        dossier.statut, dossier.message = StatutDossier.ERREUR, f"Production impossible ({erreur.__class__.__name__})."[:500]
        dossier.save(update_fields=["statut", "message"])
        return
    try:
        nom = racine(dossier.projet, dossier.indice)
        if dossier.entreprise:
            nom = f"{nom} - {dossier.entreprise.raison_sociale}"[:120]
        dossier.nom = f"{nom}.zip"
        with chemin.open("rb") as flux:
            dossier.fichier.save(dossier.nom, File(flux), save=False)
        dossier.taille, dossier.contenu, dossier.statut, dossier.message = chemin.stat().st_size, contenu, StatutDossier.PRET, ""
        dossier.save()
    finally:
        chemin.unlink(missing_ok=True)


@shared_task(time_limit=30 * 60)
def generer_dossier(dossier_id: int) -> None:
    dossier = DossierDCE.objects.select_related("projet", "entreprise").filter(pk=dossier_id).first()
    if dossier is not None:
        produire(dossier)


@shared_task(time_limit=60 * 60)
def envoyer_aux_entreprises(envoi_ids: list[int], indice: str, avec_word: bool) -> None:
    """Pour chaque envoi : dossier limité aux lots de l'entreprise (marché privé), courriel, historique."""
    for envoi in Envoi.objects.filter(pk__in=envoi_ids).select_related("projet", "entreprise"):
        projet, entreprise = envoi.projet, envoi.entreprise
        consultations = list(ConsultationEntreprise.objects.filter(projet=projet, entreprise=entreprise).select_related("lot"))
        lots = [c.lot for c in consultations]
        try:
            dossier = None
            if projet.type_marche == "PRIVE":
                dossier = DossierDCE.objects.create(projet=projet, indice=indice, entreprise=entreprise, avec_word=avec_word, cree_par=envoi.cree_par)
                dossier.lots.set(lots)
                produire(dossier, lettre=envoi.message)
                if dossier.statut != StatutDossier.PRET:
                    raise RuntimeError(dossier.message)
                envoi.dossier = dossier
                envoi.save(update_fields=["dossier"])
            if envoi.mode == ModeEnvoi.EMAIL:
                envoyer_courriel(envoi, dossier)
            else:
                envoi.statut = StatutEnvoi.A_ENVOYER
                envoi.save(update_fields=["statut"])
        except Exception as erreur:  # noqa: BLE001
            logger.exception("Envoi du DCE impossible")
            envoi.statut, envoi.erreur = StatutEnvoi.ERREUR, f"Préparation impossible ({erreur.__class__.__name__})."[:500]
            envoi.save(update_fields=["statut", "erreur"])
            continue
        if envoi.statut == StatutEnvoi.ENVOYE:
            marquer_consultees(envoi)


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


