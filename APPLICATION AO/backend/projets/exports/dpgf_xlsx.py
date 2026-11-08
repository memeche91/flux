"""Export de la DPGF d'un lot au format Excel (.xlsx).

Trois feuilles :
- « Page de garde » : opération, lot, cadre à remplir par l'entreprise ;
- « DPGF » : chapitres, ouvrages, montants calculés par formules, sous-totaux,
  solution de base puis chaque PSE / variante ;
- « Récapitulatif » : HT, TVA, TTC par solution, avec formules liées.
Version « vierge » (prix unitaires à compléter) ou « estimation » (prix du MOE).
"""
from __future__ import annotations

import io
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..structure import StructureLot
from .commun import page_de_garde

FORMAT_EUROS = '#,##0.00 "€"'
FORMAT_QUANTITE = "#,##0.00"
TRAIT = Side(style="thin", color="A6A6A6")
BORDURE = Border(left=TRAIT, right=TRAIT, top=TRAIT, bottom=TRAIT)


def _remplissage(couleur: str) -> PatternFill:
    couleur = couleur.lstrip("#").upper()
    return PatternFill("solid", start_color=couleur, end_color=couleur)


def exporter_dpgf_xlsx(structure: StructureLot, *, avec_prix: bool = False) -> bytes:
    lot = structure.lot
    projet = lot.projet
    garde = page_de_garde(structure, "Décomposition du Prix Global et Forfaitaire", "DPGF")
    couleur = projet.couleur_titres.lstrip("#").upper()
    fond_titres = _remplissage(couleur)
    fond_entetes = _remplissage(projet.couleur_tableaux)
    police = projet.police
    blanc = Font(name=police, bold=True, color="FFFFFF", size=12)

    classeur = Workbook()

    # --- Page de garde -----------------------------------------------------
    garde_feuille = classeur.active
    garde_feuille.title = "Page de garde"
    garde_feuille.sheet_view.showGridLines = False
    garde_feuille.column_dimensions["A"].width = 30
    for colonne in "BCDEF":
        garde_feuille.column_dimensions[colonne].width = 16
    ligne = 2
    if projet.maitre_ouvrage:
        garde_feuille.cell(ligne, 1, projet.maitre_ouvrage.upper()).font = Font(name=police, size=11)
        ligne += 1
    garde_feuille.cell(ligne, 1, projet.nom).font = Font(name=police, size=16, bold=True)
    ligne += 2
    for texte, taille in (
        (garde.titre_piece.upper() if not avec_prix else "ESTIMATION DU MAÎTRE D'ŒUVRE (DPGF CHIFFRÉE)", 13),
        (f"LOT {lot.code} – {lot.intitule.upper()}", 12),
    ):
        garde_feuille.merge_cells(start_row=ligne, start_column=1, end_row=ligne, end_column=6)
        cellule = garde_feuille.cell(ligne, 1, texte)
        cellule.font = Font(name=police, bold=True, color="FFFFFF", size=taille)
        cellule.fill = fond_titres
        cellule.alignment = Alignment(horizontal="center", vertical="center")
        garde_feuille.row_dimensions[ligne].height = 26
        ligne += 1
    ligne += 1
    for libelle, valeur in [*garde.lignes_operation, ("Phase", f"{projet.phase} – indice {projet.indice}"), ("Date", garde.date)]:
        garde_feuille.cell(ligne, 1, libelle).font = Font(name=police, bold=True)
        garde_feuille.cell(ligne, 1).fill = fond_entetes
        garde_feuille.merge_cells(start_row=ligne, start_column=2, end_row=ligne, end_column=6)
        garde_feuille.cell(ligne, 2, valeur).font = Font(name=police)
        for colonne in range(1, 7):
            garde_feuille.cell(ligne, colonne).border = BORDURE
        ligne += 1

    if not avec_prix:
        ligne += 1
        garde_feuille.merge_cells(start_row=ligne, start_column=1, end_row=ligne, end_column=6)
        cellule = garde_feuille.cell(ligne, 1, "CADRE RÉSERVÉ À L'ENTREPRISE")
        cellule.font = Font(name=police, bold=True)
        cellule.fill = fond_entetes
        ligne += 1
        for libelle in ("Raison sociale", "Adresse", "N° SIRET", "Téléphone", "Courriel", "Nom et qualité du signataire"):
            garde_feuille.cell(ligne, 1, libelle).font = Font(name=police)
            garde_feuille.merge_cells(start_row=ligne, start_column=2, end_row=ligne, end_column=6)
            for colonne in range(1, 7):
                garde_feuille.cell(ligne, colonne).border = BORDURE
            garde_feuille.row_dimensions[ligne].height = 22
            ligne += 1
        ligne += 1
        garde_feuille.merge_cells(start_row=ligne, start_column=1, end_row=ligne + 2, end_column=6)
        note = garde_feuille.cell(
            ligne,
            1,
            "Les quantités sont fournies à titre indicatif. L'entreprise les vérifie et complète la décomposition "
            "si nécessaire : le prix global et forfaitaire couvre l'ensemble des ouvrages décrits au CCTP.",
        )
        note.font = Font(name=police, italic=True, size=9)
        note.alignment = Alignment(wrap_text=True, vertical="top")

    # --- DPGF ----------------------------------------------------------------
    feuille = classeur.create_sheet("DPGF")
    largeurs = {"A": 10, "B": 58, "C": 7, "D": 11, "E": 14, "F": 16}
    for colonne, largeur in largeurs.items():
        feuille.column_dimensions[colonne].width = largeur
    feuille.merge_cells("A1:F1")
    feuille["A1"] = f"DPGF – Lot {lot.code} – {lot.intitule}"
    feuille["A1"].font = Font(name=police, bold=True, size=13, color=couleur)
    feuille.merge_cells("A2:F2")
    feuille["A2"] = projet.nom
    feuille["A2"].font = Font(name=police, size=10)
    entetes = ["N°", "Désignation", "U", "Qté", "PU HT", "Montant HT"]
    for colonne, texte in enumerate(entetes, start=1):
        cellule = feuille.cell(4, colonne, texte)
        cellule.font = Font(name=police, bold=True)
        cellule.fill = fond_entetes
        cellule.border = BORDURE
        cellule.alignment = Alignment(horizontal="center", vertical="center")
    feuille.freeze_panes = "A5"
    feuille.print_title_rows = "4:4"

    ligne = 5
    totaux_sections: list[tuple[str, str]] = []  # (libellé, référence de la cellule total)
    for section in structure.sections_dpgf:
        if section.option is not None:
            if not section.lignes:
                continue
            ligne += 1
            feuille.merge_cells(start_row=ligne, start_column=1, end_row=ligne, end_column=6)
            cellule = feuille.cell(ligne, 1, section.titre.upper())
            cellule.font = blanc
            cellule.fill = fond_titres
            ligne += 1
        sous_totaux: list[str] = []
        for chapitre in section.chapitres:
            feuille.cell(ligne, 1, chapitre.numero)
            feuille.cell(ligne, 2, chapitre.titre or "Ouvrages")
            for colonne in range(1, 7):
                cellule = feuille.cell(ligne, colonne)
                cellule.font = Font(name=police, bold=True)
                cellule.fill = fond_entetes
                cellule.border = BORDURE
            ligne += 1
            debut = ligne
            for element in chapitre.elements:
                poste = element.poste
                valeurs = [element.numero, element.poste.titre, poste.unite, _nombre(poste.quantite)]
                for colonne, valeur in enumerate(valeurs, start=1):
                    feuille.cell(ligne, colonne, valeur)
                if avec_prix and poste.prix_unitaire is not None:
                    feuille.cell(ligne, 5, _nombre(poste.prix_unitaire))
                feuille.cell(ligne, 6, f'=IF(OR(D{ligne}="",E{ligne}=""),"",ROUND(D{ligne}*E{ligne},2))')
                for colonne in range(1, 7):
                    cellule = feuille.cell(ligne, colonne)
                    cellule.font = Font(name=police, size=10)
                    cellule.border = BORDURE
                    cellule.alignment = Alignment(vertical="top", wrap_text=colonne == 2, horizontal="center" if colonne == 3 else None)
                feuille.cell(ligne, 4).number_format = FORMAT_QUANTITE
                feuille.cell(ligne, 5).number_format = FORMAT_EUROS
                feuille.cell(ligne, 6).number_format = FORMAT_EUROS
                ligne += 1
            feuille.cell(ligne, 2, f"Sous-total {chapitre.numero}")
            feuille.cell(ligne, 6, f"=SUM(F{debut}:F{ligne - 1})")
            for colonne in (2, 6):
                feuille.cell(ligne, colonne).font = Font(name=police, bold=True, italic=True)
            feuille.cell(ligne, 2).alignment = Alignment(horizontal="right")
            feuille.cell(ligne, 6).number_format = FORMAT_EUROS
            feuille.cell(ligne, 6).border = BORDURE
            sous_totaux.append(f"F{ligne}")
            ligne += 1

        libelle_total = "Total solution de base HT" if section.option is None else f"Total {section.option.nom_court} HT"
        feuille.cell(ligne, 2, libelle_total.upper())
        feuille.cell(ligne, 6, f"={'+'.join(sous_totaux)}" if sous_totaux else 0)
        for colonne in range(1, 7):
            cellule = feuille.cell(ligne, colonne)
            cellule.font = Font(name=police, bold=True)
            cellule.fill = fond_entetes
            cellule.border = BORDURE
        feuille.cell(ligne, 2).alignment = Alignment(horizontal="right")
        feuille.cell(ligne, 6).number_format = FORMAT_EUROS
        totaux_sections.append((section.titre, f"DPGF!F{ligne}"))
        ligne += 2

    feuille.page_setup.orientation = "portrait"
    feuille.page_setup.paperSize = feuille.PAPERSIZE_A4
    feuille.page_setup.fitToWidth = 1
    feuille.page_setup.fitToHeight = 0
    feuille.sheet_properties.pageSetUpPr.fitToPage = True
    feuille.oddFooter.center.text = f"{projet.nom} – DPGF lot {lot.code} – page &P / &N"

    # --- Récapitulatif --------------------------------------------------------
    recap = classeur.create_sheet("Récapitulatif")
    for colonne, largeur in {"A": 46, "B": 18, "C": 16, "D": 18}.items():
        recap.column_dimensions[colonne].width = largeur
    recap.merge_cells("A1:D1")
    recap["A1"] = f"Récapitulatif – Lot {lot.code} – {lot.intitule}"
    recap["A1"].font = Font(name=police, bold=True, size=13, color=couleur)
    recap["A3"] = "Taux de TVA"
    recap["A3"].font = Font(name=police, bold=True)
    recap["B3"] = float(projet.taux_tva) / 100
    recap["B3"].number_format = "0.0%"
    for colonne, texte in enumerate(["Désignation", "Montant HT", "TVA", "Montant TTC"], start=1):
        cellule = recap.cell(5, colonne, texte)
        cellule.font = Font(name=police, bold=True)
        cellule.fill = fond_entetes
        cellule.border = BORDURE
    ligne = 6
    for libelle, reference in totaux_sections:
        recap.cell(ligne, 1, libelle)
        recap.cell(ligne, 2, f"={reference}")
        recap.cell(ligne, 3, f"=ROUND(B{ligne}*$B$3,2)")
        recap.cell(ligne, 4, f"=B{ligne}+C{ligne}")
        for colonne in range(1, 5):
            cellule = recap.cell(ligne, colonne)
            cellule.border = BORDURE
            cellule.font = Font(name=police, bold=ligne == 6)
            if colonne > 1:
                cellule.number_format = FORMAT_EUROS
        ligne += 1
    if not avec_prix:
        ligne += 2
        recap.cell(ligne, 1, "Fait à ……………………………, le ……………………").font = Font(name=police)
        recap.cell(ligne + 2, 1, "Cachet et signature de l'entreprise :").font = Font(name=police, bold=True)

    flux = io.BytesIO()
    classeur.save(flux)
    return flux.getvalue()


def _nombre(valeur: Decimal | None):
    return float(valeur) if valeur is not None else None
