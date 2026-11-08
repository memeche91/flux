import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import skipUnless

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from articles.models import Article
from articles.tests import cctp_tce_docx, dpgf_xlsx
from comptes.models import Utilisateur
from referentiel.models import Lot

from .html import nettoyer_html
from .models import GenrePoste, LotProjet, Poste, Projet
from .structure import structurer

DOSSIER_TEST = tempfile.mkdtemp(prefix="application-ao-projets-")
LIBREOFFICE = shutil.which("soffice")

DESCRIPTION_RICHE = (
    '<p style="text-align: justify">Fenêtres en <strong>aluminium</strong> à '
    '<span style="color: #C00000; font-size: 12pt">rupture de pont thermique</span>, '
    '<mark data-color="#FFF59D">Uw ≤ 1,3</mark>.</p>'
    "<ul><li><p>Laquage RAL</p></li><li><p>Vitrage 4/16/4</p></li></ul>"
    '<table><tbody><tr><th><p>Repère</p></th><th><p>Dimensions</p></th></tr>'
    '<tr><td style="background-color: #FFF2CC"><p>F1</p></td><td><p>120 x 135</p></td></tr></tbody></table>'
)


@override_settings(MEDIA_ROOT=DOSSIER_TEST)
class ProjetsTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_TEST, ignore_errors=True)

    def setUp(self):
        self.client.force_login(Utilisateur.objects.create_user("economiste", password="mot-de-passe-solide-42"))
        self.lots = {lot.code: lot for lot in Lot.objects.all()}

    def json(self, methode, url, donnees=None):
        if methode == "get":
            reponse = self.client.get(url, donnees or {})
        else:
            reponse = getattr(self.client, methode)(url, json.dumps(donnees or {}), content_type="application/json")
        self.assertLess(reponse.status_code, 300, reponse.content)
        return reponse.json() if reponse.content else None

    def creer_projet_et_lot(self):
        projet = self.json(
            "post",
            "/api/projets",
            {
                "nom": "Groupe scolaire des Tilleuls",
                "maitre_ouvrage": "Ville de Saint-Aubin",
                "maitre_oeuvre": "Atelier d'architecture",
                "procedure": "Procédure adaptée",
                "lots": [self.lots["08"].pk],
            },
        )
        return projet, projet["lots"][0]["id"]

    def construire_lot(self, lot_id):
        """Généralités + 2 ouvrages de base + 1 ouvrage en PSE n°1."""
        detail = self.json("get", f"/api/lots-projet/{lot_id}")
        generalites, description = [p["id"] for p in detail["postes"]]
        self.json("post", f"/api/lots-projet/{lot_id}/postes", {"genre": "ARTICLE", "titre": "Documents de référence", "description": "<p>NF DTU 36.5</p>", "apres_id": generalites})
        detail = self.json("post", f"/api/lots-projet/{lot_id}/options", {"genre": "PSE", "libelle": "Volets roulants"})
        option_id = detail["options"][0]["id"]
        self.json("post", f"/api/lots-projet/{lot_id}/postes", {"titre": "Fenêtres aluminium", "description": DESCRIPTION_RICHE, "unite": "u", "quantite": "14", "prix_unitaire": "980"})
        self.json("post", f"/api/lots-projet/{lot_id}/postes", {"titre": "Habillages", "unite": "ml", "quantite": "85", "prix_unitaire": "42.50"})
        return self.json("post", f"/api/lots-projet/{lot_id}/postes", {"titre": "Volets roulants électriques", "unite": "u", "quantite": "22", "prix_unitaire": "640", "option_id": option_id})

    # --- Structure et API ---

    def test_creation_projet_numerotation_et_totaux(self):
        projet, lot_id = self.creer_projet_et_lot()
        self.assertEqual(projet["lots"][0]["code"], "08")
        detail = self.construire_lot(lot_id)
        self.assertEqual(
            [(p["numero"], p["titre"]) for p in detail["postes"]],
            [
                ("8.1", "Généralités"),
                ("8.1.1", "Documents de référence"),
                ("8.2", "Description des ouvrages"),
                ("8.2.1", "Fenêtres aluminium"),
                ("8.2.2", "Habillages"),
                ("8.2.3", "Volets roulants électriques"),
            ],
        )
        self.assertEqual(detail["total_base"], 13720 + 3612.5)
        self.assertEqual(detail["options"][0]["total"], 14080)
        self.assertEqual(detail["options"][0]["nom_court"], "PSE n°1")

    def test_deplacer_un_chapitre_avec_son_contenu(self):
        _, lot_id = self.creer_projet_et_lot()
        detail = self.construire_lot(lot_id)
        description = detail["postes"][2]["id"]
        detail = self.json("post", f"/api/postes/{description}/deplacer", {"sens": "haut"})
        self.assertEqual([p["numero"] + " " + p["titre"] for p in detail["postes"]][:2], ["8.1 Description des ouvrages", "8.1.1 Fenêtres aluminium"])
        self.assertEqual(detail["postes"][-1]["titre"], "Documents de référence")
        habillage = next(p["id"] for p in detail["postes"] if p["titre"] == "Habillages")
        detail = self.json("post", f"/api/postes/{habillage}/deplacer", {"sens": "haut"})
        self.assertEqual(detail["postes"][1]["titre"], "Habillages")

    def test_description_nettoyee(self):
        _, lot_id = self.creer_projet_et_lot()
        detail = self.json(
            "post",
            f"/api/lots-projet/{lot_id}/postes",
            {"titre": "Test", "description": '<p onclick="x()">ok<script>alert(1)</script><img src=x onerror=alert(1)></p>'},
        )
        poste = detail["postes"][-1]
        self.assertEqual(poste["description"], "<p>ok</p>")
        self.assertEqual(nettoyer_html('<p style="position:fixed;color:red">a</p>'), '<p style="color:red">a</p>')

    def test_reprise_d_un_ancien_cctp_et_d_une_dpgf(self):
        _, lot_id = self.creer_projet_et_lot()
        with self.captureOnCommitCallbacks(execute=True):
            cctp = self.client.post(
                "/api/bibliotheque/documents",
                {"fichier": SimpleUploadedFile("CCTP TCE.docx", cctp_tce_docx()), "type_document": "CCTP", "lot_id": self.lots["TCE"].pk},
            ).json()
        resultat = self.json("post", f"/api/lots-projet/{lot_id}/importer", {"document_id": cctp["id"]})
        # Seuls les articles du lot 08 du document « tous corps d'état » sont repris ;
        # un article placé directement sous le titre du lot va dans « Généralités ».
        self.assertEqual(resultat["importes"], 2)
        self.assertEqual(
            [(p["genre"], p["numero"], p["titre"]) for p in resultat["lot"]["postes"]],
            [
                ("CHAPITRE", "8.1", "Généralités"),
                ("ARTICLE", "8.1.1", "Prescriptions générales"),
                ("CHAPITRE", "8.2", "Châssis aluminium"),
                ("OUVRAGE", "8.2.1", "Fenêtres oscillo-battantes"),
            ],
        )
        self.assertIn("<table>", resultat["lot"]["postes"][3]["description"])

        with self.captureOnCommitCallbacks(execute=True):
            dpgf = self.client.post(
                "/api/bibliotheque/documents",
                {"fichier": SimpleUploadedFile("DPGF.xlsx", dpgf_xlsx()), "type_document": "DPGF", "lot_id": self.lots["08"].pk},
            ).json()
        resultat = self.json("post", f"/api/lots-projet/{lot_id}/importer", {"document_id": dpgf["id"]})
        self.assertEqual(resultat["importes"], 4)
        ouvrage = next(p for p in resultat["lot"]["postes"] if p["titre"].startswith("Porte-fenêtre"))
        self.assertEqual((ouvrage["unite"], ouvrage["quantite"], ouvrage["prix_unitaire"]), ("u", 4.0, 2450.0))

        article = Article.objects.filter(numero="3.2").first()
        detail = self.json("post", f"/api/lots-projet/{lot_id}/inserer-article", {"article_id": article.pk})
        self.assertEqual(detail["postes"][-1]["titre"], "Fondations superficielles")

    def test_supprimer_une_pse_ramene_ses_ouvrages_dans_la_base(self):
        _, lot_id = self.creer_projet_et_lot()
        detail = self.construire_lot(lot_id)
        detail = self.json("delete", f"/api/options/{detail['options'][0]['id']}")
        self.assertEqual(detail["options"], [])
        self.assertEqual(detail["total_base"], 13720 + 3612.5 + 14080)

    # --- Exports ---

    def lot_construit(self):
        _, lot_id = self.creer_projet_et_lot()
        self.construire_lot(lot_id)
        return lot_id

    def test_export_cctp_word(self):
        from docx import Document

        lot_id = self.lot_construit()
        reponse = self.client.get(f"/api/lots-projet/{lot_id}/export/cctp-docx")
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("CCTP%20Lot%2008%20-%20Menuiseries%20ext%C3%A9rieures.docx", reponse["Content-Disposition"])
        document = Document(io.BytesIO(reponse.content))
        titres = [(p.style.name, p.text) for p in document.paragraphs if p.style.name.startswith("Heading")]
        self.assertIn(("Heading 1", "8.2 Description des ouvrages"), titres)
        self.assertIn(("Heading 2", "8.2.3 Volets roulants électriques (PSE n°1)"), titres)
        xml = document.element.xml
        self.assertIn('TOC \\o "1-2"', xml)
        self.assertIn("C00000", xml)  # couleur du texte
        self.assertIn('w:fill="FFF2CC"', xml)  # fond de cellule
        self.assertIn("rupture de pont thermique", xml)
        pied = document.sections[1].footer._element.xml
        self.assertIn("NUMPAGES", pied)
        self.assertIn("updateFields", document.settings.element.xml)

    def test_export_cctp_pdf_avec_sommaire_pagine(self):
        import pdfplumber

        lot_id = self.lot_construit()
        reponse = self.client.get(f"/api/lots-projet/{lot_id}/export/cctp-pdf")
        self.assertEqual(reponse["Content-Type"], "application/pdf")
        with pdfplumber.open(io.BytesIO(reponse.content)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        self.assertIn("CAHIER DES CLAUSES TECHNIQUES PARTICULIÈRES", pages[0].upper())
        self.assertIn("Sommaire", pages[1])
        ligne_sommaire = next(l for l in pages[1].splitlines() if "8.2.1" in l)
        self.assertRegex(ligne_sommaire, r"Fenêtres aluminium\s*\.+\s*3$")
        self.assertIn("8.2.1 Fenêtres aluminium", pages[2])
        self.assertIn("Page 3 / ", pages[2])

    def test_export_dpgf_pdf(self):
        import pdfplumber

        lot_id = self.lot_construit()
        for prix, attendu in ((False, "Cadre réservé à l'entreprise"), (True, "13 720,00")):
            reponse = self.client.get(f"/api/lots-projet/{lot_id}/export/dpgf-pdf", {"prix": prix})
            with pdfplumber.open(io.BytesIO(reponse.content)) as pdf:
                texte = "\n".join(page.extract_text() or "" for page in pdf.pages).replace(" ", " ")
            self.assertIn(attendu, texte)
            self.assertIn("TOTAL SOLUTION DE BASE HT", texte)
            self.assertIn("PSE N°1 – VOLETS ROULANTS", texte.upper())
            if prix:
                self.assertIn("17 332,50", texte)  # total de la solution de base

    def test_export_dpgf_excel(self):
        from openpyxl import load_workbook

        lot_id = self.lot_construit()
        reponse = self.client.get(f"/api/lots-projet/{lot_id}/export/dpgf-xlsx")
        classeur = load_workbook(io.BytesIO(reponse.content))
        self.assertEqual(classeur.sheetnames, ["Page de garde", "DPGF", "Récapitulatif"])
        feuille = classeur["DPGF"]
        lignes = {feuille.cell(r, 1).value: r for r in range(1, feuille.max_row + 1) if feuille.cell(r, 1).value}
        ligne_fenetres = lignes["8.2.1"]
        self.assertEqual(feuille.cell(ligne_fenetres, 4).value, 14)
        self.assertIsNone(feuille.cell(ligne_fenetres, 5).value)  # DPGF vierge : PU à compléter
        self.assertTrue(str(feuille.cell(ligne_fenetres, 6).value).startswith("=IF("))
        self.assertIn("PSE n°1", classeur["Récapitulatif"]["A7"].value)

    @skipUnless(LIBREOFFICE, "LibreOffice n'est pas installé")
    def test_formules_excel_recalculees(self):
        """Ouvre la DPGF chiffrée dans LibreOffice et vérifie les totaux calculés."""
        lot_id = self.lot_construit()
        contenu = self.client.get(f"/api/lots-projet/{lot_id}/export/dpgf-xlsx", {"prix": True}).content
        from openpyxl import load_workbook

        with tempfile.TemporaryDirectory() as dossier:
            source = Path(dossier) / "dpgf.xlsx"
            source.write_bytes(contenu)
            sortie = Path(dossier) / "recalcule"
            subprocess.run(
                [LIBREOFFICE, f"-env:UserInstallation={Path(dossier, 'p').as_uri()}", "--headless",
                 "--convert-to", "xlsx", "--outdir", str(sortie), str(source)],
                check=True, capture_output=True, timeout=180,
            )
            classeur = load_workbook(sortie / "dpgf.xlsx", data_only=True)
        valeurs = {ligne[0]: ligne[1:] for ligne in classeur["Récapitulatif"].iter_rows(min_row=6, values_only=True) if ligne[0]}
        base_ht, base_tva, base_ttc = valeurs["Solution de base"]
        self.assertAlmostEqual(base_ht, 17332.50, places=2)
        self.assertAlmostEqual(base_tva, 3466.50, places=2)
        self.assertAlmostEqual(base_ttc, 20799.00, places=2)
        pse = next(v for cle, v in valeurs.items() if cle.startswith("PSE n°1"))
        self.assertAlmostEqual(pse[2], 16896.00, places=2)


class StructureTests(TestCase):
    def test_postes_avant_le_premier_chapitre(self):
        projet = Projet.objects.create(nom="Test")
        lot = LotProjet.objects.create(projet=projet, code="TCE", intitule="Tous corps d'état")
        Poste.objects.create(lot=lot, ordre=10, genre=GenrePoste.ARTICLE, titre="Préambule")
        Poste.objects.create(lot=lot, ordre=20, genre=GenrePoste.CHAPITRE, titre="Ouvrages")
        structure = structurer(lot)
        self.assertEqual(list(structure.numeros.values()), ["TCE.0.1", "TCE.1"])
