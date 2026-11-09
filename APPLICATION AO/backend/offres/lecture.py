"""Lecture d'une offre : DPGF complétée par l'entreprise (Excel, PDF) ou devis.

Les lignes de prix sont reconnues comme dans la bibliothèque (colonnes Désignation, U, Qté, PU,
Montant), puis rapprochées des ouvrages du lot : par numéro (8.2.1) quand l'entreprise a rempli
la DPGF du DCE, sinon par la désignation. Les totaux déclarés (« Total solution de base HT »,
« Total PSE n°1 HT ») sont comparés à la somme des lignes pour repérer les erreurs de calcul.
"""
from __future__ import annotations

import difflib
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from articles.normalisation import arrondir, lire_nombre, normaliser, normaliser_unite, texte_cellule
from articles.prix import LIGNES_RECHERCHE_ENTETE, detecter_entetes, extraire_lignes_prix
from bibliotheque.lecture import lire_document
from projets.models import GenrePoste, LotProjet
from projets.structure import structurer

TOLERANCE = Decimal("1.00")  # écart toléré (arrondis) entre total déclaré et somme des lignes
SEUIL_DESIGNATION = 0.72


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


@dataclass
class Lecture:
    lignes: list[LigneLue] = field(default_factory=list)
    base_calcule: Decimal | None = None
    options_calcules: dict[int, Decimal] = field(default_factory=dict)
    base_declare: Decimal | None = None
    options_declares: dict[int, Decimal] = field(default_factory=dict)
    ouvrages_sans_prix: int = 0
    lignes_hors_dpgf: int = 0


def _cle_numero(numero: str) -> str:
    return ".".join(p.lstrip("0") or "0" for p in normaliser(numero).replace(" ", ".").split(".") if p)


def _totaux_declares(tableaux, lot: LotProjet) -> tuple[Decimal | None, dict[int, Decimal]]:
    """Lignes « Total solution de base HT » / « Total PSE n°1 HT » de la DPGF remplie."""
    options = {normaliser(o.nom_court): o.pk for o in lot.options.all()}
    base, par_option = None, {}
    for tableau in tableaux:
        roles = None
        for indice, ligne in enumerate(tableau.lignes[:LIGNES_RECHERCHE_ENTETE]):
            roles = detecter_entetes(ligne)
            if roles:
                break
        if not roles or "montant" not in roles:
            continue
        for ligne in tableau.lignes:
            textes = [normaliser(texte_cellule(c)) for c in ligne]
            libelle = next((t for t in textes if t.startswith("total ")), "")
            if not libelle or roles["montant"] >= len(ligne):
                continue
            montant = lire_nombre(ligne[roles["montant"]])
            if montant is None:
                continue
            if libelle.startswith("total solution de base"):
                base = arrondir(montant, 2)
                continue
            for nom, option_id in options.items():
                if libelle.startswith(f"total {nom}"):
                    par_option[option_id] = arrondir(montant, 2)
    return base, par_option


def lire_offre(chemin: Path, lot: LotProjet) -> Lecture:
    with tempfile.TemporaryDirectory(prefix="offre-") as dossier:
        contenu = lire_document(chemin, Path(dossier), tableaux_pdf=True)
    extraites = extraire_lignes_prix(contenu.tableaux)

    structure = structurer(lot)
    ouvrages = [e for section in structure.sections_dpgf for e in section.lignes if e.poste.genre == GenrePoste.OUVRAGE]
    par_numero = {_cle_numero(e.numero): e for e in ouvrages}
    restants = {e.poste.pk: e for e in ouvrages}

    lecture = Lecture()
    for extraite in extraites:
        montant = extraite.montant
        if montant is None and extraite.quantite is not None and extraite.prix_unitaire is not None:
            montant = arrondir(extraite.quantite * extraite.prix_unitaire, 2)
        ligne = LigneLue(
            ordre=len(lecture.lignes) + 1, numero=extraite.numero, designation=extraite.designation, unite=extraite.unite,
            quantite=extraite.quantite, prix_unitaire=extraite.prix_unitaire, montant=montant,
        )
        element = par_numero.get(_cle_numero(extraite.numero)) if extraite.numero else None
        if element is not None and element.poste.pk in restants:
            ligne.correspondance = "NUMERO"
        else:
            element = _par_designation(extraite.designation, extraite.unite, restants.values())
            if element is not None:
                ligne.correspondance = "DESIGNATION"
        if element is not None:
            restants.pop(element.poste.pk, None)
            ligne.poste_id, ligne.option_id = element.poste.pk, element.poste.option_id
        lecture.lignes.append(ligne)

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
            base += ligne.montant  # lignes de la solution de base et lignes ajoutées par l'entreprise
    lecture.base_calcule = arrondir(base, 2) if chiffrees else None
    lecture.options_calcules = {k: arrondir(v, 2) for k, v in options.items()}
    lecture.ouvrages_sans_prix = len(restants) + sum(1 for l in lecture.lignes if l.poste_id and l.montant is None)
    lecture.lignes_hors_dpgf = sum(1 for l in lecture.lignes if l.poste_id is None and l.montant is not None)
    lecture.base_declare, lecture.options_declares = _totaux_declares(contenu.tableaux, lot)
    return lecture


def _par_designation(designation: str, unite: str, candidats) -> object | None:
    cible = normaliser(designation)
    if not cible:
        return None
    meilleur, score = None, 0.0
    for element in candidats:
        ratio = difflib.SequenceMatcher(None, cible, normaliser(element.poste.titre)).ratio()
        if unite and element.poste.unite and normaliser_unite(unite) != normaliser_unite(element.poste.unite):
            ratio -= 0.1
        if ratio > score:
            meilleur, score = element, ratio
    return meilleur if score >= SEUIL_DESIGNATION else None


def bilan(lecture: Lecture) -> tuple[str, str, Decimal | None]:
    """Statut de lecture, message et montant de base retenu."""
    if lecture.base_calcule is None and lecture.base_declare is None:
        return "NON_LUE", "Aucun prix reconnu dans ce document : saisissez le montant de l'offre.", None
    remarques = []
    retenu = lecture.base_declare if lecture.base_declare is not None else lecture.base_calcule
    a_verifier = False
    if lecture.base_declare is not None and lecture.base_calcule is not None and abs(lecture.base_declare - lecture.base_calcule) > TOLERANCE:
        a_verifier = True
        remarques.append(
            f"Total déclaré {_euros(lecture.base_declare)} différent de la somme des lignes {_euros(lecture.base_calcule)} : erreur de calcul à faire confirmer par l'entreprise"
        )
    for option_id, declare in lecture.options_declares.items():
        calcule = lecture.options_calcules.get(option_id)
        if calcule is not None and abs(declare - calcule) > TOLERANCE:
            a_verifier = True
            remarques.append("écart entre un total de PSE déclaré et ses lignes")
            break
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
