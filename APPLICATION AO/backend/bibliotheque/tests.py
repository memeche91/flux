import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from comptes.models import Utilisateur
from referentiel.models import Lot

from .models import DocumentReference, StatutAnalyse

DOSSIER_TEST = tempfile.mkdtemp(prefix="application-ao-tests-")


def fichier_docx(nom="CCTP lot 08.docx"):
    from docx import Document

    document = Document()
    document.add_heading("Lot 08 – Menuiseries extérieures", level=1)
    document.add_heading("8.1 Châssis aluminium", level=2)
    document.add_paragraph("Châssis à rupture de pont thermique, Uw ≤ 1,3 W/m².K.")
    tableau = document.add_table(rows=1, cols=2)
    tableau.rows[0].cells[0].text = "Repère"
    tableau.rows[0].cells[1].text = "Dimensions"
    flux = io.BytesIO()
    document.save(flux)
    return SimpleUploadedFile(nom, flux.getvalue())


def fichier_xlsx(nom="DPGF lot 08.xlsx"):
    from openpyxl import Workbook

    classeur = Workbook()
    feuille = classeur.active
    feuille.title = "DPGF"
    feuille.append(["N°", "Désignation", "U", "Qté", "PU HT"])
    feuille.append(["8.1", "Châssis aluminium", "u", 12, 850.0])
    flux = io.BytesIO()
    classeur.save(flux)
    return SimpleUploadedFile(nom, flux.getvalue())


@override_settings(MEDIA_ROOT=DOSSIER_TEST)
class BibliothequeApiTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_TEST, ignore_errors=True)

    def setUp(self):
        self.utilisateur = Utilisateur.objects.create_user(
            "economiste", password="mot-de-passe-solide-42", role=Utilisateur.Role.MOE
        )
        self.client.force_login(self.utilisateur)
        self.lot = Lot.objects.get(code="08")

    def televerser(self, fichier, **donnees):
        # L'analyse est lancée après validation en base : on exécute ces rappels.
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post("/api/bibliotheque/documents", {"fichier": fichier, **donnees})

    def test_cctp_docx_importe_et_analyse(self):
        reponse = self.televerser(
            fichier_docx(), type_document="CCTP", lot_id=self.lot.pk, operation="Collège Pasteur", annee=2024
        )
        self.assertEqual(reponse.status_code, 201, reponse.content)
        self.assertEqual(reponse.json()["lot"]["code"], "08")

        document = DocumentReference.objects.get()
        self.assertEqual(document.statut_analyse, StatutAnalyse.ANALYSE)
        self.assertIn("# Lot 08 – Menuiseries extérieures", document.texte_extrait)
        self.assertIn("## 8.1 Châssis aluminium", document.texte_extrait)
        self.assertIn("Repère | Dimensions", document.texte_extrait)
        self.assertTrue(document.fichier.name.startswith("bibliotheque/CCTP/08/"))

    def test_dpgf_xlsx_analysee(self):
        reponse = self.televerser(fichier_xlsx(), type_document="DPGF", lot_id=self.lot.pk)
        self.assertEqual(reponse.status_code, 201, reponse.content)
        texte = DocumentReference.objects.get().texte_extrait
        self.assertIn("8.1 | Châssis aluminium | u | 12 | 850", texte)

    def test_nombre_de_documents_illimite_et_doublon_refuse(self):
        for numero in range(5):
            reponse = self.televerser(
                SimpleUploadedFile(f"ccap-{numero}.pdf", f"contenu {numero}".encode()), type_document="CCAP"
            )
            self.assertEqual(reponse.status_code, 201, reponse.content)
        doublon = self.televerser(SimpleUploadedFile("copie.pdf", b"contenu 0"), type_document="CCAP")
        self.assertEqual(doublon.status_code, 409)
        self.assertIn("ccap-0.pdf", doublon.json()["detail"])
        self.assertEqual(DocumentReference.objects.count(), 5)

    def test_lot_obligatoire_pour_cctp_et_interdit_pour_rc(self):
        sans_lot = self.televerser(fichier_docx(), type_document="CCTP")
        self.assertEqual(sans_lot.status_code, 400)
        rc_avec_lot = self.televerser(fichier_docx("RC.docx"), type_document="RC", lot_id=self.lot.pk)
        self.assertEqual(rc_avec_lot.status_code, 400)

    def test_format_refuse(self):
        reponse = self.televerser(SimpleUploadedFile("plan.dwg", b"x"), type_document="AE")
        self.assertEqual(reponse.status_code, 400)

    def test_format_conserve_sans_analyse(self):
        reponse = self.televerser(SimpleUploadedFile("ancien.doc", b"binaire"), type_document="AE")
        self.assertEqual(reponse.status_code, 201)
        self.assertEqual(DocumentReference.objects.get().statut_analyse, StatutAnalyse.NON_PRIS_EN_CHARGE)

    def test_liste_filtre_statistiques_telechargement_suppression(self):
        self.televerser(fichier_docx(), type_document="CCTP", lot_id=self.lot.pk, operation="Collège Pasteur")
        self.televerser(fichier_xlsx(), type_document="DPGF", lot_id=self.lot.pk)

        liste = self.client.get("/api/bibliotheque/documents", {"type_document": "CCTP"}).json()
        self.assertEqual([d["nom_original"] for d in liste], ["CCTP lot 08.docx"])
        recherche = self.client.get("/api/bibliotheque/documents", {"recherche": "pasteur"}).json()
        self.assertEqual(len(recherche), 1)

        stats = self.client.get("/api/bibliotheque/statistiques").json()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["par_type"]["CCTP"], 1)
        self.assertEqual(stats["par_lot"]["DPGF"][str(self.lot.pk)], 1)

        document = DocumentReference.objects.get(type_document="CCTP")
        telechargement = self.client.get(f"/api/bibliotheque/documents/{document.pk}/telecharger")
        self.assertEqual(telechargement.status_code, 200)
        self.assertIn("CCTP lot 08.docx", telechargement["Content-Disposition"])
        telechargement.close()

        stockage, nom = document.fichier.storage, document.fichier.name
        with self.captureOnCommitCallbacks(execute=True):
            reponse = self.client.delete(f"/api/bibliotheque/documents/{document.pk}")
        self.assertEqual(reponse.status_code, 204)
        self.assertFalse(stockage.exists(nom))


class SecuriteApiTests(TestCase):
    def test_acces_refuse_sans_connexion(self):
        self.assertEqual(self.client.get("/api/bibliotheque/documents").status_code, 401)

    def test_compte_entreprise_refuse(self):
        entreprise = Utilisateur.objects.create_user(
            "entreprise", password="mot-de-passe-solide-42", role=Utilisateur.Role.ENTREPRISE
        )
        self.client.force_login(entreprise)
        self.assertEqual(self.client.get("/api/bibliotheque/documents").status_code, 401)

    def test_csrf_exige_pour_les_modifications(self):
        utilisateur = Utilisateur.objects.create_user(
            "moe", password="mot-de-passe-solide-42", role=Utilisateur.Role.MOE
        )
        client = self.client_class(enforce_csrf_checks=True)
        client.force_login(utilisateur)
        reponse = client.post(
            "/api/bibliotheque/documents",
            {"fichier": SimpleUploadedFile("a.pdf", b"x"), "type_document": "AE"},
        )
        self.assertEqual(reponse.status_code, 403)
