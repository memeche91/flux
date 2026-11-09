"""Exports PDF (WeasyPrint : HTML + CSS d'impression).

Toutes les pièces écrites (CCTP, CCAP, RC, actes d'engagement) partagent le même
gabarit ; le sommaire est calculé à la mise en page, avec les vrais numéros de page.
"""
from __future__ import annotations

from django.template.loader import render_to_string

from ..structure import StructureLot
from .document import POLICES_PDF, DocumentExport, document_cctp


def _rendre(gabarit: str, contexte: dict) -> bytes:
    from weasyprint import HTML

    return HTML(string=render_to_string(gabarit, contexte)).write_pdf()


def _contexte(doc: DocumentExport) -> dict:
    projet = doc.projet
    return {
        "document": doc,
        "projet": projet,
        "police": POLICES_PDF.get(projet.police, POLICES_PDF["Arial"]),
        "taille": projet.taille_police,
        "couleur_titres": projet.couleur_titres,
        "couleur_tableaux": projet.couleur_tableaux,
    }


def exporter_pdf(doc: DocumentExport) -> bytes:
    return _rendre("projets/document.html", _contexte(doc))


def exporter_cctp_pdf(structure: StructureLot) -> bytes:
    return exporter_pdf(document_cctp(structure))


def exporter_dpgf_pdf(structure: StructureLot, *, avec_prix: bool = False) -> bytes:
    lot = structure.lot
    projet = lot.projet
    doc = DocumentExport(
        projet=projet,
        titre_piece="Estimation du maître d'œuvre (DPGF chiffrée)" if avec_prix else "Décomposition du Prix Global et Forfaitaire",
        sigle="DPGF",
        sous_titre=f"Lot {lot.code} – {lot.intitule}",
        pied=f"{projet.nom} – DPGF lot {lot.code} – indice {projet.indice}",
        nom_fichier=f"DPGF Lot {lot.code} - {lot.intitule}",
        chapitres=[],
    )
    taux = projet.taux_tva
    recapitulatif = []
    for section in structure.sections_dpgf:
        if section.option is not None and not section.lignes:
            continue
        total = section.total
        tva = (total * taux / 100).quantize(total.__class__("0.01"))
        recapitulatif.append({"titre": section.titre, "ht": total, "tva": tva, "ttc": total + tva})
    contexte = _contexte(doc)
    contexte.update({"structure": structure, "lot": lot, "avec_prix": avec_prix, "recapitulatif": recapitulatif, "taux_tva": taux})
    return _rendre("projets/dpgf.html", contexte)
