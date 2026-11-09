"""Export d'une pièce écrite (CCTP, CCAP, RC, acte d'engagement) au format Word (.docx).

Page de garde, sommaire automatique (champ TOC mis à jour par Word à l'ouverture),
titres numérotés (styles Titre 1 / Titre 2), descriptions mises en forme,
pied de page « Page X / Y ».
"""
from __future__ import annotations

import io

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from ..html import sans_controle as _t
from ..structure import StructureLot
from .document import DocumentExport, document_cctp
from .html_docx import ConvertisseurHtmlDocx, ombrer


def _police(style, nom: str, taille: float | None = None, couleur: str | None = None, gras: bool | None = None):
    style.font.name = nom
    proprietes = style.element.get_or_add_rPr()
    polices = proprietes.find(qn("w:rFonts"))
    if polices is None:
        polices = OxmlElement("w:rFonts")
        proprietes.append(polices)
    for attribut in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        polices.set(qn(attribut), nom)
    # Les polices « de thème » du modèle Word l'emporteraient sur la police choisie.
    for attribut in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
        if polices.get(qn(attribut)) is not None:
            del polices.attrib[qn(attribut)]
    if taille:
        style.font.size = Pt(taille)
    if couleur:
        style.font.color.rgb = RGBColor.from_string(couleur)
    if gras is not None:
        style.font.bold = gras


def _champ(paragraphe, instruction: str, texte_provisoire: str = ""):
    """Insère un champ Word (PAGE, NUMPAGES, TOC…)."""
    def caractere(type_champ):
        morceau = paragraphe.add_run()
        element = OxmlElement("w:fldChar")
        element.set(qn("w:fldCharType"), type_champ)
        if type_champ == "begin":
            element.set(qn("w:dirty"), "true")
        morceau._r.append(element)
        return morceau

    caractere("begin")
    morceau = paragraphe.add_run()
    code = OxmlElement("w:instrText")
    code.set(qn("xml:space"), "preserve")
    code.text = f" {instruction} "
    morceau._r.append(code)
    caractere("separate")
    paragraphe.add_run(texte_provisoire)
    caractere("end")


def _mettre_a_jour_champs_a_l_ouverture(document):
    reglages = document.settings.element
    element = OxmlElement("w:updateFields")
    element.set(qn("w:val"), "true")
    reglages.append(element)


def exporter_cctp_docx(structure: StructureLot) -> bytes:
    return exporter_docx(document_cctp(structure))


def exporter_docx(doc: DocumentExport) -> bytes:
    """Pièce écrite au format Word : page de garde, sommaire, titres numérotés, pied de page paginé."""
    projet = doc.projet
    couleur = projet.couleur_titres.lstrip("#").upper()
    couleur_tableaux = projet.couleur_tableaux.lstrip("#").upper()

    document = Document()
    section = document.sections[0]
    section.page_height, section.page_width = Cm(29.7), Cm(21)
    section.top_margin = section.bottom_margin = Cm(2)
    section.left_margin = section.right_margin = Cm(2)

    styles = document.styles
    _police(styles["Normal"], projet.police, projet.taille_police)
    styles["Normal"].paragraph_format.space_after = Pt(4)
    _police(styles["Heading 1"], projet.police, projet.taille_police + 4, couleur, True)
    _police(styles["Heading 2"], projet.police, projet.taille_police + 1.5, couleur, True)
    _police(styles["Title"], projet.police, 24, couleur, True)
    styles["Heading 1"].paragraph_format.space_before = Pt(18)
    styles["Heading 1"].paragraph_format.page_break_before = False
    styles["Heading 2"].paragraph_format.space_before = Pt(12)

    # --- Page de garde ---
    for _ in range(3):
        document.add_paragraph()
    if projet.maitre_ouvrage:
        p = document.add_paragraph(_t(projet.maitre_ouvrage.upper()))
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.runs[0].font.size = Pt(12)
    p = document.add_paragraph(_t(projet.nom))
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.runs[0].font.size = Pt(20)
    p.runs[0].bold = True
    if projet.adresse_operation:
        p = document.add_paragraph(_t(projet.adresse_operation))
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    document.add_paragraph()

    bandeau = document.add_table(rows=1, cols=1)
    bandeau.alignment = WD_TABLE_ALIGNMENT.CENTER
    cellule = bandeau.cell(0, 0)
    ombrer(cellule._tc.get_or_add_tcPr(), couleur)
    for texte, taille in ((_t(doc.titre_piece.upper()), 16), (_t(doc.sous_titre.upper()), 14)):
        if not texte:
            continue
        p = cellule.paragraphs[0] if not cellule.paragraphs[0].text else cellule.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(8)
        morceau = p.add_run(texte)
        morceau.bold = True
        morceau.font.size = Pt(taille)
        morceau.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    document.add_paragraph()

    tableau = document.add_table(rows=0, cols=2)
    tableau.style = "Table Grid"
    for libelle, valeur in [*doc.lignes_operation, ("Phase", f"{projet.phase} – indice {projet.indice}"), ("Date", doc.date)]:
        cellules = tableau.add_row().cells
        ombrer(cellules[0]._tc.get_or_add_tcPr(), couleur_tableaux)
        cellules[0].paragraphs[0].add_run(_t(libelle)).bold = True
        cellules[1].paragraphs[0].add_run(_t(valeur))
        cellules[0].width, cellules[1].width = Cm(5), Cm(12)

    # --- Sommaire (nouvelle section : pied de page numéroté) ---
    corps = document.add_section(WD_SECTION.NEW_PAGE)
    corps.footer.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    pied = corps.footer.paragraphs[0]
    largeur_texte = section.page_width - section.left_margin - section.right_margin
    taquets = pied.paragraph_format.tab_stops
    for position in (Cm(8.255), Cm(16.51)):  # taquets du modèle Word par défaut
        taquets.add_tab_stop(position, WD_TAB_ALIGNMENT.CLEAR)
    taquets.add_tab_stop(largeur_texte, WD_TAB_ALIGNMENT.RIGHT)
    pied.text = f"{_t(doc.pied)}\tPage "
    pied.style.font.size = Pt(8)
    _champ(pied, "PAGE", "1")
    pied.add_run(" / ")
    _champ(pied, "NUMPAGES", "1")

    if doc.sommaire:
        document.add_paragraph("Sommaire", style="Title")
        entrees = []
        for chapitre in doc.chapitres:
            if chapitre.intitule:
                entrees.append(chapitre.intitule)
            entrees.extend(f"    {e.intitule}" for e in chapitre.elements)
        sommaire = document.add_paragraph()
        _champ(sommaire, 'TOC \\o "1-2" \\h \\z \\u', _t("\n".join(entrees)) or "Mettez à jour le sommaire (F9).")
        sommaire.add_run().add_break(WD_BREAK.PAGE)

    # --- Contenu ---
    convertisseur = ConvertisseurHtmlDocx(document, couleur_entetes=couleur_tableaux)
    for chapitre in doc.chapitres:
        if chapitre.intitule:
            document.add_heading(_t(chapitre.intitule), level=1)
        if chapitre.html:
            convertisseur.ajouter(chapitre.html)
        for element in chapitre.elements:
            document.add_heading(_t(element.intitule), level=2)
            if element.html:
                convertisseur.ajouter(element.html)

    _mettre_a_jour_champs_a_l_ouverture(document)
    flux = io.BytesIO()
    document.save(flux)
    return flux.getvalue()
