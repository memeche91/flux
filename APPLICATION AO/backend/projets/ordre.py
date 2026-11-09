"""Ordre des éléments d'un document (postes d'un lot, clauses d'une pièce écrite).

Un « CHAPITRE » se déplace avec tout ce qu'il contient ; les autres éléments
s'échangent avec leur voisin et peuvent ainsi changer de chapitre.
"""
from __future__ import annotations

from django.db import transaction

CHAPITRE = "CHAPITRE"


def renumeroter(objets: list) -> None:
    for indice, objet in enumerate(objets):
        objet.ordre = (indice + 1) * 10
    if objets:
        type(objets[0]).objects.bulk_update(objets, ["ordre"])


@transaction.atomic
def inserer(existants: list, nouveaux: list, apres_id: int | None = None) -> None:
    """Enregistre « nouveaux » (non encore en base) après l'élément « apres_id », ou à la fin."""
    if not nouveaux:
        return
    position = len(existants)
    if apres_id is not None:
        position = next((i + 1 for i, objet in enumerate(existants) if objet.pk == apres_id), len(existants))
        # Un nouveau chapitre se place après le contenu du chapitre sélectionné :
        # sinon il « adopterait » les éléments qui suivent la sélection.
        if any(objet.genre == CHAPITRE for objet in nouveaux):
            while position < len(existants) and existants[position].genre != CHAPITRE:
                position += 1
    for objet in nouveaux:
        objet.ordre = 0
    type(nouveaux[0]).objects.bulk_create(nouveaux)
    renumeroter(existants[:position] + nouveaux + existants[position:])


@transaction.atomic
def deplacer(objets: list, cible, sens: str) -> None:
    i = next(indice for indice, objet in enumerate(objets) if objet.pk == cible.pk)
    n = len(objets)
    if cible.genre != CHAPITRE:
        voisin = i - 1 if sens == "haut" else i + 1
        if 0 <= voisin < n:
            objets[i], objets[voisin] = objets[voisin], objets[i]
            renumeroter(objets)
        return

    fin = i + 1
    while fin < n and objets[fin].genre != CHAPITRE:
        fin += 1
    bloc = objets[i:fin]
    if sens == "haut":
        if i == 0:
            return
        debut_precedent = i - 1
        while debut_precedent > 0 and objets[debut_precedent].genre != CHAPITRE:
            debut_precedent -= 1
        renumeroter(objets[:debut_precedent] + bloc + objets[debut_precedent:i] + objets[fin:])
    else:
        if fin >= n:
            return
        fin_suivant = fin + 1
        while fin_suivant < n and objets[fin_suivant].genre != CHAPITRE:
            fin_suivant += 1
        renumeroter(objets[:i] + objets[fin:fin_suivant] + bloc + objets[fin_suivant:])
