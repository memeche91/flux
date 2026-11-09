"""Lecture des offres en tâche de fond (un PDF scanné peut demander une reconnaissance de texte)."""
import logging
from pathlib import Path

from celery import shared_task
from django.db import transaction

from bibliotheque.lecture import ErreurLecture, FormatNonAnalyse

from .lecture import bilan, lire_offre
from .models import LigneOffre, Offre, StatutLecture

logger = logging.getLogger(__name__)


def appliquer_lecture(offre: Offre) -> None:
    try:
        lecture = lire_offre(Path(offre.fichier.path), offre.lot)
    except (FormatNonAnalyse, ErreurLecture) as erreur:
        offre.statut_lecture, offre.message_lecture = StatutLecture.NON_LUE, f"{erreur} Saisissez le montant de l'offre."[:500]
        offre.save(update_fields=["statut_lecture", "message_lecture"])
        return
    except Exception as erreur:  # noqa: BLE001 - fichier protégé, abîmé…
        logger.exception("Lecture de l'offre %s impossible", offre.pk)
        offre.statut_lecture = StatutLecture.NON_LUE
        offre.message_lecture = f"Lecture impossible ({erreur.__class__.__name__}) : saisissez le montant de l'offre."
        offre.save(update_fields=["statut_lecture", "message_lecture"])
        return

    statut, message, retenu = bilan(lecture)
    with transaction.atomic():
        offre.lignes.all().delete()
        LigneOffre.objects.bulk_create([
            LigneOffre(
                offre=offre, poste_id=l.poste_id, option_id=l.option_id, ordre=l.ordre, numero=l.numero[:50],
                designation=l.designation, unite=l.unite[:20], quantite=l.quantite, prix_unitaire=l.prix_unitaire,
                montant=l.montant, correspondance=l.correspondance,
            )
            for l in lecture.lignes
        ])
        offre.statut_lecture, offre.message_lecture = statut, message
        offre.montant_base_calcule, offre.montant_base_declare = lecture.base_calcule, lecture.base_declare
        offre.montant_base = retenu
        options = {str(k): str(v) for k, v in lecture.options_calcules.items()}
        options.update({str(k): str(v) for k, v in lecture.options_declares.items()})  # le total déclaré prime
        offre.montants_options = options
        offre.save()


@shared_task(time_limit=30 * 60, soft_time_limit=28 * 60)
def analyser_offre(offre_id: int) -> None:
    offre = Offre.objects.select_related("lot__projet").filter(pk=offre_id).first()
    if offre is not None and offre.fichier:
        appliquer_lecture(offre)
