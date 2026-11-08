import io
import shutil
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest import skipUnless

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings

from bibliotheque.lecture import Bloc, Tableau
from bibliotheque.models import DocumentReference, StatutAnalyse
from comptes.models import Utilisateur
from referentiel.models import Lot

from .decoupage import decouper, detecter_titre
from .models import Article, LignePrix
from .normalisation import detecter_lot, extraire_references, lire_nombre, normaliser_unite, separer_numero
from .prix import extraire_lignes_prix

DOSSIER_TEST = tempfile.mkdtemp(prefix="application-ao-articles-")
LIBREOFFICE = shutil.which("soffice")
TESSERACT = shutil.which("tesseract")


# --- Fichiers d'exemple ------------------------------------------------------


def cctp_tce_docx() -> bytes:
    """CCTP tous corps d'état : titres Word, lots, généralités, tableau, sommaire."""
    from docx import Document

    document = Document()
    document.add_paragraph("Sommaire", style="TOC Heading") if "TOC Heading" in [s.name for s in document.styles] else None
    document.add_paragraph("Le présent CCTP décrit les travaux de réhabilitation du groupe scolaire. " * 4)
    document.add_heading("LOT 03 – GROS ŒUVRE", level=1)
    document.add_heading("3.1 Généralités", level=2)
    document.add_paragraph("Les ouvrages seront exécutés conformément au NF DTU 21 et à l'Eurocode 2.")
    document.add_heading("3.2 Fondations superficielles", level=2)
    document.add_paragraph("Semelles filantes en béton armé selon le DTU 13.11.")
    document.add_heading("LOT 08 – MENUISERIES EXTÉRIEURES", level=1)
    document.add_heading("8.1 Prescriptions générales", level=2)
    document.add_paragraph("Mise en œuvre conforme au NF DTU 36.5 et à la norme NF EN 14351-1.")
    document.add_heading("8.2 Châssis aluminium", level=2)
    document.add_heading("8.2.1 Fenêtres oscillo-battantes", level=3)
    document.add_paragraph("Châssis à rupture de pont thermique, double vitrage 4/16/4 argon, Uw ≤ 1,3 W/m².K (RE 2020).")
    tableau = document.add_table(rows=2, cols=2)
    tableau.rows[0].cells[0].text = "Repère"
    tableau.rows[0].cells[1].text = "Dimensions"
    tableau.rows[1].cells[0].text = "F1"
    tableau.rows[1].cells[1].text = "120 x 135"
    flux = io.BytesIO()
    document.save(flux)
    return flux.getvalue()


def dpgf_xlsx() -> bytes:
    from openpyxl import Workbook

    classeur = Workbook()
    garde = classeur.active
    garde.title = "Page de garde"
    garde.append(["DPGF – Lot 08 Menuiseries extérieures"])
    feuille = classeur.create_sheet("DPGF")
    feuille.append(["Groupe scolaire des Tilleuls"])
    feuille.append([])
    feuille.append(["N°", "Désignation des ouvrages", "U", "Qté", "P.U. HT", "Montant HT"])
    feuille.append(["8.2", "CHÂSSIS ALUMINIUM", None, None, None, None])
    feuille.append(["8.2.1", "Fenêtre oscillo-battante 120 x 135", "U", 14, 980, 13720])
    feuille.append(["8.2.2", "Porte-fenêtre 2 vantaux 180 x 215", "u", 4, "2 450,00 €", 9800])
    feuille.append(["8.3", "Habillages", "ml", "35,5", "42,50", None])
    feuille.append(["8.4", "Option : volets roulants", "u", 18, None, None])
    feuille.append([None, "Sous-total chapitre 8.2", None, None, None, 23520])
    feuille.append([None, "TOTAL HT", None, None, None, 99999])
    feuille.append([None, "TVA 20 %", None, None, None, 1])
    flux = io.BytesIO()
    classeur.save(flux)
    return flux.getvalue()


# --- Tests unitaires ----------------------------------------------------------


class NormalisationTests(SimpleTestCase):
    def test_lecture_des_nombres(self):
        self.assertEqual(lire_nombre("1 250,50 €"), Decimal("1250.50"))
        self.assertEqual(lire_nombre("1.250,50"), Decimal("1250.50"))
        self.assertEqual(lire_nombre("1,250.50"), Decimal("1250.50"))
        self.assertEqual(lire_nombre("12.5"), Decimal("12.5"))
        self.assertEqual(lire_nombre("1.250"), Decimal("1250"))
        self.assertEqual(lire_nombre(980), Decimal("980"))
        self.assertIsNone(lire_nombre("PM"))
        self.assertIsNone(lire_nombre("Inclus"))
        self.assertIsNone(lire_nombre(None))

    def test_unites(self):
        self.assertEqual(normaliser_unite("M2"), "m²")
        self.assertEqual(normaliser_unite("m²"), "m²")
        self.assertEqual(normaliser_unite("U"), "u")
        self.assertEqual(normaliser_unite("Forfait"), "ft")
        self.assertEqual(normaliser_unite("ML"), "ml")

    def test_references_normatives(self):
        texte = "Selon le NF DTU 36.5, le DTU 25.41, la norme NF EN 14351-1, la NF C 15-100, l'Eurocode 2 et la RE 2020."
        self.assertEqual(
            extraire_references(texte),
            ["DTU 25.41", "DTU 36.5", "Eurocode 2", "NF C 15-100", "NF EN 14351-1", "RE2020"],
        )

    def test_numero_et_lot(self):
        self.assertEqual(separer_numero("3.2.4 Châssis aluminium"), ("3.2.4", "Châssis aluminium"))
        self.assertEqual(separer_numero("8.2.1. Fenêtres"), ("8.2.1", "Fenêtres"))
        self.assertEqual(separer_numero("Châssis"), ("", "Châssis"))
        self.assertEqual(detecter_lot("LOT N° 8 – Menuiseries"), "08")
        self.assertEqual(detecter_lot("Lot 03 : Gros œuvre"), "03")
        self.assertIsNone(detecter_lot("Voir le lot 3"))


class DecoupageTests(SimpleTestCase):
    def test_titres_reconnus_dans_le_texte(self):
        self.assertEqual(detecter_titre("3.2.4 Châssis aluminium").numero, "3.2.4")
        self.assertEqual(detecter_titre("ARTICLE 4 – PÉNALITÉS DE RETARD").numero, "Article 4")
        self.assertEqual(detecter_titre("LOT N° 08 – MENUISERIES").numero, "Lot 08")
        self.assertEqual(detecter_titre("2 PRESCRIPTIONS TECHNIQUES").niveau, 1)
        # Ne sont pas des titres :
        self.assertIsNone(detecter_titre("1. Les ouvrages seront livrés propres et en parfait état de fonctionnement."))
        self.assertIsNone(detecter_titre("150 mm d'isolant en laine minérale"))
        self.assertIsNone(detecter_titre("3.2 Châssis aluminium ............ 12"))
        self.assertIsNone(detecter_titre("2024 travaux de réhabilitation"))

    def test_decoupage_texte_pdf(self):
        lignes = [
            "SOMMAIRE",
            "1 GÉNÉRALITÉS .......... 3",
            "1 GÉNÉRALITÉS",
            "1.1 Objet du marché",
            "Le présent document décrit les travaux de menuiseries extérieures.",
            "1.2 Normes",
            "Les travaux respecteront le DTU 36.5.",
            "2 DESCRIPTION DES OUVRAGES",
            "2.1 Fenêtres",
            "1. Les fenêtres seront en aluminium laqué.",
            "2. Les vitrages seront feuilletés.",
        ]
        articles = decouper([Bloc("texte", texte=l) for l in lignes], titre_par_defaut="CCTP", administratif=False)
        self.assertEqual([a.numero for a in articles], ["1.1", "1.2", "2.1"])
        self.assertEqual(articles[0].chemin, "1 GÉNÉRALITÉS")
        self.assertEqual(articles[0].categorie, "GENERALITES")
        self.assertEqual(articles[1].references, ["DTU 36.5"])
        self.assertEqual(articles[2].categorie, "OUVRAGE")
        self.assertIn("2. Les vitrages seront feuilletés.", articles[2].contenu)

    def test_document_sans_titre(self):
        articles = decouper(
            [Bloc("texte", texte="Un texte libre sans aucun titre, mais suffisamment long.")],
            titre_par_defaut="Note",
            administratif=True,
        )
        self.assertEqual(len(articles), 1)
        self.assertEqual((articles[0].titre, articles[0].categorie), ("Note", "CLAUSE"))


class PrixTests(SimpleTestCase):
    def test_tableau_coupe_sur_plusieurs_pages(self):
        page1 = Tableau("Page 1", [["N°", "Désignation", "U", "Qté", "PU", "Total"], ["1", "Dépose", "ft", "1", "1 500,00", "1 500,00"]])
        page2 = Tableau("Page 2", [["2", "Repose", "u", "3", "200", "600"]])
        lignes = extraire_lignes_prix([page1, page2])
        self.assertEqual([l.designation for l in lignes], ["Dépose", "Repose"])
        self.assertEqual(lignes[0].prix_unitaire, Decimal("1500.00"))

    def test_lot_dans_une_dpgf_tous_corps_etat(self):
        tableau = Tableau(
            "DPGF TCE",
            [
                ["Désignation", "U", "Qté", "PU"],
                ["LOT 03 – GROS ŒUVRE", None, None, None],
                ["Béton de propreté", "m3", 12, 140],
                ["LOT 08 – MENUISERIES", None, None, None],
                ["Fenêtre", "u", 4, 900],
            ],
        )
        self.assertEqual([l.code_lot for l in extraire_lignes_prix([tableau])], ["03", "08"])


# --- Tests de bout en bout (API) ----------------------------------------------


@override_settings(MEDIA_ROOT=DOSSIER_TEST)
class IndexationApiTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_TEST, ignore_errors=True)

    def setUp(self):
        self.client.force_login(
            Utilisateur.objects.create_user("economiste", password="mot-de-passe-solide-42", role="MOE")
        )
        self.lots = {lot.code: lot for lot in Lot.objects.all()}

    def televerser(self, nom, contenu, **donnees):
        with self.captureOnCommitCallbacks(execute=True):
            reponse = self.client.post(
                "/api/bibliotheque/documents", {"fichier": SimpleUploadedFile(nom, contenu), **donnees}
            )
        self.assertEqual(reponse.status_code, 201, reponse.content)
        return DocumentReference.objects.get(pk=reponse.json()["id"])

    def test_cctp_tce_decoupe_en_articles_par_lot(self):
        document = self.televerser("CCTP TCE.docx", cctp_tce_docx(), type_document="CCTP", lot_id=self.lots["TCE"].pk)
        self.assertEqual(document.statut_analyse, StatutAnalyse.ANALYSE, document.message_analyse)
        self.assertIn("5 articles", document.message_analyse)

        articles = {a.numero: a for a in Article.objects.filter(document=document)}
        self.assertEqual(set(articles), {"", "3.1", "3.2", "8.1", "8.2.1"})  # « » = préambule
        self.assertEqual(articles[""].titre, "Préambule")
        self.assertEqual(articles["3.2"].lot.code, "03")
        self.assertEqual(articles["8.2.1"].lot.code, "08")
        self.assertEqual(articles["8.2.1"].chemin, "Lot 08 MENUISERIES EXTÉRIEURES › 8.2 Châssis aluminium")
        self.assertEqual(articles["8.1"].categorie, "GENERALITES")
        self.assertEqual(articles["8.2.1"].categorie, "OUVRAGE")
        self.assertIn("F1 | 120 x 135", articles["8.2.1"].contenu)
        self.assertEqual(articles["8.1"].liste_references, ["DTU 36.5", "NF EN 14351-1"])

        reponse = self.client.get("/api/articles", {"lot_id": self.lots["08"].pk, "recherche": "chassis pont"}).json()
        self.assertEqual([a["numero"] for a in reponse["resultats"]], ["8.2.1"])
        reponse = self.client.get("/api/articles", {"reference": "DTU 36.5"}).json()
        self.assertEqual(reponse["total"], 1)
        references = self.client.get("/api/articles/references").json()
        self.assertIn({"reference": "DTU 13.11", "nombre": 1}, references)

        liste = self.client.get("/api/bibliotheque/documents", {"type_document": "CCTP"}).json()
        self.assertEqual(liste[0]["nb_articles"], 5)

    def test_dpgf_lignes_de_prix_et_statistiques(self):
        document = self.televerser("DPGF lot 08.xlsx", dpgf_xlsx(), type_document="DPGF", lot_id=self.lots["08"].pk)
        self.assertIn("4 lignes de prix, dont 3 chiffrées", document.message_analyse)

        lignes = list(LignePrix.objects.filter(document=document).order_by("ordre"))
        self.assertEqual([l.numero for l in lignes], ["8.2.1", "8.2.2", "8.3", "8.4"])
        self.assertEqual(lignes[0].chapitre, "8.2 CHÂSSIS ALUMINIUM")
        self.assertEqual(lignes[1].prix_unitaire, Decimal("2450.00"))
        self.assertEqual(lignes[2].quantite, Decimal("35.500"))
        self.assertEqual(lignes[2].unite_normalisee, "ml")
        self.assertIsNone(lignes[3].prix_unitaire)

        # « châssis » est cherché dans la désignation et dans le chapitre (8.2 CHÂSSIS ALUMINIUM).
        reponse = self.client.get("/api/prix", {"recherche": "chassis"}).json()
        self.assertEqual(reponse["total"], 3)
        self.assertEqual(
            reponse["statistiques"],
            [
                {"unite": "u", "nombre": 2, "minimum": 980.0, "mediane": 1715.0, "maximum": 2450.0},
                {"unite": "ml", "nombre": 1, "minimum": 42.5, "mediane": 42.5, "maximum": 42.5},
            ],
        )
        self.assertEqual(self.client.get("/api/prix", {"recherche": "fenetre oscillo"}).json()["total"], 1)
        tout = self.client.get("/api/prix", {"chiffrees": "false"}).json()
        self.assertEqual(tout["total"], 4)

        stats = self.client.get("/api/bibliotheque/statistiques").json()
        self.assertEqual((stats["lignes_prix"], stats["lignes_chiffrees"]), (4, 3))

    def test_relancer_analyse_et_suppression_en_cascade(self):
        document = self.televerser("DPGF lot 08.xlsx", dpgf_xlsx(), type_document="DPGF", lot_id=self.lots["08"].pk)
        with self.captureOnCommitCallbacks(execute=True):
            reponse = self.client.post(f"/api/bibliotheque/documents/{document.pk}/analyser")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(LignePrix.objects.count(), 4)  # pas de doublons après une nouvelle analyse
        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(f"/api/bibliotheque/documents/{document.pk}")
        self.assertEqual(LignePrix.objects.count(), 0)

    @skipUnless(LIBREOFFICE, "LibreOffice n'est pas installé")
    def test_ancien_format_doc_converti(self):
        with tempfile.TemporaryDirectory() as dossier:
            source = Path(dossier) / "cctp.docx"
            source.write_bytes(cctp_tce_docx())
            subprocess.run(
                [LIBREOFFICE, f"-env:UserInstallation={Path(dossier, 'profil').as_uri()}", "--headless",
                 "--convert-to", "doc", "--outdir", dossier, str(source)],
                check=True, capture_output=True, timeout=180,
            )
            contenu_doc = (Path(dossier) / "cctp.doc").read_bytes()
        document = self.televerser("ancien CCTP.doc", contenu_doc, type_document="CCTP", lot_id=self.lots["TCE"].pk)
        self.assertEqual(document.statut_analyse, StatutAnalyse.ANALYSE, document.message_analyse)
        self.assertIn("converti depuis .doc", document.message_analyse)
        self.assertTrue(Article.objects.filter(document=document, numero="8.2.1", lot__code="08").exists())

    @skipUnless(TESSERACT, "Tesseract n'est pas installé")
    def test_pdf_scanne_lu_par_ocr(self):
        from PIL import Image, ImageDraw, ImageFont

        page = Image.new("RGB", (1654, 2339), "white")  # A4 à 200 dpi
        dessin = ImageDraw.Draw(page)
        dejavu = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        police = ImageFont.truetype(str(dejavu), 44) if dejavu.exists() else ImageFont.load_default(size=44)
        lignes = ["3.2 Menuiseries aluminium", "Les chassis seront conformes au DTU 36.5.", "Double vitrage isolant."]
        for indice, ligne in enumerate(lignes):
            dessin.text((150, 200 + indice * 90), ligne, fill="black", font=police)
        flux = io.BytesIO()
        page.save(flux, format="PDF", resolution=200, quality=95)

        document = self.televerser("CCTP scanné.pdf", flux.getvalue(), type_document="CCTP", lot_id=self.lots["08"].pk)
        self.assertEqual(document.statut_analyse, StatutAnalyse.ANALYSE, document.message_analyse)
        self.assertIn("OCR sur 1 page", document.message_analyse)
        self.assertIn("DTU 36.5", document.texte_extrait)
        article = Article.objects.get(document=document)
        self.assertEqual(article.titre, "Menuiseries aluminium")
