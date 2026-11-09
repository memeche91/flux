"""Extraction des lignes de prix d'une DPGF (Excel, CSV, tableaux Word ou PDF).

On repère la ligne d'en-tête (Désignation, U, Qté, PU, Montant…), puis chaque
ligne qui porte une unité, une quantité ou un prix devient une ligne de prix.
Les lignes sans quantité ni prix sont des titres de chapitre ; les totaux sont ignorés.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .normalisation import arrondir, detecter_lot, lire_nombre, normaliser, normaliser_unite, texte_cellule

LIGNES_RECHERCHE_ENTETE = 40
_DEBUTS_TOTAL = (
    "total",
    "sous total",
    "montant total",
    "montant ht",
    "montant ttc",
    "tva",
    "report",
    "a reporter",
    "recapitulatif",
    "net a payer",
    "totaux",
)


@dataclass
class LignePrixExtraite:
    ordre: int
    numero: str
    chapitre: str
    designation: str
    unite: str
    quantite: Decimal | None
    prix_unitaire: Decimal | None
    montant: Decimal | None
    code_lot: str | None
    tableau: int = 0  # rang du tableau dans le document


def role_entete(valeur) -> str | None:
    texte = normaliser(texte_cellule(valeur))
    if not texte or len(texte) > 40:
        return None
    if texte in {"pu", "p u", "pu ht", "p u ht", "pu eur", "pu euros"} or texte.startswith(("prix unit", "pu ")):
        return "prix_unitaire"
    if texte.startswith(("montant", "total", "prix total")) or texte in {"pt", "p t", "pt ht"}:
        return "montant"
    if texte.startswith(("qte", "quant")) or texte in {"q", "qt", "qtt", "qtes"}:
        return "quantite"
    if texte in {"u", "un", "unite", "unites", "u m"} or texte.startswith("unit"):
        return "unite"
    if any(mot in texte for mot in ("designation", "libelle", "description", "intitule", "nature des", "prestation")):
        return "designation"
    if texte in {"n", "no", "n o", "num", "numero", "art", "article", "ref", "reference", "repere", "poste", "code", "item", "index"}:
        return "numero"
    return None


def detecter_entetes(ligne) -> dict[str, int] | None:
    roles: dict[str, int] = {}
    for indice, valeur in enumerate(ligne):
        role = role_entete(valeur)
        if role and role not in roles:
            roles[role] = indice
    if "designation" in roles and {"unite", "quantite", "prix_unitaire"} & roles.keys():
        return roles
    return None


_DEBUTS_TOTAL_MOTS = tuple(f"{debut} " for debut in _DEBUTS_TOTAL)


def _est_total(designation_normalisee: str) -> bool:
    # Mots entiers : « Reportage photographique » ou « Totalité des… » ne sont pas des totaux.
    return f"{designation_normalisee} ".startswith(_DEBUTS_TOTAL_MOTS) or designation_normalisee in {"ht", "ttc"}


def roles_des_tableaux(tableaux):
    """(indice, tableau, rôles des colonnes, première ligne de données) pour chaque tableau de prix.

    Un tableau sans en-tête qui a la largeur du précédent est la suite d'un tableau coupé
    sur plusieurs pages (PDF) : il reprend ses colonnes.
    """
    entetes_precedentes: tuple[dict[str, int], int] | None = None
    for indice_tableau, tableau in enumerate(tableaux):
        largeur = max((len(l) for l in tableau.lignes), default=0)
        roles, debut = None, 0
        for indice, ligne in enumerate(tableau.lignes[:LIGNES_RECHERCHE_ENTETE]):
            roles = detecter_entetes(ligne)
            if roles:
                debut = indice + 1
                break
        if roles is None:
            if entetes_precedentes and entetes_precedentes[1] == largeur:
                roles = entetes_precedentes[0]
            else:
                continue
        entetes_precedentes = (roles, largeur)
        yield indice_tableau, tableau, roles, debut


def extraire_lignes_prix(tableaux, *, montants_seuls: bool = False) -> list[LignePrixExtraite]:
    """Lignes de prix des tableaux. Avec `montants_seuls`, une ligne qui ne porte qu'un montant
    (forfait, remise, moins-value) est une ligne de prix et non un titre (lecture des offres)."""
    resultats: list[LignePrixExtraite] = []

    for indice_tableau, tableau, roles, debut in roles_des_tableaux(tableaux):

        code_lot = detecter_lot(tableau.titre)
        chapitre = ""
        lignes_du_tableau = 0

        def cellule(ligne, role):
            indice = roles.get(role)
            return ligne[indice] if indice is not None and indice < len(ligne) else None

        for ligne in tableau.lignes[debut:]:
            designation = texte_cellule(cellule(ligne, "designation"))
            numero = texte_cellule(cellule(ligne, "numero"))[:50]
            if not designation or detecter_entetes(ligne):
                continue
            designation_normalisee = normaliser(designation)
            if _est_total(designation_normalisee):
                continue

            unite = texte_cellule(cellule(ligne, "unite"))
            unite = unite if len(unite) <= 12 else ""
            quantite = lire_nombre(cellule(ligne, "quantite"))
            prix_unitaire = lire_nombre(cellule(ligne, "prix_unitaire"))
            montant = lire_nombre(cellule(ligne, "montant"))

            if not unite and quantite is None and prix_unitaire is None and not (montants_seuls and montant is not None):
                lot_detecte = detecter_lot(designation) or detecter_lot(numero)
                if lot_detecte:
                    code_lot = lot_detecte
                if numero or len(designation) <= 100 or lignes_du_tableau == 0:
                    chapitre = " ".join(p for p in (numero, designation) if p)[:500]
                else:
                    # Désignation longue répartie sur plusieurs lignes.
                    resultats[-1].designation = f"{resultats[-1].designation} {designation}"[:4000]
                continue

            resultats.append(
                LignePrixExtraite(
                    ordre=len(resultats) + 1,
                    numero=numero,
                    chapitre=chapitre,
                    designation=designation[:4000],
                    unite=unite,
                    quantite=arrondir(quantite, 3),
                    prix_unitaire=arrondir(prix_unitaire, 2),
                    montant=arrondir(montant, 2),
                    code_lot=code_lot,
                    tableau=indice_tableau,
                )
            )
            lignes_du_tableau += 1
    return resultats


__all__ = ["LignePrixExtraite", "detecter_entetes", "extraire_lignes_prix", "normaliser_unite", "roles_des_tableaux"]
