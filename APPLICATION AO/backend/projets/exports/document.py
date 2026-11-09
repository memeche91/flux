"""Représentation commune d'une pièce écrite à exporter (CCTP, CCAP, RC, acte d'engagement).

Les exports Word et PDF ne connaissent que cette structure : une page de garde,
puis des chapitres (titre de premier niveau, texte éventuel) contenant des éléments
(titre de second niveau + texte mis en forme).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.utils import timezone
from django.utils.formats import date_format

from ..models import Projet

POLICES_PDF = {
    "Arial": "Arial, 'Liberation Sans', 'DejaVu Sans', sans-serif",
    "Calibri": "Calibri, Carlito, 'Liberation Sans', 'DejaVu Sans', sans-serif",
    "Times New Roman": "'Times New Roman', 'Liberation Serif', 'DejaVu Serif', serif",
}


@dataclass
class ElementDoc:
    ancre: str
    intitule: str
    html: str = ""


@dataclass
class ChapitreDoc:
    ancre: str
    intitule: str
    html: str = ""
    elements: list[ElementDoc] = field(default_factory=list)


@dataclass
class DocumentExport:
    projet: Projet
    titre_piece: str
    sigle: str
    sous_titre: str
    pied: str
    nom_fichier: str
    chapitres: list[ChapitreDoc]
    sommaire: bool = True

    @property
    def date(self) -> str:
        return date_format(self.projet.date_document or timezone.localdate(), "j F Y")

    @property
    def lignes_operation(self) -> list[tuple[str, str]]:
        p = self.projet
        lignes = [
            ("Maître d'ouvrage", p.maitre_ouvrage),
            ("Adresse de l'opération", p.adresse_operation),
            ("Maîtrise d'œuvre", p.maitre_oeuvre),
            ("Marché", " – ".join(x for x in (p.get_type_marche_display(), p.procedure) if x)),
            ("N° d'affaire", p.numero),
        ]
        return [(libelle, valeur) for libelle, valeur in lignes if valeur]


def nom_de_fichier(base: str, extension: str) -> str:
    base = re.sub(r'[\\/:*?"<>|]+', "-", base).strip()
    return f"{base}.{extension}"


def document_cctp(structure) -> DocumentExport:
    """CCTP d'un lot : chapitres et articles / ouvrages numérotés (8.1, 8.1.1…)."""
    lot = structure.lot
    projet = lot.projet
    chapitres = []
    for indice, chapitre in enumerate(structure.chapitres, start=1):
        elements = [
            ElementDoc(f"poste-{e.poste.pk}", f"{e.numero} {e.titre_cctp}", e.poste.description) for e in chapitre.elements
        ]
        intitule = f"{chapitre.numero} {chapitre.titre}" if chapitre.titre else ""
        chapitres.append(ChapitreDoc(f"chapitre-{indice}", intitule, "", elements))
    return DocumentExport(
        projet=projet,
        titre_piece="Cahier des Clauses Techniques Particulières",
        sigle="CCTP",
        sous_titre=f"Lot {lot.code} – {lot.intitule}",
        pied=f"{projet.nom} – CCTP lot {lot.code} – indice {projet.indice}",
        nom_fichier=f"CCTP Lot {lot.code} - {lot.intitule}",
        chapitres=chapitres,
    )
