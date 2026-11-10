"""Audit global : garde-fous de la lecture des documents reçus (constats 1, 2 et 4).

- OCR : nombre de pixels plafonné pour une page géante (un PDF de 656 octets ne vide plus la mémoire).
- Bombes zip : un .docx ou un .xlsx démesuré une fois décompressé est refusé sans être lu ; les lignes
  d'un classeur sont bornées en nombre (tout le classeur) et en largeur.
- LibreOffice : profil qui bloque le téléchargement des images liées (aucune requête sortante).
"""
import io
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from . import lecture
from .lecture import ErreurLecture, decompression_excessive, lire_document


class Arret(Exception):
    """Interrompt le rendu une fois l'échelle connue (inutile de dessiner la page)."""


def _docx(paragraphes: int = 3) -> bytes:
    from docx import Document

    document = Document()
    document.add_heading("Lot 08 – Menuiseries extérieures", level=1)
    for numero in range(paragraphes):
        document.add_paragraph(f"Paragraphe {numero} : châssis aluminium à rupture de pont thermique.")
    flux = io.BytesIO()
    document.save(flux)
    return flux.getvalue()


def _xlsx(lignes: int = 2) -> bytes:
    from openpyxl import Workbook

    classeur = Workbook()
    feuille = classeur.active
    feuille.title = "DPGF"
    feuille.append(["N°", "Désignation", "U", "Qté", "PU HT"])
    for numero in range(lignes):
        feuille.append([f"8.{numero}", f"Châssis aluminium {numero}", "u", 12, 850.0])
    flux = io.BytesIO()
    classeur.save(flux)
    return flux.getvalue()


def xlsx_chaines_partagees(
    lignes: list[list[str]], partie: str = "xl/sharedStrings.xml", *, dimension: str = "", types_en_plus: str = "", liens_en_plus: str = "",
    feuilles_en_plus: str = "", classeur_en_plus: str = "",
) -> bytes:
    """Classeur avec une table des chaînes partagées, comme Excel l'écrit (openpyxl écrit le texte en ligne).

    dimension : zone déclarée par la feuille (« A1:XFD2000 ») ; types_en_plus et liens_en_plus : éléments
    ajoutés à [Content_Types].xml et aux liens du classeur ; feuilles_en_plus et classeur_en_plus : éléments
    ajoutés à <sheets> et au classeur, après <sheets>.
    """
    chaines: list[str] = []
    rangees = []
    for numero, ligne in enumerate(lignes, start=1):
        cellules = []
        for colonne, texte in enumerate(ligne):
            chaines.append(texte)
            cellules.append(f'<c r="{chr(65 + colonne)}{numero}" t="s"><v>{len(chaines) - 1}</v></c>')
        rangees.append(f'<row r="{numero}">{"".join(cellules)}</row>')
    principal = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    relations = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    type_ = "application/vnd.openxmlformats-officedocument.spreadsheetml"
    flux = io.BytesIO()
    with zipfile.ZipFile(flux, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/xl/workbook.xml" ContentType="{type_}.sheet.main+xml"/>'
            f'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="{type_}.worksheet+xml"/>'
            f'<Override PartName="/{partie}" ContentType="{type_}.sharedStrings+xml"/>{types_en_plus}</Types>'
        ))
        archive.writestr("_rels/.rels", (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{relations}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
        ))
        archive.writestr("xl/workbook.xml", (
            f'<workbook xmlns="{principal}" xmlns:r="{relations}"><sheets><sheet name="DPGF" sheetId="1" r:id="rId1"/>{feuilles_en_plus}</sheets>'
            f"{classeur_en_plus}</workbook>"
        ))
        archive.writestr("xl/_rels/workbook.xml.rels", (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{relations}/worksheet" Target="worksheets/sheet1.xml"/>'
            f'<Relationship Id="rId2" Type="{relations}/sharedStrings" Target="/{partie}"/>{liens_en_plus}</Relationships>'
        ))
        zone = f'<dimension ref="{dimension}"/>' if dimension else ""
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{principal}">{zone}<sheetData>{"".join(rangees)}</sheetData></worksheet>')
        archive.writestr(partie, (
            f'<sst xmlns="{principal}" count="{len(chaines)}" uniqueCount="{len(chaines)}">'
            + "".join(f"<si><t>{texte}</t></si>" for texte in chaines) + "</sst>"
        ))
    return flux.getvalue()


def xlsx_graphique_et_liens_externes(citations: int = 1, cadres: int = 1, references: int = 1) -> bytes:
    """Classeur « DPGF » avec une feuille de graphique citée `citations` fois par <sheets>, dont le dessin
    désigne le même graphique par `cadres` cadres, et un lien externe cité `references` fois."""
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference

    classeur = Workbook()
    feuille = classeur.active
    feuille.title = "DPGF"
    feuille.append(["N°", "Désignation", "PU HT"])
    feuille.append(["8.1", "Châssis aluminium", 850.0])
    graphique = BarChart()
    graphique.add_data(Reference(feuille, min_col=3, min_row=1, max_row=2))
    classeur.create_chartsheet("Graphique").add_chart(graphique)
    tampon = io.BytesIO()
    classeur.save(tampon)
    relations = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    source = zipfile.ZipFile(tampon)
    flux = io.BytesIO()
    with zipfile.ZipFile(flux, "w", zipfile.ZIP_DEFLATED) as archive:
        for nom in source.namelist():
            texte = source.read(nom).decode()
            if nom == "xl/workbook.xml":
                position = texte.index('name="Graphique"')
                citation = texte[texte.rindex("<sheet ", 0, position):texte.index("/>", position) + 2]
                texte = texte.replace(citation, "".join(citation.replace('name="Graphique"', f'name="Graphique {n}"') for n in range(citations)))
                texte = texte.replace("</sheets>", f'</sheets><externalReferences xmlns:r="{relations}">'
                                      + '<externalReference r:id="rId9"/>' * references + "</externalReferences>")
            elif nom == "xl/_rels/workbook.xml.rels":
                texte = texte.replace("</Relationships>", f'<Relationship Id="rId9" Type="{relations}/externalLink" '
                                      'Target="externalLinks/externalLink1.xml"/></Relationships>')
            elif nom == "xl/drawings/drawing1.xml":
                cadre = texte[texte.index("<absoluteAnchor>"):texte.index("</wsDr>")]
                texte = texte.replace(cadre, cadre * cadres)
            archive.writestr(nom, texte)
        archive.writestr("xl/externalLinks/externalLink1.xml", (
            '<externalLink xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            f'xmlns:r="{relations}"><externalBook r:id="rId1"><sheetNames><sheetName val="Prix"/></sheetNames>'
            '<sheetDataSet><sheetData sheetId="0"><row r="1"><cell r="A1"><v>850</v></cell></row></sheetData>'
            "</sheetDataSet></externalBook></externalLink>"
        ))
        archive.writestr("xl/externalLinks/_rels/externalLink1.xml.rels", (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{relations}/externalLinkPath" Target="prix.xlsx" TargetMode="External"/></Relationships>'
        ))
    return flux.getvalue()


class LectureAuditTests(SimpleTestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp(prefix="audit-lecture-"))
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)

    # --- Constat 1 : OCR d'une page géante ---------------------------------------------------------
    def test_ocr_plafonne_le_nombre_de_pixels(self):
        import pypdfium2

        chemin = self.dossier / "offre.pdf"
        pdf = pypdfium2.PdfDocument.new()
        pdf.new_page(14400, 14400)  # 200 × 200 pouces : la plus grande page permise par le format PDF
        pdf.new_page(595, 842)  # A4
        pdf.save(str(chemin))
        pdf.close()
        echelles = []

        def rendu(page, scale=1, **_options):
            echelles.append((page.get_size(), scale))
            raise Arret

        with mock.patch.object(pypdfium2.PdfPage, "render", rendu):
            for indice in (0, 1):
                with self.assertRaises(Arret):
                    lecture._ocr(chemin, [indice], self.dossier)
        (largeur, hauteur), echelle = echelles[0]
        self.assertLessEqual(largeur * echelle * hauteur * echelle, lecture.PIXELS_OCR_MAX * 1.0001)
        self.assertLess(echelle, 0.5)  # au lieu de 300 dpi : 60 000 × 60 000 pixels (plus de 10 Go)
        self.assertEqual(echelles[1][1], 300 / 72)  # une page A4 garde ses 300 dpi

    # --- Constat 2 : bombes zip ---------------------------------------------------------------------
    def test_docx_demesure_refuse_sans_etre_lu(self):
        chemin = self.dossier / "offre.docx"
        with zipfile.ZipFile(chemin, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            with archive.open("word/document.xml", "w") as partie:  # 101 Mo de texte → environ 100 Ko compressés
                bloc = b"<w:p><w:r><w:t>x</w:t></w:r></w:p>" * 30_000
                for _ in range(101 * 1024 * 1024 // len(bloc) + 1):
                    partie.write(bloc)
        self.assertLess(chemin.stat().st_size, 2 * 1024 * 1024)
        with mock.patch.object(lecture, "_lire_docx") as lire, self.assertRaisesMessage(ErreurLecture, "anormalement volumineux"):
            lire_document(chemin, self.dossier)
        lire.assert_not_called()

    def test_docx_partie_principale_au_nom_libre_comptee_par_son_type(self):
        # python-docx lit la partie désignée par les liens selon son type déclaré, quel que soit son nom :
        # « word/document.bin » déclaré document principal (Override, ou Default de l'extension .bin).
        principal = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
        w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

        def document(declaration: str, paragraphes: bytes) -> bytes:
            flux = io.BytesIO()
            with zipfile.ZipFile(flux, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("[Content_Types].xml", (
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                    f"{declaration}</Types>"
                ))
                archive.writestr("_rels/.rels", (
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                    'officeDocument" Target="word/document.bin"/></Relationships>'
                ))
                with archive.open("word/document.bin", "w") as partie:
                    partie.write(f'<w:document xmlns:w="{w}"><w:body>'.encode())
                    partie.write(paragraphes)
                    partie.write(b"</w:body></w:document>")
            return flux.getvalue()

        # Déclarations « leurres » placées après la vraie : python-docx ne lit que les enfants directs de <Types>
        # de son espace de noms ; une déclaration d'un autre espace de noms, ou imbriquée, ne compte pas pour lui.
        autre = "application/octet-stream"
        leurres = [
            "",
            f'<x:Override xmlns:x="urn:leurre" PartName="/word/document.bin" ContentType="{autre}"/>',
            f'<Leurre><Override PartName="/word/document.bin" ContentType="{autre}"/></Leurre>',
            f'<x:Default xmlns:x="urn:leurre" Extension="bin" ContentType="{autre}"/>',
            f'<Leurre><Default Extension="bin" ContentType="{autre}"/></Leurre>',
        ]
        for vraie in (
            f'<Override PartName="/word/document.bin" ContentType="{principal}"/>',
            f'<Default Extension="bin" ContentType="{principal}"/>',
        ):
            for leurre in leurres:
                from docx import Document

                declaration = vraie + leurre
                texte = b"<w:p><w:r><w:t>Lot 08</w:t></w:r></w:p>"
                self.assertEqual(Document(io.BytesIO(document(declaration, texte))).paragraphs[0].text, "Lot 08")  # lue en entier
                contenu = document(declaration, b"<w:p/>" * (8 * 1024 * 1024 // 6))  # 8 Mo, environ 10 Ko compressés
                self.assertLess(len(contenu), 100_000)
                with mock.patch.object(lecture, "XML_LU_EN_ENTIER_MAX", 5 * 1024 * 1024):
                    self.assertTrue(decompression_excessive(io.BytesIO(contenu), ".docx"), leurre)
                self.assertFalse(decompression_excessive(io.BytesIO(contenu), ".docx"))

    def test_docx_heritage_de_styles_en_boucle_lu_sans_fin(self):
        # Style de titre « basé sur » lui-même, ou deux styles basés l'un sur l'autre : la recherche de la
        # numérotation tournait sans fin (worker occupé jusqu'à la limite de temps de la tâche). La numérotation
        # héritée d'un style de base reste reconnue.
        import signal

        from docx import Document
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        def document(bases: dict[str, str], numerote: str = "") -> Path:
            fichier = Document()
            for style_id, base in bases.items():
                fichier.styles.element.get_by_id(style_id).get_or_add_basedOn().val = base
            if numerote:
                proprietes = fichier.styles.element.get_by_id(numerote).get_or_add_pPr()
                numero = OxmlElement("w:numPr")
                ident = OxmlElement("w:numId")
                ident.set(qn("w:val"), "1")
                numero.append(ident)
                proprietes.append(numero)
            fichier.add_heading("Généralités", level=1)
            fichier.add_heading("Objet du marché", level=2)
            chemin = self.dossier / "cctp.docx"
            fichier.save(chemin)
            return chemin

        def trop_long(*_):
            raise AssertionError("lecture sans fin")

        ancien = signal.signal(signal.SIGALRM, trop_long)
        self.addCleanup(signal.signal, signal.SIGALRM, ancien)
        self.addCleanup(signal.alarm, 0)
        for bases, numerote, numeros in (
            ({"Heading1": "Heading1"}, "", ["", ""]),
            ({"Heading1": "Heading2", "Heading2": "Heading1"}, "", ["", ""]),
            ({"Heading1": "Heading2", "Heading2": "Heading1"}, "Heading2", ["1", "1.1"]),  # hérité dans la boucle
            ({"Heading2": "Heading1"}, "Heading1", ["1", "1.1"]),
        ):
            signal.alarm(20)
            blocs = lire_document(document(bases, numerote), self.dossier).blocs
            signal.alarm(0)
            self.assertEqual([(b.genre, b.numero, b.texte) for b in blocs],
                             [("titre", numeros[0], "Généralités"), ("titre", numeros[1], "Objet du marché")])

    def _alarme(self, secondes: int):
        import signal

        def trop_long(*_):
            raise AssertionError("lecture trop longue")

        ancien = signal.signal(signal.SIGALRM, trop_long)
        self.addCleanup(signal.signal, signal.SIGALRM, ancien)
        self.addCleanup(signal.alarm, 0)
        signal.alarm(secondes)

    def test_docx_cellule_a_grid_span_demesure_lue_une_fois(self):
        # w:gridSpan sans borne : _Row.cells de python-docx renvoyait la cellule 10**12 fois (mémoire sans fin).
        from .tests_isolation import docx_cellule

        chemin = self.dossier / "offre.docx"
        chemin.write_bytes(docx_cellule(10**12))
        self._alarme(20)
        blocs = lire_document(chemin, self.dossier).blocs
        self.assertEqual([(b.genre, b.texte or b.lignes) for b in blocs], [("texte", "Début"), ("tableau", [["Prix"]]), ("texte", "Fin")])

    def test_docx_longue_colonne_fusionnee_lue_sans_recursion(self):
        # Colonne fusionnée verticalement sur 2 000 rangées : _Row.cells remontait récursivement jusqu'à la cellule
        # du haut pour chaque rangée (temps quadratique, RecursionError au-delà d'environ 1 000 rangées) et en
        # recopiait le texte. Le texte n'est plus lu qu'une fois, dans la cellule du haut ; une cellule fusionnée
        # horizontalement (gridSpan) ne donne qu'une valeur.
        from docx import Document

        w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

        def cellule(texte: str, proprietes: str = "") -> str:
            return f"<w:tc><w:tcPr>{proprietes}</w:tcPr><w:p><w:r><w:t>{texte}</w:t></w:r></w:p></w:tc>"

        rangees = [
            "<w:tr>" + cellule("Lot 08 – Menuiseries", '<w:vMerge w:val="restart"/>') + cellule("Article 0") + cellule("u") + "</w:tr>"
        ] + [
            "<w:tr>" + cellule("", "<w:vMerge/>") + cellule(f"Article {n}") + cellule("u") + "</w:tr>" for n in range(1, 1999)
        ] + ["<w:tr>" + cellule("", '<w:vMerge w:val="continue"/>') + cellule("Total", '<w:gridSpan w:val="2"/>') + "</w:tr>"]
        corps = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {w}><w:body><w:tbl>'
            '<w:tblGrid><w:gridCol/><w:gridCol/><w:gridCol/></w:tblGrid>' + "".join(rangees) + "</w:tbl></w:body></w:document>"
        )
        gabarit = io.BytesIO()
        Document().save(gabarit)
        chemin = self.dossier / "cctp.docx"
        with zipfile.ZipFile(gabarit) as source, zipfile.ZipFile(chemin, "w", zipfile.ZIP_DEFLATED) as cible:
            for info in source.infolist():
                cible.writestr(info.filename, corps.encode() if info.filename == "word/document.xml" else source.read(info))
        self._alarme(20)
        debut = __import__("time").monotonic()
        lignes = lire_document(chemin, self.dossier).tableaux[0].lignes
        self.assertLess(__import__("time").monotonic() - debut, 5)
        self.assertEqual(len(lignes), 2000)
        self.assertEqual(lignes[:2], [["Lot 08 – Menuiseries", "Article 0", "u"], ["", "Article 1", "u"]])
        self.assertEqual(lignes[-1], ["", "Total"])
        self.assertEqual(sum(valeur == "Lot 08 – Menuiseries" for ligne in lignes for valeur in ligne), 1)

    def test_docx_styles_resolus_une_fois_par_document(self):
        # python-docx parcourt tous les styles à chaque Paragraph.style : 85 s pour 2 000 styles et 3 000
        # paragraphes. Chaque style n'est plus résolu qu'une fois.
        from docx import Document
        from docx.enum.style import WD_STYLE_TYPE
        from docx.oxml.styles import CT_Styles

        fichier = Document()
        for numero in range(300):
            fichier.styles.add_style(f"Style {numero}", WD_STYLE_TYPE.PARAGRAPH)
        fichier.styles["Style 7"].font.bold = True
        for numero in range(300):
            fichier.add_paragraph(f"Article {numero} : châssis aluminium.", style="Normal" if numero % 2 else None)
        fichier.add_paragraph("Clause en gras par son style", style="Style 7")
        fichier.save(self.dossier / "cctp.docx")
        with (
            mock.patch.object(CT_Styles, "default_for", autospec=True, side_effect=CT_Styles.default_for) as defaut,
            mock.patch.object(CT_Styles, "get_by_id", autospec=True, side_effect=CT_Styles.get_by_id) as par_id,
        ):
            blocs = lire_document(self.dossier / "cctp.docx", self.dossier).blocs
        self.assertEqual(len(blocs), 301)
        self.assertEqual((blocs[0].texte, blocs[0].gras), ("Article 0 : châssis aluminium.", False))
        self.assertEqual((blocs[-1].texte, blocs[-1].gras), ("Clause en gras par son style", True))
        self.assertLessEqual(defaut.call_count, 1)
        self.assertEqual(par_id.call_count, 0)

    def test_docx_et_xlsx_ordinaires_toujours_lus(self):
        (self.dossier / "cctp.docx").write_bytes(_docx())
        (self.dossier / "dpgf.xlsx").write_bytes(_xlsx())
        self.assertTrue(lire_document(self.dossier / "cctp.docx", self.dossier).blocs)
        lignes = lire_document(self.dossier / "dpgf.xlsx", self.dossier).tableaux[0].lignes
        self.assertEqual(len(lignes), 3)
        self.assertEqual(lignes[1], ["8.0", "Châssis aluminium 0", "u", 12, 850.0])  # largeur déclarée : 5 colonnes

    def test_xlsx_table_des_chaines_demesuree(self):
        contenu = xlsx_chaines_partagees([[f"Châssis aluminium {n}", "u"] for n in range(400)])
        (self.dossier / "dpgf.xlsx").write_bytes(contenu)
        self.assertEqual(len(lire_document(self.dossier / "dpgf.xlsx", self.dossier).tableaux[0].lignes), 400)
        with mock.patch.object(lecture, "XML_LU_EN_ENTIER_MAX", 5_000):
            self.assertTrue(decompression_excessive(io.BytesIO(contenu), ".xlsx"))
            with mock.patch.object(lecture, "_lire_xlsx") as lire, self.assertRaisesMessage(ErreurLecture, "anormalement volumineux"):
                lire_document(self.dossier / "dpgf.xlsx", self.dossier)
        lire.assert_not_called()
        self.assertFalse(decompression_excessive(io.BytesIO(contenu), ".xlsx"))

    def test_xlsx_feuilles_lues_au_fil_de_l_eau_non_comptees(self):
        # Feuille longue (texte en ligne, comme openpyxl l'écrit, 100 Ko) : lue en flux, acceptée.
        # Le reste (thème, styles, classeur, liens…) fait environ 16 Ko.
        with mock.patch.object(lecture, "XML_LU_EN_ENTIER_MAX", 50_000):
            self.assertFalse(decompression_excessive(io.BytesIO(_xlsx(lignes=400)), ".xlsx"))

    def test_xlsx_archive_ou_feuilles_demesurees(self):
        contenu = _xlsx(lignes=400)  # environ 116 Ko décompressés, dont 100 Ko de feuille
        self.assertFalse(decompression_excessive(io.BytesIO(contenu), ".xlsx"))
        with mock.patch.object(lecture, "DOCX_DECOMPRESSE_MAX", 50_000):
            self.assertTrue(decompression_excessive(io.BytesIO(contenu), ".xlsx"))
        with mock.patch.object(lecture, "FEUILLES_MAX", 50_000):
            self.assertTrue(decompression_excessive(io.BytesIO(contenu), ".xlsx"))

    def test_xlsx_theme_demesure_refuse_meme_declare_comme_feuille(self):
        # openpyxl lit le thème en entier, sous un nom fixe : 101 Mo d'espaces, environ 100 Ko compressés.
        chemin = self.dossier / "dpgf.xlsx"
        for declaration in ("", f'<Override PartName="/xl/theme/theme1.xml" ContentType="{lecture.TYPE_FEUILLE}"/>'):
            flux = io.BytesIO(xlsx_chaines_partagees([["Châssis aluminium", "u"]], types_en_plus=declaration))
            with zipfile.ZipFile(flux, "a", zipfile.ZIP_DEFLATED) as archive, archive.open("xl/theme/theme1.xml", "w") as theme:
                espaces = b" " * (1024 * 1024)
                for _ in range(101):
                    theme.write(espaces)
            chemin.write_bytes(flux.getvalue())
            self.assertLess(chemin.stat().st_size, 2 * 1024 * 1024)
            with mock.patch.object(lecture, "_lire_xlsx") as lire, self.assertRaisesMessage(ErreurLecture, "anormalement volumineux"):
                lire_document(chemin, self.dossier)
            lire.assert_not_called()

    def test_xlsx_parties_designees_par_les_liens_comptees_quel_que_soit_leur_nom(self):
        # Feuille de graphique puis dessin, aux noms libres et déclarés comme feuilles de calcul :
        # openpyxl les lit pourtant en entier s'ils sont désignés comme tels par les liens du classeur.
        relations = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

        def classeur(type_lien: str) -> io.BytesIO:
            flux = io.BytesIO(xlsx_chaines_partagees(
                [["Châssis aluminium", "u"]],
                types_en_plus=f'<Override PartName="/xl/graphique.bin" ContentType="{lecture.TYPE_FEUILLE}"/>'
                f'<Override PartName="/xl/dessins/dessin.bin" ContentType="{lecture.TYPE_FEUILLE}"/>',
                liens_en_plus=f'<Relationship Id="rId9" Type="{relations}/{type_lien}" Target="graphique.bin"/>',
            ))
            with zipfile.ZipFile(flux, "a", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("xl/graphique.bin", "<chartsheet/>")
                archive.writestr("xl/_rels/graphique.bin.rels", (
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    f'<Relationship Id="rId1" Type="{relations}/drawing" Target="dessins/dessin.bin"/></Relationships>'
                ))
                archive.writestr("xl/dessins/dessin.bin", "<wsDr/>" + " " * 20_000)
            return flux

        with mock.patch.object(lecture, "XML_LU_EN_ENTIER_MAX", 10_000):
            self.assertTrue(decompression_excessive(classeur("chartsheet"), ".xlsx"))
            self.assertFalse(decompression_excessive(classeur("worksheet"), ".xlsx"))  # vraie feuille : lue en flux

    def test_xlsx_nom_de_partie_a_double_barre_compte(self):
        # PartName « //xl/ss.bin » : openpyxl lit l'entrée « /xl/ss.bin » (PartName[1:]), elle doit être comptée.
        contenu = xlsx_chaines_partagees([[f"Châssis {n}", "u"] for n in range(400)], partie="/xl/ss.bin")
        with mock.patch.object(lecture, "XML_LU_EN_ENTIER_MAX", 5_000):
            self.assertTrue(decompression_excessive(io.BytesIO(contenu), ".xlsx"))

    def test_xlsx_feuille_liee_comptee_quel_que_soit_son_type(self):
        # Feuille désignée par un lien « worksheet » mais déclarée sous un autre type : lue au fil de l'eau, comptée.
        relations = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        flux = io.BytesIO(xlsx_chaines_partagees(
            [["Châssis aluminium", "u"]],
            types_en_plus='<Override PartName="/xl/feuille.bin" ContentType="application/octet-stream"/>',
            liens_en_plus=f'<Relationship Id="rId9" Type="{relations}/worksheet" Target="feuille.bin"/>',
        ))
        with zipfile.ZipFile(flux, "a", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("xl/feuille.bin", "<worksheet/>" + " " * 60_000)
        with mock.patch.object(lecture, "FEUILLES_MAX", 50_000):
            self.assertTrue(decompression_excessive(flux, ".xlsx"))

    def test_xlsx_parties_designees_par_un_lien_externe_ou_vide_comptees(self):
        # Lien « TargetMode="External" » : openpyxl ne résout pas la cible, mais lit l'entrée de ce nom si
        # l'archive en contient une (lien externe lu en entier, feuille lue au fil de l'eau). Cible vide :
        # openpyxl lit l'entrée « xl ».
        from openpyxl import load_workbook

        relations = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        externe = io.BytesIO(xlsx_chaines_partagees(
            [["Châssis aluminium", "u"]],
            classeur_en_plus='<externalReferences><externalReference r:id="rId9"/></externalReferences>',
            liens_en_plus=f'<Relationship Id="rId9" Type="{relations}/externalLink" Target="xl/ext.bin" TargetMode="External"/>',
        ))
        with zipfile.ZipFile(externe, "a", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("xl/ext.bin", "<externalLink/>" + " " * 1_000_000)
        self.assertFalse(decompression_excessive(externe, ".xlsx"))
        with mock.patch.object(lecture, "XML_LU_EN_ENTIER_MAX", 200_000):
            self.assertTrue(decompression_excessive(externe, ".xlsx"))

        for cible, mode, entree in (("xl/worksheets/s.bin", ' TargetMode="External"', "xl/worksheets/s.bin"), ("", "", "xl")):
            feuille = io.BytesIO(xlsx_chaines_partagees(
                [["Châssis aluminium", "u"]],
                feuilles_en_plus='<sheet name="Annexe" sheetId="2" r:id="rId9"/>',
                liens_en_plus=f'<Relationship Id="rId9" Type="{relations}/worksheet" Target="{cible}"{mode}/>',
            ))
            with zipfile.ZipFile(feuille, "a", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(entree, "<worksheet/>" + " " * 60_000)
            self.assertEqual(load_workbook(feuille, read_only=True).sheetnames, ["DPGF", "Annexe"])  # feuille lue
            self.assertFalse(decompression_excessive(feuille, ".xlsx"))
            with mock.patch.object(lecture, "FEUILLES_MAX", 50_000):
                self.assertTrue(decompression_excessive(feuille, ".xlsx"))

    def test_xlsx_lien_ecrit_sous_une_autre_balise_compte(self):
        # openpyxl lit chaque enfant de <Relationships> comme un lien, quelle que soit sa balise : une feuille
        # « .bin » désignée par <R …>, sans déclaration dans [Content_Types].xml, est bien lue. Elle doit être
        # comptée, à chaque citation.
        import re

        from openpyxl import Workbook

        classeur = Workbook()
        classeur.active.title = "F"
        classeur.active.append(["Désignation", "PU"])
        gabarit = io.BytesIO()
        classeur.save(gabarit)
        lignes = "".join(f'<row r="{n}"><c r="A{n}" t="inlineStr"><is><t>ligne {n}</t></is></c></row>' for n in range(1, 5001))
        with zipfile.ZipFile(gabarit) as source:
            feuille = re.sub(r"<sheetData>.*</sheetData>|<sheetData/>", f"<sheetData>{lignes}</sheetData>",
                             re.sub(r"<dimension[^>]*/>", "", source.read("xl/worksheets/sheet1.xml").decode()), flags=re.S)

        def fabriquer(balise: str, citations: int) -> io.BytesIO:
            flux = io.BytesIO()
            with zipfile.ZipFile(gabarit) as source, zipfile.ZipFile(flux, "w", zipfile.ZIP_DEFLATED) as cible:
                for info in source.infolist():
                    donnees = source.read(info).decode()
                    if info.filename == "xl/worksheets/sheet1.xml":
                        cible.writestr("xl/worksheets/s.bin", feuille)
                        continue
                    if info.filename == "[Content_Types].xml":
                        donnees = re.sub(r'<Override PartName="/xl/worksheets/sheet1.xml"[^>]*/>', "", donnees)
                    elif info.filename == "xl/_rels/workbook.xml.rels":
                        donnees = re.sub(r'<Relationship ([^>]*?)Target="/?xl/worksheets/sheet1.xml"', rf'<{balise} \1Target="/xl/worksheets/s.bin"', donnees)
                        self.assertIn(f"<{balise} ", donnees)
                    elif info.filename == "xl/workbook.xml":
                        citation = re.search(r'<sheet [^>]*name="F"[^>]*/>', donnees).group(0)
                        donnees = donnees.replace(citation, citation + "".join(
                            citation.replace('name="F"', f'name="F{n}"').replace('sheetId="1"', f'sheetId="{n + 1}"') for n in range(1, citations)
                        ))
                    cible.writestr(info.filename, donnees)
            return flux

        for balise in ("Relationship", "R"):
            classeur = lecture.ouvrir_classeur(fabriquer(balise, 1))
            self.assertEqual(sum(1 for _ in classeur.worksheets[0].iter_rows(values_only=True)), 5000)  # feuille lue
            classeur.close()
            with mock.patch.object(lecture, "FEUILLES_MAX", 50_000), mock.patch.object(lecture, "XML_LU_EN_ENTIER_MAX", 50_000):
                self.assertTrue(decompression_excessive(fabriquer(balise, 1), ".xlsx"), balise)
            with mock.patch.object(lecture, "FEUILLES_MAX", len(feuille) * 3 // 2):
                self.assertFalse(decompression_excessive(fabriquer(balise, 1), ".xlsx"), balise)
                self.assertTrue(decompression_excessive(fabriquer(balise, 2), ".xlsx"), balise)  # citée deux fois

    def test_xlsx_feuille_citee_plusieurs_fois_comptee_a_chaque_citation(self):
        # openpyxl analyse une feuille autant de fois que <sheets> la cite : tout enfant de <sheets>, par son
        # r:id ou son id, quel que soit le type du lien (« drawing » : partie comptée parmi les lues en entier).
        from openpyxl import load_workbook

        relations = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

        def classeur(type_lien: str, citations: str) -> io.BytesIO:
            flux = io.BytesIO(xlsx_chaines_partagees(
                [["Châssis aluminium", "u"]],
                feuilles_en_plus=citations,
                liens_en_plus=f'<Relationship Id="rId9" Type="{relations}/{type_lien}" Target="feuille.xml"/>',
            ))
            with zipfile.ZipFile(flux, "a", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("xl/feuille.xml", "<worksheet/>" + " " * 40_000)
            return flux

        une = '<sheet name="Annexe" sheetId="2" r:id="rId9"/>'
        trois = une + '<sheet name="Annexe 2" sheetId="3" r:id="rId9"/><autre name="Annexe 3" sheetId="4" id="rId9"/>'
        for type_lien in ("worksheet", "drawing"):
            self.assertEqual(len(load_workbook(classeur(type_lien, trois), read_only=True).worksheets), 4)
        with mock.patch.object(lecture, "FEUILLES_MAX", 100_000), mock.patch.object(lecture, "XML_LU_EN_ENTIER_MAX", 100_000):
            for type_lien in ("worksheet", "drawing"):
                self.assertFalse(decompression_excessive(classeur(type_lien, une), ".xlsx"))
                self.assertTrue(decompression_excessive(classeur(type_lien, trois), ".xlsx"))
            with mock.patch.object(lecture, "PARTIES_SUIVIES_MAX", 0):  # liens non suivis : tout compté, citations comprises
                self.assertFalse(decompression_excessive(classeur("worksheet", une), ".xlsx"))
                self.assertTrue(decompression_excessive(classeur("worksheet", trois), ".xlsx"))

    def test_xlsx_liens_d_une_feuille_comptes_a_chaque_citation(self):
        # openpyxl analyse en entier les liens (.rels) d'une feuille à chaque citation de la feuille.
        from openpyxl.packaging import relationship
        from openpyxl.reader import excel

        def classeur(citations: int) -> io.BytesIO:
            flux = io.BytesIO(xlsx_chaines_partagees(
                [["Châssis aluminium", "u"]],
                feuilles_en_plus="".join(f'<sheet name="Annexe {n}" sheetId="{n + 2}" r:id="rId1"/>' for n in range(citations - 1)),
            ))
            with zipfile.ZipFile(flux, "a", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("xl/worksheets/_rels/sheet1.xml.rels", (
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    + '<Relationship Id="a" Type="t" Target="x"/>' * 1_000 + "</Relationships>"
                ))
            return flux

        with mock.patch.object(excel, "get_dependents", wraps=relationship.get_dependents) as liens:
            lecture.ouvrir_classeur(classeur(3))
        self.assertEqual([appel.args[1] for appel in liens.call_args_list].count("xl/worksheets/_rels/sheet1.xml.rels"), 3)
        with mock.patch.object(lecture, "XML_LU_EN_ENTIER_MAX", 100_000):  # liens de la feuille : 41 Ko
            self.assertFalse(decompression_excessive(classeur(1), ".xlsx"))
            self.assertTrue(decompression_excessive(classeur(3), ".xlsx"))

    def test_xlsx_liens_d_une_feuille_declares_comme_feuille_comptes_en_entier(self):
        # Liens d'une feuille (.rels) déclarés de type « feuille de calcul » dans [Content_Types].xml : openpyxl les
        # analyse pourtant en entier. Ils restent comptés avec les parties lues en entier, pas avec les feuilles.
        from openpyxl import Workbook
        from openpyxl.packaging import relationship
        from openpyxl.reader import excel

        def classeur(declarer: bool) -> io.BytesIO:
            modele = Workbook()
            modele.active.append(["Entreprise", "Ville"])
            tampon = io.BytesIO()
            modele.save(tampon)
            flux = io.BytesIO()
            with zipfile.ZipFile(tampon) as source, zipfile.ZipFile(flux, "w", zipfile.ZIP_DEFLATED) as cible:
                for info in source.infolist():
                    donnees = source.read(info)
                    if info.filename == "[Content_Types].xml" and declarer:
                        donnees = donnees.replace(b"</Types>", (
                            f'<Override PartName="/xl/worksheets/_rels/sheet1.xml.rels" ContentType="{lecture.TYPE_FEUILLE}"/></Types>'
                        ).encode())
                    cible.writestr(info, donnees)
                cible.writestr("xl/autre.xml", b"<a>" + b"<b/>" * (100 * 1024) + b"</a>")  # 400 Ko d'autre XML lu en entier
                cible.writestr("xl/worksheets/_rels/sheet1.xml.rels", (
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    + '<Relationship Id="a" Type="t" Target="x"/>' * 10_000 + "</Relationships>"  # 400 Ko
                ))
            return flux

        for declarer in (False, True):
            with mock.patch.object(excel, "get_dependents", wraps=relationship.get_dependents) as liens:
                lecture.ouvrir_classeur(classeur(declarer)).close()
            self.assertIn("xl/worksheets/_rels/sheet1.xml.rels", [appel.args[1] for appel in liens.call_args_list])
            with mock.patch.object(lecture, "XML_LU_EN_ENTIER_MAX", 500_000):
                self.assertTrue(decompression_excessive(classeur(declarer), ".xlsx"), declarer)
            self.assertFalse(decompression_excessive(classeur(declarer), ".xlsx"))

    def test_xlsx_liens_externes_et_feuilles_de_graphique_jamais_lus(self):
        # load_workbook lit chaque lien externe autant de fois que <externalReferences> le cite, et chaque
        # feuille de graphique (graphiques compris, gardés en mémoire) autant de fois que <sheets> la cite et
        # que les cadres de son dessin désignent le graphique ; decompression_excessive compte ces parties
        # une fois (56 Ko faisaient monter le worker de 3,6 Go). ouvrir_classeur ne les lit jamais.
        from openpyxl import load_workbook
        from openpyxl.chart import reader as lecteur_graphiques
        from openpyxl.reader import drawings, workbook
        from openpyxl.workbook.external_link import external

        contenu = xlsx_graphique_et_liens_externes(citations=3, cadres=2, references=4)
        with (
            mock.patch.object(workbook, "read_external_link", wraps=external.read_external_link) as liens_externes,
            mock.patch.object(drawings, "read_chart", wraps=lecteur_graphiques.read_chart) as graphiques,
        ):
            classeur = load_workbook(io.BytesIO(contenu), read_only=True, data_only=True)
            self.assertEqual((liens_externes.call_count, graphiques.call_count), (4, 6))  # le danger, avec openpyxl seul
            self.assertEqual(len(classeur._external_links), 4)
            classeur.close()
            liens_externes.reset_mock()
            graphiques.reset_mock()

            classeur = lecture.ouvrir_classeur(io.BytesIO(contenu))
            self.assertEqual((liens_externes.call_count, graphiques.call_count), (0, 0))
            self.assertEqual(classeur.sheetnames, ["DPGF"])
            classeur.close()
            (self.dossier / "dpgf.xlsx").write_bytes(contenu)
            tableaux = lire_document(self.dossier / "dpgf.xlsx", self.dossier).tableaux
            self.assertEqual([(t.titre, t.lignes[-1]) for t in tableaux], [("DPGF", ["8.1", "Châssis aluminium", 850])])
            self.assertEqual((liens_externes.call_count, graphiques.call_count), (0, 0))

    def test_xlsx_citations_impossibles_a_etablir_refuse(self):
        # Liens du classeur dans un codage multi-octets, ou DTD (dont les entités démultiplient le texte) :
        # illisibles pour la vérification, mais lus par openpyxl (lxml). Le fichier est refusé.
        from openpyxl import load_workbook

        source = zipfile.ZipFile(io.BytesIO(xlsx_chaines_partagees([["Châssis aluminium", "u"]])))
        dtd = b'<!DOCTYPE x [<!ENTITY a "Lot 08">]>'
        for partie, entete in (
            ("xl/_rels/workbook.xml.rels", b'<?xml version="1.0" encoding="Shift_JIS"?>'),
            ("xl/_rels/workbook.xml.rels", dtd),
            ("xl/workbook.xml", dtd),
        ):
            flux = io.BytesIO()
            with zipfile.ZipFile(flux, "w", zipfile.ZIP_DEFLATED) as archive:
                for nom in source.namelist():
                    archive.writestr(nom, (entete if nom == partie else b"") + source.read(nom))
            self.assertEqual(load_workbook(flux, read_only=True).sheetnames, ["DPGF"])
            (self.dossier / "dpgf.xlsx").write_bytes(flux.getvalue())
            with mock.patch.object(lecture, "_lire_xlsx") as lire, self.assertRaisesMessage(ErreurLecture, "illisible"):
                lire_document(self.dossier / "dpgf.xlsx", self.dossier)
            lire.assert_not_called()
        # Liens démesurés : refusé comme trop volumineux.
        with mock.patch.object(lecture, "XML_COURT_MAX", 100):
            self.assertTrue(decompression_excessive(io.BytesIO(xlsx_chaines_partagees([["Châssis aluminium", "u"]])), ".xlsx"))

    def test_xlsx_largeur_des_lignes_bornee(self):
        # Dimension déclarée sur 16 384 colonnes, une cellule par ligne : openpyxl compléterait chaque ligne.
        (self.dossier / "dpgf.xlsx").write_bytes(
            xlsx_chaines_partagees([[f"Châssis {n}"] for n in range(2000)], dimension="A1:XFD2000")
        )
        lignes = lire_document(self.dossier / "dpgf.xlsx", self.dossier).tableaux[0].lignes
        self.assertEqual(len(lignes), 2000)
        self.assertEqual(lignes[-1][0], "Châssis 1999")
        self.assertLessEqual(max(len(ligne) for ligne in lignes), lecture.COLONNES_MAX)

    def test_xlsx_table_des_chaines_renommee_reperee_par_son_type(self):
        contenu = xlsx_chaines_partagees([[f"Châssis {n}", "u"] for n in range(400)], partie="xl/worksheets/chaines.xml")
        (self.dossier / "dpgf.xlsx").write_bytes(contenu)
        self.assertEqual(len(lire_document(self.dossier / "dpgf.xlsx", self.dossier).tableaux[0].lignes), 400)  # openpyxl la trouve
        with mock.patch.object(lecture, "XML_LU_EN_ENTIER_MAX", 5_000):
            self.assertTrue(decompression_excessive(io.BytesIO(contenu), ".xlsx"))

    def test_feuille_remplie_de_lignes_arretee(self):
        (self.dossier / "dpgf.xlsx").write_bytes(_xlsx(lignes=120))
        with mock.patch.object(lecture, "LIGNES_PAR_CLASSEUR_MAX", 50):
            contenu = lire_document(self.dossier / "dpgf.xlsx", self.dossier)
        self.assertEqual(len(contenu.tableaux[0].lignes), 50)

    def test_budget_de_lignes_commun_a_tout_le_classeur(self):
        from openpyxl import Workbook

        classeur = Workbook()
        for numero in range(3):
            feuille = classeur.active if numero == 0 else classeur.create_sheet()
            feuille.title = f"Lot {numero + 1}"
            for ligne in range(40):
                feuille.append([f"{numero + 1}.{ligne}", "Châssis aluminium", "u", 1, 850.0])
        classeur.save(self.dossier / "dpgf.xlsx")
        with mock.patch.object(lecture, "LIGNES_PAR_CLASSEUR_MAX", 50):
            contenu = lire_document(self.dossier / "dpgf.xlsx", self.dossier)
        self.assertEqual([len(tableau.lignes) for tableau in contenu.tableaux], [40, 10])

    def test_contenu_lu_demesure_refuse(self):
        # Une chaîne partagée de 32 000 caractères citée par 1 000 cellules : 32 Ko dans le fichier et dans la
        # mémoire de la lecture, mais 32 millions de caractères pour la suite (texte(), lignes de prix), faite
        # dans le worker, hors des plafonds de la lecture isolée.
        texte = "Châssis aluminium " * 1_777 + "Lot 08"
        source = zipfile.ZipFile(io.BytesIO(xlsx_chaines_partagees([["8.0", texte]])))
        with zipfile.ZipFile(self.dossier / "dpgf.xlsx", "w", zipfile.ZIP_DEFLATED) as archive:
            for nom in source.namelist():
                donnees = source.read(nom).decode()
                if nom == "xl/worksheets/sheet1.xml":  # 1 000 lignes citant la chaîne n° 1
                    donnees = donnees.replace("</sheetData>", "".join(
                        f'<row r="{n}"><c r="A{n}" t="inlineStr"><is><t>8.{n}</t></is></c><c r="B{n}" t="s"><v>1</v></c></row>'
                        for n in range(2, 1_001)
                    ) + "</sheetData>")
                archive.writestr(nom, donnees)
        self.assertLess((self.dossier / "dpgf.xlsx").stat().st_size, 20_000)
        lignes = lire_document(self.dossier / "dpgf.xlsx", self.dossier).tableaux[0].lignes
        self.assertEqual((len(lignes), lignes[-1][:2]), (1_000, ["8.1000", texte]))
        with mock.patch.object(lecture, "CONTENU_LU_MAX", 10_000_000), self.assertRaisesMessage(ErreurLecture, lecture.MESSAGE_CONTENU):
            lire_document(self.dossier / "dpgf.xlsx", self.dossier)
        self.assertFalse(lecture.contenu_demesure(lecture.ContenuDocument(blocs=[lecture.Bloc("texte", texte="x" * 1000)])))

    def test_archive_endommagee_reste_une_erreur_de_lecture(self):
        (self.dossier / "abime.docx").write_bytes(b"PK\x03\x04 pas une archive")
        with self.assertRaises(ErreurLecture):
            lire_document(self.dossier / "abime.docx", self.dossier)

    # --- Constat 4 : images liées d'un document converti par LibreOffice -----------------------------
    def test_conversion_avec_profil_qui_bloque_les_liens(self):
        source = self.dossier / "offre.odt"
        source.write_bytes(b"contenu")
        travail = self.dossier / "travail"
        travail.mkdir()
        vu = {}

        def lancer(commande, **_options):
            profil = next(c for c in commande if c.startswith("-env:UserInstallation="))
            reglages = Path(profil.split("=", 1)[1].removeprefix("file://")) / "user" / "registrymodifications.xcu"
            vu["reglages"] = reglages.read_text(encoding="utf-8")
            (travail / "source.docx").write_bytes(b"converti")
            return subprocess.CompletedProcess(commande, 0, b"", b"")

        with mock.patch("shutil.which", return_value="/usr/bin/soffice"), mock.patch("subprocess.run", side_effect=lancer):
            resultat = lecture.convertir(source, "docx", travail)
        self.assertEqual(resultat, travail / "source.docx")
        self.assertIn('oor:name="BlockUntrustedRefererLinks"', vu["reglages"])
        self.assertIn("<value>true</value>", vu["reglages"])
        import xml.etree.ElementTree as ET

        ET.fromstring(vu["reglages"].encode())  # registre LibreOffice bien formé
