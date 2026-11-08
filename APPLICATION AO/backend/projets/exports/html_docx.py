"""Conversion du HTML de l'éditeur (déjà nettoyé) en contenu Word (python-docx).

Gère : paragraphes et alignement, gras / italique / souligné / barré, couleur,
surlignage, taille et police, titres h3/h4, listes à puces et numérotées
(imbriquées), tableaux avec fusion horizontale et couleur de fond des cellules.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

BALISES_VIDES = {"br", "col", "img", "hr"}
ALIGNEMENTS = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
SURLIGNAGE_PAR_DEFAUT = "FFF59D"


class Noeud:
    def __init__(self, balise: str, attributs=None, parent: Noeud | None = None, texte: str = ""):
        self.balise = balise
        self.attributs = dict(attributs or [])
        self.parent = parent
        self.enfants: list[Noeud] = []
        self.texte = texte

    @property
    def styles(self) -> dict[str, str]:
        resultat = {}
        for declaration in self.attributs.get("style", "").split(";"):
            if ":" in declaration:
                cle, valeur = declaration.split(":", 1)
                resultat[cle.strip().lower()] = valeur.strip()
        return resultat


class _Analyseur(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.racine = Noeud("racine")
        self.courant = self.racine

    def handle_starttag(self, balise, attributs):
        noeud = Noeud(balise, attributs, self.courant)
        self.courant.enfants.append(noeud)
        if balise not in BALISES_VIDES:
            self.courant = noeud

    def handle_endtag(self, balise):
        noeud = self.courant
        while noeud is not self.racine and noeud.balise != balise:
            noeud = noeud.parent
        if noeud is not self.racine:
            self.courant = noeud.parent

    def handle_data(self, donnees):
        self.courant.enfants.append(Noeud("#texte", parent=self.courant, texte=donnees))


def analyser(html: str) -> Noeud:
    analyseur = _Analyseur()
    analyseur.feed(html or "")
    analyseur.close()
    return analyseur.racine


def couleur_hex(valeur: str | None) -> str | None:
    """« #c00 », « #CC0000 », « rgb(204, 0, 0) » → « CC0000 »."""
    if not valeur:
        return None
    valeur = valeur.strip().lower()
    if re.fullmatch(r"#[0-9a-f]{6}", valeur):
        return valeur[1:].upper()
    if re.fullmatch(r"#[0-9a-f]{3}", valeur):
        return "".join(c * 2 for c in valeur[1:]).upper()
    correspondance = re.fullmatch(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*[\d.]+)?\)", valeur)
    if correspondance:
        return "".join(f"{min(int(c), 255):02X}" for c in correspondance.groups())
    return None


def taille_pt(valeur: str | None) -> float | None:
    correspondance = re.fullmatch(r"([\d.]+)\s*(pt|px)", (valeur or "").strip().lower())
    if not correspondance:
        return None
    nombre = float(correspondance.group(1))
    return nombre if correspondance.group(2) == "pt" else round(nombre * 0.75, 1)


def ombrer(element_proprietes, couleur: str):
    """Ajoute une couleur de fond (w:shd) à des propriétés de texte ou de cellule."""
    ombre = OxmlElement("w:shd")
    ombre.set(qn("w:val"), "clear")
    ombre.set(qn("w:color"), "auto")
    ombre.set(qn("w:fill"), couleur)
    element_proprietes.append(ombre)


class ConvertisseurHtmlDocx:
    def __init__(self, document, *, couleur_entetes: str = "D9E2F3"):
        self.document = document
        self.couleur_entetes = couleur_entetes.lstrip("#").upper()

    def ajouter(self, html: str, conteneur=None):
        conteneur = conteneur if conteneur is not None else self.document
        self._blocs(analyser(html).enfants, conteneur, profondeur_liste=0)

    # --- Blocs ---------------------------------------------------------------

    def _nouveau_paragraphe(self, conteneur):
        # Une cellule de tableau contient déjà un paragraphe vide : on le réutilise.
        paragraphes = getattr(conteneur, "paragraphs", [])
        if hasattr(conteneur, "_tc") and len(paragraphes) == 1 and not paragraphes[0].text and not paragraphes[0].runs:
            return paragraphes[0]
        return conteneur.add_paragraph()

    def _blocs(self, noeuds, conteneur, profondeur_liste: int):
        en_ligne: list[Noeud] = []

        def vider():
            if any(n.balise != "#texte" or n.texte.strip() for n in en_ligne):
                paragraphe = self._nouveau_paragraphe(conteneur)
                self._en_ligne(en_ligne, paragraphe, {})
            en_ligne.clear()

        for noeud in noeuds:
            balise = noeud.balise
            if balise in {"p", "h1", "h2", "h3", "h4", "blockquote"}:
                vider()
                if balise == "blockquote":
                    self._blocs(noeud.enfants, conteneur, profondeur_liste)
                    continue
                paragraphe = self._nouveau_paragraphe(conteneur)
                alignement = ALIGNEMENTS.get(noeud.styles.get("text-align", ""))
                if alignement is not None:
                    paragraphe.alignment = alignement
                format_titre = {}
                if balise in {"h1", "h2", "h3", "h4"}:
                    format_titre = {"gras": True, "taille": {"h1": 14, "h2": 13, "h3": 12, "h4": 11}[balise]}
                    paragraphe.paragraph_format.space_before = Pt(6)
                    paragraphe.paragraph_format.keep_with_next = True
                self._en_ligne(noeud.enfants, paragraphe, format_titre)
            elif balise in {"ul", "ol"}:
                vider()
                self._liste(noeud, conteneur, profondeur_liste + 1)
            elif balise == "table":
                vider()
                self._tableau(noeud, conteneur)
            elif balise in {"div", "section", "tbody", "thead"}:
                vider()
                self._blocs(noeud.enfants, conteneur, profondeur_liste)
            else:
                en_ligne.append(noeud)
        vider()

    def _liste(self, liste: Noeud, conteneur, profondeur: int):
        numero = 0
        for element in liste.enfants:
            if element.balise != "li":
                continue
            numero += 1
            marqueur = f"{numero}." if liste.balise == "ol" else "•"
            contenu_en_ligne = [n for n in element.enfants if n.balise not in {"ul", "ol", "p"}]
            premier_paragraphe = next((n for n in element.enfants if n.balise == "p"), None)
            paragraphe = self._nouveau_paragraphe(conteneur)
            format_paragraphe = paragraphe.paragraph_format
            format_paragraphe.left_indent = Cm(0.63 * profondeur)
            format_paragraphe.first_line_indent = Cm(-0.5)
            format_paragraphe.space_after = Pt(2)
            paragraphe.add_run(f"{marqueur}\t")
            format_paragraphe.tab_stops.add_tab_stop(Cm(0.63 * profondeur))
            self._en_ligne((premier_paragraphe.enfants if premier_paragraphe else []) + contenu_en_ligne, paragraphe, {})
            autres_paragraphes = [n for n in element.enfants if n.balise == "p" and n is not premier_paragraphe]
            for autre in autres_paragraphes:
                suite = self._nouveau_paragraphe(conteneur)
                suite.paragraph_format.left_indent = Cm(0.63 * profondeur)
                self._en_ligne(autre.enfants, suite, {})
            for sous_liste in (n for n in element.enfants if n.balise in {"ul", "ol"}):
                self._liste(sous_liste, conteneur, profondeur + 1)

    def _tableau(self, tableau: Noeud, conteneur):
        rangees: list[Noeud] = []

        def collecter(noeud: Noeud):
            for enfant in noeud.enfants:
                if enfant.balise == "tr":
                    rangees.append(enfant)
                elif enfant.balise in {"thead", "tbody", "tfoot"}:
                    collecter(enfant)

        collecter(tableau)
        if not rangees:
            return
        cellules_par_rangee = [[c for c in r.enfants if c.balise in {"td", "th"}] for r in rangees]
        largeur = max(sum(int(c.attributs.get("colspan") or 1) for c in cellules) for cellules in cellules_par_rangee)
        if largeur == 0:
            return
        table = conteneur.add_table(rows=len(rangees), cols=largeur)
        table.style = "Table Grid"
        for indice_rangee, cellules in enumerate(cellules_par_rangee):
            colonne = 0
            for cellule_html in cellules:
                if colonne >= largeur:
                    break
                etendue = max(1, min(int(cellule_html.attributs.get("colspan") or 1), largeur - colonne))
                cellule = table.cell(indice_rangee, colonne)
                if etendue > 1:
                    cellule = cellule.merge(table.cell(indice_rangee, colonne + etendue - 1))
                fond = couleur_hex(cellule_html.styles.get("background-color"))
                if cellule_html.balise == "th" and not fond:
                    fond = self.couleur_entetes
                if fond:
                    ombrer(cellule._tc.get_or_add_tcPr(), fond)
                self._blocs(cellule_html.enfants, cellule, 0)
                if cellule_html.balise == "th":
                    for paragraphe in cellule.paragraphs:
                        for morceau in paragraphe.runs:
                            morceau.bold = True
                colonne += etendue
        # Espace après le tableau (sinon le paragraphe suivant le colle).
        if hasattr(conteneur, "add_paragraph") and not hasattr(conteneur, "_tc"):
            conteneur.add_paragraph()

    # --- Texte en ligne --------------------------------------------------------

    def _en_ligne(self, noeuds, paragraphe, format_herite: dict):
        for noeud in noeuds:
            if noeud.balise == "#texte":
                texte = re.sub(r"\s+", " ", noeud.texte)
                if texte:
                    self._appliquer(paragraphe.add_run(texte), format_herite)
                continue
            if noeud.balise == "br":
                paragraphe.add_run().add_break()
                continue
            format_enfant = dict(format_herite)
            balise = noeud.balise
            if balise in {"strong", "b"}:
                format_enfant["gras"] = True
            elif balise in {"em", "i"}:
                format_enfant["italique"] = True
            elif balise == "u":
                format_enfant["souligne"] = True
            elif balise in {"s", "strike", "del"}:
                format_enfant["barre"] = True
            elif balise == "sub":
                format_enfant["indice"] = True
            elif balise == "sup":
                format_enfant["exposant"] = True
            elif balise == "mark":
                format_enfant["fond"] = (
                    couleur_hex(noeud.styles.get("background-color"))
                    or couleur_hex(noeud.attributs.get("data-color"))
                    or SURLIGNAGE_PAR_DEFAUT
                )
            styles = noeud.styles
            if couleur_hex(styles.get("color")):
                format_enfant["couleur"] = couleur_hex(styles["color"])
            if balise != "mark" and couleur_hex(styles.get("background-color")):
                format_enfant["fond"] = couleur_hex(styles["background-color"])
            if taille_pt(styles.get("font-size")):
                format_enfant["taille"] = taille_pt(styles["font-size"])
            if styles.get("font-family"):
                format_enfant["police"] = styles["font-family"].split(",")[0].strip().strip("'\"")
            if styles.get("font-weight") in {"bold", "600", "700", "800", "900"}:
                format_enfant["gras"] = True
            if styles.get("font-style") == "italic":
                format_enfant["italique"] = True
            if "underline" in styles.get("text-decoration", ""):
                format_enfant["souligne"] = True
            self._en_ligne(noeud.enfants, paragraphe, format_enfant)

    @staticmethod
    def _appliquer(morceau, format_texte: dict):
        if format_texte.get("gras"):
            morceau.bold = True
        if format_texte.get("italique"):
            morceau.italic = True
        if format_texte.get("souligne"):
            morceau.underline = True
        if format_texte.get("barre"):
            morceau.font.strike = True
        if format_texte.get("indice"):
            morceau.font.subscript = True
        if format_texte.get("exposant"):
            morceau.font.superscript = True
        if format_texte.get("couleur"):
            morceau.font.color.rgb = RGBColor.from_string(format_texte["couleur"])
        if format_texte.get("taille"):
            morceau.font.size = Pt(format_texte["taille"])
        if format_texte.get("police"):
            morceau.font.name = format_texte["police"]
        if format_texte.get("fond"):
            ombrer(morceau._r.get_or_add_rPr(), format_texte["fond"])
