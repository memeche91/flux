"""Conversions de texte communes à l'indexation, à la recherche et à la voix."""
from __future__ import annotations

import re
from html import unescape

from articles.normalisation import normaliser

MOTS_VIDES = set(
    """au aux avec ce ces cet cette dans de des du elle en et est il ils je la le les leur lui ma mais me mes moi mon ne nos
    notre nous on ou où par pas pour qu que qui sa se ses son sont sur ta te tes toi ton tu un une vos votre vous y
    quel quelle quels quelles comment combien quoi dont été être avoir fait faire peux peut puis donne donner dis dire
    moi stp svp merci bonjour selon entre sans sous plus moins très tout tous toute toutes""".split()
)


def html_vers_texte(html: str) -> str:
    texte = re.sub(r"<br\s*/?>", "\n", html or "")
    texte = re.sub(r"</(p|li|tr|h\d)>", "\n", texte)
    texte = re.sub(r"</t[dh]>", " | ", texte)
    texte = re.sub(r"<[^>]+>", "", texte)
    lignes = [" ".join(ligne.split()) for ligne in unescape(texte).splitlines()]
    return "\n".join(ligne.strip(" |") for ligne in lignes if ligne.strip(" |"))


def mots_cles(texte: str) -> list[str]:
    return [mot for mot in normaliser(texte).split() if len(mot) >= 3 and mot not in MOTS_VIDES]


def tronquer(texte: str, longueur: int) -> str:
    texte = texte.strip()
    if len(texte) <= longueur:
        return texte
    coupe = texte[:longueur].rsplit(" ", 1)[0]
    return coupe.rstrip(" ,;:") + " …"
