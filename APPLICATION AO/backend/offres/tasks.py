"""Lecture des offres en tâche de fond (un PDF scanné peut demander une reconnaissance de texte)."""
import logging
from pathlib import Path

from celery import shared_task
from django.db import transaction

from bibliotheque.lecture import ErreurLecture, FormatNonAnalyse

from .lecture import bilan, lire_offre
from .models import LigneOffre, Offre, StatutLecture

logger = logging.getLogger(__name__)
CHAMPS_LECTURE = ["montant_base_calcule", "montant_base_declare", "modifie_le"]
CHAMPS_RESULTAT = ["statut_lecture", "message_lecture", "montant_base", "montants_options"]


def _propre(texte: str, longueur: int | None = None) -> str:
    texte = (texte or "").replace("\x00", "")
    return texte[:longueur] if longueur else texte


def _echec(offre_id: int, message: str) -> None:
    # update() et non save() : une offre supprimée pendant la lecture n'est pas recréée.
    Offre.objects.filter(pk=offre_id, statut_lecture=StatutLecture.EN_COURS).update(statut_lecture=StatutLecture.NON_LUE, message_lecture=message[:500])


def appliquer_lecture(offre: Offre) -> None:
    try:
        lecture = lire_offre(Path(offre.fichier.path), offre.lot)
    except (FormatNonAnalyse, ErreurLecture) as erreur:
        _echec(offre.pk, f"{erreur} Saisissez le montant de l'offre.")
        return
    except Exception as erreur:  # noqa: BLE001 - fichier protégé, abîmé…
        logger.exception("Lecture de l'offre %s impossible", offre.pk)
        _echec(offre.pk, f"Lecture impossible ({erreur.__class__.__name__}) : saisissez le montant de l'offre.")
        return

    statut, message, retenu = bilan(lecture)
    try:
        with transaction.atomic():
            # Verrou : deux relectures ne se chevauchent pas, et les saisies faites pendant la
            # lecture (notes, délai, écart…) ne sont pas écrasées.
            courante = Offre.objects.select_for_update().filter(pk=offre.pk).first()
            if courante is None:
                return  # offre supprimée pendant la lecture
            courante.lignes.all().delete()
            LigneOffre.objects.bulk_create([
                LigneOffre(
                    offre=courante, poste_id=l.poste_id, option_id=l.option_id, ordre=l.ordre, numero=_propre(l.numero, 50),
                    designation=_propre(l.designation), unite=_propre(l.unite, 20), quantite=l.quantite, prix_unitaire=l.prix_unitaire,
                    montant=l.montant, correspondance=l.correspondance,
                )
                for l in lecture.lignes
            ])
            courante.montant_base_calcule, courante.montant_base_declare = lecture.base_calcule, lecture.base_declare
            champs = list(CHAMPS_LECTURE)
            if courante.statut_lecture == StatutLecture.EN_COURS:
                # Sinon le montant a été saisi à la main pendant la lecture : il est conservé.
                courante.statut_lecture, courante.message_lecture = statut, message
                courante.montant_base = retenu
                options = {str(k): str(v) for k, v in lecture.options_calcules.items()}
                options.update({str(k): str(v) for k, v in lecture.options_declares.items()})  # le total déclaré prime
                courante.montants_options = options
                champs += CHAMPS_RESULTAT
            courante.save(update_fields=champs)
    except Exception as erreur:  # noqa: BLE001
        logger.exception("Enregistrement de la lecture de l'offre %s impossible", offre.pk)
        _echec(offre.pk, f"Lecture impossible ({erreur.__class__.__name__}) : saisissez le montant de l'offre.")


@shared_task(time_limit=30 * 60, soft_time_limit=28 * 60)
def analyser_offre(offre_id: int) -> None:
    offre = Offre.objects.select_related("lot__projet").filter(pk=offre_id).first()
    if offre is not None and offre.fichier:
        appliquer_lecture(offre)
