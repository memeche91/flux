import io
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from comptes.models import Utilisateur
from referentiel.models import Lot

from .models import Entreprise


class AnnuaireTests(TestCase):
    def setUp(self):
        self.client.force_login(Utilisateur.objects.create_user("eco", password="mot-de-passe-solide-42", role=Utilisateur.Role.MOE))
        self.lot08 = Lot.objects.get(code="08")

    def json(self, methode, url, donnees=None, attendu=200):
        if methode == "get":
            reponse = self.client.get(url, donnees or {})
        else:
            reponse = getattr(self.client, methode)(url, json.dumps(donnees or {}), content_type="application/json")
        self.assertEqual(reponse.status_code, attendu, reponse.content)
        return reponse.json() if reponse.content else None

    def entreprise(self, **champs):
        donnees = {
            "raison_sociale": "Menuiseries Durand", "siret": "123 456 789 00012", "ville": "Annecy", "code_postal": "74000",
            "email": "contact@durand.fr", "lot_ids": [self.lot08.pk], "specialites": "aluminium, PVC",
            "contacts": [{"nom": "Paul Durand", "fonction": "Gérant", "email": "paul@durand.fr"}, {"nom": "Lise Martin", "principal": True}],
        }
        donnees.update(champs)
        return self.json("post", "/api/entreprises", donnees, attendu=201)

    def test_creation_doublon_et_recherche(self):
        cree = self.entreprise()
        self.assertEqual(cree["siret"], "12345678900012")
        self.assertEqual([c["nom"] for c in cree["contacts"]], ["Lise Martin", "Paul Durand"])  # principal en premier
        self.assertEqual(cree["lots"][0]["code"], "08")
        erreur = self.json("post", "/api/entreprises", {"raison_sociale": "Autre", "siret": "12345678900012"}, attendu=409)
        self.assertIn("Menuiseries Durand", erreur["detail"])
        self.json("post", "/api/entreprises", {"raison_sociale": "Menuiseries Durand", "ville": "Annecy"}, attendu=409)
        self.json("post", "/api/entreprises", {"raison_sociale": "X", "siret": "123"}, attendu=400)
        self.json("post", "/api/entreprises", {"raison_sociale": "X", "email": "pas-une-adresse"}, attendu=400)

        self.entreprise(raison_sociale="Plâtres Martin", siret="", ville="Lyon", code_postal="69001", lot_ids=[], specialites="plaques de plâtre", contacts=[])
        self.assertEqual([e["raison_sociale"] for e in self.json("get", "/api/entreprises", {"lot_id": self.lot08.pk})], ["Menuiseries Durand"])
        self.assertEqual([e["raison_sociale"] for e in self.json("get", "/api/entreprises", {"recherche": "platre"})], ["Plâtres Martin"])
        liste = self.json("get", "/api/entreprises")
        self.assertEqual([e["raison_sociale"] for e in liste], ["Menuiseries Durand", "Plâtres Martin"])  # ordre alphabétique
        self.assertEqual(liste[0]["contact_principal"], "Lise Martin")

        modifiee = self.json("put", f"/api/entreprises/{cree['id']}", {**cree, "lot_ids": [], "actif": False, "contacts": []})
        self.assertFalse(modifiee["actif"])
        self.assertEqual(self.json("get", "/api/entreprises", {"actives": True})[0]["raison_sociale"], "Plâtres Martin")
        self.json("delete", f"/api/entreprises/{cree['id']}", attendu=204)

    def test_import_csv_et_export(self):
        Entreprise.objects.create(raison_sociale="Menuiseries Durand", ville="Annecy", telephone="")
        csv = (
            "Entreprise;Ville;CP;Téléphone;E-mail;Lots;Contact;Remarques\n"
            "Menuiseries Durand;Annecy;74000;04 50 00 00 00;contact@durand.fr;08 - Menuiseries extérieures;Paul Durand;Très réactif\n"
            "Plâtrerie Martin;Lyon;69001;;martin@exemple;11, isolation;;\n"
            ";;;;;;;\n"
            ";Paris;;;;;;\n"
        ).encode("cp1252")
        bilan = self.client.post("/api/entreprises/importer", {"fichier": SimpleUploadedFile("carnet.csv", csv)}).json()
        self.assertEqual((bilan["creees"], bilan["mises_a_jour"]), (1, 1))
        self.assertEqual(bilan["ignorees"], ["Ligne 5 : nom de l'entreprise absent."])
        self.assertEqual(bilan["colonnes"]["code_postal"], "CP")
        durand = Entreprise.objects.get(raison_sociale="Menuiseries Durand")
        self.assertEqual(durand.telephone, "04 50 00 00 00")  # complété, pas écrasé
        self.assertEqual(list(durand.lots.values_list("code", flat=True)), ["08"])
        self.assertEqual(durand.contacts.get().nom, "Paul Durand")
        martin = Entreprise.objects.get(raison_sociale="Plâtrerie Martin")
        self.assertEqual(martin.email, "")  # adresse invalide ignorée
        self.assertEqual(list(martin.lots.values_list("code", flat=True)), ["11"])
        self.assertEqual(martin.specialites, "isolation")

        export = self.client.get("/api/entreprises/export")
        texte = export.content.decode("utf-8-sig")
        self.assertIn("Menuiseries Durand;", texte)
        self.assertIn("08 ", texte)

    def test_import_excel(self):
        from openpyxl import Workbook

        classeur = Workbook()
        feuille = classeur.active
        feuille.append(["Carnet d'adresses du cabinet"])
        feuille.append(["Raison sociale", "Commune", "Mail", "Corps d'état"])
        feuille.append(["Électricité Petit", "Grenoble", "petit@exemple.fr", "Electricité"])
        flux = io.BytesIO()
        classeur.save(flux)
        bilan = self.client.post("/api/entreprises/importer", {"fichier": SimpleUploadedFile("carnet.xlsx", flux.getvalue())}).json()
        self.assertEqual(bilan["creees"], 1)
        entreprise = Entreprise.objects.get()
        self.assertEqual(entreprise.ville, "Grenoble")
        self.assertTrue(entreprise.lots.exists() or entreprise.specialites)

    def test_import_illisible(self):
        reponse = self.client.post("/api/entreprises/importer", {"fichier": SimpleUploadedFile("carnet.csv", b"a;b\n1;2\n")})
        self.assertEqual(reponse.status_code, 400)
        self.assertIn("Colonnes introuvables", reponse.json()["detail"])


class ImportColonnesTests(TestCase):
    def setUp(self):
        self.client.force_login(Utilisateur.objects.create_user("eco", password="mot-de-passe-solide-42", role=Utilisateur.Role.MOE))

    def importer(self, nom, contenu):
        return self.client.post("/api/entreprises/importer", {"fichier": SimpleUploadedFile(nom, contenu)})

    def test_export_outlook_et_adresse_mail(self):
        csv = "Prénom;Nom;Société;Rue (bureau);Ville (bureau);Code postal (bureau);Adresse de messagerie\nPaul;Dupont;Menuiseries Durand;1 rue du Lac;Annecy;74000;paul@durand.fr\n"
        self.assertEqual(self.importer("contacts.csv", csv.encode()).status_code, 200)
        entreprise = Entreprise.objects.get()
        self.assertEqual((entreprise.raison_sociale, entreprise.email, entreprise.adresse), ("Menuiseries Durand", "paul@durand.fr", "1 rue du Lac"))
        self.assertEqual(entreprise.contacts.get().nom, "Dupont")
        csv = "Entreprise;Adresse mail;Téléphone\nPlâtres Martin;martin@exemple.fr;0450000000\n"
        self.importer("carnet.csv", csv.encode())
        self.assertEqual(Entreprise.objects.get(raison_sociale="Plâtres Martin").email, "martin@exemple.fr")

    def test_zeros_initiaux_excel_et_classeur_protege(self):
        from openpyxl import Workbook

        classeur = Workbook()
        classeur.active.append(["Entreprise", "CP", "Téléphone", "Ville"])
        classeur.active.append(["Azur Menuiserie", 6000, 612345678, "Nice"])
        flux = io.BytesIO()
        classeur.save(flux)
        self.importer("carnet.xlsx", flux.getvalue())
        entreprise = Entreprise.objects.get()
        self.assertEqual((entreprise.code_postal, entreprise.telephone), ("06000", "0612345678"))
        reponse = self.importer("protege.xlsx", b"\xd0\xcf\x11\xe0 pas un zip")
        self.assertEqual(reponse.status_code, 400)
        self.assertIn("mot de passe", reponse.json()["detail"])
