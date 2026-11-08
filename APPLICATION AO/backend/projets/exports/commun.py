"""Informations communes aux exports (page de garde, nom de fichier)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from django.utils import timezone
from django.utils.formats import date_format

from ..models import Projet
from ..structure import StructureLot

POLICES_PDF = {
    "Arial": "Arial, 'Liberation Sans', 'DejaVu Sans', sans-serif",
    "Calibri": "Calibri, Carlito, 'Liberation Sans', 'DejaVu Sans', sans-serif",
    "Times New Roman": "'Times New Roman', 'Liberation Serif', 'DejaVu Serif', serif",
}


@dataclass
class PageDeGarde:
    titre_piece: str
    sigle: str
    projet: Projet
    lot_code: str
    lot_intitule: str
    date: str

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


def page_de_garde(structure: StructureLot, titre_piece: str, sigle: str) -> PageDeGarde:
    projet = structure.lot.projet
    date = projet.date_document or timezone.localdate()
    return PageDeGarde(
        titre_piece=titre_piece,
        sigle=sigle,
        projet=projet,
        lot_code=structure.lot.code,
        lot_intitule=structure.lot.intitule,
        date=date_format(date, "j F Y"),
    )


def nom_fichier(sigle: str, structure: StructureLot, extension: str, suffixe: str = "") -> str:
    lot = structure.lot
    base = f"{sigle} Lot {lot.code} - {lot.intitule}{suffixe}"
    base = re.sub(r'[\\/:*?"<>|]+', "-", base).strip()
    return f"{base}.{extension}"
