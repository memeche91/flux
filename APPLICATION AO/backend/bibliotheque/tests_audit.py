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
    lignes: list[list[str]], partie: str = "xl/sharedStrings.xml", *, dimension: str = "", types_en_plus: str = "", liens_en_plus: str = ""
) -> bytes:
    """Classeur avec une table des chaînes partagées, comme Excel l'écrit (openpyxl écrit le texte en ligne).

    dimension : zone déclarée par la feuille (« A1:XFD2000 ») ; types_en_plus et liens_en_plus : éléments
    ajoutés à [Content_Types].xml et aux liens du classeur.
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
            f'<workbook xmlns="{principal}" xmlns:r="{relations}"><sheets><sheet name="DPGF" sheetId="1" r:id="rId1"/></sheets></workbook>'
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
