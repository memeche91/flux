"""Nettoyage du HTML produit par l'éditeur visuel (protection contre l'injection de code).

Seules les balises et propriétés de mise en forme utiles aux pièces écrites sont
conservées ; tout le reste (scripts, liens javascript:, positionnement…) est retiré.
"""
import re
from html import escape

import nh3

BALISES = {
    "p", "br", "strong", "b", "em", "i", "u", "s", "span", "mark", "sub", "sup",
    "h3", "h4", "ul", "ol", "li", "blockquote",
    "table", "thead", "tbody", "tr", "th", "td",
}
ATTRIBUTS = {
    "*": {"style"},
    "td": {"style", "colspan", "rowspan"},
    "th": {"style", "colspan", "rowspan"},
    "mark": {"style", "data-color"},
}
PROPRIETES_CSS = {
    "color", "background-color", "font-size", "font-family", "font-weight",
    "font-style", "text-decoration", "text-align",
}


# Caractères interdits en XML 1.0 : ils rendraient l'export Word impossible. Les sauts
# de ligne et de page de Word (\x0b, \x0c) deviennent des espaces, le reste disparaît.
_SAUTS = re.compile("[\x0b\x0c]")
_CONTROLE = re.compile("[\x00-\x08\x0e-\x1f\ufffe\uffff]")


def sans_controle(texte: str) -> str:
    return _CONTROLE.sub("", _SAUTS.sub(" ", texte or ""))


def texte_propre(texte: str) -> str:
    """Texte saisi sur une ligne (titre, nom) : sans caractères de contrôle ni espaces superflus."""
    return " ".join(sans_controle(texte).split())


def nettoyer_html(html: str) -> str:
    if not html:
        return ""
    return nh3.clean(
        sans_controle(html),
        tags=BALISES,
        attributes=ATTRIBUTS,
        filter_style_properties=PROPRIETES_CSS,
        link_rel=None,
    ).strip()


def texte_vers_html(texte: str) -> str:
    """Convertit le texte brut d'un article de la bibliothèque en paragraphes HTML."""
    paragraphes = [p.strip() for p in re.split(r"\n+", sans_controle(texte)) if p.strip()]
    lignes = []
    for paragraphe in paragraphes:
        if " | " in paragraphe:  # ligne de tableau extraite d'un document Word
            cellules = "".join(f"<td><p>{escape(c.strip())}</p></td>" for c in paragraphe.split(" | "))
            lignes.append(f"<table><tbody><tr>{cellules}</tr></tbody></table>")
        else:
            lignes.append(f"<p>{escape(paragraphe)}</p>")
    # Fusionne les lignes de tableau consécutives en un seul tableau.
    html = "".join(lignes)
    return html.replace("</tbody></table><table><tbody>", "")
