"""Numérotation automatique et vue structurée d'un lot (pour l'écran et les exports).

Une seule structure produit le CCTP et la DPGF :
- CHAPITRE : « 8.1 Généralités »
- ARTICLE  : texte seul, uniquement dans le CCTP (« 8.1.1 Documents de référence »)
- OUVRAGE  : texte dans le CCTP + ligne chiffrée dans la DPGF (« 8.2.1 Fenêtres… »)
Les ouvrages rattachés à une PSE ou à une variante sont regroupés à part dans la DPGF.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from articles.normalisation import normaliser

from .models import GenrePoste, LotProjet, OptionLot, Poste


def prefixe_lot(code: str) -> str:
    return str(int(code)) if code.isascii() and code.isdigit() else code


def numeroter(postes: list[Poste], code_lot: str) -> dict[int, str]:
    prefixe = prefixe_lot(code_lot)
    numeros: dict[int, str] = {}
    chapitre = element = 0
    for poste in postes:
        if poste.genre == GenrePoste.CHAPITRE:
            chapitre += 1
            element = 0
            numeros[poste.pk] = f"{prefixe}.{chapitre}"
        else:
            element += 1
            numeros[poste.pk] = f"{prefixe}.{chapitre}.{element}"
    return numeros


@dataclass
class Element:
    poste: Poste
    numero: str
    option: OptionLot | None = None

    @property
    def titre_cctp(self) -> str:
        titre = self.poste.titre
        if self.option is None or normaliser(self.option.nom_court) in normaliser(titre):
            return titre  # mention déjà présente dans le titre (souvent le cas d'un CCTP repris)
        return f"{titre} ({self.option.nom_court})"


@dataclass
class Chapitre:
    numero: str
    titre: str
    elements: list[Element] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum((e.poste.montant or Decimal("0") for e in self.elements), Decimal("0"))


@dataclass
class SectionDPGF:
    titre: str
    option: OptionLot | None
    chapitres: list[Chapitre] = field(default_factory=list)

    @property
    def lignes(self) -> list[Element]:
        return [e for c in self.chapitres for e in c.elements]

    @property
    def total(self) -> Decimal:
        return sum((e.poste.montant or Decimal("0") for e in self.lignes), Decimal("0"))


@dataclass
class StructureLot:
    lot: LotProjet
    chapitres: list[Chapitre]
    sections_dpgf: list[SectionDPGF]
    numeros: dict[int, str]

    @property
    def total_base(self) -> Decimal:
        return self.sections_dpgf[0].total if self.sections_dpgf else Decimal("0")


def structurer(lot: LotProjet) -> StructureLot:
    postes = list(lot.postes.select_related("option").all())
    options = list(lot.options.all())
    numeros = numeroter(postes, lot.code)

    chapitres: list[Chapitre] = []
    courant: Chapitre | None = None
    for poste in postes:
        if poste.genre == GenrePoste.CHAPITRE:
            courant = Chapitre(numeros[poste.pk], poste.titre)
            chapitres.append(courant)
            continue
        if courant is None:
            courant = Chapitre(f"{prefixe_lot(lot.code)}.0", "")
            chapitres.append(courant)
        courant.elements.append(Element(poste, numeros[poste.pk], poste.option))

    def section(titre: str, option: OptionLot | None) -> SectionDPGF:
        resultat = SectionDPGF(titre, option)
        for chapitre in chapitres:
            ouvrages = [
                e
                for e in chapitre.elements
                if e.poste.genre == GenrePoste.OUVRAGE and (e.poste.option_id == (option.pk if option else None))
            ]
            if ouvrages:
                resultat.chapitres.append(Chapitre(chapitre.numero, chapitre.titre, ouvrages))
        return resultat

    sections = [section("Solution de base", None)]
    for option in options:
        sections.append(section(f"{option.nom_court} – {option.libelle}", option))
    return StructureLot(lot, chapitres, sections, numeros)
