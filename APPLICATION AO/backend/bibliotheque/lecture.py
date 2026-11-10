"""Lecture des documents importés.

- Conversion des anciens formats (.doc, .xls, .odt, .rtf, .ods) avec LibreOffice.
- Word (.docx) : titres (styles et numérotation automatique), paragraphes, tableaux.
- Excel (.xlsx), CSV : tableaux de cellules.
- PDF : texte page par page, OCR (Tesseract) des pages scannées, tableaux.

Le résultat (ContenuDocument) est ensuite découpé en articles ou en lignes de prix.
"""
from __future__ import annotations

import csv
import posixpath
import re
import shutil
import subprocess
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

from articles.normalisation import separer_numero, texte_cellule

EXTENSIONS_ACCEPTEES = {".pdf", ".docx", ".doc", ".odt", ".rtf", ".xlsx", ".xlsm", ".xls", ".ods", ".csv"}
CONVERSIONS = {".doc": "docx", ".odt": "docx", ".rtf": "docx", ".xls": "xlsx", ".ods": "xlsx"}

# Garde-fous contre les fichiers fabriqués pour épuiser la mémoire du worker (bombes zip, page géante).
# Un .docx est chargé en entier en mémoire (python-docx). D'un .xlsx, openpyxl ne lit au fil de l'eau
# que les feuilles de calcul : il lit tout le reste en entier, même en lecture seule.
XML_LU_EN_ENTIER_MAX = 100 * 1024 * 1024
DOCX_DECOMPRESSE_MAX = 500 * 1024 * 1024  # toute l'archive décompressée (.docx, .xlsx et .xlsm)
TYPE_CHAINES_PARTAGEES = "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"
TYPE_FEUILLE = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
TYPES_CLASSEUR = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.template.main+xml",
    "application/vnd.ms-excel.sheet.macroEnabled.main+xml",
    "application/vnd.ms-excel.template.macroEnabled.main+xml",
}
LIEN_FEUILLE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
# Parties qu'openpyxl lit en entier sous un nom fixe (les autres sont repérées par leur type ou par les liens).
PARTIES_LUES_PAR_NOM = {
    "[Content_Types].xml", "xl/workbook.xml", "xl/styles.xml", "xl/theme/theme1.xml", "docProps/core.xml", "docProps/custom.xml",
}
XML_COURT_MAX = 5 * 1024 * 1024  # [Content_Types].xml et liens (.rels) lus pour repérer les feuilles
# Feuilles lues au fil de l'eau : openpyxl garde pourtant en mémoire chaque élément XML parcouru (environ
# 90 octets pour « <x/> », 4 octets du fichier). Au pire, 100 Mo de feuilles prennent 2,5 Go. Une feuille
# citée plusieurs fois par le classeur est analysée, et comptée, à chaque citation.
FEUILLES_MAX = 100 * 1024 * 1024
LIGNES_PAR_CLASSEUR_MAX = 200_000  # lignes lues, toutes feuilles confondues
COLONNES_MAX = 256  # une dimension déclarée « A1:XFD… » ferait compléter chaque ligne à 16 384 cellules
PIXELS_OCR_MAX = 40_000_000  # une page A4 ou A3 garde ses 300 dpi ; une page A0 passe à environ 160 dpi
MESSAGE_DECOMPRESSION = "Fichier anormalement volumineux une fois décompressé : il n’a pas été lu."


class FormatNonAnalyse(Exception):
    """Le fichier est conservé mais son contenu ne peut pas être lu automatiquement."""


class ErreurLecture(Exception):
    """Le fichier n'a pas pu être lu ou converti (protégé, endommagé…)."""


@dataclass
class Bloc:
    genre: str  # « titre », « texte » ou « tableau »
    texte: str = ""
    niveau: int = 0
    numero: str = ""
    gras: bool = False
    lignes: list[list[str]] = field(default_factory=list)


@dataclass
class Tableau:
    titre: str
    lignes: list[list]


@dataclass
class ContenuDocument:
    blocs: list[Bloc] = field(default_factory=list)
    tableaux: list[Tableau] = field(default_factory=list)
    pages_ocr: int = 0
    converti_depuis: str = ""

    def texte(self) -> str:
        lignes: list[str] = []
        if self.blocs:
            for bloc in self.blocs:
                if bloc.genre == "titre":
                    intitule = " ".join(p for p in (bloc.numero, bloc.texte) if p)
                    lignes.append(f"{'#' * max(bloc.niveau, 1)} {intitule}")
                elif bloc.genre == "tableau":
                    lignes.extend(" | ".join(ligne) for ligne in bloc.lignes)
                else:
                    lignes.append(bloc.texte)
        else:
            for tableau in self.tableaux:
                lignes.append(f"## {tableau.titre}")
                for ligne in tableau.lignes:
                    valeurs = [texte_cellule(v) for v in ligne if v not in (None, "")]
                    if valeurs:
                        lignes.append(" | ".join(valeurs))
        return "\n".join(lignes).replace("\x00", "").strip()


def lire_document(chemin: Path, dossier_travail: Path, *, tableaux_pdf: bool = False) -> ContenuDocument:
    extension = chemin.suffix.lower()
    converti_depuis = ""
    if extension in CONVERSIONS:
        chemin = convertir(chemin, CONVERSIONS[extension], dossier_travail)
        converti_depuis = extension
        extension = chemin.suffix.lower()

    from pdfminer.pdfparser import PDFSyntaxError
    from pdfplumber.utils.exceptions import PdfminerException

    try:
        if extension in {".docx", ".xlsx", ".xlsm"} and decompression_excessive(chemin, extension):
            raise ErreurLecture(MESSAGE_DECOMPRESSION)
        if extension == ".docx":
            contenu = _lire_docx(chemin)
        elif extension in {".xlsx", ".xlsm"}:
            contenu = _lire_xlsx(chemin)
        elif extension == ".pdf":
            contenu = _lire_pdf(chemin, dossier_travail, tableaux_pdf)
        elif extension == ".csv":
            contenu = _lire_csv(chemin)
        else:
            raise FormatNonAnalyse(f"Format {extension} non pris en charge.")
    except (zipfile.BadZipFile, PDFSyntaxError, PdfminerException) as erreur:
        raise ErreurLecture(
            "Fichier illisible : il est peut-être protégé par un mot de passe ou endommagé."
        ) from erreur
    contenu.converti_depuis = converti_depuis
    return contenu


def decompression_excessive(source, extension: str) -> bool:
    """Bombe zip : l'archive, ou ses parties lues en entier, dépassent-elles la limite une fois décompressées ?

    Seule la taille annoncée par l'archive est lue (rien n'est décompressé, sauf [Content_Types].xml et les
    liens d'un classeur, de petite taille, et le classeur lui-même, lu au fil de l'eau) : une taille mensongère
    est sans danger, zipfile s'arrête à cette taille puis signale une archive endommagée.
    source : chemin ou flux binaire d'un .docx, .xlsx ou .xlsm.
    """
    with zipfile.ZipFile(source) as archive:
        entrees = archive.infolist()
        if sum(i.file_size for i in entrees) > DOCX_DECOMPRESSE_MAX:
            return True
        if extension.lower() == ".docx":
            return _xml_docx(archive) > XML_LU_EN_ENTIER_MAX
        lues, feuilles = _parties_xlsx(archive)
        citations = _citations_feuilles(archive)
        if citations is None:
            return True  # citations inconnues : une feuille citée mille fois passerait inaperçue
        en_entier = en_flux = 0
        for info in entrees:
            nom = info.filename.lower()
            # openpyxl analyse une partie autant de fois que le classeur la cite comme feuille.
            taille = info.file_size * max(1, citations[nom])
            if nom in feuilles:
                en_flux += taille
            elif nom in lues or nom.endswith((".xml", ".rels")):
                en_entier += taille
        return en_entier > XML_LU_EN_ENTIER_MAX or en_flux > FEUILLES_MAX


def _xml_docx(archive: zipfile.ZipFile) -> int:
    """Taille décompressée des parties d'un .docx que python-docx analyse en entier.

    python-docx ne regarde pas le nom d'une partie mais le type déclaré dans [Content_Types].xml (Override,
    sinon Default de l'extension) : « word/document.bin » déclaré comme document principal est lu en entier.
    Sont comptées les parties nommées .xml ou .rels et celles dont le type déclaré est XML, quel que soit leur
    nom. Dans le doute ([Content_Types].xml démesuré ou illisible), tout est compté.
    """
    entrees = archive.infolist()
    try:
        types = _xml_court(archive, "[Content_Types].xml")
    except ValueError:
        return sum(i.file_size for i in entrees)
    defauts: dict[str, str] = {}
    surcharges: dict[str, str] = {}
    for element in types.iter() if types is not None else ():
        if element.tag.endswith("Default"):
            defauts[(element.get("Extension") or "").lower()] = element.get("ContentType") or ""
        elif element.tag.endswith("Override"):
            surcharges[(element.get("PartName") or "").lower()] = element.get("ContentType") or ""
    total = 0
    for info in entrees:
        nom = info.filename.lower()
        # Clés calculées comme python-docx : nom de partie « /<entrée> », extension sans le point, sans casse.
        type_ = surcharges.get("/" + nom) or defauts.get(posixpath.splitext(nom)[1][1:], "")
        if nom.endswith((".xml", ".rels")) or type_.lower().endswith("xml"):
            total += info.file_size
    return total


PARTIES_SUIVIES_MAX = 1000  # liens suivis de proche en proche dans un classeur ; au-delà, tout est compté


def _parties_xlsx(archive: zipfile.ZipFile) -> tuple[set[str], set[str]]:
    """Parties d'un classeur lues en entier par openpyxl, quel que soit leur nom, et feuilles lues au fil de l'eau.

    Lues en entier : le classeur et la table des chaînes (repérés par leur type dans [Content_Types].xml),
    les parties à nom fixe, et les parties désignées par les liens du classeur, de proche en proche
    (feuilles de graphique, liens externes, dessins…, même par un lien « External »), dont le nom est libre.
    Une feuille déclarée dans [Content_Types].xml n'est pas comptée, sauf si elle est aussi lue en entier.
    Dans le doute ([Content_Types].xml ou liens démesurés, illisibles), tout est compté. Noms en minuscules.
    """
    tout = {i.filename.lower() for i in archive.infolist()}
    if sum(i.file_size for i in archive.infolist() if i.filename.lower().endswith(".rels")) > XML_LU_EN_ENTIER_MAX:
        return tout, set()  # liens comptés de toute façon : inutile de les lire
    try:
        types = _xml_court(archive, "[Content_Types].xml")
        declarees = [
            # Nom calculé comme openpyxl (PartName[1:]) : « //xl/x » désigne l'entrée « /xl/x ».
            ((element.get("PartName") or "")[1:], element.get("ContentType"))
            for element in (types.iter() if types is not None else ())
            if element.tag.endswith("Override")
        ]
        a_suivre = [partie for partie, type_ in declarees if type_ in TYPES_CLASSEUR] + ["xl/workbook.xml"]
        lues = PARTIES_LUES_PAR_NOM | set(a_suivre) | {p for p, type_ in declarees if type_ == TYPE_CHAINES_PARTAGEES}
        feuilles_liees: set[str] = set()
        liens_lus: set[str] = set()
        while a_suivre:
            if len(liens_lus) > PARTIES_SUIVIES_MAX:
                raise ValueError("liens démesurés")
            partie = a_suivre.pop()
            dossier, nom = posixpath.split(partie)
            chemin_liens = posixpath.join(dossier, "_rels", f"{nom}.rels")
            # Plusieurs graphies d'une même partie (« xl//x ») mènent au même fichier de liens : lu une fois.
            if chemin_liens in liens_lus:
                continue
            liens_lus.add(chemin_liens)
            liens = _xml_court(archive, chemin_liens)
            for lien in liens.iter() if liens is not None else ():
                cible = _cible_lien(lien, dossier)
                if cible is None:
                    continue
                if lien.get("Type") == LIEN_FEUILLE:
                    # Feuille de calcul lue au fil de l'eau, quel que soit le type déclaré : comptée comme feuille.
                    feuilles_liees.add(cible)
                    continue
                lues.add(cible)
                a_suivre.append(cible)
    except ValueError:
        return tout, set()
    lues = {partie.lower() for partie in lues}
    feuilles = {partie.lower() for partie, type_ in declarees if type_ == TYPE_FEUILLE} | {partie.lower() for partie in feuilles_liees}
    return lues, feuilles - lues


def _cible_lien(lien, dossier: str) -> str | None:
    """Entrée de l'archive désignée par un lien (élément d'un .rels), calculée comme openpyxl ; None sinon."""
    cible = lien.get("Target")
    if not lien.tag.endswith("Relationship") or cible is None:
        return None
    if lien.get("TargetMode") == "External":
        # openpyxl ne résout pas la cible d'un lien « External », mais la lit telle quelle si l'archive contient
        # une entrée de ce nom (liens externes, feuilles, dessins) : comptée comme les autres. Une vraie cible
        # externe (adresse, fichier du réseau) ne correspond à aucune entrée : sans effet.
        return cible
    # Chemin relatif au dossier de la partie qui porte le lien. Une cible vide désigne ce dossier lui-même
    # (« xl ») : openpyxl lit l'entrée de ce nom si elle existe.
    return cible[1:] if cible.startswith("/") else posixpath.normpath(posixpath.join(dossier, cible))


def _citations_feuilles(archive: zipfile.ZipFile) -> Counter | None:
    """Nombre de fois que chaque partie est citée comme feuille par le classeur (noms en minuscules).

    openpyxl analyse une feuille autant de fois que le classeur la cite (dimensions au chargement, puis
    lignes) : une feuille sans ligne citée trente fois occupe le worker trente fois plus longtemps. Comme
    openpyxl, tout enfant de <sheets> compte, quel que soit son nom : son r:id (ou id) désigne un lien du
    classeur, quels que soient le type et le mode de ce lien. Tous les classeurs possibles (déclarés, et
    xl/workbook.xml) sont lus, au fil de l'eau, en mémoire constante. Si les citations ne peuvent pas être
    établies, le fichier n'est pas lu : None quand [Content_Types].xml, les liens d'un classeur ou les classeurs
    sont démesurés, zipfile.BadZipFile quand ils sont illisibles.
    """
    import xml.parsers.expat

    citations: Counter = Counter()
    try:
        types = _xml_court(archive, "[Content_Types].xml")
        presentes = {info.filename for info in archive.infolist()}
        classeurs = presentes & ({"xl/workbook.xml"} | {
            (element.get("PartName") or "")[1:]
            for element in (types.iter() if types is not None else ())
            if element.tag.endswith("Override") and element.get("ContentType") in TYPES_CLASSEUR
        })
        if sum(archive.getinfo(classeur).file_size for classeur in classeurs) > XML_LU_EN_ENTIER_MAX:
            return None
        for classeur in classeurs:
            dossier, nom = posixpath.split(classeur)
            liens: dict[str, set[str]] = {}
            arbre = _xml_court(archive, posixpath.join(dossier, "_rels", f"{nom}.rels"))
            for lien in arbre.iter() if arbre is not None else ():
                cible = _cible_lien(lien, dossier)
                if cible is not None:
                    liens.setdefault(lien.get("Id") or "", set()).add(cible.lower())
            profondeur = 0
            dans_sheets = False

            def debut(balise, attributs, liens=liens):
                nonlocal profondeur, dans_sheets
                profondeur += 1
                if profondeur == 2:
                    dans_sheets = balise.rpartition(":")[2] == "sheets"
                elif profondeur == 3 and dans_sheets:
                    # Préfixes non résolus : tout attribut « id » compte (r:id, ou id seul, comme openpyxl).
                    for ident in {valeur for cle, valeur in attributs.items() if cle.rpartition(":")[2] == "id"}:
                        citations.update(liens.get(ident, ()))

            def fin(_balise):
                nonlocal profondeur
                profondeur -= 1

            analyseur = xml.parsers.expat.ParserCreate()
            analyseur.StartDoctypeDeclHandler = _refuser_dtd
            analyseur.StartElementHandler = debut
            analyseur.EndElementHandler = fin
            try:
                with archive.open(classeur) as source:
                    analyseur.ParseFile(source)
            except (xml.parsers.expat.ExpatError, ValueError, NotImplementedError, RuntimeError) as erreur:
                raise PartieIllisible(f"{classeur} illisible") from erreur
    except PartieIllisible as erreur:
        # Classeur abîmé, ou d'un codage qu'openpyxl seul saurait lire : refusé comme une archive endommagée.
        raise zipfile.BadZipFile(str(erreur)) from erreur
    except ValueError:  # [Content_Types].xml ou liens démesurés
        return None
    return citations


class PartieIllisible(ValueError):
    """Partie XML illisible (et non démesurée)."""


def _refuser_dtd(*_):
    # Aucun fichier Office ne contient de DTD : ses entités démultiplieraient le texte à analyser (jusqu'à
    # 100 fois la taille de la partie, limite d'expat). Partie refusée comme illisible.
    raise ValueError("DTD refusée")


def _xml_court(archive: zipfile.ZipFile, nom: str):
    """Arbre XML d'une petite partie, None si elle est absente ; ValueError si elle est démesurée ou illisible."""
    import xml.etree.ElementTree as ET

    class SansDtd(ET.TreeBuilder):
        doctype = staticmethod(_refuser_dtd)

    try:
        info = archive.getinfo(nom)
    except KeyError:
        return None
    if info.file_size > XML_COURT_MAX:
        raise ValueError(f"{nom} démesuré")
    try:
        analyseur = ET.XMLParser(target=SansDtd())
        analyseur.feed(archive.read(info))
        return analyseur.close()
    except (ET.ParseError, ValueError, zipfile.BadZipFile, NotImplementedError, RuntimeError) as erreur:
        # ValueError : codage multi-octets (Shift_JIS…), que lit pourtant openpyxl (lxml).
        raise PartieIllisible(f"{nom} illisible") from erreur


# --- Conversion des anciens formats -----------------------------------------

# Profil LibreOffice : les images et objets liés d'un document reçu ne sont jamais téléchargés
# (aucune requête vers l'adresse choisie par l'auteur du fichier, sur Internet ou le réseau local).
PROFIL_LIBREOFFICE = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" \
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="BlockUntrustedRefererLinks" \
oor:op="fuse"><value>true</value></prop></item>
</oor:items>
"""


def convertir(source: Path, format_cible: str, dossier: Path) -> Path:
    binaire = shutil.which(settings.LIBREOFFICE_BIN)
    if not binaire:
        raise FormatNonAnalyse(
            f"Format {source.suffix.lower()} conservé : LibreOffice n'est pas installé pour le convertir."
        )
    copie = dossier / f"source{source.suffix.lower()}"
    shutil.copyfile(source, copie)
    profil = dossier / "profil-libreoffice"  # profil propre : conversions simultanées possibles
    (profil / "user").mkdir(parents=True, exist_ok=True)
    (profil / "user" / "registrymodifications.xcu").write_text(PROFIL_LIBREOFFICE, encoding="utf-8")
    commande = [
        binaire,
        f"-env:UserInstallation={profil.as_uri()}",
        "--headless",
        "--norestore",
        "--nolockcheck",
        "--convert-to",
        format_cible,
        "--outdir",
        str(dossier),
        str(copie),
    ]
    try:
        subprocess.run(commande, check=True, capture_output=True, timeout=settings.CONVERSION_DELAI_MAX)
    except subprocess.TimeoutExpired as erreur:
        raise ErreurLecture("La conversion du fichier a pris trop de temps.") from erreur
    except subprocess.CalledProcessError as erreur:
        raise ErreurLecture("LibreOffice n'a pas pu convertir ce fichier.") from erreur
    resultat = dossier / f"source.{format_cible}"
    if not resultat.exists() or resultat.stat().st_size == 0:
        raise ErreurLecture("Conversion impossible : le fichier est peut-être protégé ou endommagé.")
    return resultat


# --- Word -------------------------------------------------------------------

_STYLE_TITRE = re.compile(r"^(?:heading|titre)\s*(\d)$", re.IGNORECASE)
_STYLE_SOMMAIRE = re.compile(r"^(?:toc|table des mati|sommaire|index)", re.IGNORECASE)


def _lire_docx(chemin: Path) -> ContenuDocument:
    from docx import Document
    from docx.table import Table

    document = Document(str(chemin))
    contenu = ContenuDocument()
    compteurs = [0] * 9

    for element in document.iter_inner_content():
        if isinstance(element, Table):
            lignes = _lignes_tableau_docx(element)
            if lignes:
                contenu.blocs.append(Bloc("tableau", lignes=lignes))
                contenu.tableaux.append(Tableau(f"Tableau {len(contenu.tableaux) + 1}", lignes))
            continue

        texte = " ".join(element.text.split())
        if not texte:
            continue
        nom_style = (element.style.name if element.style is not None else "") or ""
        if _STYLE_SOMMAIRE.match(nom_style):
            continue

        style_titre = _STYLE_TITRE.match(nom_style)
        if style_titre:
            niveau = min(int(style_titre.group(1)), 9)
            compteurs[niveau - 1] += 1
            for indice in range(niveau, 9):
                compteurs[indice] = 0
            numero, titre = separer_numero(texte)
            if not numero and _numerotation_automatique(element):
                numero = ".".join(str(c or 1) for c in compteurs[:niveau])
            contenu.blocs.append(Bloc("titre", texte=titre or texte, niveau=niveau, numero=numero))
        else:
            contenu.blocs.append(Bloc("texte", texte=texte, gras=_est_gras(element)))
    return contenu


def _numerotation_automatique(paragraphe) -> bool:
    """Le titre est-il numéroté automatiquement par Word (numéro absent du texte) ?"""
    proprietes = paragraphe._p.pPr
    if proprietes is not None and proprietes.numPr is not None:
        numero_liste = proprietes.numPr.numId
        return numero_liste is None or numero_liste.val != 0
    style = paragraphe.style
    while style is not None:
        proprietes = style.element.pPr
        if proprietes is not None and proprietes.numPr is not None:
            return True
        style = style.base_style
    return False


def _est_gras(paragraphe) -> bool:
    morceaux = [r for r in paragraphe.runs if r.text.strip()]
    if not morceaux:
        return False
    style_gras = bool(paragraphe.style is not None and paragraphe.style.font.bold)
    return all(r.bold or (r.bold is None and style_gras) for r in morceaux)


def _lignes_tableau_docx(tableau) -> list[list[str]]:
    lignes = []
    for rangee in tableau.rows:
        cellules: list[str] = []
        precedente = None
        for cellule in rangee.cells:
            if cellule._tc is precedente:  # cellules fusionnées renvoyées plusieurs fois
                continue
            precedente = cellule._tc
            cellules.append(" ".join(cellule.text.split()))
        if any(cellules):
            lignes.append(cellules)
    return lignes


# --- Excel et CSV -----------------------------------------------------------


def _lire_xlsx(chemin: Path) -> ContenuDocument:
    from openpyxl import load_workbook

    classeur = load_workbook(str(chemin), read_only=True, data_only=True)
    contenu = ContenuDocument()
    lues = 0  # budget commun à toutes les feuilles : classeur rempli exprès de lignes, ou de feuilles
    try:
        for feuille in classeur.worksheets:
            if lues >= LIGNES_PAR_CLASSEUR_MAX:
                break
            lignes: list[list] = []
            vides = 0
            largeur = min(feuille.max_column or COLONNES_MAX, COLONNES_MAX)  # dimension déclarée, bornée
            for rangee in feuille.iter_rows(values_only=True, max_col=largeur):
                if lues >= LIGNES_PAR_CLASSEUR_MAX:
                    break
                lues += 1
                if all(v in (None, "") for v in rangee):
                    vides += 1
                    if vides > 200:  # feuilles « formatées » sur un million de lignes
                        break
                    continue
                vides = 0
                lignes.append(list(rangee))
            if lignes:
                contenu.tableaux.append(Tableau(feuille.title, lignes))
    finally:
        classeur.close()
    return contenu


def _lire_csv(chemin: Path) -> ContenuDocument:
    brut = chemin.read_bytes()
    for encodage in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texte = brut.decode(encodage)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialecte = csv.Sniffer().sniff(texte[:5000], delimiters=";,\t")
        separateur = dialecte.delimiter
    except csv.Error:
        separateur = ";"
    lignes = [ligne for ligne in csv.reader(texte.splitlines(), delimiter=separateur) if any(ligne)]
    return ContenuDocument(tableaux=[Tableau("CSV", lignes)])


# --- PDF et OCR -------------------------------------------------------------

_NUMERO_PAGE = re.compile(r"^(?:page\s*)?\d{1,4}\s*(?:/|sur)?\s*\d{0,4}$", re.IGNORECASE)


def _lire_pdf(chemin: Path, dossier: Path, tableaux_pdf: bool) -> ContenuDocument:
    import pdfplumber

    contenu = ContenuDocument()
    lignes_par_page: list[list[str] | None] = []
    pages_scannees: list[int] = []

    with pdfplumber.open(str(chemin)) as pdf:
        for indice, page in enumerate(pdf.pages):
            texte = page.extract_text() or ""
            if texte.strip():
                lignes_par_page.append(texte.splitlines())
                if tableaux_pdf:
                    for numero, tableau in enumerate(page.extract_tables(), start=1):
                        contenu.tableaux.append(Tableau(f"Page {indice + 1} – tableau {numero}", tableau))
            elif page.images:
                pages_scannees.append(indice)
                lignes_par_page.append(None)
            else:
                lignes_par_page.append([])

    if pages_scannees:
        if shutil.which(settings.TESSERACT_BIN):
            for indice, texte in _ocr(chemin, pages_scannees, dossier).items():
                lignes_par_page[indice] = texte.splitlines()
                contenu.pages_ocr += 1
        elif not any(lignes_par_page):
            raise FormatNonAnalyse("PDF scanné : la reconnaissance de texte (Tesseract) n'est pas installée.")

    for ligne in _sans_entetes_ni_pieds(lignes_par_page):
        texte = " ".join(ligne.split())
        if texte:
            contenu.blocs.append(Bloc("texte", texte=texte))
    if not contenu.blocs and not contenu.tableaux:
        raise FormatNonAnalyse("Aucun texte lisible dans ce PDF.")
    return contenu


def _ocr(chemin: Path, indices: list[int], dossier: Path) -> dict[int, str]:
    import pypdfium2

    resultats: dict[int, str] = {}
    pdf = pypdfium2.PdfDocument(str(chemin))
    try:
        for indice in indices[: settings.OCR_PAGES_MAX]:
            page = pdf[indice]
            # 300 dpi, sauf pour une page géante (jusqu'à 200 × 200 pouces dans un PDF) : nombre de
            # pixels plafonné, sinon le rendu demanderait des dizaines de Go de mémoire.
            largeur, hauteur = page.get_size()
            echelle = min(300 / 72, (PIXELS_OCR_MAX / max(largeur * hauteur, 1.0)) ** 0.5)
            image = page.render(scale=echelle).to_pil().convert("L")
            fichier = dossier / f"page-{indice}.png"
            image.save(fichier)
            sortie = subprocess.run(
                [settings.TESSERACT_BIN, str(fichier), "stdout", "-l", settings.OCR_LANGUE, "--psm", "3"],
                capture_output=True,
                timeout=300,
                check=True,
            )
            resultats[indice] = sortie.stdout.decode("utf-8", errors="replace")
            fichier.unlink(missing_ok=True)
    finally:
        pdf.close()
    return resultats


def _sans_entetes_ni_pieds(lignes_par_page: list[list[str] | None]) -> list[str]:
    """Retire les en-têtes et pieds de page répétés et les numéros de page."""
    pages = [p for p in lignes_par_page if p]
    repetees: set[str] = set()
    if len(pages) >= 3:
        compteur = Counter(cle for page in pages for cle in {_cle_ligne(l) for l in page})
        seuil = max(3, len(pages) // 2)
        repetees = {cle for cle, nombre in compteur.items() if nombre >= seuil and len(cle) < 120}
    resultat = []
    for page in lignes_par_page:
        for ligne in page or []:
            if _cle_ligne(ligne) in repetees or _NUMERO_PAGE.match(ligne.strip()):
                continue
            resultat.append(ligne)
    return resultat


def _cle_ligne(ligne: str) -> str:
    return re.sub(r"\d+", "#", " ".join(ligne.split()).lower())
