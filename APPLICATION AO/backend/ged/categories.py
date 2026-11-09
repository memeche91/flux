"""Catégories de documents d'un chantier : code (dans la référence), zone proposée, diffusion
par défaut, confidentialité, accusé de lecture.

- Confidentielles (OS, avenants, devis de travaux modificatifs, situations, sous-traitance) :
  seules l'entreprise du lot, la maîtrise d'œuvre et le maître d'ouvrage les voient.
- Les autres catégories techniques sont lisibles par toutes les entreprises (option de l'espace),
  le dépôt restant limité aux lots de chacune.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Categorie:
    code: str
    libelle: str
    zone: str  # zone proposée : COMMUN ou LOT
    visa: bool = False  # soumise au visa de la maîtrise d'œuvre quand une entreprise la dépose
    confidentielle: bool = False
    lecture_requise: bool = False  # accusé de lecture demandé à l'entreprise du lot


CATEGORIES = [
    Categorie("PLA", "Plans de la maîtrise d'œuvre", "COMMUN"),
    Categorie("CR", "Comptes rendus de chantier", "COMMUN"),
    Categorie("PLG", "Planning", "COMMUN"),
    Categorie("PIC", "Installation de chantier (PIC)", "COMMUN"),
    Categorie("SPS", "Sécurité et santé (PGC, registre, visites du CSPS)", "COMMUN"),
    Categorie("CT", "Contrôle technique (RICT, avis)", "COMMUN"),
    Categorie("MAR", "Pièces du marché", "COMMUN"),
    Categorie("REC", "Réception (PV d'OPR et de réception)", "COMMUN"),
    Categorie("EXE", "Plans d'exécution", "LOT", visa=True),
    Categorie("SYN", "Synthèse et réservations", "LOT", visa=True),
    Categorie("NDC", "Notes de calcul", "LOT", visa=True),
    Categorie("FT", "Fiches techniques, agréments de matériaux", "LOT", visa=True),
    Categorie("ESS", "PV d'essais et autocontrôles", "LOT"),
    Categorie("PPS", "PPSPS", "LOT"),
    Categorie("RES", "Réserves et levée des réserves", "LOT"),
    Categorie("DOE", "DOE (dossier des ouvrages exécutés)", "LOT"),
    Categorie("DIU", "Éléments pour le DIUO", "LOT"),
    Categorie("OS", "Ordres de service", "LOT", confidentielle=True, lecture_requise=True),
    Categorie("AVT", "Avenants", "LOT", confidentielle=True, lecture_requise=True),
    Categorie("TS", "Devis de travaux modificatifs", "LOT", confidentielle=True),
    Categorie("SIT", "Situations de travaux", "LOT", confidentielle=True),
    Categorie("ST", "Sous-traitance (DC4)", "LOT", confidentielle=True),
    Categorie("PHO", "Photos", "LOT"),
    Categorie("AUT", "Autres documents", "LOT"),
]
PAR_CODE = {c.code: c for c in CATEGORIES}
CHOIX = [(c.code, c.libelle) for c in CATEGORIES]
CONFIDENTIELLES = {c.code for c in CATEGORIES if c.confidentielle}
A_VISER = {c.code for c in CATEGORIES if c.visa}
LECTURE_REQUISE = {c.code for c in CATEGORIES if c.lecture_requise}
# Pièces émises par la maîtrise d'œuvre : une entreprise ne les dépose pas.
EMISES_PAR_LA_MOE = {"PLA", "CR", "OS", "AVT", "MAR"}
# Après la réception, seules ces pièces sont encore attendues des entreprises.
APRES_RECEPTION = {"DOE", "DIU", "RES", "REC", "PHO"}


def libelle(code: str) -> str:
    categorie = PAR_CODE.get(code)
    return categorie.libelle if categorie else code
