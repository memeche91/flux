"""Indices de modification des documents : A, B, … Z, AA, AB… ou 0, 1, 2…

Un indice ne revient jamais en arrière : un nouvel indice saisi doit être strictement supérieur
au précédent. Les indices numériques (0, 1…) précèdent les indices alphabétiques (A, B…),
comme pour une diffusion « indice 0 » suivie d'indices de modification A, B…
"""
from __future__ import annotations

import re

FORMAT_INDICE = re.compile(r"^(\d{1,3}|[A-Z]{1,3}\d?)$")


def normaliser_indice(indice: str) -> str:
    """« Ind. b » → « B » : majuscules, sans le mot « indice »."""
    texte = (indice or "").strip().upper()
    texte = re.sub(r"^(INDICE|IND)\.?\s*", "", texte)
    return texte.replace(" ", "")


def indice_valide(indice: str) -> bool:
    return bool(FORMAT_INDICE.match(normaliser_indice(indice)))


def cle(indice: str) -> tuple:
    """0 < 1 < … < A < A1 < A2 < B < … < Z < AA."""
    indice = normaliser_indice(indice)
    if indice.isdigit():
        return (0, int(indice), "", 0)
    lettres = indice.rstrip("0123456789")
    sous = int(indice[len(lettres):] or 0)
    return (1, len(lettres), lettres, sous)


def indice_suivant(indice: str | None) -> str:
    """Indice qui suit : A → B, Z → AA, AZ → BA ; 0 → A ; 1 → 2. Sans indice précédent : A."""
    indice = normaliser_indice(indice or "")
    if not indice:
        return "A"
    if indice.isdigit():
        # « Indice 0 » = première diffusion : les modifications suivent en A, B…
        return "A" if int(indice) == 0 else str(int(indice) + 1)
    indice = indice.rstrip("0123456789")  # après A1 vient B
    lettres = list(indice)
    position = len(lettres) - 1
    while position >= 0:
        if lettres[position] != "Z":
            lettres[position] = chr(ord(lettres[position]) + 1)
            return "".join(lettres)
        lettres[position] = "A"
        position -= 1
    return "A" + "".join(lettres)


def superieur(nouveau: str, precedent: str | None) -> bool:
    return precedent is None or cle(nouveau) > cle(precedent)
