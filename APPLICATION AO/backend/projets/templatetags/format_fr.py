from decimal import Decimal

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

ESPACE_FINE = " "


def _grouper(entier: str) -> str:
    groupes = []
    while len(entier) > 3:
        groupes.insert(0, entier[-3:])
        entier = entier[:-3]
    groupes.insert(0, entier)
    return ESPACE_FINE.join(groupes)


@register.filter
def euros(valeur) -> str:
    """1234.5 → « 1 234,50 € » ; vide si None."""
    if valeur is None or valeur == "":
        return ""
    nombre = Decimal(str(valeur)).quantize(Decimal("0.01"))
    signe = "-" if nombre < 0 else ""
    entier, decimales = f"{abs(nombre):.2f}".split(".")
    return f"{signe}{_grouper(entier)},{decimales}{ESPACE_FINE}€"


@register.filter
def quantite(valeur) -> str:
    if valeur is None or valeur == "":
        return ""
    nombre = Decimal(str(valeur)).normalize()
    texte = f"{nombre:f}"
    entier, _, decimales = texte.partition(".")
    signe = "-" if entier.startswith("-") else ""
    entier = entier.lstrip("-")
    return f"{signe}{_grouper(entier)}" + (f",{decimales}" if decimales else "")


@register.filter
def chaine_css(valeur) -> str:
    """Texte inséré dans une chaîne CSS (pied de page) : guillemets et balises neutralisés."""
    texte = " ".join(str(valeur or "").split())
    texte = texte.replace("\\", "\\\\").replace('"', '\\"').replace("<", "\\3C ")
    return mark_safe(texte)
