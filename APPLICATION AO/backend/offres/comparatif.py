"""Tableau comparatif d'un lot : ouvrages de la DPGF en lignes, estimation et offres en colonnes."""
from __future__ import annotations

import io
import re
from decimal import Decimal

from projets.models import LotProjet
from projets.structure import structurer

from .models import Offre
from .notation import classer, estimation


def _nombre(valeur) -> float | None:
    return None if valeur is None else float(valeur)


def _prix_ouvrage(lignes) -> dict | None:
    """Prix d'un ouvrage dans une offre ; un devis peut le détailler sur plusieurs lignes (bâtiments A et B…)."""
    if not lignes:
        return None
    if len(lignes) == 1:
        l = lignes[0]
        return {"pu": _nombre(l.prix_unitaire), "montant": _nombre(l.montant), "quantite": _nombre(l.quantite)}
    montants = [l.montant for l in lignes if l.montant is not None]
    quantites = [l.quantite for l in lignes]
    pus = {l.prix_unitaire for l in lignes}
    return {
        "pu": _nombre(pus.pop()) if len(pus) == 1 else None,
        "montant": _nombre(sum(montants, Decimal("0"))) if montants else None,
        "quantite": _nombre(sum(quantites, Decimal("0"))) if all(q is not None for q in quantites) else None,
    }


def comparatif(lot: LotProjet) -> dict:
    structure = structurer(lot)
    offres = list(Offre.objects.filter(lot=lot).select_related("entreprise").prefetch_related("lignes"))
    par_offre: dict[int, dict[int, list]] = {}
    for o in offres:
        for l in o.lignes.all():
            if l.poste_id:
                par_offre.setdefault(o.pk, {}).setdefault(l.poste_id, []).append(l)
    sections = []
    for section in structure.sections_dpgf:
        chapitres = []
        for chapitre in section.chapitres:
            lignes = []
            for element in chapitre.elements:
                poste = element.poste
                prix = {}
                for offre in offres:
                    prix[str(offre.pk)] = _prix_ouvrage(par_offre.get(offre.pk, {}).get(poste.pk))
                montants = [p["montant"] for p in prix.values() if p and p["montant"] is not None]
                lignes.append({
                    "poste_id": poste.pk, "numero": element.numero, "designation": poste.titre, "unite": poste.unite,
                    "quantite": _nombre(poste.quantite), "estimation_pu": _nombre(poste.prix_unitaire), "estimation": _nombre(poste.montant),
                    "offres": prix, "minimum": min(montants) if montants else None, "maximum": max(montants) if montants else None,
                })
            chapitres.append({"numero": chapitre.numero, "titre": chapitre.titre, "lignes": lignes})
        sections.append({"titre": section.titre, "option_id": section.option.pk if section.option else None, "chapitres": chapitres, "estimation": _nombre(section.total)})
    hors_dpgf = {
        str(o.pk): [{"numero": l.numero, "designation": l.designation, "montant": _nombre(l.montant)} for l in o.lignes.all() if l.poste_id is None and l.montant is not None]
        for o in offres
    }
    return {"sections": sections, "hors_dpgf": hors_dpgf}


def comparatif_xlsx(lots: list[LotProjet]) -> bytes:
    """Classeur Excel : une feuille par lot (ouvrages × offres, totaux, écarts à l'estimation)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    classeur = Workbook()
    classeur.remove(classeur.active)
    gras = Font(bold=True)
    for lot in lots:
        # Titre de feuille Excel : sans les caractères / \ * ? : [ ], 31 caractères au plus, unique.
        titre = re.sub(r"[\\/*?:\[\]]", "-", f"Lot {lot.code}")[:31]
        suffixe = 2
        while titre in classeur.sheetnames:
            titre = f"{titre[:26]} ({suffixe})"
            suffixe += 1
        feuille = classeur.create_sheet(titre)
        projet = lot.projet
        couleur = projet.couleur_tableaux.lstrip("#").upper()
        entete = PatternFill("solid", start_color=couleur, end_color=couleur)
        donnees = comparatif(lot)
        analyse, _, classement = classer(lot)
        offres = [l.offre for l in classement]
        feuille.cell(1, 1, f"{projet.nom} – Lot {lot.code} {lot.intitule} – comparatif des offres").font = Font(bold=True, size=13)
        titres = ["N°", "Désignation", "U", "Qté", "Estimation"] + [o.nom for o in offres]
        for colonne, titre in enumerate(titres, start=1):
            cellule = feuille.cell(3, colonne, titre)
            cellule.font, cellule.fill = gras, entete
            cellule.alignment = Alignment(wrap_text=True, vertical="top")
        ligne = 4
        for section in donnees["sections"]:
            feuille.cell(ligne, 2, section["titre"].upper()).font = gras
            ligne += 1
            for chapitre in section["chapitres"]:
                feuille.cell(ligne, 1, chapitre["numero"]).font = gras
                feuille.cell(ligne, 2, chapitre["titre"]).font = gras
                ligne += 1
                for ouvrage in chapitre["lignes"]:
                    valeurs = [ouvrage["numero"], ouvrage["designation"], ouvrage["unite"], ouvrage["quantite"], ouvrage["estimation"]]
                    valeurs += [(ouvrage["offres"].get(str(o.pk)) or {}).get("montant") for o in offres]
                    for colonne, valeur in enumerate(valeurs, start=1):
                        feuille.cell(ligne, colonne, valeur)
                    ligne += 1
            feuille.cell(ligne, 2, f"Total {section['titre']} HT").font = gras
            feuille.cell(ligne, 5, section["estimation"]).font = gras
            for colonne, offre in enumerate(offres, start=6):
                montant = offre.montant_base if section["option_id"] is None else offre.montants_options.get(str(section["option_id"]))
                feuille.cell(ligne, colonne, None if montant in (None, "") else float(Decimal(str(montant)))).font = gras
            ligne += 2
        feuille.cell(ligne, 2, "Prix comparé (base + PSE retenues) HT").font = gras
        reference = estimation(lot)
        retenues = list(analyse.options_retenues.values_list("pk", flat=True))
        feuille.cell(ligne, 5, float(reference["base"] + sum((reference["options"].get(o, Decimal("0")) for o in retenues), Decimal("0")))).font = gras
        for colonne, l in enumerate(classement, start=6):
            feuille.cell(ligne, colonne, None if l.prix is None else float(l.prix)).font = gras
        ligne += 1
        feuille.cell(ligne, 2, "Écart à l'estimation (%)")
        for colonne, l in enumerate(classement, start=6):
            feuille.cell(ligne, colonne, None if l.ecart_estimation is None else float(l.ecart_estimation))
        ligne += 1
        feuille.cell(ligne, 2, "Note totale / 100")
        for colonne, l in enumerate(classement, start=6):
            feuille.cell(ligne, colonne, None if l.total is None else float(l.total))
        ligne += 1
        feuille.cell(ligne, 2, "Rang")
        for colonne, l in enumerate(classement, start=6):
            feuille.cell(ligne, colonne, l.rang if l.rang else ("écartée" if l.offre.ecartee else None))
        for colonne in range(5, 6 + len(offres)):
            feuille.column_dimensions[get_column_letter(colonne)].width = 16
            for rangee in range(4, ligne + 1):
                feuille.cell(rangee, colonne).number_format = '#,##0.00'
        feuille.column_dimensions["A"].width = 9
        feuille.column_dimensions["B"].width = 50
        feuille.column_dimensions["C"].width = 6
        feuille.column_dimensions["D"].width = 9
        feuille.freeze_panes = "C4"
    if not classeur.worksheets:
        classeur.create_sheet("Comparatif")
    flux = io.BytesIO()
    classeur.save(flux)
    return flux.getvalue()
