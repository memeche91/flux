import logging
import tempfile
from pathlib import Path

from celery import shared_task

from articles.services import indexer_document

from .lecture import ErreurLecture, FormatNonAnalyse, lire_document
from .models import DocumentReference, StatutAnalyse, TypeDocument

logger = logging.getLogger(__name__)


def _nombre(n: int) -> str:
    return f"{n:,}".replace(",", " ")


@shared_task
def analyser_document(document_id: int) -> None:
    """Lit le document, enregistre son texte puis le découpe en articles ou lignes de prix."""
    document = DocumentReference.objects.filter(pk=document_id).select_related("lot").first()
    if document is None:
        return

    with tempfile.TemporaryDirectory(prefix="analyse-") as dossier:
        try:
            contenu = lire_document(
                Path(document.fichier.path),
                Path(dossier),
                tableaux_pdf=document.type_document == TypeDocument.DPGF,
            )
            texte = contenu.texte()
            bilan = indexer_document(document, contenu)
        except FormatNonAnalyse as explication:
            document.statut_analyse = StatutAnalyse.NON_PRIS_EN_CHARGE
            document.message_analyse = str(explication)[:500]
            document.texte_extrait = ""
        except ErreurLecture as explication:
            document.statut_analyse = StatutAnalyse.ERREUR
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
            details = []
            if document.type_document == TypeDocument.DPGF:
                if bilan.lignes_prix:
                    details.append(
                        f"{_nombre(bilan.lignes_prix)} lignes de prix, dont {_nombre(bilan.lignes_chiffrees)} chiffrées"
                    )
                else:
                    details.append("Aucune ligne de prix reconnue (colonnes Désignation, U, Qté, PU introuvables)")
            else:
                mot = "clauses" if document.type_document in {"CCAP", "AE", "RC"} else "articles"
                details.append(f"{_nombre(bilan.articles)} {mot}")
            if contenu.pages_ocr:
                details.append(f"texte reconnu par OCR sur {contenu.pages_ocr} page(s)")
            if contenu.converti_depuis:
                details.append(f"converti depuis {contenu.converti_depuis}")
            document.statut_analyse = StatutAnalyse.ANALYSE
            document.message_analyse = (" · ".join(details) + ".")[:500]
            document.texte_extrait = texte

    document.save(update_fields=["statut_analyse", "message_analyse", "texte_extrait"])
