import datetime
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
        self.assertIsNone(offres["Alu Martin"]["rang"])  # PSE retenue non chiffrée : offre non comparable
        self.assertEqual(offres["Menuiseries Durand"]["rang"], 1)
        self.json("patch", f"/api/offres/{ids['Alu Martin']}", {"montants_options": {str(self.pse.pk): "6000"}})
        self.json("patch", f"/api/offres/{ids['Petit Fermetures']}", {"montants_options": {str(self.pse.pk): "5000"}})
        self.json("patch", f"/api/offres/{ids['Petit Fermetures']}", {"montants_options": {"999999": "1"}}, attendu=400)
        offres = self.par_entreprise(self.etat())
        self.assertFalse(offres["Alu Martin"]["incomplete"])
        # Linéaire : 10 × (1 − (17 000 − 12 000) / 12 000) = 5,83
        self.assertEqual(offres["Menuiseries Durand"]["notes_calculees"]["Prix"], 5.83)
        self.json("patch", f"/api/lots-projet/{self.lot.pk}/analyse", {"bareme": 0}, attendu=422)
        etat = self.json("patch", f"/api/lots-projet/{self.lot.pk}/analyse", {"bareme": 20})
        offres = self.par_entreprise(etat)
        self.assertEqual(offres["Alu Martin"]["notes"]["Valeur technique"]["note"], 18)  # 9/10 → 18/20
        self.assertEqual(offres["Alu Martin"]["notes"]["Valeur technique"]["commentaire"], "Mémoire technique détaillé")
        self.assertEqual(offres["Menuiseries Durand"]["notes_calculees"]["Prix"], 11.67)
        total_sur_20 = offres["Alu Martin"]["total"]
        self.json("patch", f"/api/lots-projet/{self.lot.pk}/analyse", {"bareme": 10})
        self.assertAlmostEqual(self.par_entreprise(self.etat())["Alu Martin"]["total"], total_sur_20, delta=0.05)  # arrondi de la note de prix

        # Offre écartée : ni notée ni classée.
        etat = self.json("patch", f"/api/offres/{ids['Petit Fermetures']}", {"ecartee": True, "motif_ecart": "Offre irrégulière : DPGF non signée"})
        offres = self.par_entreprise(etat)
        self.assertIsNone(offres["Petit Fermetures"]["rang"])
        self.assertEqual(offres["Alu Martin"]["rang"], 1)

        # Validation de la proposition : statuts de l'annuaire mis à jour.
        etat = self.json("post", f"/api/lots-projet/{self.lot.pk}/analyse/valider")
        self.assertEqual((etat["analyse"]["proposee_id"], etat["analyse"]["attributaire_id"]), (ids["Alu Martin"], None))
        self.assertIsNotNone(etat["analyse"]["validee_le"])
        statuts = lambda: dict(ConsultationEntreprise.objects.filter(lot=self.lot).values_list("entreprise__raison_sociale", "statut"))  # noqa: E731
        self.assertEqual(statuts(), {
            "Alu Martin": StatutConsultation.RETENUE, "Menuiseries Durand": StatutConsultation.NON_RETENUE,
            "Petit Fermetures": StatutConsultation.NON_RETENUE,
        })

        # L'économiste peut proposer une autre offre classée : la validation est à refaire.
        etat = self.json("patch", f"/api/lots-projet/{self.lot.pk}/analyse", {"attributaire_id": ids["Menuiseries Durand"], "observations": "Délai plus court."})
        self.assertEqual((etat["analyse"]["attributaire_id"], etat["analyse"]["proposee_id"]), (ids["Menuiseries Durand"],) * 2)
        self.assertIsNone(etat["analyse"]["validee_le"])
        self.assertEqual(set(statuts().values()), {StatutConsultation.REPONDU})
        erreur = self.json("patch", f"/api/lots-projet/{self.lot.pk}/analyse", {"attributaire_id": ids["Petit Fermetures"]}, attendu=400)
        self.assertIn("n'est pas classée (écartée", erreur["detail"])
        self.json("post", f"/api/lots-projet/{self.lot.pk}/analyse/valider")
        self.assertEqual(statuts()["Menuiseries Durand"], StatutConsultation.RETENUE)
        # Une note corrigée change le classement : validation à refaire.
        etat = self.json("patch", f"/api/offres/{ids['Alu Martin']}", {"notes": {"Valeur technique": {"note": 10}}})
        self.assertIsNone(etat["analyse"]["validee_le"])
        # L'offre choisie est écartée : le choix tombe, la mieux classée est proposée.
        etat = self.json("patch", f"/api/offres/{ids['Menuiseries Durand']}", {"ecartee": True, "motif_ecart": "Attestation manquante"})
        self.assertEqual((etat["analyse"]["attributaire_id"], etat["analyse"]["proposee_id"]), (None, ids["Alu Martin"]))
        self.json("patch", f"/api/offres/{ids['Menuiseries Durand']}", {"ecartee": False})

        # Suppression d'une offre : l'entreprise redevient « consultée ».
        autre = self.deposer(self.durand, montant_base="1", variante=True)
        self.json("delete", f"/api/offres/{autre['id']}", attendu=204)
        self.json("delete", f"/api/offres/{ids['Petit Fermetures']}", attendu=204)
        self.assertEqual(ConsultationEntreprise.objects.get(entreprise=self.petit).statut, StatutConsultation.CONSULTEE)

    def test_offre_anormalement_basse_variante_et_date_de_reception(self):
        from projets.champs import consultation_du_projet

        consultation = consultation_du_projet(self.projet)
        consultation.date_limite_offres = datetime.datetime(2026, 10, 15, 12, tzinfo=datetime.timezone.utc)
        consultation.save()
        durand = self.deposer(self.durand, montant_base="12000", recue_le="2026-10-14")
        martin = self.deposer(self.martin, montant_base="12600", recue_le="2026-10-16")
        petit = self.deposer(self.petit, montant_base="7000")
        variante = self.deposer(self.durand, montant_base="6500", variante=True, libelle_variante="PVC")
        for offre in (durand, martin, petit, variante):
            self.json("patch", f"/api/offres/{offre['id']}", {"notes": {"Valeur technique": {"note": 8}, "Performance en matière de protection de l'environnement": {"note": 8}}})
        offres = self.par_entreprise(self.etat())
        self.assertEqual((offres["Menuiseries Durand"]["hors_delai"], offres["Alu Martin"]["hors_delai"]), (False, True))
        # Variantes non autorisées par le RC : ni notée ni classée.
        self.assertEqual(offres["Menuiseries Durand – variante (PVC)"]["motif_non_classee"], "variante non autorisée par le règlement de la consultation")
        self.assertIsNone(offres["Menuiseries Durand – variante (PVC)"]["rang"])
        # Offre anormalement basse classée 1re : pas de validation sans examen de ses justifications.
        self.assertEqual(offres["Petit Fermetures"]["rang"], 1)
        self.assertTrue(offres["Petit Fermetures"]["anormalement_basse"])
        erreur = self.json("post", f"/api/lots-projet/{self.lot.pk}/analyse/valider", attendu=400)
        self.assertIn("R2152-3", erreur["detail"])
        self.json("patch", f"/api/offres/{petit['id']}", {"justification_prix": "DEMANDEE"})
        self.json("post", f"/api/lots-projet/{self.lot.pk}/analyse/valider", attendu=400)
        self.json("patch", f"/api/offres/{petit['id']}", {"justification_prix": "ACCEPTEE", "motif_justification": "Matériel en stock, sous-détail cohérent."})
        self.json("post", f"/api/lots-projet/{self.lot.pk}/analyse/valider")
        texte = self.texte_rapport()
        self.assertIn("justifications apportées par l'entreprise ont été jugées satisfaisantes : Matériel en stock", texte)
        self.assertIn("Reçue après la date limite", texte)
        # Justifications rejetées : l'offre est écartée.
        etat = self.json("patch", f"/api/offres/{petit['id']}", {"justification_prix": "REJETEE"})
        offres = self.par_entreprise(etat)
        self.assertTrue(offres["Petit Fermetures"]["ecartee"])
        self.assertIn("justifications de prix insuffisantes", offres["Petit Fermetures"]["motif_ecart"])
        self.assertEqual(offres["Menuiseries Durand"]["rang"], 1)
        # Variantes autorisées : la variante est classée.
        consultation.variantes_autorisees = True
        consultation.save()
        self.assertIsNotNone(self.par_entreprise(self.etat())["Menuiseries Durand – variante (PVC)"]["rang"])

    def test_saisie_manuelle_apres_lecture(self):
        self.deposer(self.durand, "dpgf.xlsx", self.dpgf_remplie({FENETRE: 700, PORTE: 1100, VOLETS: 400}, total_base=11000))
        offre = Offre.objects.get()
        self.assertEqual(offre.statut_lecture, StatutLecture.A_VERIFIER)
        etat = self.json("patch", f"/api/offres/{offre.pk}", {"montant_base": "11400.00"})
        self.assertEqual(etat["offres"][0]["statut_lecture"], "MANUELLE")
        self.assertEqual(etat["offres"][0]["message_lecture"], "Montant saisi à la main (montant lu dans le document : 11 000,00 €).")
        self.assertNotIn("erreur de calcul", self.texte_rapport())

    def test_recapitulatif_et_arrondis_du_rapport(self):
        from .rapport import _euros

        self.assertEqual((_euros(Decimal("1100.165")), _euros("3.165")), ("1 100,17 €", "3,17 €"))
        lot11 = LotProjet.objects.create(projet=self.projet, lot=Lot.objects.get(code="11"), code="11", intitule="Plâtrerie", ordre=2)
        self.deposer(self.durand, montant_base="11400")
        reponse = self.client.post(f"/api/lots-projet/{lot11.pk}/offres", {"entreprise_id": self.martin.pk, "montant_base": "50000"})
        self.assertEqual(reponse.status_code, 201)
        texte = self.texte_rapport()
        self.assertIn("Total des lots attribués : 61 400,00 € HT, soit 73 680,00 € TTC, pour une estimation de 12 800,00 € HT (estimation non établie pour certains lots).", texte)
        self.assertIn("Estimation du maître d'œuvre : non établie", texte)

    def texte_rapport(self):
        from docx import Document

        document = Document(io.BytesIO(self.client.get(f"/api/projets/{self.projet.pk}/rapport-act/docx").content))
        return "\n".join([p.text for p in document.paragraphs] + [c.text for t in document.tables for r in t.rows for c in r.cells])

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
        self.assertIn("(TVA 20 %)", texte)

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
        lot11.code = "11/12"
        lot11.save()
        LotProjet.objects.create(projet=self.projet, lot=Lot.objects.get(code="12"), code="11:12", intitule="Peinture", ordre=3)
        classeur = load_workbook(io.BytesIO(self.client.get(f"/api/projets/{self.projet.pk}/comparatif-offres.xlsx").content))
        self.assertEqual(classeur.sheetnames, ["Lot 08", "Lot 11-12", "Lot 11-12 (2)"])

        etat = self.json("get", f"/api/projets/{self.projet.pk}/offres")
        self.assertEqual([l["code"] for l in etat["lots"]], ["08", "11/12", "11:12"])
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


ENTETE = ["N°", "Désignation", "U", "Qté", "PU HT", "Montant HT"]


@override_settings(MEDIA_ROOT=DOSSIER_TEST)
class LectureOffresTests(TestCase):
    """Scénarios de lecture relevés en revue : forfaits, remises, totaux TTC, autres lots, numéros décalés…"""

    def setUp(self):
        self.projet = Projet.objects.create(nom="Collège", type_marche="PUBLIC")
        self.lot = LotProjet.objects.create(projet=self.projet, lot=Lot.objects.get(code="08"), code="08", intitule="Menuiseries extérieures", ordre=1)
        self.pse = OptionLot.objects.create(lot=self.lot, genre=GenreOption.PSE, numero=1, libelle="Volets roulants")
        Poste.objects.create(lot=self.lot, ordre=10, genre=GenrePoste.CHAPITRE, titre="Menuiseries")
        self.fenetre = Poste.objects.create(lot=self.lot, ordre=20, titre=FENETRE, unite="u", quantite=Decimal("10"), prix_unitaire=Decimal("800"))
        self.porte = Poste.objects.create(lot=self.lot, ordre=30, titre=PORTE, unite="u", quantite=Decimal("4"), prix_unitaire=Decimal("1200"))
        self.volets = Poste.objects.create(lot=self.lot, ordre=40, titre=VOLETS, unite="u", quantite=Decimal("14"), prix_unitaire=Decimal("450"), option=self.pse)

    def lire(self, *feuilles):
        from .lecture import lire_offre

        classeur = Workbook()
        classeur.remove(classeur.active)
        for titre, lignes in feuilles:
            feuille = classeur.create_sheet(titre)
            feuille.append(ENTETE)
            for ligne in lignes:
                feuille.append(list(ligne))
        with tempfile.NamedTemporaryFile(suffix=".xlsx", dir=DOSSIER_TEST, delete=False) as fichier:
            classeur.save(fichier.name)
        return lire_offre(Path(fichier.name), self.lot)

    def dpgf(self, *supplements, base=11400, pse=5600, fenetre=("8.1.1", FENETRE, "u", 10, 700, 7000)):
        return [
            ("8.1", "Menuiseries"), fenetre, ("8.1.2", PORTE, "u", 4, 1100, 4400),
            (None, "TOTAL SOLUTION DE BASE HT", None, None, None, base),
            (None, "PSE N°1 – VOLETS ROULANTS"), ("8.1", "Menuiseries"), ("8.1.3", VOLETS, "u", 14, 400, 5600),
            *supplements, (None, "TOTAL PSE N°1 – VOLETS ROULANTS HT", None, None, None, pse),
        ]

    def test_dpgf_conforme(self):
        from .lecture import bilan

        lecture = self.lire(("DPGF", self.dpgf()))
        self.assertEqual(bilan(lecture)[0], "LUE", bilan(lecture)[1])
        self.assertEqual((lecture.base_declare, lecture.options_declares[self.pse.pk]), (Decimal("11400.00"), Decimal("5600.00")))

    def test_forfait_remise_et_total_ht_du_devis(self):
        from .lecture import bilan

        lignes = [
            (None, "Fenêtres aluminium 120x135", "u", 10, 750, 7500), (None, PORTE, "u", 4, 1100, 4400),
            (None, "Volets roulants électriques motorisés", "u", 14, 420, 5880),
            (None, "Installation de chantier", None, None, None, 1500), (None, "Remise commerciale 5 %", None, None, None, -590),
            (None, "Total HT", None, None, None, 18690), (None, "TVA 20 %", None, None, None, 3738), (None, "Total TTC", None, None, None, 22428),
        ]
        lecture = self.lire(("Devis", lignes))
        statut, message, retenu = bilan(lecture)
        self.assertEqual((statut, retenu), ("LUE", Decimal("12810.00")), message)
        self.assertEqual(lecture.options_calcules[self.pse.pk], Decimal("5880.00"))
        self.assertEqual(lecture.lignes_hors_dpgf, 2)
        lignes[5] = (None, "Total HT", None, None, None, 18000)
        statut, message, _ = bilan(self.lire(("Devis", lignes)))
        self.assertEqual(statut, "A_VERIFIER")
        self.assertIn("Total HT déclaré 18 000,00 €", message)

    def test_total_ttc_et_pse_numero_10(self):
        from .lecture import bilan

        pse10 = OptionLot.objects.create(lot=self.lot, genre=GenreOption.PSE, numero=10, libelle="Brise-soleil")
        lignes = self.dpgf()
        lignes[4:4] = [(None, "TVA 20 %", None, None, None, 2280), (None, "TOTAL SOLUTION DE BASE TTC", None, None, None, 13680)]
        lignes += [(None, "TOTAL PSE N°10 – BRISE-SOLEIL HT", None, None, None, 2000)]
        lecture = self.lire(("DPGF", lignes))
        self.assertEqual(lecture.base_declare, Decimal("11400.00"))
        self.assertEqual((lecture.options_declares[self.pse.pk], lecture.options_declares[pse10.pk]), (Decimal("5600.00"), Decimal("2000.00")))
        self.assertEqual(bilan(lecture)[0], "LUE", bilan(lecture)[1])  # ni TTC pris pour le HT, ni total de la PSE 10 pour la PSE 1

    def test_classeur_de_plusieurs_lots(self):
        from .lecture import bilan

        autre = [("9.1", "Plomberie"), ("9.1.1", "Lavabo céramique", "u", 6, 300, 1800), ("9.1.2", "WC suspendu", "u", 4, 1950, 7800),
                 (None, "TOTAL SOLUTION DE BASE HT", None, None, None, 9600)]
        lecture = self.lire(("DPGF lot 08", self.dpgf()), ("DPGF lot 09", autre))
        self.assertEqual(bilan(lecture)[:3:2], ("LUE", Decimal("11400.00")))
        self.assertEqual(lecture.lignes_hors_dpgf, 0)
        lecture = self.lire(("DPGF", self.dpgf()), ("Feuil2", autre))  # sans code de lot dans le titre
        self.assertEqual((lecture.base_declare, lecture.lignes_hors_dpgf), (Decimal("11400.00"), 0))

    def test_numeros_decales_par_un_modificatif(self):
        from .lecture import bilan

        chassis = Poste.objects.create(lot=self.lot, ordre=15, titre="Châssis fixe 60 x 60", unite="u", quantite=Decimal("2"), prix_unitaire=Decimal("300"))
        lecture = self.lire(("DPGF", self.dpgf()))  # DPGF de l'indice précédent : 8.1.1 = fenêtre
        par_poste = {l.poste_id: l for l in lecture.lignes if l.poste_id}
        self.assertEqual(par_poste[self.fenetre.pk].montant, Decimal("7000"))
        self.assertEqual(par_poste[self.volets.pk].option_id, self.pse.pk)
        self.assertNotIn(chassis.pk, par_poste)
        statut, message, _ = bilan(lecture)
        self.assertEqual(statut, "A_VERIFIER")
        self.assertIn("numéro(s) ne correspondant pas", message)
        self.assertEqual(lecture.base_calcule, Decimal("11400.00"))

    def test_rapprochement_par_designation_au_meilleur_couple(self):
        from .lecture import bilan
        from .comparatif import _prix_ouvrage  # noqa: F401

        fenetre_145 = Poste.objects.create(lot=self.lot, ordre=25, titre="Fenêtre aluminium 120 x 145", unite="u", quantite=Decimal("4"), prix_unitaire=Decimal("850"))
        lignes = [
            (None, "Fenêtre aluminium 120 x 135 – bâtiment A", "u", 6, 700, 4200),
            (None, "Fenêtre aluminium 120 x 135 – bâtiment B", "u", 4, 700, 2800),
            (None, "Fenêtre aluminium 120 x 145", "u", 4, 1485, 5940),
            (None, "Porte-fenêtre aluminium 215 x 90", "u", 4, 1100, 4400),
            (None, "Volets roulants électriques", "u", 14, 400, 5600),
        ]
        lecture = self.lire(("Devis", lignes))
        rattachement = {l.designation: l.poste_id for l in lecture.lignes}
        self.assertEqual(rattachement["Fenêtre aluminium 120 x 145"], fenetre_145.pk)
        self.assertEqual(rattachement["Porte-fenêtre aluminium 215 x 90"], self.porte.pk)
        self.assertEqual(rattachement["Fenêtre aluminium 120 x 135 – bâtiment B"], self.fenetre.pk)
        self.assertEqual(bilan(lecture)[0], "LUE", bilan(lecture)[1])

    def test_ligne_ajoutee_dans_une_pse(self):
        from .lecture import bilan

        lecture = self.lire(("DPGF", self.dpgf((None, "Commande centralisée des volets", "ens", 1, 900, 900), pse=6500)))
        self.assertEqual((lecture.base_calcule, lecture.options_calcules[self.pse.pk]), (Decimal("11400.00"), Decimal("6500.00")))
        self.assertEqual(bilan(lecture)[0], "LUE", bilan(lecture)[1])

    def test_erreur_de_multiplication(self):
        from .lecture import bilan

        lecture = self.lire(("DPGF", self.dpgf(base=10400, fenetre=("8.1.1", FENETRE, "u", 10, 700, 6000))))
        statut, message, retenu = bilan(lecture)
        self.assertEqual((statut, retenu), ("A_VERIFIER", Decimal("10400.00")))
        self.assertIn("Qté × PU différent du montant sur 1 ligne(s) (8.1.1)", message)

    def test_totaux_mots_entiers_et_suite_de_tableau_pdf(self):
        from articles.prix import _est_total
        from bibliotheque.lecture import Tableau

        from .lecture import Lecture, _totaux_declares

        self.assertFalse(_est_total("reportage photographique avant travaux"))
        self.assertFalse(_est_total("totalite des menuiseries"))
        self.assertTrue(_est_total("report"))
        self.assertTrue(_est_total("sous total 8 1"))
        page1 = Tableau("", [ENTETE, ["8.1.1", FENETRE, "u", "10", "700,00", "7 000,00"]])
        page2 = Tableau("", [["8.1.2", PORTE, "u", "4", "1 100,00", "4 400,00"], ["", "TOTAL SOLUTION DE BASE HT", "", "", "", "12 500,00"]])
        lecture = Lecture()
        _totaux_declares([page1, page2], self.lot, set(), lecture)
        self.assertEqual(lecture.base_declare, Decimal("12500.00"))

    def test_lecture_concurrente_et_echec_d_enregistrement(self):
        from unittest import mock

        from .tasks import appliquer_lecture

        entreprise = Entreprise.objects.create(raison_sociale="Durand")
        classeur = Workbook()
        classeur.active.append(ENTETE)
        for ligne in self.dpgf():
            classeur.active.append(list(ligne))
        flux = io.BytesIO()
        classeur.save(flux)
        offre = Offre(projet=self.projet, lot=self.lot, entreprise=entreprise, statut_lecture=StatutLecture.EN_COURS)
        offre.fichier.save("dpgf.xlsx", SimpleUploadedFile("dpgf.xlsx", flux.getvalue()))
        chargee = Offre.objects.get(pk=offre.pk)
        # Saisies faites pendant la lecture : conservées.
        Offre.objects.filter(pk=offre.pk).update(commentaire="RAS", delai_propose="4 mois", notes={"Valeur technique": {"note": 8, "commentaire": ""}})
        appliquer_lecture(chargee)
        offre.refresh_from_db()
        self.assertEqual((offre.statut_lecture, offre.commentaire, offre.delai_propose, offre.notes["Valeur technique"]["note"]), ("LUE", "RAS", "4 mois", 8))
        self.assertEqual(offre.montant_base, Decimal("11400.00"))
        # Montant saisi à la main pendant une relecture : conservé.
        Offre.objects.filter(pk=offre.pk).update(statut_lecture=StatutLecture.MANUELLE, montant_base=Decimal("9999"))
        appliquer_lecture(Offre.objects.get(pk=offre.pk))
        offre.refresh_from_db()
        self.assertEqual((offre.statut_lecture, offre.montant_base), ("MANUELLE", Decimal("9999.00")))
        # Erreur pendant l'enregistrement : l'offre ne reste pas « Lecture en cours ».
        Offre.objects.filter(pk=offre.pk).update(statut_lecture=StatutLecture.EN_COURS)
        with mock.patch("offres.tasks.LigneOffre.objects.bulk_create", side_effect=ValueError("NUL")):
            appliquer_lecture(Offre.objects.get(pk=offre.pk))
        offre.refresh_from_db()
        self.assertEqual(offre.statut_lecture, StatutLecture.NON_LUE)
        # Offre supprimée pendant la lecture : pas recréée.
        chargee = Offre.objects.get(pk=offre.pk)
        Offre.objects.filter(pk=offre.pk).delete()
        appliquer_lecture(chargee)
        self.assertFalse(Offre.objects.filter(pk=offre.pk).exists())
