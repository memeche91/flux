import json
import shutil
import tempfile

from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from comptes.models import Utilisateur
from dce.models import ConsultationEntreprise, StatutConsultation
from entreprises.models import Entreprise
from projets.models import LotProjet, Projet
from referentiel.models import Lot

from .indices import indice_suivant, superieur
from .models import Document, EspaceChantier, Evenement, Intervenant, StatutVisa, Version

DOSSIER_TEST = tempfile.mkdtemp(prefix="application-ao-ged-")
PDF = b"%PDF-1.4\n% plan\n"


def fichier(nom="plan.pdf", contenu=PDF):
    return SimpleUploadedFile(nom, contenu)


@override_settings(MEDIA_ROOT=DOSSIER_TEST, EMAIL_ACTIF=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", GED_URL_PUBLIQUE="https://ged.cabinet.fr")
class GedTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_TEST, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.moe = Utilisateur.objects.create_user("eco", email="eco@cabinet.fr", password="mot-de-passe-solide-42", role=Utilisateur.Role.MOE)
        self.client.force_login(self.moe)
        self.projet = Projet.objects.create(nom="Groupe scolaire les Tilleuls", maitre_oeuvre="Atelier A")
        self.lot08 = LotProjet.objects.create(projet=self.projet, lot=Lot.objects.get(code="08"), code="08", intitule="Menuiseries extérieures", ordre=1)
        self.lot11 = LotProjet.objects.create(projet=self.projet, lot=Lot.objects.get(code="11"), code="11", intitule="Plâtrerie", ordre=2)
        self.durand = Entreprise.objects.create(raison_sociale="Menuiseries Durand", email="contact@durand.fr")
        self.martin = Entreprise.objects.create(raison_sociale="Plâtrerie Martin", email="martin@platre.fr")
        for entreprise, lot in ((self.durand, self.lot08), (self.martin, self.lot11)):
            ConsultationEntreprise.objects.create(projet=self.projet, lot=lot, entreprise=entreprise, statut=StatutConsultation.RETENUE)

    # --- utilitaires -------------------------------------------------------------
    def json(self, client, methode, url, donnees=None, attendu=200):
        if methode == "get":
            reponse = client.get(url, donnees or {})
        else:
            with self.captureOnCommitCallbacks(execute=True):
                reponse = getattr(client, methode)(url, json.dumps(donnees or {}), content_type="application/json")
        self.assertEqual(reponse.status_code, attendu, reponse.content)
        return reponse.json() if reponse.content else None

    def poster(self, client, url, donnees, attendu=201):
        with self.captureOnCommitCallbacks(execute=True):
            reponse = client.post(url, donnees)
        self.assertEqual(reponse.status_code, attendu, reponse.content)
        return reponse.json()

    def ouvrir(self):
        etat = self.json(self.client, "get", f"/api/projets/{self.projet.pk}/ged")
        self.assertIsNone(etat["espace"])
        suggestions = etat["suggestions"]
        self.assertEqual([(s["nom"], [l["code"] for l in s["lots"]]) for s in suggestions], [("Menuiseries Durand", ["08"]), ("Plâtrerie Martin", ["11"])])
        intervenants = [{"entreprise_id": s["entreprise_id"], "lot_ids": [l["id"] for l in s["lots"]], "emails": s["emails"]} for s in suggestions]
        intervenants.append({"nom": "Ville de Saint-Aubin", "profil": "LECTEUR", "emails": ["moa@ville.fr"]})
        etat = self.json(self.client, "post", f"/api/projets/{self.projet.pk}/ged", {"intervenants": intervenants}, attendu=201)
        self.espace = EspaceChantier.objects.get()
        self.codes = {c["nom"]: c["code"] for c in etat["codes"]}
        return etat

    def portail(self, nom) -> Client:
        client = Client(enforce_csrf_checks=False)
        self.json(client, "post", "/api/ged/acces", {"code": self.codes[nom].lower().replace("-", " ")})
        return client

    def url(self, chemin=""):
        return f"/api/ged/espaces/{self.espace.pk}{chemin}"

    # --- tests ---------------------------------------------------------------------
    def test_indices(self):
        self.assertEqual([indice_suivant(i) for i in (None, "A", "Z", "AZ", "ZZ", "0", "1", "9")], ["A", "B", "AA", "BA", "AAA", "A", "2", "10"])
        self.assertTrue(superieur("A", "0") and superieur("AA", "Z") and superieur("C", "B"))
        self.assertFalse(superieur("B", "B") or superieur("A", "B") or superieur("2", "A"))

    def test_ouverture_codes_et_cloisonnement(self):
        etat = self.ouvrir()
        self.assertEqual(len(etat["espace"]["intervenants"]), 3)
        self.assertEqual(etat["espace"]["emails_moe"], ["eco@cabinet.fr"])
        self.assertRegex(self.codes["Menuiseries Durand"], r"^[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}$")
        self.assertFalse(Intervenant.objects.filter(code_empreinte__contains=self.codes["Menuiseries Durand"]).exists())  # jamais en clair
        self.json(self.client, "post", f"/api/projets/{self.projet.pk}/ged", {}, attendu=409)

        # Documents du cabinet : commun, lot 08, zone MOE.
        commun = self.poster(self.client, self.url("/documents"), {"fichier": fichier("Plan masse.pdf"), "zone": "COMMUN", "categorie": "PLANS"})
        self.assertEqual((commun["reference"], commun["versions"][0]["indice"], commun["versions"][0]["visa"]), ("COM-PLN-001", "A", "SANS_OBJET"))
        self.poster(self.client, self.url("/documents"), {"fichier": fichier("Carnet de détails.pdf"), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "PLANS"})
        self.poster(self.client, self.url("/documents"), {"fichier": fichier("Estimation.xlsx", b"PK"), "zone": "MOE", "categorie": "AUTRES"})
        self.poster(self.client, self.url("/documents"), {"fichier": fichier("page.html", b"<script>"), "zone": "COMMUN", "categorie": "AUTRES"}, attendu=400)

        # Chaque entreprise ne voit que le commun et ses lots ; jamais la zone MOE.
        durand, martin, ville = self.portail("Menuiseries Durand"), self.portail("Plâtrerie Martin"), self.portail("Ville de Saint-Aubin")
        self.assertEqual(sorted(d["reference"] for d in self.json(durand, "get", "/api/ged/portail/documents")), ["08-PLN-001", "COM-PLN-001"])
        self.assertEqual([d["reference"] for d in self.json(martin, "get", "/api/ged/portail/documents")], ["COM-PLN-001"])
        self.assertEqual(sorted(d["reference"] for d in self.json(ville, "get", "/api/ged/portail/documents")), ["08-PLN-001", "COM-PLN-001"])
        cache_moe = Document.objects.get(zone="MOE").versions.get()
        self.assertEqual(durand.get(f"/api/ged/portail/versions/{cache_moe.pk}/fichier").status_code, 404)
        # Les routes du cabinet restent fermées à une session d'entreprise.
        self.assertEqual(durand.get(self.url("/documents")).status_code, 401)
        self.assertEqual(durand.get(f"/api/projets/{self.projet.pk}").status_code, 401)

        # Dépôt de l'entreprise dans son lot (soumis au visa), refusé ailleurs.
        plan = self.poster(durand, "/api/ged/portail/documents", {"fichier": fichier("EXE fenêtres.pdf"), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "EXECUTION", "titre": "Plans d'exécution menuiseries", "indice": "0"})
        self.assertEqual((plan["reference"], plan["versions"][0]["indice"], plan["versions"][0]["visa"]), ("08-EXE-001", "0", "EN_ATTENTE"))
        self.poster(durand, "/api/ged/portail/documents", {"fichier": fichier(), "zone": "LOT", "lot_id": self.lot11.pk, "categorie": "PLANS"}, attendu=403)
        self.poster(durand, "/api/ged/portail/documents", {"fichier": fichier(), "zone": "COMMUN", "categorie": "PLANS"}, attendu=403)
        self.poster(ville, "/api/ged/portail/documents", {"fichier": fichier(), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "PLANS"}, attendu=403)
        self.assertNotIn("08-EXE-001", [d["reference"] for d in self.json(martin, "get", "/api/ged/portail/documents")])

        # Indices stricts : suivant automatique, saisie inférieure refusée.
        avec_a = self.poster(durand, f"/api/ged/portail/documents/{plan['id']}/versions", {"fichier": fichier("EXE fenêtres A.pdf"), "objet": "Reprise des allèges"})
        self.assertEqual([v["indice"] for v in avec_a["versions"]], ["A", "0"])
        self.poster(durand, f"/api/ged/portail/documents/{plan['id']}/versions", {"fichier": fichier(), "indice": "A"}, attendu=400)
        self.poster(martin, f"/api/ged/portail/documents/{plan['id']}/versions", {"fichier": fichier()}, attendu=404)
        commun_doc = Document.objects.get(reference="COM-PLN-001")
        self.poster(durand, f"/api/ged/portail/documents/{commun_doc.pk}/versions", {"fichier": fichier()}, attendu=403)

        # Visa par la maîtrise d'œuvre seulement.
        version_a = Version.objects.get(document_id=plan["id"], indice="A")
        self.poster(durand, f"/api/ged/portail/versions/{version_a.pk}/visa", {"statut": "VSO"}, attendu=403)
        vise = self.poster(self.client, self.url(f"/versions/{version_a.pk}/visa"), {"statut": "VAO", "commentaire": "Préciser les fixations.", "fichier": fichier("visa.pdf")}, attendu=200)
        self.assertEqual((vise["versions"][0]["visa"], vise["versions"][0]["visa_fichier"]), ("VAO", True))
        self.assertEqual(durand.get(f"/api/ged/portail/versions/{version_a.pk}/visa").status_code, 200)

        # Journal : l'entreprise ne voit que ses documents et le commun, sans connexions des autres.
        journal = self.json(martin, "get", "/api/ged/portail/journal")
        self.assertTrue(all("08-" not in e["description"] for e in journal["resultats"]))
        self.assertTrue(all(e["type"] not in ("CONNEXION", "ACCES", "TELECHARGEMENT") for e in journal["resultats"]))
        self.assertGreater(self.json(self.client, "get", self.url("/journal"))["total"], journal["total"])

    def test_notifications_groupees_et_cloisonnees(self):
        self.ouvrir()
        mail.outbox.clear()
        self.poster(self.client, self.url("/documents"), {"fichier": fichier("Plan RDC.pdf"), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "PLANS"})
        destinataires = sorted(a for m in mail.outbox for a in m.to)
        # Lot 08 : Durand, le maître d'ouvrage (lecture), la MOE ; pas Martin (lot 11).
        self.assertEqual(destinataires, ["contact@durand.fr", "eco@cabinet.fr", "moa@ville.fr"])
        message = next(m for m in mail.outbox if m.to == ["contact@durand.fr"])
        self.assertIn("https://ged.cabinet.fr/ged", message.body)
        self.assertIn("08-PLN-001", message.body)
        mail.outbox.clear()
        durand = self.portail("Menuiseries Durand")
        self.poster(durand, "/api/ged/portail/documents", {"fichier": fichier("FT menuiserie.pdf"), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "FICHES"})
        destinataires = sorted(a for m in mail.outbox for a in m.to)
        self.assertNotIn("contact@durand.fr", destinataires)  # pas pour sa propre action
        self.assertIn("soumis au visa", next(m for m in mail.outbox if m.to == ["eco@cabinet.fr"]).body)
        self.assertFalse(Evenement.objects.filter(a_notifier=True).exists())
        # Notifications coupées : rien n'est envoyé.
        self.json(self.client, "patch", self.url(), {"notifications": False})
        mail.outbox.clear()
        self.poster(self.client, self.url("/documents"), {"fichier": fichier(), "zone": "COMMUN", "categorie": "PLANS"})
        self.assertEqual(mail.outbox, [])

    def test_codes_revocation_limitation_et_espace_clos(self):
        self.ouvrir()
        durand = self.portail("Menuiseries Durand")
        intervenant = Intervenant.objects.get(nom="Menuiseries Durand")
        mail.outbox.clear()
        nouveau = self.json(self.client, "post", f"/api/ged/intervenants/{intervenant.pk}/code", {"envoyer": True})
        self.assertTrue(nouveau["envoye"])
        self.assertIn(nouveau["code"], mail.outbox[0].body)
        # L'ancien code et la session ouverte avec lui ne fonctionnent plus.
        self.assertEqual(durand.get("/api/ged/portail/documents").status_code, 401)
        client = Client()
        self.json(client, "post", "/api/ged/acces", {"code": self.codes["Menuiseries Durand"]}, attendu=401)
        self.codes["Menuiseries Durand"] = nouveau["code"]
        durand = self.portail("Menuiseries Durand")
        # Accès désactivé.
        self.json(self.client, "patch", f"/api/ged/intervenants/{intervenant.pk}", {"actif": False})
        self.assertEqual(durand.get("/api/ged/portail/documents").status_code, 401)
        # Limitation des essais.
        for _ in range(9):  # dixième échec avec l'ancien code ci-dessus
            self.json(client, "post", "/api/ged/acces", {"code": "AAAA-BBBB-CCCC"}, attendu=401)
        self.json(client, "post", "/api/ged/acces", {"code": self.codes["Plâtrerie Martin"]}, attendu=429)
        cache.clear()
        martin = self.portail("Plâtrerie Martin")
        # Espace clos : plus d'accès pour les intervenants.
        EspaceChantier.objects.update(statut="CLOS")
        self.assertEqual(martin.get("/api/ged/portail/documents").status_code, 401)

    def test_fichiers_servis_sans_risque_et_registre(self):
        from openpyxl import load_workbook
        import io

        self.ouvrir()
        pdf = self.poster(self.client, self.url("/documents"), {"fichier": fichier("Plan.pdf"), "zone": "COMMUN", "categorie": "PLANS"})
        dwg = self.poster(self.client, self.url("/documents"), {"fichier": fichier("Plan.dwg", b"AC1032"), "zone": "COMMUN", "categorie": "PLANS"})
        reponse = self.client.get(self.url(f"/versions/{pdf['versions'][0]['id']}/fichier"))
        self.assertEqual((reponse["Content-Type"], reponse["Content-Disposition"].split(";")[0]), ("application/pdf", "inline"))
        reponse = self.client.get(self.url(f"/versions/{dwg['versions'][0]['id']}/fichier"))
        self.assertEqual((reponse["Content-Type"], reponse["Content-Disposition"].split(";")[0]), ("application/octet-stream", "attachment"))
        # Annulation : le document reste dans l'historique.
        annule = self.json(self.client, "patch", self.url(f"/documents/{dwg['id']}"), {"annule": True, "motif_annulation": "Remplacé par le plan PDF"})
        self.assertTrue(annule["annule"])
        self.poster(self.client, self.url(f"/documents/{dwg['id']}/versions"), {"fichier": fichier("Plan B.dwg", b"AC1032")}, attendu=403)
        classeur = load_workbook(io.BytesIO(self.client.get(self.url("/registre.xlsx")).content))
        valeurs = [c for ligne in classeur.active.iter_rows(values_only=True) for c in ligne if c]
        self.assertIn("COM-PLN-002", valeurs)
        self.assertIn("Annulé", valeurs)
        # Suppression du projet : fichiers effacés du disque.
        from pathlib import Path

        chemin = Path(Version.objects.get(document_id=pdf["id"]).fichier.path)
        self.assertTrue(chemin.exists())
        with self.captureOnCommitCallbacks(execute=True):
            self.projet.delete()
        self.assertFalse(chemin.exists())

    def test_visa_en_retard(self):
        import datetime

        from django.utils import timezone

        self.ouvrir()
        durand = self.portail("Menuiseries Durand")
        plan = self.poster(durand, "/api/ged/portail/documents", {"fichier": fichier(), "zone": "LOT", "lot_id": self.lot08.pk, "categorie": "PLANS"})
        Version.objects.filter(document_id=plan["id"]).update(deposee_le=timezone.now() - datetime.timedelta(days=16))
        etat = self.json(self.client, "get", f"/api/projets/{self.projet.pk}/ged")
        self.assertEqual(etat["espace"]["statistiques"]["en_attente_visa"], 1)
        document = self.json(self.client, "get", self.url("/documents"))[0]
        self.assertTrue(document["versions"][0]["visa_en_retard"])
        self.assertEqual(StatutVisa.EN_ATTENTE, document["versions"][0]["visa"])
