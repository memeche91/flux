"""Numéros de lots : format accepté, comparaison et ordre de classement.

Le numéro d'un lot (« 03 », « 3a », « 10.1 », « TCE »…) apparaît dans les pièces écrites, les noms de fichiers
du DCE et les références de la GED : il reste court et sans caractère qui gênerait un nom de fichier.
"""
import re

# Lot « tous corps d'état » : ses documents couvrent plusieurs lots, retrouvés dans leurs titres (bibliothèque).
CODE_LOT_MULTI = "TCE"

LONGUEUR_CODE = 10
# Lettres (sans accent) et chiffres seulement : 03, 3a, 3bis, TCE. Ni point, ni tiret, ni espace : les articles sont
# numérotés « 03.2.1 » et la lecture des offres coupe les numéros sur ces signes ; un lot « 10.1 » ou « 10-1 » se
# confondrait avec le chapitre 1 du lot 10.
_CODE = re.compile(r"^[A-Za-z0-9]{1,%d}$" % LONGUEUR_CODE)
_NUMERO = re.compile(r"^([0-9]+)(.*)$")

MESSAGE_CODE = (
    "Numéro de lot invalide : 10 lettres (sans accent) ou chiffres au plus, sans espace ni signe "
    "(par exemple 03, 3a ou 3bis)."
)


def verifier_code(code: str | None) -> str:
    """Numéro nettoyé ; ValueError (message pour l'utilisateur) s'il est vide ou mal formé."""
    code = (code or "").strip()
    if not code:
        raise ValueError("Indiquez le numéro du lot.")
    if not _CODE.match(code):
        raise ValueError(MESSAGE_CODE)
    return code


def verifier_intitule(intitule: str | None, longueur: int) -> str:
    intitule = " ".join((intitule or "").split())
    if not intitule:
        raise ValueError("Indiquez l'intitulé du lot.")
    if len(intitule) > longueur:
        raise ValueError(f"Intitulé du lot trop long ({longueur} caractères au plus).")
    return intitule


def code_normalise(code: str) -> str:
    """Pour comparer deux numéros : « 8 », « 08 » et « 008 » désignent le même lot, « 3A » et « 3a » aussi."""
    code = code.strip().lower()
    # isascii : « ² » ou « ① » (saisis autrefois dans l'administration) ne sont pas des nombres pour int().
    return str(int(code)).zfill(2) if code.isascii() and code.isdigit() else code


def cle_tri(code: str) -> tuple:
    """Ordre des lots : TCE et les numéros sans chiffre en tête d'abord, puis 00, 01, 2, 3a, 3bis, 10…"""
    correspondance = _NUMERO.match(code.strip())
    if correspondance is None:
        return (0, 0, code.strip().lower())
    return (1, int(correspondance.group(1)), correspondance.group(2).lower())
