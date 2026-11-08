"""Exports PDF du CCTP et de la DPGF (WeasyPrint : HTML + CSS d'impression).

Le sommaire du CCTP est calculé à la mise en page : chaque titre y figure avec
son numéro de page réel.
"""
from __future__ import annotations

from django.template.loader import render_to_string

from ..structure import StructureLot
from .commun import POLICES_PDF, page_de_garde


def _rendre(gabarit: str, contexte: dict) -> bytes:
    from weasyprint import HTML

    html = render_to_string(gabarit, contexte)
    return HTML(string=html).write_pdf()


def _contexte_commun(structure: StructureLot, titre: str, sigle: str) -> dict:
    projet = structure.lot.projet
    return {
        "structure": structure,
        "lot": structure.lot,
        "projet": projet,
        "garde": page_de_garde(structure, titre, sigle),
        "police": POLICES_PDF.get(projet.police, POLICES_PDF["Arial"]),
        "taille": projet.taille_police,
        "couleur_titres": projet.couleur_titres,
        "couleur_tableaux": projet.couleur_tableaux,
    }


def exporter_cctp_pdf(structure: StructureLot) -> bytes:
    contexte = _contexte_commun(structure, "Cahier des Clauses Techniques Particulières", "CCTP")
    return _rendre("projets/cctp.html", contexte)


def exporter_dpgf_pdf(structure: StructureLot, *, avec_prix: bool = False) -> bytes:
    contexte = _contexte_commun(structure, "Décomposition du Prix Global et Forfaitaire", "DPGF")
    taux = structure.lot.projet.taux_tva
    recap = []
    for section in structure.sections_dpgf:
        if section.option is not None and not section.lignes:
            continue
        total = section.total
        tva = (total * taux / 100).quantize(total.__class__("0.01"))
        recap.append({"titre": section.titre, "ht": total, "tva": tva, "ttc": total + tva})
    contexte.update({"avec_prix": avec_prix, "recapitulatif": recap, "taux_tva": taux})
    return _rendre("projets/dpgf.html", contexte)
