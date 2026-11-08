import logging
from pathlib import Path

from celery import shared_task

from .extraction import FormatNonAnalyse, extraire_texte
from .models import DocumentReference, StatutAnalyse

logger = logging.getLogger(__name__)


@shared_task
def analyser_document(document_id: int) -> None:
    """Lit le contenu du document et enregistre le texte extrait."""
    document = DocumentReference.objects.filter(pk=document_id).first()
    if document is None:
        return

    try:
        texte = extraire_texte(Path(document.fichier.path))
    except FormatNonAnalyse as explication:
        document.statut_analyse = StatutAnalyse.NON_PRIS_EN_CHARGE
        document.message_analyse = str(explication)[:500]
        document.texte_extrait = ""
    except Exception as erreur:  # fichier corrompu, protégé par mot de passe…
        logger.exception("Analyse impossible du document %s", document_id)
        document.statut_analyse = StatutAnalyse.ERREUR
        document.message_analyse = (
            f"Lecture impossible ({erreur.__class__.__name__}). "
            "Le fichier est peut-être protégé ou endommagé."
        )[:500]
        document.texte_extrait = ""
    else:
        document.statut_analyse = StatutAnalyse.ANALYSE
        nombre = f"{len(texte):,}".replace(",", " ")
        document.message_analyse = f"{nombre} caractères extraits."
        document.texte_extrait = texte

    document.save(update_fields=["statut_analyse", "message_analyse", "texte_extrait"])
