"""Extraction du texte des documents importés.

Le texte extrait alimentera l'étape suivante : découpage en articles par lot
et apprentissage du style de rédaction par l'assistant IA local.
Les titres Word sont conservés sous forme « # Titre » pour garder la structure.
"""
import re
from pathlib import Path

EXTENSIONS_ACCEPTEES = {
    ".pdf",
    ".docx",
    ".doc",
    ".odt",
    ".rtf",
    ".xlsx",
    ".xlsm",
    ".xls",
    ".ods",
    ".csv",
}
EXTENSIONS_ANALYSEES = {".pdf", ".docx", ".xlsx", ".xlsm", ".csv"}

_TITRE = re.compile(r"^(?:heading|titre)\s*(\d)$", re.IGNORECASE)


class FormatNonAnalyse(Exception):
    """Le fichier est conservé mais son contenu n'est pas lu automatiquement."""


def extraire_texte(chemin: Path) -> str:
    extension = chemin.suffix.lower()
    if extension == ".docx":
        texte = _texte_docx(chemin)
    elif extension in {".xlsx", ".xlsm"}:
        texte = _texte_xlsx(chemin)
    elif extension == ".pdf":
        texte = _texte_pdf(chemin)
    elif extension == ".csv":
        texte = _texte_csv(chemin)
    else:
        raise FormatNonAnalyse(
            f"Format {extension} conservé. Pour l'analyser, enregistrez-le en .docx, .xlsx ou .pdf."
        )
    # PostgreSQL refuse le caractère nul dans un champ texte.
    return texte.replace("\x00", "").strip()


def _texte_docx(chemin: Path) -> str:
    from docx import Document
    from docx.table import Table

    document = Document(str(chemin))
    lignes: list[str] = []
    for bloc in document.iter_inner_content():
        if isinstance(bloc, Table):
            lignes.extend(_lignes_tableau(bloc))
            continue
        texte = bloc.text.strip()
        if not texte:
            continue
        nom_style = bloc.style.name if bloc.style is not None else ""
        correspondance = _TITRE.match(nom_style or "")
        if correspondance:
            lignes.append(f"{'#' * int(correspondance.group(1))} {texte}")
        else:
            lignes.append(texte)
    return "\n".join(lignes)


def _lignes_tableau(tableau) -> list[str]:
    lignes = []
    for rangee in tableau.rows:
        cellules: list[str] = []
        precedente = None
        for cellule in rangee.cells:
            # Les cellules fusionnées sont renvoyées plusieurs fois : on les dédoublonne.
            if precedente is not None and cellule._tc is precedente:
                continue
            precedente = cellule._tc
            cellules.append(" ".join(cellule.text.split()))
        if any(cellules):
            lignes.append(" | ".join(cellules))
    return lignes


def _texte_xlsx(chemin: Path) -> str:
    from openpyxl import load_workbook

    classeur = load_workbook(str(chemin), read_only=True, data_only=True)
    try:
        lignes: list[str] = []
        for feuille in classeur.worksheets:
            lignes.append(f"## Feuille : {feuille.title}")
            for rangee in feuille.iter_rows(values_only=True):
                valeurs = [_formater_cellule(v) for v in rangee if v not in (None, "")]
                if valeurs:
                    lignes.append(" | ".join(valeurs))
        return "\n".join(lignes)
    finally:
        classeur.close()


def _formater_cellule(valeur) -> str:
    if isinstance(valeur, float) and valeur.is_integer():
        return str(int(valeur))
    return " ".join(str(valeur).split())


def _texte_pdf(chemin: Path) -> str:
    import pdfplumber

    with pdfplumber.open(str(chemin)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    texte = "\n".join(pages).strip()
    if not texte:
        raise FormatNonAnalyse(
            "PDF sans texte (document scanné). La reconnaissance de texte (OCR) arrive à l'étape suivante."
        )
    return texte


def _texte_csv(chemin: Path) -> str:
    contenu = chemin.read_bytes()
    for encodage in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return contenu.decode(encodage)
        except UnicodeDecodeError:
            continue
    return contenu.decode("utf-8", errors="replace")
