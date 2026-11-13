"""Numéros et intitulés des lots d'un projet : à la création, ensuite, et classement par numéro."""
import json

from django.test import TestCase

from comptes.models import Utilisateur
from referentiel.models import Lot

from .models import LotProjet, Projet


class LotsDuProjetTests(TestCase):
    def setUp(self):
        self.client.force_login(Utilisateur.objects.create_user("economiste", password="mot-de-passe-solide-42", role="MOE"))
        self.lots = {lot.code: lot for lot in Lot.objects.all()}

    def envoyer(self, methode, url, donnees):
        return getattr(self.client, methode)(url, json.dumps(donnees), content_type="application/json")

    def codes(self, projet_id):
        return [(l["code"], l["intitule"]) for l in self.client.get(f"/api/projets/{projet_id}").json()["lots"]]

    def test_creation_avec_numeros_et_intitules_ajustes(self):
        reponse = self.envoyer("post", "/api/projets", {
            "nom": "Groupe scolaire",
            "lots": [self.lots["03"].pk],  # ancien format, toujours accepté
            "lots_choisis": [
                {"lot_id": self.lots["08"].pk, "code": "2", "intitule": "Menuiseries extérieures aluminium"},
                {"lot_id": self.lots["17"].pk, "code": "", "intitule": ""},  # vides : ceux de la liste proposée
                {"code": "20", "intitule": "Photovoltaïque"},  # hors liste
            ],
        })
        self.assertEqual(reponse.status_code, 201, reponse.content)
        projet_id = reponse.json()["id"]
        self.assertEqual(self.codes(projet_id), [
            ("2", "Menuiseries extérieures aluminium"), ("03", "Gros œuvre – Maçonnerie"), ("17", "Électricité – Courants forts et faibles"),
            ("20", "Photovoltaïque"),
        ])
        self.assertIsNone(LotProjet.objects.get(projet_id=projet_id, code="20").lot)
        self.assertEqual(LotProjet.objects.get(projet_id=projet_id, code="2").lot, self.lots["08"])
        self.assertTrue(LotProjet.objects.get(projet_id=projet_id, code="2").postes.exists())  # chapitres par défaut

    def test_creation_refusee_si_deux_lots_ont_le_meme_numero(self):
        reponse = self.envoyer("post", "/api/projets", {
            "nom": "Groupe scolaire",
            "lots_choisis": [{"lot_id": self.lots["08"].pk, "code": "3"}, {"lot_id": self.lots["03"].pk}],
        })
        self.assertEqual(reponse.status_code, 409, reponse.content)
        self.assertIn("Deux lots ont le même numéro (3 et 03)", reponse.json()["detail"])
        for choisi in ({"lot_id": self.lots["08"].pk, "code": "8/9"}, {"code": "20"}, {"intitule": "Sans numéro"}, {"lot_id": 999999}):
            with self.subTest(choisi=choisi):
                reponse = self.envoyer("post", "/api/projets", {"nom": "Groupe scolaire", "lots_choisis": [choisi]})
                self.assertEqual(reponse.status_code, 400, reponse.content)
        self.assertFalse(Projet.objects.exists())

    def test_modifier_numero_et_intitule_puis_reclasser(self):
        projet_id = self.envoyer("post", "/api/projets", {"nom": "Mairie", "lots": [self.lots[c].pk for c in ("02", "03", "08")]}).json()["id"]
        lot = LotProjet.objects.get(projet_id=projet_id, code="08")
        reponse = self.envoyer("patch", f"/api/lots-projet/{lot.pk}", {"code": " 1 ", "intitule": " Menuiseries  bois "})
        self.assertEqual(reponse.status_code, 200, reponse.content)
        self.assertEqual((reponse.json()["code"], reponse.json()["intitule"]), ("1", "Menuiseries bois"))
        self.assertEqual([c for c, _ in self.codes(projet_id)], ["1", "02", "03"])  # classé par numéro
        self.assertEqual(LotProjet.objects.get(pk=lot.pk).lot, self.lots["08"])  # lien avec la liste conservé

        # Le lot ajouté ensuite prend sa place, pas la dernière.
        reponse = self.envoyer("post", f"/api/projets/{projet_id}/lots", {"code": "2b", "intitule": "Clôtures"})
        self.assertEqual(reponse.status_code, 201, reponse.content)
        self.assertEqual([c for c, _ in self.codes(projet_id)], ["1", "02", "2b", "03"])

    def test_modifications_refusees(self):
        projet_id = self.envoyer("post", "/api/projets", {"nom": "Mairie", "lots": [self.lots[c].pk for c in ("02", "03")]}).json()["id"]
        lot = LotProjet.objects.get(projet_id=projet_id, code="03")
        for donnees, statut, extrait in (
            ({"code": "2"}, 409, "02 – Terrassements"),  # 2 et 02 : même numéro dans les pièces
            ({"code": "02"}, 409, "02 – Terrassements"),
            ({"code": "   "}, 400, "numéro"),
            ({"code": "03/04"}, 400, "invalide"),
            ({"intitule": "  "}, 400, "intitulé"),
            ({"intitule": "x" * 256}, 400, "trop long"),
        ):
            with self.subTest(donnees=donnees):
                reponse = self.envoyer("patch", f"/api/lots-projet/{lot.pk}", donnees)
                self.assertEqual(reponse.status_code, statut, reponse.content)
                self.assertIn(extrait, reponse.json()["detail"])
        self.assertEqual(self.envoyer("post", f"/api/projets/{projet_id}/lots", {"code": "3", "intitule": "Doublon"}).status_code, 409)
        self.assertEqual(LotProjet.objects.get(pk=lot.pk).code, "03")
        # Changer seulement l'intitulé, ou garder son propre numéro, reste possible.
        self.assertEqual(self.envoyer("patch", f"/api/lots-projet/{lot.pk}", {"code": "03", "intitule": "Maçonnerie"}).status_code, 200)

    def test_lot_deja_present_et_numeros_anciens(self):
        projet_id = self.envoyer("post", "/api/projets", {"nom": "Mairie", "lots": [self.lots["08"].pk]}).json()["id"]
        lot = LotProjet.objects.get(projet_id=projet_id)
        self.envoyer("patch", f"/api/lots-projet/{lot.pk}", {"code": "1"})
        # Le lot de la liste déjà repris (sous un autre numéro) n'est pas ajouté une seconde fois…
        reponse = self.envoyer("post", f"/api/projets/{projet_id}/lots", {"lot_id": self.lots["08"].pk})
        self.assertEqual(reponse.status_code, 409, reponse.content)
        self.assertIn("déjà dans le projet : lot 1", reponse.json()["detail"])
        self.assertEqual(self.client.get(f"/api/projets/{projet_id}").json()["lots"][0]["lot_id"], self.lots["08"].pk)
        # …et un numéro saisi autrefois sans contrôle (« 3 bis ») reste utilisable : seul l'intitulé change.
        ancien = LotProjet.objects.create(projet_id=projet_id, code="3 bis", intitule="Reprises", ordre=5)
        reponse = self.envoyer("patch", f"/api/lots-projet/{ancien.pk}", {"code": "3 bis", "intitule": "Reprises en sous-œuvre"})
        self.assertEqual(reponse.status_code, 200, reponse.content)
        catalogue = Lot.objects.create(code="4 ter", intitule="Charpente métallique", ordre=45)
        self.assertEqual(self.envoyer("post", f"/api/projets/{projet_id}/lots", {"lot_id": catalogue.pk}).status_code, 201)
        self.assertEqual(self.envoyer("post", "/api/projets", {"nom": "Autre", "lots": [catalogue.pk]}).status_code, 201)

    def test_exports_et_numeros_suivent_le_nouveau_numero(self):
        projet_id = self.envoyer("post", "/api/projets", {"nom": "Mairie", "lots": [self.lots["08"].pk]}).json()["id"]
        lot = LotProjet.objects.get(projet_id=projet_id)
        self.envoyer("patch", f"/api/lots-projet/{lot.pk}", {"code": "4", "intitule": "Menuiseries"})
        self.envoyer("post", f"/api/lots-projet/{lot.pk}/postes", {"titre": "Fenêtres", "unite": "u", "quantite": "2", "prix_unitaire": "10"})
        numeros = [p["numero"] for p in self.client.get(f"/api/lots-projet/{lot.pk}").json()["postes"] if p["genre"] == "OUVRAGE"]
        self.assertTrue(numeros and all(n.startswith("4.") for n in numeros), numeros)
        reponse = self.client.get(f"/api/lots-projet/{lot.pk}/export/dpgf-xlsx")
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("DPGF Lot 4 - Menuiseries", reponse["Content-Disposition"])
