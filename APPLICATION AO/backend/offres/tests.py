import io
import json
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from openpyxl import Workbook, load_workbook

from comptes.models import Utilisateur
from dce.models import ConsultationEntreprise, StatutConsultation
from entreprises.models import Entreprise
from projets.exports.dpgf_xlsx import exporter_dpgf_xlsx
from projets.models import GenreOption, GenrePoste, LotProjet, OptionLot, Poste, Projet
from projets.structure import structurer
from referentiel.models import Lot

from .models import AnalyseLot, Offre, StatutLecture

DOSSIER_TEST = tempfile.mkdtemp(prefix="application-ao-offres-")
FENETRE, PORTE, VOLETS = "Fenêtre aluminium 120 x 135", "Porte-fenêtre aluminium 215 x 90", "Volets roulants électriques"


@override_settings(MEDIA_ROOT=DOSSIER_TEST)
class OffresTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_TEST, ignore_errors=True)

    def setUp(self):
        self.client.force_login(Utilisateur.objects.create_user("eco", password="mot-de-passe-solide-42", role=Utilisateur.Role.MOE))
        self.projet = Projet.objects.create(nom="Groupe scolaire les Tilleuls", maitre_ouvrage="Ville de Saint-Aubin", type_marche="PUBLIC")
        self.lot = LotProjet.objects.create(projet=self.projet, lot=Lot.objects.get(code="08"), code="08", intitule="Menuiseries extérieures", ordre=1)
        self.pse = OptionLot.objects.create(lot=self.lot, genre=GenreOption.PSE, numero=1, libelle="Volets roulants")
        Poste.objects.create(lot=self.lot, ordre=10, genre=GenrePoste.CHAPITRE, titre="Menuiseries")
        Poste.objects.create(lot=self.lot, ordre=20, titre=FENETRE, unite="u", quantite=Decimal("10"), prix_unitaire=Decimal("800"))
        Poste.objects.create(lot=self.lot, ordre=30, titre=PORTE, unite="u", quantite=Decimal("4"), prix_unitaire=Decimal("1200"))
        Poste.objects.create(lot=self.lot, ordre=40, titre=VOLETS, unite="u", quantite=Decimal("14"), prix_unitaire=Decimal("450"), option=self.pse)
        self.durand = Entreprise.objects.create(raison_sociale="Menuiseries Durand")
        self.martin = Entreprise.objects.create(raison_sociale="Alu Martin")
        self.petit = Entreprise.objects.create(raison_sociale="Petit Fermetures")
        ConsultationEntreprise.objects.create(projet=self.projet, lot=self.lot, entreprise=self.durand, statut=StatutConsultation.CONSULTEE)

    # --- utilitaires -----------------------------------------------------------
    def json(self, methode, url, donnees=None, attendu=200):
        if methode == "get":
            reponse = self.client.get(url, donnees or {})
        else:
            with self.captureOnCommitCallbacks(execute=True):
                reponse = getattr(self.client, methode)(url, json.dumps(donnees or {}), content_type="application/json")
        self.assertEqual(reponse.status_code, attendu, reponse.content)
        return reponse.json() if reponse.content else None

    def deposer(self, entreprise, nom=None, contenu=None, attendu=201, **champs):
        donnees = {"entreprise_id": entreprise.pk, **champs}
        if contenu is not None:
            donnees["fichier"] = SimpleUploadedFile(nom, contenu)
        with self.captureOnCommitCallbacks(execute=True):  # lecture en tâche de fond (exécutée immédiatement en test)
            reponse = self.client.post(f"/api/lots-projet/{self.lot.pk}/offres", donnees)
        self.assertEqual(reponse.status_code, attendu, reponse.content)
        return reponse.json()

    def dpgf_remplie(self, prix: dict[str, float], total_base: float | None = None) -> bytes:
        """DPGF vierge du DCE complétée comme le ferait l'entreprise (Excel enregistre la valeur des formules)."""
        classeur = load_workbook(io.BytesIO(exporter_dpgf_xlsx(structurer(self.lot))))
        feuille = classeur["DPGF"]
        cumul = Decimal("0")
        for rangee in range(5, feuille.max_row + 1):
            titre = feuille.cell(rangee, 2).value
            if titre in prix:
                feuille.cell(rangee, 5, prix[titre])
                montant = round(Decimal(str(feuille.cell(rangee, 4).value)) * Decimal(str(prix[titre])), 2)
                feuille.cell(rangee, 6, float(montant))
                cumul += montant
            elif isinstance(titre, str) and titre.startswith("Sous-total"):
                feuille.cell(rangee, 6, float(cumul))
            elif isinstance(titre, str) and titre.startswith("TOTAL "):
                valeur = total_base if titre.startswith("TOTAL SOLUTION DE BASE") and total_base is not None else cumul
                feuille.cell(rangee, 6, float(valeur))
                cumul = Decimal("0")
        flux = io.BytesIO()
        classeur.save(flux)
        return flux.getvalue()

    def devis(self, lignes) -> bytes:
        classeur = Workbook()
        feuille = classeur.active
        feuille.append(["DEVIS n° 2026-118"])
        feuille.append(["Désignation", "Unité", "Quantité", "Prix unitaire HT", "Total HT"])
        for ligne in lignes:
            feuille.append(list(ligne))
        flux = io.BytesIO()
        classeur.save(flux)
        return flux.getvalue()

    def etat(self):
        return self.json("get", f"/api/lots-projet/{self.lot.pk}/offres")

    def par_entreprise(self, etat):
        return {o["nom"]: o for o in etat["offres"]}

    # --- lecture des offres ----------------------------------------------------
    def test_lecture_dpgf_remplie(self):
        cree = self.deposer(self.durand, "DPGF lot 08 Durand.xlsx", self.dpgf_remplie({FENETRE: 700, PORTE: 1100, VOLETS: 400}))
        self.assertEqual(cree["statut_lecture"], "EN_COURS")
        offre = Offre.objects.get(pk=cree["id"])
        self.assertEqual(offre.statut_lecture, StatutLecture.LUE, offre.message_lecture)
        self.assertEqual(offre.montant_base, Decimal("11400.00"))
        self.assertEqual(offre.montant_base_declare, Decimal("11400.00"))
        self.assertEqual(Decimal(offre.montants_options[str(self.pse.pk)]), Decimal("5600.00"))
        lignes = list(offre.lignes.filter(poste__isnull=False))
        self.assertEqual(len(lignes), 3)
        self.assertEqual({l.correspondance for l in lignes}, {"NUMERO"})
        self.assertEqual(offre.lignes.get(poste__titre=VOLETS).option_id, self.pse.pk)
        consultation = ConsultationEntreprise.objects.get(lot=self.lot, entreprise=self.durand)
        self.assertEqual(consultation.statut, StatutConsultation.REPONDU)

        # Une seule offre de base par entreprise, mais une variante est possible.
        erreur = self.deposer(self.durand, "DPGF bis.xlsx", self.dpgf_remplie({FENETRE: 1}), attendu=409)
        self.assertIn("déjà enregistrée", erreur["detail"])
        variante = self.deposer(self.durand, montant_base="10 900,50", variante=True, libelle_variante="profilés acier")
        self.assertEqual(variante["nom"], "Menuiseries Durand – variante (profilés acier)")
        self.assertEqual(variante["montant_base"], 10900.5)
        self.assertEqual(variante["statut_lecture"], "MANUELLE")
        self.deposer(self.martin, "offre.exe", b"MZ", attendu=400)

        # Document consultable et relecture à la demande.
        self.assertEqual(self.client.get(f"/api/offres/{offre.pk}/fichier").status_code, 200)
        self.json("post", f"/api/offres/{offre.pk}/relire", attendu=202)
        self.assertEqual(Offre.objects.get(pk=offre.pk).statut_lecture, StatutLecture.LUE)
        self.json("post", f"/api/offres/{variante['id']}/relire", attendu=400)

    def test_erreur_de_calcul_et_devis_sans_numeros(self):
        # Total déclaré faux : le montant déclaré est retenu (engagement de l'entreprise) mais signalé.
        self.deposer(self.durand, "dpgf.xlsx", self.dpgf_remplie({FENETRE: 700, PORTE: 1100, VOLETS: 400}, total_base=11000))
        offre = Offre.objects.get(entreprise=self.durand)
        self.assertEqual(offre.statut_lecture, StatutLecture.A_VERIFIER)
        self.assertEqual((offre.montant_base, offre.montant_base_calcule), (Decimal("11000.00"), Decimal("11400.00")))
        self.assertIn("erreur de calcul", offre.message_lecture)

        # Devis de l'entreprise : rapprochement par la désignation, ligne ajoutée comptée dans la base.
        self.deposer(self.martin, "devis.xlsx", self.devis([
            ("Fenetres aluminium 120x135", "u", 10, 750, 7500),
            ("Volets roulants électriques motorisés", "u", 14, 420, 5880),
            ("Nettoyage de fin de chantier", "ens", 1, 300, 300),
        ]))
        offre = Offre.objects.get(entreprise=self.martin)
        self.assertEqual(offre.statut_lecture, StatutLecture.A_VERIFIER)
        self.assertEqual(offre.lignes.get(designation__startswith="Fenetres").correspondance, "DESIGNATION")
        self.assertEqual(offre.montant_base, Decimal("7800.00"))
        self.assertEqual(Decimal(offre.montants_options[str(self.pse.pk)]), Decimal("5880.00"))
        self.assertIn("1 ouvrage(s) de la DPGF non chiffré(s)", offre.message_lecture)
        self.assertIn("1 ligne(s) ajoutée(s)", offre.message_lecture)

        comparatif = self.json("get", f"/api/lots-projet/{self.lot.pk}/comparatif")
        base, pse = comparatif["sections"]
        fenetre = base["chapitres"][0]["lignes"][0]
        self.assertEqual((fenetre["minimum"], fenetre["maximum"], fenetre["estimation"]), (7000.0, 7500.0, 8000.0))
        self.assertIsNone(base["chapitres"][0]["lignes"][1]["offres"][str(offre.pk)])  # porte-fenêtre non chiffrée
        self.assertEqual(pse["option_id"], self.pse.pk)
        self.assertEqual(comparatif["hors_dpgf"][str(offre.pk)][0]["montant"], 300.0)

    def test_document_illisible(self):
        self.deposer(self.durand, "offre.pdf", b"%PDF-1.4 abime")
        offre = Offre.objects.get()
        self.assertEqual(offre.statut_lecture, StatutLecture.NON_LUE)
        self.assertIn("saisissez le montant", offre.message_lecture.lower())
        etat = self.json("patch", f"/api/offres/{offre.pk}", {"montant_base": "9800.00"})
        self.assertEqual(etat["offres"][0]["montant_base"], 9800.0)

    # --- notation et classement -------------------------------------------------
    def test_notation_classement_et_attribution(self):
        self.deposer(self.durand, "dpgf.xlsx", self.dpgf_remplie({FENETRE: 700, PORTE: 1100, VOLETS: 400}))
        self.deposer(self.martin, montant_base="12500")
        self.deposer(self.petit, montant_base="7000")
        ids = {o.entreprise.raison_sociale: o.pk for o in Offre.objects.select_related("entreprise")}

        etat = self.etat()
        self.assertEqual([c["libelle"] for c in etat["criteres"] if c["prix"]], ["Prix"])
        self.assertEqual(etat["estimation_base"], 12800.0)
        offres = self.par_entreprise(etat)
        self.assertEqual(offres["Menuiseries Durand"]["notes_calculees"]["Prix"], 6.14)
        self.assertEqual(offres["Petit Fermetures"]["notes_calculees"]["Prix"], 10.0)
        self.assertTrue(offres["Petit Fermetures"]["anormalement_basse"])
        self.assertFalse(offres["Menuiseries Durand"]["anormalement_basse"])
        self.assertEqual(offres["Alu Martin"]["ecart_estimation"], -2.3)
        self.assertFalse(offres["Alu Martin"]["notation_complete"])

        technique = {"Menuiseries Durand": (8, 7), "Alu Martin": (9, 6), "Petit Fermetures": (4, 5)}
        for nom, (valeur, environnement) in technique.items():
            self.json("patch", f"/api/offres/{ids[nom]}", {"notes": {
                "Valeur technique": {"note": valeur, "commentaire": "Mémoire technique détaillé"},
                "Performance en matière de protection de l'environnement": {"note": environnement},
            }})
        self.json("patch", f"/api/offres/{ids['Alu Martin']}", {"notes": {"Valeur technique": {"note": 12}}}, attendu=400)
        offres = self.par_entreprise(self.etat())
        self.assertEqual(
            [(n, offres[n]["total"], offres[n]["rang"]) for n in ("Alu Martin", "Menuiseries Durand", "Petit Fermetures")],
            [("Alu Martin", 73.4, 1), ("Menuiseries Durand", 71.56, 2), ("Petit Fermetures", 65.0, 3)],
        )
        self.assertTrue(offres["Alu Martin"]["notation_complete"])

        # PSE retenue : prix comparé = base + PSE ; les offres sans prix de PSE sont signalées.
        etat = self.json("patch", f"/api/lots-projet/{self.lot.pk}/analyse", {"options_retenues": [self.pse.pk], "methode_prix": "LINEAIRE"})
        offres = self.par_entreprise(etat)
        self.assertEqual(offres["Menuiseries Durand"]["prix"], 17000.0)
        self.assertTrue(offres["Alu Martin"]["incomplete"])
        self.json("patch", f"/api/offres/{ids['Alu Martin']}", {"montants_options": {str(self.pse.pk): "6000"}})
        self.json("patch", f"/api/offres/{ids['Petit Fermetures']}", {"montants_options": {str(self.pse.pk): "5000"}})
        self.json("patch", f"/api/offres/{ids['Petit Fermetures']}", {"montants_options": {"999999": "1"}}, attendu=400)
        offres = self.par_entreprise(self.etat())
        self.assertFalse(offres["Alu Martin"]["incomplete"])
        # Linéaire : 10 × (1 − (17 000 − 12 000) / 12 000) = 5,83
        self.assertEqual(offres["Menuiseries Durand"]["notes_calculees"]["Prix"], 5.83)
        self.json("patch", f"/api/lots-projet/{self.lot.pk}/analyse", {"bareme": 0}, attendu=422)

        # Offre écartée : ni notée ni classée.
        etat = self.json("patch", f"/api/offres/{ids['Petit Fermetures']}", {"ecartee": True, "motif_ecart": "Offre irrégulière : DPGF non signée"})
        offres = self.par_entreprise(etat)
        self.assertIsNone(offres["Petit Fermetures"]["rang"])
        self.assertEqual(offres["Alu Martin"]["rang"], 1)

        # Validation de la proposition : statuts de l'annuaire mis à jour.
        etat = self.json("post", f"/api/lots-projet/{self.lot.pk}/analyse/valider")
        self.assertEqual(etat["analyse"]["attributaire_id"], ids["Alu Martin"])
        self.assertIsNotNone(etat["analyse"]["validee_le"])
        statuts = dict(ConsultationEntreprise.objects.filter(lot=self.lot).values_list("entreprise__raison_sociale", "statut"))
        self.assertEqual(statuts, {
            "Alu Martin": StatutConsultation.RETENUE, "Menuiseries Durand": StatutConsultation.NON_RETENUE,
            "Petit Fermetures": StatutConsultation.NON_RETENUE,
        })

        # L'économiste peut proposer une autre offre que la mieux classée.
        etat = self.json("patch", f"/api/lots-projet/{self.lot.pk}/analyse", {"attributaire_id": ids["Menuiseries Durand"], "observations": "Délai plus court."})
        self.assertEqual(etat["analyse"]["attributaire_id"], ids["Menuiseries Durand"])

        # Suppression d'une offre : l'entreprise redevient « consultée ».
        autre = self.deposer(self.durand, montant_base="1", variante=True)
        self.json("delete", f"/api/offres/{autre['id']}", attendu=204)
        self.json("delete", f"/api/offres/{ids['Petit Fermetures']}", attendu=204)
        self.assertEqual(ConsultationEntreprise.objects.get(entreprise=self.petit).statut, StatutConsultation.CONSULTEE)

    # --- rapport ACT et exports ---------------------------------------------------
    def test_rapport_act_et_comparatif_excel(self):
        from docx import Document

        self.deposer(self.durand, "dpgf.xlsx", self.dpgf_remplie({FENETRE: 700, PORTE: 1100, VOLETS: 400}))
        self.deposer(self.martin, montant_base="12500")
        self.json("patch", f"/api/lots-projet/{self.lot.pk}/analyse", {"options_retenues": [self.pse.pk]})
        lot11 = LotProjet.objects.create(projet=self.projet, lot=Lot.objects.get(code="11"), code="11", intitule="Plâtrerie", ordre=2)

        reponse = self.client.get(f"/api/projets/{self.projet.pk}/rapport-act/docx")
        self.assertEqual(reponse.status_code, 200)
        document = Document(io.BytesIO(reponse.content))
        texte = "\n".join(p.text for p in document.paragraphs)
        cellules = "\n".join(c.text for t in document.tables for r in t.rows for c in r.cells)
        self.assertIn("Proposition d'attribution", texte)
        self.assertIn("Aucune offre n'a été reçue pour ce lot.", texte)
        self.assertIn("Récapitulatif", texte)
        self.assertIn("Menuiseries Durand", cellules)
        self.assertIn("Valeur technique", cellules)

        reponse = self.client.get(f"/api/projets/{self.projet.pk}/rapport-act/pdf", {"lot_id": self.lot.pk})
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.content.startswith(b"%PDF"))
        self.assertEqual(self.client.get(f"/api/projets/{self.projet.pk}/rapport-act/odt").status_code, 422)

        reponse = self.client.get(f"/api/projets/{self.projet.pk}/comparatif-offres.xlsx")
        self.assertEqual(reponse.status_code, 200)
        classeur = load_workbook(io.BytesIO(reponse.content))
        self.assertEqual(classeur.sheetnames, ["Lot 08", "Lot 11"])
        valeurs = [c for ligne in classeur["Lot 08"].iter_rows(values_only=True) for c in ligne if c is not None]
        self.assertIn("Menuiseries Durand", valeurs)
        self.assertIn(17000.0, valeurs)  # base + PSE retenue
        self.assertEqual(self.client.get(f"/api/projets/{self.projet.pk}/comparatif-offres.xlsx", {"lot_id": lot11.pk}).status_code, 200)

        etat = self.json("get", f"/api/projets/{self.projet.pk}/offres")
        self.assertEqual([l["code"] for l in etat["lots"]], ["08", "11"])
        self.assertEqual(etat["lots"][1]["offres"], [])
        self.assertTrue(AnalyseLot.objects.filter(lot=self.lot).exists())

    def test_fichier_supprime_avec_offre(self):
        from django.db.models import ProtectedError

        cree = self.deposer(self.durand, "dpgf.xlsx", self.dpgf_remplie({FENETRE: 700}))
        chemin = Path(Offre.objects.get(pk=cree["id"]).fichier.path)
        self.assertTrue(chemin.exists())
        with self.assertRaises(ProtectedError):  # l'annuaire garde les entreprises ayant remis une offre
            self.durand.delete()
        self.json("delete", f"/api/offres/{cree['id']}", attendu=204)
        self.assertFalse(chemin.exists())
