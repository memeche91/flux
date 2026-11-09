"""Lecture d'une offre : DPGF complétée par l'entreprise (Excel, PDF) ou devis.

Les lignes de prix sont reconnues comme dans la bibliothèque (colonnes Désignation, U, Qté, PU,
Montant), puis rapprochées des ouvrages du lot : par numéro (8.2.1) quand l'entreprise a rempli
la DPGF du DCE et que la désignation concorde, sinon par la désignation. Les totaux déclarés
(« Total solution de base HT », « Total PSE n°1 HT », « Total HT » d'un devis) sont comparés à la
somme des lignes, et chaque ligne à Qté × PU, pour repérer les erreurs de calcul.
"""
from __future__ import annotations

import difflib
import re
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from articles.normalisation import arrondir, detecter_lot, lire_nombre, normaliser, normaliser_unite, texte_cellule
from articles.prix import extraire_lignes_prix, roles_des_tableaux
from bibliotheque.lecture import lire_document
from projets.models import GenrePoste, LotProjet
from projets.structure import structurer

TOLERANCE = Decimal("1.00")  # écart toléré (arrondis) entre total déclaré et somme des lignes
TOLERANCE_LIGNE = Decimal("0.05")  # écart toléré entre Qté × PU et le montant d'une ligne
SEUIL_DESIGNATION = 0.72  # ressemblance minimale pour rapprocher une ligne d'un ouvrage par sa désignation
SEUIL_NUMERO = 0.5  # en dessous, le numéro est jugé discordant (DPGF d'un autre indice…)


@dataclass
class LigneLue:
    ordre: int
    numero: str
    designation: str
    unite: str
    quantite: Decimal | None
    prix_unitaire: Decimal | None
    montant: Decimal | None
    poste_id: int | None = None
    option_id: int | None = None
    correspondance: str = ""
    tableau: int = 0


@dataclass
class Lecture:
    lignes: list[LigneLue] = field(default_factory=list)
    base_calcule: Decimal | None = None
    options_calcules: dict[int, Decimal] = field(default_factory=dict)
    base_declare: Decimal | None = None
    options_declares: dict[int, Decimal] = field(default_factory=dict)
    total_general_declare: Decimal | None = None  # « Total HT » d'un devis sans total de solution de base
    totaux_base_divergents: bool = False
    ouvrages_sans_prix: int = 0
    lignes_hors_dpgf: int = 0
    numeros_discordants: list[str] = field(default_factory=list)
    erreurs_multiplication: list[str] = field(default_factory=list)


def _cle_numero(numero: str) -> str:
    return ".".join(p.lstrip("0") or "0" for p in normaliser(numero).replace(" ", ".").split(".") if p)


def _code(code: str | None) -> str:
    return (code or "").lstrip("0") or "0"


_NOMBRE = re.compile(r"\d+")


def _nombres(texte: str) -> set[str]:
    return {n.lstrip("0") or "0" for n in _NOMBRE.findall(normaliser(texte))}


def _dimensions_compatibles(designation: str, titre_ouvrage: str) -> bool:
    """« Fenêtre 120 x 145 » ne peut pas être l'ouvrage « Porte-fenêtre 215 x 90 »."""
    ouvrage, ligne = _nombres(titre_ouvrage), _nombres(designation)
    return not ouvrage or not ligne or ouvrage <= ligne


def _similarite(designation: str, titre: str) -> float:
    """Ressemblance de deux désignations : texte proche, ou désignation abrégée (« Fenêtres alu »)."""
    a, b = normaliser(designation), normaliser(titre)
    if not a or not b:
        return 0.0
    score = difflib.SequenceMatcher(None, a, b).ratio()
    courts, longs = sorted((a.split(), b.split()), key=len)
    significatifs = [m for m in courts if len(m) >= 2 and not m.isdigit()]
    if len(significatifs) >= 2:
        trouves = sum(1 for m in significatifs if any(l == m or (len(m) >= 3 and l.startswith(m)) for l in longs))
        score = max(score, 0.9 * trouves / len(significatifs))
    return score


def _libelle_total(ligne) -> str:
    for cellule in ligne:
        texte = normaliser(texte_cellule(cellule))
        if re.match(r"(total|montant total|net)\b", texte):
            return texte
    return ""


def _totaux_declares(tableaux, lot: LotProjet, exclus: set[int], lecture: Lecture) -> None:
    """Lignes « Total solution de base HT », « Total PSE n°1 HT » ou « Total HT » de l'offre."""
    options = {normaliser(o.nom_court): o.pk for o in lot.options.all()}
    bases: list[Decimal] = []
    generaux: list[Decimal] = []
    for indice, tableau, roles, _debut in roles_des_tableaux(tableaux):
        if indice in exclus or "montant" not in roles:
            continue
        code_tableau = detecter_lot(tableau.titre)
        if code_tableau and _code(code_tableau) != _code(lot.code):
            continue
        for ligne in tableau.lignes:
            libelle = _libelle_total(ligne)
            if not libelle or roles["montant"] >= len(ligne):
                continue
            mots = libelle.split()
            if "ttc" in mots or "tva" in mots:
                continue  # le prix comparé est hors taxes
            montant = lire_nombre(ligne[roles["montant"]])
            if montant is None:
                continue
            montant = arrondir(montant, 2)
            libelle_mots = f"{libelle} "
            if libelle_mots.startswith("total solution de base "):
                bases.append(montant)
                continue
            option = next((option_id for nom, option_id in options.items() if libelle_mots.startswith(f"total {nom} ")), None)
            if option is not None:
                lecture.options_declares[option] = montant
            elif mots[0] in ("total", "montant", "net") and set(mots) <= {"total", "general", "montant", "net", "ht", "hors", "taxes", "de", "des", "l", "offre", "devis", "a", "payer", "global", "travaux", "prestations"}:
                generaux.append(montant)
    if bases:
        lecture.base_declare = bases[0]
        lecture.totaux_base_divergents = any(abs(b - bases[0]) > TOLERANCE for b in bases[1:])
    if generaux:
        lecture.total_general_declare = generaux[-1]


def lire_offre(chemin: Path, lot: LotProjet) -> Lecture:
    with tempfile.TemporaryDirectory(prefix="offre-") as dossier:
        contenu = lire_document(chemin, Path(dossier), tableaux_pdf=True)
    extraites = extraire_lignes_prix(contenu.tableaux, montants_seuls=True)

    structure = structurer(lot)
    ouvrages = [e for section in structure.sections_dpgf for e in section.lignes if e.poste.genre == GenrePoste.OUVRAGE]
    par_numero = {_cle_numero(e.numero): e for e in ouvrages}
    numeros_chapitres = {_cle_numero(c.numero) for section in structure.sections_dpgf for c in section.chapitres if c.numero}
    prefixe = _cle_numero(ouvrages[0].numero).split(".")[0] if ouvrages else ""

    lecture = Lecture()
    cumuls: dict[tuple[int, str], Decimal] = {}
    for extraite in extraites:
        if extraite.code_lot and _code(extraite.code_lot) != _code(lot.code):
            continue  # feuille ou partie d'un autre lot
        montant = extraite.montant
        seul = not extraite.unite and extraite.quantite is None and extraite.prix_unitaire is None
        cle = (extraite.tableau, extraite.chapitre)
        if seul:
            # Ligne qui ne porte qu'un montant : forfait ou remise, sauf titre de chapitre ou sous-total.
            if _cle_numero(extraite.numero) in numeros_chapitres or detecter_lot(extraite.designation):
                continue
            if cumuls.get(cle) and abs(cumuls[cle] - montant) <= TOLERANCE:
                continue
        if montant is None and extraite.quantite is not None and extraite.prix_unitaire is not None:
            montant = arrondir(extraite.quantite * extraite.prix_unitaire, 2)
        if montant is not None:
            cumuls[cle] = cumuls.get(cle, Decimal("0")) + montant
        lecture.lignes.append(LigneLue(
            ordre=len(lecture.lignes) + 1, numero=extraite.numero, designation=extraite.designation, unite=extraite.unite,
            quantite=extraite.quantite, prix_unitaire=extraite.prix_unitaire, montant=montant, tableau=extraite.tableau,
        ))

    _rapprocher(lecture, ouvrages, par_numero)

    # Tableaux d'un autre lot (classeur multi-lots) : aucune ligne rapprochée, numéros d'un autre lot.
    exclus = set()
    for indice in {l.tableau for l in lecture.lignes}:
        lignes = [l for l in lecture.lignes if l.tableau == indice]
        etrangeres = [l for l in lignes if "." in _cle_numero(l.numero) and _cle_numero(l.numero).split(".")[0] != prefixe]
        if prefixe and etrangeres and not any(l.poste_id for l in lignes) and any(l.poste_id for l in lecture.lignes):
            exclus.add(indice)
    lecture.lignes = [l for l in lecture.lignes if l.tableau not in exclus]
    for ordre, ligne in enumerate(lecture.lignes, start=1):
        ligne.ordre = ordre

    _totaux_declares(contenu.tableaux, lot, exclus, lecture)
    _repartir_lignes_ajoutees(lecture)

    base = Decimal("0")
    options: dict[int, Decimal] = {}
    chiffrees = 0
    for ligne in lecture.lignes:
        if ligne.montant is None:
            continue
        chiffrees += 1
        if ligne.option_id:
            options[ligne.option_id] = options.get(ligne.option_id, Decimal("0")) + ligne.montant
        else:
            base += ligne.montant
        if ligne.quantite is not None and ligne.prix_unitaire is not None:
            # Tolérance élargie aux quantités arrondies à l'affichage (PDF) : 0,005 × PU.
            if abs(arrondir(ligne.quantite * ligne.prix_unitaire, 2) - ligne.montant) > TOLERANCE_LIGNE + abs(ligne.prix_unitaire) * Decimal("0.005"):
                lecture.erreurs_multiplication.append(ligne.numero or ligne.designation[:40])
    lecture.base_calcule = arrondir(base, 2) if chiffrees else None
    lecture.options_calcules = {k: arrondir(v, 2) for k, v in options.items()}
    rapproches = {l.poste_id for l in lecture.lignes if l.poste_id and l.montant is not None}
    lecture.ouvrages_sans_prix = sum(1 for e in ouvrages if e.poste.pk not in rapproches)
    lecture.lignes_hors_dpgf = sum(1 for l in lecture.lignes if l.poste_id is None and l.montant is not None)
    return lecture


def _rapprocher(lecture: Lecture, ouvrages, par_numero) -> None:
    """Numéro (si la désignation concorde), puis désignation, du meilleur couple au moins bon."""
    pris: set[int] = set()
    for ligne in lecture.lignes:
        element = par_numero.get(_cle_numero(ligne.numero)) if ligne.numero else None
        if element is None or element.poste.pk in pris:
            continue
        if not ligne.designation or (
            _similarite(ligne.designation, element.poste.titre) >= SEUIL_NUMERO and _dimensions_compatibles(ligne.designation, element.poste.titre)
        ):
            pris.add(element.poste.pk)
            ligne.poste_id, ligne.option_id, ligne.correspondance = element.poste.pk, element.poste.option_id, "NUMERO"
        else:
            lecture.numeros_discordants.append(ligne.numero)

    libres = [l for l in lecture.lignes if l.poste_id is None and l.designation]
    couples = []
    for ligne in libres:
        for element in ouvrages:
            if element.poste.pk in pris or not _dimensions_compatibles(ligne.designation, element.poste.titre):
                continue
            score = _similarite(ligne.designation, element.poste.titre)
            if ligne.unite and element.poste.unite and normaliser_unite(ligne.unite) != normaliser_unite(element.poste.unite):
                score -= 0.1
            if score >= SEUIL_DESIGNATION:
                couples.append((score, ligne.ordre, ligne, element))
    affectees: dict[int, object] = {}
    for _score, _ordre, ligne, element in sorted(couples, key=lambda c: (-c[0], c[1])):
        if ligne.poste_id is not None or element.poste.pk in pris:
            continue
        pris.add(element.poste.pk)
        affectees[element.poste.pk] = element
        ligne.poste_id, ligne.option_id, ligne.correspondance = element.poste.pk, element.poste.option_id, "DESIGNATION"
    # Ouvrage détaillé sur plusieurs lignes d'un devis (bâtiment A, bâtiment B…) : lignes rattachées au même ouvrage.
    for _score, _ordre, ligne, element in sorted(couples, key=lambda c: (-c[0], c[1])):
        if ligne.poste_id is None and element.poste.pk in affectees:
            ligne.poste_id, ligne.option_id, ligne.correspondance = element.poste.pk, element.poste.option_id, "DESIGNATION"


def _repartir_lignes_ajoutees(lecture: Lecture) -> None:
    """Une ligne ajoutée par l'entreprise dans la section d'une PSE appartient à cette PSE.

    On la rattache à la section de la ligne rapprochée qui la précède, si cela rapproche
    les sommes des totaux déclarés ; sinon elle reste dans la solution de base.
    """
    if not lecture.options_declares:
        return
    section, candidates = None, []
    for ligne in lecture.lignes:
        if ligne.poste_id:
            section = ligne.option_id
        elif ligne.montant is not None and section:
            candidates.append((ligne, section))
    if not candidates:
        return

    def ecart(rattacher: bool) -> Decimal:
        base = sum((l.montant for l in lecture.lignes if l.montant is not None and not l.option_id), Decimal("0"))
        options: dict[int, Decimal] = {}
        for l in lecture.lignes:
            if l.montant is not None and l.option_id:
                options[l.option_id] = options.get(l.option_id, Decimal("0")) + l.montant
        if rattacher:
            for ligne, option in candidates:
                base -= ligne.montant
                options[option] = options.get(option, Decimal("0")) + ligne.montant
        total = abs(lecture.base_declare - base) if lecture.base_declare is not None else Decimal("0")
        return total + sum((abs(v - options.get(k, Decimal("0"))) for k, v in lecture.options_declares.items()), Decimal("0"))

    if ecart(True) < ecart(False):
        for ligne, option in candidates:
            ligne.option_id = option


def bilan(lecture: Lecture) -> tuple[str, str, Decimal | None]:
    """Statut de lecture, message et montant de base retenu."""
    base_lue = lecture.base_declare if lecture.base_declare is not None else lecture.base_calcule
    if base_lue is None and lecture.total_general_declare is None:
        return "NON_LUE", "Aucun prix reconnu dans ce document : saisissez le montant de l'offre.", None
    remarques = []
    a_verifier = False
    retenu = base_lue
    if lecture.base_declare is not None and lecture.base_calcule is not None and abs(lecture.base_declare - lecture.base_calcule) > TOLERANCE:
        a_verifier = True
        remarques.append(
            f"Total déclaré {_euros(lecture.base_declare)} différent de la somme des lignes {_euros(lecture.base_calcule)} : erreur de calcul à faire confirmer par l'entreprise"
        )
    if lecture.base_declare is None and lecture.total_general_declare is not None:
        total = lecture.total_general_declare
        if lecture.base_calcule is None:
            retenu, a_verifier = total, True
            remarques.append(f"seul le total {_euros(total)} a été lu : détail des prix à vérifier")
        else:
            avec_options = lecture.base_calcule + sum(lecture.options_calcules.values(), Decimal("0"))
            if abs(total - lecture.base_calcule) > TOLERANCE and abs(total - avec_options) > TOLERANCE:
                a_verifier = True
                remarques.append(f"Total HT déclaré {_euros(total)} différent de la somme des lignes {_euros(lecture.base_calcule)} : à faire confirmer par l'entreprise")
    if lecture.totaux_base_divergents:
        a_verifier = True
        remarques.append("plusieurs totaux de solution de base différents dans le document")
    for option_id, declare in lecture.options_declares.items():
        calcule = lecture.options_calcules.get(option_id)
        if calcule is not None and abs(declare - calcule) > TOLERANCE:
            a_verifier = True
            remarques.append("écart entre un total de PSE déclaré et ses lignes")
            break
    if lecture.erreurs_multiplication:
        a_verifier = True
        exemples = ", ".join(lecture.erreurs_multiplication[:3]) + ("…" if len(lecture.erreurs_multiplication) > 3 else "")
        remarques.append(f"Qté × PU différent du montant sur {len(lecture.erreurs_multiplication)} ligne(s) ({exemples}) : décomposition à faire rectifier")
    if lecture.numeros_discordants:
        a_verifier = True
        remarques.append(f"{len(lecture.numeros_discordants)} numéro(s) ne correspondant pas à la désignation de la DPGF (autre indice ?) : lignes rapprochées par leur désignation")
    if lecture.ouvrages_sans_prix:
        a_verifier = True
        remarques.append(f"{lecture.ouvrages_sans_prix} ouvrage(s) de la DPGF non chiffré(s) ou non retrouvé(s)")
    if lecture.lignes_hors_dpgf:
        remarques.append(f"{lecture.lignes_hors_dpgf} ligne(s) ajoutée(s) par l'entreprise")
    chiffrees = sum(1 for l in lecture.lignes if l.montant is not None)
    message = f"{chiffrees} ligne(s) de prix lue(s)" + (" ; " + " ; ".join(remarques) if remarques else "") + "."
    return ("A_VERIFIER" if a_verifier else "LUE"), message[:500], retenu


def _euros(valeur: Decimal) -> str:
    return f"{valeur:,.2f}".replace(",", " ").replace(".", ",") + " €"
