"""Lots proposés : numéros acceptés, ordre, modification réservée à l'administrateur."""
import json

from django.test import SimpleTestCase, TestCase

from comptes.models import Utilisateur

from .codes import cle_tri, code_normalise, verifier_code
from .models import Lot


class CodesTests(SimpleTestCase):
    def test_numeros_acceptes_et_refuses(self):
        for code in ("03", "3a", "3bis", "TCE", "A", "VRD2", "1234567890"):
            self.assertEqual(verifier_code(f"  {code} "), code)
        for code in ("", "   ", "../x", "a/b", "a\\b", "3 a", "10.1", "10-1", "10_1", "02-VRD", "-3", "12345678901", "3:", "Électr", "1²", "①", "٣"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                verifier_code(code)

    def test_comparaison_et_classement(self):
        self.assertEqual(code_normalise("8"), code_normalise("08"))
        self.assertEqual(code_normalise("3A"), code_normalise("3a"))
        self.assertNotEqual(code_normalise("3"), code_normalise("3a"))
        codes = ["10", "3a", "TCE", "02", "1", "10b", "00", "2", "VRD", "3bis"]
        self.assertEqual(sorted(codes, key=cle_tri), ["TCE", "VRD", "00", "1", "02", "2", "3a", "3bis", "10", "10b"])
        # Numéros saisis autrefois dans l'administration : jamais d'erreur à la comparaison.
        self.assertEqual(code_normalise("1²"), "1²")


class CatalogueApiTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create_user("admin", password="mot-de-passe-solide-42", role="ADMIN")
        self.economiste = Utilisateur.objects.create_user("economiste", password="mot-de-passe-solide-42", role="MOE")
        self.client.force_login(self.admin)

    def envoyer(self, methode, url, donnees):
        return getattr(self.client, methode)(url, json.dumps(donnees), content_type="application/json")

    def test_renumeroter_renommer_et_classer(self):
        menuiseries = Lot.objects.get(code="08")
        reponse = self.envoyer("patch", f"/api/referentiel/lots/{menuiseries.pk}", {"code": "8a", "intitule": "  Menuiseries   aluminium "})
        self.assertEqual(reponse.status_code, 200, reponse.content)
        self.assertEqual((reponse.json()["code"], reponse.json()["intitule"]), ("8a", "Menuiseries aluminium"))
        codes = list(Lot.objects.values_list("code", flat=True))
        self.assertEqual(codes.index("8a"), codes.index("07") + 1)  # classé à sa place, entre 07 et 09
        self.assertEqual(codes[0], "TCE")

        reponse = self.envoyer("post", "/api/referentiel/lots", {"code": "20", "intitule": "Photovoltaïque"})
        self.assertEqual(reponse.status_code, 201, reponse.content)
        self.assertEqual(list(Lot.objects.values_list("code", flat=True))[-1], "20")
        self.assertIn({"id": reponse.json()["id"], "code": "20", "intitule": "Photovoltaïque"}, self.client.get("/api/referentiel/lots").json())

        # Ne plus proposer : absent de la liste de création des projets, toujours utilisable ailleurs (bibliothèque,
        # articles, prix, entreprises) et dans le catalogue complet.
        reponse = self.envoyer("patch", f"/api/referentiel/lots/{menuiseries.pk}", {"propose": False})
        self.assertEqual((reponse.status_code, reponse.json()["propose"], reponse.json()["actif"]), (200, False, True))
        self.assertNotIn("8a", [l["code"] for l in self.client.get("/api/referentiel/lots", {"projets": True}).json()])
        self.assertIn("8a", [l["code"] for l in self.client.get("/api/referentiel/lots").json()])
        self.assertIn("8a", [l["code"] for l in self.client.get("/api/referentiel/lots/tous").json()])

    def test_doublons_formats_et_tce_refuses(self):
        tce, platrerie = Lot.objects.get(code="TCE"), Lot.objects.get(code="11")
        cas = [
            ("patch", f"/api/referentiel/lots/{platrerie.pk}", {"code": "3"}, 409, "03"),  # 3 et 03 : même lot
            ("post", "/api/referentiel/lots", {"code": "tce", "intitule": "Autre"}, 409, "TCE"),
            ("patch", f"/api/referentiel/lots/{platrerie.pk}", {"code": "../11"}, 400, "invalide"),
            ("patch", f"/api/referentiel/lots/{platrerie.pk}", {"intitule": "   "}, 400, "intitulé"),
            ("patch", f"/api/referentiel/lots/{tce.pk}", {"code": "MULTI"}, 400, "TCE"),
        ]
        for methode, url, donnees, statut, extrait in cas:
            with self.subTest(donnees=donnees):
                reponse = self.envoyer(methode, url, donnees)
                self.assertEqual(reponse.status_code, statut, reponse.content)
                self.assertIn(extrait, reponse.json()["detail"])
        self.assertEqual(self.envoyer("patch", f"/api/referentiel/lots/{tce.pk}", {"intitule": "Tous corps d'état"}).status_code, 200)
        self.assertEqual(Lot.objects.get(pk=tce.pk).code, "TCE")
        self.assertTrue(next(l for l in self.client.get("/api/referentiel/lots/tous").json() if l["code"] == "TCE")["code_reserve"])

    def test_numero_ancien_non_conforme_garde_et_comptes(self):
        # « 3 bis » saisi autrefois dans l'administration : l'intitulé se modifie sans toucher au numéro.
        ancien = Lot.objects.create(code="3 bis", intitule="Reprises", ordre=35)
        reponse = self.envoyer("patch", f"/api/referentiel/lots/{ancien.pk}", {"code": "3 bis", "intitule": "Reprises en sous-œuvre"})
        self.assertEqual(reponse.status_code, 200, reponse.content)
        self.assertEqual(reponse.json()["code"], "3 bis")
        # Rattachements comptés séparément : entreprises et projets.
        from entreprises.models import Entreprise

        lot08 = Lot.objects.get(code="08")
        for nom in ("A", "B"):
            Entreprise.objects.create(raison_sociale=nom).lots.add(lot08)
        projet = self.envoyer("post", "/api/projets", {"nom": "P", "lots": [lot08.pk, ancien.pk]})
        self.assertEqual(projet.status_code, 201, projet.content)
        fiche = next(l for l in self.client.get("/api/referentiel/lots/tous").json() if l["code"] == "08")
        self.assertEqual((fiche["utilisations"], fiche["projets"]), (2, 1))

    def test_modification_reservee_a_l_administrateur(self):
        self.client.force_login(self.economiste)
        lot = Lot.objects.get(code="08")
        self.assertEqual(self.client.get("/api/referentiel/lots/tous").status_code, 200)
        self.assertEqual(self.envoyer("patch", f"/api/referentiel/lots/{lot.pk}", {"intitule": "X"}).status_code, 403)
        self.assertEqual(self.envoyer("post", "/api/referentiel/lots", {"code": "20", "intitule": "X"}).status_code, 403)
        self.assertEqual(Lot.objects.get(pk=lot.pk).intitule, "Menuiseries extérieures")
